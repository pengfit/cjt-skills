"""resync_from_minio.py - 从 MinIO 读 PDF 重新入 ES

用于本地 PDF 已下载、网络下载慢/不可用时的应急重入。
- 列出 MinIO `gov-price-data/hainan-price/` 下的所有 PDF
- 下载到本地临时目录 → pdfplumber 解析 → bulk_index 到 ods_material_hainan_price
- 复用 parser.py 纯函数（解析逻辑不变）
- 与 sync.py 的差异：跳过源站列表抓取和 PDF 下载环节，直接从 MinIO 取

用法：
    python3 commands/resync_from_minio.py            # 全部 4 期重入
    python3 commands/resync_from_minio.py --period "2026.1月"
"""
import argparse
import os
import sys
import tempfile
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

from utils import (  # noqa: E402
    load_config, get_es_client, get_s3_client,
    ensure_bucket, ensure_ods_index, ensure_progress_index,
)
from parser import (  # noqa: E402
    parse_pdf, bulk_index, _doc_id, compute_period_range,
)


def _list_minio_periods(cfg):
    """列出 MinIO 里 hainan-price 下所有 period（如 '2026.1月'）。"""
    s3 = get_s3_client(cfg)
    ensure_bucket(s3, cfg['minio']['bucket'])
    prefix = cfg['minio']['prefix'] + '/'
    resp = s3.list_objects_v2(Bucket=cfg['minio']['bucket'], Prefix=prefix, Delimiter='/')
    periods = []
    for p in resp.get('CommonPrefixes', []):
        # 路径如 'hainan-price/2026.1月/'
        name = p['Prefix'].rstrip('/').split('/')[-1]
        periods.append(name)
    return sorted(periods)


def _download_pdf(cfg, period):
    """从 MinIO 下载 period 对应 PDF 到本地临时文件，返回路径。"""
    s3 = get_s3_client(cfg)
    prefix = cfg['minio']['prefix']
    # 找到该 period 下唯一的 PDF
    list_resp = s3.list_objects_v2(
        Bucket=cfg['minio']['bucket'],
        Prefix=f"{prefix}/{period}/",
    )
    pdf_keys = [o['Key'] for o in list_resp.get('Contents', []) if o['Key'].endswith('.pdf')]
    if not pdf_keys:
        return None, None
    pdf_key = pdf_keys[0]
    tmp = tempfile.NamedTemporaryFile(suffix='.pdf', delete=False)
    tmp.close()
    s3.download_file(cfg['minio']['bucket'], pdf_key, tmp.name)
    return tmp.name, pdf_key


def main():
    parser = argparse.ArgumentParser(description='海南 - 从 MinIO 重入 ES')
    parser.add_argument('--period', default='', help='指定周期（substring 匹配）')
    parser.add_argument('--year', type=int, default=0, help='只入指定年份（默认 0=不限制）')
    args = parser.parse_args()

    cfg = load_config()
    es_host = cfg['es']['host']
    es = get_es_client(es_host)
    s3 = get_s3_client(cfg)
    ensure_bucket(s3, cfg['minio']['bucket'])
    ensure_ods_index(es, es_host, cfg['es']['ods_index'])
    ensure_progress_index(es, cfg['es']['progress_index'])

    periods = _list_minio_periods(cfg)
    print(f'[minio] {len(periods)} 个 period: {periods}')

    if args.period:
        periods = [p for p in periods if args.period in p]
    if args.year:
        periods = [p for p in periods if f'{args.year}.' in p]

    print(f'[minio] 待处理 {len(periods)} 期')
    total_written = 0
    for period in periods:
        print(f'\n=== {period} ===')
        local_pdf, minio_key = _download_pdf(cfg, period)
        if not local_pdf:
            print(f'  ✗ MinIO 没找到 PDF，跳过')
            continue

        period_start, period_end, period_days = compute_period_range(period)
        print(f'  period_start={period_start}  period_end={period_end}  period_days={period_days}')

        rows = parse_pdf(local_pdf)
        print(f'  parsed: {len(rows)} 行')

        # 取 PDF 名作为发布日标识（不严求，update_date 留空，period_start 兜底）
        now = datetime.now().isoformat(timespec='seconds')
        docs = []
        for r in rows:
            p = r.get('period') or period
            docs.append({
                'no': r['no'],
                'breed': r['breed'],
                'spec': r['spec'],
                'unit': r['unit'],
                'price': r['price'],
                'tax_price': r['tax_price'],
                'remark': r.get('remark', ''),
                'region': r['region'],
                'section': r['section'],
                'category': r['category'],
                'period': p,
                'period_start': period_start,
                'period_end': period_end,
                'period_days': period_days,
                'province': '海南',
                'city': '海南',
                'update_date': period_start,  # MinIO 重入拿不到列表页 publish_date，用 period_start 兜底（date 类型不接受空串）
                'create_time': now,
                'source_pdf': minio_key,
                'source_url': '',
            })
        ok, err = bulk_index(es, cfg['es']['ods_index'], docs)
        print(f'  bulk: ok={ok}, err={err}')

        # 写 ES progress
        if ok > 0:
            try:
                es.index(index=cfg['es']['progress_index'], body={
                    'run_id': f'minio_resync_{datetime.now().strftime("%Y%m%d_%H%M%S")}',
                    'period': period,
                    'publish_date': '',
                    'docs_written': ok,
                    'status': 'ok',
                    'created_at': now,
                    'source': 'minio_resync',
                })
            except Exception as e:
                print(f'  [warn] ES progress 写入失败: {e}')

        os.unlink(local_pdf)
        total_written += ok
        print(f'  ✓ {period}: {ok} docs')

    print()
    print('=' * 60)
    print(f'[minio] 总写入: {total_written} 条')


if __name__ == '__main__':
    main()