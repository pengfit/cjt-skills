"""山西 · 测试连通性：ES + MinIO + 源站列表页。"""
import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

from utils import load_config, get_es_client, get_s3_client, ensure_bucket, fetch_html, get_headers
from sync import page_url, detect_total_pages, parse_list_page, parse_detail_page


def main():
    cfg = load_config()
    site = cfg['site']

    print('=== ES ===')
    try:
        es = get_es_client(cfg['es']['host'])
        info = es.info()
        print(
            f'  OK  version={info["version"]["number"]}  '
            f'cluster={info["cluster_name"]}'
        )
    except Exception as e:
        print(f'  ✗ {e}')

    print('\n=== MinIO ===')
    try:
        s3 = get_s3_client(cfg)
        ensure_bucket(s3, cfg['minio']['bucket'])
        print(f'  OK  bucket={cfg["minio"]["bucket"]}')
    except Exception as e:
        print(f'  ✗ {e}')

    print('\n=== 源站（首页 HTML）===')
    try:
        url = page_url(site['base_url'], site['list_path'], 0)
        html = fetch_html(url, headers=get_headers(cfg),
                          timeout=site['timeout_sec'])
        total_pages = detect_total_pages(html, fallback=site.get('max_pages', 9))
        items = parse_list_page(html)
        print(f'  OK  HTTP {html[:50].__len__()} bytes  pages={total_pages}  items={len(items)}')
        if items:
            print(f'  最新: {items[0]["title"]}  ({items[0]["date"]})')
            print(f'  detail: {items[0]["detail_path"]}')
    except Exception as e:
        print(f'  ✗ {e}')
        return

    print('\n=== 源站（详情页 PDF 解析）===')
    try:
        from urllib.parse import urljoin
        detail_url = urljoin(site['base_url'] + site['list_path'], items[0]['detail_path'])
        dhtml = fetch_html(detail_url, headers=get_headers(cfg),
                           timeout=site['timeout_sec'])
        pdf = parse_detail_page(dhtml, detail_url)
        print(f'  OK  pdf_url: {pdf.get("pdf_url")}')
        print(f'      pdf_name: {pdf.get("pdf_name")}')
        print(f'      source: {pdf.get("source")}')
    except Exception as e:
        print(f'  ✗ {e}')

    print('\n=== ODS unit 覆盖率断言（防下次增量退化）===')
    ods = cfg['es']['ods_index']
    unit_threshold = float(os.environ.get('SHANXI_UNIT_COVERAGE_MIN', '0.80'))
    try:
        total = es.count(index=ods)['count']
        if total == 0:
            print(f'  ⚠ ODS 为空 ({ods}), 跳过覆盖率检查')
        else:
            empty = es.count(index=ods, body={'query': {'term': {'unit': ''}}})['count']
            coverage = (total - empty) / total
            status = '✓' if coverage >= unit_threshold else '✗'
            print(f'  {status} total={total}, 空 unit={empty}, 覆盖率={coverage:.1%} (阈值 {unit_threshold:.0%})')
            if coverage < unit_threshold:
                print(f'  ⚠ 覆盖率低于阈值, 跑 update_units.py 补齐:')
                print(f'      python3 commands/update_units.py --step 3   # 补空 unit')
                print(f'      python3 commands/update_units.py --step 1 2 # 归一 m→m³ / m?→m³')
                # 默认不退出非零, 让 test.py 可以被 cron 用到
                if os.environ.get('SHANXI_STRICT') == '1':
                    sys.exit(2)
    except Exception as e:
        print(f'  ✗ {e}')


if __name__ == '__main__':
    main()