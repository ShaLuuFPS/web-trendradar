"""
Streamlit 看板 — 社交媒体热点追踪 v2.0。
深色编辑叙事风，AI 舆情分析 + 排名折线图 + 历史回溯。
启动方式: uv run streamlit run main.py
"""

import json as _json
from datetime import datetime as _dt
from pathlib import Path

import streamlit as st
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

import db
from db import (
    init_db,
    get_latest_topics,
    get_weekly_topics,
    get_ranking_trend,
    get_weekly_trend_events,
    get_sentiment_distribution,
    get_token_stats,
)
from spider import FETCHERS


# ============================================================
# 页面配置（必须是第一个 Streamlit 命令）
# ============================================================

st.set_page_config(
    page_title="热点趋势看板",
    page_icon="🔥",
    layout="wide",
)

# ============================================================
# 定时调度器 — 每 1 分钟抓取
# 使用 @st.cache_resource 保证跨 Streamlit 重执行单例。
# 不能用模块级变量：Streamlit 每次 rerun 会重新执行模块顶层代码，
# _scheduler = None 会把旧引用清空，导致创建新的 BackgroundScheduler，
# 而旧的 scheduler 线程仍在运行 → 每分钟累积 +1 个调度器。
# ============================================================


@st.cache_resource
def _get_scheduler() -> BackgroundScheduler:
    """创建后台调度器（cache_resource 保证整个进程生命周期只有一个）。"""

    def _auto_crawl_and_analyze():
        from spider import crawl_and_save as _crawl
        from ai_analyzer import run_analysis_all
        counts = _crawl()
        run_analysis_all(list(counts.keys()))

    scheduler = BackgroundScheduler(timezone="Asia/Shanghai")
    scheduler.add_job(
        _auto_crawl_and_analyze,
        trigger=CronTrigger(minute="*/10"),
        id="auto_crawl",
        name="自动抓取热点",
        replace_existing=True,
        max_instances=1,  # 防止前一次未完成时重叠执行
        misfire_grace_time=30,  # 允许 30 秒内的 misfire
    )
    scheduler.start()
    return scheduler


# ============================================================
# 全局 CSS — 深色编辑叙事风，对照 docs/design.md
# ============================================================


