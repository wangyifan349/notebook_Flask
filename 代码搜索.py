import json
import faiss
import numpy as np
from sentence_transformers import SentenceTransformer

# 数据库用三引号定义的多行字符串变量，每行是一个json，code和explanation都是单行字符串，没有换行符
data_str = '''{"code":"def add(a,b): return a+b","explanation":"实现两个数字相加的函数"}
{"code":"def factorial(n): return 1 if n<=1 else n*factorial(n-1)","explanation":"递归计算阶乘函数"}
{"code":"def is_prime(num): if num<=1: return False for i in range(2,int(num**0.5)+1): if num%i==0: return False return True","explanation":"判断数字是否是质数"}
{"code":"def greet(name): print(f'Hello, {name}!')","explanation":"打印简单问候语"}'''

def load_code_data_from_str(data_string):
    data = []
    for line in data_string.strip().split('\n'):
        obj = json.loads(line)
        if 'code' in obj and 'explanation' in obj:
            data.append(obj)
    return data

def encode_code_list(model, codes, batch_size=32):
    embs = []
    for i in range(0, len(codes), batch_size):
        batch = codes[i:i+batch_size]
        emb = model.encode(batch, convert_to_tensor=False, show_progress_bar=False)
        embs.append(emb)
    return np.vstack(embs).astype('float32')

def build_faiss_index(embeddings):
    dim = embeddings.shape[1]
    index = faiss.IndexFlatL2(dim)
    index.add(embeddings)
    return index

def search(index, model, query, code_data, top_k=5):
    q_emb = model.encode([query], convert_to_tensor=False)
    q_emb = np.array(q_emb).astype('float32')
    distances, indices = index.search(q_emb, top_k)
    results = []
    for dist, idx in zip(distances[0], indices[0]):
        results.append({
            'code': code_data[idx]['code'],
            'explanation': code_data[idx]['explanation'],
            'distance': dist
        })
    return results

print("加载模型（microsoft/codebert-base），请稍等...")
model = SentenceTransformer("microsoft/codebert-base")

print("加载内置的代码与解释数据...")
code_data = load_code_data_from_str(data_str)
print(f"共加载 {len(code_data)} 条代码数据")

codes = [item['code'] for item in code_data]
print("编码代码向量...")
embeddings = encode_code_list(model, codes)
print("构建FAISS索引...")
index = build_faiss_index(embeddings)
print("准备就绪，可以开始查询。（输入 exit 退出）")

while True:
    query = input("查询 >>> ").strip()
    if query.lower() in ('exit', 'quit'):
        print("退出程序")
        break
    if not query:
        continue
    results = search(index, model, query, code_data)
    print(f"找到Top-{len(results)} 相关代码：")
    for i, item in enumerate(results, 1):
        print(f"----- [{i}] 距离: {item['distance']:.4f} -----")
        print("代码：")
        print(item['code'])
        print("解释：")
        print(item['explanation'])
        print("-" * 40)
