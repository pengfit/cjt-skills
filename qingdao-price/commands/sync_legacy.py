"""青岛工程造价信息 - 同步主程序（v0.8 旧版，逃生通道）

v0.9 (2026-07-03) 起默认走 qingdao_collector.py（SyncRunner 抽象基类化）。
本文件保留 v0.8 写法，仅在 Collector 异常时通过 --legacy 调用。
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
)

PROGRESS_FILE = os.path.join(os.path.dirname(SCRIPT_DIR), '.qingdao_sync_progress.json')


def parse_list_page(html, base_url):
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, 'html.parser')
    items = []
    for li in soup.select('li[trs-attr="chip"]'):
        a = li.select_one('a[href*="t20"][href$=".html"]')
        if not a:
            continue
        href = a.get('href', '')
        title = a.get('title', '') or a.get_text(strip=True)
        date_el = li.select_one('div.div_list_li_width_right')
        publish_date = ''
        if date_el:
            m = re.search(r'\[?(\d{4}-\d{2}-\d{2})\]?', date_el.get_text(strip=True))
            if m:
                publish_date = m.group(1)
        items.append({
            'title': re.sub(r'\s+', ' ', title).strip(),
            'publish_date': publish_date,
            'detail_url': urljoin(base_url, href),
        })
    return items


def fetch_list(cfg):
    site = cfg['site']
    url = site['base_url'] + site['list_path']
    headers = {'User-Agent': site['user_agent']}
    html = fetch_html(url, headers=headers, timeout=site['timeout_sec'])
    items = parse_list_page(html, site['base_url'])
    print(f'  [list] 共 {len(items)} 期')
    seen = set()
    uniq = []
    for it in items:
        if it['detail_url'] in seen:
            continue
        seen.add(it['detail_url'])
        uniq.append(it)
    return uniq


def parse_detail_page(html, base_url, detail_url=None):
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, 'html.parser')
    title_el = soup.select_one('div.head_7 h2')
    title = title_el.get_text(strip=True) if title_el else ''
    pdf_a = None
    for a in soup.select('a[href*=".pdf"]'):
        href = a.get('href', '')
        if href.startswith('./P') or href.startswith('P') or '/P' in href:
            pdf_a = a
            break
    if not pdf_a:
        pdf_a = soup.select_one('a[href*=".pdf"]')
    if not pdf_a:
        return {'title': title, 'pdf_url': '', 'pdf_name': ''}
    href = pdf_a.get('href', '')
    pdf_url = href
    if not pdf_url.startswith('http'):
        pdf_url = urljoin(detail_url or base_url, pdf_url)
    pdf_name = pdf_a.get('download', '') or pdf_a.get_text(strip=True) or os.path.basename(pdf_url)
    return {'title': title, 'pdf_url': pdf_url, 'pdf_name': pdf_name}


def extract_period_from_title(title):
    m = re.search(r'(\d{4})年(\d{1,2})月', title)
    if not m:
        return ''
    return f'{m.group(1)}.{int(m.group(2))}月'


def _parse_price(s):
    if s is None:
        return None
    s = str(s).strip()
    if not s:
        return None
    s = s.replace('￥', '').replace('¥', '').replace(',', '').replace(' ', '')
    try:
        v = float(s)
        return v if v > 0 else None
    except ValueError:
        return None


def _is_header_row(cells):
    if not cells or len(cells) < 4:
        return False
    text = ' '.join(str(c or '').replace('\n', ' ').strip() for c in cells)
    text_compact = text.replace(' ', '').replace('\u3000', '')
    return ('序号' in text_compact
            and ('名称' in text_compact or '名' in text_compact)
            and ('规格' in text_compact or '规' in text_compact)
            and '含税价' in text)


def parse_pdf_tables(pdf_path, vat_rate):
    import pdfplumber
    rows_out = []
    with pdfplumber.open(pdf_path) as pdf:
        for i, page in enumerate(pdf.pages):
            tables = page.extract_tables() or []
            for tbl in tables:
                if not tbl or len(tbl) < 2:
                    continue
                header_idx = None
                for j, row in enumerate(tbl[:3]):
                    if _is_header_row(row):
                        header_idx = j
                        break
                if header_idx is None:
                    continue
                for row in tbl[header_idx + 1:]:
                    cells = [str(c or '').replace('\n', ' ').strip() for c in row]
                    if not cells or not any(cells):
                        continue
                    if len(cells) >= 5:
                        seq, breed, spec, unit, raw_price = cells[:5]
                        tax_price = _parse_price(raw_price)
                    elif len(cells) == 4:
                        seq, breed, spec, unit = cells[:4]
                        tax_price = _parse_price(cells[3]) if _parse_price(cells[3]) else _parse_price(cells[2])
                    else:
                        continue
                    if not breed and not spec:
                        continue
                    if tax_price is None or tax_price <= 0:
                        continue
                    price_excl = round(tax_price / (1 + vat_rate), 2)
                    rows_out.append({
                        'breed': breed, 'spec': spec, 'unit': unit,
                        'price': price_excl, 'tax_price': tax_price,
                    })
    return rows_out


def load_progress():
    if not os.path.exists(PROGRESS_FILE):
        return {'done': {}}
    with open(PROGRESS_FILE) as f:
        return json.load(f)


def save_progress(prog):
    with open(PROGRESS_FILE, 'w') as f:
        json.dump(prog, f, ensure_ascii=False, indent=2)


def _doc_id(period, breed, spec, unit, price):
    raw = f'{period}|{breed}|{spec}|{unit}|{price}'
    return hashlib.md5(raw.encode('utf-8')).hexdigest()


def bulk_index(es, index, docs):
    if not docs:
        return 0, 0
    body = ''
    for d in docs:
        _id = _doc_id(d['period'], d['breed'], d['spec'], d['unit'], d['price'])
        body += json.dumps({'index': {'_index': index, '_id': _id}}, ensure_ascii=False) + '\n'
        body += json.dumps(d, ensure_ascii=False) + '\n'
    resp = es.bulk(body=body, refresh=False)
    if resp.get('errors'):
        errors = sum(1 for it in resp['items'] if 'error' in it.get('index', {}))
        return len(docs) - errors, errors
    return len(docs), 0


def main():
    parser = argparse.ArgumentParser(description='青岛工程造价材料信息同步（v0.8 legacy）')
    parser.add_argument('--period', default='')
    parser.add_argument('--year', type=int, default=None)
    parser.add_argument('--all', action='store_true')
    parser.add_argument('--reset', action='store_true')
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--latest', action='store_true')
    args = parser.parse_args()

    cfg = load_config()
    es_host = cfg['es']['host']
    es = get_es_client(es_host)
    s3 = get_s3_client(cfg)
    ensure_bucket(s3, cfg['minio']['bucket'])
    ensure_ods_index(es, es_host, cfg['es']['ods_index'])
    ensure_progress_index(es, cfg['es']['progress_index'])

    progress = {'done': {}} if args.reset else load_progress()
    if args.reset:
        save_progress(progress)

    if args.year is None:
        args.year = cfg.get('sync', {}).get('default_year', 0) or 0

    print(f'[qingdao/legacy] ES: {es_host}  vat={cfg.get("vat", {}).get("rate", 0.09)}  year_filter={args.year}')

    items = fetch_list(cfg)
    todo = []
    for it in items:
        if args.period and args.period not in it['title']:
            continue
        if args.year and f'{args.year}年' not in it['title']:
            continue
        if it['detail_url'] in progress['done'] and progress['done'][it['detail_url']].get('status') == 'ok':
            continue
        todo.append(it)
    if args.latest:
        todo = todo[:1]

    print(f'[qingdao/legacy] 待处理 {len(todo)} 期')
    if not todo:
        print('[qingdao/legacy] 无新数据')
        return

    vat_rate = cfg.get('vat', {}).get('rate', 0.09)
    city = cfg.get('city', '青岛')
    province = cfg.get('province', '山东')
    total_written = 0
    for idx, item in enumerate(todo, 1):
        print(f'\n[qingdao/legacy] [{idx}/{len(todo)}] {item["title"]}  ({item["publish_date"]})')
        start = time.time()
        try:
            detail_html = fetch_html(item['detail_url'],
                headers={'User-Agent': cfg['site']['user_agent']},
                timeout=cfg['site']['timeout_sec'])
            detail = parse_detail_page(detail_html, cfg['site']['base_url'], detail_url=item['detail_url'])
            if not detail['pdf_url']:
                raise ValueError('详情页未找到 PDF 链接')
            print(f'  PDF: {detail["pdf_url"]}')

            with tempfile.TemporaryDirectory() as tmpdir:
                local_pdf = os.path.join(tmpdir, 'source.pdf')
                download_file(detail['pdf_url'], local_pdf, referer=item['detail_url'], timeout=120)
                if os.path.getsize(local_pdf) < 1024:
                    raise ValueError(f'PDF 太小（{os.path.getsize(local_pdf)} bytes）')

                period = extract_period_from_title(detail['title'] or item['title'])
                if not period:
                    raise ValueError(f'无法从标题推断周期: {detail["title"]}')
                print(f'  period: {period}')

                minio_key = f'{cfg["minio"]["prefix"]}/{period}/{detail["pdf_name"]}' if detail['pdf_name'] else f'{cfg["minio"]["prefix"]}/{period}/source.pdf'
                if not args.dry_run:
                    upload_to_minio(s3, cfg['minio']['bucket'], minio_key, local_pdf)

                pdf_rows = parse_pdf_tables(local_pdf, vat_rate)
                print(f'  parsed: {len(pdf_rows)} 行')

                now = datetime.now().isoformat(timespec='seconds')
                docs = []
                for r in pdf_rows:
                    docs.append({
                        'period': period, 'breed': r['breed'], 'spec': r['spec'],
                        'unit': r['unit'], 'price': r['price'], 'tax_price': r['tax_price'],
                        'city': city, 'province': province,
                        'update_date': item['publish_date'], 'create_time': now,
                        'source_pdf': minio_key, 'source_url': detail['pdf_url'],
                    })

                if args.dry_run:
                    print(f'  [dry-run] 将写 {len(docs)} 条')
                    ok, err = len(docs), 0
                else:
                    ok, err = bulk_index(es, cfg['es']['ods_index'], docs)
                    print(f'  bulk: ok={ok}, err={err}')

                elapsed = time.time() - start
                progress['done'][item['detail_url']] = {
                    'period': period, 'publish_date': item['publish_date'],
                    'detail_url': item['detail_url'], 'pdf_url': detail['pdf_url'],
                    'minio_key': minio_key, 'docs_written': ok,
                    'status': 'ok' if err == 0 else 'partial',
                    'duration_sec': round(elapsed, 1), 'created_at': now,
                }
                save_progress(progress)
                if not args.dry_run:
                    es.index(index=cfg['es']['progress_index'], body={
                        'period': period, 'publish_date': item['publish_date'],
                        'detail_url': item['detail_url'], 'pdf_url': detail['pdf_url'],
                        'minio_key': minio_key, 'docs_written': ok,
                        'status': 'ok' if err == 0 else 'partial',
                        'duration_sec': round(elapsed, 1), 'created_at': now,
                    })
                total_written += ok
                print(f'  done in {elapsed:.1f}s')
        except Exception as e:
            print(f'  ✗ 失败: {e}')
            progress['done'][item['detail_url']] = {
                'publish_date': item['publish_date'], 'detail_url': item['detail_url'],
                'status': 'failed', 'error': str(e),
            }
            save_progress(progress)

    print(f'\n[qingdao/legacy] 全部完成: total_written={total_written}')


if __name__ == '__main__':
    main()
