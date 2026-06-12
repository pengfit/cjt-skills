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
# 河南省 PDF 多格式：
#   1. 不含税价 18 城市表：主表页（5 地市）+ 续表页（13 地市）。规格/单位列1组，跨页续表。
#   2. 不含税价/含税价 4-5 列单价表（苗木、消防、装饰、安装等）：只有 1 列价格，无地市拆分。
#   3. 特殊表：8 列并排双列表、6 列带中间计数列、5 列带 序号 列。
# 表 2/3 类是"全省指导价"，city 统一记为 "河南"，同时存储 tax_price（含税价）。
PROVINCE_CITY = '河南'   # 全省指导价统一使用该 city 标签
VAT_RATE = 0.09          # 建设工程材料增值税税率


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


def parse_pdf_tables(pdf_path, cities):
    """解析 PDF → 长表 [(breed, spec, unit, city, price, tax_price?)]

    返回 long 列表。条目的 key：
      - breed, spec, unit, city, price
      - tax_price: 当表是含税价时才设置；不设则表明原始表是不含税价
    """
    parsed_pages = []  # [(fmt, page_info)]
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            tables = page.extract_tables() or []
            for tbl in tables:
                result = _parse_one_table(tbl)
                if result is not None:
                    parsed_pages.append(result)

    if not parsed_pages:
        return []

    # 按"材料组"分块。main 18 城市表需要续表；其他格式都独立输出。
    groups = []  # list of dict
    current_multi = None  # 18-city 续表结构：{'main': (cities, rows), 'extra': [...], 'tax_inclusive': bool}
    last_single = None    # 上一个单价格式，用于续表

    for item in parsed_pages:
        fmt = item[0]
        if fmt == 'multi_city':
            # 多城市表：18 城市拆 5+13。新组。
            _, page_cities, page_rows, tax_inclusive = item
            current_multi = {
                'kind': 'multi_city',
                'main': (page_cities, page_rows),
                'extra': [],
                'tax_inclusive': tax_inclusive,
            }
            groups.append(current_multi)
            last_single = None
        elif fmt == 'multi_city_cont':
            # 18 城市续表：追加到当前 multi
            _, page_cities, page_rows = item
            if current_multi is not None:
                current_multi['extra'].append((page_cities, page_rows))
            last_single = None
        elif fmt == 'single_price':
            # 单价格式：独立组
            _, page_rows, tax_inclusive = item
            last_single = {
                'kind': 'single_price',
                'rows': page_rows,
                'tax_inclusive': tax_inclusive,
            }
            groups.append(last_single)
            current_multi = None
        elif fmt == 'single_price_cont':
            # 单价续表（无表头）：追加到上一个 single
            _, page_rows = item
            if last_single is not None and last_single['kind'] == 'single_price':
                last_single['rows'].extend(page_rows)
            # 如果上一个不是 single_price，丢弃

    # 每个组独立展开长表
    out = []
    for group in groups:
        if group['kind'] == 'multi_city':
            out.extend(_expand_multi_city_group(group))
        else:
            out.extend(_expand_single_price_group(group))
    return out


def _expand_multi_city_group(group):
    """18 城市主表 + 续表：每个材料产生 18 个 city 价格条目。"""
    main_cities, main_rows = group['main']
    tax_inclusive = group.get('tax_inclusive', False)
    merged = {}
    order = []
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
    for ext_cities, ext_rows in group['extra']:
        for i, (seq, breed, spec, unit, prices) in enumerate(ext_rows):
            if i >= len(order):
                break
            key = order[i]
            for j, p in enumerate(prices):
                if j < len(ext_cities) and p is not None and p > 0:
                    merged[key][ext_cities[j]] = p
    out = []
    for key in order:
        breed, spec, unit = key
        for city, price in merged[key].items():
            rec = {
                'breed': breed, 'spec': spec, 'unit': unit,
                'city': city, 'price': price,
            }
            if tax_inclusive:
                rec['tax_price'] = price
                rec['price'] = round(price / (1 + VAT_RATE), 2)
            out.append(rec)
    return out


def _expand_single_price_group(group):
    """单价表（4-5 列）：每行 = 1 个材料 + 1 个价格。city 记为 '河南'。"""
    tax_inclusive = group.get('tax_inclusive', False)
    out = []
    for row in group['rows']:
        # row = (breed, spec, unit, price, raw_breed)  -- raw_breed 用于空列继承
        breed, spec, unit, price, raw_breed = row
        if not breed and not spec and not unit:
            continue
        if price is None or price <= 0:
            continue
        rec = {
            'breed': breed, 'spec': spec, 'unit': unit,
            'city': PROVINCE_CITY, 'price': price,
        }
        if tax_inclusive:
            rec['tax_price'] = price
            rec['price'] = round(price / (1 + VAT_RATE), 2)
        out.append(rec)
    return out


