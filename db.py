"""
数据库模块 — 自动选择后端:
  1. SUPABASE_URL 存在 → REST API（HTTPS，中国网络可用）
  2. DATABASE_URL 存在 → 直连 PostgreSQL（GitHub Actions）
  3. 否则 → 本地 SQLite
上层代码无需修改。
"""

import os
from dotenv import load_dotenv

load_dotenv()

if os.getenv("SUPABASE_URL"):
    from db_rest import *  # noqa: F401, F403, E402
elif os.getenv("DATABASE_URL"):
    from db_pg import *  # noqa: F401, F403, E402
else:
    from db_sqlite import *  # noqa: F401, F403, E402
