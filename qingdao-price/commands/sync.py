"""青岛工程造价信息 - 同步主程序

流程：
1. 抓列表页（无分页），提取每期（标题、发布日、详情页 URL）
2. 过滤：未入库 & 增量起点之后 & 目标年份
3. 对每期：
   a. 访问详情页 → 解析 PDF 链接
   b. 下载 PDF（需 Referer 头）→ 本地临时文件
   c. 上传 MinIO
   d. pdfplumber 解析 → 长表（材料×规格×单位×含税价/不含税价）
      * 每页一个分类（一/钢材、二/水泥、三/门窗……）
      * 表头固定：序号|名称|规格型号|单位|含税价(元)
   e. bulk_index 到 ods_material_qingdao_price（幂等 _id）
   f. 写进度（本地 JSON + ES progress 索引）
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

import pdfplumber
import requests
from bs4 import BeautifulSoup

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

from utils import (
    load_config, get_es_client, get_s3_client,
    ensure_bucket, ensure_ods_index, ensure_progress_index,
    fetch_html, download_file, upload_to_minio,
)

PROGRESS_FILE = os.path.join(os.path.dirname(SCRIPT_DIR), '.qingdao_sync_progress.json')


# ─── 列表页解析 ────────────────────────────────────────────────────────────────
def parse_list_page(html, base_url):
    """从列表页 HTML 提取每期信息

    列表项结构：
      <li trs-attr="chip"> <a target="_blank" href="...t{YYYYMMDD}_{ID}.html"
        title="2026年M月青岛市建设工程材料价格">
          <div class='div_float_left hi-ellipses div_list_li_width_left'>2026年M月青岛市建设工程材料价格</div>
          <div class='div_float_left div_list_li_width_right'>[YYYY-MM-DD]</div>
        </a> </li>
    """
    soup = BeautifulSoup(html, 'html.parser')
    items = []
    for li in soup.select('li[trs-attr="chip"]'):
        a = li.select_one('a[href*="t20"][href$=".html"]')
        if not a:
            continue
        href = a.get('href', '')
        title = a.get('title', '') or a.get_text(strip=True)
        # 发布日期在 div.div_list_li_width_right 里，形如 [2026-06-09]
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
    """抓取所有期（青岛住建局列表无分页，单页 15 期左右）"""
    site = cfg['site']
    url = site['base_url'] + site['list_path']
    headers = {'User-Agent': site['user_agent']}
    html = fetch_html(url, headers=headers, timeout=site['timeout_sec'])
    items = parse_list_page(html, site['base_url'])
    print(f'  [list] 共 {len(items)} 期')
    # 去重
    seen = set()
    uniq = []
    for it in items:
        if it['detail_url'] in seen:
            continue
        seen.add(it['detail_url'])
        uniq.append(it)
    return uniq


def parse_detail_page(html, base_url, detail_url=None):
    """从详情页提取 PDF 链接 + 标题

    详情页 PDF 链接结构：
      <a appendix="true" data-appendix="true" href="./P{YYYYMMDD}{ID}.pdf"
         oldsrc="/protect/P{YYYYMMDD-prefixed-path}/P{YYYYMMDD}{ID}.pdf"
         download="2026年5月青岛市建设工程材料价格.pdf">...</a>

    实测：`href`（相对路径 /YYYYMM/P{...}.pdf）可用；
          `oldsrc`（绝对路径 /protect/...）返回 404 Not Found。
    所以优先用 `href`，且必须用 detail_url 而非 base_url 做 urljoin（PDF 在详情页同目录）。
    """
    soup = BeautifulSoup(html, 'html.parser')
    title_el = soup.select_one('div.head_7 h2')
    title = title_el.get_text(strip=True) if title_el else ''
    # 找带 appendix 属性的 <a>，href 含 .pdf
    pdf_a = None
    for a in soup.select('a[href*=".pdf"]'):
        href = a.get('href', '')
        if href.startswith('./P') or href.startswith('P') or '/P' in href:
            pdf_a = a
            break
    if not pdf_a:
        # 兜底：第一个含 .pdf 的 a
        pdf_a = soup.select_one('a[href*=".pdf"]')
    if not pdf_a:
        return {'title': title, 'pdf_url': '', 'pdf_name': ''}

    href = pdf_a.get('href', '')
    # 优先 href（实测可用），fallback 到 oldsrc（通常 404）
    pdf_url = href
    if not pdf_url.startswith('http'):
        # 用 detail_url 做 urljoin（PDF 在详情页同目录，base_url 解析会丢 /YYYYMM/ 路径）
        pdf_url = urljoin(detail_url or base_url, pdf_url)

    pdf_name = pdf_a.get('download', '') or pdf_a.get_text(strip=True) or os.path.basename(pdf_url)
    return {'title': title, 'pdf_url': pdf_url, 'pdf_name': pdf_name}


def extract_period_from_title(title):
    """从详情页标题提取周期 '2026年5月青岛市建设工程材料价格' → '2026.5月'"""
    m = re.search(r'(\d{4})年(\d{1,2})月', title)
    if not m:
        return ''
    return f'{m.group(1)}.{int(m.group(2))}月'


# ─── PDF 解析 ────────────────────────────────────────────────────────────────
def _parse_price(s):
    """从含中文符号/逗号的字符串中提取 float，失败返回 None"""
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
    """判断一行是否是 5 列表头：序号|名称|规格型号|单位|含税价(元)

    注意青岛 PDF 实际表头：'序号' / '名 称'（中间带空格）/ '规 格 型 号'（中间带空格）/ '单位' / '含税价 (元)'
    """
    if not cells or len(cells) < 4:
        return False
    text = ' '.join(str(c or '').replace('\n', ' ').strip() for c in cells)
    # 去掉所有空白后做包含检查
    text_compact = text.replace(' ', '').replace('\u3000', '')
    return ('序号' in text_compact
            and ('名称' in text_compact or '名' in text_compact)
            and ('规格' in text_compact or '规' in text_compact)
            and '含税价' in text)


def parse_pdf_tables(pdf_path, vat_rate):
    """解析 PDF → 长表 [(breed, spec, unit, price, tax_price)]

    青岛 PDF 结构：
      - Page 1: 文字分析，无表格
      - Page 2: 走势图，无有效表格
      - Page 3-8: 材料价格表，表头固定 [序号|名称|规格型号|单位|含税价(元)]
      - 每页一个分类（钢材/水泥/门窗/.../装饰/.../安装）
      - 全部为含税价 → 按 vat_rate 反推 price
    """
    rows_out = []
    with pdfplumber.open(pdf_path) as pdf:
        for i, page in enumerate(pdf.pages):
            tables = page.extract_tables() or []
            for tbl in tables:
                if not tbl or len(tbl) < 2:
                    continue
                # 找表头
                header_idx = None
                for j, row in enumerate(tbl[:3]):
                    if _is_header_row(row):
                        header_idx = j
                        break
                if header_idx is None:
                    continue
                # 数据行
                for row in tbl[header_idx + 1:]:
                    cells = [str(c or '').replace('\n', ' ').strip() for c in row]
                    if not cells or not any(cells):
                        continue
                    # 标准 5 列：序号|名称|规格型号|单位|含税价
                    if len(cells) >= 5:
                        seq, breed, spec, unit, raw_price = cells[:5]
                        tax_price = _parse_price(raw_price)
                    elif len(cells) == 4:
                        # 容错：可能首列是 序号|breed|spec|unit|price 被压成 4 列
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
                        'breed': breed,
                        'spec': spec,
                        'unit': unit,
                        'price': price_excl,
                        'tax_price': tax_price,
                    })
    return rows_out


# ─── 进度管理 ────────────────────────────────────────────────────────────────
def load_progress():
    if not os.path.exists(PROGRESS_FILE):
        return {'done': {}}
    with open(PROGRESS_FILE) as f:
        return json.load(f)


def save_progress(prog):
    with open(PROGRESS_FILE, 'w') as f:
        json.dump(prog, f, ensure_ascii=False, indent=2)


# ─── 入库 ────────────────────────────────────────────────────────────────
def _doc_id(period, breed, spec, unit, price):
    raw = f'{period}|{breed}|{spec}|{unit}|{price}'
    return hashlib.md5(raw.encode('utf-8')).hexdigest()


def bulk_index(es, index, docs):
    """幂等写入（按 _id upsert）"""
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


# ─── 主流程 ────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description='青岛工程造价材料信息同步')
    parser.add_argument('--period', default='', help='指定周期（如 2026.5月）')
    parser.add_argument('--year', type=int, default=None, help='只入库指定年份（默认走 config.yml 的 default_year，0=不限制）')
    parser.add_argument('--all', action='store_true', help='同步所有未入仓的期')
    parser.add_argument('--reset', action='store_true', help='重置进度')
    parser.add_argument('--dry-run', action='store_true', help='预览，不写入')
    parser.add_argument('--latest', action='store_true', help='只同步最新一期')
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

    # 年份默认：config.yml 的 default_year（道友好 2026）
    if args.year is None:
        args.year = cfg.get('sync', {}).get('default_year', 0) or 0

    print(f'[qingdao] ES: {es_host}')
    print(f'[qingdao] MinIO: {cfg["minio"]["endpoint"]} / {cfg["minio"]["bucket"]}')
    print(f'[qingdao] city={cfg.get("city", "青岛")}  province={cfg.get("province", "山东")}  '
          f'vat={cfg.get("vat", {}).get("rate", 0.09)}  year_filter={args.year}')

    # 1. 抓所有期
    print('[qingdao] 抓取列表...')
    items = fetch_list(cfg)
    print(f'[qingdao] 共 {len(items)} 期')

    # 2. 过滤
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

    print(f'[qingdao] 待处理 {len(todo)} 期')
    if not todo:
        print('[qingdao] 无新数据')
        return

    # 3. 逐期处理
    vat_rate = cfg.get('vat', {}).get('rate', 0.09)
    city = cfg.get('city', '青岛')
    province = cfg.get('province', '山东')
    total_written = 0
    for idx, item in enumerate(todo, 1):
        print(f'\n[qingdao] [{idx}/{len(todo)}] {item["title"]}  ({item["publish_date"]})')
        start = time.time()
        try:
            detail_html = fetch_html(
                item['detail_url'],
                headers={'User-Agent': cfg['site']['user_agent']},
                timeout=cfg['site']['timeout_sec'],
            )
            detail = parse_detail_page(detail_html, cfg['site']['base_url'], detail_url=item['detail_url'])
            if not detail['pdf_url']:
                raise ValueError('详情页未找到 PDF 链接')
            print(f'  PDF: {detail["pdf_url"]}')

            with tempfile.TemporaryDirectory() as tmpdir:
                local_pdf = os.path.join(tmpdir, 'source.pdf')
                # 关键：青岛住建局 PDF 必须带 Referer 头指向详情页
                download_file(
                    detail['pdf_url'],
                    local_pdf,
                    referer=item['detail_url'],
                    timeout=120,
                )
                # 验证下载到的是 PDF
                if os.path.getsize(local_pdf) < 1024:
                    raise ValueError(f'PDF 太小（{os.path.getsize(local_pdf)} bytes），可能下载失败')

                period = extract_period_from_title(detail['title'] or item['title'])
                if not period:
                    raise ValueError(f'无法从标题推断周期: {detail["title"]}')
                print(f'  period: {period}')

                minio_key = f'{cfg["minio"]["prefix"]}/{period}/{detail["pdf_name"]}' if detail['pdf_name'] else f'{cfg["minio"]["prefix"]}/{period}/source.pdf'
                if not args.dry_run:
                    upload_to_minio(s3, cfg['minio']['bucket'], minio_key, local_pdf)
                print(f'  minio: {minio_key}')

                pdf_rows = parse_pdf_tables(local_pdf, vat_rate)
                print(f'  parsed: {len(pdf_rows)} 行')

                now = datetime.now().isoformat(timespec='seconds')
                docs = []
                for r in pdf_rows:
                    doc = {
                        'period': period,
                        'breed': r['breed'],
                        'spec': r['spec'],
                        'unit': r['unit'],
                        'price': r['price'],
                        'tax_price': r['tax_price'],
                        'city': city,
                        'province': province,
                        'update_date': item['publish_date'],
                        'create_time': now,
                        'source_pdf': minio_key,
                        'source_url': detail['pdf_url'],
                    }
                    docs.append(doc)

                if args.dry_run:
                    print(f'  [dry-run] 将写 {len(docs)} 条到 {cfg["es"]["ods_index"]}')
                    ok = len(docs)
                    err = 0
                else:
                    ok, err = bulk_index(es, cfg['es']['ods_index'], docs)
                    print(f'  bulk: ok={ok}, err={err}')

                elapsed = time.time() - start
                progress['done'][item['detail_url']] = {
                    'period': period,
                    'publish_date': item['publish_date'],
                    'detail_url': item['detail_url'],
                    'pdf_url': detail['pdf_url'],
                    'minio_key': minio_key,
                    'docs_written': ok,
                    'status': 'ok' if err == 0 else 'partial',
                    'duration_sec': round(elapsed, 1),
                    'created_at': now,
                }
                save_progress(progress)

                if not args.dry_run:
                    es.index(index=cfg['es']['progress_index'], body={
                        'period': period,
                        'publish_date': item['publish_date'],
                        'detail_url': item['detail_url'],
                        'pdf_url': detail['pdf_url'],
                        'minio_key': minio_key,
                        'docs_written': ok,
                        'status': 'ok' if err == 0 else 'partial',
                        'duration_sec': round(elapsed, 1),
                        'created_at': now,
                    })

                total_written += ok
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

    print(f'\n[qingdao] 全部完成: total_written={total_written}')


if __name__ == '__main__':
    main()
