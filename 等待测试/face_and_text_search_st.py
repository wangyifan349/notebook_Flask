#!/usr/bin/env python3
"""
face_and_text_search_st.py

功能：
1. 遍历本地目录，提取每张图片：
   - 128 维人脸向量（face_recognition）
   - 512 维图文共嵌入向量（sentence-transformers CLIP）
2. 构建并保存两个 Faiss 索引及对应的元数据文件：
   - face_index.faiss + face_metadata.pkl
   - clip_index.faiss + clip_metadata.pkl
3. 支持三种检索：
   - 人脸图像检索（L2 距离）
   - CLIP 图像检索（余弦相似度）
   - CLIP 文本检索（余弦相似度）

依赖：
    pip install face_recognition faiss-cpu opencv-python numpy torch sentence-transformers
"""

import os
import pickle
import numpy
import faiss
import cv2
import face_recognition
from sentence_transformers import SentenceTransformer

# 所有常量声明
FACE_VECTOR_DIMENSION = 128                       # 人脸向量维度
CLIP_VECTOR_DIMENSION = 512                       # CLIP 向量维度

FACE_INDEX_FILENAME = "face_index.faiss"          # 人脸索引文件名
CLIP_INDEX_FILENAME = "clip_index.faiss"          # CLIP 索引文件名

FACE_METADATA_FILENAME = "face_metadata.pkl"      # 人脸元数据文件名（图片路径列表）
CLIP_METADATA_FILENAME = "clip_metadata.pkl"      # CLIP 元数据文件名（图片路径列表）

SUPPORTED_IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png")  # 支持的图片后缀

CLIP_MODEL_NAME = "openai/clip-vit-base-patch32"   # CLIP 模型名称
DEVICE = "cuda" if os.environ.get("CUDA_VISIBLE_DEVICES") else "cpu"  # 运行设备选择

# 加载 CLIP 模型
clip_encoder = SentenceTransformer(CLIP_MODEL_NAME)  # 用于图像和文本编码

# 主流程开始，提示用户选择操作
user_choice_prompt = (
    "请选择操作：\n"
    "  1. build       — 构建索引\n"
    "  2. query_image — 图像检索\n"
    "  3. query_text  — 文本检索\n"
    "输入 1/2/3 并回车: "
)
choice = input(user_choice_prompt).strip()

if choice == "1":
    # 构建索引流程
    root_directory = input("请输入图片根目录路径: ").strip()

    all_face_vectors = []   # 存储所有人脸特征向量
    all_clip_vectors = []   # 存储所有 CLIP 特征向量
    all_image_paths = []    # 存储对应图片路径列表

    # 遍历目录及子目录
    for current_root, directory_names, file_names in os.walk(root_directory):
        for file_name in file_names:
            lower_name = file_name.lower()
            if not lower_name.endswith(SUPPORTED_IMAGE_EXTENSIONS):
                continue   # 跳过非图片文件
            full_path = os.path.join(current_root, file_name)

            # 读取图片文件
            loaded_image = cv2.imread(full_path)
            face_encoding = None
            if loaded_image is not None:
                # 转为 RGB 用于 face_recognition
                rgb_image = cv2.cvtColor(loaded_image, cv2.COLOR_BGR2RGB)
                face_encodings = face_recognition.face_encodings(rgb_image)
                if face_encodings:
                    # 只取第一张检测到的人脸编码
                    face_encoding = numpy.asarray(face_encodings[0], dtype="float32")

            # 提取 CLIP 图像向量
            clip_vector = None
            if loaded_image is not None:
                rgb_for_clip = cv2.cvtColor(loaded_image, cv2.COLOR_BGR2RGB)
                clip_embeddings = clip_encoder.encode(
                    [rgb_for_clip],
                    batch_size=1,
                    convert_to_numpy=True,
                    normalize_embeddings=True
                )
                clip_vector = clip_embeddings[0].astype("float32")

            # 如果任一向量提取失败，则跳过该图片
            if face_encoding is None or clip_vector is None:
                print(f"[Skip] 无法提取向量: {full_path}")
                continue

            # 添加到列表
            all_face_vectors.append(face_encoding)
            all_clip_vectors.append(clip_vector)
            all_image_paths.append(full_path)
            print(f"[Processed] {full_path}")

    # 构建并保存人脸索引（L2 距离）
    if all_face_vectors:
        face_matrix = numpy.vstack(all_face_vectors)  # 堆叠为二维矩阵
        face_index = faiss.IndexFlatL2(FACE_VECTOR_DIMENSION)
        face_index.add(face_matrix)                   # 添加向量
        faiss.write_index(face_index, FACE_INDEX_FILENAME)  # 保存索引
        with open(FACE_METADATA_FILENAME, "wb") as f:
            pickle.dump(all_image_paths, f)           # 保存路径列表
        print(f"[Built] 人脸索引已保存: {FACE_INDEX_FILENAME}")
    else:
        print("[Error] 未提取到任何人脸向量。")

    # 构建并保存 CLIP 索引（内积近似余弦相似度）
    if all_clip_vectors:
        clip_matrix = numpy.vstack(all_clip_vectors)
        clip_index = faiss.IndexFlatIP(CLIP_VECTOR_DIMENSION)
        clip_index.add(clip_matrix)
        faiss.write_index(clip_index, CLIP_INDEX_FILENAME)
        with open(CLIP_METADATA_FILENAME, "wb") as f:
            pickle.dump(all_image_paths, f)
        print(f"[Built] CLIP 索引已保存: {CLIP_INDEX_FILENAME}")
    else:
        print("[Error] 未提取到任何 CLIP 向量。")

