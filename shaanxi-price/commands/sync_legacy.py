"""陕西工程造价材料信息 - 同步主程序

流程（参考 henan-price）：
1. 抓列表 5 页，提取每期（标题、发布日、详情页、PDF URL）
2. 过滤：未入库 & 指定年份（默认 2026）
3. 对每期：
   a. 下载 PDF → 本地临时文件
   b. 上传 MinIO
   c. 按 city 分发到独立 parser → 长表（材料×规格×单位×城市×区县×价格）
      * 陕西 省本级：parse_shaanxi_province (B 布局)
      * 咸阳：parse_xianyang (B + E 布局)
      * 铜川：parse_tongchuan (C 布局)
      * 渭南：parse_weinan (B 布局)
      * 榆林：parse_yulin (B 布局)
      * 汉中：parse_hanzhong (F + D 布局)
      * 商洛：parse_shangluo (G 布局，pdfplumber)
      * 安康：扫描图像型 PDF，OCR 暂未识别 → 标 skipped_image_pdf
   d. bulk_index 到 ods_material_shaanxi_price（幂等 _id）
   e. 写进度（本地 JSON + ES progress 索引）
"""
import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
import time
from datetime import datetime
from urllib.parse import urljoin

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

from utils import (
    load_config, get_es_client, get_s3_client,
    ensure_bucket, ensure_ods_index, ensure_progress_index,
    fetch_html, download_file, upload_to_minio,
    parse_list_page, parse_detail_page,
    extract_period_from_title, extract_city_from_title,
)
from pdf_parser import parse_pdf_pages, MaterialRow

PROGRESS_FILE = os.path.join(os.path.dirname(SCRIPT_DIR), '.shaanxi_sync_progress.json')

PROVINCE = '陕西'


# ─── 列表抓取 ────────────────────────────────────────────────────────────────
def fetch_all_periods(cfg):
    """抓取所有期（5 页）"""
    site = cfg['site']
    base = site['base_url']
    headers = {
        'User-Agent': site['user_agent'],
        'Referer': site.get('referer', base),
    }
    all_items = []
    for page in range(site['list_pages']):
        if page == 0:
            url = base + site['list_path']
        else:
            url = base + f'/sy/yw/zjglfw/zjxx/index_{page}.html'
        try:
            html = fetch_html(url, headers=headers, timeout=site['timeout_sec'])
            page_items = parse_list_page(html, base + '/sy/yw/zjglfw/zjxx/')
            print(f'  [list] page {page}: {len(page_items)} 期')
            all_items.extend(page_items)
        except Exception as e:
            print(f'  [list] page {page} 失败: {e}')
    # 去重
    seen = set()
    uniq = []
    for it in all_items:
        if it['detail_url'] in seen:
            continue
        seen.add(it['detail_url'])
        uniq.append(it)
    return uniq


# ─── 进度管理 ────────────────────────────────────────────────────────────────
def load_progress():
    if not os.path.exists(PROGRESS_FILE):
        return {'done': {}}
    with open(PROGRESS_FILE) as f:
        return json.load(f)


def save_progress(prog):
    with open(PROGRESS_FILE, 'w') as f:
        json.dump(prog, f, ensure_ascii=False, indent=2)


# ─── 入库 ──────────────────────────────────────────────────────────────────
def _doc_id(period, breed, spec, city, county, code='', unit=''):
    """幂等 _id (v1.0 修复：包含 breed/spec/unit/county 避免 _id 冲突)。

    历史 bug: code 非空时仅用 (period+code+city+county) 作 _id，
    同一 code 在不同 breed/spec/unit 的 row 被 ES bulk upsert 静默去重，
    导致 ~600 条数据丢失。v1.0 加入 breed/spec/unit 拼接。
    """
    raw = f'{period}|{code or "_"}|{breed}|{spec}|{unit}|{city}|{county}'
    return hashlib.md5(raw.encode('utf-8')).hexdigest()


