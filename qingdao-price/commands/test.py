"""测试连通性：ES + MinIO + 源站"""
import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

from utils import (
    load_config, get_es_client, get_s3_client, ensure_bucket,
    fetch_html, download_file,
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
    list_url = cfg['site']['base_url'] + cfg['site']['list_path']
    try:
        html = fetch_html(list_url, timeout=cfg['site']['timeout_sec'])
        print(f'  OK  {list_url}  ({len(html)} 字节)')
        # 数 li 数量
        import re
        n = len(re.findall(r'<li[^>]*trs-attr="chip"', html))
        print(f'  列表条目数: {n}')
    except Exception as e:
        print(f'  ✗ {e}')

    print('\n=== 源站（PDF 下载）===')
    # 拿一个 PDF 链接测下载
    try:
        from bs4 import BeautifulSoup
        from sync import parse_detail_page, extract_period_from_title
        html = fetch_html(list_url, timeout=cfg['site']['timeout_sec'])
        soup = BeautifulSoup(html, 'html.parser')
        li = soup.select_one('li[trs-attr="chip"]')
        if not li:
            print('  ✗ 列表上找不到 li 项')
        else:
            a = li.select_one('a[href*="t20"][href$=".html"]')
            detail_url = a.get('href', '')
            print(f'  测试详情页: {detail_url}')
            detail_html = fetch_html(detail_url, timeout=cfg['site']['timeout_sec'])
            detail = parse_detail_page(detail_html, cfg['site']['base_url'], detail_url=detail_url)
            if detail['pdf_url']:
                print(f'  PDF 链接: {detail["pdf_url"]}')
                # 测下载（带 Referer）
                import tempfile
                with tempfile.TemporaryDirectory() as tmpdir:
                    local = os.path.join(tmpdir, 'test.pdf')
                    download_file(detail['pdf_url'], local, referer=detail_url, timeout=60)
                    size = os.path.getsize(local)
                    print(f'  OK  下载成功 {size} bytes (带 Referer)')
            else:
                print('  ✗ 详情页未找到 PDF 链接')
    except Exception as e:
        print(f'  ✗ {e}')


if __name__ == '__main__':
    main()
