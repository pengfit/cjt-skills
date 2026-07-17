"""山西 v1.1 剩余期导入（绕开 collector 长循环,每期独立进程处理）

背景：v1.1 Collector 路径在 2026.1-2月 PDF 上 hang（rapidocr + collector 长寿
命交互下的 native thread 卡死, 单页 OCR standalone 测 3-4s 正常）。

本脚本：直接调用 parse_pdf_tables + fetch_html + download_file + bulk_index,
每期一进程一次跑完。worker 路径与 collector 完全隔离, 避免 native thread hang。

用法:
    python3 commands/import_remaining.py            # 自动找 done 之外的所有期
    python3 commands/import_remaining.py --unit 0  # 单期索引(预览顺序的第 N 个)
"""
import argparse
import os
import sys
import tempfile
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

from sync import (
    fetch_all_periods, should_include, parse_period_from_title,
    parse_detail_page, parse_pdf_tables, row_to_doc, bulk_index,
    PROGRESS_FILE,
)
from utils import load_config, get_es_client, fetch_html, get_headers


def import_one(cfg: dict, item: dict, run_id: str) -> tuple[int, str]:
    """单个期号完整处理：抓详情 → 下载 PDF → OCR 解析 → bulk_index。"""
    from urllib.parse import urljoin
    from sync import load_progress, save_progress
    from utils import download_file, upload_to_minio, get_s3_client, ensure_bucket

    # 1. 检查 ES progress 是否已存在（之前 batch run 已写过）
    es = get_es_client(cfg['es']['host'])
    prog_index = cfg['es']['progress_index']

    win = parse_period_from_title(item['title'])
    if not win or win.get('invalid'):
        return 0, f"期号解析失败: {item['title']!r}"

    # 2. 抓详情
    dhtml = fetch_html(
        item['detail_url'], headers=get_headers(cfg),
        timeout=cfg['site']['timeout_sec'],
    )
    pdf = parse_detail_page(dhtml, item['detail_url'])
    if not pdf.get('pdf_url'):
        return 0, f"未找到 PDF: {item['detail_url']}"
    print(f'[import] PDF: {pdf["pdf_name"]}')

    # 3. 下载
    with tempfile.TemporaryDirectory() as td:
        local_pdf = os.path.join(td, 'src.pdf')
        try:
            download_file(pdf['pdf_url'], local_pdf, timeout=180)
        except Exception as e:
            return 0, f'下载失败: {e}'
        size_mb = os.path.getsize(local_pdf) / 1e6
        print(f'[import] downloaded {size_mb:.1f} MB')

        # 4. 上传 MinIO
        cfg_minio = cfg['minio']
        prefix = cfg_minio['prefix']
        bucket = cfg_minio['bucket']
        s3 = get_s3_client(cfg)
        ensure_bucket(s3, bucket)
        minio_key = f'{prefix}/{pdf["pdf_name"]}'
        try:
            upload_to_minio(s3, bucket, minio_key, local_pdf)
        except Exception as e:
            return 0, f'MinIO 上传失败: {e}'
        print(f'[import] uploaded MinIO: {minio_key}')

        # 5. OCR 解析
        try:
            rows = parse_pdf_tables(local_pdf, max_pages=50)
        except Exception as e:
            return 0, f'OCR 解析异常: {e}'
        if not rows:
            return 0, 'OCR 无数据行'
        print(f'[import] OCR 解析: {len(rows)} 行')

        # 6. 拼 doc + bulk 写
        now = datetime.now().isoformat(timespec='seconds')
        docs = [
            row_to_doc(r, {
                'period':        win['period'],
                'period_start':  win['period_start'],
                'period_end':    win['period_end'],
                'period_days':   win['period_days'],
                'publish_date':  item['publish_date'],
                'pdf_url':       pdf['pdf_url'],
                'minio_key':     minio_key,
            })
            for r in rows
        ]
        ok, err = bulk_index(es, cfg['es']['ods_index'], docs)
        print(f'[import] bulk_index: ok={ok}, err={err}')

    # 7. 写 ES progress
    try:
        es.index(
            index=prog_index,
            body={
                'period':        win['period'],
                'period_start':  win['period_start'],
                'period_end':    win['period_end'],
                'period_days':   win['period_days'],
                'publish_date':  item['publish_date'],
                'detail_url':    item['detail_url'],
                'pdf_url':       pdf['pdf_url'],
                'minio_key':     minio_key,
                'docs_written':  ok,
                'status':        'ok' if err == 0 else 'partial',
                'run_id':        run_id,
                'created_at':    now,
            },
        )
    except Exception as e:
        print(f'[import] ⚠ 写 ES progress 失败: {e}')

    # 8. 写本地进度
    try:
        prog = load_progress()
        if not isinstance(prog, dict):
            prog = {'done': {}}
        prog.setdefault('done', {})
        prog['done'][item['detail_url']] = {
            'status': 'ok' if err == 0 else 'partial',
            'period': win['period'],
            'docs_written': ok,
            'ts': now,
        }
        save_progress(prog)
    except Exception as e:
        print(f'[import] ⚠ 写本地进度失败: {e}')

    return ok, ('ok' if err == 0 else 'partial')


def main():
    parser = argparse.ArgumentParser(description='山西 v1.1 剩余期导入（独立进程版）')
    parser.add_argument('--unit', type=int, default=-1,
                        help='指定处理第 N 个未完成的期（-1 = 全部, 默认）')
    parser.add_argument('--run-id', default='', help='run_id')
    args = parser.parse_args()

    cfg = load_config()
    items = fetch_all_periods(cfg)
    filtered = [it for it in items if should_include(it, cfg)[0]]

    # 过滤掉本地 progress 已 done 的
    from sync import load_progress
    prog = load_progress()
    done_set = set((prog or {}).get('done', {}).keys())
    todo = [it for it in filtered if it['detail_url'] not in done_set]

    print(f'[import] 过滤前 {len(items)} → 标题命中 {len(filtered)} → 未完成 {len(todo)}')

    if not todo:
        print('[import] 无未完成期, 跳过。')
        return

    if args.unit >= 0:
        todo = [todo[args.unit]]
        print(f'[import] 只跑第 {args.unit} 个: {todo[0]["title"]}')

    run_id = args.run_id or f'sx_import_{datetime.now().strftime("%Y%m%d_%H%M%S")}'
    for i, it in enumerate(todo):
        print(f'\n========== [{i+1}/{len(todo)}] {it["title"]} ==========')
        ok, status = import_one(cfg, it, run_id)
        print(f'[import] 结果: {ok} docs / status={status}\n')


if __name__ == '__main__':
    main()
