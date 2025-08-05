import os
import json
import time
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from fake_useragent import UserAgent

# 配置
BASE_URL = "https://zh.wikipedia.org"
START_PATH = "/wiki/Python"
STATE_FILE = "crawler_state.json"
DATA_DIR = "data"
MAX_PAGES = 100
DELAY = 0.5

# 初始化工作目录和 Session
os.makedirs(DATA_DIR, exist_ok=True)
ua = UserAgent()
session = requests.Session()

def load_state():
    """加载爬虫状态（frontier 和 visited），不存在则初始化"""
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            state = json.load(f)
            return state["frontier"], set(state["visited"])
    except (FileNotFoundError, json.JSONDecodeError):
        return [START_PATH], set()

def save_state(frontier, visited):
    """保存当前爬虫状态到本地文件"""
    state = {"frontier": frontier, "visited": list(visited)}
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

def fetch_soup(path, referer):
    """发送 GET 请求并返回 BeautifulSoup 对象"""
    url = urljoin(BASE_URL, path)
    headers = {
        "User-Agent": ua.random,
        "Referer": urljoin(BASE_URL, referer) if referer else BASE_URL
    }
    resp = session.get(url, headers=headers, timeout=10)
    resp.raise_for_status()
    return BeautifulSoup(resp.text, "html.parser")

def extract_links(soup, visited):
    """从正文中抽取新的 /wiki/ 链接，排除已访问和特殊命名空间"""
    links = []
    content = soup.find(id="mw-content-text")
    for a in content.select("a[href^='/wiki/']"):
        href = a["href"].split("#")[0]
        if ":" not in href and href not in visited:
            links.append(href)
    return links

def parse_page(path, referer, visited):
    """解析页面标题、摘要、提取新链接，并返回页面数据与新链接列表"""
    soup = fetch_soup(path, referer)
    title_tag = soup.find(id="firstHeading")
    summary_p = soup.find(id="mw-content-text").find("p", recursive=False)
    title   = title_tag.get_text(strip=True) if title_tag else ""
    summary = summary_p.get_text(strip=True) if summary_p else ""
    new_links = extract_links(soup, visited)
    page_data = {
        "path": path,
        "title": title,
        "summary": summary,
        "new_links_count": len(new_links),
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
    }
    return page_data, new_links

def save_page_data(page_data):
    """将单个页面的数据保存为 JSON 文件"""
    safe_name = page_data["path"].strip("/").replace("/", "_")
    file_path = os.path.join(DATA_DIR, f"{safe_name}.json")
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(page_data, f, ensure_ascii=False, indent=2)

def crawl():
    frontier, visited = load_state()
    count = 0
    while frontier and count < MAX_PAGES:
        path = frontier.pop(0)
        if path in visited:
            continue
        try:
            page_data, new_links = parse_page(path, referer=path, visited=visited)
            save_page_data(page_data)         # 保存页面解析结果
            visited.add(path)                # 标记为已访问
            frontier.extend(new_links)       # 扩展待爬队列
            count += 1
            time.sleep(DELAY)                # 请求间隔
        except Exception as e:
            print(f"Error crawling {path}: {e}")
        finally:
            save_state(frontier, visited)    # 持久化爬虫状态
    print(f"爬取完成，总页面数：{count}")

if __name__ == "__main__":
    crawl()
