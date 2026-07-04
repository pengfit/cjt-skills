"""新疆 sync_progress 修复脚本

背景：v0.8 (2026-07-04) sync.py 改完重启后，正常跑完后 16 个 area 的汇总进度都因为
doc_count / current_county 字段不在 mapping（dynamic:strict）而写入失败。

功能：从 ods_material_xinjiang_price 聚合 (area_name, period) 文档数，
重写 16 条 area summary 进度，匹配 sync.py 修复版 (id=area_{areaid}__{run_id})。

用法：
  python3 commands/repair_progress.py                # 实际写入
  python3 commands/repair_progress.py --dry-run      # 只看不写
"""
import sys, os, json, argparse, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import yaml
import requests

CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'config.yml')


def _es(es_host, path, method='GET', body=None):
    h = {'Content-Type': 'application/json'}
    if method == 'GET':
        return requests.get(f"{es_host}{path}", timeout=30, verify=False, headers=h)
    elif method == 'POST':
        return requests.post(f"{es_host}{path}", data=json.dumps(body), timeout=60,
                             verify=False, headers=h)
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()

    cfg = yaml.safe_load(open(CONFIG_PATH))
    es_host = cfg['es']['host']
    ods_index = cfg['es']['ods_index']
    progress_index = cfg['es']['progress_index']

    # 1. 取所有 area 映射
    by_name_to_id = {}
    for a in cfg['areas']:
        by_name_to_id[a['name']] = str(a['areaid'])

    # 2. 从 ODS 按 (area_name, period) 聚合
    print(f'[repair] es_host={es_host}')
    print(f'[repair] 聚合 {ods_index} ...')
    body = {
        'size': 0,
        'track_total_hits': True,
        'aggs': {
            'by_area': {
                'terms': {'field': 'area_name', 'size': 50},
                'aggs': {
                    'by_period': {'terms': {'field': 'period', 'size': 10}}
                }
            }
        }
    }
    r = _es(es_host, f'/{ods_index}/_search', 'POST', body).json()
    aggs = r.get('aggregations', {}).get('by_area', {})
    pairs = []
    for area_b in aggs.get('buckets', []):
        area_name = area_b['key']
        areaid = by_name_to_id.get(area_name, '?')
        for p_b in area_b['by_period']['buckets']:
            pairs.append((area_name, areaid, p_b['key'], p_b['doc_count']))
    print(f'  共 {len(pairs)} 个 (area_name, period) 桶')

    # 3. 取最新一个 run_id（保留旧 run_id 数据，仅追加新 run）
    runs = _es(es_host, f'/{progress_index}/_search', 'POST',
               {'size': 0, 'aggs': {'r': {'terms': {'field': 'run_id', 'size': 5}}}}).json()
    latest_run_id = runs.get('aggregations', {}).get('r', {}).get('buckets', [{}])[0].get('key')
    if not latest_run_id:
        latest_run_id = f"xj_run_repair_{time.strftime('%Y%m%d_%H%M%S')}"
    print(f'[repair] 写入 run_id: {latest_run_id}')

    # 4. 按 area_name 聚合，写 16 条 area summary
    area_summary = {}
    for area_name, areaid, period, doc_count in pairs:
        if area_name not in area_summary:
            area_summary[area_name] = {
                'run_id': latest_run_id,
                'status': 'completed',
                'area': area_name,
                'areaid': areaid,
                'city': '',
                'period': '2026',
                'docs_written': 0,
                'percent': 100.0,
                'duration_sec': 0,
                'last_updated': time.strftime('%Y-%m-%d %H:%M:%S'),
                'update_date': time.strftime('%Y-%m-%d'),
                'error': '',
            }
        area_summary[area_name]['docs_written'] += doc_count

    # 5. 给每条 area_summary 加 city 字段
    by_name_to_city = {a['name']: a['city'] for a in cfg['areas']}
    for area_name in area_summary:
        area_summary[area_name]['city'] = by_name_to_city.get(area_name, area_name)

    print(f'[repair] 共 {len(area_summary)} 个 area summary 待写')
    written = 0
    for area_name, doc in area_summary.items():
        areaid = doc['areaid']
        doc_id = f'area_{areaid}__{latest_run_id}'
        if args.dry_run:
            print(f'  [dry-run] {doc_id}: {doc["docs_written"]} 条')
            written += 1
        else:
            r = _es(es_host, f'/{progress_index}/_doc/{doc_id}', 'PUT', doc)
            if r.status_code in (200, 201):
                written += 1
                print(f'  ✓ {area_name}: {doc["docs_written"]} 条 ({r.json().get("result","?")})')
            else:
                print(f'  ✗ {area_name}: {r.status_code} {r.text[:200]}')

    print(f'\n[✓] 写入 {written} 条 area summary')


if __name__ == '__main__':
    main()
