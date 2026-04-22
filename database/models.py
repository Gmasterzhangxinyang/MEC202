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
            ocr_text     TEXT,
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
            ocr_text     TEXT,
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

    # ── 文档模板定义表 ────────────────────────────────────────────────────────
    c.execute('''
        CREATE TABLE IF NOT EXISTS doc_templates (
            id                     INTEGER PRIMARY KEY AUTOINCREMENT,
            name                   TEXT    NOT NULL,
            code                   TEXT    NOT NULL UNIQUE,
            description            TEXT    DEFAULT '',
            is_system              INTEGER NOT NULL DEFAULT 0,
            classification_keywords TEXT    DEFAULT '[]',
            classification_regex   TEXT    DEFAULT '',
            created_at             TEXT    NOT NULL,
            updated_at             TEXT    NOT NULL,
            sort_order             INTEGER DEFAULT 0
        )
    ''')

    # ── 模板字段定义表 ────────────────────────────────────────────────────────
    c.execute('''
        CREATE TABLE IF NOT EXISTS template_fields (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            template_id     INTEGER NOT NULL,
            field_name      TEXT    NOT NULL,
            field_label     TEXT    NOT NULL,
            field_category  TEXT    NOT NULL DEFAULT 'required',
            ocr_pattern     TEXT    DEFAULT '',
            validation_rule TEXT    DEFAULT '',
            sort_order      INTEGER DEFAULT 0,
            FOREIGN KEY (template_id) REFERENCES doc_templates(id) ON DELETE CASCADE
        )
    ''')

    # ── 模板示例图片表 ────────────────────────────────────────────────────────
    c.execute('''
        CREATE TABLE IF NOT EXISTS template_examples (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            template_id  INTEGER NOT NULL UNIQUE,
            image_path   TEXT    NOT NULL,
            generated_at TEXT    NOT NULL,
            FOREIGN KEY (template_id) REFERENCES doc_templates(id) ON DELETE CASCADE
        )
    ''')

    conn.commit()

    try:
        c.execute('ALTER TABLE review_queue ADD COLUMN stamped INTEGER DEFAULT 0')
        conn.commit()
    except sqlite3.OperationalError:
        pass

    try:
        c.execute("ALTER TABLE audit_log ADD COLUMN ocr_text TEXT")
        conn.commit()
    except sqlite3.OperationalError:
        pass

    try:
        c.execute("ALTER TABLE review_queue ADD COLUMN ocr_text TEXT")
        conn.commit()
    except sqlite3.OperationalError:
        pass

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


