import sqlite3
import pickle
import hashlib
from pathlib import Path

# 指定数据库路径
DB_PATH = Path(r"E:\sqlite\attendance_system.db")


# --- 将加密函数直接写在这里，防止导入报错 ---
def encrypt_password(password):
    if not password: return ""
    return hashlib.sha256(str(password).encode('utf-8')).hexdigest()


# ----------------------------------------

class DBHelper:
    def __init__(self):
        print(f"[DEBUG] 数据库路径: {DB_PATH}")

        # 确保目录存在
        if not DB_PATH.parent.exists():
            DB_PATH.parent.mkdir(parents=True, exist_ok=True)

        # 连接数据库
        self.conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        self.conn.execute("PRAGMA busy_timeout = 5000")
        self.cursor = self.conn.cursor()

        self.init_tables()

    def init_tables(self):
        """初始化数据库表"""
        try:
            # 用户表
            self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL,
                face_encodings BLOB,
                is_admin INTEGER DEFAULT 0
            )
            ''')

            # 考勤表
            self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS attendance (
                att_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                att_time TEXT NOT NULL,
                att_type TEXT DEFAULT '上班',
                status TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            )
            ''')

            # 检查是否需要创建默认管理员
            self.cursor.execute("SELECT count(*) FROM users WHERE username='admin'")
            if self.cursor.fetchone()[0] == 0:
                admin_pwd = encrypt_password("123456")  # 默认密码 123456
                self.cursor.execute('INSERT INTO users (username, password, is_admin) VALUES (?, ?, ?)',
                                    ("admin", admin_pwd, 1))
                self.conn.commit()
                print("[DEBUG] 默认管理员 admin 创建成功")

            self.conn.commit()
        except sqlite3.Error as e:
            print(f"[ERROR] 初始化数据库表失败: {e}")

    def verify_user(self, username, password):
        """验证登录"""
        try:
            # 1. 计算输入密码的 SHA-256
            hashed_input = encrypt_password(password)

            # 2. 查询数据库
            self.cursor.execute('SELECT user_id, is_admin, password FROM users WHERE username = ?', (username,))
            result = self.cursor.fetchone()

            if result:
                db_password = result[2]
                # 3. 比对哈希值
                if hashed_input == db_password:
                    return {"user_id": result[0], "is_admin": result[1]}

            return None
        except sqlite3.Error as e:
            print(f"[ERROR] 验证用户失败: {e}")
            return None

    def add_user(self, username, password, is_admin=0):
        """添加用户"""
        try:
            hashed_pwd = encrypt_password(password)
            self.cursor.execute('INSERT INTO users (username, password, is_admin) VALUES (?, ?, ?)',
                                (username, hashed_pwd, is_admin))
            self.conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False  # 用户名已存在
        except sqlite3.Error:
            return False

    def get_user_by_username(self, username):
        """无密码查询用户（用于人脸识别）"""
        try:
            self.cursor.execute('SELECT user_id, is_admin FROM users WHERE username = ?', (username,))
            result = self.cursor.fetchone()
            if result:
                return {"user_id": result[0], "is_admin": result[1]}
            return None
        except sqlite3.Error:
            return None

    # --- 这里是筛选功能的关键 ---
    def get_all_attendance(self, user_name=None, att_type=None, att_status=None, date=None):
        try:
            sql = '''
                SELECT u.username, a.att_time, a.att_type, a.status 
                FROM attendance a
                JOIN users u ON a.user_id = u.user_id
                WHERE 1=1
            '''
            params = []

            if user_name and user_name.strip():
                sql += " AND u.username LIKE ?"
                params.append(f'%{user_name.strip()}%')

            if att_type and att_type != '所有':
                sql += " AND a.att_type = ?"
                params.append(att_type)

            if att_status and att_status != '所有':
                sql += " AND a.status = ?"
                params.append(att_status)

            if date and date.strip():
                sql += " AND date(a.att_time) = ?"
                params.append(date)

            sql += " ORDER BY a.att_time DESC"

            self.cursor.execute(sql, params)
            return self.cursor.fetchall()
        except sqlite3.Error as e:
            print(f"[ERROR] 查询考勤失败: {e}")
            return []

    # --- 其他辅助函数 ---
    def save_face_encoding(self, username, face_encoding):
        try:
            blob = pickle.dumps(face_encoding)
            self.cursor.execute('UPDATE users SET face_encodings = ? WHERE username = ?', (blob, username))
            self.conn.commit()
            return True
        except:
            return False

    def get_all_users_with_face(self):
        try:
            self.cursor.execute('SELECT username, face_encodings FROM users WHERE face_encodings IS NOT NULL')
            return self.cursor.fetchall()
        except:
            return []

    def add_attendance(self, user_id, att_time, att_type, status):
        try:
            self.cursor.execute('INSERT INTO attendance (user_id, att_time, att_type, status) VALUES (?, ?, ?, ?)',
                                (user_id, att_time, att_type, status))
            self.conn.commit()
            return True
        except:
            return False

    def get_user_attendance(self, user_id):
        try:
            self.cursor.execute(
                'SELECT att_time, att_type, status FROM attendance WHERE user_id = ? ORDER BY att_time DESC',
                (user_id,))
            return self.cursor.fetchall()
        except:
            return []

    def close(self):
        try:
            self.conn.close()
        except:
            pass
