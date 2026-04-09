import logging
from functools import wraps

from flask import (
    Flask, render_template, request, session,
    redirect, url_for, jsonify, send_from_directory
)
from werkzeug.security import check_password_hash

from config import SECRET_KEY, WEB_HOST, WEB_PORT, AUDIT_IMAGE_DIR, DB_PATH
from database.models import init_db, seed_demo_data
from database.audit import get_recent_logs, get_log_by_id
from database import review_queue as rq
import sqlite3

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')

app = Flask(__name__)
app.secret_key = SECRET_KEY

# 延迟初始化（避免 import 时就加载摄像头/串口）
_processor = None


def get_processor():
    global _processor
    if _processor is None:
        from main import DocumentProcessor
        _processor = DocumentProcessor()
    return _processor


# ─── 权限装饰器 ───────────────────────────────────────────────────────────────

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'username' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated


def role_required(*roles):
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            if session.get('role') not in roles:
                return jsonify({'error': '权限不足'}), 403
            return f(*args, **kwargs)
        return decorated
    return decorator


# ─── 认证 ─────────────────────────────────────────────────────────────────────

@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')

        conn = sqlite3.connect(DB_PATH)
        row = conn.execute(
            'SELECT password_hash, role FROM users WHERE username = ?', (username,)
        ).fetchone()
        conn.close()

        if row and check_password_hash(row[0], password):
            session['username'] = username
            session['role']     = row[1]
            return redirect(url_for('index'))
        error = '账号或密码错误'

    return render_template('login.html', error=error)


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))


# ─── 主操作页 ─────────────────────────────────────────────────────────────────

@app.route('/')
@login_required
def index():
    return render_template('index.html',
                           username=session['username'],
                           role=session['role'])


@app.route('/stamp', methods=['POST'])
@login_required
def stamp():
    """核心接口：触发扫描→验证→盖章全流程"""
    try:
        result = get_processor().process(session['username'])
        return jsonify(result)
    except Exception as e:
        logging.exception('处理文件时出错')
        return jsonify({'status': 'error', 'message': str(e)}), 500


# ─── 审计日志 ─────────────────────────────────────────────────────────────────

@app.route('/logs')
@login_required
def logs():
    rows = get_recent_logs(50)
    return render_template('log.html',
                           rows=rows,
                           username=session['username'],
                           role=session['role'])


@app.route('/logs/<int:log_id>')
@login_required
def log_detail(log_id):
    record = get_log_by_id(log_id)
    if not record:
        return '记录不存在', 404
    return render_template('log_detail.html', record=record,
                           username=session['username'], role=session['role'])


# ─── 人工复审队列 ─────────────────────────────────────────────────────────────

@app.route('/review')
@login_required
def review():
    if session.get('role') not in ('reviewer', 'admin'):
        return redirect(url_for('index'))
    pending = rq.get_pending()
    all_items = rq.get_all(50)
    return render_template('review.html',
                           pending=pending,
                           all_items=all_items,
                           username=session['username'],
                           role=session['role'])


@app.route('/review/<int:review_id>/resolve', methods=['POST'])
@login_required
def resolve_review(review_id):
    if session.get('role') not in ('reviewer', 'admin'):
        return jsonify({'error': '权限不足'}), 403

    decision = request.json.get('decision')
    if decision not in ('approved', 'rejected'):
        return jsonify({'error': '无效的决策'}), 400

    rq.resolve(review_id, session['username'], decision)

    # 如果批准，触发盖章
    if decision == 'approved':
        try:
            # 从复审记录取图片路径，直接盖章（跳过重新扫描）
            conn = sqlite3.connect(DB_PATH)
            row = conn.execute(
                'SELECT image_path, operator_id FROM review_queue WHERE id=?',
                (review_id,)
            ).fetchone()
            conn.close()

            if row:
                from hardware.stamp import StampController
                from database.audit import log_action
                stamper = StampController()
                stamper.stamp()
                log_action(
                    operator_id=row[1],
                    doc_type='review_approved',
                    qr_content=None,
                    doc_fields={},
                    result='APPROVED',
                    errors=[],
                    before_img=row[0],
                    after_img=row[0],
                )
        except Exception as e:
            logging.warning(f'复审后盖章失败：{e}')

    return jsonify({'status': 'ok'})


# ─── 图片访问 ─────────────────────────────────────────────────────────────────

@app.route('/images/<path:filename>')
@login_required
def audit_image(filename):
    return send_from_directory(AUDIT_IMAGE_DIR, filename)


# ─── 启动 ─────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    init_db()
    seed_demo_data()
    app.run(host=WEB_HOST, port=WEB_PORT, debug=False)
