import time
import logging
from config import SERIAL_PORT, SERIAL_BAUD, SIMULATION_MODE

logger = logging.getLogger(__name__)


class StampController:
    """
    控制 Arduino 完成盖章全序列：
      解锁印章盒 → 慢速下压（力度控制）→ 停留 → 慢速抬起 → 锁定印章盒

    SIMULATION_MODE=True 时不实际操作串口（开发阶段使用）。
    """

    # Arduino 串口命令（与 arduino/stamp_controller.ino 对应）
    CMD_STAMP  = b'S'   # 执行盖章
    CMD_LOCK   = b'L'   # 锁定印章盒
    CMD_UNLOCK = b'U'   # 解锁印章盒
    CMD_PING   = b'P'   # 心跳检测

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
            time.sleep(2)   # 等 Arduino 复位完成
            self._lock()    # 启动时确保印章处于锁定状态
            logger.info(f'Arduino 已连接：{SERIAL_PORT}')
        except Exception as e:
            raise RuntimeError(
                f'无法连接 Arduino（{SERIAL_PORT}）：{e}\n'
                '请检查：1) USB线是否插好  2) config.py 中 SERIAL_PORT 是否正确  '
                '3) 是否已上传 Arduino 固件'
            )

    def _send(self, cmd: bytes):
        if SIMULATION_MODE:
            logger.info(f'[仿真] 发送命令: {cmd}')
            return
        if self._ser and self._ser.is_open:
            self._ser.write(cmd)

    def _lock(self):
        self._send(self.CMD_LOCK)
        time.sleep(0.3)

    def _unlock(self):
        self._send(self.CMD_UNLOCK)
        time.sleep(0.5)   # 给锁定舵机时间到位

    def stamp(self):
        """
        完整盖章序列（约3秒）：
        1. 解锁印章盒
        2. 发送盖章指令（Arduino 端做慢速力度控制）
        3. 等待盖章完成
        4. 重新锁定印章盒
        """
        logger.info('开始盖章序列')
        try:
            self._unlock()
            self._send(self.CMD_STAMP)
            time.sleep(3.0)   # 等 Arduino 完成慢速下压+停留+抬起
            self._lock()
            logger.info('盖章序列完成，印章已锁定')
        except Exception as e:
            self._lock()      # 异常时也要锁定
            raise RuntimeError(f'盖章过程出错：{e}')

    def ping(self) -> bool:
        """检测 Arduino 是否在线"""
        if SIMULATION_MODE:
            return True
        try:
            self._send(self.CMD_PING)
            resp = self._ser.readline().decode().strip()
            return resp == 'PONG'
        except Exception:
            return False

    def close(self):
        if self._ser and self._ser.is_open:
            self._lock()
            self._ser.close()

    def __del__(self):
        self.close()
