#!/bin/bash
# 8 城 ETL 拆开跑（每城独立进程、独立日志）
# 设计：单城挂不会拖全局，失败可以单独重跑

set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR/.."

CITIES=${CITIES:-"xian sichuan chongqing jinan rizhao henan heze qingdao"}
LOG_DIR="/tmp/etl_8cities_$(date +%Y%m%d_%H%M%S)"
mkdir -p "$LOG_DIR"

echo "=== 8 城 ETL 拆开跑 ==="
echo "  log dir: $LOG_DIR"
echo "  城市: $CITIES"
echo ""

PIDS=()
for city in $CITIES; do
  LOG_FILE="$LOG_DIR/${city}.log"
  echo "  启动 $city → $LOG_FILE"
  PYTHONUNBUFFERED=1 nohup python3 -u ./cli/etl.py --city "$city" --incremental > "$LOG_FILE" 2>&1 &
  PIDS+=("$city:$!")
  sleep 1
done

echo ""
echo "=== 全部已起，PID ==="
for entry in "${PIDS[@]}"; do
  echo "  $entry"
done
echo ""
echo "查进度: tail -f $LOG_DIR/<city>.log"
echo "查状态: ps -p <PID>"
