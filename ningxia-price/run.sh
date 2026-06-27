#!/bin/bash
# 宁夏工程造价信息采集 - 启动脚本

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CMD_DIR="$SCRIPT_DIR/commands"

export PYTHON_CMD="${PYTHON_CMD:-python3}"

show_usage() {
    echo "用法: ./run.sh <命令> [选项]"
    echo ""
    echo "命令:"
    echo "  preview   预览数据"
    echo "  sync      同步到 ES"
    echo "  status    查看状态"
    echo "  test      测试连通性"
}

[ $# -eq 0 ] && { show_usage; exit 0; }
CMD="$1"; shift

case "$CMD" in
    preview|sync|status|test)
        "$PYTHON_CMD" "$CMD_DIR/$CMD.py" "$@"
        ;;
    *)  show_usage; exit 1 ;;
esac