import os
import faiss
import numpy as np
from sentence_transformers import SentenceTransformer
from sklearn.decomposition import PCA
from sklearn.preprocessing import StandardScaler

# --------------------
# 配置
# --------------------
MODEL_NAME = "all-MiniLM-L6-v2"  # 兼顾速度与效果的轻量模型
EMBED_DIM = 384                 # all-MiniLM-L6-v2 的向量维度
USE_SCALER = False              # 是否使用 StandardScaler（可改善某些数据分布）
USE_PCA = False                 # 是否使用 PCA 降维（仅示范）
PCA_DIM = 128
TOP_K = 5                       # 检索返回的段落数

# --------------------
# 示例语料（替换为你的文档段落）
# --------------------
documents = [
    "人工智能是计算机科学的一个分支，致力于创建智能机器。",
    "机器学习是人工智能的一个子领域，通过数据训练模型以实现预测或决策。",
    "深度学习使用多层神经网络来自动学习特征表示，广泛应用于图像和语音领域。",
    "支持向量机是一种监督学习模型，常用于分类问题。",
    "自然语言处理使计算机能够理解和生成自然语言文本。",
    "FAISS 是 Facebook 开源的相似性搜索库，用于快速向量检索。",
    "Sentence-Transformers 可以将句子编码为固定维度向量，便于语义检索和聚类。",
]

# --------------------
# 1) 加载模型并对文档进行编码
# --------------------
model = SentenceTransformer(MODEL_NAME)
embeddings = model.encode(documents, show_progress_bar=True, convert_to_numpy=True, normalize_embeddings=False)
# embeddings.shape -> (n_docs, EMBED_DIM)

# --------------------
# 2) 可选标准化 / 降维
# --------------------
if USE_SCALER:
    scaler = StandardScaler()
    embeddings = scaler.fit_transform(embeddings)

if USE_PCA:
    pca = PCA(n_components=PCA_DIM)
    embeddings = pca.fit_transform(embeddings)
    emb_dim = PCA_DIM
else:
    emb_dim = embeddings.shape[1]

# 对于余弦相似度，FAISS 最简单安全的方式是把向量归一化，然后用 Inner Product 索引
# 归一化向量
def normalize_np(a, axis=1, eps=1e-12):
    norm = np.linalg.norm(a, axis=axis, keepdims=True)
    return a / (norm + eps)

embeddings = normalize_np(embeddings, axis=1).astype('float32')

# --------------------
# 3) 建立 FAISS 索引
# --------------------
index = faiss.IndexFlatIP(emb_dim)  # 内积（dot-product）索引，适合归一化向量实现 cosine
index.add(embeddings)               # 添加向量到索引
print(f"Indexed {index.ntotal} vectors, dim = {emb_dim}")

# 保存/加载索引示例（可选）
INDEX_FILE = "faiss_index.bin"
# faiss.write_index(index, INDEX_FILE)
# index = faiss.read_index(INDEX_FILE)

# --------------------
# 4) 查询函数：检索 top_k 段落并返回拼接答案
# --------------------
def retrieve(query, top_k=TOP_K):
    q_emb = model.encode([query], convert_to_numpy=True, normalize_embeddings=False)
    if USE_SCALER:
        q_emb = scaler.transform(q_emb)
    if USE_PCA:
        q_emb = pca.transform(q_emb)
    q_emb = normalize_np(q_emb, axis=1).astype('float32')

    D, I = index.search(q_emb, top_k)  # D: 相似度分数（内积）， I: 索引位置
    scores = D[0]
    indices = I[0]
    results = []
    for score, idx in zip(scores, indices):
        if idx < 0:
            continue
        results.append((documents[idx], float(score), idx))
    return results

# 简单的答案生成：把检索到的段落按相似度拼成简短回答
def answer_query(query, top_k=TOP_K, max_chars=1000):
    retrieved = retrieve(query, top_k=top_k)
    if not retrieved:
        return "未检索到相关内容。"
    # 以最相关段落为主，拼接额外段落作为上下文
    pieces = []
    for doc, score, idx in retrieved:
        pieces.append(f"(score={score:.4f}) {doc}")
    answer = "\n\n".join(pieces)
    # 限制长度
    if len(answer) > max_chars:
        answer = answer[:max_chars].rsplit("\n\n", 1)[0] + "\n\n..."
    return answer

# --------------------
# 5) 交互示例
# --------------------
if __name__ == "__main__":
    while True:
        q = input("\n请输入问题（回车退出）：").strip()
        if q == "":
            break
        resp = answer_query(q, top_k=5)
        print("\n--- 检索结果与拼接答案 ---")
        print(resp)
