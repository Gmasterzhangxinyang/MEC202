import cv2
from pyzbar.pyzbar import decode


# 文件类型映射：二维码内容前缀 → 内部类型代码
_QR_TYPE_MAP = {
    'LEAVE':   'leave',
    'EXPENSE': 'expense',
    'CERT':    'cert',
}


def scan_qr(image_path: str) -> tuple[str | None, str]:
    """
    扫描图片中的二维码/条形码。
    返回:
        qr_raw   - 二维码原始文本（无二维码则为 None）
        doc_type - 识别出的文件类型（无法识别则为 'general'）
    """
    img = cv2.imread(image_path)
    codes = decode(img)

    if not codes:
        return None, 'general'

    qr_raw = codes[0].data.decode('utf-8').strip()
    doc_type = 'general'

    for prefix, dtype in _QR_TYPE_MAP.items():
        if qr_raw.upper().startswith(prefix):
            doc_type = dtype
            break

    return qr_raw, doc_type
