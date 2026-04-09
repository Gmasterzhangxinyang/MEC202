import sqlite3
from config import DB_PATH


def verify_id(id_number: str, name: str) -> tuple[bool, str]:
    """
    在 personnel 表中验证 ID 号与姓名是否匹配。
    返回 (passed, message)
    """
    if not id_number:
        return False, 'ID号为空，无法验证'

    conn = sqlite3.connect(DB_PATH)
    row = conn.execute(
        'SELECT name FROM personnel WHERE id_number = ?',
        (id_number,)
    ).fetchone()
    conn.close()

    if row is None:
        return False, f'ID号 {id_number} 不在系统人员记录中'

    db_name = row[0]
    if name and db_name != name:
        return False, f'ID号对应姓名为「{db_name}」，与填写的「{name}」不符'

    return True, 'OK'
