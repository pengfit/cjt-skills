"""河南工程造价信息 - 同步主程序

流程：
1. 抓列表 4 页，提取每期（标题、发布日、详情页、PDF URL）
2. 过滤：未入库 & 增量起点之后
3. 对每期：
   a. 下载 PDF → 本地临时文件
   b. 上传 MinIO
   c. pdfplumber 解析 → 长表（材料×规格×单位×18地市价格）
      * 跨页续表：主表页（材料列+地市列1组）+ 续表页（仅地市列1组）拼接
   d. bulk_index 到 ods_material_henan_price（幂等 _id）
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

import pdfplumber
from bs4 import BeautifulSoup

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

from utils import (
    load_config, get_es_client, get_s3_client,
    ensure_bucket, ensure_ods_index, ensure_progress_index,
    fetch_html, download_file, upload_to_minio,
)

PROGRESS_FILE = os.path.join(os.path.dirname(SCRIPT_DIR), '.henan_sync_progress.json')


# 18 个地市（识别"续表页"用）
_CITY_NAMES = {
    '郑州', '濮阳', '周口', '许昌', '新乡', '洛阳', '安阳', '焦作',
    '平顶山', '信阳', '漯河', '驻马店', '南阳', '鹤壁', '三门峡',
    '济源', '开封', '商丘',
}


def _is_city_name(s):
    return s in _CITY_NAMES


# ─── 列表页解析 ────────────────────────────────────────────────────────────────
def parse_list_page(html, base_url):
    """从列表页 HTML 提取每期信息"""
    soup = BeautifulSoup(html, 'html.parser')
    items = []
    for li in soup.select('li.ewb-right-item'):
        a = li.select_one('a[href*="/jcxx/004001/"]')
        if not a:
            continue
        href = a.get('href', '')
        if not re.search(r'/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\.html$', href):
            continue
        title = a.get('title', '') or a.get_text(strip=True)
        date_el = li.select_one('span.ewb-right-date')
        publish_date = date_el.get_text(strip=True) if date_el else ''
        items.append({
            'title': title,
            'publish_date': publish_date,
            'detail_url': urljoin(base_url, href),
        })
    return items


def fetch_all_periods(cfg):
    """抓取所有期（4 页）"""
    site = cfg['site']
    base = site['base_url']
    headers = {'User-Agent': site['user_agent']}
    all_items = []
    for page in range(1, site['list_pages'] + 1):
        if page == 1:
            url = base + site['list_path']
        else:
            url = base + f'/jcxx/004001/{page}.html'
        html = fetch_html(url, headers=headers, timeout=site['timeout_sec'])
        page_items = parse_list_page(html, base)
        print(f'  [list] page {page}: {len(page_items)} 期')
        all_items.extend(page_items)
    # 去重（按 detail_url）
    seen = set()
    uniq = []
    for it in all_items:
        if it['detail_url'] in seen:
            continue
        seen.add(it['detail_url'])
        uniq.append(it)
    return uniq


def parse_detail_page(html, base_url):
    """从详情页提取 PDF 链接 + 标题"""
    soup = BeautifulSoup(html, 'html.parser')
    title_el = soup.select_one('div.ewb-info-tt')
    title = title_el.get_text(strip=True) if title_el else ''
    pdf_a = soup.select_one('div.ewb-mt10 a[href*=".pdf"]')
    pdf_href = pdf_a.get('href', '') if pdf_a else ''
    pdf_url = urljoin(base_url, pdf_href) if pdf_href else ''
    pdf_name = pdf_a.get_text(strip=True) if pdf_a else ''
    return {'title': title, 'pdf_url': pdf_url, 'pdf_name': pdf_name}


def extract_period_from_title(title):
    """从详情页标题提取周期 '2026年3-4月' → '2026.3月'"""
    m = re.search(r'(\d{4})年(\d{1,2})(?:-(\d{1,2}))?月', title)
    if not m:
        return ''
    year, m1, m2 = m.group(1), m.group(2), m.group(3)
    return f'{year}.{int(m1)}月'


# ─── PDF 解析 ────────────────────────────────────────────────────────────────
def parse_pdf_tables(pdf_path, cities):
    """解析 PDF → 长表 [(breed, spec, unit, city, price)]

    PDF 跨页续表设计：
    - 主表页：含"材料名称/型号规格/单位"列 + 一组地市（通常 5 个）→ 该页是某个"材料组"的首页
    - 续表页：仅含地市（通常 13 个），无材料列 → 该页是上一个材料组的续表
    - 每个材料组 = 1 主表页 + 0~1 续表页（该组有 18 个地市价格）
    - 组之间不共享材料行（每组是独立的"水泥"、"砂浆"、"钢材"等分类）
    """
    parsed_pages = []  # [(is_main, page_cities, page_rows)]
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            tables = page.extract_tables() or []
            for tbl in tables:
                result = _parse_one_table(tbl)
                if result is not None:
                    is_main, page_cities, page_rows = result
                    parsed_pages.append((is_main, page_cities, page_rows))

    if not parsed_pages:
        return []

    # 按"材料组"分块：每个主表页开新组，续表页追加到当前组
    groups = []  # [{'main': (cities, rows), 'extra_pages': [(cities, rows), ...]}]
    current = None
    for is_main, page_cities, page_rows in parsed_pages:
        if is_main:
            # 新组
            current = {'main': (page_cities, page_rows), 'extra_pages': []}
            groups.append(current)
        else:
            # 续表页：追加到当前组
            if current is None:
                # 续表页前面没有主表页 → 跳过
                continue
            current['extra_pages'].append((page_cities, page_rows))

    # 每个组独立展开长表
    out = []
    for group in groups:
        main_cities, main_rows = group['main']
        merged = {}  # key=(breed, spec, unit) -> {city: price}
        order = []  # 首次出现的 key 顺序

        # 主表页：填入 5 地市价格
        for seq, breed, spec, unit, prices in main_rows:
            if not breed and not spec and not unit:
                continue
            key = (breed, spec, unit)
            if key not in merged:
                merged[key] = {}
                order.append(key)
            for i, p in enumerate(prices):
                if i < len(main_cities) and p is not None and p > 0:
                    merged[key][main_cities[i]] = p

        # 续表页：按行顺序补全 13 地市
        for ext_cities, ext_rows in group['extra_pages']:
            for i, (seq, breed, spec, unit, prices) in enumerate(ext_rows):
                if i >= len(order):
                    break
                key = order[i]
                for j, p in enumerate(prices):
                    if j < len(ext_cities) and p is not None and p > 0:
                        merged[key][ext_cities[j]] = p

        # 输出该组长表
        for key in order:
            breed, spec, unit = key
            for city, price in merged[key].items():
                out.append({
                    'breed': breed,
                    'spec': spec,
                    'unit': unit,
                    'price': price,
                    'city': city,
                })
    return out


def _parse_one_table(tbl):
    """解析单页 2D 表 → (is_main, page_cities, [(seq, breed, spec, unit, [prices])])"""
    if not tbl or len(tbl) < 1:
        return None

    # 找表头行
    header_idx = None
    is_main = False
    for i, row in enumerate(tbl):
        cells_text = [str(c or '').replace('\n', ' ').strip() for c in row]
        joined = ' '.join(cells_text)
        if '材料名称' in joined and ('型号规格' in joined or '单位' in joined) and '不含税价' in joined:
            header_idx = i
            is_main = True
            break

    if header_idx is None:
        # 续表页：row[0] = 标题行（如'不含税价'），row[1] = 地市名
        # 找前 3 行内含地市名的行作为 city_row
        city_row_idx = None
        for i, row in enumerate(tbl[:3]):
            cells_text = [str(c or '').replace('\n', ' ').strip() for c in row]
            city_count = sum(1 for c in cells_text if _is_city_name(c))
            if city_count >= 3:  # 至少 3 个地市名才认
                city_row_idx = i
                break
        if city_row_idx is None:
            return None
        header_idx = city_row_idx - 1  # 续表页 header_idx 是占位
        is_main = False
        data_start = city_row_idx + 1

    if is_main:
        city_row_idx = header_idx + 1
        data_start = header_idx + 2
    else:
        # city_row_idx 已在上面设置
        pass

    if city_row_idx >= len(tbl):
        return None

    city_cells = [str(c or '').replace('\n', ' ').strip() for c in tbl[city_row_idx]]
    page_cities = []
    for c in city_cells:  # 不跳过第 0 列（续表页第 0 列可能是 None）
        if c and _is_city_name(c):
            page_cities.append(c)
        elif not c:
            continue
    if not page_cities:
        return None

    # 解析数据行
    rows = []
    for row in tbl[data_start:]:
        cells = [str(c or '').replace('\n', ' ').strip() for c in row]
        if not cells or not cells[0]:
            continue
        seq = cells[0]
        if is_main and len(cells) >= 4:
            breed = cells[1]
            spec = cells[2]
            unit = cells[3]
            prices = cells[4:]
        else:
            breed = spec = unit = ''
            prices = cells[1:]

        price_list = []
        for p in prices:
            p = p.strip()
            if not p:
                price_list.append(None)
                continue
            try:
                v = float(p)
                price_list.append(v if v > 0 else None)
            except ValueError:
                price_list.append(None)
        rows.append((seq, breed, spec, unit, price_list))

    return (is_main, page_cities, rows)


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
def _doc_id(period, breed, spec, city, price):
    # 不含 price:同一 (breed, spec, city) 可能多份价格（PDF 同材料跨组出现或行序错位），后写覆盖
    raw = f'{period}|{breed}|{spec}|{city}'
    return hashlib.md5(raw.encode('utf-8')).hexdigest()


def bulk_index(es, index, docs):
    """幂等写入（按 _id upsert）"""
    if not docs:
        return 0, 0
    body = ''
    for d in docs:
        _id = _doc_id(d['period'], d['breed'], d['spec'], d['city'], d['price'])
        body += json.dumps({'index': {'_index': index, '_id': _id}}, ensure_ascii=False) + '\n'
        body += json.dumps(d, ensure_ascii=False) + '\n'
    resp = es.bulk(body=body, refresh=False)
    if resp.get('errors'):
        errors = sum(1 for it in resp['items'] if 'error' in it.get('index', {}))
        return len(docs) - errors, errors
    return len(docs), 0


# ─── 主流程 ────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description='河南工程造价材料信息同步')
    parser.add_argument('--period', default='', help='指定周期（如 2026.3月）')
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

    print(f'[henan] ES: {es_host}')
    print(f'[henan] MinIO: {cfg["minio"]["endpoint"]} / {cfg["minio"]["bucket"]}')

    # 1. 抓所有期
    print('[henan] 抓取列表...')
    items = fetch_all_periods(cfg)
    print(f'[henan] 共 {len(items)} 期')

    # 2. 过滤
    todo = []
    for it in items:
        if args.period and args.period not in it['title']:
            continue
        if it['detail_url'] in progress['done'] and progress['done'][it['detail_url']].get('status') == 'ok':
            continue
        todo.append(it)

    if args.latest:
        todo = todo[:1]

    print(f'[henan] 待处理 {len(todo)} 期')
    if not todo:
        print('[henan] 无新数据')
        return

    # 3. 逐期处理
    cities = cfg['cities']
    total_written = 0
    for idx, item in enumerate(todo, 1):
        print(f'\n[henan] [{idx}/{len(todo)}] {item["title"]}  ({item["publish_date"]})')
        start = time.time()
        try:
            detail_html = fetch_html(item['detail_url'], timeout=cfg['site']['timeout_sec'])
            detail = parse_detail_page(detail_html, cfg['site']['base_url'])
            if not detail['pdf_url']:
                raise ValueError('详情页未找到 PDF 链接')
            print(f'  PDF: {detail["pdf_url"]}')

            with tempfile.TemporaryDirectory() as tmpdir:
                local_pdf = os.path.join(tmpdir, 'source.pdf')
                download_file(detail['pdf_url'], local_pdf, timeout=120)

                period = extract_period_from_title(detail['title'] or item['title'])
                if not period:
                    raise ValueError(f'无法从标题推断周期: {detail["title"]}')
                print(f'  period: {period}')

                minio_key = f'{cfg["minio"]["prefix"]}/{period}/source.pdf'
                if not args.dry_run:
                    upload_to_minio(s3, cfg['minio']['bucket'], minio_key, local_pdf)
                print(f'  minio: {minio_key}')

                pdf_rows = parse_pdf_tables(local_pdf, cities)
                print(f'  parsed: {len(pdf_rows)} 行')

                now = datetime.now().isoformat(timespec='seconds')
                docs = []
                for r in pdf_rows:
                    docs.append({
                        'period': period,
                        'breed': r['breed'],
                        'spec': r['spec'],
                        'unit': r['unit'],
                        'price': r['price'],
                        'city': r['city'],
                        'province': '河南',
                        'update_date': item['publish_date'],
                        'create_time': now,
                        'source_pdf': minio_key,
                        'source_url': detail['pdf_url'],
                    })

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

    print(f'\n[henan] 全部完成: total_written={total_written}')


if __name__ == '__main__':
    main()
