from flask import Flask, request, jsonify, render_template_string
from sentence_transformers import SentenceTransformer
import numpy as np
import faiss

app = Flask(__name__)


QA_DATA = [
    {
        "question": "如何计算两张人脸图片的相似度？",
        "answer": """使用预训练的人脸嵌入模型（如FaceNet、ArcFace）将人脸图像编码成固定长度的特征向量，然后通过余弦相似度衡量向量之间的相似性。步骤包括：
1. 预处理：裁剪并缩放人脸图像至模型输入尺寸（通常为160×160），归一化像素值到[0,1]区间。
2. 提取特征向量：使用模型前向计算得到人脸嵌入（embedding）。
3. 计算相似度：两向量的余弦相似度（Cosine Similarity）值在-1到1之间，越接近1表示越相似。

示例代码：
```python
from facenet_pytorch import InceptionResnetV1
from PIL import Image
import torch
import numpy as np

# 1. 加载预训练模型
model = InceptionResnetV1(pretrained='vggface2').eval()

def preprocess(image_path):
    img = Image.open(image_path).convert('RGB').resize((160, 160))
    arr = np.asarray(img) / 255.0
    tensor = torch.tensor(arr, dtype=torch.float32).permute(2, 0, 1).unsqueeze(0)
    return tensor

def get_embedding(image_path):
    tensor = preprocess(image_path)
    with torch.no_grad():
        embedding = model(tensor)
    # 返回1D向量
    return embedding.numpy()[0]

def cosine_similarity(vec1, vec2):
    dot = np.dot(vec1, vec2)
    norm1 = np.linalg.norm(vec1)
    norm2 = np.linalg.norm(vec2)
    return dot / (norm1 * norm2)

# 示例调用
emb1 = get_embedding("face1.jpg")
emb2 = get_embedding("face2.jpg")
sim = cosine_similarity(emb1, emb2)
print(f"相似度: {sim:.4f}")  # 通常大于0.7可认为为同一人
```"""
    },
    {
        "question": "如何使用OpenCV和dlib实现人脸检测并对齐？",
        "answer": """通过dlib检测人脸并定位关键点，再使用OpenCV的仿射变换（affine transform）将关键点映射到标准位置，实现人脸对齐。主要流程：
1. 加载dlib的HOG+SVM人脸检测器和关键点预测器（5或68点模型）。
2. 检测输入图像中的人脸区域。
3. 获取人脸关键点坐标，选取眼角、鼻尖、嘴角等关键点。
4. 根据预定义的目标关键点位置，计算仿射矩阵并对图像进行变换。

示例代码：
```python
import cv2
import dlib
import numpy as np

# 初始化人脸检测器和5点关键点预测器
detector = dlib.get_frontal_face_detector()
predictor = dlib.shape_predictor("shape_predictor_5_face_landmarks.dat")

def align_face(image_path, output_size=(160, 160)):
    img = cv2.imread(image_path)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    faces = detector(gray, 1)
    if not faces:
        return None

    # 取第一张人脸
    face = faces[0]
    landmarks = predictor(gray, face)
    src = np.array([[p.x, p.y] for p in landmarks.parts()], dtype=np.float32)

    # 标准5点坐标（参考MTCNN或ArcFace标准）
    dst = np.array([
        [38.2946, 51.6963],
        [73.5318, 51.5014],
        [56.0252, 71.7366],
        [41.5493, 92.3655],
        [70.7299, 92.2041]
    ], dtype=np.float32)

    # 计算仿射矩阵并对齐
    M = cv2.estimateAffinePartial2D(src, dst, method=cv2.LMEDS)[0]
    aligned = cv2.warpAffine(img, M, output_size, borderValue=(0, 0, 0))
    return aligned

aligned = align_face("face.jpg")
if aligned is not None:
    cv2.imwrite("aligned_face.jpg", aligned)
    print("对齐完成，保存为 aligned_face.jpg")
else:
    print("未检测到人脸") 
```"""
    },
    {
        "question": "如何基于OpenCV实现实时人脸识别？",
        "answer": """在摄像头实时视频流中检测、对齐并识别人脸，通常流程是：
1. 打开摄像头并逐帧读取图像。
2. 使用Haar级联或DNN检测人脸。
3. 对检测到的人脸图像进行对齐及预处理。
4. 提取人脸特征向量并与数据库中已知人脸向量计算相似度。
5. 根据阈值判断身份并显示结果。

示例代码：
```python
import cv2
from facenet_pytorch import InceptionResnetV1
import numpy as np

# 初始化模型和摄像头
model = InceptionResnetV1(pretrained='vggface2').eval()
cap = cv2.VideoCapture(0)
known_embeddings = {...}  # 预先计算好的名称->向量字典

def get_embedding(face_img):
    img = cv2.resize(face_img, (160,160)) / 255.0
    tensor = torch.tensor(img, dtype=torch.float32).permute(2,0,1).unsqueeze(0)
    with torch.no_grad():
        return model(tensor).numpy()[0]

def recognize(emb):
    best_name, best_score = None, -1
    for name, db_emb in known_embeddings.items():
        score = np.dot(emb, db_emb) / (np.linalg.norm(emb)*np.linalg.norm(db_emb))
        if score > best_score:
            best_name, best_score = name, score
    return best_name if best_score > 0.7 else "Unknown"

while True:
    ret, frame = cap.read()
    if not ret: break
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    # 使用Haar或DNN检测
    faces = cv2.CascadeClassifier('haarcascade_frontalface_default.xml') \
                   .detectMultiScale(gray,1.3,5)
    for (x,y,w,h) in faces:
        face_img = frame[y:y+h, x:x+w]
        emb = get_embedding(face_img)
        name = recognize(emb)
        cv2.rectangle(frame, (x,y),(x+w,y+h),(0,255,0),2)
        cv2.putText(frame, name, (x,y-10),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0,255,0),2)
    cv2.imshow("Face Recognition", frame)
    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

cap.release()
cv2.destroyAllWindows()
```"""
    },
]


