"""济南工程造价材料信息 - 增量检测与触发同步"""
import sys, os, yaml
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests
from commands.utils import JinAnSiteSession, load_config

ES_HOST = 'http://localhost:59200'


def get_es_period_id():
    cfg_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'config.yml')
    with open(cfg_path) as f:
        cfg = yaml.safe_load(f)
    return cfg.get('sync', {}).get('last_period_id', '')


def check_incremental(session, es_host, period_id):
    """
    检测某周期内是否有新增记录，返回有变化的分类列表。

    检测逻辑（改进版）：
    网站 total 字段可能包含重复数据（同一材料多页更新导致），
    因此：
    - 若 total > page_size（多页），需遍历所有页统计唯一 _id
    - 若 total == page_size（单页），比较 total 与实际记录数是否一致
    不一致 → 有重复 → 触发精确遍历
    """
    changed = []
    all_cat_ids = session.get_all_catalogue_ids('2')

    def _doc_id_key(breed, spec, period, period_id, catalogue_id, price):
        import hashlib
        raw = f"{breed}_{spec}_{period}_{period_id}_{catalogue_id}_{price}"
        return hashlib.md5(raw.encode('utf-8')).hexdigest()

    for cat_id in all_cat_ids:
        # 分类中文名
        cat_name = session.find_catalogue_name_by_id(cat_id, '2') or cat_id

        # 抓取第一页（size=100 足以覆盖大部分单页分类）
        data = session.fetch(period_id, cat_id, page=1, size=100)
        if not data:
            continue
        records = data.get('records', [])
        if not records:
            continue

        web_total_reported = data.get('total', 0)
        first_page_count = len(records)

        # 判断是否需要精确遍历
        if web_total_reported > first_page_count:
            # 多页情况：需遍历所有页统计唯一 _id
            import time
            seen_ids = set()
            page = 1
            while True:
                page_data = session.fetch(period_id, cat_id, page=page, size=100)
                if not page_data:
                    break
                page_records = page_data.get('records', [])
                if not page_records:
                    break
                for r in page_records:
                    pid = _doc_id_key(
                        r.get('productName', ''), (r.get('features') or '').strip(),
                        '', period_id, cat_id, str(r.get('infoPrice', 0) or 0)
                    )
                    seen_ids.add(pid)
                if len(page_records) < 100:
                    break
                page += 1
                time.sleep(0.5)
            web_unique_count = len(seen_ids)
        else:
            # 单页情况：total == first_page_count，检查是否有重复（total 与实际 unique 不符）
            first_page_ids = set()
            for r in records:
                pid = _doc_id_key(
                    r.get('productName', ''), (r.get('features') or '').strip(),
                    '', period_id, cat_id, str(r.get('infoPrice', 0) or 0)
                )
                first_page_ids.add(pid)
            if len(first_page_ids) < first_page_count:
                # 有重复，total 不可信
                web_unique_count = len(first_page_ids)
            else:
                # 无重复，total 可信
                web_unique_count = web_total_reported

        # ES 中该分类该周期的记录数
        try:
            es_resp = requests.post(
                f'{es_host}/ods_material_jinan_price/_count',
                json={
                    'query': {
                        'bool': {
                            'must': [
                                {'term': {'period_id': period_id}},
                                {'term': {'catalogue': cat_id}}
                            ]
                        }
                    }
                },
                timeout=15, verify=False
            )
            es_count = es_resp.json().get('count', 0)
        except Exception:
            es_count = 0

        if web_unique_count > es_count:
            changed.append({
                'catalogue': cat_id, 'catalogue_name': cat_name,
                'web_total': web_unique_count, 'es_count': es_count
            })

    return changed


def main():
    script_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    cfg_path = os.path.join(script_dir, 'config.yml')
    cfg = load_config(cfg_path)

    print('[i] 增量检测开始...')

    # 获取网站最新周期
    session = JinAnSiteSession()
    period_name, period_id = session.get_last_period()
    if not period_id:
        print('[!] 无法获取网站最新周期')
        return

    saved_period_id = cfg.get('sync', {}).get('last_period_id', '')

    # 情况1：新周期出现
    if period_id != saved_period_id:
        print(f'[i] 新周期出现: {period_name} (id={period_id})')
        print('[→] 触发全量同步...')
        os.system(f'cd {script_dir} && python3 commands/sync.py --force')
        return

    # 情况2：同周期，检测各分类是否有新增
    print(f'[i] 当前周期无变化: {period_name}，检测分类增量...')
    changed = check_incremental(session, ES_HOST, period_id)
    if not changed:
        print('[—] 无新增记录')
        return

    print(f'[i] 发现 {len(changed)} 个分类有新数据:')
    for c in changed:
        diff = c['web_total'] - c['es_count']
        print(f'  {c["catalogue_name"]}: 网站 {c["web_total"]} > ES {c["es_count"]}  (+{diff})')
    print('[→] 触发增量同步...')
    os.system(f'cd {script_dir} && python3 commands/sync.py --force')


if __name__ == '__main__':
    main()
