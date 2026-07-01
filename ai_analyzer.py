"""
AI 舆情分析模块 — DeepSeek Flash 批量分析热点标题。
提供情感标签、一句话简评，支持去重缓存和 Token 追踪。
"""

import json as _json
import os
import re
from datetime import datetime

from openai import OpenAI

from db import (
    get_unanalyzed_keys,
    insert_analysis,
    record_token_usage,
)

# ============================================================
# 配置
# ============================================================

DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")
DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEEPSEEK_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")
BATCH_SIZE = 10

# 价格估算（USD / 1M tokens）
# DeepSeek-V3: input $0.27, output $1.10
COST_PER_1M_INPUT = 0.27
COST_PER_1M_OUTPUT = 1.10

# ============================================================
# Prompt 模板
# ============================================================

SYSTEM_PROMPT = """你是一个中文社交媒体舆情分析专家。分析给定的热搜/热门标题列表，对每条输出：

- sentiment: "positive" / "neutral" / "negative"
- label: 具体情绪标签（如 期待、愤怒、调侃、担忧、感动、争议、八卦、自豪、震惊、好奇、无奈、讽刺）
- verdict_short: 一句话简评（≤20字），点出舆论倾向

严格按照 JSON 数组格式输出，不要多余文字。
示例输出：
[
  {"title": "XXX发布新产品", "sentiment": "positive", "label": "期待", "verdict_short": "用户对新品反响热烈，期待值高"},
  {"title": "YYY事件引发争议", "sentiment": "negative", "label": "愤怒", "verdict_short": "舆论一边倒批评，情绪激烈"}
]"""


def _build_user_prompt(titles: list[str]) -> str:
    """构建用户消息：编号标题列表。"""
    items = "\n".join(f"{i+1}. {t}" for i, t in enumerate(titles))
    return f"分析以下 {len(titles)} 条热点标题：\n{items}"


# ============================================================
# 核心分析函数
# ============================================================


def analyze_batch(titles: list[str]) -> list[dict]:
    """对一批标题调用 DeepSeek API，返回分析结果列表。

    返回: [{title, sentiment, label, verdict_short}]
    """
    if not DEEPSEEK_API_KEY:
        print("[ai_analyzer] 未设置 DEEPSEEK_API_KEY，跳过 AI 分析")
        return []

    if not titles:
        return []

    client = OpenAI(
        api_key=DEEPSEEK_API_KEY,
        base_url=DEEPSEEK_BASE_URL,
    )

    user_prompt = _build_user_prompt(titles)

    try:
        response = client.chat.completions.create(
            model=DEEPSEEK_MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.3,
            max_tokens=1024,
        )
    except Exception as e:
        print(f"[ai_analyzer] API 调用失败: {e}")
        return []

    # Token 用量
    usage = response.usage
    prompt_tokens = usage.prompt_tokens if usage else 0
    completion_tokens = usage.completion_tokens if usage else 0

    # 保存 token 记录
    _record(prompt_tokens, completion_tokens, len(titles))

    # 解析 JSON 响应
    content = response.choices[0].message.content.strip() if response.choices else ""

    # 清理可能的 markdown 代码块包裹
    content = re.sub(r"^```(?:json)?\s*", "", content)
    content = re.sub(r"\s*```$", "", content)

    try:
        results = _json.loads(content)
    except _json.JSONDecodeError:
        print(f"[ai_analyzer] JSON 解析失败，原始响应: {content[:200]}")
        return []

    if not isinstance(results, list):
        return []

    return results


def _record(prompt_tokens: int, completion_tokens: int, batch_count: int) -> None:
    """记录 token 消耗到 DB + JSONL。"""
    cost = (prompt_tokens / 1_000_000) * COST_PER_1M_INPUT + \
           (completion_tokens / 1_000_000) * COST_PER_1M_OUTPUT

    try:
        record_token_usage(
            model=DEEPSEEK_MODEL,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            batch_count=batch_count,
            cost_estimated=cost,
        )
    except Exception as e:
        print(f"[ai_analyzer] token 记录失败: {e}")

    print(
        f"[ai_analyzer] tokens: {prompt_tokens} in + {completion_tokens} out"
        f" = {prompt_tokens + completion_tokens} total"
        f" (${cost:.6f})"
    )


# ============================================================
# 批量分析调度
# ============================================================


def run_analysis(platform_name: str) -> int:
    """对指定平台最新抓取中未分析的热点运行 AI 分析。

    返回: 分析成功的条数。
    """
    if not DEEPSEEK_API_KEY:
        print("[ai_analyzer] 未设置 DEEPSEEK_API_KEY，跳过 AI 分析")
        return 0

    # 查未分析的热点
    unanalyzed = get_unanalyzed_keys(platform_name)
    if not unanalyzed:
        print(f"[ai_analyzer] {platform_name}: 所有热点已分析，跳过")
        return 0

    # 获取批次统一的 captured_at（所有未分析热点来自同一批次）
    batch_captured_at = unanalyzed[0].get("captured_at", "")
    if not batch_captured_at:
        batch_captured_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    print(f"[ai_analyzer] {platform_name}: {len(unanalyzed)} 条未分析，开始批量分析...")

    total_analyzed = 0

    # 分批
    for i in range(0, len(unanalyzed), BATCH_SIZE):
        batch = unanalyzed[i : i + BATCH_SIZE]
        titles = [item["title"] for item in batch]
        ai_results = analyze_batch(titles)

        if not ai_results:
            continue

        # 匹配结果回 topic_key
        # 用 title 精确匹配（同一批次内 title 唯一）
        title_to_key = {item["title"]: item["topic_key"] for item in batch}

        rows = []
        for r in ai_results:
            tk = title_to_key.get(r.get("title", ""))
            if not tk:
                continue
            rows.append({
                "topic_key": tk,
                "captured_at": batch_captured_at,
                "sentiment": r.get("sentiment", "neutral"),
                "label": r.get("label", ""),
                "verdict_short": r.get("verdict_short", ""),
                "model": DEEPSEEK_MODEL,
                "tokens_used": 0,
            })

        if rows:
            written = insert_analysis(rows)
            total_analyzed += written
            print(f"[ai_analyzer] 批次 {i // BATCH_SIZE + 1}: {written} 条写入")

    print(f"[ai_analyzer] {platform_name}: 完成，共分析 {total_analyzed} 条")
    return total_analyzed


def run_analysis_all(platforms: list[str] | None = None) -> dict[str, int]:
    """对多个平台运行 AI 分析。

    返回: {platform_name: analyzed_count}
    """
    from spider import FETCHERS
    if platforms is None:
        platforms = list(FETCHERS.keys())

    results = {}
    for p in platforms:
        try:
            results[p] = run_analysis(p)
        except Exception as e:
            print(f"[ai_analyzer] {p} 分析失败: {e}")
            results[p] = 0
    return results