# ==== 2. 加载模型，构建索引 ====
MODEL_NAME = "sentence-transformers/paraphrase-multilingual-mpnet-base-v2"
embedder = SentenceTransformer(MODEL_NAME)
corpus_questions = [item["question"] for item in QA_DATA]
corpus_embeddings = embedder.encode(corpus_questions, convert_to_numpy=True, normalize_embeddings=True)
dim = corpus_embeddings.shape[1]
index = faiss.IndexFlatIP(dim)
index.add(corpus_embeddings)
# ==== 3. 后端搜索接口 ====
@app.route('/search', methods=['POST'])
def search():
    data = request.get_json(force=True)
    q = data.get("q", "").strip()
    k = int(data.get("k", 1))
    if not q:
        return jsonify({"error": "字段 'q' 不能为空"}), 400
    if k < 1 or k > 5:
        return jsonify({"error": "字段 'k' 必须在1-5之间"}), 400
    q_emb = embedder.encode([q], convert_to_numpy=True, normalize_embeddings=True)
    scores, idxs = index.search(q_emb, k)
    results = []
    for score, idx in zip(scores.flatten(), idxs.flatten()):
        qa = QA_DATA[idx]
        results.append({
            "question": qa["question"],
            "answer": qa["answer"],
            "score": round(float(score), 4)
        })

    return jsonify(results)

# ==== 4. 前端页面 HTML + JS，支持代码块高亮 ====

# 使用 highlight.js CDN，自动高亮页面里的 <pre><code> 代码块

