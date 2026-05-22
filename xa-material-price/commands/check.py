"""西安工程造价材料信息 - 增量检测与触发同步"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests
from commands.utils import (
    SiteSession, parse_page_date, parse_total_records, parse_table_rows,
    load_config, get_last_update_date_by_county, spot_check_county,
    save_sync_time, COUNTY_CODES
)

ES_HOST = 'http://localhost:59200'


def get_website_count(county: str) -> tuple:
    """获取网站某区县总记录数，返回 (total, page1_html)"""
    session = SiteSession(max_retries=3, timeout=30)
    html = session.fetch(county, page=1)
    if not html:
        return 0, None
    total = parse_total_records(html)
    return total, html


def get_es_count_by_county(es_host: str, es_index: str, county: str) -> int:
    """ES 中该区县的记录数"""
    try:
        r = requests.post(
            f'{es_host}/{es_index}/_count',
            json={'query': {'term': {'county': county}}},
            timeout=15, verify=False
        )
        return r.json().get('count', 0)
    except Exception:
        return 0


def main():
    script_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    cfg_path = os.path.join(script_dir, 'config.yml')
    config = load_config(cfg_path)
    es_host = config['es']['host']
    es_index = config['es']['index']

    print('[i] 增量检测开始...')

    spot_session = SiteSession(max_retries=3, timeout=30)
    changed = []

    for county in config['site']['counties']:
        html = spot_session.fetch(county, page=1)
        if not html:
            print(f'  [{county}] 获取失败，跳过')
            continue

        site_total = parse_total_records(html)
        site_date = parse_page_date(html)
        site_rows = parse_table_rows(html)

        es_count = get_es_count_by_county(es_host, es_index, county)

        if site_total == 0:
            continue

        diff = site_total - es_count

        if diff > 0:
            print(f'  [{county}] 网站 {site_total} > ES {es_count}  (+{diff}) | 更新:{site_date}')
            changed.append({'county': county, 'web_total': site_total, 'es_count': es_count, 'diff': diff, 'site_date': site_date})
        else:
            print(f'  [{county}] 一致 {site_total} | 更新:{site_date}')

    if not changed:
        print('[—] 无新增记录')
        return

    print(f'\n[i] 发现 {len(changed)} 个区县有新数据:')
    for c in changed:
        print(f'  {c["county"]}: +{c["diff"]} 条')

    print('\n[→] 触发增量同步（仅异常区县，后台运行）...')
    import subprocess
    county_list = ','.join([c['county'] for c in changed])
    log_file = '/tmp/xian-incremental-sync.log'
    ret = subprocess.Popen(
        ['python3', 'commands/sync.py', '--force', '--no-spot-check', f'--counties={county_list}'],
        cwd=script_dir,
        env={**os.environ},
        stdout=open(log_file, 'w'),
        stderr=subprocess.STDOUT,
        start_new_session=True
    )
    print(f'[→] 增量同步已在后台启动 (PID {ret.pid})，日志: {log_file}')
    print('[✓] check.py 完成，sync.py 继续在后台运行')


if __name__ == '__main__':
    main()
