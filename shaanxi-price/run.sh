#!/bin/bash
# 陕西省工程造价材料信息采集 - 启动脚本

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CMD_DIR="$SCRIPT_DIR/commands"

export PYTHON_CMD="${PYTHON_CMD:-python3}"

show_usage() {
    echo "用法: ./run.sh <命令> [选项]"
    echo ""
    echo "命令:"
    echo "  preview   预览数据（不写 ES、不传 MinIO）"
    echo "  sync      同步到 ES + MinIO"
    echo "  status    查看同步状态"
    echo "  test      测试连通性（ES + MinIO + 源站）"
    echo "  check     增量检测（不写入）"
    echo ""
    echo "sync 选项:"
    echo "  --period 2026.5月        指定 period（如 '2026.5月'、'2026.5期'）"
    echo "  --year  2026             只入指定年份（默认配置中的 target_year=2026）"
    echo "  --latest                 只同步最新一期"
    echo "  --reset                  重置本地进度"
    echo "  --all                    同步所有未入仓的期"
    echo "  --dry-run                预览，不写入"
}

[ $# -eq 0 ] && { show_usage; exit 0; }
CMD="$1"; shift

case "$CMD" in
    preview|sync|status|test|check)
        "$PYTHON_CMD" "$CMD_DIR/$CMD.py" "$@"
        ;;
    *)  show_usage; exit 1 ;;
esac
