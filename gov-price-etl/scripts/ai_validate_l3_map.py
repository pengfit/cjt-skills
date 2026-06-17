#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ai_validate_l3_map.py - AI 重新校验 v1_translated 来源的 breed_l3_map

背景：
  breed_l3_map 中有 4068 条 v1_translated（v1 大类字典 → v2 L3 的映射），
  confidence=0.7 偏低，且 64 个 L3 只用到 13 个（翻译映射过粗）。
  本脚本用 AI 重新校验每条品种应归属哪个 L3，写回 DB。

策略：
  1. 读 4068 条 v1_translated（带 current_l3）
  2. 攒批（默认 30 条/批）调 AI（默认串行，workers=1）
  3. 给 AI 64 L3 全量 + 当前 L3 作为参考上下文
  4. AI 输出：suggested_l3 + confidence + 1 句理由
  5. 保守策略：只接受 confidence >= 0.85 的变更；低于此保留 current_l3
  6. 合法性校验：suggested_l3 必须在 64 L3 全集里，否则丢弃该变更
  7. 写回 DB：l3=新值 / source=ai_v2 / confidence=新值 / updated_at=NOW

注意事项：
  - category_v2.l3 字段已是完整编码（如 "01.04.01"，l1.l2.末段 拼接），
    不是 "l1.l2.l3" 三段独立字段。prompt 已显式说明避免 AI 重复拼段。

用法：
    python3 scripts/ai_validate_l3_map.py --dry-run          # 只打印不改 DB
    python3 scripts/ai_validate_l3_map.py --limit 50         # 测试 50 条
    python3 scripts/ai_validate_l3_map.py --batch-size 30    # 自定义批大小
    python3 scripts/ai_validate_l3_map.py                    # 全量 4068 条
"""

import argparse
import json
import sqlite3
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Dict, List, Tuple

SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(PROJECT_ROOT))

from gov_price_etl.ai.service import _call_gateway
from gov_price_etl.paths import CATEGORY_V2_RULES_DB, PROJECT_ROOT

DB_PATH = CATEGORY_V2_RULES_DB

# 调参
BATCH_SIZE = 20
AI_TIMEOUT = 180
SLEEP_BETWEEN_BATCH_S = 0.5
CONCURRENT_WORKERS = 1  # 串行：避免 gateway 拥堵
MIN_ACCEPT_CONFIDENCE = 0.85  # 保守：低于此保留 current_l3


def load_taxonomy(conn: sqlite3.Connection) -> List[dict]:
    """读 64 L3 全量（含 l1/l2/l3/name_l3/name_l1）作为 AI 上下文。"""
    rows = conn.execute("""
        SELECT l1, l2, l3, name_l1, name_l2, name_l3
        FROM category_v2
        ORDER BY l1, l2, l3
    """).fetchall()
    return [
        {"l1": r[0], "l2": r[1], "l3": r[2], "name_l1": r[3],
         "name_l2": r[4], "name_l3": r[5]}
        for r in rows
    ]


def load_translated_rows(conn: sqlite3.Connection, limit: int = 0) -> List[dict]:
    """读 v1_translated 来源的全部 rows。"""
    sql = "SELECT breed_clean, l3, confidence FROM breed_l3_map WHERE source='v1_translated'"
    if limit > 0:
        sql += f" LIMIT {int(limit)}"
    rows = conn.execute(sql).fetchall()
    return [
        {"breed_clean": r[0], "current_l3": r[1], "current_confidence": r[2]}
        for r in rows
    ]


# ── Prompt 模板 ─────────────────────────────────────────────────────
SYSTEM_MSG = (
    "你是建筑工程造价专家与 BIM 工程师。"
    "任务：对每个材料品种，判断它最适合的 v2 L3 分类编码。"
    "必须基于 64 L3 全量列表 + 当前 L3 参考 + 材料名做判断。"
    "禁止编造不在列表里的 L3。"
)

TEMPLATE = """\
v2 L3 分类法全量（{total_l3} 个 L3，按 L1→L2→L3 层级）：

⚠️ 编码格式说明：每行的第一个字段（形如 "01.04.01"）就是完整的 L3 编码，**已是 3 段拼接**。
不要再拼接、不要补 0、不要加后缀。直接复制粘贴即可。

