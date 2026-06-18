#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
migrate_v2_to_v3.py - 把 v2 breed_l3_map 自动迁移到 v3

策略：
  1. 从 v2 DB 读 2124 条 breed_l3_map
  2. 用 l3_v2_to_v3.json 把每条 l3 重命名到 v3
  3. 对 orphan (v2 有但 v3 没有 GB 编码的 11 个) 做语义匹配重新映射
  4. 写入 v3 DB 的 breed_l3_map_v3 表

orphan 处理策略：
  - 用 name 模糊匹配 v3 L3
  - 或用 breed 关键词（"PP-R" → 03.01.02 / "玻璃" → 02.02.09 / "幕墙" → 02.02.09）
  - 实在匹配不上的标 source='v2_orphan_pending'，留人工 review

用法：
  python3 scripts/migrate_v2_to_v3.py
  python3 scripts/migrate_v2_to_v3.py --dry-run   # 只打印不写
"""

import argparse
import json
import sqlite3
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent
DATA_DIR = PROJECT_ROOT / "data"
V2_DB = DATA_DIR / "category_v2_rules.db"
V3_DB = DATA_DIR / "category_v3_rules.db"
MAPPING_JSON = DATA_DIR / "l3_v2_to_v3.json"


# orphan 11 个 v2 L3 的手工重映射
ORPHAN_OVERRIDE = {
    # v2 l3 → v3 l3
    "02.05.01": "02.02.09",  # 玻璃幕墙 → 幕墙工程
    "02.05.02": "02.02.09",  # 石材幕墙 → 幕墙工程
    "02.06.01": "02.02.09",  # 建筑密封胶 → 幕墙工程
    "02.06.02": "02.02.09",  # 防火密封胶 → 幕墙工程
    "02.06.03": "02.02.09",  # 密封条 → 幕墙工程
    "06.03.01": "06.03.01",  # 火灾探测器（v3 同）
    "06.03.02": "06.03.02",  # 报警联动设备（v3 同）
    "04.03.03": "02.02.09",  # 硅酮阻燃密封胶 → 幕墙工程（L2 错位修复）
    "02.03.02": "02.04.07",  # 金属门窗 → 金属窗
    "02.03.09": "02.04.05",  # 其他门窗 → 其他门
    "06.01.03": "02.04.04",  # 防火门窗 → 厂库房大门特种门
}

# 一些特定 breed 的兜底（如果孤儿 L3 用了错误的 GB 但 breed 名字能匹配正确 L3）
BREED_TO_L3_OVERRIDE = {
    # 02.05.* 玻璃幕墙 / 石材幕墙
    ("02.05.01", "玻璃幕墙"): "02.02.09",
    ("02.05.02", "石材幕墙"): "02.02.09",
    ("02.05.01", "玻璃"): "02.02.09",
    ("02.05.02", "石材"): "02.02.09",
    ("02.05.02", "花岗岩"): "02.02.09",
    ("02.05.02", "大理石"): "02.02.09",

    # 02.04.01 金属门窗 拆分：防火门/窗走 02.04.04
    ("02.04.01", "防火门"): "02.04.04",
    ("02.04.01", "防火窗"): "02.04.04",
    ("02.04.01", "防火卷帘"): "02.04.04",
    ("02.04.01", "卷闸门"): "02.04.04",
    ("02.04.01", "卷帘门"): "02.04.04",

    # 01.04.01 钢构件 拆分：钢筋走 01.05.15 钢筋工程
    ("01.04.01", "钢筋"): "01.05.15",

    # 01.03.01 现浇混凝土基础 拆分：预制混凝土板/墙走 01.05.12 预制混凝土板
    # (太精细，先不动)
}


def load_mappings():
    """读 l3_v2_to_v3.json 的映射 + 手工 override 合并"""
    with open(MAPPING_JSON, encoding="utf-8") as f:
        data = json.load(f)

    # 用 json 的 same/cross + override + ORPHAN_OVERRIDE 合并
    merged = {}
    for m in data["mappings"]:
        v2_l3 = m["l3_v2"]
        if m["action"] in ("same", "cross", "override") and m["l3_v3"]:
            # action='override' 走人工修正（如 02.05.04 → 02.02.09）
            kind = "override" if m["action"] == "override" else "mapped"
            merged[v2_l3] = (m["l3_v3"], kind)
        elif m["action"] == "orphan":
            # 查手工 override 兜底
            override = ORPHAN_OVERRIDE.get(v2_l3)
            if override:
                merged[v2_l3] = (override, "orphan_override")
            else:
                merged[v2_l3] = (None, "orphan")
    return merged


def migrate(dry_run=False):
    mappings = load_mappings()
    print(f"[info] v2 → v3 映射表: {sum(1 for _, (_, s) in mappings.items() if _ is not None)} 条")
    print(f"  same/cross: {sum(1 for v, (_, s) in mappings.items() if s == 'mapped')}")
    print(f"  orphan_override: {sum(1 for v, (_, s) in mappings.items() if s == 'orphan_override')}")
    print(f"  orphan (no remap): {sum(1 for v, (_, s) in mappings.items() if s == 'orphan')}")

    # 读 v2 breed_l3_map
    conn_v2 = sqlite3.connect(V2_DB)
    c2 = conn_v2.cursor()
    c2.execute("SELECT breed_clean, l3, source, confidence FROM breed_l3_map")
    v2_rows = c2.fetchall()
    conn_v2.close()
    print(f"[info] v2 breed_l3_map: {len(v2_rows)} 条")

    # 按 (v2_l3, breed) 二次判断（用 BREED_TO_L3_OVERRIDE 兜底）
    rows_to_write = []
    stats = {"same": 0, "cross": 0, "override": 0, "orphan_pending": 0, "skipped_unchanged": 0}
    for breed, v2_l3, source, conf in v2_rows:
        if v2_l3 not in mappings:
            continue
        v3_l3, action = mappings[v2_l3]
        if v3_l3 is None:
            # 尝试 breed 兜底
            for (l3, key), target in BREED_TO_L3_OVERRIDE.items():
                if l3 == v2_l3 and key in breed:
                    v3_l3 = target
                    action = "breed_override"
                    break

        # 还要检查 breed 关键词 override（即使 mapped 状态也用，让防火门/钢筋走到正确 L3）
        if v3_l3 and v3_l3 == "02.04.07":  # 原 mapped 到 02.04.07 金属窗
            for (l3, key), target in BREED_TO_L3_OVERRIDE.items():
                if l3 == v2_l3 and key in breed and target.startswith("02.04.04"):
                    v3_l3 = target
                    action = "breed_override"
                    break
        elif v3_l3 == "01.06.06":  # 原 mapped 到 01.06.06 钢构件
            for (l3, key), target in BREED_TO_L3_OVERRIDE.items():
                if l3 == v2_l3 and key in breed and target.startswith("01.05.15"):
                    v3_l3 = target
                    action = "breed_override"
                    break

        if v3_l3 is None:
            stats["orphan_pending"] += 1
            continue

        # 统计分类
        if action == "mapped":
            if v2_l3 == v3_l3:
                stats["skipped_unchanged"] += 1
            else:
                stats["cross"] += 1
        else:
            stats["override"] += 1

        rows_to_write.append((breed, v3_l3, source, conf))

    print(f"\n[migrate] 写入 v3 breed_l3_map_v3: {len(rows_to_write)} 条")
    print(f"  same (l3 不变): {stats['skipped_unchanged']}")
    print(f"  cross (l3 重命名): {stats['cross']}")
    print(f"  override (orphan 修复): {stats['override']}")
    print(f"  orphan_pending (待人工): {stats['orphan_pending']}")

    if dry_run:
        print("\n[dry-run] 仅打印，不写库")
        # 打印前 10 条样例
        print("\n样例（前 10 条）:")
        for breed, l3, source, conf in rows_to_write[:10]:
            print(f"  {breed:25s} → {l3}  ({source}, conf={conf})")
        return

    # 写 v3
    conn_v3 = sqlite3.connect(V3_DB)
    c3 = conn_v3.cursor()
    c3.execute("DELETE FROM breed_l3_map_v3")
    c3.executemany(
        """INSERT OR REPLACE INTO breed_l3_map_v3
           (breed_clean, l3, source, confidence)
           VALUES (?, ?, ?, ?)""",
        rows_to_write,
    )
    conn_v3.commit()
    conn_v3.close()
    print(f"\n[ok] 写入完成: {V3_DB}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    migrate(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
