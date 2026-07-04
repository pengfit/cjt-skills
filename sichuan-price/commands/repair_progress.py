"""四川 sync_progress 修复脚本

背景（v0.7 2026-07-04）：早期 sync.py 没把 period 写入 progress doc 的 _id，
导致多周期跑时同一地区的进度记录会被覆盖，最后只剩最后一个周期的；
加上偶尔产生 area="" 的 stale doc。

功能：从 ods_material_sichuan_price 聚合 (period, area) 文档数，
重新生成 ods_material_sichuan_price_sync_progress 记录，
并清理：
  - run_id 历史残留
  - area="" 的 stale doc

用法：
  python3 commands/repair_progress.py                # 默认：从 OD}{S 回灌 + 清理
  python3 commands/repair_progress.py --dry-run      # 只看不写
  python3 commands/repair_progress.py --force        # 跳过确认
"""
import sys, os, json, argparse, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import yaml
import requests

CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'config.yml')
AREA_CODES = {
    '川A': '成都市', '川B': '绵阳市', '川C': '自贡市', '川D': '攀枝花市',
    '川E': '泸州市', '川F': '德阳市', '川H': '广元市', '川J': '遂宁市',
    '川K': '内江市', '川L': '乐山市', '川M': '资阳市', '川Q': '宜宾市',
    '川R': '南充市', '川S': '达州市', '川T': '雅安市', '川U': '阿坝州',
    '川V': '甘孜州', '川W': '凉山州', '川X': '广安市', '川Y': '巴中市',
    '川Z': '眉山市',
}


def _es_post(es_host, path, body=None, method='GET'):
    try:
        if method == 'GET':
            r = requests.get(f"{es_host}{path}", timeout=30, verify=False)
        elif method == 'POST':
            r = requests.post(f"{es_host}{path}", data=json.dumps(body),
                              headers={'Content-Type': 'application/json'},
                              timeout=60, verify=False)
        elif method == 'DELETE':
            r = requests.delete(f"{es_host}{path}", timeout=30, verify=False)
        else:
            raise ValueError(method)
        return r
    except Exception as e:
        print(f'[ERR] {method} {path}: {e}')
        return None


def repair(es_host, ods_index, progress_index, dry_run=False, force=False):
    print(f'[repair] es_host={es_host}')
    print(f'[repair] ods_index={ods_index}')
    print(f'[repair] progress_index={progress_index}')

    run_id = time.strftime('%Y-%m-%d_%H-%M-%S')
    print(f'[repair] 新 run_id: {run_id}')

    # 1. 清理 stale (area 为空 / run_id 历史残留)
    print(f'\n[1/3] 清理 stale doc ...')
    stale_query = {"bool": {"should": [
        {"bool": {"must_not": [{"exists": {"field": "area"}}]}},
        {"term": {"area": ""}},
        {"range": {"run_id": {"lt": run_id}}},
    ], "minimum_should_match": 1}}
    r = _es_post(es_host, f'/{progress_index}/_count', stale_query, method='POST')
    stale_count = r.json().get('count', 0) if r else 0
    print(f'  待清理: {stale_count} 条')
    if stale_count and not dry_run:
        if not force:
            print(f'  ⚠️ 这将删除 {stale_count} 条 stale doc。加上 --force 确认。')
            return False
        r = _es_post(es_host, f'/{progress_index}/_delete_by_query?conflicts=proceed',
                     {"query": stale_query}, method='POST')
        if r and r.status_code in (200, 201):
            print(f'  [✓] 删除完成')
        else:
            print(f'  [!] 删除失败: {r.text if r else "?"}')
            return False

    # 2. 从 ODS 按 (period, city) 聚合文档数
    print(f'\n[2/3] 从 {ods_index} 聚合 (period, city) ...')
    body = {
        "size": 0,
        "track_total_hits": True,
        "aggs": {
            "by_period_city": {
                "terms": {"field": "period", "size": 50},
                "aggs": {
                    "by_city": {"terms": {"field": "city", "size": 50}}
                },
            },
        },
    }
    r = _es_post(es_host, f'/{ods_index}/_search', body, method='POST')
    if not r or r.status_code != 200:
        print(f'  [ERR] 聚合查询失败')
        return False
    aggs = r.json().get('aggregations', {}).get('by_period_city', {})
    # 拆出 (period, city) 二元组
    pairs = []
    for period_bucket in aggs.get('buckets', []):
        period = period_bucket['key']
        for city_bucket in period_bucket['by_city']['buckets']:
            city = city_bucket['key']
            doc_count = city_bucket['doc_count']
            pairs.append((period, city, doc_count))
    print(f'  共 {len(pairs)} 个 (period, city) 桶')

    # 3. 写入 progress_index
    print(f'\n[3/3] 写入 {progress_index} ...')
    docs_to_write = []
    now = time.strftime('%Y-%m-%d %H:%M:%S')
    for (period, city, doc_count) in pairs:
        if not city or not period:
            continue
        doc_id = f"{run_id}_{city}_{period}"
        docs_to_write.append({
            "_index": progress_index,
            "_id": doc_id,
            "_source": {
                "run_id": run_id,
                "status": "completed",
                "area": city,
                "period": period,
                "current_page": 1,
                "total_pages": 1,
                "total_records": doc_count,
                "docs_written": doc_count,
                "percent": 100.0,
                "duration_sec": 0.0,
                "last_updated": now,
                "error": "",
            },
        })

    if not docs_to_write:
        print(f'  [WARN] 没有可写入的文档')
        return True

    # 按 500 条一批 bulk 写入
    total_written = 0
    for i in range(0, len(docs_to_write), 500):
        batch = docs_to_write[i:i+500]
        bulk_body = ''
        for d in batch:
            bulk_body += json.dumps({"index": {"_index": d['_index'], "_id": d['_id']}}, ensure_ascii=False) + '\n'
            bulk_body += json.dumps(d['_source'], ensure_ascii=False) + '\n'
        if dry_run:
            print(f'  [dry-run] 批次 {i//500+1}，{len(batch)} 条')
            total_written += len(batch)
        else:
            r = requests.post(f'{es_host}/_bulk', data=bulk_body.encode('utf-8'),
                              headers={'Content-Type': 'application/x-ndjson'},
                              timeout=60, verify=False)
            if r.status_code in (200, 201):
                items = r.json().get('items', [])
                ok = sum(1 for it in items if it.get('index', {}).get('result') in ('created', 'updated'))
                total_written += ok
                print(f'  [{i//500+1}] {ok}/{len(batch)} 成功')
            else:
                print(f'  [{i//500+1}] bulk 失败: {r.text[:200]}')

    print(f'\n[✓] 总写入: {total_written} 条')
    print(f'[i] run_id={run_id}')
    print(f'[i] done.')
    return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--force', action='store_true', help='确认删除 stale doc')
    args = parser.parse_args()

    cfg = yaml.safe_load(open(CONFIG_PATH))
    es_host = cfg['es']['host']
    ods_index = cfg['es']['index']
    progress_index = cfg['es']['progress_index']

    repair(es_host, ods_index, progress_index, args.dry_run, args.force)


if __name__ == '__main__':
    main()
