#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
init_category_v3_db.py - 初始化 v3 分类规则库 SQLite

库路径：data/category_v3_rules.db
        （v2 是 category_v2_rules.db，平行）

v3 与 v2 的区别：
- 严格按 GB 50854-2013 / GB/T 50856-2024 / GB 50857-2013 / GB 50858-2013 重建
- L1 仍 8 大类（按材料专业分）
- L2 编号尾号 = GB 附录字母（A=土石方 ... Q=其他装饰）
- L3 全量映射到 GB 标准细目（gb_50500）

表结构同 v2，但 _v3 后缀避免冲突：
- category_v3 — 4 层分类全量节点（PK: l1, l2, l3, l4）
- breed_l3_map_v3 — breed → L3 映射
- l2_l3_v3_v2_map — v3 L3 → v2 L3（兼容老 breed_l3_map 引用）
"""

import argparse
import json
import sqlite3
import sys
from pathlib import Path


SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent
DATA_DIR = PROJECT_ROOT / "data"
DEFAULT_DB_PATH = DATA_DIR / "category_v3_rules.db"
CATEGORY_V3_JSON = DATA_DIR / "category_v3.json"
STD_CODES_V3_JSON = DATA_DIR / "std_codes_v3.json"


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS category_v3 (
    l1           TEXT NOT NULL,
    l2           TEXT NOT NULL,
    l3           TEXT NOT NULL,
    l4           TEXT NOT NULL,
    gb_50500     TEXT NOT NULL,
    ifc_class    TEXT,
    uniclass_ss  TEXT,
    eng_part     TEXT,
    eng_stage    TEXT,
    main_or_aux  TEXT,
    unit         TEXT,
    billing_unit TEXT,
    cost_method  TEXT,
    name_l1      TEXT NOT NULL,
    name_l2      TEXT NOT NULL,
    name_l3      TEXT NOT NULL,
    name_l4      TEXT,
    PRIMARY KEY (l1, l2, l3, l4)
);

CREATE INDEX IF NOT EXISTS idx_v3_l1     ON category_v3(l1);
CREATE INDEX IF NOT EXISTS idx_v3_l2     ON category_v3(l1, l2);
CREATE INDEX IF NOT EXISTS idx_v3_l3     ON category_v3(l1, l2, l3);
CREATE INDEX IF NOT EXISTS idx_v3_gb     ON category_v3(gb_50500);
CREATE INDEX IF NOT EXISTS idx_v3_ifc    ON category_v3(ifc_class);

-- breed → L3 映射（v3 专用）
CREATE TABLE IF NOT EXISTS breed_l3_map_v3 (
    breed_clean TEXT PRIMARY KEY,
    l3          TEXT NOT NULL,
    source      TEXT,
    confidence  REAL DEFAULT 1.0,
    created_at  TEXT    DEFAULT (datetime('now', 'localtime')),
    updated_at  TEXT    DEFAULT (datetime('now', 'localtime'))
);

CREATE INDEX IF NOT EXISTS idx_breed_v3_l3 ON breed_l3_map_v3(l3);

-- v2 → v3 L3 兼容映射（用于把老 breed_l3_map 自动迁移过来）
CREATE TABLE IF NOT EXISTS l3_v2_to_v3 (
    l3_v2 TEXT PRIMARY KEY,
    l3_v3 TEXT,
    action TEXT  -- 'same' / 'remap' / 'orphan' / 'split'
);

-- v3 L3 GB 编码自检：注意 GB 50500 子目编码在 L1 内可以有多个 L3 映射
-- （例：挖一般土方 / 挖沟槽土方 / 挖基坑土方 都映射到 010101）
-- 所以这里只建普通索引，不做 UNIQUE 约束
CREATE INDEX IF NOT EXISTS idx_v3_gb_l1 ON category_v3(l1, gb_50500);
"""


def init_db(db_path: Path, reset: bool = False) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if reset and db_path.exists():
        print(f"[init] 删除旧库: {db_path}")
        db_path.unlink()
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(SCHEMA_SQL)
        conn.commit()
        print(f"[init] Schema OK: {db_path}")
    finally:
        conn.close()