def inject_design_css() -> None:
    """注入 Google Fonts + 全局 CSS。"""
    st.markdown("""
    <link
        href="https://fonts.googleapis.com/css2?family=Playfair+Display:ital,wght@0,600;0,700;1,600&family=Inter:wght@300;400;500;600;700&display=swap"
        rel="stylesheet"
    >
    <style>
        /* ============================================================
           0. 全局根基
           ============================================================ */
        .stApp {
            background-color: #0F1119;
        }
        * {
            font-family: 'Inter', sans-serif;
        }
        ::-webkit-scrollbar { width: 6px; height: 6px; }
        ::-webkit-scrollbar-track { background: #0F1119; }
        ::-webkit-scrollbar-thumb { background: #2D3142; border-radius: 3px; }
        ::-webkit-scrollbar-thumb:hover { background: #3F4458; }

        /* ============================================================
           1. 顶部导航条
           ============================================================ */
        header[data-testid="stHeader"] {
            background: rgba(15, 17, 25, 0.9) !important;
            backdrop-filter: blur(8px);
            border-bottom: 1px solid rgba(255, 255, 255, 0.05);
        }
        [data-testid="stSidebar"] {
            background: #0F1119;
            border-right: 1px solid rgba(255, 255, 255, 0.05);
        }
        [data-testid="stSidebar"] * {
            color: #E2E8F0 !important;
        }

        /* ============================================================
           2. 文字层级
           ============================================================ */
        h1 {
            font-family: 'Playfair Display', serif !important;
            font-size: 36px !important;
            font-weight: 700 !important;
            color: #E2E8F0 !important;
            letter-spacing: -0.01em !important;
        }
        h2 {
            font-family: 'Playfair Display', serif !important;
            font-size: 24px !important;
            font-weight: 600 !important;
            color: #E2E8F0 !important;
        }
        h3 {
            font-family: 'Inter', sans-serif !important;
            font-size: 18px !important;
            font-weight: 600 !important;
            color: #E2E8F0 !important;
        }
        p, li, span, div {
            color: #94A3B8;
        }

        /* ============================================================
           3. 卡片 — 玻璃拟态
           ============================================================ */
        .glass-card {
            background: rgba(19, 22, 31, 0.7) !important;
            border: 1px solid rgba(255, 255, 255, 0.05) !important;
            border-radius: 6px !important;
            padding: 24px !important;
            box-shadow: 0 4px 30px rgba(0, 0, 0, 0.5) !important;
        }
        [data-testid="stMetric"] {
            background: rgba(19, 22, 31, 0.7);
            border: 1px solid rgba(255, 255, 255, 0.05);
            border-radius: 6px;
            padding: 24px;
            box-shadow: 0 4px 30px rgba(0, 0, 0, 0.5);
        }
        [data-testid="stMetric"] label {
            font-size: 11px !important;
            font-weight: 500 !important;
            color: #64748B !important;
            text-transform: uppercase;
            letter-spacing: 0.05em;
        }
        [data-testid="stMetricValue"] {
            font-family: 'Playfair Display', serif !important;
            font-size: 40px !important;
            font-weight: 700 !important;
            color: #E2E8F0 !important;
        }

        /* ============================================================
           4. 按钮
           ============================================================ */
        .stButton > button {
            background: rgba(30, 35, 48, 0.9);
            border: 1px solid rgba(255, 255, 255, 0.08);
            border-radius: 6px;
            color: #E2E8F0;
            font-size: 15px;
            font-weight: 500;
            padding: 8px 16px;
            transition: all 150ms ease-out;
        }
        .stButton > button:hover {
            background: rgba(40, 45, 58, 0.9);
            color: #FFFFFF;
            border-color: rgba(255, 255, 255, 0.15);
        }
        .stButton > button[kind="primary"] {
            background: transparent;
            border: 1px solid #D4A056;
            color: #D4A056;
            font-weight: 600;
            padding: 10px 20px;
        }
        .stButton > button[kind="primary"]:hover {
            background: rgba(212, 160, 86, 0.08);
            border-color: #D4A056;
            color: #D4A056;
            box-shadow: 0 0 20px rgba(212, 160, 86, 0.2);
        }

        /* ============================================================
           5. 表格
           ============================================================ */
        [data-testid="stDataFrame"] thead tr th {
            background: transparent !important;
            font-size: 11px !important;
            font-weight: 500 !important;
            color: #64748B !important;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            padding: 8px 12px !important;
            border-bottom: 1px solid rgba(255, 255, 255, 0.06) !important;
            border-right: none !important;
        }
        [data-testid="stDataFrame"] tbody tr td {
            font-size: 14px;
            color: #94A3B8;
            padding: 10px 12px !important;
            border-bottom: 1px solid rgba(255, 255, 255, 0.03) !important;
            border-right: none !important;
            vertical-align: middle;
        }
        [data-testid="stDataFrame"] tbody tr:hover td {
            background: rgba(255, 255, 255, 0.02) !important;
        }

        /* 千万级热度行 — 金辉标注 */
        .row-megahit td {
            background: rgba(212, 160, 86, 0.06) !important;
            border-left: 2px solid #D4A056 !important;
        }

        /* ============================================================
           6. Tab / 导航激活态
           ============================================================ */
        .stTabs [data-baseweb="tab-list"] {
            border-bottom: 1px solid rgba(255, 255, 255, 0.06);
            gap: 0;
        }
        .stTabs [data-baseweb="tab"] {
            font-size: 14px;
            font-weight: 500;
            color: #64748B;
            padding: 12px 16px;
            border-bottom: 2px solid transparent;
            margin-bottom: -1px;
            transition: color 150ms;
        }
        .stTabs [data-baseweb="tab"]:hover {
            color: #E2E8F0;
        }
        .stTabs [aria-selected="true"] {
            color: #D4A056 !important;
            border-bottom-color: #D4A056 !important;
        }

        /* ============================================================
           7. 输入框
           ============================================================ */
        .stTextInput > div > div > input {
            background: rgba(19, 22, 31, 0.9);
            border: 1px solid rgba(255, 255, 255, 0.1);
            border-radius: 6px;
            color: #E2E8F0;
        }
        .stTextInput > div > div > input:focus {
            border-color: #D4A056;
            box-shadow: 0 0 0 1px rgba(212, 160, 86, 0.3);
        }

        /* selectbox 隐藏闪烁光标 */
        [data-baseweb="select"] input {
            caret-color: transparent !important;
        }

        /* ============================================================
           8. 分隔线
           ============================================================ */
        hr {
            border-color: rgba(255, 255, 255, 0.06);
            margin: 32px 0;
        }

        /* ============================================================
           9. 信息提示框
           ============================================================ */
        .stAlert {
            background: rgba(19, 22, 31, 0.7);
            border: 1px solid rgba(255, 255, 255, 0.05);
            border-radius: 6px;
        }

        /* ============================================================
           10. 历史模式标签
           ============================================================ */
        .history-badge {
            display: inline-block;
            background: rgba(78, 205, 196, 0.1);
            border: 1px solid rgba(78, 205, 196, 0.25);
            border-radius: 4px;
            padding: 2px 10px;
            font-size: 12px;
            color: #4ECDC4;
            font-weight: 400;
            font-family: 'Inter', sans-serif;
            vertical-align: middle;
        }

        /* ============================================================
           10b. 旋转点圈 spinner（loading 动画复用）
           ============================================================ */
        .dot-spinner {
            display: inline-block;
            width: 36px;
            height: 36px;
            border: 3px solid rgba(212, 160, 86, 0.15);
            border-top-color: #D4A056;
            border-radius: 50%;
            animation: spin 0.8s linear infinite;
        }
        @keyframes spin {
            to { transform: rotate(360deg); }
        }

        /* ============================================================
           11. API 用量卡片（侧边栏）
           ============================================================ */
        .token-card {
            background: rgba(19, 22, 31, 0.7);
            border: 1px solid rgba(255, 255, 255, 0.05);
            border-radius: 6px;
            padding: 16px;
            margin-top: 16px;
        }
        .token-card .label {
            font-size: 11px;
            color: #64748B;
            text-transform: uppercase;
            letter-spacing: 0.05em;
        }
        .token-card .value {
            font-size: 18px;
            font-weight: 700;
            color: #E2E8F0;
            font-family: 'Playfair Display', serif;
        }

        /* ============================================================
           12. 加载更多分隔条
           ============================================================ */
        .load-more-divider {
            text-align: center;
            padding: 12px;
            color: #64748B;
            font-size: 12px;
            border-top: 1px solid rgba(255, 255, 255, 0.04);
            cursor: pointer;
            transition: color 150ms;
        }
        .load-more-divider:hover {
            color: #D4A056;
        }

        /* ============================================================
           13. radio 水平按钮组样式
           ============================================================ */
        div[data-testid="stRadio"] > div {
            gap: 4px;
        }
        div[data-testid="stRadio"] label {
            padding: 6px 16px !important;
            border-radius: 4px !important;
            border: 1px solid rgba(255,255,255,0.06) !important;
            color: #64748B !important;
            font-size: 13px !important;
            font-weight: 500 !important;
        }
        div[data-testid="stRadio"] label:hover {
            color: #E2E8F0 !important;
            border-color: rgba(255,255,255,0.12) !important;
        }
        div[data-testid="stRadio"] label[data-selected="true"] {
            color: #D4A056 !important;
            border-color: #D4A056 !important;
            background: rgba(212, 160, 86, 0.08) !important;
        }

        /* ============================================================
           14. 热点卡片 / 列表视图
           ============================================================ */
        .hotlist-container {
            display: flex;
            flex-direction: column;
            gap: 8px;
        }
        .hot-row {
            display: flex;
            align-items: center;
            gap: 16px;
            background: rgba(19, 22, 31, 0.7);
            border: 1px solid rgba(255, 255, 255, 0.05);
            border-radius: 6px;
            padding: 14px 20px;
            text-decoration: none !important;
            transition: all 150ms ease-out;
            cursor: pointer;
            position: relative;
            box-shadow: 0 2px 12px rgba(0, 0, 0, 0.3);
        }
        .hot-row:hover {
            background: rgba(28, 32, 43, 0.9);
            border-color: rgba(255, 255, 255, 0.1);
            box-shadow: 0 4px 20px rgba(0, 0, 0, 0.45);
        }
        .hot-row.top3 {
            box-shadow: 0 0 20px rgba(212, 160, 86, 0.06);
            border-color: rgba(212, 160, 86, 0.12);
        }
        .hot-row.megahit {
            border-top: 2px solid #D4A056;
        }

        /* 卡片网格（2列） */
        .hot-cards-grid {
            display: grid;
            grid-template-columns: repeat(2, 1fr);
            gap: 16px;
        }
        @media (max-width: 900px) {
            .hot-cards-grid { grid-template-columns: 1fr; }
        }
        .hot-card {
            background: rgba(19, 22, 31, 0.7);
            border: 1px solid rgba(255, 255, 255, 0.05);
            border-radius: 6px;
            overflow: hidden;
            text-decoration: none !important;
            transition: all 150ms ease-out;
            cursor: pointer;
            position: relative;
            box-shadow: 0 2px 12px rgba(0, 0, 0, 0.3);
        }
        .hot-card:hover {
            background: rgba(28, 32, 43, 0.9);
            border-color: rgba(255, 255, 255, 0.1);
            transform: translateY(-2px);
            box-shadow: 0 8px 25px rgba(0, 0, 0, 0.45);
        }
        .hot-card.top3 {
            box-shadow: 0 0 20px rgba(212, 160, 86, 0.08);
            border-color: rgba(212, 160, 86, 0.15);
        }
        .hot-card.megahit {
            border-top: 2px solid #D4A056;
        }

        /* 排名徽章（卡片左上角浮层） */
        .rank-badge-float {
            position: absolute;
            top: 10px;
            left: 10px;
            z-index: 2;
            background: rgba(15, 17, 25, 0.85);
            backdrop-filter: blur(4px);
            border-radius: 4px;
            padding: 2px 8px;
            font-size: 13px;
            font-weight: 600;
            color: #94A3B8;
            border: 1px solid rgba(255, 255, 255, 0.08);
        }
        .rank-badge-float.rank-top3 {
            color: #D4A056;
            border-color: rgba(212, 160, 86, 0.3);
        }

        /* 排名徽章（列表行缩略图左上角覆盖） */
        .rank-badge-overlay {
            position: absolute;
            top: 3px;
            left: 3px;
            z-index: 2;
            background: rgba(15, 17, 25, 0.85);
            backdrop-filter: blur(4px);
            border-radius: 3px;
            padding: 1px 6px;
            font-size: 11px;
            font-weight: 600;
            color: #94A3B8;
            border: 1px solid rgba(255, 255, 255, 0.08);
        }
        .rank-badge-overlay.rank-top3 {
            color: #D4A056;
            border-color: rgba(212, 160, 86, 0.3);
        }

        /* 卡片缩略图 */
        .card-thumb {
            width: 100%;
            aspect-ratio: 16 / 9;
            background: linear-gradient(135deg, #1A1D28 0%, #252A3A 100%);
            overflow: hidden;
            position: relative;
        }
        .card-thumb img {
            width: 100%;
            height: 100%;
            object-fit: cover;
        }
        .card-thumb .thumb-placeholder {
            display: flex;
            align-items: center;
            justify-content: center;
            width: 100%;
            height: 100%;
            font-size: 28px;
            color: rgba(212, 160, 86, 0.3);
        }

        /* 列表行缩略图 */
        .row-thumb {
            width: 96px;
            height: 64px;
            border-radius: 4px;
            flex-shrink: 0;
            background: linear-gradient(135deg, #1A1D28 0%, #252A3A 100%);
            overflow: hidden;
            position: relative;
        }
        .row-thumb img {
            width: 100%;
            height: 100%;
            object-fit: cover;
        }
        .row-thumb .thumb-placeholder {
            display: flex;
            align-items: center;
            justify-content: center;
            width: 100%;
            height: 100%;
            font-size: 18px;
            color: rgba(212, 160, 86, 0.3);
        }

        /* 标题 */
        .hot-title {
            font-size: 17px;
            font-weight: 600;
            color: #E2E8F0;
            line-height: 1.45;
            margin-bottom: 6px;
            display: -webkit-box;
            -webkit-line-clamp: 2;
            -webkit-box-orient: vertical;
            overflow: hidden;
        }
        .hot-row .hot-title { font-size: 17px; }
        .hot-card .hot-title { font-size: 16px; }

        /* 热度数字 */
        .hot-score {
            font-family: 'Playfair Display', serif;
            font-weight: 700;
            color: #E2E8F0;
            white-space: nowrap;
            flex-shrink: 0;
        }
        .hot-row .hot-score {
            font-size: 22px;
            text-align: right;
            min-width: 80px;
        }
        .hot-card .hot-score {
            font-size: 24px;
            margin-bottom: 4px;
        }
        .hot-score.megahit { color: #D4A056; }

        /* 元信息行 */
        .hot-meta {
            font-size: 13px;
            color: #64748B;
            line-height: 1.5;
            display: flex;
            flex-wrap: wrap;
            gap: 4px 10px;
        }
        .hot-meta .sent-pos { color: #4ECDC4; font-weight: 500; }
        .hot-meta .sent-neg { color: #E74C3C; font-weight: 500; }
        .hot-meta .sent-neu { color: #D4A056; font-weight: 500; }

        /* 卡片正文区 */
        .card-body {
            padding: 14px 16px 16px;
        }

        /* 列表行正文区 */
        .hot-body {
            flex: 1;
            min-width: 0;
        }

        /* 空状态 */
        .hot-empty {
            text-align: center;
            padding: 48px 24px;
            background: rgba(19, 22, 31, 0.7);
            border: 1px dashed rgba(255, 255, 255, 0.08);
            border-radius: 6px;
            color: #64748B;
            font-size: 14px;
        }
    </style>
    <meta http-equiv="refresh" content="60">
    """, unsafe_allow_html=True)


