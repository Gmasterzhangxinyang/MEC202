import re
from vision.ocr import _get_engine


def check_page_completeness(image_path: str) -> tuple[bool, str]:
    """
    检测文件是否包含"第X页/共Y页"标注，判断是否提交完整。
    如果文件没有页码标注，视为单页文件，返回通过。
    """
    engine = _get_engine()
    result = engine.ocr(image_path, cls=True)
    if not result or not result[0]:
        return True, 'OK'

    full_text = '\n'.join([item[1][0] for item in result[0]])

    # 支持格式："第1页/共3页"、"Page 1 of 3"、"1/3"
    m = re.search(r'第\s*(\d+)\s*页[，,\s/]*共\s*(\d+)\s*页', full_text)
    if m:
        current = int(m.group(1))
        total   = int(m.group(2))
        if current < total:
            return False, f'文件共 {total} 页，当前仅提交第 {current} 页，请提交完整文件'
        return True, 'OK'

    # 英文页码
    m = re.search(r'[Pp]age\s*(\d+)\s*of\s*(\d+)', full_text)
    if m:
        current = int(m.group(1))
        total   = int(m.group(2))
        if current < total:
            return False, f'文件共 {total} 页，当前仅提交第 {current} 页'
        return True, 'OK'

    # 没有页码标注 → 视为单页，通过
    return True, 'OK'
