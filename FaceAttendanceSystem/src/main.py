from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
import cv2
import numpy as np
import os
import base64
import json
from datetime import datetime
import sqlite3
import pickle
import threading

from src.db.db_helper import DBHelper
from src.utils.common import encrypt_password
from src.face.face_recognizer import FaceRecognizer

app = Flask(__name__, template_folder='../templates', static_folder='../static')
app.config['SECRET_KEY'] = 'your-secret-key-here-change-this'
app.config['DATABASE_PATH'] = 'E:/sqlite/attendance_system.db'

# 初始化Flask-Login
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# 全局变量
db_helper = None
face_recognizer = None
init_lock = threading.Lock()
app_initialized = False


def init_app():
    """初始化应用 - 只初始化数据库，人脸识别器延迟加载"""
    global db_helper, face_recognizer, app_initialized

    with init_lock:
        if not app_initialized:
            try:
                print("[INFO] 初始化数据库...")
                db_helper = DBHelper()
                print("[INFO] 数据库初始化完成")
                # 人脸识别器延迟加载，只在需要时初始化
                face_recognizer = None
                app_initialized = True
                print("[INFO] 应用初始化完成")
            except Exception as e:
                print(f"[ERROR] 应用初始化失败: {e}")
                raise


def ensure_face_recognizer_initialized():
    """确保人脸识别器已初始化"""
    global face_recognizer
    if face_recognizer is None:
        with init_lock:
            if face_recognizer is None:
                try:
                    print("[INFO] 延迟初始化人脸识别器...")
                    face_recognizer = FaceRecognizer()
                    face_recognizer.set_db_helper(db_helper)
                    print("[INFO] 人脸识别器初始化完成")
                except Exception as e:
                    print(f"[ERROR] 人脸识别器初始化失败: {e}")
                    raise


@app.before_request
def ensure_initialized():
    """确保应用已初始化"""
    if not app_initialized:
        init_app()


class User(UserMixin):
    def __init__(self, user_id, username, is_admin=0):
        self.id = str(user_id)
        self.username = username
        self.is_admin = bool(is_admin)


@login_manager.user_loader
def load_user(user_id):
    """加载用户"""
    if not db_helper:
        return None

    try:
        # 创建一个新的数据库连接用于用户加载
        conn = sqlite3.connect(app.config['DATABASE_PATH'])
        cursor = conn.cursor()
        cursor.execute('SELECT user_id, username, is_admin FROM users WHERE user_id = ?', (user_id,))
        user_data = cursor.fetchone()
        conn.close()

        if user_data:
            return User(user_data[0], user_data[1], user_data[2])
        return None
    except Exception as e:
        print(f"[ERROR] 加载用户失败: {e}")
        return None


# 路由定义
@app.route('/')
def index():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')

        if not db_helper:
            flash('系统初始化失败，请稍后重试', 'error')
            return render_template('login.html', username=username)

        user_data = db_helper.verify_user(username, password)
        if user_data:
            user = User(user_data['user_id'], username, user_data['is_admin'])
            login_user(user)
            flash('登录成功！', 'success')
            return redirect(url_for('dashboard'))
        else:
            flash('用户名或密码错误', 'error')
            # 登录失败时保留用户名
            return render_template('login.html', username=username)

    return render_template('login.html')


@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('已成功退出登录', 'info')
    return redirect(url_for('login'))


@app.route('/dashboard')
@login_required
def dashboard():
    return render_template('dashboard.html', user=current_user)


@app.route('/register', methods=['GET', 'POST'])
@login_required
def register():
    if not current_user.is_admin:
        flash('需要管理员权限', 'error')
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        is_admin = 1 if request.form.get('is_admin') == 'on' else 0

        if db_helper.add_user(username, password, is_admin):
            flash(f'用户 {username} 注册成功', 'success')
            return redirect(url_for('manage_users'))
        else:
            flash('用户名已存在', 'error')

    return render_template('register_user.html')


@app.route('/face-register')
@login_required
def face_register():
    return render_template('face_register.html')


