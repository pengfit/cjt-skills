"""测试连通性：ES + MinIO + 源站"""
import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

from utils import load_config, get_es_client, get_s3_client, ensure_bucket, http_get
from fetch import fetch_list, fetch_all_policies


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

    print('\n=== 源站 (AJAX API) ===')
    try:
        obj = fetch_list(cfg, areaid=1, page=1, page_size=5)
        print(f'  OK  Total={obj.get("Total")}, Rows={len(obj.get("Rows", []))}')
    except Exception as e:
        print(f'  ✗ {e}')

    print('\n=== 16 个 area 抓取测试 ===')
    for area in cfg['areas']:
        try:
            policies = fetch_all_policies(cfg, area['areaid'])
            from fetch import filter_target_year
            targets = filter_target_year(policies, cfg['sync']['year'])
            print(f"  [{area['areaid']:2d}] {area['name']:8s}  总 {len(policies):3d} 期  {cfg['sync']['year']}年 {len(targets)} 期")
        except Exception as e:
            print(f"  [{area['areaid']:2d}] {area['name']:8s}  ✗ {e}")


if __name__ == '__main__':
    main()