def _is_valid_price(price):
    """防御式校验：材料价格需在 (0, 1_000_000) 区间内。None 视为合法（占位）。

    2026-07-21：曾因 _parse_type_B 的 code 腐蚀 bug 产生 price=360703310、802103301 等
    8 亿级错误数据，落到 ES 后污染 DWS 看板。在写入前最后一道防线卡住异常值。
    """
    if price is None:
        return True
    try:
        v = float(price)
    except (TypeError, ValueError):
        return False
    return 0 < v < 1_000_000


def bulk_index(es, index, docs):
    if not docs:
        return 0, 0
    # v2 (2026-07-21): 防御式过滤 — 剔除明显异常的 price
    filtered = [d for d in docs if _is_valid_price(d.get('price'))]
    skipped = len(docs) - len(filtered)
    if skipped:
        print(f'  [bulk_index] 防御式过滤跳过 {skipped} 条 price 异常记录（不在 0<p<1_000_000）')
    docs = filtered
    if not docs:
        return 0, skipped
    body = ''
    for d in docs:
        # code 为空时（如商洛 G 类型），加 unit 进 _id 避免重复被去重
        code = d.get('code', '') or ''
        extra = '' if code else d.get('unit', '') or ''
        _id = _doc_id(d['period'], d.get('breed', ''), d.get('spec', ''),
                      d.get('city', ''), d.get('county', ''), code, d.get('unit', '') or '')
        body += json.dumps({'index': {'_index': index, '_id': _id}}, ensure_ascii=False) + '\n'
        body += json.dumps(d, ensure_ascii=False) + '\n'
    resp = es.bulk(body=body, refresh=False)
    if resp.get('errors'):
        errors = sum(1 for it in resp['items'] if 'error' in it.get('index', {}))
        return len(docs) - errors, errors
    return len(docs), 0


def row_to_doc(row: MaterialRow, period, city, publish_date, source_pdf, source_url, now):
    """MaterialRow → ES doc"""
    return {
        'code': row.code,
        'breed': row.breed,
        'spec': row.spec,
        'unit': row.unit,
        'category': row.category,
        'price': row.price,
        'tax_price': row.tax_price,
        'period': period,
        'province': PROVINCE,
        'city': city,
        'county': row.county,
        'update_date': publish_date,
        'create_time': now,
        'source_pdf': source_pdf,
        'source_url': source_url,
    }


