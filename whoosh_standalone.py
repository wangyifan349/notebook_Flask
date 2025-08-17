#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
whoosh_standalone.py

双击或命令行运行此脚本即可：
    1) 自动建立或更新索引（内置 JSON 数据）
    2) 支持中文分词（基于 jieba）
    3) 采用 BM25F 算法，准确度更高
    4) 进入交互式搜索
    5) 输入 q/quit/exit 退出
"""

import os
import sys
import json
import jieba
from whoosh import index
from whoosh.fields import Schema, TEXT, ID, NUMERIC
from whoosh.analysis import Tokenizer, Token
from whoosh.qparser import MultifieldParser
from whoosh.highlight import UppercaseFormatter
from whoosh.scoring import BM25F

# --------- 内置示例数据（无需额外文件） ---------
DATA_JSON = """
[
    {"id": "1", "title": "Python入门教程",   "content": "这是一个Python编程的入门教程。"},
    {"id": "2", "title": "机器学习基础",     "content": "介绍机器学习的基本概念和算法。"},
    {"id": "3", "title": "深度学习实战",     "content": "使用深度学习进行图像识别。"},
    {"id": "4", "title": "数据分析指南",     "content": "利用Pandas进行数据分析。"},
    {"id": "5", "title": "自然语言处理",     "content": "文本处理和语言模型介绍。"}
]
"""

INDEX_DIR = "indexdir"

## 中文分词器
class JiebaTokenizer(Tokenizer):
    def __call__(self, text, **kwargs):
        for word in jieba.cut_for_search(text):
            t = Token(text=word)
            yield t

def get_schema():
    """
    定义 Whoosh 索引 Schema，并使用 BM25F 默认权重：
      - title 权重为 3.0
      - content 权重为 1.0
      - id 存储不分词
      - length 用于演示 NUMERIC 字段
    """
    return Schema(
        id=ID(stored=True, unique=True),
        title=TEXT(stored=True, analyzer=JiebaTokenizer(), field_boost=3.0),
        content=TEXT(stored=True, analyzer=JiebaTokenizer(), field_boost=1.0),
        length=NUMERIC(stored=True)
    )

def create_or_open_index(index_dir, schema):
    """创建或打开索引目录，并返回 Index 对象"""
    if not os.path.exists(index_dir):
        os.mkdir(index_dir)
        ix = index.create_in(index_dir, schema)
    else:
        if index.exists_in(index_dir):
            ix = index.open_dir(index_dir)
        else:
            ix = index.create_in(index_dir, schema)
    return ix

def build_index(ix, data):
    """
    建立或更新索引：
      - 对每条文档计算 content 长度，存入 length 字段
      - writer.update_document 可以自动更新相同 id 的文档
    """
    writer = ix.writer()
    for doc in data:
        content = doc.get("content", "")
        writer.update_document(
            id=doc["id"],
            title=doc.get("title", ""),
            content=content,
            length=len(content)
        )
    writer.commit()

def interactive_search(ix):
    """
    交互式搜索：
      - 支持多字段查询（title & content）
      - 使用 BM25F 作为打分模型
      - 高亮关键词（大写显示）
    """
    print("==== Whoosh 简易搜索 (支持中文分词 & BM25F) ====")
    print("输入关键词回车检索，输入 q/quit/exit 退出。\n")

    with ix.searcher(weighting=BM25F(title_B=0.75, content_B=0.75)) as searcher:
        parser = MultifieldParser(["title", "content"], schema=ix.schema)
        searcher.formatter = UppercaseFormatter()
        while True:
            try:
                query_str = input("搜索> ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\n退出程序。")
                break

            if query_str.lower() in ("q", "quit", "exit"):
                print("退出程序。")
                break
            if not query_str:
                continue

            query = parser.parse(query_str)
            results = searcher.search(query, limit=10)
            results.fragmenter.charlimit = None

            if not results:
                print("没有找到匹配结果。\n")
                continue

            print(f"\n共找到 <b>{len(results)}</b> 条结果：\n")
            for rank, hit in enumerate(results, 1):
                title_hl = hit.highlights("title", top=1) or hit["title"]
                content_hl = hit.highlights("content", top=1) or hit["content"][:200] + "…"
                print(f"[{rank:02d}] id=<b>{hit['id']}</b> | score=<b>{hit.score:.3f}</b>")
                print("  标题:", title_hl)
                print("  内容:", content_hl)
                print("-" * 50)
            print()

def main():
    try:
        data = json.loads(DATA_JSON)
    except Exception as e:
        print("解析内置 JSON 数据失败：", e)
        sys.exit(1)

    schema = get_schema()
    ix = create_or_open_index(INDEX_DIR, schema)
    build_index(ix, data)
    interactive_search(ix)

if __name__ == "__main__":
    main()
