"""测试连通性：ES + MinIO + 源站"""
import os
import re
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

from utils import load_config, get_es_client, get_s3_client, ensure_bucket, fetch_html


def main():
    cfg = load_config()
    print('=== ES ===')
    try:
        es = get_es_client(cfg['es']['host'])
        info = es.info()
        print(f'  OK  version={info["version"]["number"]}  cluster={info["cluster_name"]}')
    except Exception as e:
        print(f'  ✗ {e}')

    print('\n=== MinIO ===')
    try:
        s3 = get_s3_client(cfg)
        ensure_bucket(s3, cfg['minio']['bucket'])
        print(f'  OK  bucket={cfg["minio"]["bucket"]}')
    except Exception as e:
        print(f'  ✗ {e}')

    print('\n=== 源站 ===')
    site = cfg['site']
    for page in [1, 2]:
        if page == 1:
            url = site['base_url'] + site['list_path']
        else:
            url = site['base_url'] + site['list_page_pattern'].format(n=page)
        try:
            html = fetch_html(url, timeout=site['timeout_sec'])
            m = re.findall(r'/\d{6}/[0-9a-f]{32}\.shtml', html)
            print(f'  OK  {url}  ({len(html)} 字节, 列表条目: {len(m)})')
        except Exception as e:
            print(f'  ✗ {url}: {e}')


if __name__ == '__main__':
    main()
