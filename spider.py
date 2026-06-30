"""
爬虫模块 — 抓取各平台热搜数据。
架构：每个平台一个类，统一返回列表[dict]，方便上层调度。
"""

import hashlib
import json
import random
import time
from datetime import datetime

import requests
import jieba
import jieba.analyse
from snownlp import SnowNLP

# ============================================================
# 通用工具
# ============================================================

def _safe_get(url: str, headers: dict | None = None, timeout: int = 15) -> requests.Response | None:
    """带重试 & 随机延迟的 GET 请求。"""
    default_headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/126.0.0.0 Safari/537.36"
        ),
    }
    if headers:
        default_headers.update(headers)

    for attempt in range(3):
        try:
            time.sleep(random.uniform(0.8, 2.5))
            resp = requests.get(url, headers=default_headers, timeout=timeout)
            resp.raise_for_status()
            return resp
        except requests.RequestException as e:
            if attempt == 2:
                raise e
            time.sleep(2 ** attempt)
    return None


def _analyze(title: str) -> tuple[float, str]:
    """对标题做情感分析 + 关键词提取。"""
    try:
        sentiment = SnowNLP(title).sentiments
    except Exception:
        sentiment = 0.5
    try:
        kw = jieba.analyse.extract_tags(title, topK=3, allowPOS=("n", "v", "a", "ns", "nr"))
    except Exception:
        kw = []
    return round(sentiment, 4), ",".join(kw)


def _normalize(raw: dict, platform_name: str) -> dict:
    """将平台原始数据统一为内部格式，附加情感与关键词。"""
    title = raw.get("title", "")
    sentiment, keywords = _analyze(title)
    return {
        "rank": raw.get("rank", 0),
        "title": title,
        "url": raw.get("url", ""),
        "hot_score": raw.get("hot_score", 0),
        "raw_data": raw.get("raw_data", {}),
        "sentiment": sentiment,
        "keywords": keywords,
    }


# ============================================================
# 知乎热榜
# ============================================================

ZHIHU_HOT_URL = "https://www.zhihu.com/hot"


def _fetch_zhihu_playwright() -> list[dict]:
    """用 Playwright 真实浏览器抓取知乎热榜 — 绕过反爬检测。"""
    from playwright.sync_api import sync_playwright

    topics = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/126.0.0.0 Safari/537.36"
            ),
        )
        page.goto(ZHIHU_HOT_URL, wait_until="networkidle", timeout=30000)
        html = page.content()
        browser.close()

    # 从页面中提取 <script id="js-initialData" type="text/json">...</script>
    marker_start = '<script id="js-initialData" type="text/json">'
    marker_end = "</script>"
    pos = html.find(marker_start)
    if pos == -1:
        print("[spider] 知乎: 未找到 js-initialData")
        return []

    pos += len(marker_start)
    end = html.find(marker_end, pos)
    if end == -1:
        print("[spider] 知乎: js-initialData 截断")
        return []

    try:
        initial_data = json.loads(html[pos:end])
    except json.JSONDecodeError as e:
        print(f"[spider] 知乎: JSON 解析失败: {e}")
        return []

    hot_list = (
        initial_data.get("initialState", {})
        .get("topstory", {})
        .get("hotList", [])
    )
    for item in hot_list:
        target = item.get("target", {})
        title = target.get("titleArea", {}).get("text", "") or target.get("title", "")
        metrics = target.get("metricsArea", {}).get("text", "0")
        hot_score = 0
        try:
            hot_str = metrics.replace(" 万热度", "0000").replace(" 万", "0000").replace(",", "").strip()
            hot_score = int(float(hot_str))
        except (ValueError, TypeError):
            pass

        topics.append(
            _normalize(
                {
                    "rank": len(topics) + 1,
                    "title": title,
                    "url": target.get("link", {}).get("url", ""),
                    "hot_score": hot_score,
                    "raw_data": {
                        "excerpt": target.get("excerptArea", {}).get("text", ""),
                        "answer_count": target.get("answerCount", 0),
                        "follower_count": target.get("followerCount", 0),
                    },
                },
                "zhihu",
            )
        )
    return topics


