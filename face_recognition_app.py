# face_recognition_app.py

import os
import dlib
import cv2
import numpy as np
from scipy.spatial import distance
# —— 模型加载 / Model Loading —— #
detector = dlib.get_frontal_face_detector()  # 人脸检测器 / face detector
shape_predictor = dlib.shape_predictor("shape_predictor_68_face_landmarks.dat")  # 68 点关键点模型 / 68-point landmark model
face_rec_model = dlib.face_recognition_model_v1("dlib_face_recognition_resnet_model_v1.dat")  # 人脸识别模型 / face recognition model
# —— 提取人脸关键点 / Extract Face Landmarks —— #
def extract_landmarks(image_path):
    """
    输入：图像路径
    Input: image file path
    输出：每张人脸 68 个 (x, y) 坐标列表
    Output: list of 68 (x, y) landmark coordinates per face
    """
    img = cv2.imread(image_path)  # 读取图像 / read image
    if img is None:
        return []
    rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)  # 转为 RGB / convert to RGB
    faces = detector(rgb, 1)  # 检测人脸 / detect faces
    all_landmarks = []
    for face in faces:
        shape = shape_predictor(rgb, face)  # 预测关键点 / predict landmarks
        coords = np.array([[pt.x, pt.y] for pt in shape.parts()])  # 提取坐标 / extract coords
        all_landmarks.append(coords)
    return all_landmarks
# —— 提取 128D 人脸特征向量 / Extract 128D Face Descriptors —— #
def extract_face_descriptor(image_path):
    """
    输入：图像路径
    Input: image file path
    输出：每张人脸的 128D 特征向量列表
    Output: list of 128D face descriptor arrays
    """
    img = cv2.imread(image_path)
    if img is None:
        return []
    rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    faces = detector(rgb, 1)
    descriptors = []
    for face in faces:
        shape = shape_predictor(rgb, face)
        descriptor = face_rec_model.compute_face_descriptor(rgb, shape)  # 计算特征向量 / compute descriptor
        descriptors.append(np.array(descriptor))
    return descriptors
# —— 对比两张人脸 / Compare Two Faces —— #
def compare_faces(feat1, feat2, method="cosine"):
    """
    feat1, feat2: 两个 128D 向量 / two 128D descriptor arrays
    method: "cosine" 或 "l2"
    返回：相似度得分 / returns similarity score
    - 余弦：越接近 1 越相似 / closer to 1 is more similar
    - L2：越接近 0 越相似 / closer to 0 is more similar
    """
    if method == "cosine":
        return 1 - distance.cosine(feat1, feat2)
    elif method == "l2":
        return np.linalg.norm(feat1 - feat2)
    else:
        raise ValueError("method must be 'cosine' or 'l2'")
# —— 构建人脸数据库 / Build Face Database —— #
def build_face_database(folder_path):
    """
    folder_path: 存放人脸图片的文件夹
    folder_path: directory of face images
    返回：{ filename: (descriptor, landmarks) }
    returns: dict mapping filename to (descriptor, landmarks)
    """
    db = {}
    for fname in os.listdir(folder_path):
        if fname.lower().endswith((".jpg", ".png")):
            path = os.path.join(folder_path, fname)
            descs = extract_face_descriptor(path)  # 特征向量 / descriptors
            lmarks = extract_landmarks(path)       # 关键点 / landmarks
            if descs and lmarks:
                db[fname] = (descs[0], lmarks[0])  # 仅使用首张人脸 / use first face
    return db
# —— 人脸搜索 / Search Face —— #
def search_face(query_image, db, top_k=5, method="cosine"):
    """
    query_image: 查询图片路径 / query image path
    db: 人脸数据库 / face database
    top_k: 返回最相似的前 K 个 / top K results
    method: "cosine" or "l2"
    返回：[(filename, score, landmarks), ...]
    returns: list of (filename, score, landmarks)
    """
    q_descs = extract_face_descriptor(query_image)
    q_lmarks = extract_landmarks(query_image)
    if not q_descs or not q_lmarks:
        return []
    qdesc = q_descs[0]
    qlmark = q_lmarks[0]
    results = []
    for fname, (desc, lmark) in db.items():
        score = compare_faces(qdesc, desc, method=method)
        if method == "l2":
            score = -score  # 使距离较小的排前面 / invert for sorting
        results.append((fname, score, lmark))
    results.sort(key=lambda x: x[1], reverse=True)
    return results[:top_k]
# —— 主函数示例 / Main Function Example —— #
if __name__ == "__main__":
    face_db = build_face_database("faces_folder")  # 构建数据库 / build database
    # 对比示例 / comparison example
    desc1 = extract_face_descriptor("person1.jpg")
    desc2 = extract_face_descriptor("person2.jpg")
    if desc1 and desc2:
        print("Cosine Similarity:", compare_faces(desc1[0], desc2[0], method="cosine"))
        print("L2 Distance:", compare_faces(desc1[0], desc2[0], method="l2"))
    # 搜索示例 / search example
    matches = search_face("query.jpg", face_db, top_k=3, method="cosine")
    for name, sim, landmarks in matches:
        print(f"{name}: {sim:.4f}, first landmark: {landmarks[0]}")
