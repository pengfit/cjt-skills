#!/usr/bin/env python3
"""一次性把 ODS 全部品种加入 breed_l3_map_v3

现有机制: 只 fallback_v3 (本地规则都不命中) 的品种才入库
          pattern_v3 / db_exact_v3 / db_fuzzy_v3 命中的不入库
本脚本: 把所有品种都过一遍 classify_v3, 全部入库

用法:
  cd ~/.openclaw/workspace/skills/gov-price-etl
  python3 scripts/seed_breed_l3_map.py [--city qingdao] [--index ods_material_qingdao_price]
"""
import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from elasticsearch import Elasticsearch
from elasticsearch import helpers
import sqlite3

from gov_price_etl.classify import classify_v3
from gov_price_etl.classify.category_v3 import close_singleton
from gov_price_etl.paths import PROJECT_ROOT

ES_HOST = 'http://localhost:59200'
DB_PATH = str(PROJECT_ROOT / 'data' / 'category_v3_rules.db')


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--city', default='qingdao', help='城市 key（决定 index 名）')
    p.add_argument('--es', default=ES_HOST)
    p.add_argument('--db', default=DB_PATH)
    p.add_argument('--dry-run', action='store_true', help='只统计不入库')
    args = p.parse_args()

    index = f'ods_material_{args.city}_price'
    es = Elasticsearch(args.es, request_timeout=30)

    # 1) ODS 全部唯一 breed
    print(f'扫 {index}...')
    breeds = set()
    items_per_breed = {}
    for d in helpers.scan(es, index=index):
        b = d['_source'].get('breed', '').strip()
        if b:
            breeds.add(b)
            items_per_breed[b] = items_per_breed.get(b, 0) + 1
    print(f'ODS 唯一 breed: {len(breeds)} (总 items {sum(items_per_breed.values())})')

    # 2) 已入库
    conn = sqlite3.connect(args.db)
    cur = conn.cursor()
    existing = {r[0]: r for r in cur.execute(
        'SELECT breed_clean, l3, source, confidence FROM breed_l3_map_v3')}
    print(f'已入库: {len(existing)}')

    # 3) 逐个分类 + 入库
    insert_count = 0
    update_count = 0
    skip_count = 0
    for breed in sorted(breeds):
        v2 = classify_v3(breed, spec='', unit='', breed_clean=breed)
        l3 = v2.get('l3', '') or '其他'
        source = v2.get('category_v2_source', 'no_match')
        conf = v2.get('category_v2_confidence', 0.0)

        # 优先: Dify 跑过的 (ai_v3) 比 pattern_v3 更准; 但若 ai_v3 是'其他'占位, 仍写新的
        # 这里仅用 classify_v3 单条结果, 重新分类, 会覆盖之前 Dify 的结果
        # 为安全: 只在 DB 已有但 l3='其他' / source=ai_fallback_v3 时才覆盖

        if breed in existing:
            old_l3, old_src, old_conf = existing[breed][1], existing[breed][2], existing[breed][3]
            # 已有真 L3 (非'其他') 就跳过
            if old_l3 and old_l3 != '其他' and old_src != 'ai_fallback_v3':
                skip_count += 1
                continue
            # 否则 (l3='其他' 或 source=ai_fallback) 用新结果更新
            if args.dry_run:
                update_count += 1
                continue
            cur.execute('''UPDATE breed_l3_map_v3
                          SET l3=?, source=?, confidence=?, updated_at=datetime('now','localtime')
                          WHERE breed_clean=?''',
                       (l3, source, conf, breed))
            update_count += 1
        else:
            if args.dry_run:
                insert_count += 1
                continue
            cur.execute('''INSERT INTO breed_l3_map_v3
                          (breed_clean, l3, source, confidence)
                          VALUES (?, ?, ?, ?)''',
                       (breed, l3, source, conf))
            insert_count += 1

    if not args.dry_run:
        conn.commit()
    conn.close()
    close_singleton()

    print(f'\n=== 结果 ({args.city}) ===')
    print(f'  新增: {insert_count}')
    print(f'  更新: {update_count}')
    print(f'  跳过 (已有真 L3): {skip_count}')
    if args.dry_run:
        print('  [DRY-RUN] 未写入 DB')


if __name__ == '__main__':
    main()
