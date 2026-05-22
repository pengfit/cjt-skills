#!/bin/bash
# 四川工程造价信息采集入口

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CMD_DIR="$SCRIPT_DIR/commands"

export PYTHON_CMD="${PYTHON_CMD:-python3}"

show_usage() {
    echo "用法: ./run.sh <命令> [选项]"
    echo ""
    echo "命令:"
    echo "  preview              预览数据（不写入 ES）"
    echo "  preview --pages N    预览前 N 页"
    echo "  sync                 同步到 ES（有增量检测）"
    echo "  sync --dry-run       预览同步（不写入）"
    echo "  sync --force         强制全量同步（跳过增量检测）"
    echo "  sync --reset         重置进度，重新开始"
    echo "  sync --period \"2026年03月\"  指定周期"
    echo "  status               查看同步状态"
    echo "  test                 测试 ES 连接"
    echo "  check                检查源站是否有新数据"
    echo ""
    echo "增量逻辑：按时间周期判断。同步完成后自动更新 last_period。"
    echo "定时任务建议：crontab 设置 ./run.sh check，有更新时自动 sync"
    echo "支持翻页：ASP.NET POST 翻页，rptPager_input"
}

if [ $# -eq 0 ]; then
    show_usage
    exit 0
fi

CMD="$1"
shift

case "$CMD" in
    preview|sync|status|test|check)
        "$PYTHON_CMD" "$CMD_DIR/$CMD.py" "$@"
        ;;
    *)
        echo "未知命令: $CMD"
        show_usage
        exit 1
        ;;
esac