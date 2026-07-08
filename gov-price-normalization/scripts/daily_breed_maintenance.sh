#!/usr/bin/env bash
# daily_breed_maintenance.sh — 每日 breed_canonical 维护 + NORM 增量重建
#
# 三步串联：
#   1. extract   — 扫 DWS 找新的 breed_clean（不入 AI）
#   2. resolve   — 调 Dify etl-canonicalize-breed 规范化（防回归）
#   3. classify  — 补 UNCLASSIFIED 的 l3_code（防回归）
#   4. rebuild   — NORM 增量重建（since 默认 7 天，覆盖本周新增）
#
# 设计原则：
#   - 每步都幂等：跑多次不破坏数据
#   - 任一步失败：log 错误但继续后续步骤（让运维能在早上看到完整报告）
#   - 整步耗时预估：~15-30 分钟（resolve + classify 是 Dify 瓶颈）
#
# 调度方式：OpenClaw cron 每日 02:00（Asia/Shanghai）
#   见 ~/.openclaw/workspace/cjt/memory/cron_jobs.md
#
# 用法：
#   bash scripts/daily_breed_maintenance.sh           # 日常跑
#   SINCE=14 bash scripts/daily_breed_maintenance.sh  # 重跑最近 14 天
#   SKIP_REBUILD=1 bash scripts/daily_breed_maintenance.sh  # 只维护 breed_canonical

set -u
# 不开 set -e：单步失败不能阻断后续步骤（运维要能看见整盘情况）

cd "$(dirname "$0")/.." || exit 1
SKILL_ROOT="$(pwd)"
PKG="gov_price_normalization"

SINCE="${SINCE:-7}"
TS="$(date +%Y%m%d_%H%M%S)"
LOG_DIR="tmp"
mkdir -p "$LOG_DIR"

LOG="$LOG_DIR/daily_${TS}.log"
echo "[$(date '+%Y-%m-%d %H:%M:%S')] daily_breed_maintenance start (since=${SINCE}d) → $LOG"
exec > >(tee -a "$LOG") 2>&1

PENDING="$LOG_DIR/pending_breeds_${TS}.json"

# ── 1. extract：DWS 扫 distinct breed_clean ─────────────────────────
echo
echo "========== [1/4] extract =========="
if python3 -m cli.canonicalize_breeds extract --out "$PENDING"; then
    echo "[1/4] extract OK → $PENDING"
else
    echo "[1/4] extract FAIL（跳到 step 2-3 处理历史 pending）"
    # 不 exit，pending 文件可能上次留下
fi

# ── 2. resolve：调 Dify 规范化 ──────────────────────────────────────
echo
echo "========== [2/4] resolve =========="
if [ -f "$PENDING" ]; then
    PEND_COUNT=$(python3 -c "import json; d=json.load(open('$PENDING')); print(d.get('pending_count', 0))")
    if [ "${PEND_COUNT:-0}" -gt 0 ]; then
        if python3 -m cli.canonicalize_breeds resolve --in "$PENDING" --batch-size 20; then
            echo "[2/4] resolve OK"
        else
            echo "[2/4] resolve FAIL（pending 仍待下次）"
        fi
    else
        echo "[2/4] 无 pending，跳过"
    fi
else
    echo "[2/4] pending 文件不存在，跳过"
fi

# ── 3. classify：补 UNCLASSIFIED 的 l3_code ────────────────────────
echo
echo "========== [3/4] classify =========="
if python3 -m cli.canonicalize_breeds classify --batch-size 10; then
    echo "[3/4] classify OK"
else
    echo "[3/4] classify FAIL（下次再跑）"
fi

# ── 4. rebuild：NORM 增量重建 ──────────────────────────────────────
echo
echo "========== [4/4] rebuild (since=${SINCE}d) =========="
if [ "${SKIP_REBUILD:-0}" = "1" ]; then
    echo "[4/4] SKIP_REBUILD=1，跳过"
else
    SINCE_DATE=$(python3 -c "from datetime import datetime, timedelta; print((datetime.utcnow() - timedelta(days=${SINCE})).strftime('%Y-%m-%d'))")
    if python3 -m cli.build_norm_index --all-cities --since "$SINCE_DATE"; then
        echo "[4/4] rebuild OK"
    else
        echo "[4/4] rebuild FAIL（partial 状态，NORM 索引可能不一致）"
    fi
fi

# ── 收尾 ────────────────────────────────────────────────────────────
echo
echo "========== summary =========="
python3 -m cli.canonicalize_breeds stats

# 清理 pending 临时文件
[ -f "$PENDING" ] && rm -f "$PENDING"

echo
echo "[$(date '+%Y-%m-%d %H:%M:%S')] daily_breed_maintenance done"