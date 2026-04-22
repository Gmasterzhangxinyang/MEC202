import cv2
import logging
import os
import threading
import time
from datetime import datetime
from config import CAMERA_INDEX, AUDIT_IMAGE_DIR

logger = logging.getLogger(__name__)


def open_camera(index):
    """打开摄像头（仅用于枚举列表）"""
    cap = cv2.VideoCapture(index)
    if not cap.isOpened():
        return None
    cap.set(cv2.CAP_PROP_AUTOFOCUS, 1)
    return cap


class SharedCamera:
    """单例摄像头 + 后台线程帧缓冲，避免多 VideoCapture 冲突"""
    _instance = None

    def __init__(self, index=0):
        self._index = index
        self._cap = open_camera(index)
        if self._cap is None:
            raise RuntimeError(f'无法打开摄像头（index={index}）')
        self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
        self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)
        self._frame_lock = threading.Lock()
        self._latest_frame = None
        self._running = True
        self._thread = threading.Thread(target=self._read_loop, daemon=True)
        self._thread.start()
        for _ in range(5):
            time.sleep(0.2)
        w = int(self._cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h = int(self._cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        logger.info(f'摄像头已启动: index={index}, 分辨率={w}x{h}')

    def _read_loop(self):
        while self._running:
            ret, frame = self._cap.read()
            if ret:
                with self._frame_lock:
                    self._latest_frame = frame
            else:
                time.sleep(0.01)

    def get_frame(self):
        """返回最新帧副本（给视频流用）"""
        with self._frame_lock:
            if self._latest_frame is not None:
                return self._latest_frame.copy()
        return None

    def capture(self, filename: str) -> str:
        """从帧缓冲取当前帧保存到文件"""
        with self._frame_lock:
            if self._latest_frame is not None:
                frame = self._latest_frame.copy()
            else:
                raise RuntimeError('摄像头尚未就绪，无可用帧')
        os.makedirs(AUDIT_IMAGE_DIR, exist_ok=True)
        path = os.path.join(AUDIT_IMAGE_DIR, filename)
        cv2.imwrite(path, frame, [cv2.IMWRITE_JPEG_QUALITY, 95])
        logger.info(f'已保存图片: {path}')
        return path

    def capture_timestamped(self, tag: str) -> str:
        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        return self.capture(f'{ts}_{tag}.jpg')

    def get_resolution(self) -> tuple:
        w = int(self._cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h = int(self._cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        return w, h

    @classmethod
    def get_instance(cls, index=None):
        if cls._instance is None:
            idx = index if index is not None else CAMERA_INDEX
            cls._instance = cls(idx)
        return cls._instance

    @classmethod
    def reset(cls):
        if cls._instance is not None:
            cls._instance._running = False
            try:
                cls._instance._cap.release()
            except Exception:
                pass
            cls._instance = None
