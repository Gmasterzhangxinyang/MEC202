import cv2
import os
import time
from datetime import datetime
from config import CAMERA_INDEX, AUDIT_IMAGE_DIR


class Camera:
    def __init__(self):
        self.cap = None
        self._init_camera()

    def _init_camera(self):
        self.cap = cv2.VideoCapture(CAMERA_INDEX)
        if not self.cap.isOpened():
            raise RuntimeError(
                f'无法打开摄像头（index={CAMERA_INDEX}）。\n'
                '请检查：1) USB摄像头是否插好  2) config.py 中 CAMERA_INDEX 是否正确'
            )
        # 预热：前3帧丢弃（摄像头刚开自动曝光不稳定）
        for _ in range(3):
            self.cap.read()
            time.sleep(0.1)

    def capture(self, filename: str) -> str:
        """
        拍一张照片，保存到 audit_images/ 目录。
        返回保存的完整路径。
        """
        os.makedirs(AUDIT_IMAGE_DIR, exist_ok=True)
        ret, frame = self.cap.read()
        if not ret:
            raise RuntimeError('摄像头读取失败，请检查连接。')

        path = os.path.join(AUDIT_IMAGE_DIR, filename)
        cv2.imwrite(path, frame)
        return path

    def capture_timestamped(self, tag: str) -> str:
        """用时间戳自动命名并拍照，tag 为 'before' 或 'after'"""
        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f'{ts}_{tag}.jpg'
        return self.capture(filename)

    def release(self):
        if self.cap:
            self.cap.release()

    def __del__(self):
        self.release()
