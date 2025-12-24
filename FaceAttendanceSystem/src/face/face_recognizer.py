import face_recognition
import cv2
import numpy as np
import pickle


class FaceRecognizer:
    def __init__(self, db_helper=None):
        self.db_helper = db_helper
        self.known_face_encodings = []
        self.known_face_names = []

        if db_helper:
            self.load_known_faces_from_db()

    def set_db_helper(self, db_helper):
        self.db_helper = db_helper
        if db_helper:
            self.load_known_faces_from_db()

    def load_known_faces_from_db(self):
        """从数据库加载已知面部信息"""
        if not self.db_helper:
            return

        try:
            rows = self.db_helper.get_all_users_with_face()
            self.known_face_encodings = []
            self.known_face_names = []

            for username, face_blob in rows:
                if face_blob:
                    try:
                        face_encoding = pickle.loads(face_blob)
                        if isinstance(face_encoding, np.ndarray) and face_encoding.shape[0] == 128:
                            self.known_face_encodings.append(face_encoding)
                            self.known_face_names.append(username)
                    except Exception:
                        continue

            print(f"[INFO] 已加载 {len(self.known_face_names)} 个已知人脸: {self.known_face_names}")

        except Exception as e:
            print(f"[ERROR] 从数据库加载人脸失败: {e}")

    def detect_and_encode(self, image):
        """检测并编码面部 (用于注册)"""
        try:
            rgb_image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
            face_locations = face_recognition.face_locations(rgb_image, model="hog")
            if len(face_locations) == 0:
                return []
            face_encodings = face_recognition.face_encodings(rgb_image, face_locations)
            return face_encodings
        except Exception as e:
            print(f"[ERROR] 编码失败: {e}")
            return []

    def detect_faces(self, image):
        """仅检测位置 (用于前端画框)"""
        try:
            rgb_image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
            return face_recognition.face_locations(rgb_image, model="hog")
        except:
            return []

    def recognize_face(self, image):
        """
        识别人脸
        返回:
            - 用户名 (识别成功)
            - "Unknown" (是人脸，但未录入)
            - None (未检测到人脸)
        """
        # 确保数据已加载
        if len(self.known_face_encodings) == 0:
            if self.db_helper:
                self.load_known_faces_from_db()

            # 如果数据库还是空的，但检测到了人脸，那就是陌生人
            if len(self.known_face_encodings) == 0:
                print("[DEBUG] 数据库中没有已注册的人脸数据")
                temp_encoding = self.detect_and_encode(image)
                return "Unknown" if len(temp_encoding) > 0 else None

        try:
            # 1. 检测当前人脸
            face_encodings = self.detect_and_encode(image)

            if len(face_encodings) == 0:
                return None  # 没脸

            # 取第一张脸进行识别
            unknown_face_encoding = face_encodings[0]

            # 2. 计算与数据库中所有人的“距离” (距离越小越像)
            # face_distance 返回一个数组，对应 known_face_encodings
            face_distances = face_recognition.face_distance(self.known_face_encodings, unknown_face_encoding)

            # 找到最小距离的索引
            best_match_index = np.argmin(face_distances)
            min_distance = face_distances[best_match_index]

            print(f"[DEBUG] 识别结果: 最像 {self.known_face_names[best_match_index]}, 差异度: {min_distance:.4f}")

            # 3. 判断是否匹配
            # tolerance 默认为 0.6，越低要求越严格。建议 0.5-0.6 之间
            # 如果差异度小于 0.5，我们认为匹配成功
            if min_distance < 0.55:
                return self.known_face_names[best_match_index]
            else:
                return "Unknown"  # 也就是陌生人

        except Exception as e:
            print(f"[ERROR] 面部识别出错: {e}")
            return None
