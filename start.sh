#!/usr/bin/env bash
#
# start.sh — 启动 DaiFlow 服务（参考 README 安装 & 启动流程）
#
# 用法：
#   ./start.sh              # 使用默认端口 8000，自动打开浏览器
#   ./start.sh --no-browser # 不自动打开浏览器
#   ./start.sh --port 9000  # 指定端口
#   ./start.sh --setup      # 首次/完整安装后再启动（venv + pip + 前端构建）
#
# 要求：Python >= 3.11, Node.js >= 18

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

# 默认端口（与 daiflow start 一致）
PORT=8000
EXTRA_ARGS=""
DO_SETUP=false

while [ $# -gt 0 ]; do
    case "$1" in
        --port)
            PORT="$2"
            shift 2
            ;;
        --no-browser)
            EXTRA_ARGS="--no-browser"
            shift
            ;;
        --setup)
            DO_SETUP=true
            shift
            ;;
        *)
            echo "未知选项: $1"
            echo "用法: $0 [--port PORT] [--no-browser] [--setup]"
            exit 1
            ;;
    esac
done

if [ "$DO_SETUP" = true ]; then
    echo "==> 创建/激活虚拟环境"
    [ ! -d .venv ] && python3 -m venv .venv
    # shellcheck source=/dev/null
    source .venv/bin/activate

    echo "==> 安装后端依赖"
    pip install -r requirements.txt
    pip install -e .

    echo "==> 构建前端"
    (cd frontend && npm install && npm run build)
fi

# 若存在 .venv 则激活，保证 daiflow 可用
if [ -d .venv ]; then
    # shellcheck source=/dev/null
    source .venv/bin/activate
fi

echo "==> 启动 DaiFlow (http://127.0.0.1:${PORT})"
exec daiflow start --port "$PORT" $EXTRA_ARGS
