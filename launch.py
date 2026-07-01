"""
启动器 — 同时启动 Streamlit 和 Cloudflare Tunnel，自动获取公网地址。
用法: uv run python launch.py
"""

import subprocess as _sp
import sys as _sys
import time as _time
import re as _re
import os as _os
import signal as _signal

# 修复中文 Windows GBK 终端下 emoji 输出报错
_sys.stdout.reconfigure(encoding="utf-8", errors="replace")

STREAMLIT_PORT = 3000
STREAMLIT_CMD = [
    _sys.executable, "-m", "streamlit", "run", "main.py",
    "--server.port", str(STREAMLIT_PORT),
    "--server.headless", "true",
]
CLOUDFLARED_CMD = [
    "cloudflared", "tunnel",
    "--url", f"http://localhost:{STREAMLIT_PORT}",
    "--no-autoupdate",
]

TUNNEL_URL_PATTERN = _re.compile(r"https://[a-zA-Z0-9-]+\.trycloudflare\.com")


def _find_cloudflared() -> str | None:
    """查找 cloudflared 可执行文件。"""
    import shutil as _shutil
    path = _shutil.which("cloudflared")
    if path:
        return path
    # Windows 常见路径
    for p in [
        r"C:\Users\Administrator\bin\cloudflared.exe",
        r"C:\Program Files\cloudflared\cloudflared.exe",
    ]:
        if _os.path.exists(p):
            return p
    return None


def main() -> None:
    # 检查 cloudflared
    cf_path = _find_cloudflared()
    if not cf_path:
        print("❌ 未找到 cloudflared，请先安装：")
        print("   winget install Cloudflare.cloudflared")
        print("   或下载: https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/")
        _sys.exit(1)

    CLOUDFLARED_CMD[0] = cf_path

    print("=" * 60)
    print("  🔥 热点趋势看板 · 启动中")
    print("=" * 60)
    print()

    # 启动 cloudflared tunnel
    print("⏳ 正在建立 Cloudflare Tunnel …")
    cf_proc = _sp.Popen(
        CLOUDFLARED_CMD,
        stdout=_sp.PIPE,
        stderr=_sp.STDOUT,
        text=True,
        encoding="utf-8",
        bufsize=1,
    )

    # 等待并解析 tunnel URL（拿到地址就立即继续）
    tunnel_url = None
    deadline = _time.time() + 30  # 最多等 30 秒
    try:
        for line in cf_proc.stdout:
            print(f"   [cloudflared] {line.rstrip()}")
            match = TUNNEL_URL_PATTERN.search(line)
            if match:
                tunnel_url = match.group(0)
                break  # 拿到地址立刻启动 Streamlit
            if _time.time() > deadline:
                break
    except Exception:
        pass

    if not tunnel_url:
        print("⚠️  未能获取 Cloudflare Tunnel URL，将仅启动本地服务")
    else:
        print()
        print(f"🌐 公网地址: {tunnel_url}")
        print()

    # 启动 Streamlit
    print("⏳ 正在启动 Streamlit …")
    st_proc = _sp.Popen(
        STREAMLIT_CMD,
        stdout=_sp.PIPE,
        stderr=_sp.STDOUT,
        text=True,
        encoding="utf-8",
        bufsize=1,
    )

    print()
    print("=" * 60)
    print("  ✅ 启动完成")
    print(f"  本地访问: http://localhost:{STREAMLIT_PORT}")
    if tunnel_url:
        print(f"  公网访问: {tunnel_url}")
    print("=" * 60)
    print()
    print("按 Ctrl+C 停止所有服务")

    # 等待子进程
    try:
        # Streamlit 前台输出
        for line in st_proc.stdout:
            print(line.rstrip())
    except KeyboardInterrupt:
        print("\n⏹ 正在关闭…")
    finally:
        for proc, name in [(cf_proc, "Cloudflare Tunnel"), (st_proc, "Streamlit")]:
            try:
                proc.terminate()
                proc.wait(timeout=5)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
        print("已停止所有服务")


if __name__ == "__main__":
    main()
