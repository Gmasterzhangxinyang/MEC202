import sqlite3
import os
from werkzeug.security import generate_password_hash
from config import DB_PATH


def init_db():
    """初始化所有数据表（如已存在则跳过）"""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # ── 人员记录表（ID对库验证用）────────────────────────────────────────────
    c.execute('''
        CREATE TABLE IF NOT EXISTS personnel (
            id_number TEXT PRIMARY KEY,
            name      TEXT NOT NULL,
            dept      TEXT,
            role      TEXT
        )
    ''')

    # ── 审计日志表 ────────────────────────────────────────────────────────────
    c.execute('''
        CREATE TABLE IF NOT EXISTS audit_log (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp    TEXT    NOT NULL,
            operator_id  TEXT    NOT NULL,
            doc_type     TEXT,
            qr_content   TEXT,
            doc_fields   TEXT,
            result       TEXT    NOT NULL,
            errors       TEXT,
            before_img   TEXT,
            after_img    TEXT,
            dms_doc_id   TEXT
        )
    ''')

    # ── 人工复审队列 ──────────────────────────────────────────────────────────
    c.execute('''
        CREATE TABLE IF NOT EXISTS review_queue (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp    TEXT    NOT NULL,
            operator_id  TEXT    NOT NULL,
            doc_type     TEXT,
            doc_fields   TEXT,
            warnings     TEXT,
            image_path   TEXT,
            status       TEXT    NOT NULL DEFAULT 'pending',
            reviewer_id  TEXT,
            resolved_at  TEXT,
            decision     TEXT
        )
    ''')

    # ── 用户权限表 ────────────────────────────────────────────────────────────
    c.execute('''
        CREATE TABLE IF NOT EXISTS users (
            username     TEXT PRIMARY KEY,
            password_hash TEXT NOT NULL,
            role         TEXT NOT NULL DEFAULT 'operator'
        )
    ''')

    conn.commit()
    conn.close()


def seed_demo_data():
    """
    写入演示数据：
      - 3个测试人员（用于ID对库验证演示）
      - 3个测试账号
    如果数据已存在则跳过。
    """
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # 人员数据
    personnel = [
        ('20210001', '张三', '计算机学院', 'student'),
        ('20210002', '李四', '计算机学院', 'student'),
        ('20210003', '王五', '电子工程学院', 'student'),
        ('T001',     '陈邦翔', '教务处', 'staff'),
    ]
    c.executemany(
        'INSERT OR IGNORE INTO personnel VALUES (?,?,?,?)',
        personnel
    )

    # 用户账号（密码明文: admin123 / op123 / reviewer123）
    users = [
        ('admin',    generate_password_hash('admin123'),    'admin'),
        ('operator1', generate_password_hash('op123'),      'operator'),
        ('reviewer1', generate_password_hash('reviewer123'), 'reviewer'),
    ]
    c.executemany(
        'INSERT OR IGNORE INTO users VALUES (?,?,?)',
        users
    )

    conn.commit()
    conn.close()
