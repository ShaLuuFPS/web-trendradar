-- ============================================================
-- Trend Radar · Supabase 数据库迁移
-- 请在 Supabase SQL Editor: https://supabase.com/dashboard
-- 中打开你的项目，粘贴整段并执行
-- ============================================================

-- 1. 基础表
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

-- 2. 索引
CREATE INDEX IF NOT EXISTS idx_pg_captured_at ON hot_topics(captured_at);
CREATE INDEX IF NOT EXISTS idx_pg_platform_id  ON hot_topics(platform_id);
CREATE INDEX IF NOT EXISTS idx_pg_topic_key    ON hot_topics(topic_key);
CREATE INDEX IF NOT EXISTS idx_pg_ta_topic_key ON topic_analysis(topic_key);
CREATE INDEX IF NOT EXISTS idx_pg_ta_captured  ON topic_analysis(captured_at);

-- 3. 平台种子数据
INSERT INTO platforms (name, display_name) VALUES
    ('weibo', '微博热搜'),
    ('zhihu', '知乎热榜'),
    ('bilibili', 'B站热门')
ON CONFLICT (name) DO NOTHING;

-- ============================================================
-- Row Level Security — 允许 anon 角色通过 REST API 读写
-- ============================================================

-- 启用 RLS
ALTER TABLE platforms ENABLE ROW LEVEL SECURITY;
ALTER TABLE hot_topics ENABLE ROW LEVEL SECURITY;
ALTER TABLE topic_analysis ENABLE ROW LEVEL SECURITY;
ALTER TABLE token_usage ENABLE ROW LEVEL SECURITY;

-- platforms: 公开可读，不允许 anon 写入（种子数据已写死）
CREATE POLICY "anon_read_platforms"  ON platforms      FOR SELECT TO anon USING (true);

-- hot_topics: 公开可读写
CREATE POLICY "anon_read_hot_topics"  ON hot_topics     FOR SELECT TO anon USING (true);
CREATE POLICY "anon_insert_hot_topics" ON hot_topics    FOR INSERT TO anon WITH CHECK (true);

-- topic_analysis: 公开可读写
CREATE POLICY "anon_read_ta"  ON topic_analysis  FOR SELECT TO anon USING (true);
CREATE POLICY "anon_insert_ta" ON topic_analysis FOR INSERT TO anon WITH CHECK (true);

-- token_usage: 公开可读写
CREATE POLICY "anon_read_usage"   ON token_usage FOR SELECT TO anon USING (true);
CREATE POLICY "anon_insert_usage" ON token_usage FOR INSERT TO anon WITH CHECK (true);

-- ============================================================
-- PostgreSQL RPC 函数（供 REST API 调用复杂查询）
-- ============================================================

-- 获取最新批次热点（含 AI 分析）
CREATE OR REPLACE FUNCTION get_latest_topics(
    platform_name TEXT,
    limit_val INT DEFAULT 50
) RETURNS TABLE(
    rank BIGINT,
    title TEXT,
    url TEXT,
    hot_score DOUBLE PRECISION,
    raw_data JSONB,
    sentiment DOUBLE PRECISION,
    keywords TEXT,
    captured_at TIMESTAMPTZ,
    topic_key TEXT,
    ai_label TEXT,
    ai_verdict TEXT,
    ai_sentiment TEXT
) LANGUAGE plpgsql AS $$
DECLARE
    latest_ts TIMESTAMPTZ;
    pid INT;
BEGIN
    SELECT id INTO pid FROM platforms WHERE platforms.name = platform_name;
    IF pid IS NULL THEN RETURN; END IF;

    SELECT MAX(h.captured_at) INTO latest_ts
    FROM hot_topics h WHERE h.platform_id = pid;

    IF latest_ts IS NULL THEN RETURN; END IF;

    RETURN QUERY
    SELECT
        MIN(h.rank)::BIGINT,
        h.title,
        h.url,
        MAX(h.hot_score),
        h.raw_data,
        h.sentiment,
        h.keywords,
        h.captured_at,
        h.topic_key,
        ta.label,
        ta.verdict_short,
        ta.sentiment
    FROM hot_topics h
    LEFT JOIN topic_analysis ta
        ON h.topic_key = ta.topic_key
        AND ta.captured_at = (
            SELECT MAX(ta2.captured_at) FROM topic_analysis ta2
            WHERE ta2.topic_key = h.topic_key
              AND ta2.captured_at <= h.captured_at
        )
    WHERE h.platform_id = pid AND h.captured_at = latest_ts
    GROUP BY h.topic_key, h.title, h.url, h.raw_data, h.sentiment, h.keywords,
             h.captured_at, ta.label, ta.verdict_short, ta.sentiment
    ORDER BY MIN(h.rank)
    LIMIT limit_val;
