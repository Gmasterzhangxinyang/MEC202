import logging
import os
import json
import time
from functools import wraps

from flask import (
    Flask, render_template, request, session,
    redirect, url_for, jsonify, send_from_directory, Response
)
from werkzeug.security import check_password_hash

from config import SECRET_KEY, WEB_HOST, WEB_PORT, AUDIT_IMAGE_DIR, DB_PATH, EXAMPLE_IMAGE_DIR, CAMERA_INDEX
from database.models import init_db, seed_demo_data, seed_default_templates
from database.audit import get_recent_logs, get_log_by_id
from database import review_queue as rq
from database import template as tpl_db
import sqlite3

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')

_TEMPLATE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'templates')
app = Flask(__name__, template_folder=_TEMPLATE_DIR)
app.secret_key = SECRET_KEY
app.config['TEMPLATES_AUTO_RELOAD'] = True

@app.after_request
def no_cache(response):
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response

# 延迟初始化（避免 import 时就加载摄像头/串口）
_processor = None
_arm = None


def get_processor():
    global _processor
    if _processor is None:
        from main import DocumentProcessor
        _processor = DocumentProcessor()
    return _processor


def get_arm():
    global _arm
    if _arm is None:
        from hardware.arm import ArmController
        _arm = ArmController()
    return _arm


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
        logging.info('[stamp] 开始处理，用户: %s', session['username'])
        result = get_processor().process(session['username'])
        return jsonify(result)
    except Exception as e:
        logging.exception('[stamp] 处理文件时出错')
        return jsonify({'status': 'error', 'message': str(e)}), 500


# ─── 审计日志 ─────────────────────────────────────────────────────────────────

