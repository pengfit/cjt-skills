#!/usr/bin/env python3
"""一次性把 ODS 全部品种入 breed_l3_map_v3, 全部走 AI (Dify) 分类

不依赖本地 pattern/db_exact/db_fuzzy 规则 — 所有 breed 都送 Dify,
回包 source='ai_v3' (成功) 或 'ai_fallback_v3' (Dify 失败).

用法:
  python3 scripts/seed_breed_l3_map_ai.py --city qingdao [--dry-run]
  python3 scripts/seed_breed_l3_map_ai.py --city sichuan
"""
import argparse
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from elasticsearch import Elasticsearch
from elasticsearch import helpers
import sqlite3

from gov_price_etl.ai.service import (
    _ai_invoke, _load_taxonomy_for_prompt, find_top_l3_for_prompt,
)
from gov_price_etl.classify.utils import format_breed_list
from gov_price_etl.paths import PROJECT_ROOT

ES_HOST = 'http://localhost:59200'
DB_PATH = str(PROJECT_ROOT / 'data' / 'category_v3_rules.db')
BATCH_SIZE = 10  # 与 ETL 一致


def ai_classify_batch(items: list, city: str = '') -> dict:
    """直接送 Dify, 跳过本地规则. items: [{breed, breed_clean, spec, unit}, ...]
    返回 {breed_clean: {l3, source, confidence}}"""
    results = {}
    if not items:
        return results

    # 攒批
    for batch_start in range(0, len(items), BATCH_SIZE):
        batch = items[batch_start:batch_start + BATCH_SIZE]
        # 算 top-K L3 候选
        _batch_breeds = list({(it.get("breed",""), it.get("spec","")): None for it in batch}.keys())
        _top_set = set()
        for _b, _s in _batch_breeds:
            for _t in find_top_l3_for_prompt(_b, _s, top_k=10):
                _top_set.add((_t['l1'], _t['l2'], _t['l3']))
        _taxonomy = _load_taxonomy_for_prompt()
        l3_list_str = "\n".join(
            f"  {t['l3']}  {t['name_l1']}/{t['name_l2']}/{t['name_l3']}"
            for t in _taxonomy if (t['l1'], t['l2'], t['l3']) in _top_set
        )

        breed_list_str = format_breed_list(batch)
        ok, content = _ai_invoke(
            "classify",
            dify_inputs={
                "breed_list": breed_list_str,
                "batch_n": len(batch),
                "total_l3": len(_taxonomy),
                "candidate_l3": l3_list_str,
            },
            user=f"seed-script-{int(time.time()*1000)}",
            timeout=90,
        )

        if not ok:
            # Dify 失败 → 全部 fallback
            for it in batch:
                bc = it.get("breed_clean", "")
                results[bc] = {
                    "l3": "其他",
                    "source": "ai_fallback_v3",
                    "confidence": 0.0,
                }
            continue

        # 解析响应
        import json
        try:
            parsed = json.loads(content)
            if isinstance(parsed, dict):
                results_raw = parsed.get("results", [])
            elif isinstance(parsed, list):
                results_raw = parsed
            else:
                results_raw = []
        except Exception:
            results_raw = []

        # results_raw 可能是 list[dict] 或 dict[bc->dict]
        ai_map = {}
        if isinstance(results_raw, list):
            for r in results_raw:
                bc = r.get("breed_clean", "")
                if bc:
                    ai_map[bc] = r
        elif isinstance(results_raw, dict):
            ai_map = results_raw

        for it in batch:
            bc = it.get("breed_clean", "")
            r = ai_map.get(bc, {})
            l3 = r.get("l3", "")
            if l3 and l3 != "其他":
                results[bc] = {
                    "l3": l3,
                    "source": "ai_v3",
                    "confidence": float(r.get("confidence", 0.7) or 0.7),
                }
            else:
                # AI 返回空 l3 → fallback
                results[bc] = {
                    "l3": "其他",
                    "source": "ai_fallback_v3",
                    "confidence": 0.0,
                }

    return results


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

    # 2) 已有
    conn = sqlite3.connect(args.db)
    cur = conn.cursor()
    existing = {r[0]: r for r in cur.execute(
        'SELECT breed_clean, l3, source, confidence FROM breed_l3_map_v3')}
    print(f'已入库: {len(existing)}')

    # 3) 构造 items
    items = []
    for b in breeds:
        items.append({
            'breed': b,
            'breed_clean': b,
            'spec': '',
            'unit': '',
        })

    # 4) 全部送 Dify
    print(f'\n送 Dify 分类 (共 {len(items)} 个 breed)...')
    t0 = time.time()
    ai_results = ai_classify_batch(items, city=args.city)
    elapsed = time.time() - t0
    print(f'Dify 调用总耗时: {elapsed:.1f}s')

    # 5) 写库
    insert_count = 0
    update_count = 0
    skip_count = 0
    for bc, v in sorted(ai_results.items()):
        l3 = v['l3']
        source = v['source']
        conf = v['confidence']

        if bc in existing:
            old_l3, old_src, old_conf = existing[bc][1], existing[bc][2], existing[bc][3]
            # 已是 ai_v3 且 L3 一致 → 跳过
            if old_src == 'ai_v3' and old_l3 == l3 and abs(old_conf - conf) < 0.01:
                skip_count += 1
                continue
            # 否则更新
            if args.dry_run:
                update_count += 1
                continue
            cur.execute('''UPDATE breed_l3_map_v3
                          SET l3=?, source=?, confidence=?, updated_at=datetime('now','localtime')
                          WHERE breed_clean=?''',
                       (l3, source, conf, bc))
            update_count += 1
        else:
            if args.dry_run:
                insert_count += 1
                continue
            cur.execute('''INSERT INTO breed_l3_map_v3
                          (breed_clean, l3, source, confidence)
                          VALUES (?, ?, ?, ?)''',
                       (bc, l3, source, conf))
            insert_count += 1

    if not args.dry_run:
        conn.commit()
    conn.close()

    print(f'\n=== 结果 ({args.city}) ===')
    print(f'  新增: {insert_count}')
    print(f'  更新: {update_count}')
    print(f'  跳过: {skip_count}')
    if args.dry_run:
        print('  [DRY-RUN] 未写入 DB')


if __name__ == '__main__':
    main()