def _parse_one_table(tbl):
    """解析单页 2D 表 → 多种格式元组。

    返回值：
      ('multi_city', page_cities, rows, tax_inclusive)   18 城市主表
      ('multi_city_cont', page_cities, rows)             18 城市续表
      ('single_price', rows, tax_inclusive)              全省指导价主表（4-5 列）
      ('single_price_cont', rows)                        全省指导价续表（无表头）
      None                                              无法识别
    """
    if not tbl or len(tbl) < 1:
        return None

    # ── 检测表头：取前 3 行中第一行非全空且最像表头的行 ──
    header_idx = None
    tax_inclusive = None  # True=含税价, False=不含税价, None=无价格表头
    for i, row in enumerate(tbl[:4]):
        cells_text = [str(c or '').replace('\n', ' ').strip() for c in row]
        joined = ' '.join(cells_text)
        if '材料名称' not in joined and '序号' not in joined and not any(_is_city_name(c) for c in cells_text):
            continue
        # 判断是否是多城市表（必须有“型号规格/单位 + 不含税价/含税价”且宽列数较多）
        if '材料名称' in joined and ('型号规格' in joined or '单位' in joined):
            if '不含税价' in joined:
                tax_inclusive = False
                header_idx = i
                break
            if '含税价' in joined and '不含' not in joined:
                tax_inclusive = True
                header_idx = i
                break
        # 序号表（5-6 列）
        if '材料名称' in joined and ('规格型号' in joined or '型号规格' in joined) and '含税价' in joined:
            tax_inclusive = True
            header_idx = i
            break
        if '材料名称' in joined and ('规格型号' in joined or '型号规格' in joined) and '不含税价' in joined:
            tax_inclusive = False
            header_idx = i
            break

    if header_idx is not None:
        return _parse_table_with_header(tbl, header_idx, tax_inclusive)

    # ── 无表头：判断是 18 城市续表还是 单价续表 ──
    # 18 城市续表特征：前 3 行中某行 ≥ 3 个地市名
    for i, row in enumerate(tbl[:3]):
        cells_text = [str(c or '').replace('\n', ' ').strip() for c in row]
        city_count = sum(1 for c in cells_text if _is_city_name(c))
        if city_count >= 3:
            page_cities = [c for c in cells_text if _is_city_name(c)]
            data_start = i + 1
            cont_rows = []
            for row in tbl[data_start:]:
                cells = [str(c or '').replace('\n', ' ').strip() for c in row]
                if not cells or not cells[0]:
                    continue
                seq = cells[0]
                breed = spec = unit = ''
                prices = cells[1:]
                price_list = [_parse_price(p) for p in prices]
                cont_rows.append((seq, breed, spec, unit, price_list))
            return ('multi_city_cont', page_cities, cont_rows)

    # 单价续表特征：列数与上一“single_price”一致（4-5 列），第一行可能是分组合并的子项
    # 启发：列数 <= 6 且不存在地市名
    if tbl and len(tbl[0]) <= 6:
        first_row_text = ' '.join(str(c or '').strip() for c in tbl[0])
        if not any(_is_city_name(c) for c in tbl[0]) and not any(k in first_row_text for k in ['材料名称', '序号', '不含税价', '含税价']):
            cont_rows = []
            for row in tbl:
                cells = [str(c or '').replace('\n', ' ').strip() for c in row]
                if not cells:
                    continue
                if len(cells) == 4:
                    # 4 列单价：breed, spec, unit, price
                    breed, spec, unit, raw_price = cells
                    price = _parse_price(raw_price)
                    cont_rows.append((breed, spec, unit, price, breed))
                elif len(cells) == 5:
                    # 5 列：可能是 序号|breed|spec|unit|price，或 breed|sub|spec|unit|price
                    breed, c1, c2, unit, raw_price = cells
                    price = _parse_price(raw_price)
                    # 序号列：第一个 cell 是纯数字
                    if breed.isdigit() and breed not in ('',):
                        seq, real_breed, spec, unit, raw_price = cells
                        cont_rows.append((real_breed, spec, unit, price, real_breed))
                    else:
                        # 5 列有中间空列：可能 breed|sub|spec|unit|price。猜 spec = c1 + c2
                        spec_combined = c1 if c1 else ''
                        if c2 and c2 not in spec_combined:
                            spec_combined = (spec_combined + ' ' + c2).strip() if spec_combined else c2
                        cont_rows.append((breed, spec_combined, unit, price, breed))
                else:
                    continue
            if cont_rows:
                return ('single_price_cont', cont_rows)

    return None