# ─── 主流程 ────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description='陕西省工程造价材料信息同步')
    parser.add_argument('--period', default='', help='指定 period（如 2026.5月、2026.3期、2026.1期(季刊)）')
    parser.add_argument('--year', type=int, default=0, help='只入指定年份（默认 = config.sync.target_year = 2026，0=不限制）')
    parser.add_argument('--all', action='store_true', help='同步所有未入仓的期')
    parser.add_argument('--reset', action='store_true', help='重置进度')
    parser.add_argument('--dry-run', action='store_true', help='预览，不写入')
    parser.add_argument('--latest', action='store_true', help='只同步最新一期')
    parser.add_argument('--limit', type=int, default=0, help='最多同步 N 期（0=全部）')
    args = parser.parse_args()

    cfg = load_config()
    es_host = cfg['es']['host']
    es = get_es_client(es_host)
    s3 = get_s3_client(cfg)
    if not args.dry_run:
        ensure_bucket(s3, cfg['minio']['bucket'])
        ensure_ods_index(es, cfg['es']['ods_index'])
        ensure_progress_index(es, cfg['es']['progress_index'])

    progress = {'done': {}} if args.reset else load_progress()
    if args.reset:
        save_progress(progress)

    print(f'[shaanxi] ES: {es_host}')
    print(f'[shaanxi] MinIO: {cfg["minio"]["endpoint"]} / {cfg["minio"]["bucket"]}')

    # 0. 默认 year
    if args.year == 0:
        args.year = cfg.get('sync', {}).get('target_year', datetime.now().year)

    # 1. 抓所有期
    print('[shaanxi] 抓取列表...')
    items = fetch_all_periods(cfg)
    print(f'[shaanxi] 共 {len(items)} 期')

    # 2. 过滤
    todo = []
    for it in items:
        # year 过滤
        if args.year and f'{args.year}年' not in it['title']:
            continue
        if args.period and args.period not in it['title']:
            continue
        # 已同步完成 或 主动跳过（图像型 PDF 等）不重试
        # 例外：status='pending_reparse' 允许重跑（手工修改 progress 后）
        prior_status = progress['done'].get(it['detail_url'], {}).get('status')
        if prior_status in ('ok', 'partial', 'skipped_image_pdf'):
            continue
        todo.append(it)
    # pending_reparse 项：不论 title 是否匹配都添加
    for it in items:
        prior_status = progress['done'].get(it['detail_url'], {}).get('status')
        if prior_status == 'pending_reparse':
            if it not in todo:
                todo.append(it)

    if args.latest:
        todo = todo[:1]
    if args.limit and len(todo) > args.limit:
        todo = todo[:args.limit]

    print(f'[shaanxi] 待处理 {len(todo)} 期（year={args.year}）')
    if not todo:
        print('[shaanxi] 无新数据')
        return

    # 3. 逐期处理
    total_written = 0
    for idx, item in enumerate(todo, 1):
        print(f'\n[shaanxi] [{idx}/{len(todo)}] {item["title"]}  ({item["publish_date"]})')
        start = time.time()
        try:
            headers = {
                'User-Agent': cfg['site']['user_agent'],
                'Referer': cfg['site'].get('referer', cfg['site']['base_url']),
            }
            detail_html = fetch_html(item['detail_url'], headers=headers, timeout=cfg['site']['timeout_sec'])
            detail = parse_detail_page(detail_html, item['detail_url'])
            if not detail['pdf_url']:
                raise ValueError('详情页未找到 PDF 链接')
            print(f'  PDF: {detail["pdf_url"]}')

            period = extract_period_from_title(detail['title'] or item['title'])
            if not period:
                raise ValueError(f'无法从标题推断周期: {detail["title"]}')
            city = extract_city_from_title(item['title'], cfg['city_patterns'], cfg['province_label'])
            print(f'  period: {period}, city: {city}')

            #  city 是否有对应 parser？没有则直接标 skipped 并跳过 PDF 下载
            from pdf_parser import CITY_PARSERS as _CITY_PARSERS
            if city not in _CITY_PARSERS:
                print(f'  ⚠ city {city} 无对应 parser（仅 陕西/咸阳/铜川/渭南/榆林/汉中/商洛），跳过')
                now = datetime.now().isoformat(timespec='seconds')
                progress['done'][item['detail_url']] = {
                    'period': period, 'title': item['title'], 'city': city,
                    'publish_date': item['publish_date'], 'detail_url': item['detail_url'],
                    'status': 'skipped_no_parser',
                    'docs_written': 0, 'pages_parsed': 0,
                    'note': f'CITY_PARSERS 未覆盖 {city}，未实现解析器（参考安康 扫描图像型）',
                    'duration_sec': 0, 'created_at': now,
                }
                save_progress(progress)
                if not args.dry_run:
                    try:
                        es.index(index=cfg['es']['progress_index'], body={
                            'period': period, 'title': item['title'], 'city': city,
                            'publish_date': item['publish_date'],
                            'detail_url': item['detail_url'],
                            'status': 'skipped_no_parser',
                            'docs_written': 0, 'pages_parsed': 0,
                            'created_at': now,
                        })
                    except Exception:
                        pass
                continue

            with tempfile.TemporaryDirectory() as tmpdir:
                local_pdf = os.path.join(tmpdir, 'source.pdf')
                download_file(detail['pdf_url'], local_pdf, headers=headers, timeout=180)

                minio_key = f'{cfg["minio"]["prefix"]}/{period}_{detail["pdf_name"]}' if detail['pdf_name'] else f'{cfg["minio"]["prefix"]}/{period}/source.pdf'
                if not args.dry_run:
                    upload_to_minio(s3, cfg['minio']['bucket'], minio_key, local_pdf)
                print(f'  minio: {minio_key}')

                page_results = parse_pdf_pages(local_pdf, city)
                total_rows = sum(len(rows) for _, _, rows in page_results)
                pages_parsed = sum(1 for _, pt, rows in page_results if rows and not pt.startswith('error'))
                # OCR 兑底过（图像型 PDF）但 0 条 → skipped_image_pdf
                ocr_attempted = any(r[3] == 'OCR' for r in page_results) if page_results and len(page_results[0]) > 3 else False
                # 用更可靠的方式判断：从 pdf_parser 模块读 _OCR_CACHE 或重新检查每页 tag
                # parse_pdf_pages 已 strip 过 tag，这里借 pdf_parser 内的全局
                try:
                    from pdf_parser import _OCR_CACHE as _ocr_cache
                    # 估算是否触发过 OCR（任何一页 key 数量 > 0）
                    ocr_attempted = len(_ocr_cache) > 0
                except Exception:
                    pass
                print(f'  parsed: {pages_parsed} pages, {total_rows} rows (OCR: {ocr_attempted})')

                now = datetime.now().isoformat(timespec='seconds')
                docs = []
                for pno, ptype, rows in page_results:
                    if ptype.startswith('error'):
                        continue
                    for row in rows:
                        if row.price is None and row.tax_price is None:
                            continue
                        doc = row_to_doc(row, period, city, item['publish_date'],
                                         minio_key, detail['pdf_url'], now)
                        docs.append(doc)

                # 状态判定优先级：partial > skipped_image_pdf > ok
                # err 初始化（避免 dry-run 路径未赋值）
                err = 0
                ok_n = 0
                if args.dry_run:
                    status = 'dry-run'
                elif len(docs) == 0 and ocr_attempted:
                    status = 'skipped_image_pdf'  # OCR 跑完仍 0 条（图像型 PDF 解析未通）
                else:
                    status = 'ok'

                if args.dry_run:
                    print(f'  [dry-run] 将写 {len(docs)} 条到 {cfg["es"]["ods_index"]}（status={status}）')
                    ok_n = len(docs)
                else:
                    ok_n, err = bulk_index(es, cfg['es']['ods_index'], docs)
                    print(f'  bulk: ok={ok_n}, err={err}（status={status}）')
                    if err > 0:
                        status = 'partial'

                elapsed = time.time() - start
                progress['done'][item['detail_url']] = {
                    'period': period,
                    'title': item['title'],
                    'city': city,
                    'publish_date': item['publish_date'],
                    'detail_url': item['detail_url'],
                    'pdf_url': detail['pdf_url'],
                    'minio_key': minio_key,
                    'docs_written': ok_n,
                    'pages_parsed': pages_parsed,
                    'status': status,
                    'duration_sec': round(elapsed, 1),
                    'created_at': now,
                }
                save_progress(progress)

                if not args.dry_run:
                    es.index(index=cfg['es']['progress_index'], body={
                        'period': period,
                        'title': item['title'],
                        'city': city,
                        'publish_date': item['publish_date'],
                        'detail_url': item['detail_url'],
                        'pdf_url': detail['pdf_url'],
                        'minio_key': minio_key,
                        'docs_written': ok_n,
                        'pages_parsed': pages_parsed,
                        'status': status,
                        'duration_sec': round(elapsed, 1),
                        'created_at': now,
                    })

                total_written += ok_n
                print(f'  done in {elapsed:.1f}s')

        except Exception as e:
            elapsed = time.time() - start
            print(f'  ✗ 失败: {e}')
            progress['done'][item['detail_url']] = {
                'publish_date': item['publish_date'],
                'detail_url': item['detail_url'],
                'status': 'failed',
                'error': str(e),
                'duration_sec': round(elapsed, 1),
            }
            save_progress(progress)

    print(f'\n[shaanxi] 全部完成: total_written={total_written}')


if __name__ == '__main__':
    main()
