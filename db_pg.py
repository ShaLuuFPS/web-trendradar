"""
PostgreSQL 后端 — 连接 Supabase 云数据库。
接口与 db_sqlite.py 完全一致，上层代码无需修改。
"""

import hashlib
import json
import os
from datetime import datetime, timedelta, timezone

CST = timezone(timedelta(hours=8))  # 中国标准时间
from dotenv import load_dotenv

import psycopg2
import psycopg2.extras
import psycopg2.pool

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

_pool = None


def _ensure_pool():
    global _pool
    if _pool is None:
        if not DATABASE_URL:
            raise RuntimeError("DATABASE_URL 未设置，请在 .env 中配置 Supabase 连接串")
        _pool = psycopg2.pool.ThreadedConnectionPool(2, 10, DATABASE_URL)


def get_conn():
    _ensure_pool()
    return _pool.getconn()


def put_conn(conn):
    if _pool is not None:
        _pool.putconn(conn)


def _topic_key(title: str, platform_id: int) -> str:
    raw = f"{title}|{platform_id}".encode("utf-8")
    return hashlib.md5(raw).hexdigest()


# ============================================================
# 初始化 & 迁移
# ============================================================


def init_db() -> None:
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS platforms (
                    id          SERIAL PRIMARY KEY,
                    name        TEXT NOT NULL UNIQUE,
                    display_name TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS hot_topics (
                    id          SERIAL PRIMARY KEY,
                    platform_id INTEGER NOT NULL REFERENCES platforms(id),
                    rank        INTEGER NOT NULL,
                    title       TEXT NOT NULL,
                    url         TEXT NOT NULL DEFAULT '',
                    hot_score   DOUBLE PRECISION NOT NULL DEFAULT 0,
                    raw_data    JSONB NOT NULL DEFAULT '{}',
                    sentiment   DOUBLE PRECISION,
                    keywords    TEXT,
                    captured_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    topic_key   TEXT NOT NULL DEFAULT ''
                );

                CREATE TABLE IF NOT EXISTS topic_analysis (
                    id            SERIAL PRIMARY KEY,
                    topic_key     TEXT NOT NULL,
                    captured_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    sentiment     TEXT NOT NULL DEFAULT 'neutral',
                    label         TEXT NOT NULL DEFAULT '',
                    verdict_short TEXT NOT NULL DEFAULT '',
                    model         TEXT NOT NULL DEFAULT '',
                    tokens_used   INTEGER NOT NULL DEFAULT 0,
                    UNIQUE(topic_key, captured_at)
                );

                CREATE TABLE IF NOT EXISTS token_usage (
                    id                SERIAL PRIMARY KEY,
                    timestamp         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    model             TEXT NOT NULL DEFAULT '',
                    prompt_tokens     INTEGER NOT NULL DEFAULT 0,
                    completion_tokens INTEGER NOT NULL DEFAULT 0,
                    batch_count       INTEGER NOT NULL DEFAULT 0,
                    cost_estimated    DOUBLE PRECISION NOT NULL DEFAULT 0.0
                );
            """)

            # 索引（幂等）
            for idx_sql in [
                "CREATE INDEX IF NOT EXISTS idx_pg_captured_at ON hot_topics(captured_at)",
                "CREATE INDEX IF NOT EXISTS idx_pg_platform_id  ON hot_topics(platform_id)",
                "CREATE INDEX IF NOT EXISTS idx_pg_topic_key    ON hot_topics(topic_key)",
                "CREATE INDEX IF NOT EXISTS idx_pg_ta_topic_key ON topic_analysis(topic_key)",
                "CREATE INDEX IF NOT EXISTS idx_pg_ta_captured  ON topic_analysis(captured_at)",
            ]:
                cur.execute(idx_sql)

            # 确保平台字典存在
            for name, display in [
                ("weibo", "微博热搜"),
                ("zhihu", "知乎热榜"),
                ("bilibili", "B站热门"),
            ]:
                cur.execute(
                    "INSERT INTO platforms (name, display_name) VALUES (%s, %s) ON CONFLICT (name) DO NOTHING",
                    (name, display),
                )

            conn.commit()
    finally:
        put_conn(conn)


def clear_crawled_data() -> None:
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM topic_analysis")
            cur.execute("DELETE FROM hot_topics")
            conn.commit()
    finally:
        put_conn(conn)


# ============================================================
# 写入
# ============================================================


def insert_topics(platform_name: str, topics: list[dict]) -> int:
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM platforms WHERE name = %s", (platform_name,))
            row = cur.fetchone()
            if row is None:
                raise ValueError(f"未知平台: {platform_name}")
            platform_id = row[0]

            now = datetime.now()
            seen = set()
            rows = []
            for t in topics:
                tk = _topic_key(t["title"], platform_id)
                if tk in seen:
                    continue
                seen.add(tk)
                rows.append(
                    (
                        platform_id,
                        tk,
                        t.get("rank", 0),
                        t["title"],
                        t.get("url", ""),
                        t.get("hot_score", 0),
                        json.dumps(t.get("raw_data", {}), ensure_ascii=False),
                        t.get("sentiment"),
                        t.get("keywords"),
                        now,
                    )
                )

            psycopg2.extras.execute_values(
                cur,
                """INSERT INTO hot_topics
                   (platform_id, topic_key, rank, title, url, hot_score, raw_data, sentiment, keywords, captured_at)
                   VALUES %s""",
                rows,
            )
            conn.commit()
            return len(rows)
    finally:
        put_conn(conn)


# ============================================================
# 查询 — 实时榜单
# ============================================================


def get_latest_topics(platform_name: str, limit: int = 50) -> list[dict]:
    conn = get_conn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT MAX(captured_at) FROM hot_topics "
                "JOIN platforms ON hot_topics.platform_id = platforms.id "
                "WHERE platforms.name = %s",
                (platform_name,),
            )
            latest_time = cur.fetchone()["max"]
            if not latest_time:
                return []

            cur.execute(
                """SELECT
                       MIN(h.rank) AS rank, h.title, h.url,
                       MAX(h.hot_score) AS hot_score, h.raw_data,
                       h.sentiment, h.keywords, h.captured_at, h.topic_key,
                       ta.label AS ai_label,
                       ta.verdict_short AS ai_verdict,
                       ta.sentiment AS ai_sentiment
                   FROM hot_topics h
                   JOIN platforms p ON h.platform_id = p.id
                   LEFT JOIN topic_analysis ta
                     ON h.topic_key = ta.topic_key
                    AND ta.captured_at = (
                        SELECT MAX(ta2.captured_at) FROM topic_analysis ta2
                        WHERE ta2.topic_key = h.topic_key
                          AND ta2.captured_at <= h.captured_at
                    )
                   WHERE p.name = %s AND h.captured_at = %s
                   GROUP BY h.topic_key, h.title, h.url, h.raw_data, h.sentiment, h.keywords, h.captured_at, ta.label, ta.verdict_short, ta.sentiment
                   ORDER BY MIN(h.rank)
                   LIMIT %s""",
                (platform_name, latest_time, limit),
            )
            return [dict(r) for r in cur.fetchall()]
    finally:
        put_conn(conn)


def get_weekly_topics(platform_name: str, limit: int = 50) -> list[dict]:
    conn = get_conn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            seven_days_ago = datetime.now() - timedelta(days=7)
            cur.execute(
                """SELECT
                       agg.min_rank AS rank,
                       latest.title,
                       latest.url,
                       latest.hot_score,
                       latest.raw_data,
                       latest.sentiment,
                       latest.keywords,
                       latest.captured_at,
                       agg.topic_key,
                       ta.label         AS ai_label,
                       ta.verdict_short AS ai_verdict,
                       ta.sentiment     AS ai_sentiment
                   FROM (
                       SELECT
                           h_inner.topic_key,
                           MIN(h_inner.rank)       AS min_rank,
                           MAX(h_inner.captured_at) AS latest_captured
                       FROM hot_topics h_inner
                       JOIN platforms p_inner
                         ON h_inner.platform_id = p_inner.id
                       WHERE p_inner.name = %s
                         AND h_inner.captured_at >= %s
                       GROUP BY h_inner.topic_key
                   ) agg
                   JOIN hot_topics latest
                     ON latest.topic_key = agg.topic_key
                    AND latest.captured_at = agg.latest_captured
                   LEFT JOIN topic_analysis ta
                     ON agg.topic_key = ta.topic_key
                    AND ta.captured_at = (
                        SELECT MAX(ta2.captured_at) FROM topic_analysis ta2
                        WHERE ta2.topic_key = agg.topic_key
                          AND ta2.captured_at <= agg.latest_captured
                    )
                   ORDER BY agg.min_rank
                   LIMIT %s""",
                (platform_name, seven_days_ago, limit),
            )
            return [dict(r) for r in cur.fetchall()]
    finally:
        put_conn(conn)


# ============================================================
# 查询 — 历史趋势
# ============================================================


def _compute_since(time_window: str) -> datetime:
    """将时间窗口字符串转为 timezone-aware datetime（CST）。"""
    now = datetime.now(CST)
    windows = {
        "today":  now.replace(hour=0, minute=0, second=0, microsecond=0),
        "week":   now - timedelta(days=7),
        "7days":  now - timedelta(days=7),
        "month":  now - timedelta(days=30),
        "year":   now - timedelta(days=365),
    }
    return windows.get(time_window, now.replace(hour=0, minute=0, second=0, microsecond=0))


def get_ranking_trend(
    platform_name: str,
    time_window: str = "today",
    top_n: int = 5,
) -> list[dict]:
    since = _compute_since(time_window)
    conn = get_conn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            # 1. 检查窗口内是否有数据
            cur.execute(
                """SELECT COUNT(*) AS cnt FROM hot_topics
                   JOIN platforms ON hot_topics.platform_id = platforms.id
                   WHERE platforms.name = %s
                     AND captured_at >= %s""",
                (platform_name, since),
            )
            if cur.fetchone()["cnt"] == 0:
                return []

            # 2. 取窗口内所有快照中排名靠前的 topic_key
            cur.execute(
                """SELECT topic_key, MIN(title) AS title, MIN(rank) AS rank
                   FROM hot_topics
                   JOIN platforms ON hot_topics.platform_id = platforms.id
                   WHERE platforms.name = %s
                     AND captured_at >= %s
                   GROUP BY topic_key
                   ORDER BY MIN(rank)
                   LIMIT %s""",
                (platform_name, since, top_n),
            )
            top_rows = cur.fetchall()
            if not top_rows:
                return []

            top_keys = [r["topic_key"] for r in top_rows]
            title_map = {r["topic_key"]: r["title"] for r in top_rows}

            # 3. 查这些 topic_key 的所有记录
            cur.execute(
                """SELECT topic_key, rank, hot_score, captured_at FROM hot_topics
                   JOIN platforms ON hot_topics.platform_id = platforms.id
                   WHERE platforms.name = %s
                     AND topic_key = ANY(%s)
                     AND captured_at >= %s
                   ORDER BY captured_at, rank""",
                (platform_name, top_keys, since),
            )
            rows = cur.fetchall()

            # 4. 按 topic_key 分组
            groups: dict[str, list] = {}
            for r in rows:
                groups.setdefault(r["topic_key"], []).append({
                    "captured_at": r["captured_at"].strftime("%Y-%m-%d %H:%M:%S") if r["captured_at"] else "",
                    "rank": r["rank"],
                    "hot_score": r["hot_score"],
                })

            return [
                {
                    "topic_key": tk,
                    "title": title_map.get(tk, ""),
                    "data_points": groups.get(tk, []),
                }
                for tk in top_keys
            ]
    finally:
        put_conn(conn)


def get_weekly_trend_events(
    platform_name: str,
    top_n: int = 8,
) -> list[dict]:
    seven_days_ago = datetime.now() - timedelta(days=7)
    conn = get_conn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """SELECT topic_key, COUNT(*) AS cnt, MIN(title) AS title
                   FROM hot_topics
                   JOIN platforms ON hot_topics.platform_id = platforms.id
                   WHERE platforms.name = %s
                     AND captured_at >= %s
                   GROUP BY topic_key
                   ORDER BY cnt DESC
                   LIMIT %s""",
                (platform_name, seven_days_ago, top_n),
            )
            top_rows = cur.fetchall()
            if not top_rows:
                return []

            top_keys = [r["topic_key"] for r in top_rows]
            title_map = {r["topic_key"]: r["title"] for r in top_rows}

            cur.execute(
                """SELECT topic_key, rank, hot_score, captured_at FROM hot_topics
                   JOIN platforms ON hot_topics.platform_id = platforms.id
                   WHERE platforms.name = %s
                     AND topic_key = ANY(%s)
                     AND captured_at >= %s
                   ORDER BY captured_at, rank""",
                (platform_name, top_keys, seven_days_ago),
            )
            rows = cur.fetchall()

            groups: dict[str, list] = {}
            for r in rows:
                groups.setdefault(r["topic_key"], []).append({
                    "captured_at": r["captured_at"].strftime("%Y-%m-%d %H:%M:%S") if r["captured_at"] else "",
                    "rank": r["rank"],
                    "hot_score": r["hot_score"],
                })

            return [
                {
                    "topic_key": tk,
                    "title": title_map.get(tk, ""),
                    "data_points": groups.get(tk, []),
                }
                for tk in top_keys
            ]
    finally:
        put_conn(conn)


def get_sentiment_distribution(
    platform_name: str,
    time_window: str = "today",
) -> dict:
    since = _compute_since(time_window)
    conn = get_conn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """SELECT
                       COALESCE(ta.sentiment,
                           CASE WHEN h.sentiment >= 0.6 THEN 'positive'
                                WHEN h.sentiment <= 0.4 THEN 'negative'
                                ELSE 'neutral' END
                       ) AS sentiment_label
                   FROM hot_topics h
                   JOIN platforms p ON h.platform_id = p.id
                   LEFT JOIN topic_analysis ta
                     ON h.topic_key = ta.topic_key
                    AND ta.captured_at = (
                        SELECT MAX(ta2.captured_at) FROM topic_analysis ta2
                        WHERE ta2.topic_key = h.topic_key
                          AND ta2.captured_at <= h.captured_at
                    )
                   WHERE p.name = %s
                     AND h.captured_at >= %s
                     AND h.captured_at = (
                         SELECT MAX(h2.captured_at) FROM hot_topics h2
                         WHERE h2.topic_key = h.topic_key
                           AND h2.captured_at >= %s
                     )""",
                (platform_name, since, since),
            )
            rows = cur.fetchall()

        positive = sum(1 for r in rows if r["sentiment_label"] == "positive")
        neutral = sum(1 for r in rows if r["sentiment_label"] == "neutral")
        negative = sum(1 for r in rows if r["sentiment_label"] == "negative")
        total = positive + neutral + negative

        return {
            "positive": positive,
            "neutral": neutral,
            "negative": negative,
            "total": total,
            "positive_pct": round(positive / total * 100, 1) if total else 0,
        }
    finally:
        put_conn(conn)


def get_trend(platform_name: str, keyword: str, hours: int = 24) -> list[dict]:
    since = datetime.now() - timedelta(hours=hours)
    conn = get_conn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """SELECT hot_score, captured_at FROM hot_topics
                   JOIN platforms ON hot_topics.platform_id = platforms.id
                   WHERE platforms.name = %s
                     AND title LIKE %s
                     AND captured_at >= %s
                   ORDER BY captured_at""",
                (platform_name, f"%{keyword}%", since),
            )
            return [dict(r) for r in cur.fetchall()]
    finally:
        put_conn(conn)


# ============================================================
# AI 分析缓存
# ============================================================


def get_unanalyzed_keys(platform_name: str) -> list[dict]:
    conn = get_conn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """SELECT h.topic_key, MIN(h.title) AS title, MIN(h.captured_at) AS captured_at
                   FROM hot_topics h
                   JOIN platforms p ON h.platform_id = p.id
                   WHERE p.name = %s
                     AND h.captured_at = (
                         SELECT MAX(h2.captured_at) FROM hot_topics h2
                         JOIN platforms p2 ON h2.platform_id = p2.id
                         WHERE p2.name = %s
                     )
                     AND h.topic_key NOT IN (
                         SELECT ta.topic_key FROM topic_analysis ta
                         WHERE ta.topic_key = h.topic_key
                     )
                   GROUP BY h.topic_key
                   ORDER BY MIN(h.rank)""",
                (platform_name, platform_name),
            )
            return [dict(r) for r in cur.fetchall()]
    finally:
        put_conn(conn)


def insert_analysis(results: list[dict]) -> int:
    if not results:
        return 0

    conn = get_conn()
    try:
        with conn.cursor() as cur:
            rows = [
                (
                    r["topic_key"],
                    r["captured_at"],
                    r["sentiment"],
                    r["label"],
                    r["verdict_short"],
                    r["model"],
                    r["tokens_used"],
                )
                for r in results
            ]
            psycopg2.extras.execute_values(
                cur,
                """INSERT INTO topic_analysis
                   (topic_key, captured_at, sentiment, label, verdict_short, model, tokens_used)
                   VALUES %s
                   ON CONFLICT (topic_key, captured_at) DO NOTHING""",
                rows,
            )
            conn.commit()
            return len(rows)
    finally:
        put_conn(conn)


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
    timestamp = datetime.now()

    conn = get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO token_usage
                   (timestamp, model, prompt_tokens, completion_tokens, batch_count, cost_estimated)
                   VALUES (%s, %s, %s, %s, %s, %s)""",
                (timestamp, model, prompt_tokens, completion_tokens, batch_count, cost_estimated),
            )
            conn.commit()
    finally:
        put_conn(conn)

    # 追加 JSONL（本地文件）
    jsonl_path = Path(__file__).resolve().parent / "token_usage.jsonl"
    entry = {
        "timestamp": timestamp.strftime("%Y-%m-%d %H:%M:%S"),
        "model": model,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "batch_count": batch_count,
        "cost_estimated": cost_estimated,
    }
    with open(jsonl_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def get_token_stats() -> dict:
    now = datetime.now()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    conn = get_conn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """SELECT COALESCE(SUM(prompt_tokens), 0) AS prompt,
                          COALESCE(SUM(completion_tokens), 0) AS completion,
                          COALESCE(SUM(cost_estimated), 0) AS cost,
                          COUNT(*) AS calls
                   FROM token_usage WHERE timestamp >= %s""",
                (today_start,),
            )
            today_row = cur.fetchone()

            cur.execute(
                """SELECT COALESCE(SUM(prompt_tokens), 0) AS prompt,
                          COALESCE(SUM(completion_tokens), 0) AS completion,
                          COALESCE(SUM(cost_estimated), 0) AS cost,
                          COUNT(*) AS calls
                   FROM token_usage WHERE timestamp >= %s""",
                (month_start,),
            )
            month_row = cur.fetchone()

            cur.execute(
                """SELECT timestamp, model, prompt_tokens, completion_tokens, batch_count, cost_estimated
                   FROM token_usage ORDER BY id DESC LIMIT 1"""
            )
            last_row = cur.fetchone()

        return {
            "today": {
                "prompt_tokens": today_row["prompt"],
                "completion_tokens": today_row["completion"],
                "total_tokens": today_row["prompt"] + today_row["completion"],
                "cost": round(today_row["cost"], 6),
                "calls": today_row["calls"],
            },
            "month": {
                "prompt_tokens": month_row["prompt"],
                "completion_tokens": month_row["completion"],
                "total_tokens": month_row["prompt"] + month_row["completion"],
                "cost": round(month_row["cost"], 6),
                "calls": month_row["calls"],
            },
            "last_call": dict(last_row) if last_row else None,
        }
    finally:
        put_conn(conn)
