#!/bin/bash
# gov-price-auto-mine 后台启动脚本（非阻塞）
# 用法: bash run.sh [city] [--headless]
# 示例: bash run.sh rizhao
#       bash run.sh all --headless

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PYTHON="$(which python3 2>/dev/null || which python 2>/dev/null)"
LOGFILE="$SCRIPT_DIR/logs/auto-mine-$(date +%Y%m%d-%H%M%S).log"

mkdir -p "$SCRIPT_DIR/logs"

CITY="${1:-rizhao}"
HEADLESS_FLAG=""
if [[ "$*" == *"--headless"* ]]; then
    HEADLESS_FLAG="--headless"
fi

echo "🚀 启动 auto-mine（城市=$CITY），日志: $LOGFILE"
echo "PID: $$"

# 关键：不使用 nohup/disown，让 bash 退出后子进程继续运行
# macOS 无 setsid，使用 nohup + 后台运行 + 输出重定向
nohup python3 "$SCRIPT_DIR/scripts/playwright-auto-mine.py" --city "$CITY" $HEADLESS_FLAG >> "$LOGFILE" 2>&1 &
PID=$!
echo "✅ 后台进程已启动 (pid=$PID)，日志: $LOGFILE"
echo "查看日志: tail -f $LOGFILE"