INDEX_HTML = """
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8" />
    <title>在线问答系统</title>
    <style>
        body { font-family: Arial, sans-serif; margin: 20px; background: #f9f9f9; }
        h1 { color: #222; }
        #qa-form { margin-bottom: 20px; }
        #results { background: #fff; padding: 15px; border-radius: 6px; box-shadow: 0 0 8px #ccc; max-width: 800px; }
        .result { margin-bottom: 20px; border-bottom: 1px solid #eee; padding-bottom: 15px; }
        .question { font-weight: bold; color: #2a6ebb; }
        .answer { margin-top: 8px; white-space: pre-wrap; font-size: 14px; color: #333; }
        label { margin-right: 10px; }
        input[type=text] { width: 60%; padding: 6px 8px; font-size: 14px; }
        input[type=number] { width: 50px; padding: 6px 8px; font-size: 14px; }
        button { padding: 6px 16px; font-size: 14px; cursor: pointer; }
        #error { color: red; margin-bottom: 10px; }
        pre { background: #272822; color: #f8f8f2; padding: 10px; border-radius: 4px; overflow-x: auto; }
    </style>

    <!-- highlight.js 样式 & 库 -->
    <link rel="stylesheet"
          href="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.8.0/styles/vs2015.min.css">
    <script src="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.8.0/highlight.min.js"></script>
    <script>hljs.highlightAll();</script>
</head>
<body>
    <h1>中文健身与医学问答系统</h1>
    <div id="error"></div>
    <form id="qa-form" onsubmit="return false;">
        <label for="question">请输入您的问题：</label><br/>
        <input type="text" id="question" name="question" placeholder="例如：Python如何读文件？" required />
        <label for="topk">返回条数：</label>
        <input type="number" id="topk" name="topk" value="1" min="1" max="5" />
        <button type="submit">查询</button>
    </form>
    <div id="results"></div>

<script>
document.getElementById('qa-form').addEventListener('submit', async () => {
    const q = document.getElementById('question').value.trim();
    const k = parseInt(document.getElementById('topk').value);
    const errorDiv = document.getElementById('error');
    const resultsDiv = document.getElementById('results');
    errorDiv.textContent = '';
    resultsDiv.innerHTML = '';

    if (!q) {
        errorDiv.textContent = "请输入有效的问题！";
        return;
    }
    if (k < 1 || k > 5) {
        errorDiv.textContent = "返回条数必须在1到5之间。";
        return;
    }

    try {
        resultsDiv.innerHTML = "<p>正在查询，请稍候...</p>";
        const response = await fetch('/search', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ q: q, k: k })
        });

        if (!response.ok) {
            const err = await response.json();
            errorDiv.textContent = err.error || '查询出现错误！';
            resultsDiv.innerHTML = '';
            return;
        }

        const data = await response.json();

        if (!data.length) {
            resultsDiv.textContent = "未找到相关答案。";
            return;
        }

        // 为了确保代码块的三引号被正确转成 <pre><code>，做简单转换
        // 服务器端答案中代码块格式均为三引号python代码块，我们把 ```python ... ``` 转成 <pre><code class="language-python"> ... </code></pre>
        function escapeHtml(text) {
            var map = {
                '&': '&amp;',
                '<': '&lt;',
                '>': '&gt;',
                '"': '&quot;',
                "'": '&#039;'
            };
            return text.replace(/[&<>"']/g, function(m) { return map[m]; });
        }

        function convertMarkdownCodeBlocks(text) {
            // 先转义html
            text = escapeHtml(text);

            // 转换 ```python ... ``` 或 ``` ... ```
            return text.replace(/```(\\w*)\\n([\\s\\S]*?)```/g,
                function(match, lang, code) {
                    lang = lang || '';
                    return `<pre><code class="language-${lang}">${code}</code></pre>`;
                });
        }

        // 由于JS 正则不支持 \w，需要稍作修改：
        function convertCodeBlocks(text){
            text = escapeHtml(text)
            // ```python\ncode\n``` 代码块正则
            return text.replace(/```(\\w*)\\n([\\s\\S]*?)```/gm, function(match, lang, code){
                lang = lang || '';
                return `<pre><code class="language-${lang}">${code}</code></pre>`;
            }).replace(/```([\\s\\S]*?)```/gm,function(match,code){ // 无语言声明的代码块
                code = match.replace(/```/g,"");
                return `<pre><code>${code}</code></pre>`;
            });
        }

        let htmlResults = data.map(item => {
            // 将答案中的三引号代码块替换为 <pre><code> 供 highlihgt.js高亮
            // 因为后端字符串中的三引号语法是 ```, frag 直接替换即可
            // 这里用正则替换
            let ansHtml = item.answer
                .replace(/```(\\w+)?\\n([\\s\\S]*?)```/g, function(_, lang = '', code){
                    lang = lang.trim() || 'plaintext';
                    // 注意html转义
                    const escapedCode = code.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
                    return `<pre><code class="language-${lang}">${escapedCode}</code></pre>`;
                });

            // 还要把没有语言声明的代码块 ``` ... ``` 也处理
            ansHtml = ansHtml.replace(/```([\\s\\S]*?)```/g, function(_, code) {
                const escapedCode = code.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
                return `<pre><code>${escapedCode}</code></pre>`;
            });

            // 转义其他非代码内容 (换行保留)
            // 为了简单，先替换答案中所有剩余 & < > 等
            // 注意不能转义代码块内部内容，否则会影响显示，所以先用代码块分隔
            // 因为可以覆盖，先不做多余复杂分割


            return `
            <div class="result">
                <div class="question">问：${item.question}</div>
                <div class="answer">${ansHtml}</div>
                <div><small>匹配度：${item.score}</small></div>
            </div>
            `;
        }).join('');

        resultsDiv.innerHTML = htmlResults;
        // 重新调用高亮
        hljs.highlightAll();

    } catch (e) {
        errorDiv.textContent = "查询异常：" + e.message;
        resultsDiv.innerHTML = '';
    }
});
</script>


</body>
</html>
"""
@app.route('/')
def index():
    return render_template_string(INDEX_HTML)
# ==== 5. 入口 ====
if __name__ == '__main__':
    app.run(port=5000, debug=True)