def _parse_table_with_header(tbl, header_idx, tax_inclusive):
    """有表头的表：判断是多城市表还是单价表。"""
    header = [str(c or '').replace('\n', ' ').strip() for c in tbl[header_idx]]
    n_cols = len(header)

    # ── 多城市表：必须有“价格 + 地市列” 模式，列数 8+ ──
    if tax_inclusive is not None and n_cols >= 8:
        city_row_idx = header_idx + 1
        if city_row_idx >= len(tbl):
            return None
        city_cells = [str(c or '').replace('\n', ' ').strip() for c in tbl[city_row_idx]]
        page_cities = [c for c in city_cells if _is_city_name(c)]
        if not page_cities:
            return None
        data_start = header_idx + 2
        rows = []
        for row in tbl[data_start:]:
            cells = [str(c or '').replace('\n', ' ').strip() for c in row]
            if not cells or not cells[0]:
                continue
            seq = cells[0]
            if len(cells) >= 4:
                breed, spec, unit, *prices = cells[1:]
            else:
                breed = spec = unit = ''
                prices = cells[1:]
            price_list = [_parse_price(p) for p in prices]
            rows.append((seq, breed, spec, unit, price_list))
        return ('multi_city', page_cities, rows, tax_inclusive)

    # ── 4-6 列单价表 ──
    if tax_inclusive is not None and n_cols <= 6:
        data_start = header_idx + 1
        rows = []
        for row in tbl[data_start:]:
            cells = [str(c or '').replace('\n', ' ').strip() for c in row]
            if not cells:
                continue
            # 跳过仅作分隔的空行
            if not any(c for c in cells):
                continue
            # 识别 8 列并排双列表
            if n_cols == 8:
                half1 = cells[:4]
                half2 = cells[4:]
                rec1 = _parse_single_row(half1, has_seq=False)
                rec2 = _parse_single_row(half2, has_seq=False)
                if rec1: rows.append(rec1)
                if rec2: rows.append(rec2)
                continue
            rec = _parse_single_row(cells, has_seq=(n_cols >= 5 and header[0] == '序号'))
            if rec:
                rows.append(rec)
        return ('single_price', rows, tax_inclusive)

    return None


def _parse_single_row(cells, has_seq=False):
    """将一行 4-6 列的 unit row 转为 (breed, spec, unit, price, raw_breed)。"""
    if not cells:
        return None
    if has_seq and len(cells) >= 5:
        # 序号|材料名称|规格型号|单位|含税价
        seq, breed, spec, unit, raw_price = cells[:5]
        return (breed, spec, unit, _parse_price(raw_price), breed)
    if len(cells) == 4:
        # 材料名称|型号规格|单位|含税价
        breed, spec, unit, raw_price = cells
        return (breed, spec, unit, _parse_price(raw_price), breed)
    if len(cells) == 5:
        # 多出的中间列可能是：① 序号 ② 子名 ③ 单位隔列
        breed, c1, c2, unit, raw_price = cells
        # 推断：序号列是纯数字 → 跳过
        if breed.strip().isdigit():
            seq, real_breed, spec, unit, raw_price = cells
            return (real_breed, spec, unit, _parse_price(raw_price), real_breed)
        # 否则中间是“子名/分类”与“型号规格”
        sub = c1
        spec_combined = c2
        if sub:
            # 将子名拼接到 breed 后面作为分类 hint
            breed_full = f'{breed}（{sub}）' if breed else sub
        else:
            breed_full = breed
        return (breed_full, spec_combined, unit, _parse_price(raw_price), breed)
    if len(cells) == 6:
        # 序号|材料名称|规格型号|中间量|单位|含税价
        seq, breed, spec, mid_qty, unit, raw_price = cells
        if mid_qty and not mid_qty.isdigit():
            spec_combined = f'{spec}（{mid_qty}）' if spec else mid_qty
        else:
            spec_combined = spec
        return (breed, spec_combined, unit, _parse_price(raw_price), breed)
    return None


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
    parser.add_argument('--year', type=int, default=0, help='只入库指定年份的期（按 title 过滤，如 2026）')
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
        if args.year and f'{args.year}年' not in it['title']:
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

                minio_key = f'{cfg["minio"]["prefix"]}/{detail["pdf_name"]}' if detail['pdf_name'] else f'{cfg["minio"]["prefix"]}/{period}/source.pdf'
                if not args.dry_run:
                    upload_to_minio(s3, cfg['minio']['bucket'], minio_key, local_pdf)
                print(f'  minio: {minio_key}')

                pdf_rows = parse_pdf_tables(local_pdf, cities)
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
                        'city': r['city'],
                        'province': '河南',
                        'update_date': item['publish_date'],
                        'create_time': now,
                        'source_pdf': minio_key,
                        'source_url': detail['pdf_url'],
                    }
                    if 'tax_price' in r:
                        doc['tax_price'] = r['tax_price']
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

    print(f'\n[henan] 全部完成: total_written={total_written}')


if __name__ == '__main__':
    main()