elif choice == "2":
    # 图像检索流程
    query_image_path = input("请输入查询图片路径: ").strip()
    method = input("选择检索类型 face/clip: ").strip().lower()
    top_k_input = input("请输入返回结果数量 top_k（默认5）: ").strip()
    try:
        top_k = int(top_k_input)
    except ValueError:
        top_k = 5  # 默认返回 5 条结果

    # 读取查询图片
    loaded_query_image = cv2.imread(query_image_path)
    query_vector = None
    index_to_search = None
    metadata_to_search = None

    if method == "face":
        # 人脸检索：提取人脸向量
        if loaded_query_image is not None:
            rgb_query = cv2.cvtColor(loaded_query_image, cv2.COLOR_BGR2RGB)
            face_encs = face_recognition.face_encodings(rgb_query)
            if face_encs:
                query_vector = numpy.asarray(face_encs[0], dtype="float32")
        index_to_search = faiss.read_index(FACE_INDEX_FILENAME)  # 加载人脸索引
        with open(FACE_METADATA_FILENAME, "rb") as f:
            metadata_to_search = pickle.load(f)
        metric_name = "L2"
    else:
        # CLIP 图像检索：提取 CLIP 向量
        if loaded_query_image is not None:
            rgb_query = cv2.cvtColor(loaded_query_image, cv2.COLOR_BGR2RGB)
            clip_embeddings = clip_encoder.encode(
                [rgb_query],
                batch_size=1,
                convert_to_numpy=True,
                normalize_embeddings=True
            )
            query_vector = clip_embeddings[0].astype("float32")
        index_to_search = faiss.read_index(CLIP_INDEX_FILENAME)  # 加载 CLIP 索引
        with open(CLIP_METADATA_FILENAME, "rb") as f:
            metadata_to_search = pickle.load(f)
        metric_name = "IP"

    # 如果向量或索引加载失败
    if query_vector is None or index_to_search is None:
        print("[Error] 无法提取查询向量或读取索引文件。")
    else:
        # 执行搜索
        query_matrix = numpy.expand_dims(query_vector, axis=0)
        distances, indices = index_to_search.search(query_matrix, top_k)
        print(f"\n[Results] {method} search, metric={metric_name}, top {top_k}:")
        for dist, idx in zip(distances[0], indices[0]):
            print(f"  {metadata_to_search[idx]}    Score/Distance: {dist:.4f}")

elif choice == "3":
    # 文本检索流程
    query_text = input("请输入查询文本描述: ").strip()
    top_k_input = input("请输入返回结果数量 top_k（默认5）: ").strip()
    try:
        top_k = int(top_k_input)
    except ValueError:
        top_k = 5

    # 提取文本向量
    text_embedding = clip_encoder.encode(
        [query_text],
        batch_size=1,
        convert_to_numpy=True,
        normalize_embeddings=True
    )[0].astype("float32")

    # 加载 CLIP 索引和元数据
    clip_index = faiss.read_index(CLIP_INDEX_FILENAME)
    with open(CLIP_METADATA_FILENAME, "rb") as f:
        clip_metadata = pickle.load(f)

    # 执行文本查询
    query_matrix = numpy.expand_dims(text_embedding, axis=0)
    scores, indices = clip_index.search(query_matrix, top_k)
    print(f"\n[Results] CLIP text search, top {top_k}:")
    for score, idx in zip(scores[0], indices[0]):
        print(f"  {clip_metadata[idx]}    Score: {score:.4f}")

else:
    # 无效选择时退出
    print("[Error] 无效选择，程序结束。")