@app.route('/api/register-face', methods=['POST'])
@login_required
def api_register_face():
    try:
        # 确保人脸识别器已初始化
        ensure_face_recognizer_initialized()
        
        if not db_helper or not face_recognizer:
            return jsonify({'success': False, 'message': '系统未初始化'})

        data = request.get_json()
        image_data = data.get('image')

        if not image_data:
            return jsonify({'success': False, 'message': '未收到图像数据'})

        # 移除base64前缀
        if ',' in image_data:
            image_data = image_data.split(',')[1]

        # 解码base64图像
        img_bytes = base64.b64decode(image_data)
        nparr = np.frombuffer(img_bytes, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

        if img is None:
            return jsonify({'success': False, 'message': '图像解码失败'})

        # 检测和编码面部
        face_encodings = face_recognizer.detect_and_encode(img)

        if len(face_encodings) == 0:
            return jsonify({'success': False, 'message': '未检测到人脸'})

        if len(face_encodings) > 1:
            return jsonify({'success': False, 'message': '请确保只有一张人脸'})

        # 保存面部编码到数据库
        try:
            db_helper.save_face_encoding(current_user.username, face_encodings[0])
            # 重新加载已知人脸
            face_recognizer.load_known_faces_from_db()

            return jsonify({
                'success': True,
                'message': '面部注册成功'
            })
        except Exception as e:
            return jsonify({'success': False, 'message': f'保存失败: {str(e)}'})

    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})


@app.route('/attendance')
@login_required
def attendance():
    return render_template('attendance.html')


