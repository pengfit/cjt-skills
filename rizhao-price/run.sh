#!/bin/bash
# 日照工程造价信息采集入口（v1.1 多期 + REST API 模式, 2026-07-03）

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CMD_DIR="$SCRIPT_DIR/commands"

export PYTHON_CMD="${PYTHON_CMD:-python3}"

show_usage() {
    echo "用法: ./run.sh <命令> [选项]"
    echo ""
    echo "命令:"
    echo "  sync                          同步到 ES（默认 Collector 路径，推荐）"
    echo "  sync --periods 2026-01..2026-05  多期范围语法：5 期 × 3 tab = 15 units"
    echo "  sync --periods 2026-01,2026-02   多期列表语法"
    echo "  sync --tabs 1                 只抓建设工程材料（1=建设, 2=苗木, 3=区县）"
    echo "  sync --tabs 1,3               抓建设+区县，跳过苗木"
    echo "  sync --reset                  重置本地进度，重新开始"
    echo "  sync --max-units 1            验证模式：只跑前 1 个 unit"
    echo "  sync --legacy                 走 v0 流式旧路径（逃生通道）"
    echo ""
    echo "  preview                       预览前 N 页数据（默认 2 页，兼容旧调用）"
    echo "  status                        查看同步状态"
    echo "  check                         检查源站是否有新数据（兼容旧调用）"
    echo "  test                          测试 ES 和源站连接"
    echo ""
    echo "字段："
    echo "  每个 doc 必含 period_start / period_end / period_days（v1.0 新增）"
    echo "  period 格式：'YYYY-MM'（如 '2026-05'）→ 推算 start/end/days"
    echo ""
    echo "数据范围（v1.1）："
    echo "  源站支持 2026-01 ~ 2026-05 历史期回溯"
    echo "  5 期 × 3 tab = 15 units，约 80 秒（1 次浏览器启动 + 15 unit API）"
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