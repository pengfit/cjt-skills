#!/bin/bash
# 重庆工程造价材料信息采集 - 启动脚本

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CMD_DIR="$SCRIPT_DIR/commands"

export PYTHON_CMD="${PYTHON_CMD:-python3}"

if [ "$1" = "sync" ]; then
    "$PYTHON_CMD" "$CMD_DIR/sync.py" "${@:2}" &
    echo "[i] 同步任务已在后台启动 (PID: $!)"
else
    "$PYTHON_CMD" "$CMD_DIR/$1.py" "${@:2}"
fi