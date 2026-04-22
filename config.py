import os
import logging

# ─── 串口配置 ─────────────────────────────────────────────────────────────────
SERIAL_BAUD = 115200

def _auto_detect_serial_port() -> str:
    """自动检测 CH340 串口"""
    try:
        import serial.tools.list_ports
        ports = serial.tools.list_ports.comports()
        for p in ports:
            if 'CH340' in p.description or (p.vid == 0x1A86 and p.pid == 0x7523):
                logging.info(f'自动检测到 CH340 串口: {p.device} ({p.description})')
                return p.device
        # 回退：列出所有可用端口
        for p in ports:
            if 'USB' in p.description.upper() or 'SERIAL' in p.description.upper():
                logging.info(f'回退匹配串口: {p.device} ({p.description})')
                return p.device
    except ImportError:
        pass
    except Exception as e:
        logging.warning(f'串口自动检测失败: {e}')
    return 'COM4'  # 默认值

SERIAL_PORT = _auto_detect_serial_port()

# ─── 摄像头 ──────────────────────────────────────────────────────────────────
# 0 = 系统默认摄像头（笔记本内置或第一个USB摄像头）
CAMERA_INDEX = 0

# ─── 路径 ────────────────────────────────────────────────────────────────────
BASE_DIR       = os.path.dirname(os.path.abspath(__file__))
DB_PATH        = os.path.join(BASE_DIR, 'stamp_robot.db')
AUDIT_IMAGE_DIR = os.path.join(BASE_DIR, 'audit_images')
EXAMPLE_IMAGE_DIR = os.path.join(BASE_DIR, 'example_images')

# ─── Web ─────────────────────────────────────────────────────────────────────
SECRET_KEY = 'stamp_robot_mec202_secret'
WEB_HOST   = '0.0.0.0'
WEB_PORT   = 5001

# ─── 文档规则 ─────────────────────────────────────────────────────────────────
# 不同文件类型需要的必填字段
REQUIRED_FIELDS = {
    'leave':    ['姓名', '学号', '日期', '原因'],
    'expense':  ['姓名', '学号', '日期', '金额'],
    'cert':     ['姓名', '学号', '日期'],
    'general':  ['姓名', '日期'],
}

# 签名关键词（OCR扫到这些词说明有签名栏）
SIGNATURE_KEYWORDS = ['签名', '签字', '审批', '审核人', '负责人', '盖章']

# ─── 文档管理系统（DMS）集成 ──────────────────────────────────────────────────
# 如果学校没有DMS，设为空字符串即可，系统会跳过上传
DMS_BASE_URL = ''
DMS_API_KEY  = ''

# ─── 硬件仿真模式 ─────────────────────────────────────────────────────────────
SIMULATION_MODE = False

# ─── 纸张检测 ─────────────────────────────────────────────────────────────────
# False = 跳过纸张检测，直接拍照识别（固定纸张位置时使用）
PAPER_DETECTION_ENABLED = False
