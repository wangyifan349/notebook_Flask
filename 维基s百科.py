#!/usr/bin/env python3
# coding: utf-8
 
import os
import time
import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urljoin, urlparse, unquote
import sqlite3
 
import requests
from bs4 import BeautifulSoup
 # ----------------- 配置 -----------------
WIKI_BASE_URL = "https://zh.wikipedia.org"
START_PAGE_PATH = "/wiki/Python"
FACE_USERAGENT = "face_usetagent/1.0 (your_email@example.com)"
REQUESTS_DELAY_SECONDS = 0.8
MIN_DOMAIN_INTERVAL_SECONDS = 0.3
MAX_PAGES_PER_RUN = 500
THREAD_COUNT = 6
OUTPUT_TEXT_FILE = "wiki_results.txt"
SQLITE_DB_FILE = "wiki_crawler_state.db"
MAX_QUEUE_SIZE = 20000
# -----------------------------------------
 HEADERS = {"User-Agent": FACE_USERAGENT}
WIKI_INTERNAL_LINK_RE = re.compile(
    r'^/wiki/(?!File:|Help:|Special:|Talk:|Category:|Portal:|Template:|User:|Wikipedia:).+'
)
 
# global counters and locks
global_lock = threading.Lock()
last_request_time = 0.0
pages_processed_counter = 0
 
