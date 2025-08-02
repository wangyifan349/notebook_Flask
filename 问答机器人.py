from flask import Flask, request, jsonify
from sentence_transformers import SentenceTransformer
import faiss

app = Flask(__name__)

# 内存中的 QA 数据，支持 question、answer、可选的 code
QA_DATA = [
    {
        "question": "如何计算两个向量的余弦相似度？",
        "answer": "可以用 numpy 实现：cos_sim = (a·b) / (||a|| * ||b||)。",
        "code": """\
import numpy as np

def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    # 点积
    dot = np.dot(a, b)
    # L2 范数
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    return dot / (norm_a * norm_b)

# 示例
vec1 = np.array([1.0, 2.0, 3.0])
vec2 = np.array([4.0, 5.0, 6.0])
print("Cosine similarity:", cosine_similarity(vec1, vec2))
"""
    },
    {
        "question": "如何计算两个向量的 L2 距离？",
        "answer": "L2 距离即欧氏距离：||a - b||₂。",
        "code": """\
import numpy as np

def l2_distance(a: np.ndarray, b: np.ndarray) -> float:
    return np.linalg.norm(a - b)

# 示例
vec1 = np.array([1.0, 2.0, 3.0])
vec2 = np.array([4.0, 5.0, 6.0])
print("L2 distance:", l2_distance(vec1, vec2))
"""
    },
    {
        "question": "什么是 RSA 加密？",
        "answer": "RSA 是一种非对称加密算法，使用公钥加密、私钥解密。",
        "code": """\
from Crypto.PublicKey import RSA
from Crypto.Cipher import PKCS1_OAEP

# 生成密钥对
key = RSA.generate(2048)
private_key = key.export_key()
public_key = key.publickey().export_key()

# 加密
rsa_pub = RSA.import_key(public_key)
cipher = PKCS1_OAEP.new(rsa_pub)
ciphertext = cipher.encrypt(b"Hello RSA")

# 解密
rsa_priv = RSA.import_key(private_key)
dec_cipher = PKCS1_OAEP.new(rsa_priv)
plaintext = dec_cipher.decrypt(ciphertext)
print(plaintext)  # b'Hello RSA'
"""
    },
    {
        "question": "如何使用 AES 对称加密？",
        "answer": "AES 是对称加密算法，需要相同的密钥进行加解密。",
        "code": """\
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad, unpad

key = b'16byteslongkey!!'  # 16 字节密钥
data = b"Secret Message"

# 加密（ECB 模式示例）
cipher_enc = AES.new(key, AES.MODE_ECB)
ct = cipher_enc.encrypt(pad(data, AES.block_size))

# 解密
cipher_dec = AES.new(key, AES.MODE_ECB)
pt = unpad(cipher_dec.decrypt(ct), AES.block_size)
print(pt)  # b'Secret Message'
"""
    },
    {
        "question": "什么是 PCR（聚合酶链式反应）？",
        "answer": "PCR 是一种体外扩增 DNA 的技术，通过重复加热-退火-延伸循环来指数级扩增特定 DNA 片段。",
    },
    {
        "question": "基因组测序与转录组测序有什么区别？",
        "answer": "基因组测序（Genome Sequencing）测整个基因组，转录组测序（RNA-Seq）只测活细胞中表达的 RNA。",
    },
]

# 构建语料
corpus_questions = [item["question"] for item in QA_DATA]

# 加载多语种嵌入模型
embedder = SentenceTransformer(
    "sentence-transformers/paraphrase-multilingual-mpnet-base-v2"
)
corpus_embeddings = embedder.encode(
    corpus_questions, convert_to_numpy=True, normalize_embeddings=True
)

# 建立 FAISS 索引
dim = corpus_embeddings.shape[1]
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

    # 查询向量化并归一化
    q_emb = embedder.encode([q], convert_to_numpy=True, normalize_embeddings=True)
    scores, idxs = index.search(q_emb, k)
    scores = scores.flatten()
    idxs   = idxs.flatten()

    # 构造返回
    results = []
    for score, idx in zip(scores, idxs):
        qa = QA_DATA[int(idx)]
        item = {
            "question": qa["question"],
            "answer":   qa["answer"],
            "score":    round(float(score), 4)
        }
        if "code" in qa:
            item["code"] = qa["code"]
        results.append(item)

    return jsonify(results)

if __name__ == "__main__":
    app.run(port=5000, debug=True)
