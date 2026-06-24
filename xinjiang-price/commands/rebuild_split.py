"""新疆 ES 数据 - 一次性重建：为已有文档补充 breed_clean / spec 字段

用法：
  python3 commands/rebuild_split.py           # 全量重建
  python3 commands/rebuild_split.py --dry-run # 只统计，不写入
"""
import os
import sys
import time

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

from utils import load_config, get_es_client
from parse import split_breed_spec


def main():
    import argparse
    parser = argparse.ArgumentParser(description='重建 ES 文档：拆分 breed/spec')
    parser.add_argument('--dry-run', action='store_true', help='只统计不写入')
    parser.add_argument('--batch-size', type=int, default=500)
    parser.add_argument('--force', action='store_true', help='重跑所有文档（不跳过已填充的）')
    args = parser.parse_args()

    cfg = load_config()
    es = get_es_client(cfg['es']['host'])
    ods_index = cfg['es']['ods_index']

    total = es.count(index=ods_index)['count']
    print(f'[rebuild] 索引 {ods_index} 总 {total:,} 条')

    # 滚动扫描所有文档
    if args.force:
        # --force: 重跑所有
        body = {'query': {'match_all': {}}, 'sort': [{'_doc': 'asc'}]}
    else:
        body = {
            'query': {'bool': {'must_not': [{'exists': {'field': 'breed_clean'}}]}},
            'sort': [{'_doc': 'asc'}],
        }
    body['_source'] = ['breed', 'spec', 'breed_clean']

    updated = 0
    skipped = 0
    failed = 0
    split_stats = {'with_spec': 0, 'no_spec': 0, 'changed': 0}

    res = es.search(index=ods_index, body=body, size=args.batch_size, scroll='2m')
    scroll_id = res.get('_scroll_id')
    hits = res['hits']['hits']

    start = time.time()
    while hits:
        bulk_body = []
        for h in hits:
            src = h['_source']
            breed = src.get('breed', '') or ''
            existing_spec = src.get('spec', '') or ''
            existing_clean = src.get('breed_clean', '') or ''

            # 已经拆分过且 breed_clean/spec 都填好 → 跳过
            if existing_clean and existing_spec and not args.force:
                skipped += 1
                continue

            breed_clean, spec_extracted = split_breed_spec(breed)
            final_spec = existing_spec if existing_spec else spec_extracted

            if not breed_clean:
                breed_clean = breed  # fallback

            if final_spec:
                split_stats['with_spec'] += 1
            else:
                split_stats['no_spec'] += 1

            if args.dry_run:
                continue

            # 用 _id 重新 index（覆盖）
            new_doc = dict(src)
            new_doc['breed_clean'] = breed_clean
            new_doc['spec'] = final_spec
            bulk_body.append(
                f'{{"index": {{"_index": "{ods_index}", "_id": "{h["_id"]}"}}}}'
            )
            bulk_body.append(str(new_doc).replace("'", '"'))

        if not args.dry_run and bulk_body:
            resp = es.bulk(body='\n'.join(bulk_body) + '\n', refresh=False)
            if resp.get('errors'):
                for it in resp['items']:
                    if 'error' in it.get('index', {}):
                        failed += 1
                    else:
                        updated += 1
            else:
                updated += len(hits)

        if updated + skipped + failed > 0 and (updated + skipped + failed) % 5000 < args.batch_size:
            print(f'  进度: 已处理 {updated + skipped + failed:,}/{total:,}  '
                  f'updated={updated}  skipped={skipped}  failed={failed}')

        res = es.scroll(scroll_id=scroll_id, scroll='2m')
        scroll_id = res.get('_scroll_id')
        hits = res['hits']['hits']

    if scroll_id:
        es.clear_scroll(scroll_id=scroll_id)

    elapsed = time.time() - start
    print(f'\n[rebuild] 完成（{elapsed:.1f}s）')
    print(f'  updated: {updated:,}')
    print(f'  skipped: {skipped:,}')
    print(f'  failed:  {failed:,}')
    print(f'  拆分后:  {split_stats["with_spec"]:,} 有 spec / {split_stats["no_spec"]:,} 无 spec')

    if not args.dry_run:
        es.indices.refresh(index=ods_index)
        print('  索引已 refresh')


if __name__ == '__main__':
    main()
