"""陕西工程造价材料信息 - 连通性测试

测试 ES + MinIO + 源站列表 + 详情页 + PDF 下载。
"""
import os
import sys
import tempfile

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

from utils import (
    load_config, get_es_client, get_s3_client,
    ensure_bucket, ensure_ods_index, ensure_progress_index,
    fetch_html, parse_list_page, parse_detail_page,
)


def main():
    cfg = load_config()
    print('[test] === 陕西工程造价连通性测试 ===\n')

    # 1. ES
    print('[1/5] ES 连接...', end=' ')
    try:
        es = get_es_client(cfg['es']['host'])
        info = es.info()
        print(f'OK (version={info["version"]["number"]})')
        # 确保索引
        ensure_ods_index(es, cfg['es']['ods_index'])
        ensure_progress_index(es, cfg['es']['progress_index'])
        print(f'  - {cfg["es"]["ods_index"]}: ready')
        print(f'  - {cfg["es"]["progress_index"]}: ready')
    except Exception as e:
        print(f'FAIL: {e}')
        return

    # 2. MinIO
    print('\n[2/5] MinIO 连接...', end=' ')
    try:
        s3 = get_s3_client(cfg)
        ensure_bucket(s3, cfg['minio']['bucket'])
        print(f'OK (bucket={cfg["minio"]["bucket"]} exists)')
    except Exception as e:
        print(f'FAIL: {e}')
        return

    # 3. 源站列表
    print('\n[3/5] 源站列表 (page 0)...', end=' ')
    try:
        site = cfg['site']
        headers = {
            'User-Agent': site['user_agent'],
            'Referer': site.get('referer', site['base_url']),
        }
        html = fetch_html(site['base_url'] + site['list_path'], headers=headers, timeout=site['timeout_sec'])
        items = parse_list_page(html, site['base_url'] + '/sy/yw/zjglfw/zjxx/')
        print(f'OK ({len(items)} 期)')
        if items:
            print(f'  最新: {items[0]["title"][:60]}')
            print(f'  发布: {items[0]["publish_date"]}')
    except Exception as e:
        print(f'FAIL: {e}')
        return

    # 4. 详情页 + PDF URL 提取
    if items:
        print(f'\n[4/5] 详情页 + PDF URL (latest)...', end=' ')
        try:
            detail_html = fetch_html(items[0]['detail_url'], headers=headers, timeout=site['timeout_sec'])
            detail = parse_detail_page(detail_html, items[0]['detail_url'])
            if detail['pdf_url']:
                print(f'OK')
                print(f'  PDF URL: {detail["pdf_url"]}')
                print(f'  PDF name: {detail["pdf_name"]}')
            else:
                print('FAIL: 未找到 PDF URL')
                return
        except Exception as e:
            print(f'FAIL: {e}')
            return

        # 5. PDF 下载
        print(f'\n[5/5] PDF 下载 (前 1MB)...', end=' ')
        try:
            with tempfile.TemporaryDirectory() as tmpdir:
                local_pdf = os.path.join(tmpdir, 'test.pdf')
                # 用 stream 控制只下 1MB
                import requests
                r = requests.get(detail['pdf_url'], headers=headers, timeout=60, stream=True)
                r.raise_for_status()
                with open(local_pdf, 'wb') as f:
                    downloaded = 0
                    for chunk in r.iter_content(chunk_size=64 * 1024):
                        downloaded += len(chunk)
                        f.write(chunk)
                        if downloaded >= 1024 * 1024:
                            break
                size = os.path.getsize(local_pdf)
                print(f'OK ({size} bytes)')
        except Exception as e:
            print(f'FAIL: {e}')
            return

    print('\n[test] === 全部连通 ===')


if __name__ == '__main__':
    main()
