import os
import pickle
import jieba
import numpy as np
import faiss
from sklearn.feature_extraction.text import TfidfVectorizer
from sentence_transformers import SentenceTransformer

# --- Paths and QA data inline ---
BASE_DIR    = os.path.dirname(__file__)
EMB_PATH    = os.path.join(BASE_DIR, 'data', 'zh_embeddings.txt')  # Chinese word vectors
INDICES_DIR = os.path.join(BASE_DIR, 'indices')
MODELS_DIR  = os.path.join(BASE_DIR, 'models')

os.makedirs(INDICES_DIR, exist_ok=True)
os.makedirs(MODELS_DIR, exist_ok=True)

qa_pairs = [
    {"q":"什么是 TF-IDF？","a":"TF-IDF 用于衡量词在文档中的重要性。"},
    {"q":"FAISS 有什么用？","a":"FAISS 支持大规模向量相似度检索。"},
    {"q":"如何加载词向量？","a":"从本地文本文件按行读取到 dict。"}
]
questions = [p['q'] for p in qa_pairs]
answers   = [p['a'] for p in qa_pairs]
# Load Chinese word embeddings
def load_embeddings(path=EMB_PATH):
    emb = {}
    with open(path, encoding='utf-8') as f:
        for line in f:
            parts = line.strip().split()
            if len(parts) < 3:
                continue
            word = parts[0]
            vec  = np.array(parts[1:], dtype=np.float32)
            emb[word] = vec
    return emb
# Custom tokenizer using jieba
def jieba_tokenize(text):
    return [tok for tok in jieba.lcut(text) if tok.strip()]
# Build or load TF–IDF + local Chinese embeddings FAISS index
def get_tfidf_index():
    idx_file  = os.path.join(INDICES_DIR, 'tfidf_zh.index')
    meta_file = os.path.join(INDICES_DIR, 'tfidf_zh.meta')
    if os.path.exists(idx_file) and os.path.exists(meta_file):
        index = faiss.read_index(idx_file)
        with open(meta_file,'rb') as f:
            emb, terms, idf, term2idx = pickle.load(f)
        return index, emb, terms, idf, term2idx

    emb = load_embeddings()
    # TF–IDF with jieba tokenizer
    vectorizer = TfidfVectorizer(tokenizer=jieba_tokenize, lowercase=False)
    tfidf_mat  = vectorizer.fit_transform(questions).toarray()
    terms      = vectorizer.get_feature_names_out()
    idf        = vectorizer.idf_
    term2idx   = {t:i for i,t in enumerate(terms)}
    dim        = next(iter(emb.values())).shape[0]

    qvecs = np.zeros((len(questions), dim), dtype=np.float32)
    for i, weights in enumerate(tfidf_mat):
        vsum = np.zeros(dim, dtype=np.float32); wsum = 0.0
        for term, idx in term2idx.items():
            w = weights[idx]
            if w > 0 and term in emb:
                vsum += w * emb[term]; wsum += w
        if wsum > 0:
            qvecs[i] = vsum / wsum

    faiss.normalize_L2(qvecs)
    index = faiss.IndexFlatIP(dim)
    index.add(qvecs)
    faiss.write_index(index, idx_file)
    with open(meta_file,'wb') as f:
        pickle.dump((emb, terms, idf, term2idx), f)
    return index, emb, terms, idf, term2idx
# Build or load HF Chinese sentence-embedding index
def get_hf_index(model_name='paraphrase-multilingual-MiniLM-L12-v2'):
    idx_file  = os.path.join(INDICES_DIR, 'hf_zh.index')
    model_dir = os.path.join(MODELS_DIR, 'hf_zh')
    if os.path.exists(idx_file) and os.path.exists(model_dir):
        model = SentenceTransformer(model_dir)
        index = faiss.read_index(idx_file)
        return index, model

    model = SentenceTransformer(model_name)
    model.save(model_dir)
    qvecs = model.encode(questions, convert_to_numpy=True, normalize_embeddings=True)
    dim   = qvecs.shape[1]
    index = faiss.IndexFlatIP(dim)
    index.add(qvecs)
    faiss.write_index(index, idx_file)
    return index, model
# Query function supporting both modes
def search(query, mode='hf', top_k=3):
    if mode == 'tfidf':
        index, emb, terms, idf, t2idx = get_tfidf_index()
        toks = jieba_tokenize(query)
        qw   = np.zeros(len(terms), dtype=np.float32)
        for t in toks:
            if t in t2idx:
                qw[t2idx[t]] += 1
        dim = next(iter(emb.values())).shape[0]
        qv  = np.zeros(dim, dtype=np.float32); wsum = 0.0
        for term, idx in t2idx.items():
            w = qw[idx] * idf[idx]
            if w > 0 and term in emb:
                qv += w * emb[term]; wsum += w
        if wsum > 0:
            qv /= wsum
        faiss.normalize_L2(qv.reshape(1,-1))
    else:
        index, model = get_hf_index()
        qv = model.encode([query], convert_to_numpy=True, normalize_embeddings=True)

    D, I = index.search(qv.reshape(1,-1), top_k)
    results = []
    for i, score in zip(I[0], D[0]):
        results.append({
            'question': questions[i],
            'answer':   answers[i],
            'score':    float(score)
        })
    return results
# Interactive loop
if __name__ == '__main__':
    print("输入 'mode tfidf' 或 'mode hf' 切换模式，'exit' 退出。")
    mode = 'hf'
    while True:
        line = input(f"[{mode}] Query> ").strip()
        if line.lower() == 'exit':
            break
        if line.startswith('mode '):
            m = line.split()[1]
            if m in ('tfidf','hf'):
                mode = m
                print(f"切换到模式: {mode}")
            else:
                print("无效模式，请选 'tfidf' 或 'hf'")
            continue
        for item in search(line, mode=mode, top_k=3):
            print(f"Q: {item['question']}  (score {item['score']:.4f})")
            print(f"A: {item['answer']}\n")