@app.route('/api/mark-attendance', methods=['POST'])
@login_required
def api_mark_attendance():
    try:
        # 确保人脸识别器已初始化
        ensure_face_recognizer_initialized()
        
        if not db_helper or not face_recognizer:
            return jsonify({'success': False, 'message': '系统未初始化'})

        data = request.get_json()
        image_data = data.get('image')

        if not image_data:
            return jsonify({'success': False, 'message': '未收到图像数据'})

        if ',' in image_data:
            image_data = image_data.split(',')[1]

        # 解码
        img_bytes = base64.b64decode(image_data)
        nparr = np.frombuffer(img_bytes, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

        if img is None:
            return jsonify({'success': False, 'message': '图像解码失败'})

        # --- 核心修改部分开始 ---

        # 1. 识别用户
        # 返回值可能是: "张三", "Unknown", 或 None
        result_name = face_recognizer.recognize_face(img)

        # 情况A: 未检测到人脸
        if result_name is None:
            return jsonify({'success': False, 'message': '未检测到人脸，请正对摄像头'})

        # 情况B: 检测到人脸，但是陌生人
        if result_name == "Unknown":
            return jsonify({
                'success': False,
                'message': '陌生人员 / 未录入系统',
                'is_unknown': True  # 标记位，前端可用
            })

        # 情况C: 识别成功
        username = result_name

        # --- 核心修改部分结束 ---

        # 记录考勤逻辑 (后续代码基本不变)
        current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        current_hour = datetime.now().hour
        current_minute = datetime.now().minute
        
        # 判断考勤类型：上午12点前为上班，12点后为下班
        att_type = '上班' if current_hour < 12 else '下班'
        
        # 根据时间判断状态
        if att_type == '上班':
            # 上班打卡：9点前为正常，9点后为迟到
            if current_hour < 9:
                status = '正常'
            else:
                status = '迟到'
        else:
            # 下班打卡：18点后为正常，18点前为早退
            if current_hour >= 18:
                status = '正常'
            else:
                status = '早退'

        # 这里的 get_user_by_username 是我们在 db_helper.py 里新加的方法
        user_data = db_helper.get_user_by_username(username)

        if not user_data:
            # 这种情况极少发生，除非数据库里删了人但内存里没更新
            return jsonify({'success': False, 'message': f'数据异常: 用户 {username} 不在库中'})

        user_id = user_data['user_id']
        today = datetime.now().strftime('%Y-%m-%d')

        conn = sqlite3.connect(app.config['DATABASE_PATH'])
        cursor = conn.cursor()
        cursor.execute('''
            SELECT * FROM attendance 
            WHERE user_id = ? AND date(att_time) = ? AND att_type = ?
        ''', (user_id, today, att_type))
        existing = cursor.fetchone()
        conn.close()

        if existing:
            return jsonify({
                'success': False,
                'message': f'{username}，您今日{att_type}已打过卡了'
            })

        db_helper.add_attendance(user_id, current_time, att_type, status)

        return jsonify({
            'success': True,
            'message': f'{username} {att_type}打卡成功',
            'username': username,
            'time': current_time,
            'type': att_type
        })

    except Exception as e:
        print(f"[ERROR] 考勤接口报错: {e}")  # 打印错误到后台
        return jsonify({'success': False, 'message': f'系统错误: {str(e)}'})


@app.route('/my-attendance')
@login_required
def my_attendance():
    if not db_helper:
        flash('系统初始化失败', 'error')
        return redirect(url_for('dashboard'))

    try:
        records = db_helper.get_user_attendance(int(current_user.id))
        return render_template('my_attendance.html', records=records)
    except Exception as e:
        flash(f'获取考勤记录失败: {e}', 'error')
        return render_template('my_attendance.html', records=[])


@app.route('/all-attendance')
@login_required
def all_attendance():
    if not current_user.is_admin:
        flash('需要管理员权限', 'error')
        return redirect(url_for('dashboard'))

    # 获取筛选参数
    filter_name = request.args.get('username', '')
    filter_type = request.args.get('type', '所有')
    filter_status = request.args.get('status', '所有')
    filter_date = request.args.get('date', '')

    try:
        # 调用修改后的 db_helper 方法
        records = db_helper.get_all_attendance(
            user_name=filter_name,
            att_type=filter_type,
            att_status=filter_status,
            date=filter_date
        )
        return render_template('all_attendance.html', records=records,
                             f_name=filter_name, f_type=filter_type,
                             f_status=filter_status, f_date=filter_date)
    except Exception as e:
        flash(f'获取考勤记录失败: {e}', 'error')
        return render_template('all_attendance.html', records=[])


@app.route('/manage-users')
@login_required
def manage_users():
    if not current_user.is_admin:
        flash('需要管理员权限', 'error')
        return redirect(url_for('dashboard'))

    conn = sqlite3.connect(app.config['DATABASE_PATH'])
    cursor = conn.cursor()
    cursor.execute('SELECT user_id, username, is_admin FROM users')
    users = cursor.fetchall()
    conn.close()

    return render_template('manage_users.html', users=users)


@app.route('/api/delete-user/<int:user_id>', methods=['DELETE'])
@login_required
def delete_user(user_id):
    if not current_user.is_admin:
        return jsonify({'success': False, 'message': '权限不足'})

    if int(current_user.id) == user_id:
        return jsonify({'success': False, 'message': '不能删除当前登录用户'})

    try:
        conn = sqlite3.connect(app.config['DATABASE_PATH'])
        cursor = conn.cursor()
        cursor.execute('DELETE FROM users WHERE user_id = ?', (user_id,))
        conn.commit()
        conn.close()

        # 重新加载人脸识别器
        if face_recognizer:
            face_recognizer.load_known_faces_from_db()

        return jsonify({'success': True, 'message': '用户删除成功'})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    # 如果已经登录，直接跳到首页
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        # 自助注册强制为非管理员 (0)
        is_admin = 0

        if not db_helper:
            flash('系统错误', 'error')
            return render_template('signup.html')

        if db_helper.add_user(username, password, is_admin):
            flash(f'注册成功！请登录。', 'success')
            return redirect(url_for('login'))
        else:
            flash('用户名已存在，请换一个。', 'error')

    return render_template('signup.html')

if __name__ == '__main__':
    # 初始化应用
    init_app()

    # 导入webbrowser模块用于自动打开浏览器
    import webbrowser
    import threading
    import time
    import requests
    
    def open_browser():
        """在服务器启动后自动打开浏览器"""
        max_retries = 10
        for i in range(max_retries):
            try:
                # 尝试连接服务器
                response = requests.get('http://localhost:5000', timeout=1)
                if response.status_code < 500:
                    # 服务器已启动，打开浏览器
                    webbrowser.open('http://localhost:5000')
                    print("[INFO] 已自动打开浏览器访问 http://localhost:5000")
                    return
            except:
                # 服务器未启动，等待后重试
                pass
            time.sleep(0.5)
        
        print("[WARNING] 服务器启动超时，请手动打开浏览器访问 http://localhost:5000")
    
    # 创建并启动线程在后台打开浏览器
    browser_thread = threading.Thread(target=open_browser)
    browser_thread.daemon = True
    browser_thread.start()

    app.run(debug=False, host='0.0.0.0', port=5000)
