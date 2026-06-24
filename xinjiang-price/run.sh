#!/usr/bin/env bash
# 新疆工程造价信息采集 - 一键脚本
set -e
cd "$(dirname "$0")"

case "${1:-help}" in
  sync)
    shift
    python3 commands/sync.py "$@"
    ;;
  sync-dry)
    shift
    python3 commands/sync.py --dry-run "$@"
    ;;
  sync-area)
    shift
    python3 commands/sync.py --areaid "$@"
    ;;
  reset)
    python3 commands/sync.py --reset
    ;;
  check)
    python3 commands/check.py
    ;;
  status)
    python3 commands/status.py
    ;;
  test)
    python3 commands/test.py
    ;;
  help|*)
    echo "用法: $0 {sync|sync-dry|sync-area|reset|check|status|test}"
    echo ""
    echo "  sync          同步 2026 年（默认）所有 area 数据到 ES + MinIO"
    echo "  sync-dry      dry-run（不写入）"
    echo "  sync-area N   只同步指定 areaid"
    echo "  reset         重置本地进度（强制重新同步）"
    echo "  check         增量检测（源站 vs ES）"
    echo "  status        查看本地 + ES + MinIO 状态"
    echo "  test          连通性测试"
    echo ""
    echo "附加参数（透传给 sync.py）："
    echo "  --year YYYY   指定年份（默认 2026）"
    echo "  --no-skip     不跳过已完成条目"
    ;;
esac
