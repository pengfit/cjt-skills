#!/usr/bin/env python3
"""
clean_breed_unclassified.py

清理 breed_canonical.db 中 l3_code='UNCLASSIFIED' 的垃圾数据。
(K道友指示 2026-07-25 11:00: /taxonomy 页面品种映射 L3 出现 UNCLASSIFIED
需要删除。)

只清理:
  - breed_canonical.l3_code='UNCLASSIFIED'    (品种→L3 映射垃圾)

不清理:
  - category_v3.l4='UNCLASSIFIED'              (合法 L4 占位符)
  - category_v3.l1/l2/l3 列里的 'UNCLASSIFIED' (v2/v3 字典自身的占位)

注：2026-07-27 起 breed_canonical_review 表已 DROP（本脚本不再处理）。

用法:
  python3 scripts/clean_breed_unclassified.py           # 报告 + 询问
  python3 scripts/clean_breed_unclassified.py --yes    # 直接删
  python3 scripts/clean_breed_unclassified.py --dry-run # 只统计不删
"""
from __future__ import annotations
import sqlite3
import argparse
import sys
import os
from datetime import datetime

DB_PATH = "data/breed_canonical.db"


def _open():
    if not os.path.exists(DB_PATH):
        sys.exit(f"❌ 不存在: {DB_PATH}")
    return sqlite3.connect(DB_PATH)


def report(c: sqlite3.Connection) -> dict:
    table = "breed_canonical"
    row = c.execute(
        f"SELECT COUNT(*) FROM {table} WHERE l3_code=?",
        ("UNCLASSIFIED",),
    ).fetchone()
    n = row[0] if row else 0
    if n > 0:
        dist = c.execute(
            f"SELECT source, COUNT(*) FROM {table} WHERE l3_code=? GROUP BY source",
            ("UNCLASSIFIED",),
        ).fetchall()
        print(f"  {table}: {n} 行 UNCLASSIFIED")
        for s, c2 in dist:
            print(f"    source={s!r}: {c2} 行")
    return {table: n}


def delete_unclassified(c: sqlite3.Connection) -> int:
    n1 = c.execute(
        "DELETE FROM breed_canonical WHERE l3_code=?", ("UNCLASSIFIED",)
    ).rowcount
    c.commit()
    return n1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--yes", action="store_true", help="直接删除（不要 confirm 提示）")
    ap.add_argument("--dry-run", action="store_true", help="只统计不删")
    args = ap.parse_args()

    c = _open()
    print(f"=== {DB_PATH} cleanup ===")
    print(f"  time: {datetime.now().isoformat(timespec='seconds')}")
    print()
    print(f"[scan] before:")
    counts = report(c)

    total = sum(counts.values())
    if total == 0:
        print("\n✅ 没有 UNCLASSIFIED,无需清理。")
        c.close()
        return 0
    if args.dry_run:
        print(f"\n[dry-run] 共 {total} 行待删。")
        c.close()
        return 0

    if not args.yes:
        ans = input(f"\n确认删除上述 {total} 行? [yes/N] ").strip().lower()
        if ans not in ("y", "yes"):
            print("取消")
            c.close()
            return 1
    n1 = delete_unclassified(c)
    print(f"\n[done] 删 breed_canonical: {n1} 行")

    print("\n[verify] after:")
    report(c)
    c.close()
    print("\n=== 注意 ===")
    print("  - 不删 category_v3.l4='UNCLASSIFIED'(合法 L4 占位)")
    print("  - 删除后,下游 ETL 需要 refresh 一遍让缓存同步")
    return 0


if __name__ == "__main__":
    sys.exit(main())