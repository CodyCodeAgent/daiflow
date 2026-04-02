#!/usr/bin/env bash
#
# deploy.sh — DaiFlow 部署管理脚本
#
# 用法：
#   ./deploy.sh start              # 后台启动
#   ./deploy.sh stop               # 停止
#   ./deploy.sh restart             # 重启
#   ./deploy.sh update              # pull 代码 + 重建 + 重启
#   ./deploy.sh status              # 查看运行状态
#   ./deploy.sh logs                # 查看日志（tail -f）
#   ./deploy.sh start --port 9000   # 指定端口

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

PID_FILE=".daiflow.pid"
LOG_FILE="daiflow.log"
DEFAULT_PORT=8000

# ── 工具函数 ──

get_pid() {
  [ -f "$PID_FILE" ] && cat "$PID_FILE" || echo ""
}

is_running() {
  local pid
  pid=$(get_pid)
  [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null && \
    ps -p "$pid" -o comm= 2>/dev/null | grep -qi "daiflow\|uvicorn\|python"
}

activate_venv() {
  if [ -d .venv ]; then
    # shellcheck source=/dev/null
    source .venv/bin/activate
  else
    echo "错误: .venv 不存在，请先运行 ./start.sh --setup"
    exit 1
  fi
}

# ── 命令实现 ──

do_start() {
  if is_running; then
    echo "DaiFlow 已在运行 (PID: $(get_pid))"
    exit 1
  fi

  local port=$DEFAULT_PORT
  while [ $# -gt 0 ]; do
    case "$1" in
      --port) port="$2"; shift 2 ;;
      *) shift ;;
    esac
  done

  activate_venv

  echo "==> 启动 DaiFlow (http://127.0.0.1:${port})"
  nohup daiflow start --host 0.0.0.0 --port "$port" --no-browser > "$LOG_FILE" 2>&1 &
  echo $! > "$PID_FILE"

  # 等待确认进程启动
  sleep 1
  if is_running; then
    echo "启动成功 (PID: $(get_pid))，日志: $LOG_FILE"
  else
    echo "启动失败，查看日志: cat $LOG_FILE"
    rm -f "$PID_FILE"
    exit 1
  fi
}

do_stop() {
  if ! is_running; then
    echo "DaiFlow 未在运行"
    rm -f "$PID_FILE"
    return 0
  fi

  local pid
  pid=$(get_pid)
  echo "==> 停止 DaiFlow (PID: $pid)"
  kill "$pid"

  # 等待进程退出，最多 10 秒
  local waited=0
  while kill -0 "$pid" 2>/dev/null && [ $waited -lt 10 ]; do
    sleep 1
    waited=$((waited + 1))
  done

  if kill -0 "$pid" 2>/dev/null; then
    echo "进程未响应，强制终止"
    kill -9 "$pid" 2>/dev/null || true
  fi

  rm -f "$PID_FILE"
  echo "已停止"
}

do_restart() {
  do_stop
  do_start "$@"
}

do_update() {
  echo "==> 丢弃本地修改"
  git checkout .

  echo "==> 拉取最新代码"
  git pull

  activate_venv

  echo "==> 安装后端依赖"
  pip install -r requirements.txt -q
  pip install -e . -q

  echo "==> 数据库迁移"
  alembic upgrade head

  echo "==> 构建前端"
  (cd frontend && npm install --silent && npm run build)

  echo "==> 重启服务"
  do_restart "$@"
}

do_status() {
  if is_running; then
    local pid
    pid=$(get_pid)
    echo "DaiFlow 运行中 (PID: $pid)"
    ps -p "$pid" -o pid,etime,rss,command 2>/dev/null | head -2
  else
    echo "DaiFlow 未在运行"
    rm -f "$PID_FILE"
  fi
}

do_logs() {
  if [ -f "$LOG_FILE" ]; then
    tail -f "$LOG_FILE"
  else
    echo "日志文件不存在: $LOG_FILE"
  fi
}

# ── 入口 ──

CMD="${1:-}"
shift || true

case "$CMD" in
  start)   do_start "$@" ;;
  stop)    do_stop ;;
  restart) do_restart "$@" ;;
  update)  do_update "$@" ;;
  status)  do_status ;;
  logs)    do_logs ;;
  *)
    echo "用法: $0 {start|stop|restart|update|status|logs} [--port PORT]"
    echo ""
    echo "  start    后台启动服务"
    echo "  stop     停止服务"
    echo "  restart  重启服务"
    echo "  update   git pull + 重建 + 重启"
    echo "  status   查看运行状态"
    echo "  logs     实时查看日志"
    exit 1
    ;;
esac
