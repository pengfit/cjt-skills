#!/usr/bin/env python3
"""从 breed_spec_rules.db 生成 L3 类目 attr 白名单

2026-07-17 v2:从 DWS 取数失败(DWS 被清空),改从规则 DB 取。
规则 DB 里 25,337 条已填 l3,每条规则有 attr 字段,
统计每个 l3 下出现过的 attr,作为该 l3 的允许 keys。

输出:data/category_l3_whitelist.json
"""
import json
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent.parent  # scripts 在 gov-price-etl/scripts/,DB 在 cjt/skills/data/
DB_PATH = PROJECT_ROOT / "data" / "breed_spec_rules.db"
OUTPUT_PATH = PROJECT_ROOT / "data" / "category_l3_whitelist.json"

THRESHOLD = 0.10  # 至少 10% 规则有该 attr_key 才保留(防止 1/10000 噪声)


def main():
    if not DB_PATH.exists():
        print(f"❌ DB 不存在: {DB_PATH}")
        return
    
    conn = sqlite3.connect(DB_PATH, timeout=30)
    print(f"DB: {DB_PATH}")
    
    # 1. 拉所有非空 l3 的规则 attr 分布
    rows = conn.execute("""
        SELECT l3, attr FROM breed_spec_rules
        WHERE l3 IS NOT NULL AND l3 != '' AND attr IS NOT NULL AND attr != ''
    """).fetchall()
    print(f"总规则数(有 l3): {len(rows)}")
    
    # 2. 按 l3 聚合 attr 频次
    l3_attr_counter = defaultdict(Counter)
    l3_total = Counter()  # 每个 l3 的总规则数
    for l3, attr in rows:
        l3_attr_counter[l3][attr] += 1
        l3_total[l3] += 1
    
    print(f"唯一 L3 数: {len(l3_attr_counter)}")
    
    # 3. 生成白名单:保留覆盖率 >= THRESHOLD 的 attr
    whitelist = {}
    print(f"\n阈值: 覆盖率 >= {THRESHOLD*100:.0f}% 的 attr_keys 入选")
    print(f"{'L3':10s} {'规则数':>6s} {'白名单数':>8s}  白名单 keys")
    print("-" * 80)
    
    for l3 in sorted(l3_attr_counter.keys()):
        counter = l3_attr_counter[l3]
        total = l3_total[l3]
        kept = []
        for attr_k, cnt in counter.most_common():
            if cnt / total >= THRESHOLD:
                kept.append(attr_k)
        # 至少保留 1 个(出现最多的)
        if not kept and counter:
            kept = [counter.most_common(1)[0][0]]
        whitelist[l3] = kept
        if total >= 50:  # 只展示有意义的 L3
            print(f"  {l3:10s} {total:>6d} {len(kept):>8d}  {','.join(kept[:8])}{'...' if len(kept) > 8 else ''}")
    
    # 4. 写文件
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(whitelist, f, ensure_ascii=False, indent=2)
    
    print(f"\n✅ 白名单写入: {OUTPUT_PATH}")
    print(f"   总 L3 数: {len(whitelist)}")
    print(f"   平均 keys/L3: {sum(len(v) for v in whitelist.values())/max(len(whitelist),1):.1f}")
    print(f"   平均覆盖率阈值: {THRESHOLD*100:.0f}%")


if __name__ == "__main__":
    main()
