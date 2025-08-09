from flask import Flask, request, jsonify, render_template_string
from sklearn.feature_extraction.text import CountVectorizer
import jieba
import numpy as np
from sentence_transformers import SentenceTransformer, util
import os

app = Flask(__name__)

# --------------------------
# 配置和数据（QA字典等）
# --------------------------

qa_dict = {
    "写python哈希函数": """def pjw_hash(str):
    bits_in_unsigned_int = 4 * 8
    three_quarters = (bits_in_unsigned_int * 3) // 4
    one_eighth = bits_in_unsigned_int // 8
    high_bits = (0xFFFFFFFF << (bits_in_unsigned_int - one_eighth)) & 0xFFFFFFFF
    hash = 0
    test = 0
    for char in str:
        hash = (hash << one_eighth) + ord(char)
        test = hash & high_bits
        if test != 0:
            hash = ((hash ^ (test >> three_quarters)) & (~high_bits)) & 0xFFFFFFFF
    return hash

print(pjw_hash("hello world"))""",

    "你是谁": "我是一个智能小助手，专为回答你的问题而设计。",

    "什么是机器学习": "机器学习是人工智能的一个分支，涉及让计算机通过数据学习，从而做出预测或决策。",

    "写一个快速排序算法": """def quick_sort(arr):
    if len(arr) <= 1:
        return arr
    pivot = arr[len(arr) // 2]
    left = [x for x in arr if x < pivot]
    middle = [x for x in arr if x == pivot]
    right = [x for x in arr if x > pivot]
    return quick_sort(left) + middle + quick_sort(right)

print(quick_sort([3,6,8,10,1,2,1]))""",

    "python 如何读取文件": """with open('file.txt', 'r', encoding='utf-8') as f:
    data = f.read()
    print(data)"""
}


# --------------------------
# 算法实现类
# --------------------------

class MatchingAlgorithm:
    def __init__(self, qa_dict):
        self.qa_dict = qa_dict
        self.questions = list(qa_dict.keys())

    def find_best(self, query):
        raise NotImplementedError

class LCSAlgorithm(MatchingAlgorithm):
    @staticmethod
    def lcs_length(a: str, b: str) -> int:
        m, n = len(a), len(b)
        dp = [[0]*(n+1) for _ in range(m+1)]
        for i in range(1,m+1):
            for j in range(1,n+1):
                if a[i-1]==b[j-1]:
                    dp[i][j] = dp[i-1][j-1] + 1
                else:
                    dp[i][j] = max(dp[i-1][j], dp[i][j-1])
        return dp[m][n]

    def find_best(self, query):
        candidates = [(q, ans, self.lcs_length(query, q)) for q, ans in self.qa_dict.items()]
        q, ans, score = max(candidates, key=lambda x: x[2])
        if score <= 0:
            return None, None, 0
        return q, ans, score


class TFAlgorithm(MatchingAlgorithm):
    def __init__(self, qa_dict):
        super().__init__(qa_dict)
        self.vectorizer = CountVectorizer()
        corpus = [" ".join(jieba.lcut(q)) for q in self.questions]
        self.tf_matrix = self.vectorizer.fit_transform(corpus)

    def find_best(self, query):
        tokens = " ".join(jieba.lcut(query))
        vec = self.vectorizer.transform([tokens])
        sims = (self.tf_matrix @ vec.T).toarray().flatten()
        norms = np.linalg.norm(self.tf_matrix.toarray(), axis=1) * np.linalg.norm(vec.toarray())
        sims = sims / np.where(norms == 0, 1, norms)
        idx = np.argmax(sims)
        score = sims[idx]
        if score <= 0:
            return None, None, 0
        return self.questions[idx], self.qa_dict[self.questions[idx]], score


class BERTAlgorithm(MatchingAlgorithm):
    def __init__(self, qa_dict, model_name='paraphrase-multilingual-MiniLM-L12-v2', local_model_path='models/bert_model'):
        super().__init__(qa_dict)
        if os.path.exists(local_model_path):
            self.model = SentenceTransformer(local_model_path)
        else:
            self.model = SentenceTransformer(model_name)
            # 保存到本地，方便下次离线加载
            os.makedirs(local_model_path, exist_ok=True)
            self.model.save(local_model_path)
        self.question_embeddings = self.model.encode(self.questions, convert_to_tensor=True)

    def find_best(self, query, top_k=3):
        query_embedding = self.model.encode(query, convert_to_tensor=True)
        cos_scores = util.cos_sim(query_embedding, self.question_embeddings)[0]
        top_results = cos_scores.topk(k=top_k)
        results = []
        for score, idx in zip(top_results.values, top_results.indices):
            idx = idx.item()
            score = score.item()
            if score <= 0:
                continue
            q = self.questions[idx]
            ans = self.qa_dict[q]
            results.append( (q, ans, score) )
        if not results:
            return None, None, 0, []
        return results[0][0], results[0][1], results[0][2], results

# --------------------------
# 算法管理逻辑（选择、持久化算法配置）
# --------------------------

ALGO_CONFIG_FILE = 'selected_algo.conf'

def load_selected_algo():
    if os.path.exists(ALGO_CONFIG_FILE):
        with open(ALGO_CONFIG_FILE, 'r', encoding='utf-8') as f:
            algo = f.read().strip()
            if algo in ['lcs', 'tf', 'bert']:
                return algo
    return None

def save_selected_algo(algo):
    with open(ALGO_CONFIG_FILE, 'w', encoding='utf-8') as f:
        f.write(algo)

def choose_algorithm_interactively():
    print("请选择匹配算法（lcs / tf / bert）：")
    algo = None
    while algo not in ('lcs','tf','bert'):
        algo = input("输入算法名称：").strip().lower()
    save_selected_algo(algo)
    print(f"已选择算法: {algo}")
    return algo

