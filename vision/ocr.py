import os
os.environ['FLAGS_use_mkldnn'] = '0'

import re
from paddleocr import PaddleOCR

_ocr_engine = None


def _get_engine():
    global _ocr_engine
    if _ocr_engine is None:
        _ocr_engine = PaddleOCR(use_angle_cls=True, lang='ch', show_log=False, enable_mkldnn=False)
    return _ocr_engine


def extract_fields(image_path: str) -> tuple[dict, str]:
    """
    对图片执行OCR，提取关键字段。
    返回:
        fields   - 字典，包含识别出的字段（姓名/学号/日期/金额等）
        full_text - 全部OCR文本拼接（供验证模块做关键词检索）
    """
    engine = _get_engine()
    result = engine.ocr(image_path, cls=True)

    lines = []
    if result and result[0]:
        lines = [item[1][0] for item in result[0]]

    full_text = '\n'.join(lines)
    fields = _parse_fields(full_text)
    return fields, full_text


def _parse_fields(text: str) -> dict:
    fields = {}

    # 姓名：支持"姓名：张三" / "姓名:张三" 两种格式
    m = re.search(r'姓\s*名\s*[：:]\s*(\S{2,5})', text)
    if m:
        fields['姓名'] = m.group(1)

    # 学号/工号（6-12位数字）
    m = re.search(r'(?:学号|工号|学生编号)\s*[：:]\s*(\d{6,12})', text)
    if m:
        fields['学号'] = m.group(1)
    else:
        # 降级：直接找连续8-12位数字
        m = re.search(r'\b(\d{8,12})\b', text)
        if m:
            fields['学号'] = m.group(1)

    # 日期（多种格式：2024-01-01 / 2024年1月1日 / 2024/01/01）
    m = re.search(
        r'(\d{4})\s*[-年/]\s*(\d{1,2})\s*[-月/]\s*(\d{1,2})\s*日?',
        text
    )
    if m:
        y, mo, d = m.group(1), m.group(2).zfill(2), m.group(3).zfill(2)
        fields['日期'] = f'{y}-{mo}-{d}'

    # 金额（含"元"或"¥"符号）
    m = re.search(r'(?:金额|合计|总计)\s*[：:￥¥]?\s*(\d+(?:\.\d{1,2})?)\s*元?', text)
    if m:
        fields['金额'] = m.group(1)

    # 原因/事由（请假、报销等）
    m = re.search(r'(?:原因|事由|申请原因)\s*[：:]\s*(.{2,30})', text)
    if m:
        fields['原因'] = m.group(1).strip()

    return fields


def extract_fields_with_positions(image_path: str) -> tuple:
    """与 extract_fields 相同，但额外返回 OCR 检测框列表（含像素坐标）。"""
    engine = _get_engine()
    result = engine.ocr(image_path, cls=True)

    lines = []
    boxes = []
    if result and result[0]:
        for item in result[0]:
            text = item[1][0]
            bbox = item[0]
            lines.append(text)
            pts = [(int(p[0]), int(p[1])) for p in bbox]
            cx = sum(p[0] for p in pts) // 4
            cy = sum(p[1] for p in pts) // 4
            boxes.append({"text": text, "box": pts, "center": (cx, cy)})

    full_text = '\n'.join(lines)
    fields = _parse_fields(full_text)
    return fields, full_text, boxes


def find_stamp_target(boxes: list, keywords: list | None = None) -> tuple | None:
    """从 OCR 检测框中找到盖章目标位置（归一化坐标）"""
    if keywords is None:
        keywords = ['盖章处', '审批人', '签名', '签字', '审核人', '负责人']

    if not boxes:
        return None

    max_x = max(b['center'][0] for b in boxes)
    max_y = max(b['center'][1] for b in boxes)
    if max_x == 0 or max_y == 0:
        return None

    for kw in keywords:
        for b in boxes:
            if kw in b['text']:
                cx, cy = b['center']
                xs = [p[0] for p in b['box']]
                box_w = max(xs) - min(xs)
                if kw == '盖章处':
                    stamp_x, stamp_y = cx, cy
                else:
                    stamp_x = cx + int(box_w * 0.5) + 60
                    stamp_y = cy
                return (stamp_x / max_x, stamp_y / max_y)

    return (0.82, 0.85)