{l3_list}

待校验的 {batch_n} 条品种（来自 v1 字典翻译，confidence=0.7 偏低）：
{breed_list}

每行品种格式：N. breed=<品种名> | current_l3=<当前 L3 编码>
其中 current_l3 是 v1→v2 自动翻译的结果，可能过粗或不够准确。

你的任务：对每条品种输出一个 JSON 对象，按出现顺序排列到 results 数组：
  - "breed_clean": 原品种名（保持完全一致）
  - "current_l3": 原 L3 编码（保持完全一致）
  - "suggested_l3": 你建议的 L3 编码（必须是上面 64 L3 完整编码之一，3 段格式如 "01.04.01"；如 current 已准确，输出原值）
  - "confidence": 0.0-1.0 置信度（>=0.85 表示高置信度变更/确认）
  - "reason": 一句话理由（中文，不超过 30 字）

输出 JSON 结构（严格遵守，不要任何额外说明文字）：
{{
  "ok": true,
  "results": [
    {{"breed_clean": "...", "current_l3": "...", "suggested_l3": "...", "confidence": 0.9, "reason": "..."}},
    ...
  ]
}}
"""


def format_l3_list(taxonomy: List[dict]) -> str:
    """把 64 L3 拼成短文本。
    重要：t['l3'] 字段已是完整编码（如 "01.04.01"），不要再拼 l1.l2。
    """
    lines = []
    for t in taxonomy:
        # 直接用 l3（已是完整 3 段编码），层级通过 name 助理解
        lines.append(f"{t['l3']}  [{t['name_l1']} > {t['name_l2']} > {t['name_l3']}]")
    return "\n".join(lines)


def format_breed_list(items: List[dict]) -> str:
    """待校验品种拼成短文本。"""
    lines = []
    for i, it in enumerate(items, 1):
        lines.append(f"  {i}. breed={it['breed_clean']} | current_l3={it['current_l3']}")
    return "\n".join(lines)


def call_ai_validate(batch: List[dict], taxonomy: List[dict], retries: int = 2) -> Tuple[bool, str, dict]:
    """调 AI 校验一批（带重试）。返回 (ok, raw_content, parsed_json)。"""
    user = TEMPLATE.format(
        total_l3=len(taxonomy),
        l3_list=format_l3_list(taxonomy),
        batch_n=len(batch),
        breed_list=format_breed_list(batch),
    )
    last_err = ""
    for attempt in range(1, retries + 2):
        ok, content = _call_gateway(
            prompt=user,
            system=SYSTEM_MSG,
            user="validate_l3_batch",
            timeout=180,  # 64 L3 全量 + 长 batch 给足时间
        )
        if not ok:
            last_err = content
            if attempt <= retries:
                time.sleep(3 * attempt)  # 退避重试
                continue
            return False, last_err, {}

        # 解析 JSON
        parsed = {}
        try:
            c = content.strip()
            if c.startswith("```"):
                c = c.split("```")[1]
                if c.startswith("json"):
                    c = c[4:]
            parsed = json.loads(c.strip())
        except Exception as e:
            last_err = f"JSON 解析失败: {e} | raw={content[:200]}"
            if attempt <= retries:
                time.sleep(2 * attempt)
                continue
            return False, last_err, {}

        return True, content, parsed
    return False, last_err, {}


def _norm_bc(s: str) -> str:
    """breed_clean 归一化：智能引号 → 直引号，全/半角标点统一。
    AI 模型常会把 U+201C/U+201D (“”) 规范成 ASCII 的 " (U+0022)，
    导致 join 丢失。归一化后才能匹配上原始 batch。
    """
    if not s:
        return s
    return (
        s
        .replace('\u201c', '"').replace('\u201d', '"')   # 智能双引号 → 直双引号
        .replace('\u2018', "'").replace('\u2019', "'")   # 智能单引号 → 直单引号
        .replace('\u3001', ',')                            # 中文句号 → 逗号
    )


def merge_results(batch: List[dict], ai_results: List[dict], valid_l3_set: set) -> List[dict]:
    """合并 AI 输出 + 原始 batch，按 breed_clean 关联。
    合法性校验：suggested_l3 必须在 64 L3 全集里，否则 ai_valid=False。
    """
    by_bc = {it["breed_clean"]: it for it in batch}
    # 归一化索引（用于匹配 AI 返回的 breed_clean）
    by_bc_norm = {_norm_bc(k): v for k, v in by_bc.items()}
    merged = []
    for r in ai_results:
        bc = r.get("breed_clean", "")
        # 优先精确匹配，失败时回退到归一化匹配
        orig = by_bc.get(bc) or by_bc_norm.get(_norm_bc(bc))
        if not orig:
            continue
        sug_l3_raw = r.get("suggested_l3", orig["current_l3"])
        sug_l3 = str(sug_l3_raw).strip() if sug_l3_raw is not None else orig["current_l3"]
        is_valid = sug_l3 in valid_l3_set
        merged.append({
            **orig,
            "suggested_l3": sug_l3,
            "ai_confidence": float(r.get("confidence", 0)),
            "ai_reason": r.get("reason", ""),
            "ai_valid": is_valid,
        })
    return merged


def write_back(conn: sqlite3.Connection, updates: List[dict], dry_run: bool, min_accept: float) -> Tuple[int, int, int]:
    """
    写回 DB。保守策略：ai_confidence >= min_accept 且 ai_valid 且 suggested_l3 != current_l3 才接受变更；
    否则保留 current_l3（只更新 confidence 为 ai_confidence）。
    返回 (changed_count, kept_count, invalid_count)。
    """
    changed = 0
    kept = 0
    invalid = 0
    now = time.strftime("%Y-%m-%d %H:%M:%S")

    for u in updates:
        cur_l3 = u["current_l3"]
        sug_l3 = u["suggested_l3"]
        ai_conf = u["ai_confidence"]
        ai_valid = u.get("ai_valid", False)

        if not ai_valid:
            # AI 给的 L3 不合法（不在 64 L3 全集里）—— 保留 current_l3，仅更新 conf
            new_l3 = cur_l3
            new_conf = ai_conf
            invalid += 1
            kept += 1
        elif ai_conf >= min_accept and sug_l3 != cur_l3:
            # 接受变更
            new_l3 = sug_l3
            new_conf = ai_conf
            changed += 1
        else:
            # 保留原值（更新 conf 和 updated_at 作为 AI 校验的痕迹）
            new_l3 = cur_l3
            new_conf = ai_conf
            kept += 1

        if not dry_run:
            conn.execute(
                """
                UPDATE breed_l3_map
                SET l3 = ?, source = 'ai_v2', confidence = ?, updated_at = ?
                WHERE breed_clean = ?
                """,
                (new_l3, new_conf, now, u["breed_clean"]),
            )
    conn.commit()
    return changed, kept, invalid


def main():
    p = argparse.ArgumentParser(description="AI 重新校验 breed_l3_map (v1_translated 来源)")
    p.add_argument("--dry-run", action="store_true", help="只跑不改 DB")
    p.add_argument("--limit", type=int, default=0, help="限制条数（测试用）")
    p.add_argument("--batch-size", type=int, default=BATCH_SIZE, help="每批条数")
    p.add_argument("--sleep", type=float, default=SLEEP_BETWEEN_BATCH_S, help="批间隔秒")
    p.add_argument("--workers", type=int, default=CONCURRENT_WORKERS, help="并发批数")
    p.add_argument("--min-accept", type=float, default=MIN_ACCEPT_CONFIDENCE,
                   help="AI confidence >= 此值才接受变更")
    p.add_argument("--show-suggestions", action="store_true",
                   help="dry-run 时打印 AI 建议明细")
    p.add_argument("--show-limit", type=int, default=15, help="--show-suggestions 打印条数")
    args = p.parse_args()

    print(f"📂 DB: {DB_PATH}")
    print(f"⚙️  batch_size={args.batch_size}, min_accept={args.min_accept}, dry_run={args.dry_run}")
    print()

    conn = sqlite3.connect(DB_PATH)
    taxonomy = load_taxonomy(conn)
    valid_l3_set = {t["l3"] for t in taxonomy}
    print(f"✓ 加载 64 L3 分类法")
    rows = load_translated_rows(conn, limit=args.limit)
    print(f"✓ 加载 {len(rows)} 条 v1_translated（待校验）")
    print()

    # 统计 current_l3 分布
    from collections import Counter
    cur_dist = Counter(r["current_l3"] for r in rows)
    print(f"当前 L3 分布（校验前）：")
    for l3, cnt in sorted(cur_dist.items(), key=lambda x: -x[1]):
        print(f"  {l3}  {cnt}")
    print()

    # 攒批
    total_changed = 0
    total_kept = 0
    total_failed = 0
    total_invalid_now = [0]  # 用 list 包装以支持 nonlocal
    batches = [rows[i:i + args.batch_size] for i in range(0, len(rows), args.batch_size)]
    print(f"🚀 开始校验 {len(rows)} 条，分 {len(batches)} 批（并发 {args.workers}）")
    print("=" * 70)

    db_lock = threading.Lock()

    def ai_only(bi_batch):
        """仅调 AI，不写 DB。返回 (bi, batch, parsed_or_None, err)。"""
        bi, batch = bi_batch
        ok, raw, parsed = call_ai_validate(batch, taxonomy)
        if not ok or "results" not in parsed:
            return bi, batch, None, raw[:120]
        return bi, batch, parsed, ""

    def write_one(bi, batch, parsed):
        """串行写 DB。"""
        nonlocal total_changed, total_kept, total_failed
        if parsed is None:
            total_failed += len(batch)
            return bi, 0, 0, len(batch), "AI 调用失败"
        ai_results = parsed["results"]
        merged = merge_results(batch, ai_results, valid_l3_set)
        # dry-run + show-suggestions 时打印变更明细
        if args.dry_run and args.show_suggestions:
            for m in merged[:args.show_limit]:
                if not m.get("ai_valid"):
                    flag = "✗ INVALID"
                elif m["ai_confidence"] >= args.min_accept and m["suggested_l3"] != m["current_l3"]:
                    flag = "✓ CHANGE"
                else:
                    flag = "· keep  "
                print(f"    {flag}  {m['breed_clean']:25s}  {m['current_l3']} → {m['suggested_l3']}  conf={m['ai_confidence']:.2f}  reason={m.get('ai_reason','')}")
        with db_lock:
            changed, kept, invalid = write_back(conn, merged, dry_run=args.dry_run, min_accept=args.min_accept)
            total_changed += changed
            total_kept += kept
            total_invalid = total_invalid_now[0] + invalid
            total_invalid_now[0] = total_invalid
        return bi, changed, kept, 0, ""

    t0 = time.time()
    completed = 0
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futures = {ex.submit(ai_only, (bi, b)): bi for bi, b in enumerate(batches, 1)}
        for fut in as_completed(futures):
            bi, batch, parsed, err = fut.result()
            bi2, changed, kept, failed, write_err = write_one(bi, batch, parsed)
            completed += 1
            elapsed = time.time() - t0
            rate = completed / elapsed if elapsed > 0 else 0
            eta_s = (len(batches) - completed) / rate if rate > 0 else 0
            if failed:
                print(f"  ❌ 批 {bi:>3d}/{len(batches)} 失败: {write_err or err}")
            else:
                print(f"  ✓ 批 {bi:>3d}/{len(batches)}  "
                      f"changed={changed:2d}  kept={kept:2d}  "
                      f"elapsed={elapsed/60:.1f}min  ETA={eta_s/60:.1f}min")
            time.sleep(args.sleep)

    print()
    print("=" * 70)
    print(f"🏁 完成：{len(rows)} 条 / {len(batches)} 批 / 失败 {total_failed} 条 / 耗时 {(time.time()-t0)/60:.1f} 分钟")
    print(f"   接受变更: {total_changed} 条")
    print(f"   保持原值: {total_kept} 条")
    print(f"   AI 输出非法 L3（被丢弃）: {total_invalid_now[0]} 条")

    # 校验后 L3 分布
    if not args.dry_run:
        rows_after = conn.execute(
            "SELECT l3, count(*) FROM breed_l3_map WHERE source='ai_v2' GROUP BY l3 ORDER BY count(*) DESC"
        ).fetchall()
        print()
        print(f"校验后 ai_v2 L3 分布（共 {sum(r[1] for r in rows_after)} 条）：")
        for l3, cnt in rows_after[:20]:
            print(f"  {l3}  {cnt}")

    conn.close()


if __name__ == "__main__":
    main()
