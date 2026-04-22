import time
import json
import os
import logging
from config import SERIAL_PORT, SERIAL_BAUD, SIMULATION_MODE, BASE_DIR

logger = logging.getLogger(__name__)

SERVO_NAMES = {0: '底盘', 1: '大臂', 2: '小臂', 3: '手腕', 4: '夹爪', 5: '辅助'}
PWM_MIN, PWM_MAX = 500, 2500
PWM_MID = 1500

STAMP_DOWN_PWM = 2000
STAMP_UP_PWM = 1500
STAMP_WRIST_PWM = 1300
WRIST_NEUTRAL_PWM = 1500

CALIBRATION_FILE = os.path.join(BASE_DIR, 'calibration.json')


def _cmd(servo_id: int, pwm: int, duration: int) -> bytes:
    return f'#{servo_id:03d}P{pwm:04d}T{duration:04d}!'.encode()


def _cmd_multi(*cmds) -> bytes:
    body = ''.join(f'#{i:03d}P{p:04d}T{t:04d}!' for i, p, t in cmds)
    return f'{{{body}}}'.encode()


def load_calibration() -> dict:
    if os.path.exists(CALIBRATION_FILE):
        with open(CALIBRATION_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}


def save_calibration(data: dict):
    with open(CALIBRATION_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def compute_pwms_at_position(x: float, y: float, cal: dict | None = None) -> dict:
    """
    双线性插值：根据四角标定数据计算 (x, y) 处的 PWM 值。
    x, y 为归一化坐标 (0~1)，(0,0)=左上角，(1,1)=右下角。
    """
    if cal is None:
        cal = load_calibration()

    corners = cal.get('corners')
    if not corners or len(corners) < 4:
        raise RuntimeError('未完成四角标定')

    tl = corners['top_left']
    tr = corners['top_right']
    bl = corners['bottom_left']
    br = corners['bottom_right']

    result = {}
    for sid in range(6):
        if sid in (1, 3):
            continue
        top = tl[str(sid)] * (1 - x) + tr[str(sid)] * x
        bottom = bl[str(sid)] * (1 - x) + br[str(sid)] * x
        result[sid] = int(top * (1 - y) + bottom * y)

    return result


class ArmController:
    _instance = None
    _ser = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if not SIMULATION_MODE and self._ser is None:
            self._connect()
        elif SIMULATION_MODE:
            logger.info('[仿真模式] ArmController 已初始化')

    def _connect(self):
        import serial
        try:
            self._ser = serial.Serial(SERIAL_PORT, SERIAL_BAUD, timeout=3)
            time.sleep(2)
            self._send(_cmd_multi(
                (0, PWM_MID, 1000), (1, PWM_MID, 1000), (2, PWM_MID, 1000),
                (3, PWM_MID, 1000), (4, PWM_MID, 1000), (5, PWM_MID, 1000),
            ))
            time.sleep(1.5)
            logger.info(f'WeArm 已连接: {SERIAL_PORT}')
        except Exception as e:
            raise RuntimeError(
                f'无法连接 WeArm（{SERIAL_PORT}）：{e}\n'
                '请检查：1) USB线是否插好  2) 电源开关是否打开  3) CH340驱动是否安装'
            )

    def _send(self, data: bytes):
        if SIMULATION_MODE:
            logger.info(f'[仿真] 发送: {data.decode()!r}')
            return
        if self._ser and self._ser.is_open:
            self._ser.write(data)

    def move_to(self, pwms: dict, duration: int = 1000):
        """移动到指定 PWM 位置。pwms: {servo_id: pwm_value}"""
        cmds = tuple((sid, int(pwm), duration) for sid, pwm in pwms.items())
        self._send(_cmd_multi(*cmds))
        time.sleep(duration / 1000 + 0.3)

    def move_single(self, servo_id: int, pwm: int, duration: int = 500):
        """控制单个舵机"""
        pwm = max(PWM_MIN, min(PWM_MAX, int(pwm)))
        self._send(_cmd(servo_id, pwm, duration))
        time.sleep(duration / 1000 + 0.2)

    def stamp_at(self, position_pwms: dict):
        """在指定位置执行盖章。position_pwms 包含 S0/S2 等定位关节的 PWM。"""
        MOVE_TIME = 1200
        HOLD_TIME = 0.9
        LIFT_TIME = 1000

        # 移动到目标位置上方（S1 保持抬起，S3 调整角度）
        move_pwms = dict(position_pwms)
        move_pwms[1] = STAMP_UP_PWM
        move_pwms[3] = STAMP_WRIST_PWM
        self.move_to(move_pwms, MOVE_TIME)

        # S1 下压盖章
        stamp_pwms = dict(move_pwms)
        stamp_pwms[1] = STAMP_DOWN_PWM
        self.move_to(stamp_pwms, MOVE_TIME)
        time.sleep(HOLD_TIME)

        # 抬起
        reset_pwms = dict(move_pwms)
        reset_pwms[1] = STAMP_UP_PWM
        reset_pwms[3] = WRIST_NEUTRAL_PWM
        self.move_to(reset_pwms, LIFT_TIME)

        # 回安全位置
        self.move_to({i: PWM_MID for i in range(6)}, 1000)

    def ping(self) -> bool:
        if SIMULATION_MODE:
            return True
        try:
            return self._ser is not None and self._ser.is_open
        except Exception:
            return False

    def close(self):
        if self._ser and self._ser.is_open:
            self._ser.close()
        ArmController._ser = None

    def __del__(self):
        self.close()