inject_design_css()

# ============================================================
# 初始化
# ============================================================

init_db()
scheduler = _get_scheduler()
next_run = scheduler.get_job("auto_crawl")
next_time = next_run.next_run_time.strftime("%H:%M") if next_run and next_run.next_run_time else "—"

# ============================================================
# 工具函数
# ============================================================

PLATFORM_DISPLAY = {
    "weibo": "微博热搜",
    "bilibili": "B站热门",
}

# 散点图 10 色调色板 — 高饱和、高对比度，深色背景优化
SCATTER_COLORS = [
    "#FF6B6B", "#4ECDC4", "#FFD93D", "#6C5CE7", "#A8E6CF",
    "#FF8A5C", "#45B7D1", "#F8B500", "#FF477E", "#00D2FF",
]


def ai_sentiment_label(topic: dict) -> str:
    """从 AI 分析结果获取情绪标签，未分析时显示占位文本。"""
    label = topic.get("ai_label", "")
    if label:
        return label
    sentiment_val = topic.get("ai_sentiment", "")
    if sentiment_val:
        # 有 AI 分析但无 label，降级展示
        return {"positive": "正面", "neutral": "中性", "negative": "负面"}.get(sentiment_val, "—")
    # 未分析
    return "分析中…"


def sentiment_arrow(topic: dict) -> str:
    """根据 AI 情绪返回箭头指示符：▲ 正面 / ─ 中性 / ▼ 负面。"""
    sentiment_val = topic.get("ai_sentiment", "")
    if sentiment_val == "positive":
        return "▲"
    elif sentiment_val == "negative":
        return "▼"
    elif sentiment_val == "neutral":
        return "─"
    # 未分析
    return "…"


def _style_wind(val: str) -> str:
    """pandas Styler 回调：根据风向箭头返回对应颜色 + 大号字体。"""
    base = "font-size: 18px; font-weight: bold; "
    if val == "▲":
        return base + "color: #4ECDC4"   # 绿色（正面/上升）
    elif val == "▼":
        return base + "color: #E74C3C"   # 红色（负面/下降）
    elif val == "─":
        return base + "color: #D4A056"   # 金色（中性/平稳）
    return ""


def ai_verdict_short(topic: dict) -> str:
    """获取 AI 一句话简评，未分析时显示占位。"""
    verdict = topic.get("ai_verdict", "")
    if verdict:
        return verdict
    if topic.get("ai_sentiment", ""):
        return ""  # 分析了但无简评
    return "AI 生成中…"


def format_hot_score(score: float) -> str:
    """格式化热度值，带千万/百万标注。"""
    if score >= 10_000_000:
        return f"🔥🔥 {score:,.0f}"
    elif score >= 1_000_000:
        return f"🔥 {score:,.0f}"
    return f"{score:,.0f}"


