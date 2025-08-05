import faiss
import numpy as np
from sentence_transformers import SentenceTransformer

code_data = [
    {
        "code": """def add(a, b):
    return a + b""",
        "explanation": "实现两个数字相加的函数"
    },
    {
        "code": """def factorial(n):
    if n <= 1:
        return 1
    else:
        return n * factorial(n - 1)""",
        "explanation": "递归计算阶乘函数"
    },
    {
        "code": """import face_recognition
import cv2

def compare_faces(image1_path, image2_path, tolerance=0.6):
    # 加载图片
    image1 = face_recognition.load_image_file(image1_path)
    image2 = face_recognition.load_image_file(image2_path)

    # 获取人脸编码
    encodings1 = face_recognition.face_encodings(image1)
    encodings2 = face_recognition.face_encodings(image2)

    if len(encodings1) == 0 or len(encodings2) == 0:
        print("未检测到人脸，无法比较")
        return False

    # 只取第一张脸进行比较
    result = face_recognition.compare_faces([encodings1[0]], encodings2[0], tolerance=tolerance)
    return result[0]

if __name__ == '__main__':
    img1 = 'person1.jpg'
    img2 = 'person2.jpg'
    match = compare_faces(img1, img2)
    if match:
        print('两张图片是同一个人')
    else:
        print('两张图片不是同一个人')
""",
        "explanation": "使用 face_recognition 库对两张图片的人脸进行比较，判断是否为同一个人"
    }
]

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

def search(index, model, query, code_data, top_k=3):
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

print("加载模型（microsoft/codebert-base）...")
model = SentenceTransformer("microsoft/codebert-base")

codes = [item['code'] for item in code_data]
print("编码代码向量中...")
embeddings = encode_code_list(model, codes)
print("构建FAISS索引...")
index = build_faiss_index(embeddings)

print("准备就绪，输入exit退出")
while True:
    query = input('输入查询 >>> ')
    if query.lower() in ('exit', 'quit'):
        break
    results = search(index, model, query, code_data)
    for i, item in enumerate(results, 1):
        print(f"-----[{i}] 距离: {item['distance']:.4f}-----")
        print(item['code'])
        print(item['explanation'])
        print("-" * 20)
