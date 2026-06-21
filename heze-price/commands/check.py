"""菏泽 - 增量检测：对比 ES 最新 update_date vs 源站最新发布日期"""
import sys, os, requests

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)
from utils import load_config, get_es_client


def main():
    cfg = load_config()
    es = get_es_client(cfg['es']['host'])
    site = cfg['site']
    ods_index = cfg['es']['ods_index']

    # 1. 获取 ES 最新 update_date
    es_latest = ''
    try:
        r = es.search(index=ods_index, size=1, sort=[{'update_date': 'desc'}],
                       _source=['update_date'])
        hits = r['hits']['hits']
        if hits:
            es_latest = hits[0]['_source'].get('update_date', '') or ''
    except Exception as e:
        print(f'[菏泽] ES 查询失败: {e}')

    # 2. 获取源站最新发布
    site_latest = ''
    site_subject = ''
    try:
        api_url = f'{site["api_url"]}/1/1'
        body = {
            'dw': [site['dwid']],
            'catas': [site['catas']],
            'fwzt': '3', 'order': 'fwdate', 'type': [1],
        }
        headers = {'User-Agent': site['user_agent'], 'Content-Type': 'application/json'}
        r = requests.post(api_url, json=body, headers=headers, timeout=30, verify=False)
        data = r.json()
        contents = data.get('data', {}).get('contents', [])
        if contents:
            latest = contents[0]
            site_latest = latest.get('fwdate', '')
            site_subject = latest.get('subject', '')
    except Exception as e:
        print(f'[菏泽] 源站查询失败: {e}')

    print(f'[菏泽] 源站最新: {site_subject} ({site_latest})')
    print(f'[菏泽] ES 最新:   {es_latest or "无"}')

    if es_latest and site_latest:
        if site_latest > str(es_latest)[:10]:
            print(f'[菏泽] 🔔 有更新！{site_subject}')
        else:
            print(f'[菏泽] ✅ 无新数据')
    elif site_latest:
        print(f'[菏泽] 🔔 源站有数据，ES 无记录，需首次同步')
    else:
        print(f'[菏泽] ⚠️ 无法获取源站数据')


if __name__ == '__main__':
    main()
