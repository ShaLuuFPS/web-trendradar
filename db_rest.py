"""
Supabase REST API 后端 — 通过 HTTPS 连接 Supabase。
用于本地开发（中国网络环境）和 Streamlit Cloud。
"""

import hashlib
import json
import os
from datetime import datetime, timedelta, timezone

CST = timezone(timedelta(hours=8))  # 中国标准时间
from dotenv import load_dotenv

from supabase import create_client, Client

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise RuntimeError("SUPABASE_URL / SUPABASE_KEY 未设置，请在 .env 中配置")

_supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)


def _topic_key(title: str, platform_id: int) -> str:
    raw = f"{title}|{platform_id}".encode("utf-8")
    return hashlib.md5(raw).hexdigest()


# ============================================================
# 初始化（需要先在 Supabase SQL Editor 中运行建表 SQL）
# ============================================================


def init_db() -> None:
    """验证表是否存在。建表请在 Supabase SQL Editor 中执行 migration.sql。"""
    try:
        r = _supabase.table("platforms").select("id", count="exact").limit(1).execute()
        print(f"[db_rest] 已连接 Supabase, platforms 表存在")
    except Exception as e:
        print(f"[db_rest] ⚠️ 表尚未创建，请在 Supabase SQL Editor 中执行 migration.sql")
        print(f"   错误详情: {e}")


def clear_crawled_data() -> None:
    _supabase.table("topic_analysis").delete().neq("id", 0).execute()
    _supabase.table("hot_topics").delete().neq("id", 0).execute()


# ============================================================
# 写入
# ============================================================


def insert_topics(platform_name: str, topics: list[dict]) -> int:
    r = _supabase.table("platforms").select("id").eq("name", platform_name).execute()
    if not r.data:
        raise ValueError(f"未知平台: {platform_name}")
    platform_id = r.data[0]["id"]

    now = datetime.now().isoformat()
    seen = set()
    rows = []
    for t in topics:
        tk = _topic_key(t["title"], platform_id)
        if tk in seen:
            continue
        seen.add(tk)
        rows.append({
            "platform_id": platform_id,
            "topic_key": tk,
            "rank": t.get("rank", 0),
            "title": t["title"],
            "url": t.get("url", ""),
            "hot_score": t.get("hot_score", 0),
            "raw_data": json.dumps(t.get("raw_data", {}), ensure_ascii=False),
            "sentiment": t.get("sentiment"),
            "keywords": t.get("keywords"),
            "captured_at": now,
        })

    if not rows:
        return 0

    # 分批插入（REST API 有 body size 限制）
    batch_size = 30
    total = 0
    for i in range(0, len(rows), batch_size):
        batch = rows[i:i + batch_size]
        _supabase.table("hot_topics").insert(batch).execute()
        total += len(batch)
    return total


# ============================================================
# 查询 — 实时榜单
# ============================================================


def get_latest_topics(platform_name: str, limit: int = 50) -> list[dict]:
    """获取指定平台最近一次抓取的热点列表。

    REST API 限制：复杂 JOIN 用 RPC 函数代替。
    需要先在 Supabase 中创建 get_latest_topics 函数。
    """
    try:
        r = _supabase.rpc("get_latest_topics", {
            "platform_name": platform_name,
            "limit_val": limit,
        }).execute()
        return r.data if r.data else []
    except Exception as e:
        print(f"[db_rest] get_latest_topics RPC 不可用: {e}")
        # 回退：简单查询
        return _get_latest_topics_simple(platform_name, limit)


def _get_latest_topics_simple(platform_name: str, limit: int = 50) -> list[dict]:
    """简化版：只查 hot_topics 表，不做 JOIN。"""
    # 先拿到 platform_id
    r = _supabase.table("platforms").select("id").eq("name", platform_name).execute()
    if not r.data:
        return []
    platform_id = r.data[0]["id"]

    # 拿最新时间
    r = _supabase.table("hot_topics").select("captured_at") \
        .eq("platform_id", platform_id) \
        .order("captured_at", desc=True).limit(1).execute()
    if not r.data:
        return []

    latest = r.data[0]["captured_at"]

    # 拿该时间的所有记录
    r = _supabase.table("hot_topics").select("*") \
        .eq("platform_id", platform_id) \
        .eq("captured_at", latest) \
        .order("rank").limit(limit).execute()

    return [
        {
            "rank": d.get("rank"),
            "title": d.get("title", ""),
            "url": d.get("url", ""),
            "hot_score": d.get("hot_score", 0),
            "raw_data": d.get("raw_data", "{}"),
            "sentiment": d.get("sentiment"),
            "keywords": d.get("keywords"),
            "captured_at": d.get("captured_at", ""),
            "topic_key": d.get("topic_key", ""),
            "ai_label": d.get("ai_label", ""),
            "ai_verdict": d.get("ai_verdict", ""),
            "ai_sentiment": d.get("ai_sentiment", ""),
        }
        for d in (r.data or [])
    ]


def get_weekly_topics(platform_name: str, limit: int = 50) -> list[dict]:
    try:
        r = _supabase.rpc("get_weekly_topics", {
            "platform_name": platform_name,
            "limit_val": limit,
        }).execute()
        return r.data if r.data else []
    except Exception:
        # 简化回退
        return _get_latest_topics_simple(platform_name, limit)