def hot_score_megahit(score: float) -> bool:
    """是否千万级热度。"""
    return score >= 10_000_000


def extract_pubtime(raw_str: str):
    """从 raw_data JSON 提取发布时间 datetime。"""
    try:
        rd = _json.loads(raw_str) if isinstance(raw_str, str) else raw_str
        ts = rd.get("pubdate", 0)
        if ts and ts > 0:
            return _dt.fromtimestamp(ts)
    except Exception:
        pass
    return None


def format_pubtime(raw_str: str) -> str:
    """格式化发布时间。"""
    pt = extract_pubtime(raw_str)
    return pt.strftime("%m-%d %H:%M") if pt else "实时"


def format_freshness(raw_str: str, capture_time: str) -> str:
    """计算时效：抓取时间 - 发布时间。"""
    pt = extract_pubtime(raw_str)
    if pt:
        try:
            capture_dt = _dt.strptime(str(capture_time), "%Y-%m-%d %H:%M:%S")
        except ValueError:
            capture_dt = _dt.now()
        diff = capture_dt - pt
        hours = diff.total_seconds() / 3600
        if hours < 1:
            return f"{int(diff.total_seconds() / 60)}分钟前"
        elif hours < 24:
            return f"{int(hours)}小时前"
        else:
            return f"{int(hours / 24)}天前"
    return "—"


def rank_badge(rank_val: int) -> str:
    """排名徽章：Top 3 金色，Top 10 浅灰，其余无标记。"""
    return str(rank_val)


def extract_thumb_url(topic: dict) -> str:
    """从 raw_data JSON 提取缩略图 URL，无则返回空字符串。"""
    try:
        raw = topic.get("raw_data", "{}")
        rd = _json.loads(raw) if isinstance(raw, str) else raw
        return rd.get("thumb_url", "") or ""
    except Exception:
        return ""


def _build_rank_html(rank_val: int, view: str) -> str:
    """生成排名徽章 HTML。view: 'card' | 'list'"""
    is_top3 = rank_val <= 3
    top3_class = " rank-top3" if is_top3 else ""
    label = str(rank_val)
    if view == "card":
        return f"""<span class="rank-badge-float{top3_class}">{label}</span>"""
    else:
        return f"""<span class="rank-badge-overlay{top3_class}">{label}</span>"""


def _build_thumb_html(thumb_url: str, view: str, rank_html: str = "") -> str:
    """生成缩略图 HTML。view: 'card' | 'list'。rank_html 仅 list 视图叠加。"""
    thumb_class = "card-thumb" if view == "card" else "row-thumb"
    if thumb_url:
        img_html = f'<img src="{thumb_url}" loading="lazy" referrerpolicy="no-referrer" alt="">'
    else:
        placeholder_icon = "🔥"
        img_html = f'<span class="thumb-placeholder">{placeholder_icon}</span>'

    inner = img_html + (rank_html if view == "list" else "")
    return f'<div class="{thumb_class}">{inner}</div>'


def _build_meta_html(topic: dict) -> str:
    """生成元信息行：风向 + 标签 + 简评 + 时效。"""
    parts = []
    # 风向
    arrow = sentiment_arrow(topic)
    sent_val = topic.get("ai_sentiment", "")
    sent_class = {"positive": "sent-pos", "negative": "sent-neg", "neutral": "sent-neu"}.get(sent_val, "")
    if arrow and arrow != "…":
        parts.append(f'<span class="{sent_class}">{arrow} {ai_sentiment_label(topic)}</span>')
    # 简评（≤12字）
    verdict = ai_verdict_short(topic)
    if verdict and verdict != "AI 生成中…":
        short = verdict[:12] + ("…" if len(verdict) > 12 else "")
        parts.append(f"<span>{short}</span>")
    # 时效
    raw_data = topic.get("raw_data", "{}")
    capture_time = topic.get("captured_at", "未知")
    freshness = format_freshness(raw_data, str(capture_time))
    if freshness and freshness != "—":
        parts.append(f"<span>{freshness}</span>")
    return " · ".join(parts) if parts else ""


def render_hotlist(topics: list[dict], view: str, visible: int) -> str:
    """渲染热点列表为 HTML。

    view: 'list' | 'card'
    visible: 显示条数
    返回 HTML 字符串。
    """
    if not topics:
        return (
            '<div class="hot-empty">'
            '<p style="margin:0 0 8px; font-size:18px;">📡</p>'
            '<p style="margin:0;">暂无数据，等待自动抓取…</p>'
            '</div>'
        )

    items = topics[:visible]
    parts = []

    for topic in items:
        rank_val = topic.get("rank", 0)
        title = topic.get("title", "")
        url = topic.get("url", "")
        hot_score = topic.get("hot_score", 0)
        is_megahit = hot_score >= 10_000_000
        is_top3 = rank_val <= 3

        thumb_url = extract_thumb_url(topic)

        # 热度格式化
        if is_megahit:
            score_str = f"🔥🔥 {hot_score:,.0f}"
            score_class = "hot-score megahit"
        elif hot_score >= 1_000_000:
            score_str = f"🔥 {hot_score:,.0f}"
            score_class = "hot-score"
        else:
            score_str = f"{hot_score:,.0f}"
            score_class = "hot-score"

        # 元信息
        meta_html = _build_meta_html(topic)

        # CSS 类
        extra_classes = []
        if is_top3:
            extra_classes.append("top3")
        if is_megahit:
            extra_classes.append("megahit")
        class_str = " ".join(extra_classes)

        if view == "card":
            rank_html_full = _build_rank_html(rank_val, "card")
            thumb_html = _build_thumb_html(thumb_url, "card")
            # 卡片：缩略图置顶 → 排名浮层 → 正文（无缩进，避免 markdown 代码块）
            parts.append(
                f'<a href="{url}" target="_blank" class="hot-card {class_str}" rel="noopener">'
                f'{rank_html_full}{thumb_html}'
                f'<div class="card-body">'
                f'<div class="hot-title">{title}</div>'
                f'<div class="{score_class}">{score_str}</div>'
                f'<div class="hot-meta">{meta_html}</div>'
                f'</div>'
                f'</a>'
            )
        else:
            rank_overlay = _build_rank_html(rank_val, "list")
            thumb_html = _build_thumb_html(thumb_url, "list", rank_overlay)
            # 列表：缩略图·排名叠加在左 → 标题+元信息 → 热度在右
            parts.append(
                f'<a href="{url}" target="_blank" class="hot-row {class_str}" rel="noopener">'
                f'{thumb_html}'
                f'<div class="hot-body">'
                f'<div class="hot-title">{title}</div>'
                f'<div class="hot-meta">{meta_html}</div>'
                f'</div>'
                f'<div class="{score_class}">{score_str}</div>'
                f'</a>'
            )

    container_class = "hotlist-container" if view == "list" else "hot-cards-grid"
    inner = "\n".join(parts)
    return f'<div class="{container_class}">\n{inner}\n</div>'


