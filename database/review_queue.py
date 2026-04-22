import sqlite3
from datetime import datetime
from config import DB_PATH


def add_to_queue(
    operator_id: str,
    doc_type: str,
    doc_fields: dict,
    warnings: list,
    image_path: str,
    ocr_text: str = '',
) -> int:
    """将需要人工复审的文件推入队列，返回队列记录 id"""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.execute(
        '''INSERT INTO review_queue
           (timestamp, operator_id, doc_type, doc_fields, ocr_text, warnings, image_path, status)
           VALUES (?,?,?,?,?,?,?,?)''',
        (
            datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            operator_id,
            doc_type,
            str(doc_fields),
            ocr_text,
            str(warnings),
            image_path,
            'pending',
        )
    )
    conn.commit()
    row_id = cur.lastrowid
    conn.close()
    assert row_id is not None
    return row_id


def get_pending() -> list:
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        "SELECT * FROM review_queue WHERE status='pending' ORDER BY id DESC"
    ).fetchall()
    conn.close()
    return rows


def resolve(review_id: int, reviewer_id: str, decision: str):
    """
    decision: 'approved' 或 'rejected'
    """
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        '''UPDATE review_queue
           SET status=?, reviewer_id=?, resolved_at=?, decision=?
           WHERE id=?''',
        (
            decision,
            reviewer_id,
            datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            decision,
            review_id,
        )
    )
    conn.commit()
    conn.close()


def get_all(limit: int = 50) -> list:
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        'SELECT * FROM review_queue ORDER BY id DESC LIMIT ?', (limit,)
    ).fetchall()
    conn.close()
    return rows


def get_approved_for_stamping() -> list:
    """获取已批准但尚未盖章的复审记录"""
    conn = sqlite3.connect(DB_PATH)
    try:
        rows = conn.execute(
            "SELECT * FROM review_queue WHERE status='approved' AND (stamped=0 OR stamped IS NULL) ORDER BY id DESC"
        ).fetchall()
    except Exception:
        rows = conn.execute(
            "SELECT * FROM review_queue WHERE status='approved' ORDER BY id DESC"
        ).fetchall()
    conn.close()
    return rows


def mark_stamped(review_id: int):
    """标记已盖章"""
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "UPDATE review_queue SET stamped=1 WHERE id=?", (review_id,)
    )
    conn.commit()
    conn.close()