def import_category_nodes(db_path: Path) -> int:
    cat_v3 = json.loads(CATEGORY_V3_JSON.read_text(encoding="utf-8"))
    std_v3 = json.loads(STD_CODES_V3_JSON.read_text(encoding="utf-8"))["codes"]

    rows = []
    for l1_node in cat_v3["tree"]["l1"]:
        l1 = l1_node["code"]
        name_l1 = l1_node["name"]
        for l2_node in l1_node["l2"]:
            l2 = l2_node["code"]
            name_l2 = l2_node["name"]
            for l3_node in l2_node["l3"]:
                l3 = l3_node["code"]
                name_l3 = l3_node["name"]
                std = std_v3.get(l3, {})
                rows.append((
                    l1, l2, l3, "UNCLASSIFIED",
                    std.get("gb_50500") or "010000",
                    std.get("ifc_class"),
                    std.get("uniclass_ss"),
                    std.get("eng_part"),
                    ",".join(std.get("eng_stage", [])) or None,
                    std.get("main_or_aux"),
                    std.get("unit"),
                    std.get("billing_unit"),
                    std.get("cost_method"),
                    name_l1, name_l2, name_l3, "",
                ))

    conn = sqlite3.connect(db_path)
    try:
        conn.execute("DELETE FROM category_v3")
        conn.executemany(
            """INSERT OR REPLACE INTO category_v3
               (l1, l2, l3, l4, gb_50500, ifc_class, uniclass_ss,
                eng_part, eng_stage, main_or_aux, unit, billing_unit, cost_method,
                name_l1, name_l2, name_l3, name_l4)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            rows,
        )
        conn.commit()
        print(f"[import] category_v3: {len(rows)} 行")
        return len(rows)
    finally:
        conn.close()


def verify_consistency(db_path: Path) -> bool:
    """校验：GB 编码格式 + 跨册映射提示"""
    conn = sqlite3.connect(db_path)
    try:
        c = conn.cursor()

        # 1) 6 位 GB 编码格式
        c.execute("SELECT l1, l2, l3, gb_50500 FROM category_v3 WHERE length(gb_50500) != 6")
        bad = c.fetchall()
        if bad:
            print(f"[FAIL] GB 编码非 6 位 {len(bad)} 处：")
            for r in bad[:5]:
                print(f"  {r}")
            return False

        # 2) L1 数字 ↔ GB 前 2 位一致性（GB 50854/50857/50858 体系的例外要打印提示）
        c.execute("SELECT l1, l2, l3, gb_50500, substr(gb_50500, 1, 2) gb_l1 FROM category_v3")
        rows = c.fetchall()
        mismatched = []
        for r in rows:
            l1, l2, l3, gb, gb_l1 = r
            if l1 != gb_l1:
                mismatched.append(r)
        if mismatched:
            print(f"[INFO] L1 ↔ GB 前 2 位不匹配 {len(mismatched)} 处（GB 50854 / 50857 / 50858 跨册映射）:")
            for r in mismatched[:10]:
                print(f"  l1={r[0]} l3={r[2]} gb={r[3]} (gb_l1={r[4]})")
            # 不算失败：L1=02 装饰工程 用 GB 50854 (01xxxx)；L1=07 市政 用 GB 50857 (04xxxx)；L1=08 园林 用 GB 50858 (05xxxx)

        # 3) 统计每个 GB 编码对应的 L3 数量（一个子目多个 L3 是预期的）
        c.execute("SELECT gb_50500, COUNT(DISTINCT l3) c FROM category_v3 GROUP BY gb_50500 ORDER BY c DESC LIMIT 5")
        top = c.fetchall()
        print(f"[ok] GB 编码全部 6 位（{len(rows)} 条）")
        print(f"[ok] 共享 GB 子目 (1 子目多 L3 映射)，top 5：")
        for gb, c in top:
            print(f"     {gb} → {c} 个 L3")
        return True
    finally:
        conn.close()


def show_summary(db_path: Path) -> None:
    conn = sqlite3.connect(db_path)
    try:
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM category_v3")
        total = c.fetchone()[0]
        c.execute("SELECT COUNT(DISTINCT l1) FROM category_v3")
        l1_n = c.fetchone()[0]
        c.execute("SELECT COUNT(DISTINCT l2) FROM category_v3")
        l2_n = c.fetchone()[0]
        c.execute("SELECT COUNT(DISTINCT l3) FROM category_v3")
        l3_n = c.fetchone()[0]
        print(f"\n=== 库概要 ({db_path.name}) ===")
        print(f"  category_v3: {total} 行 / L1={l1_n} / L2={l2_n} / L3={l3_n}")

        c.execute("SELECT l1, l2, l3, name_l3, gb_50500, ifc_class FROM category_v3 ORDER BY l1, l2, l3 LIMIT 5")
        print(f"\n=== 样本（前 5 行）===")
        for row in c.fetchall():
            print(f"  {row[0]} > {row[1]} > {row[2]} | {row[3]:18s} | {row[4]} | {row[5]}")
    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser(description="初始化 v3 分类规则库")
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH), help="数据库路径")
    parser.add_argument("--reset", action="store_true", help="删除旧库重建")
    parser.add_argument("--import", dest="do_import", action="store_true", help="只导入数据")
    args = parser.parse_args()

    db_path = Path(args.db)

    if args.do_import:
        if not db_path.exists():
            print(f"[err] 库不存在: {db_path}", file=sys.stderr)
            sys.exit(1)
        import_category_nodes(db_path)
    else:
        init_db(db_path, reset=args.reset)
        import_category_nodes(db_path)

    verify_consistency(db_path)
    show_summary(db_path)


if __name__ == "__main__":
    main()
