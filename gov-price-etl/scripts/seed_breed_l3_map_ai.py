#!/usr/bin/env python3
"""简易 AI 批量分类：ODS breed → Dify → 入库 breed_l3_map_v3
"""
import argparse
import json
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

import requests
import sqlite3

print('import 1 OK', flush=True)
from gov_price_etl.classify.utils import format_breed_list
from gov_price_etl.transform.clean import clean_breed
print('import 2 OK', flush=True)

ES_HOST = 'http://localhost:59200'
DB_PATH = str(PROJECT_ROOT / 'data' / 'category_v3_rules.db')
BATCH_SIZE = 10


def _get_unique_breeds(es_host: str, index: str) -> dict:
    session = requests.Session()
    resp = session.post(f'{es_host}/{index}/_search', json={
        'size': 0,
        'aggs': {'breeds': {'terms': {'field': 'breed.keyword', 'size': 500}}},
    }, timeout=30)
    if resp.status_code != 200:
        print(f'ES 查询失败: {resp.text[:200]}')
        return {}
    data = resp.json()
    buckets = data.get('aggregations', {}).get('breeds', {}).get('buckets', [])
    return {b['key']: b['doc_count'] for b in buckets}


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--city', default='qingdao')
    p.add_argument('--es', default=ES_HOST)
    p.add_argument('--db', default=DB_PATH)
    p.add_argument('--dry-run', action='store_true')
    args = p.parse_args()

    index = f'ods_material_{args.city}_price'
    print(f'扫 {index}...', flush=True)
    breeds = _get_unique_breeds(args.es, index)
    print(f'ODS 唯一 breed: {len(breeds)} (total items {sum(breeds.values())})', flush=True)

    conn = sqlite3.connect(args.db)
    cur = conn.cursor()
    existing = {r[0] for r in cur.execute('SELECT breed_clean FROM breed_l3_map_v3')}
    breeds_to_classify = {b: c for b, c in breeds.items() if b not in existing}
    print(f'已入库: {len(existing)}, 待分类: {len(breeds_to_classify)}', flush=True)
    if not breeds_to_classify:
        print('所有 breed 已入库', flush=True)
        return

    items = [{'breed': b, 'breed_clean': clean_breed(b), 'spec': '', 'unit': ''}
             for b in sorted(breeds_to_classify)]
    print(f'\n送 Dify 分类 ({len(items)} 个 breed)...', flush=True)

    # 延迟导入（避免挂起）
    print('导入 _ai_invoke...', flush=True)
    from gov_price_etl.ai.service import _ai_invoke
    print('导入完成', flush=True)

    t0 = time.time()
    results = {}
    total_batches = len(items) // BATCH_SIZE + (1 if len(items) % BATCH_SIZE else 0)

    for batch_start in range(0, len(items), BATCH_SIZE):
        batch = items[batch_start:batch_start + BATCH_SIZE]
        breed_list_str = format_breed_list(batch)
        batch_no = batch_start // BATCH_SIZE + 1

        print(f'  批次 {batch_no}/{total_batches}...', flush=True)
        ok, content = _ai_invoke(
            "classify",
            dify_inputs={"breed_list": breed_list_str, "batch_n": len(batch)},
            user=f"seed-{int(time.time()*1000)}",
            timeout=120,
        )
        if not ok:
            print(f'    失败 → fallback')
            for it in batch:
                results[it['breed_clean']] = {"l3": "其他", "source": "ai_fallback_v3", "confidence": 0.0}
            continue

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

        ai_map = {}
        if isinstance(results_raw, list):
            for r in results_raw:
                bc = r.get("breed_clean", "")
                if bc:
                    ai_map[bc] = r
        elif isinstance(results_raw, dict):
            ai_map = results_raw

        for it in batch:
            bc = it['breed_clean']
            r = ai_map.get(bc, {})
            l3 = r.get("l3", "")
            if l3 and l3 != "其他":
                results[bc] = {"l3": l3, "source": "ai_v3", "confidence": float(r.get("confidence", 0.85) or 0.85)}
            else:
                results[bc] = {"l3": "其他", "source": "ai_fallback_v3", "confidence": 0.0}

        print(f'    完成, {time.time()-t0:.1f}s', flush=True)

    elapsed = time.time() - t0
    print(f'Dify 调用总耗时: {elapsed:.1f}s', flush=True)

    ok_count = sum(1 for v in results.values() if v['source'] == 'ai_v3')
    fail_count = sum(1 for v in results.values() if v['source'] == 'ai_fallback_v3')
    print(f'  AI 成功: {ok_count}, 失败: {fail_count}', flush=True)
    if fail_count > 0:
        fails = [bc for bc, v in results.items() if v['source'] == 'ai_fallback_v3']
        print(f'  失败 breed: {", ".join(fails)}', flush=True)

    insert_count = 0
    for bc, v in sorted(results.items()):
        if bc in existing or v['source'] != 'ai_v3':
            continue
        if args.dry_run:
            insert_count += 1
            continue
        cur.execute(
            'INSERT OR REPLACE INTO breed_l3_map_v3 (breed_clean, l3, source, confidence) VALUES (?, ?, ?, ?)',
            (bc, v['l3'], v['source'], v['confidence']))
        insert_count += 1

    if not args.dry_run:
        conn.commit()
    conn.close()

    print(f'\n=== 结果 ({args.city}) ===')
    print(f'  新增: {insert_count}')
    if args.dry_run:
        print('  [DRY-RUN] 未写入 DB')


if __name__ == '__main__':
    main()
