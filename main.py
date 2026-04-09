"""
main.py - 文档处理主流程

DocumentProcessor 封装了从拍照到盖章的完整流程：
  1. 拍摄盖章前图片
  2. 扫描二维码，识别文件类型
  3. OCR提取字段
  4. 多页完整性检测
  5. 六项规则验证
  6. 决策：盖章 / 推入人工复审 / 直接拒绝
  7. 拍摄盖章后图片
  8. 写审计日志
  9. 上传至DMS（如已配置）
"""

import logging
from vision.camera import Camera
from vision.ocr import extract_fields
from vision.qr_scanner import scan_qr
from vision.page_counter import check_page_completeness
from validator.rules import DocumentValidator
from hardware.stamp import StampController
from database.audit import log_action
from database import review_queue as rq
from integration.dms_client import DMSClient

logger = logging.getLogger(__name__)


class DocumentProcessor:
    """单例：在 Web 应用生命周期内复用摄像头和串口连接"""

    def __init__(self):
        self.camera    = Camera()
        self.stamper   = StampController()
        self.validator = DocumentValidator()
        self.dms       = DMSClient()
        logger.info('DocumentProcessor 已初始化')

    def process(self, operator_id: str) -> dict:
        """
        执行完整文档处理流程。
        返回值格式：
          { status: 'approved' | 'rejected' | 'pending_review' | 'error',
            fields: {...}, errors: [...], warnings: [...] }
        """
        # ── 步骤1：拍摄原始图（盖章前）────────────────────────────────
        before_img = self.camera.capture_timestamped('before')
        logger.info(f'[{operator_id}] 已拍摄原始图: {before_img}')

        # ── 步骤2：二维码扫描，识别文件类型 ───────────────────────────
        qr_content, doc_type = scan_qr(before_img)
        logger.info(f'[{operator_id}] 文件类型: {doc_type}, QR: {qr_content}')

        # ── 步骤3：OCR识别 ─────────────────────────────────────────────
        fields, full_text = extract_fields(before_img)
        logger.info(f'[{operator_id}] 识别字段: {fields}')

        # ── 步骤4：多页完整性检测 ──────────────────────────────────────
        page_ok, page_msg = check_page_completeness(before_img)
        if not page_ok:
            log_action(operator_id, doc_type, qr_content, fields,
                       'REJECTED', [page_msg], before_img, before_img)
            return {
                'status': 'rejected',
                'fields': fields,
                'errors': [page_msg],
                'warnings': [],
            }

        # ── 步骤5：规则验证 ────────────────────────────────────────────
        v_result = self.validator.validate(fields, full_text, doc_type)

        # ── 步骤6：决策 ────────────────────────────────────────────────
        if not v_result.passed:
            # 有硬错误 → 直接拒绝
            logger.info(f'[{operator_id}] 拒绝: {v_result.hard_errors}')
            log_action(operator_id, doc_type, qr_content, fields,
                       'REJECTED', v_result.hard_errors, before_img, before_img)
            return {
                'status': 'rejected',
                'fields': fields,
                'errors': v_result.hard_errors,
                'warnings': [],
            }

        if v_result.needs_review:
            # 有软警告 → 推入人工复审队列
            logger.info(f'[{operator_id}] 推入复审: {v_result.soft_warnings}')
            rq.add_to_queue(operator_id, doc_type, fields,
                            v_result.soft_warnings, before_img)
            log_action(operator_id, doc_type, qr_content, fields,
                       'PENDING_REVIEW', v_result.soft_warnings,
                       before_img, before_img)
            return {
                'status': 'pending_review',
                'fields': fields,
                'errors': [],
                'warnings': v_result.soft_warnings,
            }

        # ── 步骤7：盖章 ────────────────────────────────────────────────
        logger.info(f'[{operator_id}] 验证通过，开始盖章')
        self.stamper.stamp()

        # ── 步骤8：拍摄盖章后图片 ──────────────────────────────────────
        after_img = self.camera.capture_timestamped('after')
        logger.info(f'[{operator_id}] 盖章后图片: {after_img}')

        # ── 步骤9：上传DMS ─────────────────────────────────────────────
        metadata = {'operator_id': operator_id, 'doc_type': doc_type, **fields}
        dms_doc_id = self.dms.upload_stamped_doc(after_img, metadata)

        # ── 步骤10：写审计日志 ─────────────────────────────────────────
        log_action(operator_id, doc_type, qr_content, fields,
                   'APPROVED', [], before_img, after_img, dms_doc_id)

        logger.info(f'[{operator_id}] 流程完成，dms_doc_id={dms_doc_id}')
        return {
            'status': 'approved',
            'fields': fields,
            'errors': [],
            'warnings': [],
        }

    def shutdown(self):
        self.camera.release()
        self.stamper.close()


# ── 直接运行时启动 Web 服务 ────────────────────────────────────────────────
if __name__ == '__main__':
    import sys
    import os

    # 把项目根目录加入 sys.path（从任意目录启动时也能正确 import）
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

    from database.models import init_db, seed_demo_data
    init_db()
    seed_demo_data()
    print('数据库已初始化')
    print('演示账号: admin / admin123')
    print()

    # 启动 Flask
    from web.app import app
    from config import WEB_HOST, WEB_PORT
    print(f'Web 服务启动中... 访问 http://127.0.0.1:{WEB_PORT}')
    app.run(host=WEB_HOST, port=WEB_PORT, debug=False)