def generate_verdict(topics: list[dict], platform_name: str) -> str:
    """根据数据生成编辑式 VERDICT 结论。"""
    if not topics:
        return "暂无数据，等待自动抓取获取最新热点。"
    count = len(topics)
    pos = sum(
        1 for t in topics
        if (t.get("ai_sentiment") == "positive") or
           (not t.get("ai_sentiment") and (t.get("sentiment") or 0.5) >= 0.6)
    )
    neg = sum(
        1 for t in topics
        if (t.get("ai_sentiment") == "negative") or
           (not t.get("ai_sentiment") and (t.get("sentiment") or 0.5) <= 0.4)
    )
    pos_pct = pos / count * 100
    neg_pct = neg / count * 100

    if platform_name == "weibo":
        if pos_pct >= 55:
            return f"舆论环境偏积极，正面话题占比 {pos_pct:.0f}%，适合内容创作与话题跟进。"
        elif neg_pct >= 30:
            return f"负面情绪占比 {neg_pct:.0f}%，争议话题集中，建议谨慎选题。"
        else:
            return f"情绪分布均衡，正面 {pos_pct:.0f}%、中性 {100-pos_pct-neg_pct:.0f}%、负面 {neg_pct:.0f}%。"
    elif platform_name == "bilibili":
        avg_views = round(sum(t.get("hot_score", 0) for t in topics) / count) if count else 0
        if avg_views > 500000:
            return f"均播放 {avg_views/10000:.0f} 万，内容消费需求旺盛，正面占比 {pos_pct:.0f}%。"
        elif avg_views > 100000:
            return f"均播放 {avg_views/10000:.0f} 万，各区表现均衡，用户兴趣多元化。"
        else:
            return f"播放量平稳，正面占比 {pos_pct:.0f}%，话题有待发酵。"
    return "数据正常更新中。"


def kpi_section(topics: list[dict]) -> dict:
    """计算 KPI 摘要。"""
    count = len(topics)
    pos = sum(
        1 for t in topics
        if (t.get("ai_sentiment") == "positive") or
           (not t.get("ai_sentiment") and (t.get("sentiment") or 0.5) >= 0.6)
    )
    neg = sum(
        1 for t in topics
        if (t.get("ai_sentiment") == "negative") or
           (not t.get("ai_sentiment") and (t.get("sentiment") or 0.5) <= 0.4)
    )
    neu = count - pos - neg
    avg_score = round(sum(t.get("hot_score", 0) for t in topics) / count, 1) if count else 0
    megahit_count = sum(1 for t in topics if t.get("hot_score", 0) >= 10_000_000)
    return {
        "count": count,
        "pos": pos,
        "neg": neg,
        "neu": neu,
        "avg_score": avg_score,
        "pos_pct": round(pos / count * 100) if count else 0,
        "megahit_count": megahit_count,
    }


# ============================================================
# 侧边栏 — 平台 + 时间 + API 用量
# ============================================================

with st.sidebar:
    st.markdown("### 🔥 TrendRadar")
    st.caption(f"⏱ 下次自动抓取: {next_time}")

    st.divider()

    # 平台选择
    selected_platform = st.selectbox(
        "平台",
        options=list(FETCHERS.keys()),
        format_func=lambda k: PLATFORM_DISPLAY[k],
        key="sidebar_platform",
    )

    # 时间维度
    SIDEBAR_TIME_OPTIONS = {
        "今日": "today",
        "最近7天": "7days",
    }
    selected_time_label = st.radio(
        " ",
        list(SIDEBAR_TIME_OPTIONS.keys()),
        horizontal=True,
        label_visibility="collapsed",
        key="sidebar_time",
    )
    selected_time = SIDEBAR_TIME_OPTIONS[selected_time_label]
    is_history = selected_time != "today"

    st.divider()

    # API 用量卡片
    token_stats = get_token_stats()
    today = token_stats["today"]
    month = token_stats["month"]
    last = token_stats["last_call"]

    st.markdown("#### 📊 API 用量")

    st.markdown(f"""
    <div class="token-card">
        <div class="label">今日消耗</div>
        <div class="value">{today['total_tokens']:,} tokens</div>
        <div style="font-size:12px; color:#64748B; margin-top:4px;">
            {today['calls']} 次调用
        </div>
    </div>
    """, unsafe_allow_html=True)

    st.markdown(f"""
    <div class="token-card">
        <div class="label">本月累计</div>
        <div class="value">{month['total_tokens']:,} tokens</div>
        <div style="font-size:12px; color:#64748B; margin-top:4px;">
            {month['calls']} 次调用
        </div>
    </div>
    """, unsafe_allow_html=True)

    if last:
        st.caption(
            f"最近调用: {last['timestamp']} | "
            f"{last['prompt_tokens']}+{last['completion_tokens']} tokens"
        )
    else:
        st.caption("暂无 API 调用记录")

def render_echarts_chart(
    trend_data: list[dict],
    sent_dist: dict,
    time_window: str,
    update_time_iso: str,
) -> str:
    """生成 ECharts 散点图 + 环形图完整 HTML。

    trend_data: get_ranking_trend / get_weekly_trend_events 返回格式
    sent_dist: get_sentiment_distribution 返回格式
    time_window: "today" | "7days"
    update_time_iso: 当前时间的 ISO 字符串，用于前端计算相对时间
    """
    # 合并 AI 情绪信息到 trend_data
    for t in trend_data:
        t.setdefault("ai_sentiment", "")
        t.setdefault("ai_label", "")
        t.setdefault("ai_verdict", "")

    # 读取本地 ECharts JS（避免 CDN 超时）
    _echarts_js_path = Path(__file__).resolve().parent / "static" / "echarts.min.js"
    _echarts_js = _echarts_js_path.read_text(encoding="utf-8")

    trend_json = _json.dumps(trend_data, ensure_ascii=False)
    sent_json = _json.dumps(sent_dist, ensure_ascii=False)
    colors_json = _json.dumps(SCATTER_COLORS, ensure_ascii=False)
    time_fmt = "%H:%M" if time_window == "today" else "%m-%d"

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<script>""" + _echarts_js + f"""</script>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{
    background: #0F1119;
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
    padding: 0;
  }}
  #scatter-chart {{ width: 100%; height: 400px; }}
  #update-info {{
    text-align: center;
    padding: 4px 0 10px;
    font-size: 11px;
    color: #64748B;
    letter-spacing: 0.03em;
    font-family: 'Inter', sans-serif;
  }}
  #donut-chart {{ width: 100%; height: 200px; }}
  .empty-state {{
    display: flex;
    align-items: center;
    justify-content: center;
    height: 400px;
    color: #64748B;
    font-size: 14px;
    font-family: 'Inter', sans-serif;
  }}
