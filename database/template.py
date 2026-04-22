import sqlite3
import json
from datetime import datetime
from config import DB_PATH


# ─── 模板 CRUD ─────────────────────────────────────────────────────────────────

def create_template(name, code, description='', classification_keywords=None,
                    classification_regex='', is_system=0, sort_order=0) -> int:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.execute(
        '''INSERT INTO doc_templates
           (name, code, description, is_system, classification_keywords,
            classification_regex, created_at, updated_at, sort_order)
           VALUES (?,?,?,?,?,?,?,?,?)''',
        (
            name, code, description, is_system,
            json.dumps(classification_keywords or [], ensure_ascii=False),
            classification_regex,
            datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            sort_order,
        )
    )
    conn.commit()
    tid = cur.lastrowid
    conn.close()
    assert tid is not None
    return tid


def get_template_by_id(template_id: int) -> dict | None:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    row = conn.execute('SELECT * FROM doc_templates WHERE id=?', (template_id,)).fetchone()
    conn.close()
    if not row:
        return None
    tpl = dict(row)
    tpl['fields'] = get_fields_for_template(template_id)
    tpl['example_image'] = get_example_image(template_id)
    return tpl


def get_template_by_code(code: str) -> dict | None:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    row = conn.execute('SELECT * FROM doc_templates WHERE code=?', (code,)).fetchone()
    conn.close()
    if not row:
        return None
    tpl = dict(row)
    tpl['fields'] = get_fields_for_template(tpl['id'])
    tpl['example_image'] = get_example_image(tpl['id'])
    return tpl


def get_all_templates(with_fields=False) -> list:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute('SELECT * FROM doc_templates ORDER BY sort_order, id').fetchall()
    conn.close()
    result = []
    for row in rows:
        tpl = dict(row)
        if with_fields:
            tpl['fields'] = get_fields_for_template(tpl['id'])
            tpl['example_image'] = get_example_image(tpl['id'])
        else:
            # 仅加载字段统计
            tpl['fields'] = get_fields_for_template(tpl['id'])
            tpl['field_stats'] = _compute_field_stats(tpl['fields'])
            tpl['example_image'] = get_example_image(tpl['id'])
        result.append(tpl)
    return result


def _compute_field_stats(fields):
    stats = {'required': 0, 'optional': 0, 'forbidden': 0}
    for f in fields:
        cat = f.get('field_category', 'required')
        if cat in stats:
            stats[cat] += 1
    return stats


def update_template(template_id: int, **kwargs) -> bool:
    allowed = {'name', 'code', 'description', 'classification_keywords',
               'classification_regex', 'sort_order', 'updated_at'}
    updates = {k: v for k, v in kwargs.items() if k in allowed}
    if not updates:
        return False
    if 'classification_keywords' in updates and isinstance(updates['classification_keywords'], list):
        updates['classification_keywords'] = json.dumps(updates['classification_keywords'], ensure_ascii=False)
    updates['updated_at'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    sets = ', '.join(f'{k}=?' for k in updates)
    vals = list(updates.values()) + [template_id]
    conn = sqlite3.connect(DB_PATH)
    conn.execute(f'UPDATE doc_templates SET {sets} WHERE id=?', vals)
    conn.commit()
    conn.close()
    return True


def delete_template(template_id: int) -> bool:
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute('SELECT is_system FROM doc_templates WHERE id=?', (template_id,)).fetchone()
    if not row or row[0]:
        conn.close()
        return False
    conn.execute('DELETE FROM template_fields WHERE template_id=?', (template_id,))
    conn.execute('DELETE FROM template_examples WHERE template_id=?', (template_id,))
    conn.execute('DELETE FROM doc_templates WHERE id=?', (template_id,))
    conn.commit()
    conn.close()
    return True


# ─── 字段管理 ─────────────────────────────────────────────────────────────────

def add_field(template_id, field_name, field_label, field_category='required',
              ocr_pattern='', validation_rule='', sort_order=0) -> int:
    conn = sqlite3.connect(DB_PATH)
    cur = conn.execute(
        '''INSERT INTO template_fields
           (template_id, field_name, field_label, field_category,
            ocr_pattern, validation_rule, sort_order)
           VALUES (?,?,?,?,?,?,?)''',
        (template_id, field_name, field_label, field_category,
         ocr_pattern, validation_rule, sort_order)
    )
    conn.commit()
    fid = cur.lastrowid
    conn.close()
    assert fid is not None
    return fid


def update_field(field_id: int, **kwargs) -> bool:
    allowed = {'field_name', 'field_label', 'field_category', 'ocr_pattern',
               'validation_rule', 'sort_order'}
    updates = {k: v for k, v in kwargs.items() if k in allowed}
    if not updates:
        return False
    sets = ', '.join(f'{k}=?' for k in updates)
    vals = list(updates.values()) + [field_id]
    conn = sqlite3.connect(DB_PATH)
    conn.execute(f'UPDATE template_fields SET {sets} WHERE id=?', vals)
    conn.commit()
    conn.close()
    return True


def delete_field(field_id: int):
    conn = sqlite3.connect(DB_PATH)
    conn.execute('DELETE FROM template_fields WHERE id=?', (field_id,))
    conn.commit()
    conn.close()


def get_fields_for_template(template_id: int) -> list:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        'SELECT * FROM template_fields WHERE template_id=? ORDER BY sort_order, id',
        (template_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def replace_fields(template_id: int, fields_data: list):
    """替换模板的所有字段。fields_data 是字段字典列表。"""
    conn = sqlite3.connect(DB_PATH)
    conn.execute('DELETE FROM template_fields WHERE template_id=?', (template_id,))
    for i, fd in enumerate(fields_data):
        conn.execute(
            '''INSERT INTO template_fields
               (template_id, field_name, field_label, field_category,
                ocr_pattern, validation_rule, sort_order)
               VALUES (?,?,?,?,?,?,?)''',
            (
                template_id,
                fd.get('field_name', ''),
                fd.get('field_label', fd.get('field_name', '')),
                fd.get('field_category', 'required'),
                fd.get('ocr_pattern', ''),
                fd.get('validation_rule', ''),
                i,
            )
        )
    conn.commit()
    conn.close()


# ─── 分类辅助 ─────────────────────────────────────────────────────────────────

def get_all_classification_rules() -> list:
    """返回所有模板的分类规则，用于自动分类。"""
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        '''SELECT id, code, name, classification_keywords, classification_regex
           FROM doc_templates WHERE is_system=1 OR code!='general'
           ORDER BY sort_order'''
    ).fetchall()
    conn.close()
    result = []
    for row in rows:
        result.append({
            'id': row[0],
            'code': row[1],
            'name': row[2],
            'keywords': json.loads(row[3]) if row[3] else [],
            'regex': row[4] or '',
        })
    return result


# ─── 示例图片 ─────────────────────────────────────────────────────────────────

def set_example_image(template_id: int, image_path: str):
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        '''INSERT INTO template_examples (template_id, image_path, generated_at)
           VALUES (?,?,?)
           ON CONFLICT(template_id) DO UPDATE SET image_path=?, generated_at=?''',
        (template_id, image_path, datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
         image_path, datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
    )
    conn.commit()
    conn.close()


def get_example_image(template_id: int) -> str | None:
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute(
        'SELECT image_path FROM template_examples WHERE template_id=?', (template_id,)
    ).fetchone()
    conn.close()
    return row[0] if row else None


def get_type_name_map() -> dict:
    """返回 {code: name} 映射，用于模板显示。"""
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute('SELECT code, name FROM doc_templates').fetchall()
    conn.close()
    return {r[0]: r[1] for r in rows}
