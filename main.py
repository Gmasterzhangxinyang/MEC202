import logging
import cv2
import numpy as np
from vision.camera import Camera
from hardware.stamp import StampController
from database.audit import log_action

logger = logging.getLogger(__name__)

# 检测到纸张的最小白色像素占比（0~1），低于此值认为没有纸
_PAPER_THRESHOLD = 0.3


def _has_paper(image_path: str) -> bool:
    img = cv2.imread(image_path)
    if img is None:
        return False
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    # 亮度高于180的像素视为白纸区域
    white_ratio = np.sum(gray > 180) / gray.size
    return white_ratio > _PAPER_THRESHOLD


class DocumentProcessor:
    def __init__(self):
        self.camera  = Camera()
        self.stamper = StampController()
        logger.info('DocumentProcessor 已初始化')

    def process(self, operator_id: str) -> dict:
        before_img = self.camera.capture_timestamped('before')
        logger.info(f'[{operator_id}] 已拍摄图片: {before_img}')

        if not _has_paper(before_img):
            logger.info(f'[{operator_id}] 未检测到纸张，跳过盖章')
            return {'status': 'rejected', 'errors': ['未检测到纸张'], 'warnings': []}

        logger.info(f'[{operator_id}] 检测到纸张，开始盖章')
        self.stamper.stamp()

        after_img = self.camera.capture_timestamped('after')
        log_action(operator_id, 'general', None, {}, 'APPROVED', [], before_img, after_img)

        logger.info(f'[{operator_id}] 盖章完成')
        return {'status': 'approved', 'errors': [], 'warnings': []}

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