# ----------------- SQLite helpers -----------------
def get_sqlite_connection():
    # 每个线程可以调用这个函数获取自己的连接（SQLite connections 不是完全线程安全）
    conn = sqlite3.connect(SQLITE_DB_FILE, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn
 
def initialize_database():
    existed = os.path.exists(SQLITE_DB_FILE)
    conn = get_sqlite_connection()
    with conn:
        conn.execute("""
        CREATE TABLE IF NOT EXISTS pending_queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            page_path TEXT NOT NULL UNIQUE,
            added_at INTEGER NOT NULL
        );
        """)
        conn.execute("""
        CREATE TABLE IF NOT EXISTS done_pages (
            page_path TEXT PRIMARY KEY,
            title TEXT,
            url TEXT,
            saved_at INTEGER
        );
        """)
    conn.close()
 
def enqueue_page_if_not_exists(page_path):
    conn = get_sqlite_connection()
    with conn:
        try:
            conn.execute(
                "INSERT OR IGNORE INTO pending_queue(page_path, added_at) VALUES (?, ?)",
                (page_path, int(time.time()))
            )
        finally:
            conn.close()
 
def dequeue_batch(batch_size):
    """
    从 pending_queue 中弹出一批页面（按 id 升序），并删除它们（事务内操作保证原子性）。
    返回 page_path 列表。
    """
    conn = get_sqlite_connection()
    try:
        with conn:
            cursor = conn.execute(
                "SELECT id, page_path FROM pending_queue ORDER BY id ASC LIMIT ?",
                (batch_size,)
            )
            rows = cursor.fetchall()
            if not rows:
                return []
            ids = [str(r["id"]) for r in rows]
            page_paths = [r["page_path"] for r in rows]
            # 删除这些 id
            conn.execute(f"DELETE FROM pending_queue WHERE id IN ({','.join(['?']*len(ids))})", ids)
            return page_paths
    finally:
        conn.close()
 
def mark_page_done(page_path, title_text, absolute_url):
    conn = get_sqlite_connection()
    with conn:
        conn.execute(
            "INSERT OR REPLACE INTO done_pages(page_path, title, url, saved_at) VALUES (?, ?, ?, ?)",
            (page_path, title_text, absolute_url, int(time.time()))
        )
    conn.close()
 
def count_pending():
    conn = get_sqlite_connection()
    try:
        cur = conn.execute("SELECT COUNT(*) as c FROM pending_queue")
        return cur.fetchone()["c"]
    finally:
        conn.close()
 
def count_done():
    conn = get_sqlite_connection()
    try:
        cur = conn.execute("SELECT COUNT(*) as c FROM done_pages")
        return cur.fetchone()["c"]
    finally:
        conn.close()
 
def pending_contains(page_path):
    conn = get_sqlite_connection()
    try:
        cur = conn.execute("SELECT 1 FROM pending_queue WHERE page_path=? LIMIT 1", (page_path,))
        return cur.fetchone() is not None
    finally:
        conn.close()
 
def done_contains(page_path):
    conn = get_sqlite_connection()
    try:
        cur = conn.execute("SELECT 1 FROM done_pages WHERE page_path=? LIMIT 1", (page_path,))
        return cur.fetchone() is not None
    finally:
        conn.close()
 
# ----------------- 网络与解析 -----------------
def normalize_wiki_path(href):
    if not href:
        return None
    parsed = urlparse(href)
    if parsed.netloc and parsed.netloc != urlparse(WIKI_BASE_URL).netloc:
        return None
    path = parsed.path
    if not path.startswith("/wiki/"):
        return None
    return unquote(path.split('#', 1)[0])
 
def fetch_html_with_session(session, page_path):
    global last_request_time
    absolute_url = urljoin(WIKI_BASE_URL, page_path)
    try:
        # 全局速率控制
        with global_lock:
            now = time.time()
            elapsed = now - last_request_time
            if elapsed < MIN_DOMAIN_INTERVAL_SECONDS:
                time.sleep(MIN_DOMAIN_INTERVAL_SECONDS - elapsed)
            last_request_time = time.time()
        response = session.get(absolute_url, headers=HEADERS, timeout=15)
        response.raise_for_status()
        time.sleep(REQUESTS_DELAY_SECONDS)
        return response.text
    except Exception as e:
        print(f"[WARN] 请求失败 {absolute_url}: {e}")
        return None
 
def extract_title_from_soup(soup):
    heading = soup.find(id="firstHeading")
    if heading and heading.get_text(strip=True):
        return heading.get_text(strip=True)
    if soup.title:
        return soup.title.get_text(strip=True)
    return ""
 
def get_main_content_node(soup):
    node = soup.find("div", id="mw-content-text")
    if node:
        return node
    return soup.find("div", class_="mw-parser-output")
 
def clean_text(raw_text):
    if not raw_text:
        return ""
    text = re.sub(r'$$\s*[\dA-Za-z]+\s*$$', '', raw_text)
    text = re.sub(r'[\x00-\x1f\x7f]', '', text)
    text = re.sub(r'\s+', ' ', text).strip()
    text = re.sub(r'([。！？\?\.])\s*', r'\1\n\n', text)
    text = re.sub(r'(\n\s*){3,}', '\n\n', text)
    return text.strip()
 
def extract_body_and_links(soup):
    content_node = get_main_content_node(soup)
    if content_node is None:
        return "", set()
    for selector in ['table', 'style', 'script', 'sup.reference', 'div.reflist', 'ol.references',
                     'div.thumb', 'div.navbox', 'table.infobox', 'span.mw-editsection', 'div#toc']:
        for node in content_node.select(selector):
            node.decompose()
    paragraph_list = []
    for element in content_node.find_all(['p', 'ul', 'ol'], recursive=True):
        p_text = element.get_text(separator=' ', strip=True)
        if not p_text:
            continue
        if len(p_text) < 30 and re.match(r'^[$$$$$$\s:;，。,.0-9-]+$', p_text):
            continue
        paragraph_list.append(p_text)
    combined = "\n\n".join(paragraph_list)
    cleaned = clean_text(combined)
    found_links = set()
    for anchor in content_node.find_all('a', href=True):
        normalized = normalize_wiki_path(anchor['href'])
        if normalized and WIKI_INTERNAL_LINK_RE.match(normalized):
            found_links.add(normalized)
    return cleaned, found_links
 
def append_result_to_text_file(title_text, absolute_url, body_text):
    separator = "\n" + "-" * 40 + "\n"
    block = f"标题: {title_text}\nURL: {absolute_url}\n正文:\n{body_text}\n"
    with global_lock:
        with open(OUTPUT_TEXT_FILE, "a", encoding="utf-8") as f:
            f.write(separator)
            f.write(block)
            f.write(separator)
 
# ----------------- 工作线程 -----------------
def worker_task(page_path):
    global pages_processed_counter
    # 每线程使用独立 Session（更安全）
    session = requests.Session()
    try:
        # 提前检查是否已完成（防止重复）
        if done_contains(page_path):
            return None
        html = fetch_html_with_session(session, page_path)
        if html is None:
            # 将失败的页面标记为已完成以避免循环重试；可改为重试策略
            mark_page_done(page_path, None, None)
            return None
        soup = BeautifulSoup(html, "html.parser")
        title_text = extract_title_from_soup(soup) or "(无标题)"
        body_text, discovered_links = extract_body_and_links(soup)
        absolute_url = urljoin(WIKI_BASE_URL, page_path)
 
        # 写输出文件与数据库标记 done
        append_result_to_text_file(title_text, absolute_url, body_text or "(无正文)")
        mark_page_done(page_path, title_text, absolute_url)
 
        # 将新链接入队（如果不在 pending 和 done 中）
        for new_path in discovered_links:
            if not done_contains(new_path) and not pending_contains(new_path):
                enqueue_page_if_not_exists(new_path)
 
        with global_lock:
            pages_processed_counter += 1
    finally:
        session.close()
    return page_path
 
# ----------------- 主流程 -----------------
def crawl_main():
    global pages_processed_counter
    initialize_database()
    # 初始化起始页面（只有在数据库为空时加入）
    if count_pending() == 0 and count_done() == 0:
        enqueue_page_if_not_exists(START_PAGE_PATH)
 
    # 确保输出文件存在
    if not os.path.exists(OUTPUT_TEXT_FILE):
        open(OUTPUT_TEXT_FILE, "w", encoding="utf-8").close()
 
    pages_processed_counter = 0
    with ThreadPoolExecutor(max_workers=THREAD_COUNT) as executor:
        futures = set()
        try:
            while pages_processed_counter < MAX_PAGES_PER_RUN:
                # 从 pending 中取出一批（batch size = THREAD_COUNT）
                batch = dequeue_batch(THREAD_COUNT)
                if not batch:
                    break
                for page in batch:
                    futures.add(executor.submit(worker_task, page))
                # 等待至少一个完成，以便持续提交新任务
                done_iter = as_completed(futures)
                for finished_future in done_iter:
                    try:
                        result = finished_future.result()
                    except Exception as exc:
                        print(f"[ERROR] 任务异常: {exc}")
                    futures.discard(finished_future)
                    # 周期性检查是否达到上限
                    if pages_processed_counter >= MAX_PAGES_PER_RUN:
                        break
                    # break after one completed to go fetch next batch
                    break
        finally:
            # 等待所有提交的任务完成（可选，根据需要）
            for future in futures:
                try:
                    future.result(timeout=5)
                except Exception:
                    pass
 
    print(f"[DONE] 抓取完成: {pages_processed_counter} 页。已完成总数: {count_done()}。待抓队列: {count_pending()}")
 
if __name__ == "__main__":
    crawl_main()