END;
$$;

-- 排名趋势数据
CREATE OR REPLACE FUNCTION get_ranking_trend(
    platform_name TEXT,
    since_val TIMESTAMPTZ,
    top_n_val INT DEFAULT 5
) RETURNS TABLE(
    topic_key TEXT,
    title TEXT,
    data_points JSONB
) LANGUAGE plpgsql AS $$
DECLARE
    pid INT;
BEGIN
    SELECT id INTO pid FROM platforms WHERE platforms.name = platform_name;
    IF pid IS NULL THEN RETURN; END IF;

    RETURN QUERY
    WITH top_keys AS (
        SELECT h.topic_key, MIN(h.title) AS t, MIN(h.rank) AS r
        FROM hot_topics h
        WHERE h.platform_id = pid AND h.captured_at >= since_val
        GROUP BY h.topic_key
        ORDER BY MIN(h.rank)
        LIMIT top_n_val
    ),
    points AS (
        SELECT
            h2.topic_key,
            jsonb_agg(
                jsonb_build_object(
                    'captured_at', to_char(h2.captured_at, 'YYYY-MM-DD HH24:MI:SS'),
                    'rank', h2.rank,
                    'hot_score', h2.hot_score
                ) ORDER BY h2.captured_at, h2.rank
            ) AS dps
        FROM hot_topics h2
        JOIN top_keys tk ON h2.topic_key = tk.topic_key
        WHERE h2.platform_id = pid AND h2.captured_at >= since_val
        GROUP BY h2.topic_key
    )
    SELECT tk.topic_key, tk.t, COALESCE(p.dps, '[]'::JSONB)
    FROM top_keys tk
    LEFT JOIN points p ON tk.topic_key = p.topic_key
    ORDER BY tk.r;
END;
$$;

-- 7 天高频热点趋势
CREATE OR REPLACE FUNCTION get_weekly_trend_events(
    platform_name TEXT,
    top_n_val INT DEFAULT 8
) RETURNS TABLE(
    topic_key TEXT,
    title TEXT,
    data_points JSONB
) LANGUAGE plpgsql AS $$
DECLARE
    pid INT;
    since_ts TIMESTAMPTZ;
BEGIN
    SELECT id INTO pid FROM platforms WHERE platforms.name = platform_name;
    IF pid IS NULL THEN RETURN; END IF;
    since_ts := NOW() - INTERVAL '7 days';

    RETURN QUERY
    WITH top_keys AS (
        SELECT h.topic_key, COUNT(*) AS cnt, MIN(h.title) AS t
        FROM hot_topics h
        WHERE h.platform_id = pid AND h.captured_at >= since_ts
        GROUP BY h.topic_key
        ORDER BY cnt DESC
        LIMIT top_n_val
    ),
    points AS (
        SELECT
            h2.topic_key,
            jsonb_agg(
                jsonb_build_object(
                    'captured_at', to_char(h2.captured_at, 'YYYY-MM-DD HH24:MI:SS'),
                    'rank', h2.rank,
                    'hot_score', h2.hot_score
                ) ORDER BY h2.captured_at, h2.rank
            ) AS dps
        FROM hot_topics h2
        JOIN top_keys tk ON h2.topic_key = tk.topic_key
        WHERE h2.platform_id = pid AND h2.captured_at >= since_ts
        GROUP BY h2.topic_key
    )
    SELECT tk.topic_key, tk.t, COALESCE(p.dps, '[]'::JSONB)
    FROM top_keys tk
    LEFT JOIN points p ON tk.topic_key = p.topic_key
    ORDER BY tk.cnt DESC;
END;
$$;

