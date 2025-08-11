#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
本脚本：BERT 向量化 + FAISS 检索 + 问答循环系统
----------------------------------------------------------------
功能：
  1. 使用 Sentence-BERT（paraphrase-multilingual-MiniLM-L12-v2）将预设问题向量化并构建 FAISS 索引
  2. 接收用户输入的短问题，通过向量检索找到最相似的预设问题
  3. 返回对应的详细答案，并显示匹配度

使用场景：
  离线或网络环境不佳时，快速获取预设 QA 知识点的回答。

安装依赖（推荐创建并激活 virtualenv）：
  pip install sentence-transformers faiss-cpu transformers

首次运行时需联网下载模型，之后可离线使用。

运行示例：
  python3 qa_system.py
  > 光速是多少？
  答案：……
  (匹配度：0.999)

退出：
  输入 exit 或直接回车

----------------------------------------------------------------
"""

import os
import faiss
from sentence_transformers import SentenceTransformer
from transformers import AutoTokenizer, AutoModelForQuestionAnswering, pipeline

# 1. 指定本地缓存目录（按需修改）
CACHE_DIR = "/path/to/your/cache_dir"
os.environ["TRANSFORMERS_CACHE"] = CACHE_DIR
os.environ["SENTENCE_TRANSFORMERS_HOME"] = CACHE_DIR

# 2. QA 知识库：问题—答案字典
qa_knowledge = {
    "第一任国家主席是谁？": """
毛泽东，1893 年出生于湖南省韶山市，1921 年参与创建中国共产党，1949 年中华人民共和国成立后，
被选为中央人民政府主席（即国家主席）。他领导了新中国的建立和初期建设，直到1959 年才正式
将主席职务交给刘少奇，并继续担任中共中央主席，直到1976 年逝世。""",
    "中华人民共和国成立日期？": """
中华人民共和国成立于1949年10月1日。在这一天，毛泽东在北京天安门城楼上向全世界庄严宣布：
“中华人民共和国中央人民政府今天成立了！”从此，标志着中国进入社会主义历史时期。""",
    "光速是多少？": """
光速在真空中是一个恒定值，约为299 792 458米/秒（约3.0×10⁸米/秒）。这个数值被定义为精确
常量，是现代物理学中最基本的自然常数之一，广泛应用于相对论、天文学和光学等领域。""",
    "《红楼梦》的作者？": """
《红楼梦》是中国古典小说巅峰之作，一般认为作者是清代作家曹雪芹（1715–1763）。小说以贾
宝玉和林黛玉的爱情悲剧为主线，揭示了封建社会的兴衰，所反映的社会风貌和人物刻画堪称不朽。""",
    "世界最大沙漠？": """
世界上最大的热带沙漠是非洲的撒哈拉沙漠，面积约9.2百万平方公里，横跨阿尔及利亚、利比亚、
埃及、苏丹等多个国家。它气候极端干旱，昼夜温差大，是地球上最荒凉但又极具自然魅力的区域。"""
}

# 3. 模型名称与检索参数
MODEL_EMBED = 'paraphrase-multilingual-MiniLM-L12-v2'
MODEL_QA = 'distilbert-base-uncased-distilled-squad'
EMBED_BATCH = 16
TOP_K = len(qa_knowledge)

# 4. 预下载并缓存 Sentence-BERT
print("正在下载并缓存 Sentence-BERT 模型…")
embed_model = SentenceTransformer(MODEL_EMBED)
_ = embed_model.encode(["预下载测试"], batch_size=EMBED_BATCH, show_progress_bar=False)

# 5. 预下载并缓存问答模型和 tokenizer
print("正在下载并缓存问答模型及 tokenizer…")
tokenizer = AutoTokenizer.from_pretrained(MODEL_QA)
model_qa = AutoModelForQuestionAnswering.from_pretrained(MODEL_QA)
qa_pipeline = pipeline('question-answering', model=model_qa, tokenizer=tokenizer)
_ = qa_pipeline(question="What is Python?", context="Python is a programming language.")

# 6. 构建 FAISS 索引
print("构建 FAISS 索引…")
questions = list(qa_knowledge.keys())
answers = list(qa_knowledge.values())
doc_embeddings = embed_model.encode(
    questions,
    batch_size=EMBED_BATCH,
    show_progress_bar=False,
    convert_to_numpy=True
)
faiss.normalize_L2(doc_embeddings)
dim = doc_embeddings.shape[1]
index = faiss.IndexFlatIP(dim)
index.add(doc_embeddings)

# 7. 交互式问答循环
print("请输入简短问题（如“光速是多少？”），输入 exit 退出：")
while True:
    query = input("> ").strip()
    if not query or query.lower() == 'exit':
        print("已退出。")
        break

    q_emb = embed_model.encode([query], convert_to_numpy=True)
    faiss.normalize_L2(q_emb)
    sims, idxs = index.search(q_emb, TOP_K)
    best_idx = int(idxs[0][0])
    sim_score = float(sims[0][0])

    if sim_score < 0.3:
        print("未能匹配到合适答案，请尝试换个问法。")
        continue

    print("\n答案：")
    print(answers[best_idx])
    print(f"(匹配度：{sim_score:.3f})\n")