def fetch_zhihu() -> list[dict]:
    """抓取知乎热榜（Playwright 浏览器引擎）。"""
    return _fetch_zhihu_playwright()


# ============================================================
# 微博热搜
# ============================================================

WEIBO_API = "https://weibo.com/ajax/side/hotSearch"


def fetch_weibo() -> list[dict]:
    """抓取微博热搜榜（需带 Referer 和 Cookie 才能稳定访问）。"""
    headers = {
        "Referer": "https://weibo.com/",
        "Accept": "application/json, text/plain, */*",
    }
    resp = _safe_get(WEIBO_API, headers=headers)
    if resp is None:
        return []

    data = resp.json().get("data", {}).get("realtime", [])
    topics = []
    for item in data[:50]:
        word = item.get("word", "")
        topics.append(
            _normalize(
                {
                    "rank": item.get("realpos", len(topics) + 1),
                    "title": item.get("note", word),
                    "url": f"https://s.weibo.com/weibo?q={word}",
                    "hot_score": item.get("raw_hot", item.get("num", 0)),
                    "raw_data": {
                        "category": item.get("category", ""),
                        "icon_desc": item.get("icon_desc", ""),
                    },
                },
                "weibo",
            )
        )
    return topics


# ============================================================
# B站热门
# ============================================================

BILIBILI_API = "https://api.bilibili.com/x/web-interface/popular?pn=1&ps=50"


def fetch_bilibili() -> list[dict]:
    """抓取B站热门视频。"""
    resp = _safe_get(BILIBILI_API)
    if resp is None:
        return []

    items = resp.json().get("data", {}).get("list", [])
    topics = []
    for item in items:
        topics.append(
            _normalize(
                {
                    "rank": len(topics) + 1,
                    "title": item.get("title", ""),
                    "url": item.get("short_link_v2", f"https://www.bilibili.com/video/{item.get('bvid', '')}"),
                    "hot_score": item.get("stat", {}).get("view", 0),
                    "raw_data": {
                        "bvid": item.get("bvid", ""),
                        "play": item.get("stat", {}).get("view", 0),
                        "danmaku": item.get("stat", {}).get("danmaku", 0),
                        "reply": item.get("stat", {}).get("reply", 0),
                        "favorite": item.get("stat", {}).get("favorite", 0),
                        "author": item.get("owner", {}).get("name", ""),
                        "tname": item.get("tname", ""),
                        "pubdate": item.get("pubdate", 0),  # Unix 时间戳
                    },
                },
                "bilibili",
            )
        )
    return topics


# ============================================================
# 调度入口
# ============================================================

FETCHERS = {
    "weibo":    fetch_weibo,
    "bilibili": fetch_bilibili,
    # "zhihu":    fetch_zhihu,  # 知乎需要登录 Cookie，暂不启用
}


def fetch_all(platforms: list[str] | None = None) -> dict[str, list[dict]]:
    """批量抓取，返回 {platform_name: [topics]}。"""
    if platforms is None:
        platforms = list(FETCHERS.keys())

    results = {}
    for name in platforms:
        fetcher = FETCHERS.get(name)
        if fetcher is None:
            print(f"[spider] 未知平台: {name}，跳过")
            continue
        try:
            print(f"[spider] 正在抓取 {name} ...")
            results[name] = fetcher()
            print(f"[spider] {name} 抓到 {len(results[name])} 条")
        except Exception as e:
            print(f"[spider] {name} 抓取失败: {e}")
            results[name] = []
    return results


def save_to_db(results: dict[str, list[dict]]) -> dict[str, int]:
    """将抓取结果写入 SQLite，返回各平台写入条数。"""
    from db import insert_topics

    counts = {}
    for platform_name, topics in results.items():
        if topics:
            counts[platform_name] = insert_topics(platform_name, topics)
        else:
            counts[platform_name] = 0
    return counts


def crawl_and_save(platforms: list[str] | None = None) -> dict[str, int]:
    """一体化：抓取 + 写入数据库。供 APScheduler 定时任务调用。"""
    results = fetch_all(platforms)
    return save_to_db(results)
