"""
Streamlit 看板 — 社交媒体热点追踪。
深色编辑叙事风，严格遵循 docs/design.md 设计规范。
启动方式: uv run streamlit run main.py
"""

import json as _json
from datetime import datetime as _dt

import altair as alt
import pandas as pd
import streamlit as st
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from db import init_db, get_latest_topics, get_trend
from spider import crawl_and_save, FETCHERS

# ============================================================
# 定时调度器 — 每半小时自动抓取（北京时间 :00 和 :30）
# ============================================================


def _init_scheduler() -> BackgroundScheduler:
    """创建后台调度器，只在首次创建。"""
    if "scheduler" not in st.session_state:
        scheduler = BackgroundScheduler(timezone="Asia/Shanghai")
        scheduler.add_job(
            crawl_and_save,
            trigger=CronTrigger(minute="0,30"),
            id="auto_crawl",
            name="自动抓取热点",
            replace_existing=True,
        )
        scheduler.start()
        st.session_state["scheduler"] = scheduler
        st.session_state["scheduler_started"] = _dt.now().strftime("%H:%M:%S")
    return st.session_state["scheduler"]


# ============================================================
# 页面配置（必须是第一个 Streamlit 命令）
# ============================================================

st.set_page_config(
    page_title="热点趋势看板",
    page_icon="🔥",
    layout="wide",
)

# ============================================================
# 全局 CSS — 深色编辑叙事风，对照 docs/design.md
# ============================================================


