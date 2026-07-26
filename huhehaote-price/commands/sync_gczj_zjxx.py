#!/usr/bin/env python3
"""呼和浩特 · 建设工程造价信息 增量同步（v0.1, 2026-07-26）

只抓「建设工程造价信息」系列（双月刊主刊），排除「信息价1期」等散刊。
独立 progress 文件（.huhehaote_gczj_sync_progress.json），可与原 sync 并行。

用法:
  ./run.sh sync-gczj                  # 增量同步（默认）
  ./run.sh sync-gczj --reset           # 重置进度，重抓全量
  ./run.sh sync-gczj --dry-run         # 只看不写
  ./run.sh sync-gczj --latest          # 只同步最新一期

复用 sync.py 的 fetch/parse 工具:
  - parse_list_page / fetch_all_periods
  - fetch_detail_pdf / pdf_basename
  - parse_pdf
"""
import argparse
import json
import os
import sys
import time
from datetime import datetime
from urllib.parse import urljoin

import pdfplumber

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

# 复用 sync.py 的工具
from sync import (
    parse_list_page, fetch_all_periods,
    fetch_detail_pdf, pdf_basename, parse_pdf,
)
from utils import (
    load_config, get_es_client, get_s3_client,
    ensure_bucket, ensure_ods_index,
    fetch_html, download_file, upload_to_minio,
    apply_smart_split,
)

PROGRESS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '.huhehaote_gczj_sync_progress.json')

# 建设工程造价信息 系列标题匹配（精确含「建设工程造价信息」且不含「信息价」散刊关键字）
SERIES_TITLE_KEYWORD = '建设工程造价信息'
SERIES_TITLE_EXCLUDE = ['信息价']  # 排除「2026年信息价1期」等散刊


def filter_gczj_zjxx(items):
    """只保留「建设工程造价信息」系列（双月刊主刊）"""
    out = []
    for it in items:
        title = it.get('title', '')
        if SERIES_TITLE_KEYWORD not in title:
            continue
        if any(kw in title for kw in SERIES_TITLE_EXCLUDE):
            continue
        out.append(it)
    return out


def load_progress():
    if not os.path.exists(PROGRESS_FILE):
        return {'done': {}}
    with open(PROGRESS_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)


def save_progress(prog):
    with open(PROGRESS_FILE, 'w', encoding='utf-8') as f:
        json.dump(prog, f, ensure_ascii=False, indent=2)


def main():
    parser = argparse.ArgumentParser(description='呼和浩特 建设工程造价信息 增量同步')
    parser.add_argument('--reset', action='store_true', help='重置本地进度')
    parser.add_argument('--dry-run', action='store_true', help='预览，不写入')
    parser.add_argument('--latest', action='store_true', help='只同步最新一期')
    parser.add_argument('--run-id', default='', help='指定 run_id')
    parser.add_argument('--max-periods', type=int, default=0, help='最多处理几个期')
    args = parser.parse_args()

    cfg = load_config()
    es_host = cfg['es']['host']
    es = get_es_client(es_host)
    s3 = get_s3_client(cfg)
    ensure_bucket(s3, cfg['minio']['bucket'])

    run_id = args.run_id or f"hhht_gczj_run_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    print(f'[gczj-zjxx v0.1] run_id={run_id}')
    print(f'  PROGRESS_FILE={PROGRESS_FILE}')

    progress = {'done': {}} if args.reset else load_progress()
    if args.reset:
        save_progress(progress)

    # 1) 抓列表
    items = fetch_all_periods(cfg)
    items = filter_gczj_zjxx(items)
    print(f'  [list] 「建设工程造价信息」系列: {len(items)} 期')
    for it in items:
        print(f'    - {it["publish_date"]}  {it["title"][:40]}  {it["detail_url"][-40:]}')

    if args.latest and items:
        items = [items[0]]
        print(f'  [latest] 只取最新: {items[0]["title"]}')

    if args.max_periods > 0:
        items = items[:args.max_periods]
        print(f'  [max-periods] 截断: {len(items)} 期')

    # 2) 跳过已 done 的
    todo = []
    for it in items:
        key = it['detail_url']
        if key in progress['done'] and progress['done'][key].get('status') == 'ok':
            print(f'  [skip] 已同步: {it["title"][:30]}')
            continue
        todo.append(it)
    print(f'  [todo] 待处理 {len(todo)} 期')

    if not todo:
        print('[done] 无新期，退出')
        return 0

    # 3) 逐期处理：详情 → PDF → 解析 → ES
    import tempfile
    ensure_ods_index(es, es_host, cfg['es']['ods_index'])

    summary = {'synced': 0, 'failed': 0, 'skipped': 0, 'rows': 0}
    for it in todo:
        title, pdf_url, _ = fetch_detail_pdf(cfg, it['detail_url'])
        if not pdf_url:
            print(f'  [fail] 无 PDF 链接: {it["detail_url"]}')
            progress['done'][it['detail_url']] = {'status': 'no_pdf', 'title': it['title'], 'ts': time.time()}
            save_progress(progress)
            summary['failed'] += 1
            continue

        # PDF → MinIO（可选）/ 本地临时
        pdf_name = pdf_basename(pdf_url)
        with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as tf:
            tmp_path = tf.name
        try:
            download_file(pdf_url, tmp_path, headers={'User-Agent': cfg['site']['user_agent']})
            # 上传 MinIO
            if not args.dry_run:
                s3_key = upload_to_minio(s3, cfg['minio']['bucket'], f'{cfg["minio"]["prefix"]}/{pdf_name}', tmp_path)
            else:
                s3_key = None
            # 解析
            rows = parse_pdf(tmp_path)
            print(f'  [parse] {it["title"][:30]} → {len(rows)} 行  pdf={pdf_name}')
            summary['rows'] += len(rows)
            if not args.dry_run:
                # 写 ES (ods_material_huhehaote_price)
                ods_idx = cfg['es']['ods_index']
                # v0.3 (2026-07-26): 空格拆分 breed — "钢筋HRB400E Φ8" → breed="钢筋HRB400E" spec="Φ8"
