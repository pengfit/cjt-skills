"""贵州 · 测试连通性：ES + MinIO + 源站 AJAX。"""
import json
import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

from utils import (
    load_config, get_es_client, get_s3_client, ensure_bucket, post_form,
)


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

    print('\n=== 源站（POST AJAX 列表首页）===')
    url = site['base_url'] + site['ajax_path']
    body = (
        f"guid={site['sub_tab_guid']}"
        f"&page=1&pagesize={site['page_size']}"
    )
    headers = {
        'Referer': site['base_url'] + site['list_path'],
        'X-Requested-With': 'XMLHttpRequest',
        'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
    }
    try:
        r = post_form(url, data=body, headers=headers,
                      timeout=site['timeout_sec'])
        r.raise_for_status()
        try:
            data = json.loads(r.text)
        except json.JSONDecodeError:
            print(f'  ✗ 返回非 JSON: {r.text[:200]}')
            return
        rows = data.get('Rows') or []
        total = data.get('Total')
        print(f'  OK  HTTP {r.status_code}  Total={total}  Rows={len(rows)}')
        if rows:
            row0 = rows[0]
            print(
                f'  最新: {row0["Name"]}  '
                f'entryDate={row0.get("EntryDate")}'
            )
            atts = row0.get('PoliciesAttachmentDTOS') or []
            if atts:
                fu = atts[0].get('FileUrl')
                print(f'  PDF 路径: .../Upload/File/{fu}')
    except Exception as e:
        print(f'  ✗ {e}')


if __name__ == '__main__':
    main()
