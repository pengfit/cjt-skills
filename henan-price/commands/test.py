"""测试连通性：ES + MinIO + 源站"""
import os
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
    url = cfg['site']['base_url'] + cfg['site']['list_path']
    try:
        html = fetch_html(url, timeout=cfg['site']['timeout_sec'])
        print(f'  OK  {url}  ({len(html)} 字节)')
        # 简单看期数
        import re
        m = re.findall(r'/\d{8}/[0-9a-f-]{36}\.html', html)
        print(f'  列表条目数: {len(m)}')
    except Exception as e:
        print(f'  ✗ {e}')


if __name__ == '__main__':
    main()