</style>
</head>
<body>
<div id="scatter-chart"></div>
<div id="update-info"></div>
<div id="donut-chart"></div>
<script>
(function() {{
  const scatterDom = document.getElementById('scatter-chart');
  const donutDom = document.getElementById('donut-chart');
  const updateDom = document.getElementById('update-info');
  const trendData = {trend_json};
  const sentDist = {sent_json};
  const COLORS = {colors_json};
  const updateTimeISO = "{update_time_iso}";

  // ---- 更新时间戳 ----
  function updateTimeDisplay() {{
    const now = new Date();
    const ut = new Date(updateTimeISO);
    if (isNaN(ut.getTime())) {{ updateDom.textContent = '🕐 数据更新于 …'; return; }}
    const diffMin = Math.max(0, Math.floor((now - ut) / 60000));
    let relative;
    if (diffMin < 1) relative = '刚刚';
    else if (diffMin < 60) relative = diffMin + '分钟前';
    else relative = Math.floor(diffMin / 60) + '小时前';
    const hh = String(ut.getHours()).padStart(2,'0');
    const mm = String(ut.getMinutes()).padStart(2,'0');
    updateDom.textContent = '🕐 数据更新于 ' + hh + ':' + mm + '（' + relative + '）';
  }}
  updateTimeDisplay();
  setInterval(updateTimeDisplay, 60000);

  // ---- 环形图 ----
  if (sentDist.total > 0) {{
    const donut = echarts.init(donutDom);
    donut.setOption({{
      backgroundColor: '#0F1119',
      tooltip: {{
        trigger: 'item',
        backgroundColor: 'rgba(19,22,31,0.95)',
        borderColor: 'rgba(255,255,255,0.08)',
        textStyle: {{ color: '#E2E8F0', fontSize: 12, fontFamily: 'Inter, sans-serif' }},
        formatter: '{{b}}: {{c}} 条 ({{d}}%)'
      }},
      series: [{{
        type: 'pie',
        radius: ['55%', '78%'],
        center: ['50%', '50%'],
        avoidLabelOverlap: false,
        itemStyle: {{ borderColor: '#0F1119', borderWidth: 2 }},
        label: {{ show: false }},
        emphasis: {{
          scaleSize: 8,
          label: {{ show: true, fontSize: 14, fontWeight: 'bold', color: '#E2E8F0' }}
        }},
        data: [
          {{ value: sentDist.positive, name: '😊 正面', itemStyle: {{ color: '#4ECDC4' }} }},
          {{ value: sentDist.neutral,  name: '😐 中性', itemStyle: {{ color: '#94A3B8' }} }},
          {{ value: sentDist.negative, name: '😡 负面', itemStyle: {{ color: '#E74C3C' }} }}
        ]
      }}],
      graphic: [
        {{
          type: 'text', left: 'center', top: '38%',
          style: {{
            text: sentDist.total.toString(),
            textAlign: 'center',
            fill: '#E2E8F0',
            font: '700 22px "Playfair Display", serif'
          }}
        }},
        {{
          type: 'text', left: 'center', top: '56%',
          style: {{
            text: '正面 ' + sentDist.positive_pct + '%',
            textAlign: 'center',
            fill: '#4ECDC4',
            font: '500 12px "Inter", sans-serif'
          }}
        }}
      ]
    }});
  }}

  // ---- 散点图 ----
  if (!trendData || trendData.length === 0) {{
    scatterDom.innerHTML = '<div class="empty-state">暂无趋势数据，等待自动抓取开始积累</div>';
    return;
  }}
  const hasEnough = trendData.some(function(t) {{ return t.data_points && t.data_points.length >= 2; }});
  if (!hasEnough) {{
    scatterDom.innerHTML = '<div class="empty-state">数据积累中，需要更多抓取周期</div>';
    return;
  }}

  const scatterChart = echarts.init(scatterDom);
  const numEvents = trendData.length;

  // 计算气泡大小范围（对数映射）
  let minScore = Infinity, maxScore = -Infinity;
  trendData.forEach(function(event) {{
    (event.data_points||[]).forEach(function(dp) {{
      var s = dp.hot_score || 0;
      if (s < minScore) minScore = s;
      if (s > maxScore) maxScore = s;
    }});
  }});
  if (minScore <= 0) minScore = 1;
  var logMin = Math.log10(minScore);
  var logMax = Math.log10(maxScore);
  var logRange = (logMax - logMin) || 1;

  function bubbleSize(score) {{
    var s = Math.max(score || 0, 1);
    var n = (Math.log10(s) - logMin) / logRange;
    return 8 + n * 52;
  }}

  // 情绪显示
  function sentLabel(s) {{
    if (s === 'positive') return '▲ 正面';
    if (s === 'negative') return '▼ 负面';
    if (s === 'neutral')  return '─ 中性';
    return '';
  }}
  function sentColor(s) {{
    if (s === 'positive') return '#4ECDC4';
    if (s === 'negative') return '#E74C3C';
    return '#D4A056';
  }}

  // 构建 series
  var scatterSeries = [];
  var lineSeries = [];
  trendData.forEach(function(event, i) {{
    var color = COLORS[i % COLORS.length];
    var points = (event.data_points||[]).map(function(dp) {{
      return {{
        value: [
          dp.captured_at || '',
          dp.hot_score || 0,
          dp.rank || 0,
          event.ai_sentiment || '',
          event.ai_verdict || ''
        ],
        symbolSize: bubbleSize(dp.hot_score||0)
      }};
    }});

    scatterSeries.push({{
      type: 'scatter',
      name: (event.title||'').length > 18 ? (event.title||'').substring(0,18)+'…' : (event.title||''),
      data: points,
      itemStyle: {{ color: color, opacity: 0.85 }},
      emphasis: {{
        focus: 'series',
        blurScope: 'coordinateSystem',
        scale: 1.3,
        itemStyle: {{ shadowBlur: 12, shadowColor: color, borderColor: '#fff', borderWidth: 1 }}
      }},
      blur: {{
        itemStyle: {{ opacity: 0.12 }}
      }},
      encode: {{ x: 0, y: 1 }}
    }});

    // 隐藏连线 series（hover 时显现）
    var sorted = points.slice().sort(function(a,b) {{
      return new Date(a.value[0]) - new Date(b.value[0]);
    }});
    lineSeries.push({{
      type: 'line',
      name: '__line_' + i,
      data: sorted.map(function(p) {{ return [p.value[0], p.value[1]]; }}),
      lineStyle: {{ color: color, type: 'dashed', width: 1.5, opacity: 0 }},
      itemStyle: {{ opacity: 0 }},
      symbol: 'none',
      silent: true,
      z: 0,
      emphasis: {{
        lineStyle: {{ opacity: 0.45 }},
        itemStyle: {{ opacity: 0 }}
      }}
    }});
  }});

  scatterChart.setOption({{
    backgroundColor: '#0F1119',
    toolbox: {{
      right: 16, top: 8,
      itemSize: 14,
      iconStyle: {{ borderColor: '#64748B' }},
      emphasis: {{ iconStyle: {{ borderColor: '#D4A056' }} }},
      feature: {{ restore: {{ title: '还原' }} }}
    }},
    tooltip: {{
      trigger: 'item',
      triggerOn: 'mousemove',
      backgroundColor: 'rgba(19,22,31,0.95)',
      borderColor: 'rgba(255,255,255,0.08)',
      textStyle: {{ color: '#E2E8F0', fontSize: 13, fontFamily: 'Inter, sans-serif' }},
      extraCssText: 'border-radius:6px;box-shadow:0 4px 24px rgba(0,0,0,0.5);',
      formatter: function(params) {{
        if (params.seriesType !== 'scatter' || !params.data) return '';
        var v = params.data.value || params.data;
        var title = params.seriesName || '';
        var rank = v[2];
        var score = v[1];
        var sent = v[3] || '';
        var verdict = v[4] || '';
        var time = v[0] || '';
        var h = '<div style="font-weight:600;font-size:14px;margin-bottom:6px;color:#E2E8F0;">' + title + '</div>';
        h += '<div style="font-size:12px;color:#94A3B8;line-height:1.9;">';
        h += '排名 <b style="color:#D4A056">#' + rank + '</b> · 热度 <b style="color:#E2E8F0">' + Number(score).toLocaleString() + '</b>';
        if (sent) h += '<br/><span style="color:' + sentColor(sent) + '">' + sentLabel(sent) + '</span>';
        if (verdict) {{
          var short = verdict.length > 20 ? verdict.substring(0,20) + '…' : verdict;
          h += ' <span style="color:#64748B;font-size:11px;">' + short + '</span>';
        }}
        h += '<br/><span style="color:#64748B;font-size:11px;">' + time + '</span>';
        h += '</div>';
        return h;
      }}
    }},
    legend: {{
      data: scatterSeries.map(function(s) {{ return s.name; }}),
      bottom: 0,
      textStyle: {{ color: '#94A3B8', fontSize: 11, fontFamily: 'Inter, sans-serif' }},
      itemWidth: 10,
      itemHeight: 10,
      itemGap: 16
    }},
    grid: {{
      left: 56, right: 24, top: 16, bottom: 60,
      containLabel: false
    }},
    xAxis: {{
      type: 'time',
      axisLine: {{ lineStyle: {{ color: 'rgba(255,255,255,0.1)' }} }},
      axisTick: {{ show: false }},
      axisLabel: {{ color: '#64748B', fontSize: 10, fontFamily: 'Inter, sans-serif' }},
      splitLine: {{ lineStyle: {{ color: 'rgba(255,255,255,0.04)' }} }}
    }},
    yAxis: {{
      type: 'value',
      name: '热度',
      nameTextStyle: {{ color: '#64748B', fontSize: 10, fontFamily: 'Inter, sans-serif' }},
      axisLine: {{ show: false }},
      axisTick: {{ show: false }},
      axisLabel: {{
        color: '#64748B', fontSize: 10, fontFamily: 'Inter, sans-serif',
        formatter: function(v) {{ return v >= 10000 ? (v/10000).toFixed(0)+'万' : v; }}
      }},
      splitLine: {{ lineStyle: {{ color: 'rgba(255,255,255,0.04)' }} }}
    }},
    dataZoom: [
      {{
        type: 'inside',
        xAxisIndex: 0,
        zoomOnMouseWheel: true,
        moveOnMouseMove: true,
        moveOnMouseWheel: false,
        minSpan: 5,
        maxSpan: 100
      }},
      {{
        type: 'slider',
        xAxisIndex: 0,
        bottom: 2,
        height: 22,
        showDataShadow: true,
        dataBackground: {{
          lineStyle: {{ color: 'rgba(255,255,255,0.08)', width: 0.5 }},
          areaStyle: {{ color: 'rgba(255,255,255,0.03)' }}
        }},
        borderColor: 'rgba(255,255,255,0.06)',
        handleStyle: {{ color: '#64748B', borderColor: '#64748B' }},
        selectedDataBackground: {{
          lineStyle: {{ color: 'rgba(255,255,255,0.15)' }},
          areaStyle: {{ color: 'rgba(255,255,255,0.06)' }}
        }},
        textStyle: {{ color: '#64748B', fontSize: 10 }},
        fillerColor: 'rgba(212,160,86,0.15)',
        minSpan: 5,
        maxSpan: 100
      }}
    ],
    series: scatterSeries.concat(lineSeries)
  }});

  // ---- 悬停交互：emphasis 原生发光 + dispatchAction 驱动连线 ----
  scatterChart.on('mouseover', function(params) {{
    if (params.seriesType === 'scatter' && params.seriesIndex < numEvents) {{
      scatterChart.dispatchAction({{ type: 'downplay' }});
      scatterChart.dispatchAction({{ type: 'highlight', seriesIndex: numEvents + params.seriesIndex }});
    }}
  }});
  scatterChart.on('globalout', function() {{
    scatterChart.dispatchAction({{ type: 'downplay' }});
  }});

  // ---- 拖拽缩放时隐藏 tooltip，避免按下去弹窗 ----
  scatterChart.on('datazoom', function() {{
    scatterChart.dispatchAction({{ type: 'hideTip' }});
  }});

  // 响应式
  window.addEventListener('resize', function() {{
    scatterChart.resize();
    var d = echarts.getInstanceByDom(donutDom);
    if (d) d.resize();
  }});
}})();
</script>
</body>
</html>"""


# ============================================================
# 数据加载（单平台，跟随侧边栏选择）
# ============================================================

if selected_time == "today":
    topics = get_latest_topics(selected_platform)
else:
    topics = get_weekly_topics(selected_platform)

chart_platform = selected_platform

# ============================================================
# Hero 区域 — KPI + VERDICT
# ============================================================

total_count = len(topics)
total_pos = sum(
    1 for t in topics
    if (t.get("ai_sentiment") == "positive") or
       (not t.get("ai_sentiment") and (t.get("sentiment") or 0.5) >= 0.6)
)
total_megahit = sum(1 for t in topics if t.get("hot_score", 0) >= 10_000_000)

st.markdown(f"""
<h2 style="font-family: 'Playfair Display', serif; font-size: 28px; font-weight: 700;
           color: #E2E8F0; margin-bottom: 24px; letter-spacing: -0.01em;">
    {selected_time_label}热点概览
