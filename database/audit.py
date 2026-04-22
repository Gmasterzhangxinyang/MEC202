import sqlite3
from datetime import datetime
from config import DB_PATH


def log_action(
    operator_id: str,
    doc_type: str,
    qr_content: str | None,
    doc_fields: dict,
    result: str,
    errors: list,
    before_img: str,
    after_img: str,
    dms_doc_id: str | None = None,
    ocr_text: str = '',
) -> int:
    """
    写入一条审计记录。
    result 取值: 'APPROVED' / 'REJECTED' / 'PENDING_REVIEW'
    返回新记录的 id。
    """
    conn = sqlite3.connect(DB_PATH)
    cur = conn.execute(
        '''INSERT INTO audit_log
           (timestamp, operator_id, doc_type, qr_content, doc_fields,
            ocr_text, result, errors, before_img, after_img, dms_doc_id)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)''',
        (
            datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            operator_id,
            doc_type,
            qr_content,
            str(doc_fields),
            ocr_text,
            result,
            str(errors),
            before_img,
            after_img,
            dms_doc_id,
        )
    )
    conn.commit()
    row_id = cur.lastrowid
    conn.close()
    assert row_id is not None
    return row_id


def get_recent_logs(limit: int = 50) -> list:
     """
    获取最近的审计日志记录。
    Args:
        limit: 返回记录的最大数量，默认为 50。
    Returns:
        list: 包含日志记录的列表。
    """
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        'SELECT * FROM audit_log ORDER BY id DESC LIMIT ?', (limit,)
    ).fetchall()
    conn.close()
    return rows


def get_log_by_id(log_id: int) -> dict | None:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        'SELECT * FROM audit_log WHERE id = ?', (log_id,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None
