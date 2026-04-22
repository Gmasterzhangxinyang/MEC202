"""
demo_app.py
完全自包含的演示程序，无需任何硬件，无需 PaddleOCR / OpenCV。
依赖：flask, pillow, werkzeug
"""
import os
import sys
import random
import sqlite3
import json
from datetime import datetime, timedelta
from functools import wraps

from flask import (
    Flask, render_template, request, session,
    redirect, url_for, jsonify, send_from_directory
)
from werkzeug.security import generate_password_hash, check_password_hash
from PIL import Image, ImageDraw, ImageFont
import io

# 将项目根目录加入 path，以便 import 共享模块
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# ─── 路径 ─────────────────────────────────────────────────────────────────────
BASE_DIR    = os.path.dirname(os.path.abspath(__file__))
DB_PATH     = os.path.join(BASE_DIR, 'demo.db')
IMG_DIR     = os.path.join(BASE_DIR, 'demo_images')
EXAMPLE_DIR = os.path.join(BASE_DIR, 'demo_examples')
TMPL_DIR    = os.path.join(BASE_DIR, 'templates')

os.makedirs(IMG_DIR, exist_ok=True)
os.makedirs(EXAMPLE_DIR, exist_ok=True)

app = Flask(__name__, template_folder=TMPL_DIR)
app.secret_key = 'demo_secret_2024'


# ─────────────────────────────────────────────────────────────────────────────
#  图片生成（用 Pillow 画假文件）
# ─────────────────────────────────────────────────────────────────────────────

def _get_font(size):
    """尝试加载中文字体，找不到就用默认字体"""
    font_candidates = [
        '/System/Library/Fonts/STHeiti Light.ttc',      # macOS
        '/System/Library/Fonts/PingFang.ttc',
        '/System/Library/Fonts/Supplemental/Arial Unicode.ttf',
        '/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc', # Linux
        '/usr/share/fonts/truetype/wqy/wqy-microhei.ttc',
        '/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc',
        '/Windows/Fonts/msyh.ttc',                       # Windows
    ]
    for path in font_candidates:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    return ImageFont.load_default()