</h2>
""", unsafe_allow_html=True)

kpi_cols = st.columns(3)
with kpi_cols[0]:
    st.metric(label="热点总数", value=f"{total_count} 条")
with kpi_cols[1]:
    overall_pos_pct = round(total_pos / total_count * 100) if total_count else 0
    st.metric(
        label="正面情绪占比",
        value=f"{overall_pos_pct}%",
        delta=f"😊 {total_pos} 条正面",
    )
with kpi_cols[2]:
    avg_hot = round(sum(t.get("hot_score", 0) for t in topics) / total_count) if total_count else 0
    st.metric(
        label="平均热度值",
        value=f"{avg_hot:,.0f}",
        delta=f"🔥🔥 {total_megahit} 条千万级" if total_megahit else None,
    )

# 总评
verdict_text = generate_verdict(topics, selected_platform)
verdict_html = f"**{PLATFORM_DISPLAY[selected_platform]}**：{verdict_text}"
st.markdown(f"""
<div style="
    background: rgba(19, 22, 31, 0.7);
    border: 1px solid rgba(212, 160, 86, 0.3);
    border-radius: 6px;
    padding: 16px 24px;
    margin: 24px 0 0 0;
    box-shadow: 0 4px 30px rgba(0, 0, 0, 0.5);
">
    <span style="
        font-size: 11px;
        font-weight: 600;
        color: #D4A056;
        text-transform: uppercase;
        letter-spacing: 0.08em;
        margin-right: 12px;
    ">总评</span>
    <span style="
        font-size: 14px;
        color: #94A3B8;
        line-height: 1.8;
    ">{verdict_html}</span>
