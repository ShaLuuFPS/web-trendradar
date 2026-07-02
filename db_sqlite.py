"""
SQLite 存储模块 — 建表、写入热点、查询历史、AI 分析缓存、Token 追踪。
"""

import hashlib
import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent / "trend_radar.db"


def get_conn() -> sqlite3.Connection:
    """获取数据库连接（启用 WAL 模式以支持并发读写）。"""
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def _topic_key(title: str, platform_id: int) -> str:
    """计算话题唯一标识：md5(title + platform_id) 的 hex digest。"""
    raw = f"{title}|{platform_id}".encode("utf-8")
    return hashlib.md5(raw).hexdigest()


# ============================================================
# 初始化 & 迁移
# ============================================================


def init_db() -> None:
    """建表（幂等 — 表/列不存在才创建）。"""
    conn = get_conn()

    # 基础表
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS platforms (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            name        TEXT    NOT NULL UNIQUE,
            display_name TEXT   NOT NULL
        );

        CREATE TABLE IF NOT EXISTS hot_topics (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            platform_id INTEGER NOT NULL REFERENCES platforms(id),
            rank        INTEGER NOT NULL,
            title       TEXT    NOT NULL,
            url         TEXT    NOT NULL DEFAULT '',
            hot_score   REAL    NOT NULL DEFAULT 0,
            raw_data    TEXT    NOT NULL DEFAULT '{}',
            sentiment   REAL,
            keywords    TEXT,
            captured_at DATETIME NOT NULL
        );
    """)

    # 迁移：为旧表添加 topic_key 列（幂等 — try/except 忽略已存在错误）
    try:
        conn.execute("ALTER TABLE hot_topics ADD COLUMN topic_key TEXT NOT NULL DEFAULT ''")
    except sqlite3.OperationalError:
        pass

    # 索引（幂等）
    conn.executescript("""
        CREATE INDEX IF NOT EXISTS idx_captured_at ON hot_topics(captured_at);
        CREATE INDEX IF NOT EXISTS idx_platform_id   ON hot_topics(platform_id);
        CREATE INDEX IF NOT EXISTS idx_topic_key     ON hot_topics(topic_key);
    """)

    # 新建表
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS topic_analysis (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            topic_key     TEXT    NOT NULL,
            captured_at   DATETIME NOT NULL,
            sentiment     TEXT    NOT NULL DEFAULT 'neutral',
            label         TEXT    NOT NULL DEFAULT '',
            verdict_short TEXT    NOT NULL DEFAULT '',
            model         TEXT    NOT NULL DEFAULT '',
            tokens_used   INTEGER NOT NULL DEFAULT 0,
            UNIQUE(topic_key, captured_at)
        );

        CREATE INDEX IF NOT EXISTS idx_ta_topic_key ON topic_analysis(topic_key);
        CREATE INDEX IF NOT EXISTS idx_ta_captured  ON topic_analysis(captured_at);

        CREATE TABLE IF NOT EXISTS token_usage (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp         DATETIME NOT NULL,
            model             TEXT    NOT NULL DEFAULT '',
            prompt_tokens     INTEGER NOT NULL DEFAULT 0,
            completion_tokens INTEGER NOT NULL DEFAULT 0,
            batch_count       INTEGER NOT NULL DEFAULT 0,
            cost_estimated    REAL    NOT NULL DEFAULT 0.0
        );
    """)

    # 确保平台字典存在
    conn.executemany(
        "INSERT OR IGNORE INTO platforms (name, display_name) VALUES (?, ?)",
        [
            ("weibo",    "微博热搜"),
            ("zhihu",    "知乎热榜"),
            ("bilibili", "B站热门"),
        ],
    )
    conn.commit()

    # 对存量数据回填 topic_key（幂等：只更新空值）
    _backfill_topic_keys(conn)

    conn.close()


def clear_crawled_data() -> None:
    """清空抓取数据和 AI 分析结果（保留平台字典和 token 记录）。"""
    conn = get_conn()
    conn.execute("DELETE FROM topic_analysis")
    conn.execute("DELETE FROM hot_topics")
    conn.commit()
    conn.close()


