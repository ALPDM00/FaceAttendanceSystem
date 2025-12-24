import hashlib
from datetime import datetime

def encrypt_password(password: str) -> str:
    """加密密码"""
    return hashlib.sha256(password.encode()).hexdigest()

def verify_password(input_password: str, hashed_password: str) -> bool:
    """验证密码"""
    return encrypt_password(input_password) == hashed_password

def format_time(timestamp: str) -> str:
    """格式化时间显示"""
    try:
        dt = datetime.strptime(timestamp, '%Y-%m-%d %H:%M:%S')
        return dt.strftime('%Y-%m-%d %H:%M:%S')
    except:
        return timestamp

def get_current_time() -> str:
    """获取当前时间字符串"""
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')