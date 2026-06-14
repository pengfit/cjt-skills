#!/bin/bash
# 菏泽工程造价材料信息采集 - 启动脚本

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CMD_DIR="$SCRIPT_DIR/commands"

export PYTHON_CMD="${PYTHON_CMD:-python3}"

case "$1" in
    preview)
        "$PYTHON_CMD" -u "$CMD_DIR/preview.py" "${@:2}"
        ;;
    sync)
        "$PYTHON_CMD" -u "$CMD_DIR/sync.py" "${@:2}"
        ;;
    status)
        "$PYTHON_CMD" -u "$CMD_DIR/status.py" "${@:2}"
        ;;
    *)
        echo "用法: $0 {preview|sync|status} [args...]"
        echo ""
        echo "  preview              预览（不写入）"
        echo "    --period 2026.1     指定周期"
        echo "    --year 2026         只预览指定年份的期（默认本年，0=不限制）"
        echo "    --latest           只预览最新一期"
        echo ""
        echo "  sync                 同步到 ES + MinIO"
        echo "    --period 2026.1     指定周期"
        echo "    --year 2026         只入库指定年份的期（默认本年，0=不限制）"
        echo "    --latest           只同步最新一期"
        echo "    --all              同步所有未入仓的期"
        echo "    --reset            重置进度"
        echo "    --dry-run          预览同步"
        echo ""
        echo "  status               查看进度"
        exit 1
        ;;
esac
