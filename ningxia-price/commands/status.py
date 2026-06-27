"""查看宁夏同步进度（本地 JSON + ES 进度索引）"""
import json
import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

from utils import load_config, get_es_client, get_s3_client

PROGRESS_FILE = os.path.join(os.path.dirname(SCRIPT_DIR), '.ningxia_sync_progress.json')


def main():
    cfg = load_config()
    es = get_es_client(cfg['es']['host'])

    print('=== 本地进度 ===')
    if not os.path.exists(PROGRESS_FILE):
        print('  (空)')
    else:
        with open(PROGRESS_FILE) as f:
            prog = json.load(f)
        done = prog.get('done', {})
        print(f'  总数: {len(done)}')
        ok = sum(1 for v in done.values() if v.get('status') == 'ok')
        fail = sum(1 for v in done.values() if v.get('status') == 'failed')
        partial = sum(1 for v in done.values() if v.get('status') == 'partial')
        print(f'  ok: {ok}  partial: {partial}  failed: {fail}')
        for k, v in done.items():
            print(f"    [{v.get('status','?'):8s}] {v.get('period','?'):15s} docs={v.get('docs_written',0):5d}  {v.get('minio_key','')[:60]}")

    print('\n=== ES ODS ===')
    try:
        cnt = es.count(index=cfg['es']['ods_index'])['count']
        print(f'  {cfg["es"]["ods_index"]}: {cnt:,} 条')
        if cnt:
            r = es.search(
                index=cfg['es']['ods_index'],
                size=0,
                aggs={
                    'by_period':   {'terms': {'field': 'period', 'size': 20, 'order': {'_key': 'desc'}}},
                    'by_section':  {'terms': {'field': 'section.keyword', 'size': 30}},
                    'by_city':     {'terms': {'field': 'city', 'size': 30}},
                    'by_category': {'terms': {'field': 'category', 'size': 10}},
                },
            )
            print('  各周期:')
            for b in r['aggregations']['by_period']['buckets']:
                print(f'    {b["key"]:15s} {b["doc_count"]:,}')
            print('  章节(TOP 30):')
            for b in r['aggregations']['by_section']['buckets']:
                print(f'    {b["key"]:30s} {b["doc_count"]:,}')
            print('  城市(TOP 30):')
            for b in r['aggregations']['by_city']['buckets'][:30]:
                print(f'    {b["key"]:15s} {b["doc_count"]:,}')
            print('  大类:')
            for b in r['aggregations']['by_category']['buckets']:
                print(f'    {b["key"]:15s} {b["doc_count"]:,}')
    except Exception as e:
        print(f'  ✗ {e}')

    print('\n=== MinIO ===')
    try:
        s3 = get_s3_client(cfg)
        from utils import ensure_bucket
        ensure_bucket(s3, cfg['minio']['bucket'])
        prefix = cfg['minio']['prefix']
        resp = s3.list_objects_v2(Bucket=cfg['minio']['bucket'], Prefix=prefix + '/')
        objs = resp.get('Contents', [])
        print(f'  {cfg["minio"]["bucket"]}/{prefix}/: {len(objs)} 对象')
        for o in objs[:20]:
            size_kb = o['Size'] / 1024
            print(f'    {o["Key"]:80s}  {size_kb:.0f} KB')
    except Exception as e:
        print(f'  ✗ {e}')


if __name__ == '__main__':
    main()