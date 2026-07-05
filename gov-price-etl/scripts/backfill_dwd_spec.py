#!/usr/bin/env python3
"""回填 DWD 索引的 spec 字段——应用 clean_spec 去空格污染。

只对 spec 字段做 update，不动 attr / 分类 / 业务字段。跑完后 DWS 阶段 2/3
会重新基于干净 spec 走本地规则库 + AI。

用法:
    ./scripts/backfill_dwd_spec.py --city huhehaote
    ./scripts/backfill_dwd_spec.py --city huhehaote --dry-run
    ./scripts/backfill_dwd_spec.py --index dwd_heze_price
"""
import argparse
import sys
from elasticsearch import Elasticsearch, helpers

# 兼容包内调用
sys.path.insert(0, '.')
from gov_price_etl.transform.clean import clean_spec


def scan_and_collect(es, index):
    """扫描索引中所有 spec 字段，统计有多少会变化。"""
    total = es.count(index=index)['count']
    changes = []
    query = {"query": {"exists": {"field": "spec"}}, "_source": ["spec"]}
    for h in helpers.scan(es, index=index, query=query, size=1000):
        old = h['_source'].get('spec', '') or ''
        new = clean_spec(old)
        if new != old:
            changes.append((h['_id'], old, new))
    return total, changes


def bulk_update(es, index, changes, dry_run=False):
    """按 _id 批量 update spec 字段。"""
    if dry_run:
        return 0
    actions = []
    for _id, _old, new in changes:
        actions.append({
            "_op_type": "update",
            "_index": index,
            "_id": _id,
            "doc": {"spec": new},
        })
    success, errors = helpers.bulk(es, actions, refresh=False, raise_on_error=False)
    return success


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--city', help='CITY_CONFIGS 里的城市 key（如 huhehaote）')
    ap.add_argument('--index', help='DWD 索引名（与 --city 二选一）')
    ap.add_argument('--es-host', default='http://localhost:59200')
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()

    if not args.city and not args.index:
        ap.error('--city 或 --index 二选一')

    if args.city and not args.index:
        from gov_price_etl.config import CITY_CONFIGS
        cfg = CITY_CONFIGS.get(args.city)
        if not cfg:
            sys.exit(f'城市 {args.city!r} 不在 CITY_CONFIGS')
        index = cfg['dwd']
    else:
        index = args.index

    es = Elasticsearch([args.es_host])
    print(f'索引: {index}')
    print(f'ES:   {args.es_host}')
    print(f'模式: {"DRY-RUN" if args.dry_run else "UPDATE"}')

    total, changes = scan_and_collect(es, index)
    print(f'\n扫描结果: 总 {total} 条, 需更新 {len(changes)} 条')

    if not changes:
        print('无需更新。')
        return

    print('\n样本（前 10 条）:')
    for _id, old, new in changes[:10]:
        print(f'  {repr(old):<45s} -> {repr(new)}')

    updated = bulk_update(es, index, changes, dry_run=args.dry_run)
    es.indices.refresh(index=index)
    print(f'\n{"模拟 " if args.dry_run else ""}更新完成: {updated} 条')


if __name__ == '__main__':
    main()
