#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
translate_v1_to_v2.py - v1 breed_category_rules.db → v2 breed_l3_map 转译

背景：
  v1 字典（data/breed_category_rules.db）有 4068 条 breed→category 映射（v1 26 类）
  v2 字典（data/category_v2_rules.db）有 50 个 L3 节点 + breed_l3_map（空）

  v1 26 类按"材料类型"分（钢材金属材料 / 园林绿化 / ...）
  v2 L1 按"工程专业"分（建筑工程 / 园林景观 / ...）
  v1→L1 是"类型→工程"的语义映射

转译策略：
  1. v1 breed → clean_breed() 标准化 → v2 breed_clean
  2. v1 category → 查 v1_to_l1 映射表 → v2 L1
  3. v2 L1 → 查 l1_to_default_l3 → v2 L3（默认 L1 内最常见 L3）
  4. 写入 v2 breed_l3_map，source='v1_translated', confidence=0.7

限制：
  - 粒度粗（按 v1 类映射到 L1 内的默认 L3）
  - 仅覆盖 v1 字典里有的品种
  - 后续 AI 阶段 4 接管（用更高 confidence 覆盖）

用法：
    python3 scripts/translate_v1_to_v2.py             # 默认转译
    python3 scripts/translate_v1_to_v2.py --reset     # 先清空 v2 breed_l3_map 再转译
    python3 scripts/translate_v1_to_v2.py --dry-run  # 只统计不写入
"""

import argparse
import json
import sqlite3
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(PROJECT_ROOT))


V1_DB = PROJECT_ROOT / "data" / "breed_category_rules.db"
V2_DB = PROJECT_ROOT / "data" / "category_v2_rules.db"
MAP_JSON = PROJECT_ROOT / "data" / "v1_to_v2_l1_map.json"


def main():
    parser = argparse.ArgumentParser(description="v1 字典 → v2 breed_l3_map 转译")
    parser.add_argument("--dry-run", action="store_true", help="只统计不写入")
    parser.add_argument("--reset", action="store_true", help="先清空 v2 breed_l3_map 再转译")
    args = parser.parse_args()

    if not V1_DB.exists():
        print(f"[err] v1 库不存在: {V1_DB}", file=sys.stderr)
        sys.exit(1)
    if not V2_DB.exists():
        print(f"[err] v2 库不存在: {V2_DB}，先跑 init_category_v2_db.py 初始化", file=sys.stderr)
        sys.exit(1)
    if not MAP_JSON.exists():
        print(f"[err] 映射表不存在: {MAP_JSON}", file=sys.stderr)
        sys.exit(1)

    # 加载映射表
    with open(MAP_JSON, encoding="utf-8") as f:
        m = json.load(f)
    v1_to_l1 = m["v1_to_l1"]
    l1_to_l3 = m["l1_to_default_l3"]
    confidence = m["translation_confidence"]
    source = m["translation_source"]

    # 读 v1 字典
    v1 = sqlite3.connect(str(V1_DB))
    v1_rules = v1.execute(
        "SELECT breed, category, source FROM breed_category_rules"
    ).fetchall()
    v1.close()
    print(f"[read] v1 字典: {len(v1_rules)} 条")

    # 读 v2 字典（验证 L3 存在）
    v2 = sqlite3.connect(str(V2_DB))
    valid_l3 = {r[0] for r in v2.execute("SELECT DISTINCT l3 FROM category_v2")}
    valid_l1 = {r[0] for r in v2.execute("SELECT DISTINCT l1 FROM category_v2")}
    print(f"[read] v2 字典: {len(valid_l1)} L1 / {len(valid_l3)} L3")

    # 应用 clean_breed（跟 ETL 一致）
    from gov_price_etl.transform.clean import clean_breed

    # 转译
    rows_to_insert = []
    skip_reasons = {"no_v1_l1_mapping": 0, "empty_breed": 0, "dup_breed": 0, "invalid_l3": 0, "below_threshold": 0}
    seen_breed_clean = set()
    skipped_examples = []

    # 入库最低置信度（与 service.py / stage 1/2 一致）
    from gov_price_etl.classify.constants import MIN_RULE_CONFIDENCE

    for breed, category, src in v1_rules:
        if not breed or not category:
            skip_reasons["empty_breed"] += 1
            continue
        l1 = v1_to_l1.get(category)
        if not l1:
            skip_reasons["no_v1_l1_mapping"] += 1
            if len(skipped_examples) < 5:
                skipped_examples.append(f"  - {category!r} → 无 L1 映射: {breed!r}")
            continue
        l3 = l1_to_l3.get(l1)
        if l3 not in valid_l3:
            skip_reasons["invalid_l3"] += 1
            continue

        breed_clean = clean_breed(breed)
        if not breed_clean:
            skip_reasons["empty_breed"] += 1
            continue
        if breed_clean in seen_breed_clean:
            skip_reasons["dup_breed"] += 1
            continue
        seen_breed_clean.add(breed_clean)

        # 低 conf 直接不入库（避免污染规则库）
        if confidence < MIN_RULE_CONFIDENCE:
            skip_reasons["below_threshold"] += 1
            continue

        rows_to_insert.append((breed_clean, l3, source, confidence))

    print(f"\n=== 转译结果 ===")
    print(f"  准备写入: {len(rows_to_insert)} 条")
    for k, v in skip_reasons.items():
        if v:
            print(f"  跳过 ({k}): {v}")
    if skipped_examples:
        print(f"\n  跳过示例（前 5）:")
        for s in skipped_examples:
            print(s)

    # 按 l3 统计
    by_l3 = {}
    for _, l3, _, _ in rows_to_insert:
        by_l3[l3] = by_l3.get(l3, 0) + 1
    print(f"\n  按 L3 分布（前 10）:")
    for l3, cnt in sorted(by_l3.items(), key=lambda x: -x[1])[:10]:
        print(f"    L3={l3:8s}  {cnt:4d} 条")

    if args.dry_run:
        print(f"\n[DRY-RUN] 不写入 v2 breed_l3_map")
        return

    # 写入 v2 breed_l3_map
    if args.reset:
        deleted = v2.execute("DELETE FROM breed_l3_map").rowcount
        print(f"\n[reset] 清空 v2 breed_l3_map: {deleted} 条")
    v2.executemany(
        """INSERT OR REPLACE INTO breed_l3_map (breed_clean, l3, source, confidence)
           VALUES (?, ?, ?, ?)""",
        rows_to_insert,
    )
    v2.commit()
    print(f"\n[write] 写入 v2 breed_l3_map: {len(rows_to_insert)} 条")

    # 验证
    cnt = v2.execute("SELECT COUNT(*) FROM breed_l3_map").fetchone()[0]
    print(f"[verify] v2 breed_l3_map 当前: {cnt} 条")
    v2.close()


if __name__ == "__main__":
    main()
