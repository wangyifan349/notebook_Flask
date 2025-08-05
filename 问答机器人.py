from flask import Flask, request, jsonify, render_template_string
from sentence_transformers import SentenceTransformer
import faiss

app = Flask(__name__)

# 问答数据
QA_DATA = [
    {
        "question": "人脸识别原理是什么？",
        "answer": "人脸识别通过提取人脸特征向量，通过相似度比较进行身份验证。",
        "code": """import cv2
import face_recognition
image = face_recognition.load_image_file("your_image.jpg")
face_locations = face_recognition.face_locations(image)
face_encodings = face_recognition.face_encodings(image, face_locations)"""
    },
    {
        "question": "如何使用face_recognition库进行人脸比对？",
        "answer": "利用face_recognition对比两个编码的欧氏距离实现人脸比对。",
        "code": """import face_recognition
img1 = face_recognition.load_image_file("person1.jpg")
img2 = face_recognition.load_image_file("person2.jpg")
enc1 = face_recognition.face_encodings(img1)[0]
enc2 = face_recognition.face_encodings(img2)[0]
results = face_recognition.compare_faces([enc1], enc2)
print(results)"""
    },
    {
        "question": "什么是人脸特征向量？",
        "answer": "人脸特征向量是用来表示人脸独特特征的数值数组，通常维度为128。",
        "code": """# 计算人脸向量
encodings = face_recognition.face_encodings(image)
print(len(encodings[0]))  # 输出128"""
    },
    {
        "question": "如何安装face_recognition库？",
        "answer": "可以通过pip直接安装face_recognition库。",
        "code": """pip install face_recognition"""
    },
    {
        "question": "如何读取摄像头画面进行实时人脸识别？",
        "answer": "使用OpenCV打开摄像头，逐帧检测人脸进行识别。",
        "code": """import cv2
import face_recognition
video_capture = cv2.VideoCapture(0)
while True:
    ret, frame = video_capture.read()
    rgb_frame = frame[:, :, ::-1]
    face_locations = face_recognition.face_locations(rgb_frame)
    for top, right, bottom, left in face_locations:
        cv2.rectangle(frame, (left, top), (right, bottom), (0, 255, 0), 2)
    cv2.imshow('Video', frame)
    if cv2.waitKey(1) & 0xFF == ord('q'):
        break
video_capture.release()
cv2.destroyAllWindows()"""
    },
    {
        "question": "如何提高人脸识别准确率？",
        "answer": "优化模型和使用更高分辨率的图片，同时选择合适的人脸编码算法。",
        "code": ""
    },
    {
        "question": "常用的人脸识别算法有哪些？",
        "answer": "包括Eigenfaces、Fisherfaces、LBPH、Deep learning方法等。",
        "code": ""
    },
    {
        "question": "如何保存和加载人脸编码数据？",
        "answer": "可以使用pickle等序列化库保存numpy数组到本地，再加载使用。",
        "code": """import pickle
# 保存
with open('encodings.pkl', 'wb') as f:
    pickle.dump(encodings, f)
# 加载
with open('encodings.pkl', 'rb') as f:
    encodings = pickle.load(f)"""
    }
]

# 取所有问题
corpus_questions = [item["question"] for item in QA_DATA]

# 初始化中文语义模型
embedder = SentenceTransformer(
    "sentence-transformers/paraphrase-multilingual-mpnet-base-v2"
)
corpus_embeddings = embedder.encode(
    corpus_questions, convert_to_numpy=True, normalize_embeddings=True
)

# 构建faiss索引（内积，前提归一化了）
dim = corpus_embeddings.shape[1]
index = faiss.IndexFlatIP(dim)
index.add(corpus_embeddings)


@app.route("/")
def home():
    return render_template_string(HTML_TEMPLATE)


@app.route('/search', methods=['POST'])
def search():
    data = request.get_json(force=True)
    q = data.get("q", "").strip()
    k = int(data.get("k", 1))

    if not q:
        return jsonify({"error": "字段 'q' 不能为空"}), 400
    if k < 1:
        return jsonify({"error": "字段 'k' 必须 >= 1"}), 400

    q_emb = embedder.encode([q], convert_to_numpy=True, normalize_embeddings=True)
    scores, idxs = index.search(q_emb, k)
    scores = scores.flatten()
    idxs = idxs.flatten()

    results = []
    for score, idx in zip(scores, idxs):
        qa = QA_DATA[int(idx)]
        item = {
            "question": qa["question"],
            "answer": qa["answer"],
            "score": round(float(score), 4)
        }
        if "code" in qa and qa["code"]:
            item["code"] = qa["code"]
        results.append(item)

    return jsonify(results)


HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>智能问答聊天机器人</title>
  <!-- Bootstrap 5 CSS -->
  <link
    href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css"
    rel="stylesheet"
  />
  <!-- Google Fonts: Noto Sans SC for better Chinese -->
  <link
    href="https://fonts.googleapis.com/css2?family=Noto+Sans+SC&display=swap"
    rel="stylesheet"
  />
  <!-- Highlight.js -->
  <link rel="stylesheet"
    href="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.8.0/styles/atom-one-dark.min.css">
  <script src="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.8.0/highlight.min.js"></script>
  <script>hljs.highlightAll();</script>
  <style>
    body {
      font-family: 'Noto Sans SC', sans-serif;
      background-color: #f8f9fa;
      padding: 30px 0;
    }
    h2 {
      color: #0d6efd;
      text-align: center;
      margin-bottom: 25px;
      font-weight: 700;
      letter-spacing: 2px;
    }
    #chatbox {
      background: white;
      max-width: 720px;
      height: 480px;
      margin: 0 auto;
      border-radius: 0.5rem;
      box-shadow: 0 0.5rem 1rem rgb(0 0 0 / 0.15);
      overflow-y: auto;
      padding: 1rem 1.5rem;
      display: flex;
      flex-direction: column;
      gap: 1rem;
      scroll-behavior: smooth;
    }
    .message {
      max-width: 75%;
      padding: 0.8rem 1.2rem;
      border-radius: 1.25rem;
      font-size: 1rem;
      line-height: 1.5;
      word-break: break-word;
      white-space: pre-wrap;
      box-shadow: 0 0.125rem 0.25rem rgb(0 0 0 / 0.1);
      position: relative;
      animation: fadeIn 0.3s ease forwards;
    }
    .message.user {
      align-self: flex-end;
      background-color: #d1e7ff;
      color: #084298;
      border-bottom-right-radius: 0.25rem;
    }
    .message.bot {
      align-self: flex-start;
      background-color: #e9f5f2;
      color: #0f5132;
      border-bottom-left-radius: 0.25rem;
    }
    pre {
      background-color: #212529;
      color: #d1d5db;
      padding: 1rem 1.25rem;
      border-radius: 0.5rem;
      font-family: 'JetBrains Mono', monospace;
      font-size: 0.9rem;
      overflow-x: auto;
      margin-top: 0.75rem;
      box-shadow: inset 0 0 8px rgb(33 37 41 / 0.9);
      white-space: pre-wrap;
    }
    #inputarea {
      max-width: 720px;
      margin: 20px auto 0 auto;
      display: flex;
      gap: 0.75rem;
    }
    #userinput {
      flex-grow: 1;
      font-size: 1.1rem;
      border-radius: 0.5rem;
      border: 1px solid #ced4da;
      resize: none;
      padding: 0.75rem 1rem;
      line-height: 1.4;
      font-family: 'Noto Sans SC', sans-serif;
      min-height: 60px;
      box-shadow: inset 0 0.125rem 0.25rem rgb(0 0 0 / 0.1);
    }
    button {
      background-color: #0d6efd;
      color: white;
      border: none;
      border-radius: 0.5rem;
      min-width: 90px;
      font-size: 1.15rem;
      transition: background-color 0.3s ease;
      box-shadow: 0 0.25rem 0.5rem rgb(13 110 253 / 0.5);
    }
    button:hover {
      background-color: #0b5ed7;
      cursor: pointer;
    }
    @keyframes fadeIn {
      from {
        opacity: 0;
        transform: translateY(10px);
      }
      to {
        opacity: 1;
        transform: translateY(0);
      }
    }
  </style>
</head>
<body>
  <h2>智能问答聊天机器人</h2>
  <section id="chatbox"></section>
  <section id="inputarea">
    <textarea
      id="userinput"
      placeholder="请输入你的问题，支持中文，按Shift+Enter换行，Enter发送"
      rows="3"
    ></textarea>
    <button id="sendBtn">发送</button>
  </section>

  <script>
    const chatbox = document.getElementById("chatbox");
    const userinput = document.getElementById("userinput");
    const sendBtn = document.getElementById("sendBtn");

    // 添加一条消息信息 messageText，sender：'user'或'bot'，render code块
    function addMessage(messageText, sender = "bot", codeText = "") {
      const msgContainer = document.createElement("div");
      msgContainer.className = "message " + sender;

      // 文本内容支持换行
      msgContainer.textContent = messageText;

      // 如果有code，使用pre+code标签块包起来，并用highlight.js高亮
      if (codeText) {
        const pre = document.createElement("pre");
        const code = document.createElement("code");
        code.textContent = codeText;
        // 设置代码语言为python，方便高亮
        code.className = "language-python";
        pre.appendChild(code);
        msgContainer.appendChild(pre);

        // 触发hljs高亮
        hljs.highlightElement(code);
      }
      chatbox.appendChild(msgContainer);
      chatbox.scrollTop = chatbox.scrollHeight;
    }

    // 发送请求到后端，获取回答
    async function sendMessage() {
      let question = userinput.value.trim();
      if (!question) return;

      addMessage(question, "user");
      userinput.value = "";
      sendBtn.disabled = true;

      try {
        const res = await fetch("/search", {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({ q: question, k: 1 }),
        });

        if (!res.ok) {
          addMessage("服务器错误: " + res.statusText);
          sendBtn.disabled = false;
          return;
        }

        const data = await res.json();
        if (data.error) {
          addMessage("错误: " + data.error);
          sendBtn.disabled = false;
          return;
        }

        if (data.length === 0) {
          addMessage("抱歉，未找到相关答案。");
        } else {
          // 只取第一条最相似回答
          const answer = data[0];
          addMessage(answer.answer, "bot", answer.code || "");
        }

      } catch (e) {
        addMessage("请求失败，请稍后重试。");
      } finally {
        sendBtn.disabled = false;
      }
    }

    // 支持回车发送，Shift+Enter换行
    userinput.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        sendMessage();
      }
    });

    sendBtn.addEventListener("click", () => {
      sendMessage();
    });
  </script>
</body>
</html>
"""

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=7860, debug=True)
