from flask import Flask, request, jsonify, render_template_string, g
from fuzzywuzzy import process
import sqlite3
import os

DATABASE = 'components.db'
MAX_RESULTS = 5

app = Flask(__name__)

# HTML 模板
HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>化学成分查询</title>
  <style>
    body { font-family: Arial, sans-serif; margin: 2em; }
    input, button { padding: 0.5em; font-size: 1em; }
    ul { list-style: none; padding: 0; }
    li { margin: 0.5em 0; }
    pre { background: #f4f4f4; padding: 1em; white-space: pre-wrap; }
  </style>
  <script>
    async function doSearch() {
      const q = document.getElementById('query').value;
      const res = await fetch(`/api/search?query=${encodeURIComponent(q)}`);
      const list = await res.json();
      const ul = document.getElementById('results');
      ul.innerHTML = '';
      list.forEach(item => {
        const li = document.createElement('li');
        li.innerHTML = `<a href="#" onclick="showDetail(${item.id});return false;">
                          <b>${item.name}</b> (${item.formula}) [${item.score}]
                        </a>`;
        ul.appendChild(li);
      });
      document.getElementById('detail').innerText = '';
    }

    async function showDetail(id) {
      const res = await fetch(`/api/components/${id}`);
      const data = await res.json();
      document.getElementById('detail').innerText =
        `名称：${data.name}\n` +
        `分子式：${data.formula}\n` +
        `描述：${data.description}\n` +
        `属性：${data.properties}`;
    }
  </script>
</head>
<body>
  <h1>化学成分查询</h1>
  <input id="query" type="text" placeholder="输入成分名称" onkeydown="if(event.key==='Enter')doSearch()">
  <button onclick="doSearch()">搜索</button>
  <ul id="results"></ul>
  <pre id="detail"></pre>
</body>
</html>
"""

def get_db():
    if 'db' not in g:
        g.db = sqlite3.connect(DATABASE)
        g.db.row_factory = sqlite3.Row
    return g.db

@app.teardown_appcontext
def close_conn(exception):
    db = g.pop('db', None)
    if db:
        db.close()

@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE)

@app.route('/api/search')
def api_search():
    query = request.args.get('query', '').strip()
    if not query:
        return jsonify([])

    db = get_db()
    rows = db.execute("SELECT id, name, formula FROM components").fetchall()
    choices = {row['name']: row['id'] for row in rows}

    # 模糊匹配并取前 MAX_RESULTS 条
    results = process.extract(query, choices.keys(), limit=MAX_RESULTS)
    response = []
    for name, score in results:
        comp_id = choices[name]
        row = db.execute("SELECT id, name, formula FROM components WHERE id = ?", (comp_id,)).fetchone()
        response.append({
            'id': row['id'],
            'name': row['name'],
            'formula': row['formula'],
            'score': score
        })
    return jsonify(response)

@app.route('/api/components/<int:comp_id>')
def api_detail(comp_id):
    db = get_db()
    row = db.execute("SELECT * FROM components WHERE id = ?", (comp_id,)).fetchone()
    if not row:
        return jsonify({'error': 'Not found'}), 404
    return jsonify(dict(row))

def init_db():
    exists = os.path.exists(DATABASE)
    db = sqlite3.connect(DATABASE)
    if not exists:
        db.execute("""
          CREATE TABLE components (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            formula TEXT,
            description TEXT,
            properties TEXT
          )
        """)
        # 示例数据，可根据需要删改或删除此处
        sample = [
          ('水', 'H2O', '无色无味液体', '{"沸点":"100°C","密度":"1 g/cm³"}'),
          ('乙醇', 'C2H6O', '常用溶剂', '{"沸点":"78.37°C","密度":"0.789 g/cm³"}'),
          ('苯', 'C6H6', '芳香族溶剂', '{"沸点":"80.1°C","密度":"0.8765 g/cm³"}')
        ]
        db.executemany("INSERT INTO components (name,formula,description,properties) VALUES (?,?,?,?)", sample)
        db.commit()
    db.close()

if __name__ == '__main__':
    init_db()
    app.run(host='0.0.0.0', port=5000)
