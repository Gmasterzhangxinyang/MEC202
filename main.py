import os
os.environ['PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK'] = 'True'
os.environ['FLAGS_use_mkldnn'] = '0'

import logging
import sqlite3
import cv2
import numpy as np
from vision.ocr import extract_fields, extract_fields_with_positions
from vision.qr_scanner import scan_qr
from vision.page_counter import check_page_completeness
from vision.classifier import classify_document
from validator.rules import DocumentValidator
from hardware.arm import ArmController
from hardware.arm import compute_pwms_at_position, load_calibration
from database.audit import log_action
from database import review_queue as rq
from config import DB_PATH, PAPER_DETECTION_ENABLED

logger = logging.getLogger(__name__)

_PAPER_THRESHOLD = 0.3


def _has_paper(image_path: str) -> bool:
    img = cv2.imread(image_path)
    if img is None:
        return False
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    white_ratio = np.sum(gray > 180) / gray.size
    return white_ratio > _PAPER_THRESHOLD


class DocumentProcessor:
    def __init__(self):
        from vision.camera import SharedCamera
        self.camera   = SharedCamera.get_instance()
        self.arm      = ArmController()
        self.validator = DocumentValidator()
        logger.info('DocumentProcessor 已初始化')

    def process(self, operator_id: str) -> dict:
        before_img = self.camera.capture_timestamped('before')
        logger.info(f'[{operator_id}] 已拍摄图片: {before_img}')

        if PAPER_DETECTION_ENABLED and not _has_paper(before_img):
            logger.info(f'[{operator_id}] 未检测到纸张，跳过盖章')
            return {'status': 'rejected', 'errors': ['未检测到纸张'], 'warnings': []}

        # QR 扫描 → 识别文档类型
        qr_content, doc_type = scan_qr(before_img)
        logger.info(f'[{operator_id}] QR: {qr_content}, 类型: {doc_type}')

        # OCR 识别（带位置信息）
        fields, full_text, boxes = extract_fields_with_positions(before_img)
        logger.info(f'[{operator_id}] 识别字段: {fields}')

        # 自动分类（QR 未识别具体类型时）
        if doc_type == 'general' or doc_type is None:
            classified_code, confidence = classify_document(full_text, fields)
            if classified_code:
                doc_type = classified_code
                logger.info(f'[{operator_id}] 自动分类为: {doc_type} (置信度: {confidence:.2f})')
            else:
                doc_type = 'pending'
                logger.info(f'[{operator_id}] 无法自动分类，标记为 pending')

        if doc_type == 'pending':
            pending_msg = '无法自动识别文件类型，请管理员手动分类'
            queue_id = rq.add_to_queue(operator_id, 'pending', fields, [pending_msg], before_img, full_text)
            log_action(operator_id, 'pending', qr_content, fields,
                       'PENDING_REVIEW', [pending_msg], before_img, before_img, ocr_text=full_text)
            return {
                'status': 'pending_review',
                'review_id': queue_id,
                'fields': fields,
                'errors': [],
                'warnings': [pending_msg],
            }

        # 多页完整性检测
        page_ok, page_msg = check_page_completeness(before_img)
        if not page_ok:
            log_action(operator_id, doc_type, qr_content, fields,
                       'REJECTED', [page_msg], before_img, before_img, ocr_text=full_text)
            return {
                'status': 'rejected',
                'fields': fields,
                'errors': [page_msg],
                'warnings': [],
            }

        # 规则验证
        v_result = self.validator.validate(fields, full_text, doc_type)

        if not v_result.passed:
            logger.info(f'[{operator_id}] 拒绝: {v_result.hard_errors}')
            log_action(operator_id, doc_type, qr_content, fields,
                       'REJECTED', v_result.hard_errors, before_img, before_img, ocr_text=full_text)
            return {
                'status': 'rejected',
                'fields': fields,
                'errors': v_result.hard_errors,
                'warnings': [],
            }

        if v_result.needs_review:
            logger.info(f'[{operator_id}] 推入复审: {v_result.soft_warnings}')
            queue_id = rq.add_to_queue(operator_id, doc_type, fields,
                            v_result.soft_warnings, before_img, full_text)
            log_action(operator_id, doc_type, qr_content, fields,
                       'PENDING_REVIEW', v_result.soft_warnings,
                       before_img, before_img, ocr_text=full_text)
            return {
                'status': 'pending_review',
                'review_id': queue_id,
                'fields': fields,
                'errors': [],
                'warnings': v_result.soft_warnings,
            }

        # 盖章
        logger.info(f'[{operator_id}] 验证通过，开始盖章')
        self._do_stamp(before_img, boxes)

        after_img = self.camera.capture_timestamped('after')
        log_action(operator_id, doc_type, qr_content, fields,
                   'APPROVED', [], before_img, after_img, ocr_text=full_text)

        logger.info(f'[{operator_id}] 盖章完成')
        return {'status': 'approved', 'errors': [], 'warnings': []}

    def process_review_stamping(self, review_id: int, operator_id: str) -> dict:
        """复审通过后的验证盖章流程"""
        import ast
        from vision.comparator import verify_document
        from vision.ocr import extract_fields_with_positions, find_stamp_target

        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            'SELECT * FROM review_queue WHERE id=? AND status="approved"',
            (review_id,)
        ).fetchone()
        conn.close()

        if not row:
            return {'status': 'error', 'message': '记录不存在或未批准'}

        original_img = row['image_path']
        original_fields = ast.literal_eval(row['doc_fields']) if row['doc_fields'] else {}

        new_img = self.camera.capture_timestamped('review_verify')
        logger.info(f'[{operator_id}] 复审验证拍照: {new_img}')

        if PAPER_DETECTION_ENABLED and not _has_paper(new_img):
            return {'status': 'rejected', 'errors': ['未检测到纸张'], 'warnings': []}

        new_fields, new_full_text, boxes = extract_fields_with_positions(new_img)

        passed, messages = verify_document(original_img, new_img, original_fields, new_fields)

        if not passed:
            logger.info(f'[{operator_id}] 复审验证失败: {messages}')
            log_action(operator_id, row['doc_type'] or 'review', None,
                       new_fields, 'REJECTED', messages, new_img, new_img, ocr_text=new_full_text)
            return {
                'status': 'rejected',
                'errors': messages,
                'warnings': [],
            }

        logger.info(f'[{operator_id}] 复审验证通过，开始盖章')
        self._do_stamp(new_img, boxes)

        after_img = self.camera.capture_timestamped('after')
        log_action(operator_id, row['doc_type'] or 'review', None,
                   new_fields, 'APPROVED', [], new_img, after_img, ocr_text=new_full_text)
        rq.mark_stamped(review_id)

        logger.info(f'[{operator_id}] 复审盖章完成')
        return {'status': 'approved', 'errors': [], 'warnings': []}

    def _do_stamp(self, image_path: str, boxes: list | None = None):
        """执行盖章，优先使用标定数据精确定位"""
        cal = load_calibration()
        if cal.get('corners') and boxes:
            from vision.ocr import find_stamp_target
            stamp_pos = find_stamp_target(boxes)
            if stamp_pos:
                logger.info(f'盖章位置 (归一化): x={stamp_pos[0]:.3f}, y={stamp_pos[1]:.3f}')
                pwms = compute_pwms_at_position(stamp_pos[0], stamp_pos[1], cal)
                logger.info(f'盖章 PWM: {pwms}')
                self.arm.stamp_at(pwms)
                return
            logger.warning('未找到盖章目标位置，使用默认位置')
        else:
            logger.info(f'标定/boxes 状态: corners={bool(cal.get("corners"))}, boxes={bool(boxes)}')
        self.arm.stamp_at({0: 1500, 2: 1500})

    def shutdown(self):
        from vision.camera import SharedCamera
        SharedCamera.reset()
        self.arm.close()


if __name__ == '__main__':
    import sys
    import os

    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

    from database.models import init_db, seed_demo_data, seed_default_templates
    init_db()
    seed_demo_data()
    seed_default_templates()
    print('数据库已初始化')
    print('演示账号: admin / admin123')
    print()

    from web.app import app
    from config import WEB_HOST, WEB_PORT
    print(f'Web 服务启动中... 访问 http://127.0.0.1:{WEB_PORT}')
    app.run(host=WEB_HOST, port=WEB_PORT, debug=False)