</div>
""", unsafe_allow_html=True)

st.divider()

# ============================================================
# 图表区 — ECharts 散点图（全宽）+ 情绪环形图（下方）
# ============================================================

# 标题 + 历史标签同行，消除垂直抖动
history_badge = f"""<span class="history-badge" style="margin-left:12px; vertical-align:middle;">📅 {selected_time_label}回溯</span>""" if is_history else ""

st.markdown(f"""
<h3 style="font-family: 'Playfair Display', serif; font-size: 22px; font-weight: 600;
           color: #E2E8F0; margin-bottom: 16px;">
    数据洞察 · {PLATFORM_DISPLAY.get(chart_platform, chart_platform)}{history_badge}
</h3>
""", unsafe_allow_html=True)

# ---- 降采样：1min 抓取频率下限制每事件点数 ----
def _decimate(data_points: list, max_points: int) -> list:
    """从 data_points 中均匀抽取最多 max_points 个点（含首尾）。"""
    n = len(data_points)
    if n <= max_points:
        return data_points
    step = (n - 1) / (max_points - 1)
    return [data_points[round(i * step)] for i in range(max_points)]

_DECIMATE_LIMITS = {"today": 60, "7days": 80, "week": 60, "month": 100, "year": 120}

# 加载数据：7 天用出现次数 Top N，今日用最新 Top N
if selected_time == "7days":
    trend_data = get_weekly_trend_events(chart_platform, top_n=8)
else:
    trend_data = get_ranking_trend(chart_platform, selected_time, top_n=5)

# 对每个事件的数据点做降采样
_limit = _DECIMATE_LIMITS.get(selected_time, 60)
if trend_data:
    trend_data = [
        {**t, "data_points": _decimate(t.get("data_points", []), _limit)}
        for t in trend_data
    ]

sent_dist = get_sentiment_distribution(chart_platform, selected_time)

# 合并 AI 情绪信息到 trend_data（用于 tooltip）
if trend_data:
    topic_keys = [t["topic_key"] for t in trend_data]
    if topic_keys:
        import sqlite3
        _conn = sqlite3.connect(str(db.DB_PATH))
        _conn.row_factory = sqlite3.Row
        _placeholders = ",".join("?" for _ in topic_keys)
        _sent_rows = _conn.execute(
            f"""SELECT ta.topic_key, ta.sentiment, ta.label, ta.verdict_short
                FROM topic_analysis ta
                INNER JOIN (
                    SELECT topic_key, MAX(captured_at) AS max_cap
                    FROM topic_analysis
                    WHERE topic_key IN ({_placeholders})
                    GROUP BY topic_key
                ) latest ON ta.topic_key = latest.topic_key AND ta.captured_at = latest.max_cap""",
            topic_keys,
        ).fetchall()
        _conn.close()
        _sent_map: dict[str, dict] = {r["topic_key"]: dict(r) for r in _sent_rows}
        for t in trend_data:
            s = _sent_map.get(t["topic_key"], {})
            t["ai_sentiment"] = s.get("sentiment", "")
            t["ai_label"] = s.get("label", "")
            t["ai_verdict"] = s.get("verdict_short", "")

# 生成当前时间 ISO 供前端"数据更新于"计算
from datetime import datetime as _dt_now
_update_iso = _dt_now.now().isoformat()

# 渲染 ECharts
echarts_html = render_echarts_chart(trend_data, sent_dist, selected_time, _update_iso)
st.components.v1.html(echarts_html, height=650)

st.divider()

# ============================================================
# 实时榜单
# ============================================================

st.markdown("""
<h3 style="font-family: 'Playfair Display', serif; font-size: 22px; font-weight: 600;
           color: #E2E8F0; margin-bottom: 8px;">
    实时热点榜单
</h3>
""", unsafe_allow_html=True)

PAGE_SIZE = 12

capture_time = topics[0].get("captured_at", "未知") if topics else "未知"
total_count = len(topics)

load_key = f"hot_visible_{selected_platform}"
if load_key not in st.session_state:
    st.session_state[load_key] = PAGE_SIZE
visible = st.session_state[load_key]

# 抓取信息行
st.caption(f"抓取: {capture_time} · 共 {total_count} 条")

# 渲染列表
html = render_hotlist(topics, "列表", visible)
st.markdown(html, unsafe_allow_html=True)

# 加载更多
if total_count > visible:
    remaining = total_count - visible
    if st.button(
        f"▼ 加载更多（还有 {remaining} 条）",
        key=f"load_more_{selected_platform}",
        use_container_width=True,
    ):
        st.session_state[load_key] = visible + PAGE_SIZE
        st.rerun()

# ============================================================
# 页脚 — 数据溯源
# ============================================================

st.divider()
st.markdown("""
<p style="font-family: 'Playfair Display', serif; font-size: 18px; font-weight: 600;
          color: #E2E8F0; margin-bottom: 16px;">
    数据溯源
</p>
""", unsafe_allow_html=True)

source_info = {
    "微博热搜": {
        "url": "https://weibo.com/ajax/side/hotSearch",
        "method": "HTTP API（需 Referer）",
        "fields": "排名、标题、热度值、分类标签",
    },
    "B站热门": {
        "url": "https://api.bilibili.com/x/web-interface/popular",
        "method": "HTTP API（公开）",
        "fields": "排名、标题、播放量、弹幕数、UP主、分区、发布时间",
    },
}

footer_cols = st.columns(len(source_info))
for j, (name, info) in enumerate(source_info.items()):
    with footer_cols[j]:
        st.markdown(f"""
        <div style="
            background: rgba(19, 22, 31, 0.7);
            border: 1px solid rgba(255, 255, 255, 0.05);
            border-radius: 6px;
            padding: 24px;
            box-shadow: 0 4px 30px rgba(0, 0, 0, 0.5);
        ">
            <div style="
                font-size: 14px; font-weight: 600;
                color: #E2E8F0; margin-bottom: 12px;
            ">{name}</div>
            <div style="
                font-size: 12px; color: #64748B; line-height: 2;
            ">
                <div>接口: <a href="{info['url']}" target="_blank"
                    style="color: #D4A056; text-decoration: none;">{info['url'][:40]}…</a></div>
                <div>方式: {info['method']}</div>
                <div>字段: {info['fields']}</div>
            </div>
        </div>
        """, unsafe_allow_html=True)