def _backfill_topic_keys(conn: sqlite3.Connection) -> None:
    """对 hot_topics 中 topic_key 为空的行回填 hash。"""
    try:
        empty_count = conn.execute(
            "SELECT COUNT(*) FROM hot_topics WHERE topic_key = '' OR topic_key IS NULL"
        ).fetchone()[0]
    except sqlite3.OperationalError:
        # topic_key 列可能还不存在（全新库），跳过
        return

    if empty_count == 0:
        return

    rows = conn.execute(
        """SELECT id, title, platform_id FROM hot_topics
           WHERE topic_key = '' OR topic_key IS NULL"""
    ).fetchall()

    for r in rows:
        tk = _topic_key(r["title"], r["platform_id"])
        conn.execute(
            "UPDATE hot_topics SET topic_key = ? WHERE id = ?",
            (tk, r["id"]),
        )

    conn.commit()
    print(f"[db] 已回填 {len(rows)} 条 topic_key")


# ============================================================
# 写入
# ============================================================


def insert_topics(platform_name: str, topics: list[dict]) -> int:
    """批量写入一条平台的热点抓取结果，返回写入条数。"""
    conn = get_conn()
    cur = conn.execute("SELECT id FROM platforms WHERE name = ?", (platform_name,))
    row = cur.fetchone()
    if row is None:
        conn.close()
        raise ValueError(f"未知平台: {platform_name}")
    platform_id = row["id"]

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")  # 微秒精度，避免同秒多批次碰撞
    seen = set()
    rows = []
    for t in topics:
        tk = _topic_key(t["title"], platform_id)
        # 跳过同批次内重复标题（API 可能返回重复条目）
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
    conn.executemany(
        """INSERT INTO hot_topics
           (platform_id, topic_key, rank, title, url, hot_score, raw_data, sentiment, keywords, captured_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        rows,
    )
    conn.commit()
    count = conn.total_changes
    conn.close()
    return count


# ============================================================
# 查询 — 实时榜单
# ============================================================


def get_latest_topics(platform_name: str, limit: int = 50) -> list[dict]:
    """获取指定平台最近一次抓取的热点列表（JOIN AI 分析结果）。"""
    conn = get_conn()
    latest_time = conn.execute(
        """SELECT MAX(captured_at) FROM hot_topics
           JOIN platforms ON hot_topics.platform_id = platforms.id
           WHERE platforms.name = ?""",
        (platform_name,),
    ).fetchone()[0]

    if not latest_time:
        conn.close()
        return []

    rows = conn.execute(
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
           WHERE p.name = ? AND h.captured_at = ?
           GROUP BY h.topic_key
           ORDER BY MIN(h.rank)
           LIMIT ?""",
        (platform_name, latest_time, limit),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_weekly_topics(platform_name: str, limit: int = 50) -> list[dict]:
    """获取最近 7 天内出现过的所有话题，按窗口内最高排名排列。

    返回格式与 get_latest_topics 完全一致，可直接复用热榜渲染。
    """
    conn = get_conn()

    rows = conn.execute(
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
               WHERE p_inner.name = ?
                 AND h_inner.captured_at >= datetime('now', 'localtime', '-7 days')
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
           LIMIT ?""",
        (platform_name, limit),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ============================================================
# 查询 — 历史趋势
# ============================================================


def get_ranking_trend(
    platform_name: str,
    time_window: str = "today",
    top_n: int = 5,
) -> list[dict]:
    """获取指定时间窗口内 Top N 热点的排名+热度趋势数据。

    time_window: "today" | "week" | "month" | "year"
    返回: [{topic_key, title, data_points: [{captured_at, rank, hot_score}]}]
    """
    conn = get_conn()

    windows = {
        "today": "start of day",
        "week": "-7 days",
        "7days": "-7 days",
        "month": "-30 days",
        "year": "-365 days",
    }
    since = windows.get(time_window, "start of day")

    # 1. 检查窗口内是否有数据
    has_data = conn.execute(
        """SELECT COUNT(*) FROM hot_topics
           JOIN platforms ON hot_topics.platform_id = platforms.id
           WHERE platforms.name = ?
             AND captured_at >= datetime('now', 'localtime', ?)""",
        (platform_name, since),
    ).fetchone()[0]

    if not has_data:
        conn.close()
        return []

    # 2. 取窗口内所有快照中排名靠前的 topic_key（去重合并，不只看最新一次快照）
    top_rows = conn.execute(
        """SELECT topic_key, MIN(title) AS title, MIN(rank) AS rank
           FROM hot_topics
           JOIN platforms ON hot_topics.platform_id = platforms.id
           WHERE platforms.name = ?
             AND captured_at >= datetime('now', 'localtime', ?)
           GROUP BY topic_key
           ORDER BY MIN(rank)
           LIMIT ?""",
        (platform_name, since, top_n),
    ).fetchall()

    if not top_rows:
        conn.close()
        return []

    top_keys = [r["topic_key"] for r in top_rows]
    title_map = {r["topic_key"]: r["title"] for r in top_rows}

    # 3. 查这些 topic_key 在时间窗口内的所有记录
    placeholders = ",".join("?" for _ in top_keys)
    rows = conn.execute(
        f"""SELECT topic_key, rank, hot_score, captured_at FROM hot_topics
            JOIN platforms ON hot_topics.platform_id = platforms.id
            WHERE platforms.name = ?
              AND topic_key IN ({placeholders})
              AND captured_at >= datetime('now', 'localtime', ?)
            ORDER BY captured_at, rank""",
        (platform_name, *top_keys, since),
    ).fetchall()
    conn.close()

    # 4. 按 topic_key 分组
    groups: dict[str, list] = {}
    for r in rows:
        groups.setdefault(r["topic_key"], []).append({
            "captured_at": r["captured_at"],
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


def get_weekly_trend_events(
    platform_name: str,
    top_n: int = 8,
) -> list[dict]:
    """获取 7 天内出现次数最多的 Top N 事件及其全部数据点。

    返回格式与 get_ranking_trend 一致: [{topic_key, title, data_points}]。
    data_points 按 captured_at 排序。
    """
    conn = get_conn()

    # 1. 统计 7 天内每个 topic_key 的出现次数，按次数降序取 Top N
    top_rows = conn.execute(
        """SELECT topic_key, COUNT(*) AS cnt, MIN(title) AS title
           FROM hot_topics
           JOIN platforms ON hot_topics.platform_id = platforms.id
           WHERE platforms.name = ?
             AND captured_at >= datetime('now', 'localtime', '-7 days')
           GROUP BY topic_key
           ORDER BY cnt DESC
           LIMIT ?""",
        (platform_name, top_n),
    ).fetchall()

    if not top_rows:
        conn.close()
        return []

    top_keys = [r["topic_key"] for r in top_rows]
    title_map = {r["topic_key"]: r["title"] for r in top_rows}

    # 2. 拉这些 topic_key 在 7 天内的所有数据点
    placeholders = ",".join("?" for _ in top_keys)
    rows = conn.execute(
        f"""SELECT topic_key, rank, hot_score, captured_at FROM hot_topics
            JOIN platforms ON hot_topics.platform_id = platforms.id
            WHERE platforms.name = ?
              AND topic_key IN ({placeholders})
              AND captured_at >= datetime('now', 'localtime', '-7 days')
            ORDER BY captured_at, rank""",
        (platform_name, *top_keys),
    ).fetchall()
    conn.close()

    # 3. 按 topic_key 分组
    groups: dict[str, list] = {}
    for r in rows:
        groups.setdefault(r["topic_key"], []).append({
            "captured_at": r["captured_at"],
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


def get_sentiment_distribution(
    platform_name: str,
    time_window: str = "today",
) -> dict:
    """获取指定时间窗口的情绪分布统计。

    返回: {positive: int, neutral: int, negative: int, total: int, positive_pct: float}
    """
    conn = get_conn()

    windows = {
        "today": "start of day",
        "week": "-7 days",
        "7days": "-7 days",
        "month": "-30 days",
        "year": "-365 days",
    }
    since = windows.get(time_window, "start of day")

    # 取窗口内最新批次的数据，JOIN AI 分析结果
    # 情绪来源：优先 AI label → 其次 sentiment 数值
    rows = conn.execute(
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
           WHERE p.name = ?
             AND h.captured_at >= datetime('now', 'localtime', ?)
             AND h.captured_at = (
                 SELECT MAX(h2.captured_at) FROM hot_topics h2
                 WHERE h2.topic_key = h.topic_key
                   AND h2.captured_at >= datetime('now', 'localtime', ?)
             )""",
        (platform_name, since, since),
    ).fetchall()
    conn.close()

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


def get_trend(platform_name: str, keyword: str, hours: int = 24) -> list[dict]:
    """查询某个关键词过去 N 小时的热度趋势。"""
    conn = get_conn()
    rows = conn.execute(
        """SELECT hot_score, captured_at FROM hot_topics
           JOIN platforms ON hot_topics.platform_id = platforms.id
           WHERE platforms.name = ?
             AND title LIKE ?
             AND captured_at >= datetime('now', 'localtime', ? || ' hours')
           ORDER BY captured_at""",
        (platform_name, f"%{keyword}%", f"-{hours}"),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ============================================================
# AI 分析缓存
# ============================================================


def get_unanalyzed_keys(platform_name: str) -> list[dict]:
    """获取指定平台最新抓取批次中尚未在 topic_analysis 中分析的热点。

    返回: [{topic_key, title, captured_at}]
    """
    conn = get_conn()
    rows = conn.execute(
        """SELECT h.topic_key, MIN(h.title) AS title, MIN(h.captured_at) AS captured_at
           FROM hot_topics h
           JOIN platforms p ON h.platform_id = p.id
           WHERE p.name = ?
             AND h.captured_at = (
                 SELECT MAX(h2.captured_at) FROM hot_topics h2
                 JOIN platforms p2 ON h2.platform_id = p2.id
                 WHERE p2.name = ?
             )
             AND h.topic_key NOT IN (
                 SELECT ta.topic_key FROM topic_analysis ta
                 WHERE ta.topic_key = h.topic_key
             )
           GROUP BY h.topic_key
           ORDER BY MIN(h.rank)""",
        (platform_name, platform_name),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def insert_analysis(results: list[dict]) -> int:
    """批量写入 AI 分析结果到 topic_analysis 表。

    results: [{topic_key, captured_at, sentiment, label, verdict_short, model, tokens_used}]
    返回写入条数。
    """
    if not results:
        return 0

    conn = get_conn()
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
    conn.executemany(
        """INSERT OR IGNORE INTO topic_analysis
           (topic_key, captured_at, sentiment, label, verdict_short, model, tokens_used)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        rows,
    )
    conn.commit()
    count = conn.total_changes
    conn.close()
    return count


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
    """记录一笔 API 调用到 token_usage 表 + token_usage.jsonl 文件。"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # 写入 SQLite
    conn = get_conn()
    conn.execute(
        """INSERT INTO token_usage
           (timestamp, model, prompt_tokens, completion_tokens, batch_count, cost_estimated)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (timestamp, model, prompt_tokens, completion_tokens, batch_count, cost_estimated),
    )
    conn.commit()
    conn.close()

    # 追加 JSONL
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
    """获取 Token 消耗统计：本次会话 / 今日 / 本月。"""
    conn = get_conn()

    now = datetime.now()
    today_start = now.strftime("%Y-%m-%d") + " 00:00:00"
    month_start = now.strftime("%Y-%m-01") + " 00:00:00"

    # 今日
    today_row = conn.execute(
        """SELECT COALESCE(SUM(prompt_tokens), 0) AS prompt,
                  COALESCE(SUM(completion_tokens), 0) AS completion,
                  COALESCE(SUM(cost_estimated), 0) AS cost,
                  COUNT(*) AS calls
           FROM token_usage WHERE timestamp >= ?""",
        (today_start,),
    ).fetchone()

    # 本月
    month_row = conn.execute(
        """SELECT COALESCE(SUM(prompt_tokens), 0) AS prompt,
                  COALESCE(SUM(completion_tokens), 0) AS completion,
                  COALESCE(SUM(cost_estimated), 0) AS cost,
                  COUNT(*) AS calls
           FROM token_usage WHERE timestamp >= ?""",
        (month_start,),
    ).fetchone()

    # 最近一次调用
    last_row = conn.execute(
        """SELECT timestamp, model, prompt_tokens, completion_tokens, batch_count, cost_estimated
           FROM token_usage ORDER BY id DESC LIMIT 1"""
    ).fetchone()

    conn.close()

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
