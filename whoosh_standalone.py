#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
whoosh_standalone.py

双击或命令行运行此脚本即可：
    1) 自动建立或更新索引（内置 JSON 数据）
    2) 进入交互式搜索
    3) 输入 q/quit/exit 退出
"""

import os
import sys
import json
from whoosh import index
from whoosh.fields import Schema, TEXT, ID
from whoosh.qparser import MultifieldParser
from whoosh.highlight import UppercaseFormatter

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

# --------- 定义 Whoosh 索引 Schema ---------
def get_schema():
    return Schema(
        id=ID(stored=True, unique=True),
        title=TEXT(stored=True, field_boost=2.0),
        content=TEXT(stored=True, field_boost=1.0),
    )

# --------- 创建或打开索引 ---------
def create_or_open_index(index_dir, schema):
    if not os.path.exists(index_dir):
        os.mkdir(index_dir)
        ix = index.create_in(index_dir, schema)
    else:
        if index.exists_in(index_dir):
            ix = index.open_dir(index_dir)
        else:
            ix = index.create_in(index_dir, schema)
    return ix

# --------- 建立索引 ---------
def build_index(ix, data):
    writer = ix.writer()
    for doc in data:
        writer.update_document(
            id=doc.get("id", ""),
            title=doc.get("title", ""),
            content=doc.get("content", "")
        )
    writer.commit()

# --------- 交互式搜索 ---------
def interactive_search(ix):
    print("==== Whoosh 简易搜索 ====")
    print("输入关键词回车检索，输入 q/quit/exit 退出。\n")
    with ix.searcher() as searcher:
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

            print(f"\n共找到 {len(results)} 条结果：\n")
            for rank, hit in enumerate(results, 1):
                title_hl = hit.highlights("title") or hit["title"]
                content_hl = hit.highlights("content") or hit["content"][:200] + "…"
                print(f"[{rank:02d}] id={hit['id']} | score={hit.score:.3f}")
                print("  标题:", title_hl)
                print("  内容:", content_hl)
                print("-" * 50)
            print()

# --------- 主流程 ---------
def main():
    # 1. 加载内置 JSON 数据
    try:
        data = json.loads(DATA_JSON)
    except Exception as e:
        print("解析内置 JSON 数据失败：", e)
        sys.exit(1)

    # 2. 创建 / 打开索引
    schema = get_schema()
    ix = create_or_open_index(INDEX_DIR, schema)

    # 3. 建立索引（会自动更新时间戳相同的文档）
    build_index(ix, data)

    # 4. 进入交互式搜索
    interactive_search(ix)

if __name__ == "__main__":
    main()