def generate_document_image(doc_data: dict, stamped: bool = False) -> bytes:
    """生成一张模拟文件图片，stamped=True 时叠加红色印章"""
    W, H = 600, 800
    img = Image.new('RGB', (W, H), '#FAFAFA')
    draw = ImageDraw.Draw(img)

    font_title = _get_font(22)
    font_label = _get_font(16)
    font_value = _get_font(16)
    font_small  = _get_font(13)

    # 边框
    draw.rectangle([20, 20, W-20, H-20], outline='#CCCCCC', width=1)

    # 标题
    title = doc_data.get('title', '申请表')
    draw.text((W//2, 55), title, fill='#1A1A1A', font=font_title, anchor='mm')
    draw.line([60, 75, W-60, 75], fill='#CCCCCC', width=1)

    # 字段
    fields = doc_data.get('fields', [])
    y = 100
    for label, value in fields:
        draw.text((60, y),   f'{label}：', fill='#555555', font=font_label)
        draw.text((200, y),  str(value),   fill='#1A1A1A', font=font_value)
        draw.line([60, y+26, W-60, y+26], fill='#EEEEEE', width=1)
        y += 42

    # 签名栏
    y += 20
    draw.text((60, y),  '审批人签名：', fill='#555555', font=font_label)
    draw.text((200, y), doc_data.get('signer', '陈老师'), fill='#1A1A1A', font=font_value)
    y += 42
    draw.text((60, y),  '日期：',      fill='#555555', font=font_label)
    draw.text((200, y), doc_data.get('sign_date', datetime.now().strftime('%Y-%m-%d')),
              fill='#1A1A1A', font=font_value)

    # 页码
    draw.text((W//2, H-35), '第 1 页 / 共 1 页',
              fill='#AAAAAA', font=font_small, anchor='mm')

    # 盖章
    if stamped:
        _draw_stamp(draw, W-140, H//2 + 80)

    buf = io.BytesIO()
    img.save(buf, format='JPEG', quality=92)
    return buf.getvalue()


def _draw_stamp(draw, cx, cy):
    """在 (cx, cy) 位置画一个红色圆形印章"""
    r = 65
    # 外圆
    draw.ellipse([cx-r, cy-r, cx+r, cy+r], outline='#CC0000', width=3)
    # 内圆
    draw.ellipse([cx-r+8, cy-r+8, cx+r-8, cy+r-8], outline='#CC0000', width=1)
    # 中间文字
    font = _get_font(18)
    draw.text((cx, cy-10), '已审核', fill='#CC0000', font=font, anchor='mm')
    font_s = _get_font(12)
    draw.text((cx, cy+14), datetime.now().strftime('%Y.%m.%d'),
              fill='#CC0000', font=font_s, anchor='mm')


def save_demo_images(name_prefix: str, doc_data: dict):
    """保存盖章前后两张图，返回 (before_path, after_path)"""
    before_bytes = generate_document_image(doc_data, stamped=False)
    after_bytes  = generate_document_image(doc_data, stamped=True)

    before_path = os.path.join(IMG_DIR, f'{name_prefix}_before.jpg')
    after_path  = os.path.join(IMG_DIR, f'{name_prefix}_after.jpg')

    with open(before_path, 'wb') as f: f.write(before_bytes)
    with open(after_path,  'wb') as f: f.write(after_bytes)

    return before_path, after_path


# ─────────────────────────────────────────────────────────────────────────────
#  模拟场景（三种结果）
# ─────────────────────────────────────────────────────────────────────────────

SCENARIOS = [
    {
        'weight': 5,
        'outcome': 'approved',
        'doc_data': {
            'title': '请假申请表',
            'fields': [
                ('姓名',   '张三'),
                ('学号',   '20210001'),
                ('日期',   datetime.now().strftime('%Y-%m-%d')),
                ('请假类型', '事假'),
                ('请假天数', '2天'),
                ('原因',   '家中有事'),
            ],
            'signer': '李院长',
        },
        'fields':   {'姓名': '张三', '学号': '20210001', '日期': datetime.now().strftime('%Y-%m-%d')},
        'doc_type': 'leave',
    },
    {
        'weight': 3,
        'outcome': 'approved',
        'doc_data': {
            'title': '报销申请单',
            'fields': [
                ('姓名',  '李四'),
                ('学号',  '20210002'),
                ('日期',  datetime.now().strftime('%Y-%m-%d')),
                ('金额',  '¥ 258.00'),
                ('用途',  '办公用品采购'),
            ],
            'signer': '王主任',
        },
        'fields':   {'姓名': '李四', '学号': '20210002', '日期': datetime.now().strftime('%Y-%m-%d'), '金额': '258.00'},
        'doc_type': 'expense',
    },
    {
        'weight': 2,
        'outcome': 'rejected',
        'doc_data': {
            'title': '证明申请表',
            'fields': [
                ('姓名',  '王五'),
                ('学号',  ''),        # 故意留空 → 触发"缺少必填项"
                ('日期',  '2025-13-01'),  # 非法日期
            ],
            'signer': '',
        },
        'fields':   {'姓名': '王五', '日期': '2025-13-01'},
        'doc_type': 'cert',
        'errors':   ['缺少必填项：学号', '日期格式无法识别：2025-13-01', '未检测到签名/审批栏'],
    },
    {
        'weight': 2,
        'outcome': 'pending_review',
        'doc_data': {
            'title': '综合测评申请',
            'fields': [
                ('姓名',  '赵六'),
                ('学号',  '20210003'),
                ('日期',  (datetime.now() - timedelta(days=120)).strftime('%Y-%m-%d')),
                ('申请项', '优秀学生干部'),
            ],
            'signer': '辅导员',
        },
        'fields':   {'姓名': '赵六', '学号': '20210003',
                     '日期': (datetime.now() - timedelta(days=120)).strftime('%Y-%m-%d')},
        'doc_type': 'general',
        'warnings': ['注意：文件日期距今已超过 120 天，请人工确认是否有效'],
    },
    {
        'weight': 1,
        'outcome': 'pending_review',
        'doc_data': {
            'title': '未知文件',
            'fields': [
                ('姓名',  '孙七'),
                ('备注',  '无法识别的文件类型'),
            ],
            'signer': '',
        },
        'fields':   {'姓名': '孙七', '备注': '无法识别的文件类型'},
        'doc_type': 'pending',
        'warnings': ['无法自动识别文件类型，请管理员手动分类'],
    },
]


def pick_scenario():
    weights = [s['weight'] for s in SCENARIOS]
    return random.choices(SCENARIOS, weights=weights, k=1)[0]


# ─────────────────────────────────────────────────────────────────────────────
#  数据库
# ─────────────────────────────────────────────────────────────────────────────

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    c.execute('''CREATE TABLE IF NOT EXISTS users (
        username TEXT PRIMARY KEY,
        password_hash TEXT,
        role TEXT
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS audit_log (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp   TEXT,
        operator_id TEXT,
        doc_type    TEXT,
        doc_fields  TEXT,
        result      TEXT,
        errors      TEXT,
        before_img  TEXT,
        after_img   TEXT
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS review_queue (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp   TEXT,
        operator_id TEXT,
        doc_type    TEXT,
        doc_fields  TEXT,
        warnings    TEXT,
        image_path  TEXT,
        status      TEXT DEFAULT 'pending',
        reviewer_id TEXT,
        resolved_at TEXT,
        decision    TEXT
    )''')

    # 新增模板相关表
    c.execute('''CREATE TABLE IF NOT EXISTS doc_templates (
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
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS template_fields (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        template_id     INTEGER NOT NULL,
        field_name      TEXT    NOT NULL,
        field_label     TEXT    NOT NULL,
        field_category  TEXT    NOT NULL DEFAULT 'required',
        ocr_pattern     TEXT    DEFAULT '',
        validation_rule TEXT    DEFAULT '',
        sort_order      INTEGER DEFAULT 0,
        FOREIGN KEY (template_id) REFERENCES doc_templates(id) ON DELETE CASCADE
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS template_examples (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        template_id  INTEGER NOT NULL UNIQUE,
        image_path   TEXT    NOT NULL,
        generated_at TEXT    NOT NULL,
        FOREIGN KEY (template_id) REFERENCES doc_templates(id) ON DELETE CASCADE
    )''')

    conn.commit()

    # 用户
    users = [
        ('admin',     generate_password_hash('admin123'),    'admin'),
        ('operator1', generate_password_hash('op123'),       'operator'),
        ('reviewer1', generate_password_hash('reviewer123'), 'reviewer'),
    ]
    for u in users:
        c.execute('INSERT OR IGNORE INTO users VALUES (?,?,?)', u)

    conn.commit()
    conn.close()


def seed_default_templates():
    """写入预设模板到 demo 数据库"""
    templates = [
        {
            'name': '请假条', 'code': 'leave', 'description': '学生请假申请文件',
            'is_system': 1, 'sort_order': 1,
            'keywords': ['请假', '事假', '病假', '公假', '请假条', '请假申请'],
            'regex': '请假',
            'fields': [
                ('姓名', '姓名', 'required', '', '{"min_length":2}'),
                ('学号', '学号', 'required', '', '{"regex":"^\\d{6,12}$"}'),
                ('日期', '日期', 'required', '', '{"date_format":"%Y-%m-%d"}'),
                ('原因', '请假原因', 'required', '', '{"min_length":2}'),
                ('请假类型', '请假类型', 'optional', '', '{"allowed_values":["事假","病假","公假"]}'),
                ('金额', '报销金额', 'forbidden', '', ''),
            ],
        },
        {
            'name': '报销申请表', 'code': 'expense', 'description': '费用报销申请文件',
            'is_system': 1, 'sort_order': 2,
            'keywords': ['报销', '费用', '金额', '合计', '报销单', '报销申请'],
            'regex': '报销',
            'fields': [
                ('姓名', '姓名', 'required', '', '{"min_length":2}'),
                ('学号', '学号', 'required', '', '{"regex":"^\\d{6,12}$"}'),
                ('日期', '日期', 'required', '', '{"date_format":"%Y-%m-%d"}'),
                ('金额', '报销金额', 'required', '', '{"min_value":0.01,"max_value":100000}'),
                ('用途', '报销用途', 'optional', '', ''),
                ('原因', '请假原因', 'forbidden', '', ''),
            ],
        },
        {
            'name': '证明申请', 'code': 'cert', 'description': '各类证明文件申请',
            'is_system': 1, 'sort_order': 3,
            'keywords': ['证明', '在读', '成绩', '学籍', '毕业', '证明申请'],
            'regex': '证明',
            'fields': [
                ('姓名', '姓名', 'required', '', '{"min_length":2}'),
                ('学号', '学号', 'required', '', '{"regex":"^\\d{6,12}$"}'),
                ('日期', '日期', 'required', '', '{"date_format":"%Y-%m-%d"}'),
                ('证明类型', '证明类型', 'optional', '', '{"allowed_values":["在读证明","成绩证明","毕业证明"]}'),
                ('金额', '报销金额', 'forbidden', '', ''),
            ],
        },
        {
            'name': '通用文件', 'code': 'general', 'description': '无法归类的通用文件',
            'is_system': 1, 'sort_order': 99,
            'keywords': [], 'regex': '',
            'fields': [
                ('姓名', '姓名', 'required', '', '{"min_length":2}'),
                ('日期', '日期', 'required', '', '{"date_format":"%Y-%m-%d"}'),
            ],
        },
    ]

    for tpl in templates:
        existing = conn_query('SELECT id FROM doc_templates WHERE code=?', (tpl['code'],))
        if existing:
            continue
        tid = conn_execute(
            '''INSERT INTO doc_templates
               (name,code,description,is_system,classification_keywords,classification_regex,
                created_at,updated_at,sort_order)
               VALUES (?,?,?,?,?,?,?,?,?)''',
            (tpl['name'], tpl['code'], tpl['description'], tpl['is_system'],
             json.dumps(tpl['keywords'], ensure_ascii=False), tpl['regex'],
             datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
             datetime.now().strftime('%Y-%m-%d %H:%M:%S'), tpl['sort_order'])
        )
        for i, fd in enumerate(tpl['fields']):
            conn_execute(
                '''INSERT INTO template_fields
                   (template_id,field_name,field_label,field_category,ocr_pattern,validation_rule,sort_order)
                   VALUES (?,?,?,?,?,?,?)''',
                (tid, fd[0], fd[1], fd[2], fd[3], fd[4], i)
            )


def conn_execute(sql, params=()):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.execute(sql, params)
    conn.commit()
    rowid = cur.lastrowid
    conn.close()
    return rowid


def conn_query(sql, params=()):
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return rows


def get_type_name_map():
    rows = conn_query('SELECT code, name FROM doc_templates')
    return {r[0]: r[1] for r in rows}


def get_all_templates():
    rows = conn_query('SELECT * FROM doc_templates ORDER BY sort_order, id')
    result = []
    for row in rows:
        tpl = {'id': row[0], 'name': row[1], 'code': row[2], 'description': row[3],
               'is_system': row[4], 'classification_keywords': row[5],
               'classification_regex': row[6]}
        tpl['fields'] = conn_query(
            'SELECT * FROM template_fields WHERE template_id=? ORDER BY sort_order, id',
            (tpl['id'],)
        )
        tpl['fields'] = [dict(zip(['id','template_id','field_name','field_label','field_category',
                                    'ocr_pattern','validation_rule','sort_order'], f))
                         for f in tpl['fields']]
        stats = {'required': 0, 'optional': 0, 'forbidden': 0}
        for f in tpl['fields']:
            cat = f.get('field_category', 'required')
            if cat in stats:
                stats[cat] += 1
        tpl['field_stats'] = stats
        ex = conn_query('SELECT image_path FROM template_examples WHERE template_id=?', (tpl['id'],))
        tpl['example_image'] = ex[0][0] if ex else None
        result.append(tpl)
    return result


def seed_history():
    """生成历史审计记录和待复审记录"""
    conn = sqlite3.connect(DB_PATH)
    count = conn.execute('SELECT COUNT(*) FROM audit_log').fetchone()[0]
    if count > 0:
        conn.close()
        return

    operators = ['operator1', 'admin']
    history_scenarios = [
        ('张三', '20210001', 'leave',   'APPROVED', [], '请假申请表'),
        ('李四', '20210002', 'expense', 'APPROVED', [], '报销申请单'),
        ('王五', '20210003', 'cert',    'REJECTED',
         ['缺少必填项：学号', '未检测到签名/审批栏'], '证明申请表'),
        ('赵六', '20210001', 'leave',   'APPROVED', [], '请假申请表'),
        ('张三', '20210001', 'expense', 'APPROVED', [], '报销申请单'),
        ('李四', '20210002', 'cert',    'APPROVED', [], '证明申请'),
        ('王五', '20210003', 'leave',   'REJECTED',
         ['日期格式无法识别：2025-13-01'], '请假申请表'),
        ('赵六', '20210001', 'general', 'PENDING_REVIEW',
         ['文件日期距今已超过90天'], '综合测评'),
        ('张三', '20210001', 'expense', 'APPROVED', [], '差旅报销单'),
        ('李四', '20210002', 'leave',   'APPROVED', [], '请假申请表'),
        ('张三', '20210001', 'leave',   'APPROVED', [], '请假申请表'),
        ('李四', '20210002', 'expense', 'REJECTED', ['缺少必填项：金额'], '报销申请单'),
        ('王五', '20210003', 'cert',    'APPROVED', [], '在读证明申请'),
        ('赵六', '20210003', 'leave',   'APPROVED', [], '病假申请'),
        ('张三', '20210002', 'expense', 'APPROVED', [], '书籍报销'),
    ]

    for i, (name, sid, dtype, result, errors, title) in enumerate(history_scenarios):
        ts = (datetime.now() - timedelta(hours=i*3+1)).strftime('%Y-%m-%d %H:%M:%S')
        op = random.choice(operators)

        doc_data = {
            'title': title,
            'fields': [('姓名', name), ('学号', sid),
                       ('日期', (datetime.now() - timedelta(days=i)).strftime('%Y-%m-%d'))],
            'signer': '陈老师' if result != 'REJECTED' else '',
        }
        prefix = f'hist_{i:02d}_{sid}'
        before_path, after_path = save_demo_images(prefix, doc_data)
        after_path_final = after_path if result == 'APPROVED' else before_path

        conn.execute(
            'INSERT INTO audit_log (timestamp,operator_id,doc_type,doc_fields,result,errors,before_img,after_img) VALUES (?,?,?,?,?,?,?,?)',
            (ts, op, dtype, str({'姓名': name, '学号': sid}),
             result, str(errors), before_path, after_path_final)
        )

    # 3条待复审（含1条 pending 类型）
    review_items = [
        ('赵六', '20210003', 'general',
         str(['文件日期距今已超过 100 天，请人工确认是否有效'])),
        ('张三', '20210001', 'pending',
         str(['无法自动识别文件类型，请管理员手动分类'])),
        ('李四', '20210002', 'general',
         str(['文件日期距今已超过 95 天，请人工确认是否有效'])),
    ]
    for i, (name, sid, dtype, warnings) in enumerate(review_items):
        ts = (datetime.now() - timedelta(minutes=30+i*15)).strftime('%Y-%m-%d %H:%M:%S')
        doc_data = {
            'title': '未知文件' if dtype == 'pending' else '综合测评申请',
            'fields': [('姓名', name), ('学号', sid),
                       ('日期', (datetime.now() - timedelta(days=100)).strftime('%Y-%m-%d'))],
            'signer': '辅导员',
        }
        prefix = f'review_{i}_{sid}'
        before_path, _ = save_demo_images(prefix, doc_data)
        conn.execute(
            '''INSERT INTO review_queue
               (timestamp,operator_id,doc_type,doc_fields,warnings,image_path,status)
               VALUES (?,?,?,?,?,?,?)''',
            (ts, 'operator1', dtype,
             str({'姓名': name, '学号': sid}), warnings, before_path, 'pending')
        )

    conn.commit()
    conn.close()


# ─────────────────────────────────────────────────────────────────────────────
#  Flask 路由
# ─────────────────────────────────────────────────────────────────────────────

def login_required(f):
    @wraps(f)
    def dec(*args, **kwargs):
        if 'username' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return dec


@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        u = request.form.get('username', '').strip()
        p = request.form.get('password', '')
        conn = sqlite3.connect(DB_PATH)
        row = conn.execute(
            'SELECT password_hash, role FROM users WHERE username=?', (u,)
        ).fetchone()
        conn.close()
        if row and check_password_hash(row[0], p):
            session['username'] = u
            session['role']     = row[1]
            return redirect(url_for('index'))
        error = '账号或密码错误'
    return render_template('login.html', error=error)


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))


@app.route('/')
@login_required
def index():
    return render_template('index.html',
                           username=session['username'],
                           role=session['role'])


@app.route('/stamp', methods=['POST'])
@login_required
def stamp():
    """模拟完整处理流程（随机挑选场景）"""
    import time
    time.sleep(1.5)   # 模拟处理耗时

    scenario = pick_scenario()
    outcome  = scenario['outcome']
    fields   = scenario['fields']
    doc_data = scenario['doc_data']
    doc_type = scenario['doc_type']
    errors   = scenario.get('errors', [])
    warnings = scenario.get('warnings', [])

    ts_prefix = datetime.now().strftime('%Y%m%d_%H%M%S')
    before_path, after_path = save_demo_images(ts_prefix, doc_data)

    conn = sqlite3.connect(DB_PATH)

    if outcome == 'approved':
        conn.execute(
            'INSERT INTO audit_log (timestamp,operator_id,doc_type,doc_fields,result,errors,before_img,after_img) VALUES (?,?,?,?,?,?,?,?)',
            (datetime.now().strftime('%Y-%m-%d %H:%M:%S'), session['username'],
             doc_type, str(fields), 'APPROVED', '[]', before_path, after_path)
        )

    elif outcome == 'rejected':
        conn.execute(
            'INSERT INTO audit_log (timestamp,operator_id,doc_type,doc_fields,result,errors,before_img,after_img) VALUES (?,?,?,?,?,?,?,?)',
            (datetime.now().strftime('%Y-%m-%d %H:%M:%S'), session['username'],
             doc_type, str(fields), 'REJECTED', str(errors), before_path, before_path)
        )

    else:  # pending_review
        conn.execute(
            '''INSERT INTO review_queue
               (timestamp,operator_id,doc_type,doc_fields,warnings,image_path,status)
               VALUES (?,?,?,?,?,?,?)''',
            (datetime.now().strftime('%Y-%m-%d %H:%M:%S'), session['username'],
             doc_type, str(fields), str(warnings), before_path, 'pending')
        )
        conn.execute(
            'INSERT INTO audit_log (timestamp,operator_id,doc_type,doc_fields,result,errors,before_img,after_img) VALUES (?,?,?,?,?,?,?,?)',
            (datetime.now().strftime('%Y-%m-%d %H:%M:%S'), session['username'],
             doc_type, str(fields), 'PENDING_REVIEW', str(warnings), before_path, before_path)
        )

    conn.commit()
    conn.close()

    return jsonify({
        'status':   outcome,
        'fields':   fields,
        'errors':   errors,
        'warnings': warnings,
    })


@app.route('/logs')
@login_required
def logs():
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute(
        'SELECT * FROM audit_log ORDER BY id DESC LIMIT 50'
    ).fetchall()
    conn.close()
    type_map = get_type_name_map()
    return render_template('log.html', rows=rows, type_map=type_map,
                           username=session['username'], role=session['role'])


@app.route('/review')
@login_required
def review():
    if session.get('role') not in ('reviewer', 'admin'):
        return redirect(url_for('index'))
    conn = sqlite3.connect(DB_PATH)
    pending   = conn.execute("SELECT * FROM review_queue WHERE status='pending' ORDER BY id DESC").fetchall()
    all_items = conn.execute('SELECT * FROM review_queue ORDER BY id DESC LIMIT 30').fetchall()
    conn.close()
    type_map = get_type_name_map()
    all_templates = get_all_templates()
    return render_template('review.html', pending=pending, all_items=all_items,
                           type_map=type_map, all_templates=all_templates,
                           username=session['username'], role=session['role'])


@app.route('/review/<int:rid>/resolve', methods=['POST'])
@login_required
def resolve_review(rid):
    if session.get('role') not in ('reviewer', 'admin'):
        return jsonify({'error': '权限不足'}), 403
    decision = request.json.get('decision')
    if decision not in ('approved', 'rejected'):
        return jsonify({'error': '无效决策'}), 400

    reclassify = request.json.get('reclassify')

    conn = sqlite3.connect(DB_PATH)
    row = conn.execute('SELECT image_path FROM review_queue WHERE id=?', (rid,)).fetchone()
    conn.execute(
        'UPDATE review_queue SET status=?,reviewer_id=?,resolved_at=?,decision=? WHERE id=?',
        (decision, session['username'], datetime.now().strftime('%Y-%m-%d %H:%M:%S'), decision, rid)
    )
    if decision == 'approved' and row:
        img = Image.open(row[0])
        draw = ImageDraw.Draw(img)
        _draw_stamp(draw, img.width - 140, img.height // 2 + 80)
        after_path = row[0].replace('_before.jpg', '_reviewed_after.jpg')
        img.save(after_path, 'JPEG', quality=92)

        actual_type = reclassify or conn.execute(
            'SELECT doc_type FROM review_queue WHERE id=?', (rid,)
        ).fetchone()[0] or 'review_approved'

        conn.execute(
            'INSERT INTO audit_log (timestamp,operator_id,doc_type,doc_fields,result,errors,before_img,after_img) VALUES (?,?,?,?,?,?,?,?)',
            (datetime.now().strftime('%Y-%m-%d %H:%M:%S'), session['username'],
             actual_type, '{}', 'APPROVED', '[]', row[0], after_path)
        )
    conn.commit()
    conn.close()
    return jsonify({'status': 'ok'})


@app.route('/images/<path:filename>')
@login_required
def serve_image(filename):
    return send_from_directory(IMG_DIR, filename)


# ─── 模板管理路由 (demo) ──────────────────────────────────────────────────

@app.route('/admin/templates')
@login_required
def admin_templates():
    if session.get('role') != 'admin':
        return redirect(url_for('index'))
    templates = get_all_templates()
    return render_template('admin.html', templates=templates,
                           username=session['username'], role=session['role'])


@app.route('/admin/templates/new', methods=['GET', 'POST'])
@login_required
def admin_template_new():
    if session.get('role') != 'admin':
        return redirect(url_for('index'))
    if request.method == 'GET':
        return render_template('template_edit.html', template=None,
                               username=session['username'], role=session['role'])
    name = request.form.get('name', '').strip()
    code = request.form.get('code', '').strip()
    description = request.form.get('description', '').strip()
    keywords_str = request.form.get('keywords', '').strip()
    regex = request.form.get('regex', '').strip()
    if not name or not code:
        return '模板名称和编码不能为空', 400
    keywords = [k.strip() for k in keywords_str.split(',') if k.strip()] if keywords_str else []
    tid = conn_execute(
        '''INSERT INTO doc_templates (name,code,description,is_system,classification_keywords,
           classification_regex,created_at,updated_at,sort_order) VALUES (?,?,?,?,?,?,?,?,?)''',
        (name, code, description, 0, json.dumps(keywords, ensure_ascii=False), regex,
         datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
         datetime.now().strftime('%Y-%m-%d %H:%M:%S'), 99)
    )
    _save_fields_demo(tid, request.form)
    return redirect(url_for('admin_templates'))


@app.route('/admin/templates/<int:tid>/edit', methods=['GET', 'POST'])
@login_required
def admin_template_edit(tid):
    if session.get('role') != 'admin':
        return redirect(url_for('index'))
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    row = conn.execute('SELECT * FROM doc_templates WHERE id=?', (tid,)).fetchone()
    conn.close()
    if not row:
        return '模板不存在', 404
    template = dict(row)
    if request.method == 'GET':
        try:
            kw_list = json.loads(template['classification_keywords'])
            template['keywords'] = ', '.join(kw_list)
        except (json.JSONDecodeError, TypeError):
            template['keywords'] = template['classification_keywords']
        template['regex'] = template.get('classification_regex', '')
        field_rows = conn_query('SELECT * FROM template_fields WHERE template_id=? ORDER BY sort_order, id', (tid,))
        template['fields'] = [dict(zip(['id','template_id','field_name','field_label','field_category',
                                        'ocr_pattern','validation_rule','sort_order'], f))
                              for f in field_rows]
        ex = conn_query('SELECT image_path FROM template_examples WHERE template_id=?', (tid,))
        template['example_image'] = ex[0][0] if ex else None
        return render_template('template_edit.html', template=template,
                               username=session['username'], role=session['role'])

    name = request.form.get('name', '').strip()
    description = request.form.get('description', '').strip()
    keywords_str = request.form.get('keywords', '').strip()
    regex = request.form.get('regex', '').strip()
    keywords = [k.strip() for k in keywords_str.split(',') if k.strip()] if keywords_str else []
    conn_execute(
        '''UPDATE doc_templates SET name=?,description=?,classification_keywords=?,
           classification_regex=?,updated_at=? WHERE id=?''',
        (name, description, json.dumps(keywords, ensure_ascii=False), regex,
         datetime.now().strftime('%Y-%m-%d %H:%M:%S'), tid)
    )
    _save_fields_demo(tid, request.form, replace=True)
    return redirect(url_for('admin_templates'))


@app.route('/admin/templates/<int:tid>/delete', methods=['POST'])
@login_required
def admin_template_delete(tid):
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute('SELECT is_system FROM doc_templates WHERE id=?', (tid,)).fetchone()
    if not row or row[0]:
        conn.close()
        return jsonify({'error': '系统预设模板不可删除'}), 400
    conn.execute('DELETE FROM template_fields WHERE template_id=?', (tid,))
    conn.execute('DELETE FROM template_examples WHERE template_id=?', (tid,))
    conn.execute('DELETE FROM doc_templates WHERE id=?', (tid,))
    conn.commit()
    conn.close()
    return jsonify({'status': 'ok'})


@app.route('/admin/templates/<int:tid>/generate_example', methods=['POST'])
@login_required
def admin_generate_example(tid):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    row = conn.execute('SELECT * FROM doc_templates WHERE id=?', (tid,)).fetchone()
    conn.close()
    if not row:
        return jsonify({'error': '模板不存在'}), 404

    try:
        from vision.example_generator import generate_example_for_template
        filename = f'{row["code"]}_example.jpg'
        filepath = os.path.join(EXAMPLE_DIR, filename)
        img_bytes = generate_example_for_template({'name': row['name'], 'fields': _get_template_fields(tid)})
        with open(filepath, 'wb') as f:
            f.write(img_bytes)
        conn = sqlite3.connect(DB_PATH)
        conn.execute(
            '''INSERT INTO template_examples (template_id,image_path,generated_at)
               VALUES (?,?,?)
               ON CONFLICT(template_id) DO UPDATE SET image_path=?,generated_at=?''',
            (tid, filepath, datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
             filepath, datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
        )
        conn.commit()
        conn.close()
    except Exception as e:
        return jsonify({'error': str(e)}), 500

    return redirect(url_for('admin_template_edit', tid=tid))


@app.route('/examples/<path:filename>')
@login_required
def example_image(filename):
    return send_from_directory(EXAMPLE_DIR, filename)


# ─── 统计面板路由 (demo) ──────────────────────────────────────────────────

@app.route('/stats')
@login_required
def stats():
    return render_template('stats.html',
                           username=session['username'],
                           role=session['role'])


@app.route('/stats/data')
@login_required
def stats_data():
    conn = sqlite3.connect(DB_PATH)
    total = conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0]
    approved = conn.execute("SELECT COUNT(*) FROM audit_log WHERE result='APPROVED'").fetchone()[0]
    rejected = conn.execute("SELECT COUNT(*) FROM audit_log WHERE result='REJECTED'").fetchone()[0]
    pending_review = conn.execute("SELECT COUNT(*) FROM audit_log WHERE result='PENDING_REVIEW'").fetchone()[0]
    pending_queue = conn.execute("SELECT COUNT(*) FROM review_queue WHERE status='pending'").fetchone()[0]

    type_rows = conn.execute("SELECT doc_type, COUNT(*) FROM audit_log GROUP BY doc_type").fetchall()
    result_rows = conn.execute("SELECT result, COUNT(*) FROM audit_log GROUP BY result").fetchall()
    daily_rows = conn.execute("""
        SELECT DATE(timestamp) as day, result, COUNT(*)
        FROM audit_log
        WHERE timestamp >= DATE('now', '-30 days')
        GROUP BY day, result
        ORDER BY day
    """).fetchall()
    recent = conn.execute("SELECT * FROM audit_log ORDER BY id DESC LIMIT 10").fetchall()
    conn.close()

    type_map = get_type_name_map()
    type_distribution = {type_map.get(r[0], r[0]): r[1] for r in type_rows}
    result_distribution = {'通过': approved, '拒绝': rejected, '待复审': pending_review}

    return jsonify({
        'total': total, 'approved': approved, 'rejected': rejected,
        'pending_review': pending_review, 'pending_queue': pending_queue,
        'type_distribution': type_distribution,
        'result_distribution': result_distribution,
        'daily_trend': [[r[0], {'APPROVED':'通过','REJECTED':'拒绝','PENDING_REVIEW':'待复审'}.get(r[1],r[1]), r[2]] for r in daily_rows],
        'recent': [[r[0],r[1],r[2],type_map.get(r[3],r[3] or '未知'),r[6]] for r in recent],
    })


# ─── 辅助函数 ─────────────────────────────────────────────────────────────

def _get_template_fields(tid):
    rows = conn_query('SELECT * FROM template_fields WHERE template_id=? ORDER BY sort_order, id', (tid,))
    return [dict(zip(['id','template_id','field_name','field_label','field_category',
                      'ocr_pattern','validation_rule','sort_order'], r)) for r in rows]


def _save_fields_demo(template_id, form_data, replace=False):
    names = form_data.getlist('field_name')
    labels = form_data.getlist('field_label')
    categories = form_data.getlist('field_category')
    patterns = form_data.getlist('ocr_pattern')
    rules = form_data.getlist('validation_rule')

    fields = []
    for i in range(len(names)):
        fname = names[i].strip()
        if not fname:
            continue
        fields.append({
            'field_name': fname,
            'field_label': labels[i].strip() or fname,
            'field_category': categories[i] if i < len(categories) else 'required',
            'ocr_pattern': patterns[i].strip() if i < len(patterns) else '',
            'validation_rule': rules[i].strip() if i < len(rules) else '',
        })

    if replace:
        conn_execute('DELETE FROM template_fields WHERE template_id=?', (template_id,))
    for i, fd in enumerate(fields):
        conn_execute(
            '''INSERT INTO template_fields
               (template_id,field_name,field_label,field_category,ocr_pattern,validation_rule,sort_order)
               VALUES (?,?,?,?,?,?,?)''',
            (template_id, fd['field_name'], fd['field_label'], fd['field_category'],
             fd['ocr_pattern'], fd['validation_rule'], i)
        )


if __name__ == '__main__':
    init_db()
    seed_default_templates()
    seed_history()
    print('=' * 50)
    print('  文档盖章机器人  DEMO 模式')
    print('=' * 50)
    print('  账号：admin / admin123')
    print('  账号：operator1 / op123')
    print('  账号：reviewer1 / reviewer123')
    print()
    print('  访问：http://127.0.0.1:5001')
    print('=' * 50)
    app.run(host='0.0.0.0', port=5001, debug=False)