# ============================================================
# 查询 — 历史趋势
# ============================================================


def _compute_since(time_window: str) -> str:
    now = datetime.now(CST)
    windows = {
        "today":  now.replace(hour=0, minute=0, second=0, microsecond=0),
        "week":   now - timedelta(days=7),
        "7days":  now - timedelta(days=7),
        "month":  now - timedelta(days=30),
        "year":   now - timedelta(days=365),
    }
    return windows.get(time_window, now.replace(hour=0, minute=0, second=0, microsecond=0)).isoformat()


def get_ranking_trend(
    platform_name: str,
    time_window: str = "today",
    top_n: int = 5,
) -> list[dict]:
    try:
        r = _supabase.rpc("get_ranking_trend", {
            "platform_name": platform_name,
            "since_val": _compute_since(time_window),
            "top_n_val": top_n,
        }).execute()
        return r.data if r.data else []
    except Exception as e:
        print(f"[db_rest] get_ranking_trend RPC 不可用: {e}")
        return []


def get_weekly_trend_events(
    platform_name: str,
    top_n: int = 8,
) -> list[dict]:
    try:
        r = _supabase.rpc("get_weekly_trend_events", {
            "platform_name": platform_name,
            "top_n_val": top_n,
        }).execute()
        return r.data if r.data else []
    except Exception as e:
        print(f"[db_rest] get_weekly_trend_events RPC 不可用: {e}")
        return []


def get_sentiment_distribution(
    platform_name: str,
    time_window: str = "today",
) -> dict:
    try:
        r = _supabase.rpc("get_sentiment_distribution", {
            "platform_name": platform_name,
            "since_val": _compute_since(time_window),
        }).execute()
        if r.data:
            return r.data[0]
    except Exception:
        pass
    return {"positive": 0, "neutral": 0, "negative": 0, "total": 0, "positive_pct": 0.0}


def get_trend(platform_name: str, keyword: str, hours: int = 24) -> list[dict]:
    since = (datetime.now() - timedelta(hours=hours)).isoformat()
    r = _supabase.table("hot_topics").select("hot_score, captured_at") \
        .eq("platform_id", _get_platform_id(platform_name)) \
        .gte("captured_at", since) \
        .like("title", f"%{keyword}%") \
        .order("captured_at").execute()
    return r.data if r.data else []


# ============================================================
# AI 分析缓存
# ============================================================


def get_unanalyzed_keys(platform_name: str) -> list[dict]:
    try:
        r = _supabase.rpc("get_unanalyzed_keys", {
            "platform_name": platform_name,
        }).execute()
        return r.data if r.data else []
    except Exception:
        return []


def insert_analysis(results: list[dict]) -> int:
    if not results:
        return 0
    rows = [
        {
            "topic_key": r["topic_key"],
            "captured_at": r["captured_at"],
            "sentiment": r["sentiment"],
            "label": r["label"],
            "verdict_short": r["verdict_short"],
            "model": r["model"],
            "tokens_used": r["tokens_used"],
        }
        for r in results
    ]
    # 分批
    total = 0
    for i in range(0, len(rows), 30):
        batch = rows[i:i + 30]
        _supabase.table("topic_analysis").upsert(batch, on_conflict="topic_key,captured_at").execute()
        total += len(batch)
    return total


# ============================================================
# 批量查询 AI 分析
# ============================================================


def get_analysis_batch(topic_keys: list[str]) -> dict[str, dict]:
    if not topic_keys:
        return {}
    try:
        r = _supabase.rpc("get_analysis_batch", {"topic_keys": topic_keys}).execute()
        if r.data:
            return {d["topic_key"]: d for d in r.data}
    except Exception as e:
        print(f"[db_rest] get_analysis_batch RPC 不可用: {e}")
    return {}


# ============================================================
# Token 用量追踪
# ============================================================


def record_token_usage(
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    batch_count: int = 1,
    cost_estimated: float = 0.0,
) -> None:
    from pathlib import Path
    timestamp = datetime.now().isoformat()

    try:
        _supabase.table("token_usage").insert({
            "timestamp": timestamp,
            "model": model,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "batch_count": batch_count,
            "cost_estimated": cost_estimated,
        }).execute()
    except Exception as e:
        print(f"[db_rest] record_token_usage 写入 Supabase 失败: {e}")

    # 追加 JSONL（本地文件）
    jsonl_path = Path(__file__).resolve().parent / "token_usage.jsonl"
    entry = {
        "timestamp": timestamp,
        "model": model,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "batch_count": batch_count,
        "cost_estimated": cost_estimated,
    }
    with open(jsonl_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def get_token_stats() -> dict:
    try:
        r = _supabase.rpc("get_token_stats").execute()
        if r.data:
            return r.data[0]
    except Exception:
        pass
    return {
        "today": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "cost": 0, "calls": 0},
        "month": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "cost": 0, "calls": 0},
        "last_call": None,
    }


# ============================================================
# 辅助
# ============================================================


def _get_platform_id(platform_name: str) -> int:
    r = _supabase.table("platforms").select("id").eq("name", platform_name).execute()
    if r.data:
        return r.data[0]["id"]
    return 0
