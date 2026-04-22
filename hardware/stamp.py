import time
import logging
from config import SERIAL_PORT, SERIAL_BAUD, SIMULATION_MODE

logger = logging.getLogger(__name__)

# WeArm 舵机 ID（对应控制手册引脚映射）
_SHOULDER = 1   # 肩部（大臂）—— 负责下压盖章
_WRIST    = 3   # 腕部 —— 微调盖章角度

# PWM 值
_SHOULDER_UP   = 1500   # 抬起（中位）
_SHOULDER_DOWN = 2000   # 下压盖章
_WRIST_STAMP   = 1300   # 盖章时腕部角度
_WRIST_NEUTRAL = 1500   # 腕部中位

_STAMP_TIME = 1200      # 下压运动时间 ms
_HOLD_TIME  = 0.9       # 下压停留时间 s
_LIFT_TIME  = 1000      # 抬起运动时间 ms


def _cmd(servo_id: int, pwm: int, duration: int) -> bytes:
    return f'#{servo_id:03d}P{pwm:04d}T{duration:04d}!'.encode()


def _cmd_multi(*cmds) -> bytes:
    body = ''.join(f'#{i:03d}P{p:04d}T{t:04d}!' for i, p, t in cmds)
    return f'{{{body}}}'.encode()


class StampController:
    def __init__(self):
        self._ser = None
        if not SIMULATION_MODE:
            self._connect()
        else:
            logger.info('[仿真模式] StampController 已初始化，不连接串口')

    def _connect(self):
        import serial
        try:
            self._ser = serial.Serial(SERIAL_PORT, SERIAL_BAUD, timeout=3)
            time.sleep(2)
            # 初始化：肩部和腕部回中位
            self._ser.write(_cmd_multi(
                (_SHOULDER, _SHOULDER_UP, 1000),
                (_WRIST, _WRIST_NEUTRAL, 1000),
            ))
            time.sleep(1.2)
            logger.info(f'WeArm 已连接：{SERIAL_PORT}')
        except Exception as e:
            raise RuntimeError(
                f'无法连接 WeArm（{SERIAL_PORT}）：{e}\n'
                '请检查：1) USB线是否插好  2) 电源开关是否打开  '
                '3) CH340驱动是否安装'
            )

    def _send(self, data: bytes):
        if SIMULATION_MODE:
            logger.info(f'[仿真] 发送: {data.decode()!r}')
            return
        if self._ser and self._ser.is_open:
            self._ser.write(data)

    def stamp(self):
        logger.info('开始盖章序列')
        try:
            # 腕部调整 + 肩部下压（同时运动）
            self._send(_cmd_multi(
                (_SHOULDER, _SHOULDER_DOWN, _STAMP_TIME),
                (_WRIST, _WRIST_STAMP, _STAMP_TIME),
            ))
            time.sleep(_STAMP_TIME / 1000 + _HOLD_TIME)

            # 抬起复位
            self._send(_cmd_multi(
                (_SHOULDER, _SHOULDER_UP, _LIFT_TIME),
                (_WRIST, _WRIST_NEUTRAL, _LIFT_TIME),
            ))
            time.sleep(_LIFT_TIME / 1000 + 0.2)
            logger.info('盖章序列完成')
        except Exception as e:
            # 异常时强制抬起
            self._send(_cmd(_SHOULDER, _SHOULDER_UP, 800))
            raise RuntimeError(f'盖章过程出错：{e}')

    def ping(self) -> bool:
        if SIMULATION_MODE:
            return True
        try:
            return self._ser is not None and self._ser.is_open
        except Exception:
            return False

    def close(self):
        if self._ser and self._ser.is_open:
            self._send(_cmd_multi(
                (_SHOULDER, _SHOULDER_UP, 800),
                (_WRIST, _WRIST_NEUTRAL, 800),
            ))
            time.sleep(1)
            self._ser.close()

    def __del__(self):
        self.close()