-- 7 天热点列表
CREATE OR REPLACE FUNCTION get_weekly_topics(
    platform_name TEXT,
    limit_val INT DEFAULT 50
) RETURNS TABLE(
    rank BIGINT,
    title TEXT,
    url TEXT,
    hot_score DOUBLE PRECISION,
    raw_data JSONB,
    sentiment DOUBLE PRECISION,
    keywords TEXT,
    captured_at TIMESTAMPTZ,
    topic_key TEXT,
    ai_label TEXT,
    ai_verdict TEXT,
    ai_sentiment TEXT
) LANGUAGE plpgsql AS $$
DECLARE
    pid INT;
    since_ts TIMESTAMPTZ;
BEGIN
    SELECT id INTO pid FROM platforms WHERE platforms.name = platform_name;
    IF pid IS NULL THEN RETURN; END IF;
    since_ts := NOW() - INTERVAL '7 days';

    RETURN QUERY
    SELECT
        agg.min_rank::BIGINT,
        latest.title,
        latest.url,
        latest.hot_score,
        latest.raw_data,
        latest.sentiment,
        latest.keywords,
        latest.captured_at,
        agg.topic_key,
        ta.label,
        ta.verdict_short,
        ta.sentiment
    FROM (
        SELECT
            h.topic_key,
            MIN(h.rank) AS min_rank,
            MAX(h.captured_at) AS latest_captured
        FROM hot_topics h
        WHERE h.platform_id = pid AND h.captured_at >= since_ts
        GROUP BY h.topic_key
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
    LIMIT limit_val;
END;
$$;

-- 情绪分布
CREATE OR REPLACE FUNCTION get_sentiment_distribution(
    platform_name TEXT,
    since_val TIMESTAMPTZ
) RETURNS TABLE(
    positive BIGINT,
    neutral BIGINT,
    negative BIGINT,
    total BIGINT,
    positive_pct DOUBLE PRECISION
) LANGUAGE plpgsql AS $$
DECLARE
    pos BIGINT := 0;
    neu BIGINT := 0;
    neg BIGINT := 0;
    tot BIGINT := 0;
    pid INT;
BEGIN
    SELECT id INTO pid FROM platforms WHERE platforms.name = platform_name;
    IF pid IS NULL THEN
        RETURN QUERY SELECT 0::BIGINT, 0::BIGINT, 0::BIGINT, 0::BIGINT, 0.0;
        RETURN;
    END IF;

    SELECT
        COALESCE(COUNT(*) FILTER (WHERE sl = 'positive'), 0),
        COALESCE(COUNT(*) FILTER (WHERE sl = 'neutral'), 0),
        COALESCE(COUNT(*) FILTER (WHERE sl = 'negative'), 0)
    INTO pos, neu, neg
    FROM (
        SELECT
            COALESCE(ta.sentiment,
                CASE WHEN h.sentiment >= 0.6 THEN 'positive'
                     WHEN h.sentiment <= 0.4 THEN 'negative'
                     ELSE 'neutral' END
            ) AS sl
        FROM hot_topics h
        LEFT JOIN topic_analysis ta
            ON h.topic_key = ta.topic_key
            AND ta.captured_at = (
                SELECT MAX(ta2.captured_at) FROM topic_analysis ta2
                WHERE ta2.topic_key = h.topic_key
                  AND ta2.captured_at <= h.captured_at
            )
        WHERE h.platform_id = pid
          AND h.captured_at >= since_val
          AND h.captured_at = (
              SELECT MAX(h2.captured_at) FROM hot_topics h2
              WHERE h2.topic_key = h.topic_key
                AND h2.captured_at >= since_val
          )
    ) sub;

    tot := pos + neu + neg;
    RETURN QUERY SELECT
        pos, neu, neg, tot,
        CASE WHEN tot > 0 THEN ROUND(pos::DOUBLE PRECISION / tot * 100, 1) ELSE 0.0 END;
END;
$$;

-- 未分析的热点
CREATE OR REPLACE FUNCTION get_unanalyzed_keys(
    platform_name TEXT
) RETURNS TABLE(
    topic_key TEXT,
    title TEXT,
    captured_at TIMESTAMPTZ
) LANGUAGE plpgsql AS $$
DECLARE
    pid INT;
BEGIN
    SELECT id INTO pid FROM platforms WHERE platforms.name = platform_name;
    IF pid IS NULL THEN RETURN; END IF;

    RETURN QUERY
    SELECT h.topic_key, MIN(h.title) AS t, MIN(h.captured_at) AS ca
    FROM hot_topics h
    WHERE h.platform_id = pid
      AND h.captured_at = (
          SELECT MAX(h2.captured_at) FROM hot_topics h2
          WHERE h2.platform_id = pid
      )
      AND h.topic_key NOT IN (
          SELECT ta.topic_key FROM topic_analysis ta
          WHERE ta.topic_key = h.topic_key
      )
    GROUP BY h.topic_key
    ORDER BY MIN(h.rank);
END;
$$;

-- 批量查询 AI 分析
CREATE OR REPLACE FUNCTION get_analysis_batch(
    topic_keys TEXT[]
) RETURNS TABLE(
    topic_key TEXT,
    sentiment TEXT,
    label TEXT,
    verdict_short TEXT
) LANGUAGE plpgsql AS $$
BEGIN
    RETURN QUERY
    SELECT ta.topic_key, ta.sentiment, ta.label, ta.verdict_short
    FROM topic_analysis ta
    INNER JOIN (
        SELECT topic_key, MAX(captured_at) AS max_cap
        FROM topic_analysis
        WHERE topic_key = ANY(topic_keys)
        GROUP BY topic_key
    ) latest ON ta.topic_key = latest.topic_key AND ta.captured_at = latest.max_cap;
END;
$$;

-- Token 统计
CREATE OR REPLACE FUNCTION get_token_stats()
RETURNS JSONB LANGUAGE plpgsql AS $$
DECLARE
    today_start TIMESTAMPTZ := DATE_TRUNC('day', NOW());
    month_start TIMESTAMPTZ := DATE_TRUNC('month', NOW());
    today_prompt BIGINT;
    today_comp BIGINT;
    today_cost DOUBLE PRECISION;
    today_calls BIGINT;
    month_prompt BIGINT;
    month_comp BIGINT;
    month_cost DOUBLE PRECISION;
    month_calls BIGINT;
    last_rec JSONB;
BEGIN
    SELECT COALESCE(SUM(prompt_tokens), 0), COALESCE(SUM(completion_tokens), 0),
           COALESCE(SUM(cost_estimated), 0), COUNT(*)
    INTO today_prompt, today_comp, today_cost, today_calls
    FROM token_usage WHERE timestamp >= today_start;

    SELECT COALESCE(SUM(prompt_tokens), 0), COALESCE(SUM(completion_tokens), 0),
           COALESCE(SUM(cost_estimated), 0), COUNT(*)
    INTO month_prompt, month_comp, month_cost, month_calls
    FROM token_usage WHERE timestamp >= month_start;

    SELECT row_to_json(t) INTO last_rec
    FROM (SELECT timestamp, model, prompt_tokens, completion_tokens, batch_count, cost_estimated
          FROM token_usage ORDER BY id DESC LIMIT 1) t;

    RETURN jsonb_build_object(
        'today', jsonb_build_object(
            'prompt_tokens', today_prompt,
            'completion_tokens', today_comp,
            'total_tokens', today_prompt + today_comp,
            'cost', ROUND(today_cost::numeric, 6),
            'calls', today_calls
        ),
        'month', jsonb_build_object(
            'prompt_tokens', month_prompt,
            'completion_tokens', month_comp,
            'total_tokens', month_prompt + month_comp,
            'cost', ROUND(month_cost::numeric, 6),
            'calls', month_calls
        ),
        'last_call', last_rec
    );
END;
$$;

-- 启用 REST API 访问这些函数
GRANT EXECUTE ON FUNCTION get_latest_topics TO anon, authenticated, service_role;
GRANT EXECUTE ON FUNCTION get_ranking_trend TO anon, authenticated, service_role;
GRANT EXECUTE ON FUNCTION get_weekly_trend_events TO anon, authenticated, service_role;
GRANT EXECUTE ON FUNCTION get_weekly_topics TO anon, authenticated, service_role;
GRANT EXECUTE ON FUNCTION get_sentiment_distribution TO anon, authenticated, service_role;
GRANT EXECUTE ON FUNCTION get_unanalyzed_keys TO anon, authenticated, service_role;
GRANT EXECUTE ON FUNCTION get_token_stats TO anon, authenticated, service_role;
GRANT EXECUTE ON FUNCTION get_analysis_batch TO anon, authenticated, service_role;
