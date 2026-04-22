import cv2
import numpy as np


def compare_images_ssim(img_path_a: str, img_path_b: str) -> float:
    """计算两张图片的 SSIM 相似度 (0~1)。"""
    a = cv2.imread(img_path_a, cv2.IMREAD_GRAYSCALE)
    b = cv2.imread(img_path_b, cv2.IMREAD_GRAYSCALE)
    if a is None or b is None:
        return 0.0
    h = min(a.shape[0], b.shape[0])
    w = min(a.shape[1], b.shape[1])
    a = cv2.resize(a, (w, h))
    b = cv2.resize(b, (w, h))

    from skimage.metrics import structural_similarity as ssim
    score, _ = ssim(a, b, full=True)
    return score


def compare_ocr_fields(fields_a: dict, fields_b: dict) -> tuple:
    """比对两组 OCR 字段。返回 (passed, mismatches)。"""
    mismatches = []
    all_keys = set(fields_a.keys()) | set(fields_b.keys())
    for key in all_keys:
        va = fields_a.get(key, '')
        vb = fields_b.get(key, '')
        if va and vb and va != vb:
            mismatches.append(f'字段「{key}」不一致：原「{va}」vs 现「{vb}」')
    return len(mismatches) == 0, mismatches


def verify_document(original_img: str, new_img: str,
                    original_fields: dict, new_fields: dict,
                    ssim_threshold: float = 0.85) -> tuple:
    """完整验证：图像相似度 + OCR 字段比对。返回 (passed, messages)。"""
    messages = []
    sim = compare_images_ssim(original_img, new_img)
    messages.append(f'图像相似度: {sim:.2%}')
    if sim < ssim_threshold:
        messages.append(f'图像差异过大（阈值 {ssim_threshold:.0%}），可能不是同一份文件')
    fields_ok, field_msgs = compare_ocr_fields(original_fields, new_fields)
    messages.extend(field_msgs)
    return sim >= ssim_threshold and fields_ok, messages
