"""
demo_app.py
完全自包含的演示程序，无需任何硬件，无需 PaddleOCR / OpenCV。
依赖：flask, pillow, werkzeug
"""

import os
import random
import sqlite3
from datetime import datetime, timedelta
from functools import wraps

from flask import (
    Flask, render_template, request, session,
    redirect, url_for, jsonify, send_from_directory
)
from werkzeug.security import generate_password_hash, check_password_hash
from PIL import Image, ImageDraw, ImageFont
import io

# ─── 路径 ─────────────────────────────────────────────────────────────────────
BASE_DIR    = os.path.dirname(os.path.abspath(__file__))
DB_PATH     = os.path.join(BASE_DIR, 'demo.db')
IMG_DIR     = os.path.join(BASE_DIR, 'demo_images')
TMPL_DIR    = os.path.join(BASE_DIR, 'templates')

os.makedirs(IMG_DIR, exist_ok=True)

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


def seed_history():
    """生成10条历史审计记录和2条待复审记录"""
    conn = sqlite3.connect(DB_PATH)
    count = conn.execute('SELECT COUNT(*) FROM audit_log').fetchone()[0]
    if count > 0:
        conn.close()
        return  # 已有数据，跳过

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

    # 2条待复审
    for i, (name, sid) in enumerate([('赵六', '20210003'), ('张三', '20210001')]):
        ts = (datetime.now() - timedelta(minutes=30+i*15)).strftime('%Y-%m-%d %H:%M:%S')
        doc_data = {
            'title': '综合测评申请',
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
            (ts, 'operator1', 'general',
             str({'姓名': name, '学号': sid}),
             str(['文件日期距今已超过 100 天，请人工确认是否有效']),
             before_path, 'pending')
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
    return render_template('log.html', rows=rows,
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
    return render_template('review.html', pending=pending, all_items=all_items,
                           username=session['username'], role=session['role'])


@app.route('/review/<int:rid>/resolve', methods=['POST'])
@login_required
def resolve_review(rid):
    if session.get('role') not in ('reviewer', 'admin'):
        return jsonify({'error': '权限不足'}), 403
    decision = request.json.get('decision')
    if decision not in ('approved', 'rejected'):
        return jsonify({'error': '无效决策'}), 400

    conn = sqlite3.connect(DB_PATH)
    row = conn.execute('SELECT image_path FROM review_queue WHERE id=?', (rid,)).fetchone()
    conn.execute(
        'UPDATE review_queue SET status=?,reviewer_id=?,resolved_at=?,decision=? WHERE id=?',
        (decision, session['username'], datetime.now().strftime('%Y-%m-%d %H:%M:%S'), decision, rid)
    )
    if decision == 'approved' and row:
        # 生成盖章后图片（用已保存的before图重新画）
        img = Image.open(row[0])
        draw = ImageDraw.Draw(img)
        _draw_stamp(draw, img.width - 140, img.height // 2 + 80)
        after_path = row[0].replace('_before.jpg', '_reviewed_after.jpg')
        img.save(after_path, 'JPEG', quality=92)

        conn.execute(
            'INSERT INTO audit_log (timestamp,operator_id,doc_type,doc_fields,result,errors,before_img,after_img) VALUES (?,?,?,?,?,?,?,?)',
            (datetime.now().strftime('%Y-%m-%d %H:%M:%S'), session['username'],
             'review_approved', '{}', 'APPROVED', '[]', row[0], after_path)
        )
    conn.commit()
    conn.close()
    return jsonify({'status': 'ok'})


@app.route('/images/<path:filename>')
@login_required
def serve_image(filename):
    return send_from_directory(IMG_DIR, filename)


@app.route('/stats')
@login_required
def stats():
    """返回统计数据供主页展示"""
    conn = sqlite3.connect(DB_PATH)
    total    = conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0]
    approved = conn.execute("SELECT COUNT(*) FROM audit_log WHERE result='APPROVED'").fetchone()[0]
    rejected = conn.execute("SELECT COUNT(*) FROM audit_log WHERE result='REJECTED'").fetchone()[0]
    pending  = conn.execute("SELECT COUNT(*) FROM review_queue WHERE status='pending'").fetchone()[0]
    conn.close()
    return jsonify({'total': total, 'approved': approved,
                    'rejected': rejected, 'pending': pending})


if __name__ == '__main__':
    init_db()
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
