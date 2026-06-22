"""测试连通性：ES + MinIO + 源站"""
import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

from utils import (
    load_config, get_es_client, get_s3_client, ensure_bucket,
    fetch_html, fetch_list_page,
)


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

    print('\n=== 源站（列表页）===')
    site = cfg['site']
    list_url = site['base_url'] + site['list_path']
    try:
        html = fetch_html(list_url, timeout=site['timeout_sec'])
        print(f'  OK  {list_url}  ({len(html)} 字节)')
    except Exception as e:
        print(f'  ✗ {e}')

    print('\n=== 源站（dataproxy.jsp 第 1 页）===')
    try:
        xml = fetch_list_page(cfg, 1)
        from sync import parse_list_xml
        items = parse_list_xml(xml)
        print(f'  OK  {len(items)} 条记录')
        if items:
            print(f'  最新: {items[0]["publish_date"]}  {items[0]["title"]}')
    except Exception as e:
        print(f'  ✗ {e}')

    print('\n=== 依赖库 ===')
    import importlib
    for mod in ['requests', 'bs4', 'pdfplumber', 'boto3', 'elasticsearch', 'yaml']:
        try:
            importlib.import_module(mod)
            print(f'  ✓ {mod}')
        except ImportError:
            print(f'  ✗ {mod}  (pip3 install {mod})')


if __name__ == '__main__':
    main()
