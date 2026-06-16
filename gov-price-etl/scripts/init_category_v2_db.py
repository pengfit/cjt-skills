#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
init_category_v2_db.py - 初始化 v2 分类规则库 SQLite

库路径（默认）：data/category_v2_rules.db
    - 与现有 breed_category_rules.db 平行
    - 不冲突，按版本号区分

库结构（两张表）：

1. category_v2  —— 4 层分类全量节点
   - 主键: (l1, l2, l3, l4)
   - 字段: l1, l2, l3, l4, gb_50500, quota_ref, ifc_class, uniclass_ss,
          eng_part, eng_stage, main_or_aux, unit, billing_unit, cost_method,
          name_l1, name_l2, name_l3, name_l4
   - 数据来源: data/category_v2.json + data/std_codes.json

2. breed_l3_map  —— breed → L3 映射（v2 专用）
   - 主键: breed_clean TEXT
   - 字段: l3, source, confidence, created_at
   - source 取值: 'manual' / 'ai' / 'jaccard'
   - 数据来源: 阶段 1/2/3 命中（v1 db_exact / db_fuzzy / 规则匹配）+ 阶段 3 AI 输出

用法:
    python3 scripts/init_category_v2_db.py            # 默认初始化
    python3 scripts/init_category_v2_db.py --reset    # 删除旧库重建
    python3 scripts/init_category_v2_db.py --import  # 只导入数据（库已存在）
"""

import argparse
import json
import sqlite3
import sys
from pathlib import Path


# ── 路径配置（与现有 ETL 保持一致风格） ─────────────────────────────
SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent
DATA_DIR = PROJECT_ROOT / "data"
DEFAULT_DB_PATH = DATA_DIR / "category_v2_rules.db"
CATEGORY_V2_JSON = DATA_DIR / "category_v2.json"
STD_CODES_JSON = DATA_DIR / "std_codes.json"


# ── Schema ───────────────────────────────────────────────────────────
SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS category_v2 (
    l1           TEXT NOT NULL,
    l2           TEXT NOT NULL,
    l3           TEXT NOT NULL,
    l4           TEXT NOT NULL,         -- L4 细目；MVP 阶段 L4 暂为 "UNCLASSIFIED" 兜底
    gb_50500     TEXT,
    quota_ref    TEXT,
    ifc_class    TEXT,
    uniclass_ss  TEXT,
    eng_part     TEXT,
    eng_stage    TEXT,                  -- 逗号分隔多阶段："设计,施工,运维"
    main_or_aux  TEXT,
    unit         TEXT,
    billing_unit TEXT,
    cost_method  TEXT,
    name_l1      TEXT,
    name_l2      TEXT,
    name_l3      TEXT,
    name_l4      TEXT,
    PRIMARY KEY (l1, l2, l3, l4)
);

CREATE INDEX IF NOT EXISTS idx_v2_l1     ON category_v2(l1);
CREATE INDEX IF NOT EXISTS idx_v2_l2     ON category_v2(l1, l2);
CREATE INDEX IF NOT EXISTS idx_v2_l3     ON category_v2(l1, l2, l3);
CREATE INDEX IF NOT EXISTS idx_v2_gb     ON category_v2(gb_50500);
CREATE INDEX IF NOT EXISTS idx_v2_ifc    ON category_v2(ifc_class);

CREATE TABLE IF NOT EXISTS breed_l3_map (
    breed_clean TEXT PRIMARY KEY,
    l3          TEXT NOT NULL,
    source      TEXT,                   -- 'manual' / 'ai' / 'jaccard'
    confidence  REAL DEFAULT 1.0,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_breed_l3 ON breed_l3_map(l3);
"""


def init_db(db_path: Path, reset: bool = False) -> None:
    """初始化/重建库"""
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
    """
    从 category_v2.json + std_codes.json 导入 4 层分类节点到 category_v2 表。
    L4 阶段 MVP 暂用 "UNCLASSIFIED" 兜底。
    返回写入行数。
    """
    cat_v2 = json.loads(CATEGORY_V2_JSON.read_text(encoding="utf-8"))
    std_codes = json.loads(STD_CODES_JSON.read_text(encoding="utf-8"))["codes"]

    rows = []
    for l1_node in cat_v2["tree"]["l1"]:
        l1 = l1_node["code"]
        name_l1 = l1_node["name"]
        for l2_node in l1_node["l2"]:
            l2 = l2_node["code"]
            name_l2 = l2_node["name"]
            for l3_node in l2_node["l3"]:
                l3 = l3_node["code"]
                name_l3 = l3_node["name"]
                std = std_codes.get(l3, {})
                rows.append((
                    l1, l2, l3, "UNCLASSIFIED",
                    std.get("gb_50500"),
                    std.get("quota_ref"),
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
        # 全量重建：先清空 category_v2 表（不影响 breed_l3_map）
        conn.execute("DELETE FROM category_v2")
        conn.executemany(
            """INSERT OR REPLACE INTO category_v2
               (l1, l2, l3, l4, gb_50500, quota_ref, ifc_class, uniclass_ss,
                eng_part, eng_stage, main_or_aux, unit, billing_unit, cost_method,
                name_l1, name_l2, name_l3, name_l4)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            rows,
        )
        conn.commit()
        print(f"[import] category_v2: {len(rows)} 行")
        return len(rows)
    finally:
        conn.close()


def show_summary(db_path: Path) -> None:
    """打印库概要（验证导入）"""
    conn = sqlite3.connect(db_path)
    try:
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM category_v2")
        total = c.fetchone()[0]
        c.execute("SELECT COUNT(DISTINCT l1) FROM category_v2")
        l1_n = c.fetchone()[0]
        c.execute("SELECT COUNT(DISTINCT l2) FROM category_v2")
        l2_n = c.fetchone()[0]
        c.execute("SELECT COUNT(DISTINCT l3) FROM category_v2")
        l3_n = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM breed_l3_map")
        breed_n = c.fetchone()[0]
        print(f"\n=== 库概要 ({db_path.name}) ===")
        print(f"  category_v2: {total} 行 / L1={l1_n} / L2={l2_n} / L3={l3_n}")
        print(f"  breed_l3_map: {breed_n} 行")

        # 抽 5 个样本
        c.execute("SELECT l1, l2, l3, l4, name_l3, gb_50500, ifc_class FROM category_v2 LIMIT 5")
        print(f"\n=== 样本（前 5 行）===")
        for row in c.fetchall():
            print(f"  {row[0]} > {row[1]} > {row[2]} > {row[3]:15s} | {row[4]:15s} | {row[5]} | {row[6]}")
    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser(description="初始化 v2 分类规则库")
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH), help="数据库路径")
    parser.add_argument("--reset", action="store_true", help="删除旧库重建")
    parser.add_argument("--import", dest="do_import", action="store_true", help="只导入数据（库已存在）")
    args = parser.parse_args()

    db_path = Path(args.db)

    if args.do_import:
        if not db_path.exists():
            print(f"[err] 库不存在: {db_path}，先跑不带 --import 初始化", file=sys.stderr)
            sys.exit(1)
        import_category_nodes(db_path)
    else:
        init_db(db_path, reset=args.reset)
        import_category_nodes(db_path)

    show_summary(db_path)


if __name__ == "__main__":
    main()
