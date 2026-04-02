#!/usr/bin/env bash
#
# stop.sh — 关闭 DaiFlow 服务（优雅终止监听端口的 uvicorn 进程）
#
# 用法：
#   ./stop.sh           # 关闭默认端口 8000 上的服务
#   ./stop.sh 9000      # 关闭指定端口上的服务
#   DAIFLOW_PORT=9000 ./stop.sh
#
# 流程：SIGTERM 优雅关闭（5 秒超时），超时后 SIGKILL 兜底（参考 README 桌面端关闭逻辑）

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

PORT="${1:-${DAIFLOW_PORT:-8000}}"
TIMEOUT=5

# 根据端口查找监听进程（兼容 macOS / Linux）
find_pids() {
    if command -v lsof &>/dev/null; then
        lsof -ti ":$PORT" 2>/dev/null || true
    elif command -v ss &>/dev/null; then
        # Linux: ss 取监听端口的 inode，再从 /proc/*/fd 反查 pid（此处简化为依赖 lsof）
        true
    fi
}

PIDS=$(find_pids)
if [ -z "$PIDS" ]; then
    echo "端口 $PORT 上无运行中的 DaiFlow 进程。"
    exit 0
fi

echo "正在关闭端口 $PORT 上的 DaiFlow 进程: $PIDS"
for pid in $PIDS; do
    kill -TERM "$pid" 2>/dev/null || true
done

# 等待最多 TIMEOUT 秒
elapsed=0
while [ $elapsed -lt "$TIMEOUT" ]; do
    remaining=$(find_pids)
    if [ -z "$remaining" ]; then
        echo "已优雅关闭。"
        exit 0
    fi
    sleep 1
    elapsed=$((elapsed + 1))
done

# 超时则强制结束
remaining=$(find_pids)
if [ -n "$remaining" ]; then
    echo "超时 ${TIMEOUT}s，强制结束: $remaining"
    for pid in $remaining; do
        kill -KILL "$pid" 2>/dev/null || true
    done
fi
echo "已关闭。"
