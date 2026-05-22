#!/bin/bash
# 西安工程造价材料信息采集入口

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CMD_DIR="$SCRIPT_DIR/commands"

export PYTHON_CMD="${PYTHON_CMD:-python3}"

show_usage() {
    echo "用法: ./run.sh <命令> [选项]"
    echo ""
    echo "命令:"
    echo "  preview           预览数据（不写入 ES）"
    echo "  preview --pages N 预览前 N 页"
    echo "  sync              全量同步全部区县到 ES"
    echo "  sync --dry-run      预览同步（不写入）"
    echo "  sync --force        强制全量同步（忽略增量）"
    echo "  sync --counties \"区县\"  指定区县同步"
    echo "  sync --reset        重置进度，重新开始"
    echo "  sync --no-spot-check 跳过抽检（增量同步专用）"
    echo "  sync --no-log       不写入 ES 进度索引"
    echo "  sync --resume-from COUNTY  从指定区县继续"
    echo "  check              增量检测（自动触发后台同步）"
    echo "  status             查看同步状态"
    echo "  test               测试 ES 连接"
    echo ""
    echo "区县: 阎良区 临潼区 高陵区 鄠邑区 蓝田县 周至县（自动同步全部）"
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