@app.route('/logs')
@login_required
def logs():
    rows = get_recent_logs(50)
    type_map = tpl_db.get_type_name_map()
    return render_template('log.html',
                           rows=rows,
                           type_map=type_map,
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
    type_map = tpl_db.get_type_name_map()
    all_templates = tpl_db.get_all_templates()
    return render_template('review.html',
                           pending=pending,
                           all_items=all_items,
                           type_map=type_map,
                           all_templates=all_templates,
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

    # 支持手动分类：admin 可以在复审时指定 doc_type
    reclassify = request.json.get('reclassify')

    rq.resolve(review_id, session['username'], decision)

    if decision == 'rejected':
        from database.audit import log_action
        conn = sqlite3.connect(DB_PATH)
        row = conn.execute(
            'SELECT image_path, operator_id, doc_type FROM review_queue WHERE id=?',
            (review_id,)
        ).fetchone()
        conn.close()
        if row:
            actual_type = reclassify or row[2] or 'review_rejected'
            log_action(
                operator_id=row[1], doc_type=actual_type, qr_content=None,
                doc_fields={}, result='REJECTED', errors=['人工复审拒绝'],
                before_img=row[0], after_img=row[0]
            )

    return jsonify({'status': 'ok'})


# ─── 摄像头管理 ───────────────────────────────────────────────────────────────

import threading

_camera_lock = threading.Lock()
_current_camera_index = CAMERA_INDEX
_paper_detected = False


@app.route('/api/cameras')
@login_required
def list_cameras():
    import cv2
    from vision.camera import open_camera
    cameras = []
    for i in range(5):
        try:
            c = open_camera(i)
        except Exception:
            continue
        if c is None:
            continue
        w = int(c.get(cv2.CAP_PROP_FRAME_WIDTH))
        h = int(c.get(cv2.CAP_PROP_FRAME_HEIGHT))
        c.release()
        cameras.append({'index': i, 'resolution': f'{w}x{h}'})
    return jsonify({'cameras': cameras, 'current': _current_camera_index})


@app.route('/api/camera/select', methods=['POST'])
@login_required
def select_camera():
    global _current_camera_index
    idx = request.json.get('index')
    if idx is None or not isinstance(idx, int):
        return jsonify({'error': '无效的摄像头索引'}), 400
    with _camera_lock:
        _current_camera_index = idx
        import config as cfg
        cfg.CAMERA_INDEX = idx
        from vision.camera import SharedCamera
        SharedCamera.reset()
        _processor = None
    return jsonify({'status': 'ok', 'index': idx})


def _processor_reset():
    global _processor
    from vision.camera import SharedCamera
    SharedCamera.reset()
    _processor = None


def _gen_frames():
    import cv2
    import numpy as np
    from vision.camera import SharedCamera
    cam = SharedCamera.get_instance()
    try:
        while True:
            frame = cam.get_frame()
            if frame is None:
                time.sleep(0.03)
                continue
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            has_paper = (np.sum(gray > 180) / gray.size) > 0.3
            global _paper_detected
            _paper_detected = bool(has_paper)
            color = (40, 200, 40) if has_paper else (60, 60, 200)
            label = '已检测到纸张' if has_paper else '未检测到纸张'
            cv2.rectangle(frame, (8, 8), (220, 42), (0, 0, 0), -1)
            cv2.putText(frame, label, (14, 32), cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)
            _, buf = cv2.imencode('.jpg', frame)
            yield (b'--frame\r\nContent-Type: image/jpeg\r\n\r\n' + buf.tobytes() + b'\r\n')
    except Exception:
        time.sleep(1)


@app.route('/video_feed')
@login_required
def video_feed():
    return Response(_gen_frames(), mimetype='multipart/x-mixed-replace; boundary=frame')


@app.route('/paper_status')
@login_required
def paper_status():
    return jsonify({'has_paper': bool(_paper_detected)})


# ─── 模板管理 ─────────────────────────────────────────────────────────────────

@app.route('/admin/templates')
@login_required
@role_required('admin')
def admin_templates():
    templates = tpl_db.get_all_templates()
    return render_template('admin.html',
                           templates=templates,
                           username=session['username'],
                           role=session['role'])


@app.route('/admin/templates/new', methods=['GET', 'POST'])
@login_required
@role_required('admin')
def admin_template_new():
    if request.method == 'GET':
        return render_template('template_edit.html', template=None,
                               username=session['username'], role=session['role'])
    # POST: 创建模板
    name = request.form.get('name', '').strip()
    code = request.form.get('code', '').strip()
    description = request.form.get('description', '').strip()
    keywords_str = request.form.get('keywords', '').strip()
    regex = request.form.get('regex', '').strip()

    if not name or not code:
        return '模板名称和编码不能为空', 400

    keywords = [k.strip() for k in keywords_str.split(',') if k.strip()] if keywords_str else []

    tid = tpl_db.create_template(
        name=name, code=code, description=description,
        classification_keywords=keywords,
        classification_regex=regex,
    )

    # 收集字段
    _save_fields(tid, request.form)

    return redirect(url_for('admin_templates'))


@app.route('/admin/templates/<int:tid>/edit', methods=['GET', 'POST'])
@login_required
@role_required('admin')
def admin_template_edit(tid):
    template = tpl_db.get_template_by_id(tid)
    if not template:
        return '模板不存在', 404

    if request.method == 'GET':
        # 解析 keywords 为逗号分隔字符串供表单使用
        if isinstance(template.get('classification_keywords'), str):
            try:
                kw_list = json.loads(template['classification_keywords'])
                template['keywords'] = ', '.join(kw_list)
            except (json.JSONDecodeError, TypeError):
                template['keywords'] = template['classification_keywords']
        else:
            template['keywords'] = ', '.join(template.get('classification_keywords', []))
        template['regex'] = template.get('classification_regex', '')
        return render_template('template_edit.html', template=template,
                               username=session['username'], role=session['role'])

    # POST: 更新模板
    name = request.form.get('name', '').strip()
    description = request.form.get('description', '').strip()
    keywords_str = request.form.get('keywords', '').strip()
    regex = request.form.get('regex', '').strip()

    keywords = [k.strip() for k in keywords_str.split(',') if k.strip()] if keywords_str else []

    tpl_db.update_template(tid, name=name, description=description,
                           classification_keywords=keywords,
                           classification_regex=regex)

    # 替换字段
    _save_fields(tid, request.form, replace=True)

    return redirect(url_for('admin_templates'))


@app.route('/admin/templates/<int:tid>/delete', methods=['POST'])
@login_required
@role_required('admin')
def admin_template_delete(tid):
    ok = tpl_db.delete_template(tid)
    if ok:
        return jsonify({'status': 'ok'})
    return jsonify({'error': '系统预设模板不可删除'}), 400


@app.route('/admin/templates/<int:tid>/generate_example', methods=['POST'])
@login_required
@role_required('admin')
def admin_generate_example(tid):
    template = tpl_db.get_template_by_id(tid)
    if not template:
        return jsonify({'error': '模板不存在'}), 404

    try:
        from vision.example_generator import generate_example_for_template
        os.makedirs(EXAMPLE_IMAGE_DIR, exist_ok=True)
        filename = f'{template["code"]}_example.jpg'
        filepath = os.path.join(EXAMPLE_IMAGE_DIR, filename)
        img_bytes = generate_example_for_template(template)
        with open(filepath, 'wb') as f:
            f.write(img_bytes)
        tpl_db.set_example_image(tid, filepath)
    except Exception as e:
        logging.exception('生成示例图片失败')
        return jsonify({'error': str(e)}), 500

    return redirect(url_for('admin_template_edit', tid=tid))


# ─── 示例图片访问 ─────────────────────────────────────────────────────────────

@app.route('/examples/<path:filename>')
@login_required
def example_image(filename):
    return send_from_directory(EXAMPLE_IMAGE_DIR, filename)


# ─── 统计面板 ─────────────────────────────────────────────────────────────────

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

    # 类型分布
    type_rows = conn.execute(
        "SELECT doc_type, COUNT(*) FROM audit_log GROUP BY doc_type"
    ).fetchall()

    # 审批结果分布
    result_rows = conn.execute(
        "SELECT result, COUNT(*) FROM audit_log GROUP BY result"
    ).fetchall()

    # 近30天趋势
    daily_rows = conn.execute("""
        SELECT DATE(timestamp) as day, result, COUNT(*)
        FROM audit_log
        WHERE timestamp >= DATE('now', '-30 days')
        GROUP BY day, result
        ORDER BY day
    """).fetchall()

    # 最近10条
    recent = conn.execute(
        "SELECT * FROM audit_log ORDER BY id DESC LIMIT 10"
    ).fetchall()

    conn.close()

    type_map = tpl_db.get_type_name_map()

    type_distribution = {}
    for code, count in type_rows:
        label = type_map.get(code, code)
        type_distribution[label] = count

    result_distribution = {}
    label_map = {'APPROVED': '通过', 'REJECTED': '拒绝', 'PENDING_REVIEW': '待复审'}
    for result, count in result_rows:
        label = label_map.get(result, result)
        result_distribution[label] = count

    return jsonify({
        'total': total,
        'approved': approved,
        'rejected': rejected,
        'pending_review': pending_review,
        'pending_queue': pending_queue,
        'type_distribution': type_distribution,
        'result_distribution': result_distribution,
        'daily_trend': [[r[0], label_map.get(r[1], r[1]), r[2]] for r in daily_rows],
        'recent': [[r[0], r[1], r[2], type_map.get(r[3], r[3] or '未知'), r[6]] for r in recent],
    })


# ─── 图片访问 ─────────────────────────────────────────────────────────────────

@app.route('/images/<path:filename>')
@login_required
def audit_image(filename):
    return send_from_directory(AUDIT_IMAGE_DIR, filename)


# ─── 辅助函数 ─────────────────────────────────────────────────────────────────

def _save_fields(template_id, form_data, replace=False):
    """从表单数据中提取字段列表并保存"""
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
        tpl_db.replace_fields(template_id, fields)
    else:
        for i, fd in enumerate(fields):
            tpl_db.add_field(template_id, fd['field_name'], fd['field_label'],
                             fd['field_category'], fd['ocr_pattern'], fd['validation_rule'], i)


# ─── 启动 ─────────────────────────────────────────────────────────────────────

# ─── 标定功能 ─────────────────────────────────────────────────────────────────

@app.route('/calibration')
@login_required
@role_required('admin')
def calibration_page():
    from hardware.arm import load_calibration
    cal = load_calibration()
    return render_template('calibration.html',
                           calibration=cal,
                           username=session['username'],
                           role=session['role'])


@app.route('/api/calibration/load')
@login_required
def calibration_load():
    from hardware.arm import load_calibration
    return jsonify(load_calibration())


@app.route('/api/calibration/ping', methods=['POST'])
@login_required
def calibration_ping():
    """测试机械臂连通性：发送回中位指令"""
    try:
        arm = get_arm()
        arm.move_to({0: 1500, 1: 1500, 2: 1500, 3: 1500, 4: 1500, 5: 1500}, 1000)
        ok = arm.ping()
        logging.info(f'[标定] ping: connected={ok}')
        return jsonify({'status': 'ok', 'connected': ok})
    except Exception as e:
        logging.error(f'[标定] ping 失败: {e}')
        return jsonify({'status': 'error', 'message': str(e)})


@app.route('/api/calibration/move_single', methods=['POST'])
@login_required
def calibration_move():
    data = request.json
    servo_id = data.get('servo_id')
    pwm = data.get('pwm')
    duration = data.get('duration', 500)
    if servo_id is None or pwm is None:
        return jsonify({'error': '缺少参数'}), 400
    try:
        logging.info(f'[标定] S{servo_id} -> PWM {pwm}')
        get_arm().move_single(int(servo_id), int(pwm), int(duration))
        return jsonify({'status': 'ok'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/calibration/move_multi', methods=['POST'])
@login_required
def calibration_move_multi():
    data = request.json
    pwms = data.get('pwms')
    if not pwms:
        return jsonify({'error': '缺少参数'}), 400
    try:
        get_arm().move_to({int(k): int(v) for k, v in pwms.items()}, 1200)
        return jsonify({'status': 'ok'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/calibration/save_corner', methods=['POST'])
@login_required
def calibration_save_corner():
    data = request.json
    corner_name = data.get('corner')
    pwms = data.get('pwms')
    if not corner_name or not pwms:
        return jsonify({'error': '缺少参数'}), 400
    from hardware.arm import load_calibration, save_calibration
    cal = load_calibration()
    if 'corners' not in cal:
        cal['corners'] = {}
    cal['corners'][corner_name] = pwms
    save_calibration(cal)
    return jsonify({'status': 'ok', 'corners': cal['corners']})


@app.route('/api/calibration/test_move', methods=['POST'])
@login_required
def calibration_test_move():
    data = request.json
    corner = data.get('corner')
    from hardware.arm import load_calibration
    cal = load_calibration()
    corners = cal.get('corners', {})
    if corner not in corners:
        return jsonify({'error': f'角 {corner} 未标定'}), 400
    pwms = {int(k): v for k, v in corners[corner].items()}
    get_arm().move_to(pwms, 1200)
    return jsonify({'status': 'ok'})


@app.route('/api/calibration/reset', methods=['POST'])
@login_required
def calibration_reset():
    from hardware.arm import save_calibration
    save_calibration({})
    return jsonify({'status': 'ok'})


@app.route('/api/calibration/home', methods=['POST'])
@login_required
def calibration_home():
    get_arm().move_to({i: 1500 for i in range(6)}, 1000)
    return jsonify({'status': 'ok'})


# ─── 复审盖章（操作员重新放文档验证后盖章）────────────────────────────────

@app.route('/api/review/pending_stamps')
@login_required
def pending_stamps():
    items = rq.get_approved_for_stamping()
    type_map = tpl_db.get_type_name_map()
    result = []
    for item in items:
        result.append({
            'id': item[0],
            'timestamp': item[1],
            'operator_id': item[2],
            'doc_type': item[3],
            'doc_type_name': type_map.get(item[3], item[3] or '通用'),
        })
    return jsonify({'items': result})


@app.route('/review/stamp/<int:review_id>', methods=['POST'])
@login_required
def review_stamp(review_id):
    try:
        result = get_processor().process_review_stamping(review_id, session['username'])
        return jsonify(result)
    except Exception as e:
        logging.exception('复审盖章失败')
        return jsonify({'status': 'error', 'message': str(e)}), 500


if __name__ == '__main__':
    init_db()
    seed_demo_data()
    seed_default_templates()
    app.run(host=WEB_HOST, port=WEB_PORT, debug=False)