ALGO = load_selected_algo() or choose_algorithm_interactively()

if ALGO == 'lcs':
    matcher = LCSAlgorithm(qa_dict)
elif ALGO == 'tf':
    matcher = TFAlgorithm(qa_dict)
elif ALGO == 'bert':
    matcher = BERTAlgorithm(qa_dict)
else:
    raise ValueError("未知算法配置")

print(f"使用匹配算法：{ALGO}")


# 简化版 HTML
HTML = """<!DOCTYPE html>
<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8" />
  <title>聊天机器人</title>
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet"/>
  <link rel="stylesheet"
        href="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.8.0/styles/github.min.css">
  <style>
    body { margin:0; padding:0; font-family:"Segoe UI",Tahoma,sans-serif; }
    .chat-container { width:100vw; height:100vh; display:flex; flex-direction:column; background:#e8f5e9; }
    #chat-window { flex:1; padding:20px; overflow-y:auto; background:#f1f8e9; }
    .input-group { display:flex; padding:10px; background:#ffffff; box-shadow:0 -2px 5px rgba(0,0,0,0.1); position:sticky; bottom:0; }
    .msg-user { text-align:right; margin-bottom:10px; }
    .msg-user .bubble { display:inline-block; background:#a5d6a7; color:#1b5e20; padding:8px 12px; border-radius:15px 15px 0 15px; max-width:75%; word-wrap:break-word; }
    .msg-bot { text-align:left; margin-bottom:10px; }
    .msg-bot .bubble { position: relative; display:inline-block; background:#c8e6c9; color:#2e7d32; padding:8px 12px; border-radius:15px 15px 15px 0; max-width:75%; word-wrap:break-word; white-space:pre-wrap; }
    .copy-btn { 
      position: absolute; top:4px; right:4px; 
      border:none; background:transparent; 
      color:#555; font-size:12px; cursor:pointer; 
      padding:2px 4px; border-radius:3px;
    }
    .copy-btn:hover { color:#000; background:rgba(0,0,0,0.1); }
    pre { margin:0; }
  </style>
</head>
<body>
  <div class="chat-container">
    <div id="chat-window"></div>
    <div class="input-group">
      <input type="text" id="user-input" class="form-control me-2" placeholder="请输入..." />
      <button id="send-btn" class="btn btn-success">发送</button>
    </div>
  </div>

  <script src="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.8.0/highlight.min.js"></script>
  <script>hljs.highlightAll();</script>
  <script>
    const chatWindow = document.getElementById('chat-window');
    const userInput  = document.getElementById('user-input');
    const sendBtn    = document.getElementById('send-btn');

    function appendMessage(content, isUser, isCode=false) {
      const wrapper = document.createElement('div');
      wrapper.className = isUser ? 'msg-user' : 'msg-bot';
      const bubble = document.createElement('div');
      bubble.className = 'bubble';

      if (isCode) {
        bubble.innerHTML = `<pre><code>${
          content.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')
        }</code></pre>`;
        hljs.highlightElement(bubble.querySelector('code'));
      } else {
        bubble.textContent = content;
      }

      if (!isUser) {
        const btn = document.createElement('button');
        btn.className = 'copy-btn';
        btn.textContent = '复制';
        btn.addEventListener('click', () => {
          const textToCopy = isCode 
            ? content 
            : content;
          navigator.clipboard.writeText(textToCopy)
            .then(() => {
              btn.textContent = '已复制';
              setTimeout(() => btn.textContent = '复制', 1000);
            })
            .catch(() => {
              btn.textContent = '失败';
              setTimeout(() => btn.textContent = '复制', 1000);
            });
        });
        bubble.appendChild(btn);
      }

      wrapper.appendChild(bubble);
      chatWindow.appendChild(wrapper);
      chatWindow.scrollTop = chatWindow.scrollHeight;
    }

    async function sendQuery() {
      const text = userInput.value.trim();
      if (!text) return;
      appendMessage(text, true);
      userInput.value = '';
      try {
        const resp = await fetch('/chat', {
          method: 'POST',
          headers: {'Content-Type':'application/json'},
          body: JSON.stringify({query: text})
        });
        const data = await resp.json();
        appendMessage(data.answer, false, data.is_code);
      } catch {
        appendMessage('网络错误，请稍后再试。', false);
      }
    }

    sendBtn.addEventListener('click', sendQuery);
    userInput.addEventListener('keydown', e => {
      if (e.key === 'Enter') sendQuery();
    });
  </script>
</body>
</html>

"""

# --------------------------
# 路由及接口实现
# --------------------------

@app.route('/')
def index():
    return render_template_string(HTML)

@app.route('/chat', methods=['POST'])
def chat():
    data = request.get_json(force=True)
    query = data.get('query', '').strip()
    if not query:
        return jsonify({"answer":"请说点什么吧～","is_code":False}),400

    if ALGO == 'bert':
        q, ans, score, results = matcher.find_best(query)
        if score <= 0 or ans is None:
            return jsonify({"answer":"抱歉，我不太明白你的意思。","is_code":False})
        is_code = "\n" in ans and len(ans.splitlines()) > 1
        return jsonify({"answer": ans, "is_code": is_code, "score": float(score)})
    else:
        q, ans, score = matcher.find_best(query)
        if score <= 0 or ans is None:
            return jsonify({"answer":"抱歉，我不太明白你的意思。","is_code":False})
        is_code = "\n" in ans and len(ans.splitlines()) > 1
        return jsonify({"answer": ans, "is_code": is_code})

if __name__ == '__main__':
    app.run(debug=False, port=5000)
