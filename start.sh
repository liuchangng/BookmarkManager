#!/usr/bin/env bash
# ============================================
#  🔖 收藏夹管理工具 — 一键启动 (Linux / macOS)
#  自动 uv sync → 启动 webapp → 打开浏览器
# ============================================
set -euo pipefail
cd "$(dirname "$0")"

# 读取 Web 端口（config.yaml → web 段 port，默认 8989）
# 注意: config 里代理段也有 port(7890)，awk 限定在 web: 之后匹配
PORT="$(awk '/^web:/{f=1;next} f&&/^[[:space:]]*port:/{print $2;exit}' config.yaml 2>/dev/null || true)"
PORT="${PORT:-8989}"
URL="http://127.0.0.1:${PORT}"

echo ""
echo "  =========================================="
echo "   收藏夹管理工具 — 一键启动"
echo "  =========================================="
echo ""

# 服务已在运行？直接开浏览器
CODE="$(curl -s -o /dev/null -w '%{http_code}' --max-time 2 "${URL}/" || true)"
if [ "$CODE" = "200" ]; then
    echo "  [OK] 服务已在运行: ${URL}"
    (python3 -m webbrowser "${URL}" 2>/dev/null) || (open "${URL}" 2>/dev/null) || (xdg-open "${URL}" 2>/dev/null) || true
    exit 0
fi

# 检查 uv
if ! command -v uv >/dev/null 2>&1; then
    echo "  [X] 未找到 uv，请先安装: https://docs.astral.sh/uv/"
    echo "      安装命令: curl -LsSf https://astral.sh/uv/install.sh | sh"
    exit 1
fi

# 同步依赖
echo "  [..] 同步依赖 (uv sync) ..."
uv sync

# 启动服务
# webapp.py 启动后会按 config 的 web.auto_open_browser 自动打开浏览器
echo "  [OK] 正在启动: ${URL}"
exec uv run python webapp.py
