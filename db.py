"""
SQLite 存储模块 — 建表、写入热点、查询历史。
"""

import json
import sqlite3
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent / "trend_radar.db"


def get_conn() -> sqlite3.Connection:
    """获取数据库连接（启用 WAL 模式以支持并发读写）。"""
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db() -> None:
    """建表（幂等 — 表不存在才创建）。"""
    conn = get_conn()
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
            sentiment   REAL,                         -- SnowNLP 情感得分 0~1
            keywords    TEXT,                          -- jieba 关键词，逗号分隔
            captured_at DATETIME NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_captured_at ON hot_topics(captured_at);
        CREATE INDEX IF NOT EXISTS idx_platform_id   ON hot_topics(platform_id);
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
    conn.close()


def insert_topics(platform_name: str, topics: list[dict]) -> int:
    """批量写入一条平台的热点抓取结果，返回写入条数。"""
    conn = get_conn()
    cur = conn.execute("SELECT id FROM platforms WHERE name = ?", (platform_name,))
    row = cur.fetchone()
    if row is None:
        conn.close()
        raise ValueError(f"未知平台: {platform_name}")
    platform_id = row["id"]

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    rows = [
        (
            platform_id,
            t.get("rank", 0),
            t["title"],
            t.get("url", ""),
            t.get("hot_score", 0),
            json.dumps(t.get("raw_data", {}), ensure_ascii=False),
            t.get("sentiment"),
            t.get("keywords"),
            now,
        )
        for t in topics
    ]
    conn.executemany(
        """INSERT INTO hot_topics
           (platform_id, rank, title, url, hot_score, raw_data, sentiment, keywords, captured_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        rows,
    )
    conn.commit()
    count = conn.total_changes
    conn.close()
    return count


def get_latest_topics(platform_name: str, limit: int = 50) -> list[dict]:
    """获取指定平台最近一次抓取的热点列表。"""
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
        """SELECT rank, title, url, hot_score, raw_data, sentiment, keywords, captured_at
           FROM hot_topics
           JOIN platforms ON hot_topics.platform_id = platforms.id
           WHERE platforms.name = ? AND captured_at = ?
           ORDER BY rank
           LIMIT ?""",
        (platform_name, latest_time, limit),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_trend(platform_name: str, keyword: str, hours: int = 24) -> list[dict]:
    """查询某个关键词过去 N 小时的热度趋势。"""
    conn = get_conn()
    rows = conn.execute(
        """SELECT hot_score, captured_at FROM hot_topics
           JOIN platforms ON hot_topics.platform_id = platforms.id
           WHERE platforms.name = ?
             AND title LIKE ?
             AND captured_at >= datetime('now', ? || ' hours')
           ORDER BY captured_at""",
        (platform_name, f"%{keyword}%", f"-{hours}"),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]
