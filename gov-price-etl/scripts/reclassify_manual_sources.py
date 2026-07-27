#!/usr/bin/env python3
"""reclassify_manual_sources.py

将 breed_l3_map_v3 中 source LIKE 'manual_fix_%' OR 'manual_l3_%' OR 'local_%' 的记录
通过 Dify etl-classify-category 重新分类,UPDATE l3/source/confidence。

参考 etl 中 _ai_invoke → _call_dify_workflow("etl-classify-category", ...) 的调用模式,
但走 UPDATE 路径(而非 INSERT OR IGNORE),精准替换原行的 l3。

用法:
  python3 scripts/reclassify_manual_sources.py            # 实际执行
  python3 scripts/reclassify_manual_sources.py --dry-run  # 只看不写
"""
import sys
import sqlite3
import time
from pathlib import Path

# 路径
ETL_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ETL_ROOT))
DB_PATH = Path('/Users/pengfit/.openclaw/workspace/cjt/skills/data/category_v3_rules.db')

# 2026-07-27:gov-price-etl/dify/dify.config.local.json 含 base_url + apps.api_key
from gov_price_etl.ai.service import classify_v3_batch


def main():
    dry_run = '--dry-run' in sys.argv
    if dry_run:
        print('=== DRY RUN 模式(不写库)===\n')

    if not DB_PATH.exists():
        print(f'❌ DB 不存在: {DB_PATH}')
        return 1

    con = sqlite3.connect(str(DB_PATH))
    con.row_factory = sqlite3.Row

    # 1. 取要重分类的记录
    records = con.execute("""
        SELECT breed_clean, l3 AS old_l3, source, confidence
        FROM breed_l3_map_v3
        WHERE source LIKE 'manual_fix_%'
           OR source LIKE 'manual_l3_%'
           OR source LIKE 'local_%'
        ORDER BY breed_clean
    """).fetchall()

    # 测试模式:只处理前 N 条
    limit = None
    for arg in sys.argv[1:]:
        if arg.startswith('--limit='):
            limit = int(arg.split('=', 1)[1])
    if limit and limit < len(records):
        print(f'  --limit={limit}: 只处理前 {limit} 条(剩 {len(records)-limit} 条跳过)')
        records = records[:limit]

    print(f'=== 找到 {len(records)} 条待重分类 ===')
    if records:
        print(f'  示例 5 条:')
        for r in records[:5]:
            print(f'    {r["breed_clean"][:30]:30s}  l3={r["old_l3"]:10s}  src={r["source"]}  conf={r["confidence"]}')

    if not records:
        return 0

    # 2. 准备 batch items
    items = [
        {'breed_clean': r['breed_clean'], 'breed': r['breed_clean'], 'spec': '', 'unit': ''}
        for r in records
    ]

    # 3. 调 Dify(参考 ai/service.py:209 alias="etl-classify-category")
    print(f'\n=== 调 Dify classify_v3_batch({len(items)} 条)===')
    t0 = time.time()
    # write_rules=False: 走返回结果但不直接 INSERT 到 breed_l3_map_v3
    # (我们要自己 UPDATE 现有行,不要让 classify_v3_batch 重复 INSERT)
    results = classify_v3_batch(items, write_rules=False)
    dt = time.time() - t0
    print(f'  返回 {len(results)} 条, 耗时 {dt:.1f}s')

    # 4. UPDATE l3 / source / confidence
    print(f'\n=== 处理结果 ===')
    updated = 0
    l3_changed = 0
    skipped_no_l3 = 0
    protected_by_source = 0
    failed_no_result = 0

    for r in records:
        bc = r['breed_clean']
        old_l3 = r['old_l3']

        v2 = results.get(bc)
        if not v2:
            failed_no_result += 1
            continue
        if not v2.get('l3'):
            skipped_no_l3 += 1
            continue

        new_l3 = v2['l3']
        new_conf = v2.get('category_v2_confidence', 0.95)
        if new_conf < 0.95:
            new_conf = 0.95  # 与 ai/service.py:804 同样的兜底

        changed = (new_l3 != old_l3)
        if changed:
            l3_changed += 1
        updated += 1

        if not dry_run:
            con.execute("""
                UPDATE breed_l3_map_v3
                SET l3=?, source='ai_v3', confidence=?, updated_at=datetime('now')
                WHERE breed_clean=?
            """, (new_l3, new_conf, bc))

    if not dry_run:
        con.commit()
    con.close()

    print(f'  更新行数:  {updated} 条')
    print(f'    其中 l3 改变: {l3_changed} 条')
    print(f'  Dify 无返回:  {failed_no_result} 条(原始 l3 保留)')
    print(f'  Dify 返 l3=空:  {skipped_no_l3} 条(原始 l3 保留)')
    if dry_run:
        print(f'\n  DRY RUN — 未写库')
    else:
        print(f'\n  ✓ 已写库')

    return 0


if __name__ == '__main__':
    sys.exit(main())
