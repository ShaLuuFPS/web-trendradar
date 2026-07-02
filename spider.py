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


def _normalize(raw: dict, platform_name: str) -> dict:
    """将平台原始数据统一为内部格式，情感值由 AI 模块后续填充。"""
    title = raw.get("title", "")
    return {
        "rank": raw.get("rank", 0),
        "title": title,
        "url": raw.get("url", ""),
        "hot_score": raw.get("hot_score", 0),
        "raw_data": raw.get("raw_data", {}),
        "sentiment": None,
        "keywords": None,
    }


# ============================================================
# 知乎热榜
# ============================================================

ZHIHU_API = "https://www.zhihu.com/api/v3/feed/topstory/hot-list-wx?limit=30"


def fetch_zhihu() -> list[dict]:
    """抓取知乎热榜（微信小程序 API，无需登录）。"""
    headers = {
        "Referer": "https://www.zhihu.com/hot",
        "Accept": "application/json, text/plain, */*",
    }
    resp = _safe_get(ZHIHU_API, headers=headers)
    if resp is None:
        return []

    items = resp.json().get("data", [])
    topics = []
    for item in items:
        target = item.get("target", {})
        title = target.get("title_area", {}).get("text", "") or target.get("title", "")
        metrics = target.get("metrics_area", {}).get("text", "0")
        hot_score = 0
        try:
            # "899 万热度" → 8990000
            hot_str = (
                metrics.replace(" 万热度", "0000")
                .replace(" 万", "0000")
                .replace(",", "")
                .strip()
            )
            hot_score = int(float(hot_str))
        except (ValueError, TypeError):
            pass

        excerpt = target.get("excerpt_area", {}).get("text", "")
        answer_count = item.get("feed_specific", {}).get("answer_count", 0)

        topics.append(
            _normalize(
                {
                    "rank": len(topics) + 1,
                    "title": title,
                    "url": target.get("link", {}).get("url", ""),
                    "hot_score": hot_score,
                    "raw_data": {
                        "excerpt": excerpt,
                        "answer_count": answer_count,
                        "metrics": metrics,
                    },
                },
                "zhihu",
            )
        )
    return topics


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
    # 不带 Cookie 也能拿数据，但字段可能不完整
    resp = _safe_get(WEIBO_API, headers=headers)
    if resp is None:
        return []

    data = resp.json().get("data", {}).get("realtime", [])
    topics = []
    for item in data[:30]:
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

BILIBILI_API = "https://api.bilibili.com/x/web-interface/popular?pn=1&ps=30"


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
                        "thumb_url": item.get("pic", ""),  # 封面图
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
    "zhihu":    fetch_zhihu,
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
    """一体化：抓取 + 写入数据库。AI 分析由调用方异步触发。"""
    results = fetch_all(platforms)
    return save_to_db(results)
