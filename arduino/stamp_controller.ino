/*
 * stamp_controller.ino
 * 文档盖章机器人 - Arduino 固件
 *
 * 接线说明：
 *   盖章舵机 (MG996R)  → 信号线接 Pin 9，红线接 5V，棕线接 GND
 *   锁定舵机 (MG90S)   → 信号线接 Pin 10，红线接 5V，棕线接 GND
 *
 * 串口命令（9600 baud）：
 *   'S' → 执行盖章（慢速下压→停留→慢速抬起）
 *   'L' → 锁定印章盒
 *   'U' → 解锁印章盒
 *   'P' → 心跳检测，回复 "PONG\n"
 */

#include <Servo.h>

Servo stampServo;   // 盖章舵机：Pin 9
Servo lockServo;    // 锁定舵机：Pin 10

// ── 角度配置（根据实际安装方向调整）──────────────────────────────
const int STAMP_UP   = 0;    // 印章抬起位置（度）
const int STAMP_DOWN = 85;   // 印章按下位置（度，越大压得越深）
const int LOCK_ON    = 90;   // 锁定位置
const int LOCK_OFF   = 0;    // 解锁位置

// ── 盖章参数 ────────────────────────────────────────────────────────
const int STEP_DELAY  = 25;  // 每步延迟（ms），越大越慢越轻 → 控制印章力度
const int HOLD_TIME   = 900; // 下压停留时间（ms），确保印迹清晰

void setup() {
  stampServo.attach(9);
  lockServo.attach(10);

  // 初始状态：印章抬起，盒子锁定
  stampServo.write(STAMP_UP);
  lockServo.write(LOCK_ON);
  delay(500);

  Serial.begin(9600);
  Serial.println("READY");
}

void loop() {
  if (!Serial.available()) return;

  char cmd = Serial.read();

  switch (cmd) {
    case 'S': doStamp(); break;
    case 'L': doLock();  break;
    case 'U': doUnlock();break;
    case 'P': Serial.println("PONG"); break;
    default: break;
  }
}

// ── 盖章序列：慢速下压（力度控制）──────────────────────────────────
void doStamp() {
  Serial.println("STAMPING");

  // 慢速下压
  for (int angle = STAMP_UP; angle <= STAMP_DOWN; angle += 3) {
    stampServo.write(angle);
    delay(STEP_DELAY);
  }
  stampServo.write(STAMP_DOWN);  // 确保到位

  // 停留，让印迹充分着墨
  delay(HOLD_TIME);

  // 慢速抬起
  for (int angle = STAMP_DOWN; angle >= STAMP_UP; angle -= 3) {
    stampServo.write(angle);
    delay(STEP_DELAY);
  }
  stampServo.write(STAMP_UP);   // 确保完全抬起

  Serial.println("DONE");
}

void doLock() {
  lockServo.write(LOCK_ON);
  delay(300);
  Serial.println("LOCKED");
}

void doUnlock() {
  lockServo.write(LOCK_OFF);
  delay(300);
  Serial.println("UNLOCKED");
}
