#!/bin/bash
# 菏泽工程造价材料信息采集 - 启动脚本

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CMD_DIR="$SCRIPT_DIR/commands"

export PYTHON_CMD="${PYTHON_CMD:-python3}"

show_usage() {
    echo "用法: ./run.sh <命令> [选项]"
    echo ""
    echo "命令:"
    echo "  preview   预览数据"
    echo "  sync      同步到 ES（v0.8 默认走 HezeCollector，加 --legacy 走 v0.7）"
    echo "  status    查看状态"
    echo "  check     增量检测（不写入）"
    echo ""
    echo "sync 常用参数:"
    echo "  --year 2026          只入库指定年份（默认本年，0=不限制）"
    echo "  --period 2026.1期    指定单期"
    echo "  --latest             只同步最新一期"
    echo "  --reset              重置本地进度"
    echo "  --legacy             走 v0.7 cmd_legacy_sync（逃生通道）"
    echo "  --dry-run            预览不写入（仅 legacy 支持）"
    echo "  --max-units N        Collector 路径：只跑前 N 个工作单元（验证用）"
}

[ $# -eq 0 ] && { show_usage; exit 0; }
CMD="$1"; shift

case "$CMD" in
    preview|sync|status|check)
        "$PYTHON_CMD" "$CMD_DIR/$CMD.py" "$@"
        ;;
    *)  show_usage; exit 1 ;;
esac
