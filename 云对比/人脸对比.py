import os
import numpy as np
import face_recognition
from typing import Callable, Dict, List, Tuple
from io import BytesIO
from PIL import Image

# --------------------------------------------------
# 默认距离→相似度转换函数
# --------------------------------------------------
def default_distance_to_similarity(d: float) -> float:
    # 0 距离→1，相似度；0.6 距离→0
    return max(0.0, 1.0 - d / 0.6)

# --------------------------------------------------
# 批量构建人脸编码数据库
# --------------------------------------------------
def build_face_encoding_db(
    directory: str,
    threshold: float = 0.6,
    distance_to_similarity: Callable[[float], float] = default_distance_to_similarity
) -> Tuple[Dict[str, List[np.ndarray]], Callable[[float], float]]:
    """
    扫描目录，提取每张图片中所有人脸编码，返回：
      - encoding_db: { filename: [encoding1, encoding2, …], … }
      - distance_to_similarity: 相似度转换函数（基于 threshold）
    """
    if not os.path.isdir(directory):
        raise FileNotFoundError(f"目录不存在：{directory}")

    def convert(d: float) -> float:
        return max(0.0, 1.0 - d / threshold)

    encoding_db: Dict[str, List[np.ndarray]] = {}
    for fname in os.listdir(directory):
        if not fname.lower().endswith(('.jpg', '.jpeg', '.png')):
            continue
        path = os.path.join(directory, fname)
        try:
            img = face_recognition.load_image_file(path)
            encs = face_recognition.face_encodings(img)
            if encs:
                encoding_db[fname] = encs
        except Exception:
            # 跳过无法处理的文件
            continue

    return encoding_db, convert

# --------------------------------------------------
# 计算两张图的人脸相似度
# --------------------------------------------------
def compare_two_faces(
    path1: str,
    path2: str,
    distance_to_similarity: Callable[[float], float]
) -> float:
    """
    加载两张图像的第一张人脸编码，计算欧式距离并转换为相似度
    """
    encs1 = face_recognition.face_encodings(face_recognition.load_image_file(path1))
    encs2 = face_recognition.face_encodings(face_recognition.load_image_file(path2))
    if not encs1 or not encs2:
        raise ValueError("至少有一张图片未检测到人脸！")
    dist = np.linalg.norm(encs1[0] - encs2[0])
    return distance_to_similarity(dist)

# --------------------------------------------------
# 在数据库中搜索最相似的人脸
# --------------------------------------------------
def search_similar_faces(
    query_path: str,
    encoding_db: Dict[str, List[np.ndarray]],
    distance_to_similarity: Callable[[float], float],
    top_n: int = 5
) -> List[Tuple[str, float]]:
    """
    对查询图像中每张人脸编码，与数据库每条记录的所有编码比较，
    取最小距离，转换相似度，最终返回 top_n 排名前缀列表。
    """
    if top_n <= 0:
        raise ValueError("top_n 必须为正整数")

    query_encs = face_recognition.face_encodings(
        face_recognition.load_image_file(query_path)
    )
    if not query_encs:
        raise ValueError("查询图片未检测到人脸！")

    scores: Dict[str, float] = {}
    for q_enc in query_encs:
        for fname, enc_list in encoding_db.items():
            best_dist = min(np.linalg.norm(q_enc - db_enc) for db_enc in enc_list)
            sim = distance_to_similarity(best_dist)
            scores[fname] = max(scores.get(fname, 0.0), sim)

    # 排序并取前 top_n
    sorted_results = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    return sorted_results[:top_n]

# --------------------------------------------------
# 统计相似度分布
# --------------------------------------------------
def similarity_statistics(results: List[Tuple[str, float]]) -> Dict[str, float]:
    """
    接受 [(filename, similarity), …]，返回统计信息：
      - max, min, mean, median
    """
    sims = [s for _, s in results]
    if not sims:
        return {"max": 0.0, "min": 0.0, "mean": 0.0, "median": 0.0}

    sims_sorted = sorted(sims)
    n = len(sims)
    mean = sum(sims) / n
    median = (
        sims_sorted[n // 2]
        if n % 2 == 1
        else (sims_sorted[n // 2 - 1] + sims_sorted[n // 2]) / 2
    )
    return {
        "max": max(sims_sorted),
        "min": min(sims_sorted),
        "mean": mean,
        "median": median,
    }

# --------------------------------------------------
# 主程序示例
# --------------------------------------------------
if __name__ == "__main__":
    # 1. 构建数据库
    db_dir = "./face_database"
    encoding_db, dist_to_sim = build_face_encoding_db(db_dir, threshold=0.6)

    # 2. 两张图像对比
    try:
        sim_score = compare_two_faces("face1.jpg", "face2.jpg", dist_to_sim)
        print(f"两张人脸相似度：{sim_score:.4f}")
    except ValueError as e:
        print("对比失败：", e)

    # 3. 在数据库中搜索最相似
    try:
        top_matches = search_similar_faces("query.jpg", encoding_db, dist_to_sim, top_n=5)
        print("Top 5 相似结果：")
        for fname, score in top_matches:
            print(f"{fname}: {score:.4f}")
    except ValueError as e:
        print("搜索失败：", e)

    # 4. 输出相似度统计
    stats = similarity_statistics(top_matches)
    print("相似度统计：", stats)
