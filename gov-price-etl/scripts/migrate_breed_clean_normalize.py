#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
migrate_breed_clean_normalize.py

将 breed_l3_map_v3 表中所有 breed_clean 跑一遍新的 clean_breed(全角括号→半角、Mpa→MPa)
使 DB 规则与 ODS 清洗后的字符串保持一致。

2026-06-30 配套改动：
- clean_breed 增强：全角括号→半角、Mpa→MPa
- DB 中旧规则（约 849 条 = 12.8%）需要同步归一化

策略：
1. 读所有 (old_bc, l3, source, confidence) 行
2. 对 old_bc 应用 clean_breed → new_bc
3. 处理碰撞（多 old → 同一 new）：
   - 优先保留 manual_v3.x（人工已 review）
   - 同 source 时取 confidence 最高
4. 写新表，原子替换

回滚：data/category_v3_rules.db.bak.YYYYMMDD_HHMMSS
"""

import sqlite3
import shutil
import sys
import time
from collections import defaultdict
from pathlib import Path

# 项目根
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
DB_PATH = PROJECT_ROOT / "data" / "category_v3_rules.db"

# clean_breed 来自项目
sys.path.insert(0, str(PROJECT_ROOT))
from gov_price_etl.transform.clean import clean_breed


# 优先级：manual > ai（同 L3 碰撞时优先人工）
SOURCE_PRIORITY = {
    "manual_v3.6": 100,
    "manual_v3.5": 100,
    "manual_v3.4": 100,
    "manual_v3.3": 100,
    "ai_v3": 50,
}


def main():
    # 0. 备份
    bak = DB_PATH.with_suffix(f".db.bak.{time.strftime('%Y%m%d_%H%M%S')}")
    shutil.copy2(DB_PATH, bak)
    print(f"[1/5] 备份 → {bak.name}")

    conn = sqlite3.connect(str(DB_PATH))
    c = conn.cursor()

    # 1. 读所有规则
    rows = c.execute("""
      SELECT breed_clean, l3, source, confidence, created_at, updated_at
      FROM breed_l3_map_v3
    """).fetchall()
    print(f"[2/5] 读 {len(rows)} 条规则")

    # 2. 归一化 + 碰撞处理
    # 规则: 同 new_bc 出现多次时:
    #   1) 同 l3 → 取 source 优先级最高(manual > ai)
    #   2) 不同 l3 → 保留最高优先级，丢弃其他
    new_rules = {}  # new_bc -> best row tuple
    drop_count = 0
    change_count = 0

    for old_bc, l3, source, conf, created_at, updated_at in rows:
        new_bc = clean_breed(old_bc)
        if new_bc != old_bc:
            change_count += 1
        key = new_bc
        cand = (new_bc, l3, source, conf, created_at, updated_at)
        if key not in new_rules:
            new_rules[key] = cand
        else:
            # 碰撞：取 priority 高的
            old_row = new_rules[key]
            old_pri = SOURCE_PRIORITY.get(old_row[2], 0)
            new_pri = SOURCE_PRIORITY.get(source, 0)
            if new_pri > old_pri:
                drop_count += 1
                new_rules[key] = cand
            elif new_pri == old_pri:
                # 同优先级: 保留 confidence 高的
                if conf > old_row[3]:
                    drop_count += 1
                    new_rules[key] = cand
                else:
                    drop_count += 1
            else:
                drop_count += 1

    print(f"[3/5] 归一化: {change_count} 条变化, {drop_count} 条因碰撞丢弃")
    print(f"      新规则数: {len(new_rules)} (原 {len(rows)})")

    # 3. 写新表
    new_table = "breed_l3_map_v3_new"
    c.execute(f"DROP TABLE IF EXISTS {new_table}")
    c.execute(f"""
      CREATE TABLE {new_table} (
        breed_clean TEXT PRIMARY KEY,
        l3 TEXT NOT NULL,
        source TEXT,
        confidence REAL DEFAULT 1.0,
        created_at TEXT DEFAULT (datetime('now','localtime')),
        updated_at TEXT DEFAULT (datetime('now','localtime'))
      )
    """)
    c.execute(f"CREATE INDEX idx_{new_table}_l3 ON {new_table}(l3)")

    c.executemany(f"""
      INSERT INTO {new_table}
      (breed_clean, l3, source, confidence, created_at, updated_at)
      VALUES (?, ?, ?, ?, ?, ?)
    """, new_rules.values())

    # 4. 原子替换
    c.execute("DROP TABLE breed_l3_map_v3")
    c.execute(f"ALTER TABLE {new_table} RENAME TO breed_l3_map_v3")
    # 重建索引
    c.execute("CREATE INDEX IF NOT EXISTS idx_breed_v3_l3 ON breed_l3_map_v3(l3)")
    conn.commit()
    conn.close()

    # 5. 验证
    conn = sqlite3.connect(str(DB_PATH))
    c = conn.cursor()
    n = c.execute("SELECT COUNT(*) FROM breed_l3_map_v3").fetchone()[0]
    print(f"[5/5] 完成,新表行数: {n}")
    print(f"\n回滚命令: cp {bak} {DB_PATH}")


if __name__ == "__main__":
    main()