def seed_default_templates():
    """写入预设文档模板和字段定义（已存在则跳过）"""
    from database.template import create_template, add_field

    templates = [
        {
            'name': '请假条',
            'code': 'leave',
            'description': '学生请假申请文件，包含请假原因、天数等信息',
            'is_system': 1,
            'sort_order': 1,
            'keywords': ['请假', '事假', '病假', '公假', '请假条', '请假申请', '请假类型', '请假天数'],
            'regex': '请假',
            'fields': [
                ('姓名', '姓名', 'required', r'姓\s*名\s*[：:]\s*(\S{2,5})',
                 '{"regex": "\\S{2,5}", "min_length": 2, "max_length": 5}'),
                ('学号', '学号', 'required', r'(?:学号|工号|学生编号)\s*[：:]\s*(\d{6,12})',
                 '{"regex": "^\\d{6,12}$"}'),
                ('日期', '日期', 'required',
                 r'(\d{4})\s*[-年/]\s*(\d{1,2})\s*[-月/]\s*(\d{1,2})\s*日?',
                 '{"date_format": "%Y-%m-%d"}'),
                ('原因', '请假原因', 'required', r'(?:原因|事由|请假原因)\s*[：:]\s*(.{2,30})',
                 '{"min_length": 2, "max_length": 30}'),
                ('请假类型', '请假类型', 'optional', r'(?:请假类型|假别)\s*[：:]\s*(\S{2,10})',
                 '{"allowed_values": ["事假", "病假", "公假", "丧假", "婚假"]}'),
                ('金额', '报销金额', 'forbidden', '', ''),
            ],
        },
        {
            'name': '报销申请表',
            'code': 'expense',
            'description': '费用报销申请文件，包含金额、用途等信息',
            'is_system': 1,
            'sort_order': 2,
            'keywords': ['报销', '费用', '金额', '合计', '总计', '用途', '报销单', '报销申请'],
            'regex': '报销',
            'fields': [
                ('姓名', '姓名', 'required', r'姓\s*名\s*[：:]\s*(\S{2,5})',
                 '{"regex": "\\S{2,5}", "min_length": 2, "max_length": 5}'),
                ('学号', '学号', 'required', r'(?:学号|工号|学生编号)\s*[：:]\s*(\d{6,12})',
                 '{"regex": "^\\d{6,12}$"}'),
                ('日期', '日期', 'required',
                 r'(\d{4})\s*[-年/]\s*(\d{1,2})\s*[-月/]\s*(\d{1,2})\s*日?',
                 '{"date_format": "%Y-%m-%d"}'),
                ('金额', '报销金额', 'required', r'(?:金额|合计|总计)\s*[：:￥¥]?\s*(\d+(?:\.\d{1,2})?)\s*元?',
                 '{"regex": "^\\d+(\\.\\d{1,2})?$", "min_value": 0.01, "max_value": 100000}'),
                ('用途', '报销用途', 'optional', r'(?:用途|事由|说明)\s*[：:]\s*(.{2,50})',
                 '{"min_length": 2}'),
                ('原因', '请假原因', 'forbidden', '', ''),
            ],
        },
        {
            'name': '证明申请',
            'code': 'cert',
            'description': '各类证明文件申请，如在读证明、成绩证明等',
            'is_system': 1,
            'sort_order': 3,
            'keywords': ['证明', '在读', '成绩', '学籍', '毕业', '证明申请'],
            'regex': '证明',
            'fields': [
                ('姓名', '姓名', 'required', r'姓\s*名\s*[：:]\s*(\S{2,5})',
                 '{"regex": "\\S{2,5}", "min_length": 2, "max_length": 5}'),
                ('学号', '学号', 'required', r'(?:学号|工号|学生编号)\s*[：:]\s*(\d{6,12})',
                 '{"regex": "^\\d{6,12}$"}'),
                ('日期', '日期', 'required',
                 r'(\d{4})\s*[-年/]\s*(\d{1,2})\s*[-月/]\s*(\d{1,2})\s*日?',
                 '{"date_format": "%Y-%m-%d"}'),
                ('证明类型', '证明类型', 'optional', r'(?:证明类型|类型)\s*[：:]\s*(\S{2,20})',
                 '{"allowed_values": ["在读证明", "成绩证明", "毕业证明", "学位证明", "学籍证明"]}'),
                ('金额', '报销金额', 'forbidden', '', ''),
            ],
        },
        {
            'name': '通用文件',
            'code': 'general',
            'description': '无法归类的通用文件，仅检查基本字段',
            'is_system': 1,
            'sort_order': 99,
            'keywords': [],
            'regex': '',
            'fields': [
                ('姓名', '姓名', 'required', r'姓\s*名\s*[：:]\s*(\S{2,5})',
                 '{"regex": "\\S{2,5}"}'),
                ('日期', '日期', 'required',
                 r'(\d{4})\s*[-年/]\s*(\d{1,2})\s*[-月/]\s*(\d{1,2})\s*日?',
                 '{"date_format": "%Y-%m-%d"}'),
            ],
        },
    ]

    for tpl in templates:
        # 检查是否已存在
        from database.template import get_template_by_code
        if get_template_by_code(tpl['code']):
            continue
        tid = create_template(
            name=tpl['name'],
            code=tpl['code'],
            description=tpl['description'],
            classification_keywords=tpl['keywords'],
            classification_regex=tpl['regex'],
            is_system=tpl['is_system'],
            sort_order=tpl['sort_order'],
        )
        for i, fd in enumerate(tpl['fields']):
            add_field(tid, fd[0], fd[1], fd[2], fd[3], fd[4], i)