def inject_design_css() -> None:
    """注入 Google Fonts + 全局 CSS，严格遵循 docs/design.md。"""
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

        /* 滚动条 */
        ::-webkit-scrollbar { width: 6px; height: 6px; }
        ::-webkit-scrollbar-track { background: #0F1119; }
        ::-webkit-scrollbar-thumb { background: #2D3142; border-radius: 3px; }
        ::-webkit-scrollbar-thumb:hover { background: #3F4458; }

        /* ============================================================
           1. 顶部导航条 — design.md §4.3
              border-bottom + 半透明背景
           ============================================================ */
        header[data-testid="stHeader"] {
            background: rgba(15, 17, 25, 0.9) !important;
            backdrop-filter: blur(8px);
            border-bottom: 1px solid rgba(255, 255, 255, 0.05);
        }

        /* 侧边栏 — 深色 */
        [data-testid="stSidebar"] {
            background: #0F1119;
            border-right: 1px solid rgba(255, 255, 255, 0.05);
        }
        [data-testid="stSidebar"] * {
            color: #E2E8F0 !important;
        }
        [data-testid="stSidebar"] .stButton > button {
            width: 100%;
        }

        /* ============================================================
           2. 文字层级 — design.md §2
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
           3. 卡片 — 玻璃拟态 — design.md §4.1
              background: rgba(19,22,31,0.7)
              border: 1px solid rgba(255,255,255,0.05)
              border-radius: 6px
              box-shadow: 0 4px 30px rgba(0,0,0,0.5)
           ============================================================ */
        .glass-card {
            background: rgba(19, 22, 31, 0.7) !important;
            border: 1px solid rgba(255, 255, 255, 0.05) !important;
            border-radius: 6px !important;
            padding: 24px !important;
            box-shadow: 0 4px 30px rgba(0, 0, 0, 0.5) !important;
        }

        /* Streamlit 原生容器近似玻璃效果 */
        [data-testid="stMetric"] {
            background: rgba(19, 22, 31, 0.7);
            border: 1px solid rgba(255, 255, 255, 0.05);
            border-radius: 6px;
            padding: 24px;
            box-shadow: 0 4px 30px rgba(0, 0, 0, 0.5);
        }
        [data-testid="stMetric"] > div {
            background: transparent;
            border: none;
            box-shadow: none;
            padding: 0;
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

        /* 表格容器 — 玻璃卡片 */
        [data-testid="stDataFrame"] {
            background: transparent !important;
            border: none !important;
            box-shadow: none !important;
        }

        /* ============================================================
           4. 按钮 — design.md §4.2
              Primary: 金色轮廓线框
              Secondary: 半透明深色填充
           ============================================================ */
        /* Secondary（默认） */
        .stButton > button {
            background: rgba(30, 35, 48, 0.9);
            border: 1px solid rgba(255, 255, 255, 0.08);
            border-radius: 6px;
            color: #E2E8F0;
            font-size: 13px;
            font-weight: 500;
            padding: 8px 16px;
            transition: all 150ms ease-out;
        }
        .stButton > button:hover {
            background: rgba(40, 45, 58, 0.9);
            color: #FFFFFF;
            border-color: rgba(255, 255, 255, 0.15);
        }

        /* Primary 按钮 — 金色轮廓线框 */
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
           5. 表格 — design.md §4.5
              无竖线、微弱横线、小表头
           ============================================================ */
        [data-testid="stDataFrame"] thead tr th {
            background: transparent !important;
            font-size: 11px !important;
            font-weight: 500 !important;
            color: #64748B !important;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            padding: 12px 16px !important;
            border-bottom: 1px solid rgba(255, 255, 255, 0.06) !important;
            border-right: none !important;
        }
        [data-testid="stDataFrame"] tbody tr td {
            font-size: 14px;
            color: #94A3B8;
            padding: 12px 16px !important;
            border-bottom: 1px solid rgba(255, 255, 255, 0.03) !important;
            border-right: none !important;
            vertical-align: middle;
        }
        [data-testid="stDataFrame"] tbody tr:hover td {
            background: rgba(255, 255, 255, 0.02) !important;
        }

        /* ============================================================
           6. Tab — design.md §4.3 导航激活态
              bottom border 指示器
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
           7. 输入框 — design.md §4.4
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

        /* 多选下拉 */
        .stMultiSelect [data-baseweb="select"] > div {
            background: rgba(19, 22, 31, 0.9);
            border: 1px solid rgba(255, 255, 255, 0.1);
            border-radius: 6px;
        }
        /* 多选已选标签文字 — 白色 */
        .stMultiSelect [data-baseweb="tag"] span {
            color: #FFFFFF !important;
        }
        /* 多选输入框内文字 — 白色 */
        .stMultiSelect [data-baseweb="input"] {
            color: #E2E8F0 !important;
        }

        /* ============================================================
           8. 分隔线
           ============================================================ */
        hr {
            border-color: rgba(255, 255, 255, 0.06);
            margin: 32px 0;
        }

        /* ============================================================
           9. 图表区域容器
           ============================================================ */
        [data-testid="stArrowVegaLiteChart"] {
            background: transparent;
        }

        /* ============================================================
           10. 选择框
           ============================================================ */
        .stSelectbox [data-baseweb="select"] > div {
            background: rgba(19, 22, 31, 0.9);
            border: 1px solid rgba(255, 255, 255, 0.1);
            border-radius: 6px;
        }

        /* ============================================================
           11. radio / pills
           ============================================================ */
        .stRadio [data-baseweb="radio"] label {
            color: #94A3B8 !important;
        }

        /* ============================================================
           12. 信息提示框
           ============================================================ */
        .stAlert {
            background: rgba(19, 22, 31, 0.7);
            border: 1px solid rgba(255, 255, 255, 0.05);
            border-radius: 6px;
        }
    </style>
    """, unsafe_allow_html=True)


inject_design_css()

# ============================================================
# 初始化数据库
# ============================================================

init_db()

# 启动定时调度器
scheduler = _init_scheduler()
next_run = scheduler.get_job("auto_crawl")
next_time = next_run.next_run_time.strftime("%H:%M") if next_run and next_run.next_run_time else "—"

# ============================================================
# 工具函数
# ============================================================

PLATFORM_DISPLAY = {
    "weibo": "微博热搜",
    "bilibili": "B站热门",
}
PLATFORM_SOURCES = {
    "weibo": "https://weibo.com/ajax/side/hotSearch",
    "bilibili": "https://api.bilibili.com/x/web-interface/popular",
}


def sentiment_label(score: float | None) -> str:
    """情感得分 → 可读标签。"""
    if score is None:
        return "—"
    if score >= 0.6:
        return "😊 正面"
    elif score <= 0.4:
        return "😡 负面"
    return "😐 中性"


def sentiment_short(score: float | None) -> str:
    """情感得分 → 单字标签。"""
    if score is None:
        return "—"
    if score >= 0.6:
        return "正面"
    elif score <= 0.4:
        return "负面"
    return "中性"


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
    if rank_val <= 3:
        return f"⬤ {rank_val}"
    elif rank_val <= 10:
        return f"○ {rank_val}"
    return str(rank_val)


def generate_verdict(topics: list[dict], platform_name: str) -> str:
    """根据数据生成编辑式 VERDICT 结论，design.md §5.2。"""
    if not topics:
        return "暂无数据，点击「立即抓取」获取最新热点。"
    count = len(topics)
    pos = sum(1 for t in topics if t.get("sentiment", 0.5) >= 0.6)
    neg = sum(1 for t in topics if t.get("sentiment", 0.5) <= 0.4)
    pos_pct = pos / count * 100
    neg_pct = neg / count * 100
    keywords_all = []
    for t in topics:
        kw = t.get("keywords", "")
        if kw:
            keywords_all.extend(kw.split(","))
    # 取出现最多的关键词
    from collections import Counter
    top_kw = [k for k, _ in Counter(keywords_all).most_common(5)] if keywords_all else ["综合"]

    if platform_name == "weibo":
        if pos_pct >= 55:
            return f"舆论环境偏积极。{', '.join(top_kw[:3])} 等话题集中，适合内容创作与话题跟进。"
        elif neg_pct >= 30:
            return f"负面情绪占比 {neg_pct:.0f}%，{', '.join(top_kw[:3])} 引发争议，建议谨慎选题。"
        else:
            return f"情绪分布均衡。{', '.join(top_kw[:3])} 交错上榜，话题空间多元化。"
    elif platform_name == "bilibili":
        avg_views = round(sum(t.get("hot_score", 0) for t in topics) / count) if count else 0
        if avg_views > 500000:
            return f"均播放 {avg_views/10000:.0f} 万，内容消费需求旺盛。{', '.join(top_kw[:3])} 领跑各区。"
        elif avg_views > 100000:
            return f"均播放 {avg_views/10000:.0f} 万，各区表现均衡，用户兴趣多元化。"
        else:
            return f"播放量平稳，{', '.join(top_kw[:3])} 话题有待发酵。"
    return "数据正常更新中。"


def kpi_section(topics: list[dict], platform_name: str) -> dict:
    """计算某个平台的 KPI 摘要。"""
    count = len(topics)
    pos = sum(1 for t in topics if t.get("sentiment", 0.5) >= 0.6)
    neg = sum(1 for t in topics if t.get("sentiment", 0.5) <= 0.4)
    neu = count - pos - neg
    avg_score = round(sum(t.get("hot_score", 0) for t in topics) / count, 1) if count else 0
    return {
        "count": count,
        "pos": pos,
        "neg": neg,
        "neu": neu,
        "avg_score": avg_score,
        "pos_pct": round(pos / count * 100) if count else 0,
    }


# ============================================================
# 主区域
# ============================================================

# --- 顶部控制栏 ---
top_left, top_right = st.columns([3, 1])
with top_left:
    st.title("🔥 社交媒体热点趋势")
with top_right:
    st.write("")  # 垂直对齐
    selected_platforms = st.multiselect(
        "选择平台",
        options=list(FETCHERS.keys()),
        format_func=lambda k: PLATFORM_DISPLAY[k],
        default=list(FETCHERS.keys()),
        label_visibility="collapsed",
    )

if not selected_platforms:
    st.info("请选择一个或多个平台查看数据")
    st.stop()

# 抓取按钮 + 状态行
ctrl_col1, ctrl_col2, ctrl_col3 = st.columns([1, 2, 1])
with ctrl_col1:
    if st.button("⚡ 立即抓取", use_container_width=True, type="primary"):
        with st.spinner("正在抓取数据…"):
            counts = crawl_and_save(selected_platforms)
        st.toast(
            f"已刷新：{' | '.join(f'{PLATFORM_DISPLAY[k]} {v}条' for k, v in counts.items())}",
            icon="✅",
        )
with ctrl_col3:
    st.caption(f"⏱ 下次自动: {next_time}")

st.divider()

# ============================================================
# Hero 区域 — 核心 KPI + VERDICT（design.md §5.2 叙事层）
# ============================================================

# 聚合所有平台数据
all_topics: dict[str, list[dict]] = {}
for p in selected_platforms:
    all_topics[p] = get_latest_topics(p)

# 计算聚合 KPI
total_count = sum(len(v) for v in all_topics.values())
total_pos = sum(
    sum(1 for t in v if t.get("sentiment", 0.5) >= 0.6) for v in all_topics.values()
)
total_neg = sum(
    sum(1 for t in v if t.get("sentiment", 0.5) <= 0.4) for v in all_topics.values()
)
overall_pos_pct = round(total_pos / total_count * 100) if total_count else 0

# Hero 标题行（Playfair 衬线体）
st.markdown("""
<h2 style="font-family: 'Playfair Display', serif; font-size: 28px; font-weight: 700;
           color: #E2E8F0; margin-bottom: 24px; letter-spacing: -0.01em;">
    今日热点概览
</h2>
""", unsafe_allow_html=True)

# KPI 大数字行
kpi_cols = st.columns(3)
with kpi_cols[0]:
    st.metric(
        label="热点总数",
        value=f"{total_count} 条",
    )
with kpi_cols[1]:
    st.metric(
        label="正面情绪占比",
        value=f"{overall_pos_pct}%",
        delta=f"😊 {total_pos} 条正面",
    )
with kpi_cols[2]:
    # 找一个有代表性的平均热度
    sample_scores = []
    for v in all_topics.values():
        for t in v:
            sample_scores.append(t.get("hot_score", 0))
    avg_hot = round(sum(sample_scores) / len(sample_scores)) if sample_scores else 0
    st.metric(
        label="平均热度值",
        value=f"{avg_hot:,.0f}",
    )

# VERDICT 结论标签（design.md §5.2）
verdict_texts = []
for p in selected_platforms:
    verdict_texts.append(f"**{PLATFORM_DISPLAY[p]}**：{generate_verdict(all_topics[p], p)}")

verdict_html = "<br>".join(verdict_texts)
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
    ">VERDICT</span>
    <span style="
        font-size: 14px;
        color: #94A3B8;
        line-height: 1.8;
    ">{verdict_html}</span>
</div>
""", unsafe_allow_html=True)

st.divider()

# ============================================================
# 图表区 — 情绪分布 + 热度趋势（design.md §5.1 图表行）
# ============================================================

st.markdown("""
<h3 style="font-family: 'Playfair Display', serif; font-size: 22px; font-weight: 600;
           color: #E2E8F0; margin-bottom: 16px;">
    数据洞察
</h3>
""", unsafe_allow_html=True)

chart_col1, chart_col2 = st.columns(2)

with chart_col1:
    # 情绪分布柱状图
    st.markdown("""
    <p style="font-size: 11px; color: #64748B; text-transform: uppercase;
              letter-spacing: 0.05em; margin-bottom: 8px;">
        情绪分布 · Sentiment
    </p>
    """, unsafe_allow_html=True)

    sentiment_data = []
    for p in selected_platforms:
        topics = all_topics[p]
        kpi = kpi_section(topics, p)
        sentiment_data.append({
            "平台": PLATFORM_DISPLAY[p],
            "😊 正面": kpi["pos"],
            "😐 中性": kpi["neu"],
            "😡 负面": kpi["neg"],
        })
    if sentiment_data:
        df_sentiment = pd.DataFrame(sentiment_data).set_index("平台")
        df_melt = df_sentiment.reset_index().melt(
            id_vars="平台", var_name="情绪", value_name="数量"
        )
        chart = (
            alt.Chart(df_melt)
            .mark_bar()
            .encode(
                x=alt.X("平台:N", title=None, axis=alt.Axis(labelAngle=0)),
                y=alt.Y("数量:Q", title=None),
                color=alt.Color(
                    "情绪:N",
                    scale=alt.Scale(
                        domain=["😊 正面", "😐 中性", "😡 负面"],
                        range=["#4ECDC4", "#94A3B8", "#E74C3C"],
                    ),
                    legend=alt.Legend(orient="bottom", title=None),
                ),
                xOffset="情绪:N",
            )
            .properties(height=300)
            .configure_axis(gridColor="rgba(255,255,255,0.04)", domainColor="rgba(255,255,255,0.1)")
            .configure_view(strokeWidth=0)
        )
        st.altair_chart(chart, use_container_width=True)
    else:
        st.info("暂无数据")

with chart_col2:
    # 热度趋势图
    st.markdown("""
    <p style="font-size: 11px; color: #64748B; text-transform: uppercase;
              letter-spacing: 0.05em; margin-bottom: 8px;">
        热度趋势 · Trend
    </p>
    """, unsafe_allow_html=True)

    trend_kw = st.text_input(
        "输入关键词查看趋势",
        placeholder="如: AI",
        label_visibility="collapsed",
        key="trend_keyword",
    )
    if trend_kw and selected_platforms:
        trend_data = get_trend(selected_platforms[0], trend_kw, hours=24)
        if trend_data:
            df_trend = pd.DataFrame(trend_data)
            df_trend["captured_at"] = pd.to_datetime(df_trend["captured_at"])
            st.line_chart(
                df_trend.set_index("captured_at")["hot_score"],
                use_container_width=True,
                color="#D4A056",
            )
        else:
            st.info("暂无该关键词的趋势数据")
    elif not trend_kw:
        st.info("👈 输入关键词查看热度变化")

st.divider()

# ============================================================
# 实时榜单表格（design.md §5.1 数据层）
# ============================================================

st.markdown("""
<h3 style="font-family: 'Playfair Display', serif; font-size: 22px; font-weight: 600;
           color: #E2E8F0; margin-bottom: 8px;">
    实时热点榜单
</h3>
""", unsafe_allow_html=True)

tabs = st.tabs([PLATFORM_DISPLAY[p] for p in selected_platforms])

for i, platform_name in enumerate(selected_platforms):
    with tabs[i]:
        topics = all_topics[platform_name]
        if not topics:
            st.warning("暂无数据，请点击「立即抓取」获取")
            continue

        df = pd.DataFrame(topics)
        capture_time = df["captured_at"].iloc[0] if "captured_at" in df.columns else "未知"
        source_url = PLATFORM_SOURCES.get(platform_name, "")

        # 数据溯源行
        st.caption(
            f"来源: [{PLATFORM_DISPLAY[platform_name]}]({source_url})"
            f" · 抓取: {capture_time}"
            f" · 共 {len(topics)} 条"
        )

        # 构建展示列
        display_cols = {
            "rank": "排名",
            "title": "标题",
            "hot_score": "热度",
            "keywords": "关键词",
            "url": "来源",
        }
        available_cols = [c for c in display_cols if c in df.columns]
        df_display = df[available_cols].rename(columns=display_cols).copy()

        # 舆情列
        df_display["舆情"] = df["sentiment"].apply(sentiment_label)

        # 发布时间 & 时效
        df_display["发布时间"] = df["raw_data"].apply(format_pubtime)
        df_display["时效"] = df["raw_data"].apply(
            lambda r: format_freshness(r, str(capture_time))
        )

        # 排名徽章
        if "排名" in df_display.columns:
            df_display["排名"] = df["rank"].apply(rank_badge)

        # 数字格式化
        if "热度" in df_display.columns:
            df_display["热度"] = df_display["热度"].apply(lambda x: f"{x:,.0f}")

        # column_config：来源列可点击
        col_cfg = {}
        if "来源" in df_display.columns:
            col_cfg["来源"] = st.column_config.LinkColumn(
                "来源", display_text="🔗 原文"
            )

        # 列顺序
        column_order = [c for c in [
            "排名", "标题", "热度", "舆情", "关键词", "发布时间", "时效", "来源"
        ] if c in df_display.columns]

        st.dataframe(
            df_display[column_order],
            column_config=col_cfg,
            use_container_width=True,
            hide_index=True,
            height=560,
        )

# ============================================================
# 页脚 — 数据溯源（design.md §4.1 卡片样式）
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
