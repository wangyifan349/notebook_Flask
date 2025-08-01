from flask import Flask, request, jsonify
from sentence_transformers import SentenceTransformer
import numpy as np
import faiss

app = Flask(__name__)

# 内存中的 QA 数据
QA_DATA = [
    {"question": "今天天气怎么样？", "answer": "今天天气晴好，适合外出。"},
    {"question": "How to watch a movie?", "answer": "You can use a projector at home or go to a cinema."},
    {"question": "什么是机器学习？", "answer": "Machine learning is a technology that allows computers to improve from data."},
    {"question": "Difference between deep learning and machine learning?", "answer": "Deep learning is a subfield of machine learning, typically using multi-layer neural nets."},
    {"question": "我喜欢吃哪些水果？", "answer": "你喜欢苹果和香蕉。"}
]

corpus_questions = []
for item in QA_DATA:
    corpus_questions.append(item["question"])

# 加载多语种 MPNet 嵌入模型
MODEL = "sentence-transformers/paraphrase-multilingual-mpnet-base-v2"
embedder = SentenceTransformer(MODEL)

# 对语料做向量化并归一化
corpus_embeddings = embedder.encode(corpus_questions, convert_to_numpy=True, normalize_embeddings=True)
dim = corpus_embeddings.shape[1]

# 用 FAISS 建立 IndexFlatIP 索引（内积＝余弦相似度）
index = faiss.IndexFlatIP(dim)
index.add(corpus_embeddings)

@app.route('/search', methods=['POST'])
def search():
    data = request.get_json(force=True)
    q = data.get("q", "").strip()
    k = int(data.get("k", 1))

    if not q:
        return jsonify({"error": "字段 'q' 不能为空"}), 400
    if k < 1:
        return jsonify({"error": "字段 'k' 必须 >= 1"}), 400

    # 将查询向量化并归一化
    q_emb = embedder.encode([q], convert_to_numpy=True, normalize_embeddings=True)

    # 在 FAISS 索引中检索 top-k
    scores, idxs = index.search(q_emb, k)
    scores = scores.flatten()
    idxs = idxs.flatten()

    # 构造返回
    results = []
    for i in range(len(scores)):
        score = scores[i]
        idx = idxs[i]
        qa = QA_DATA[int(idx)]
        results.append({
            "question": qa["question"],
            "answer": qa["answer"],
            "score": round(float(score), 4)
        })

    return jsonify(results)

if __name__ == "__main__":
    app.run(port=5000, debug=True)