# 源 PDF 表格里“空格分词”是常见模式（材料名后跟规格），不拆会成1 个 breed 占多行（综合/DN50 等 121 条 miss 都是这个原因）
                def _split_breed_spec(r):
                    return apply_smart_split(r)

                # 补充元数据 (严格遵循 ods_material_huhehaote_price 的 strict whitelist)
                whitelist_extras = set()  # 记录要删的字段
                for r in rows:
                    r['source_url'] = it['detail_url']
                    r['source_pdf'] = pdf_url
                    r['source_file'] = pdf_name
                    r['published_at'] = it['publish_date']
                    r['run_id'] = run_id
                    r['source'] = 'huhehaote_gczj_zjxx'  # 用 whitelist 字段区分系列
                    # v0.2 (2026-07-26): 补 period_start = published_at 月初, 给 ETL→DWD→DWS→NORM 链路用
                    # 之前漏了 period_start 导致新 doc 无法被 ETL 处理,热力图不出数据
                    if it['publish_date']:
                        r['period_start'] = it['publish_date'][:7] + '-01'
                    # v0.4 (2026-07-26): 智能拆分 breed/spec (通用正则 + 领域特例) — 委托给 utils.apply_smart_split
                    _split_breed_spec(r)
                    # 删除非 whitelist 字段 (strict mapping 会拒收)
                    whitelist_extras.update([
                        'period_source_url', 'period_pdf_url', 'period_pdf_name',
                        'period_publish_date', 'series',
                    ])
                    for k in whitelist_extras:
                        r.pop(k, None)
                    # spec_origin 是 parse_pdf 加的审计标记，不在 whitelist，必须删
                    r.pop('spec_origin', None)
                # bulk 写入
                from elasticsearch.helpers import bulk
                actions = [{'_op_type': 'index', '_index': ods_idx, '_source': r} for r in rows]
                ok, fail = bulk(es, actions, raise_on_error=False, stats_only=True)
                print(f'  [bulk] 写入 {ok} 条 / fail {fail}')
                summary['synced'] += 1
                if fail:
                    summary['failed'] += 1
            progress['done'][it['detail_url']] = {
                'status': 'ok',
                'title': it['title'],
                'pdf_url': pdf_url,
                'rows': len(rows),
                'ts': time.time(),
            }
            save_progress(progress)
        finally:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass

    print(f'\n[gczj-zjxx] 完成: {summary}')
    return 0 if summary['failed'] == 0 else 2


if __name__ == '__main__':
    sys.exit(main())