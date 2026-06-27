"""宁夏工程造价信息 - 同步主程序

流程：
1. 抓取列表 index.html / index_2.html / ...（共 6 页），提取每期（标题含 PDF 链接）
2. 过滤：
   - 标题必须包含 `journal_keyword`（"《宁夏工程造价》"）
   - 跳过 progress['done'] 已 ok 的期
3. 对每期：
   a. 下载 PDF → 本地临时文件
   b. 上传 MinIO
   c. pdfplumber 解析 → 长表
      - 跳过"政策文件/改革探索"等非数据章节
      - 价格资讯章节里的"材料价格表"：
        * 横向"地区×材料"结构 → 长表展开（每市/县一行）
      - 价格资讯章节里的"定额项目价格表"（8-11 节）：
        * 横向"项目×市/县"结构 → 长表展开
   d. bulk_index 到 ods_material_ningxia_price（幂等 _id）
   e. 写进度（本地 JSON + ES progress 索引）

PDF 结构（154 页）：
- 政策文件 / 改革探索 / 行业动态（p11-50）：文章，跳过
- 价格资讯（p51-）：主体数据
  - 8/9/10/11 节：定额项目价格（项目编号 × 项目名 × 单位 × 银川市价）
  - 材料价格信息：5 地市分别一段（银川市 / 石嘴山市 / 吴忠市 / 固原市 / 中卫市）
    每段内表结构：序号 / 材料名称 / 规格型号 / 单位 / [市辖区/县价格列]
  - 三、绿色认证预拌混凝土价格：横向表（地区 × 强度等级 × 价格）
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

PROGRESS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '.ningxia_sync_progress.json')

VAT_RATE = 0.13   # 建设工程材料增值税率


# ─── 列表页解析 ──────────────────────────────────────────────────────────────
def parse_list_page(html, base_url):
    """从列表页提取每期（a.ellipsis.fl 是文章链接，time.fr 是日期）"""
    soup = BeautifulSoup(html, 'html.parser')
    items = []
    for a in soup.select('a.ellipsis.fl[href*=".html"]'):
        href = a.get('href', '')
        title = a.get('title', '') or a.get_text(strip=True)
        li = a.find_parent('li')
        time_el = li.select_one('time.fr') if li else None
        publish_date = time_el.get_text(strip=True) if time_el else ''
        items.append({
            'title': title.strip(),
            'publish_date': publish_date,
            'detail_url': urljoin(base_url + '/ztzl/gczj/zjtt/', href),
        })
    return items


def fetch_all_periods(cfg):
    """抓取所有期（首页 + 分页）"""
    site = cfg['site']
    base = site['base_url']
    headers = {'User-Agent': site['user_agent']}
    all_items = []
    for page in range(1, site['list_pages'] + 1):
        if page == 1:
            url = base + site['list_path']
        else:
            url = base + site['list_page_pattern'].format(n=page)
        try:
            html = fetch_html(url, headers=headers, timeout=site['timeout_sec'])
        except Exception as e:
            print(f'  [list] page {page}: 失败 {e}')
            break
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


def fetch_detail_pdf(cfg, detail_url):
    """访问详情页，提取 PDF 链接 + 标题

    PDF 链接可能在：
    - <a href="…pdf">（部分详情页）
    - JS 字符串 var params="…pdf";（宁夏详情页的主要格式）
    """
    html = fetch_html(detail_url, timeout=cfg['site']['timeout_sec'])
    soup = BeautifulSoup(html, 'html.parser')
    title_el = soup.select_one('title')
    title = title_el.get_text(strip=True) if title_el else ''

    # 1. 优先从 a 标签找
    pdf_a = soup.select_one('a[href$=".pdf"]')
    if pdf_a:
        pdf_href = pdf_a.get('href', '')
        pdf_url = urljoin(detail_url, pdf_href)
        return title, pdf_url, pdf_a.get_text(strip=True) or ''

    # 2. 从 JS 字符串提取（宁夏详情页 var params="…pdf";）
    # 可能是 PDF 或 OFD，但 OFD 这里都转 PDF
    m = re.search(r'var\s+params\s*=\s*["\']([^"\']+\.pdf)["\']', html)
    if m:
        pdf_url = urljoin(detail_url, m.group(1))
        return title, pdf_url, ''

    return title, None, None


def pdf_basename(pdf_url: str) -> str:
    """从 PDF URL 提取 basename（含 .pdf）"""
    from urllib.parse import urlparse
    return os.path.basename(urlparse(pdf_url).path) or 'source.pdf'


# ─── PDF 解析 ────────────────────────────────────────────────────────────────
def _parse_price(s):
    if s is None:
        return None
    s = str(s).strip()
    # 清理噪声字符（中文括号、空格、人民币符号、↑↓↑↓ 趋势箭头、换行符等）
    for ch in ['\n', '\r', '\t', ' ', ',', '￥', '¥', '↑', '↓']:
        s = s.replace(ch, '')
    if not s or s in ('—', '-', '——', '/'):
        return None
    try:
        v = float(s)
        return v if v > 0 else None
    except ValueError:
        return None


def _is_data_row(row, n_cols):
    """判断一行是否是有效数据行（首列是数字序号）"""
    if not row or len(row) < n_cols:
        return False
    seq = str(row[0] or '').strip()
    if not seq or not seq.isdigit():
        return False
    return True


# 价格资讯章节标识
PRICE_SECTION_TITLE = '价格资讯'

# 章节编号识别（定额表只在 8-11 节：8.抹灰工程 / 9.木作 / 10.油漆 / 11.金属制品）
QUOTA_SECTION_RE = re.compile(r'^(8|9|10|11)\.\s*(.+)')


def _detect_section(text: str, default: str = '') -> str:
    """从页眉文本识别章节"""
    if not text:
        return default
    if PRICE_SECTION_TITLE in text:
        return '价格资讯'
    return default


def _detect_subsection(text: str) -> str:
    """识别定额章节（8.抹灰工程 / 9.木作 / 10.油漆 / 11.金属制品）"""
    if not text:
        return ''
    for line in text.split('\n')[:10]:
        m = QUOTA_SECTION_RE.match(line.strip())
        if m:
            return f'{m.group(1)}.{m.group(2)}'
    return ''


# 城市/县名识别（表格列头）
COMMON_COUNTIES = [
    '兴庆区', '金凤区', '西夏区', '永宁县', '贺兰县', '灵武市',
    '大武口区', '惠农区', '平罗县',
    '利通区', '红寺堡区', '盐池县', '同心县', '青铜峡市',
    '原州区', '西吉县', '隆德县', '泾源县', '彭阳县',
    '沙坡头区', '中宁县', '海原县',
    # 城市全名
    '银川市', '石嘴山市', '吴忠市', '固原市', '中卫市',
]


def _detect_table_kind(tbl, header_idx, current_subsection):
    """识别表格类型"""
    if not tbl or header_idx is None or header_idx >= len(tbl):
        return None, None, None
    header_row = tbl[header_idx]
    cells_text = ' '.join(str(c or '') for c in header_row)
    n_cols = len(header_row)

    # 按 header_row 实际列顺序找出市/县列（保留表格中出现的先后顺序）
    counties_in_header = []
    for cell in header_row:
        c = str(cell or '').strip()
        # cell 里可能含换行符，匹配所有可能的县/市名
        for county in COMMON_COUNTIES:
            if county in c and county not in counties_in_header:
                counties_in_header.append(county)

    # 检查是否含定额项目编号（5位数字如 08001 09001）
    has_quota_code = bool(re.search(r'\b\d{5}\b', cells_text))

    # 检查星等级表头
    has_star = '一星级' in cells_text and '二星级' in cells_text and '三星级' in cells_text

    # 检查横排强度等级（C15 C20 ... C60）
    has_strength_grade = bool(re.search(r'C\d{2}', cells_text))

    if counties_in_header:
        # 材料价格表：序号 / 材料名称 / 规格型号 / 单位 / [各县价格]
        if n_cols >= 5:
            return 'material', counties_in_header, []
        return None, None, None
    elif has_quota_code and current_subsection:
        # 定额项目价格表：项目编号 / 项目名 / 单位 / 各市价
        quota_codes = re.findall(r'\b\d{5}\b', cells_text)
        if quota_codes and n_cols >= 4:
            return 'quota', ['银川市'], quota_codes
    elif has_star:
        # 绿色建材多星等级表：序号 / 材料 / 规格 / 单位 / 一星级 / 二星级 / 三星级 / 备注
        return 'material', ['一星级', '二星级', '三星级'], []
    elif has_strength_grade:
        # 横排混凝土表：序号 / 强度等级 / C15-C60（区域×强度）→ 特殊表，不解析
        # （预留：未来可开发横排解析）
        return None, None, None
    elif n_cols == 5:
        # 5 列单价格表：序号 / 材料 / 规格 / 单位 / 综合价格
        return 'material', ['综合价格'], []
    elif n_cols == 6 and '综合价格' in cells_text:
        # 6 列单价格+备注：序号 / 材料 / 规格 / 单位 / 综合价格 / 备注
        return 'material', ['综合价格'], []
    return None, None, None


def parse_pdf(pdf_path):
    """解析 PDF → 长表 [{...}]"""
    out = []
    current_section = ''
    current_subsection = ''
    current_city_group = ''  # 当前章节的地市分组（一、银川市 / 二、石嘴山市 / ...）
    current_category = ''  # 当前大类（一、主体及围护结构类 / 二、装饰装修类 / ...）

    # 价格资讯章节内的"地区分组"识别
    CITY_GROUP_RE = re.compile(r'^[一二三四五六七八九十]+、(.+)')
    # 大类识别（不限于地市）
    # 例：一、主体及围护结构类 / 二、装饰装修类 / 三、安装类 / 四、市政类
    CATEGORY_RE = re.compile(r'^[一二三四五六七八九十]+、(.+?类)$')
    # 跨页大类：全章节标题（全区建筑工程主要材料价格 / 装配式及绿色建材价格信息 等）
    CHAPTER_TITLES = {
        '全区建筑工程主要材料价格': '全区建筑工程主要材料价格',
        '装配式及绿色建材价格信息': '装配式及绿色建材',
        '市政工程主要材料价格': '市政工程材料',
        '绿色建材价格': '绿色建材',
        '人工价格信息': '人工价格',
        '材料价格信息': '材料价格',
    }

    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            try:
                text = page.extract_text() or ''
            except Exception as e:
                # 个别页（如封面、复杂图像页）pdfplumber 可能报错，跳过
                continue
            if not text:
                continue

            section = _detect_section(text)
            new_section = False
            if section:
                if section != current_section:
                    new_section = True
                current_section = section
                # 进入价格资讯章节时重置 subsection（current_city_group 不重置，避免续表丢失上下文）
                if section == PRICE_SECTION_TITLE and new_section:
                    current_subsection = ''
                    current_category = ''
            # 仅在价格资讯章节解析
            if current_section != PRICE_SECTION_TITLE:
                continue

            # 识别定额小节（8/9/10/11 节）
            subsection = _detect_subsection(text)
            if subsection:
                current_subsection = subsection

            # 识别跨页章节标题（全区建筑工程主要材料价格 / 装配式及绿色建材等）
            for line in text.split('\n')[:15]:
                stripped = line.strip()
                for keyword, region_value in CHAPTER_TITLES.items():
                    if keyword in stripped and len(stripped) < 30:
                        current_city_group = region_value
                        current_category = ''
                        break
                if current_city_group in CHAPTER_TITLES.values():
                    break

            # 识别地市分组（一、银川市 / 二、石嘴山市）
            for line in text.split('\n')[:15]:
                m = CITY_GROUP_RE.match(line.strip())
                if m:
                    grp = m.group(1).strip()
                    # 跳过纯大类（“装饰装修类”含“类”）
                    if grp.endswith('类'):
                        continue
                    # 跳过 PDF 目录索引（后续含 ……）
                    if '…' in grp:
                        continue
                    current_city_group = grp
                    break

            # 识别大类（一、主体及围护结构类 / 二、装饰装修类 / 三、安装类 / 四、市政类）
            for line in text.split('\n')[:15]:
                m = CATEGORY_RE.match(line.strip())
                if m:
                    current_category = m.group(1).strip()
                    break

            tables = page.extract_tables() or []
            for tbl in tables:
                if not tbl or len(tbl) < 2:
                    continue
                # 找表头行（包含"序号"或"项目"）
                header_idx = None
                for i, row in enumerate(tbl[:6]):
                    if row:
                        cells = ' '.join(str(c or '') for c in row)
                        if '序号' in cells or '材料名称' in cells:
                            header_idx = i
                            break
                        # 定额表表头含 5 位项目编号
                        if re.search(r'\b\d{5}\b', cells) and ('项目' in cells or '名称' in cells):
                            header_idx = i
                            break
                if header_idx is None:
                    continue

                kind, cities, quota_codes = _detect_table_kind(tbl, header_idx, current_subsection)
                if kind is None:
                    continue

                # 确定 section 名称
                section_name = current_city_group or current_subsection or '材料价格'

                if kind == 'material':
                    # 材料价格表：长表展开
                    _parse_material_table(tbl, header_idx, cities, section_name, current_category, out)
                elif kind == 'quota':
                    # 定额项目价格表
                    _parse_quota_table(tbl, header_idx, cities, current_subsection, out)

    return out


def _parse_material_table(tbl, header_idx, cities, section_name, category_name, out):
    """材料价格表 → 长表展开（每个城市一行）"""
    # 列位置：0=序号 1=材料名称 2=规格型号 3=单位 4+=城市价
    # 但有时表格只 5 列（1 个城市），需要动态确定起始列
    if header_idx + 1 >= len(tbl):
        return
    data_rows = tbl[header_idx + 1:]
    for row in data_rows:
        if not row or len(row) < 5:
            continue
        if all(c is None or str(c).strip() == '' for c in row):
            continue
        seq = str(row[0] or '').strip()
        if not seq.isdigit():
            continue
        breed = str(row[1] or '').strip()
        spec = str(row[2] or '').strip()
        unit = str(row[3] or '').strip()
        # 取备注列（最后一列，如果存在）
        remark = ''
        if len(row) > 5:
            remark = str(row[-1] or '').strip()

        # 城市价列：从第 5 列开始
        for ci, city in enumerate(cities):
            col_idx = 4 + ci
            if col_idx >= len(row):
                break
            raw = row[col_idx]
            price = _parse_price(raw)
            if price is None:
                continue
            out.append({
                'no': seq,
                'breed': breed,
                'spec': spec,
                'unit': unit,
                'price': price,
                'tax_price': round(price * (1 + VAT_RATE), 2),
                'remark': remark,
                'section': section_name,
                'category': category_name or '主要材料',
                'region': section_name,
                'city': city,
                'breed_table_kind': 'material',
            })


def _parse_quota_table(tbl, header_idx, cities, subsection, out):
    """定额项目价格表 → 长表展开（每项目×每城市）"""
    if header_idx + 1 >= len(tbl):
        return
    data_rows = tbl[header_idx + 1:]
    for row in data_rows:
        if not row or len(row) < 4:
            continue
        if all(c is None or str(c).strip() == '' for c in row):
            continue
        # 定额表：第一列项目编号 / 第二列项目名 / 第三列单位 / 第四列后是价格
        # 但有时项目编号在第 1 列（数字 5 位）
        first_col = str(row[0] or '').strip()
        if first_col.isdigit() and len(first_col) == 5:
            code = first_col
            name = str(row[1] or '').strip()
            unit = str(row[2] or '').strip() if len(row) > 2 else ''
            price_start = 3
        else:
            # 可能是"续表"无编号
            continue
        for ci, city in enumerate(cities):
            col_idx = price_start + ci
            if col_idx >= len(row):
                break
            price = _parse_price(row[col_idx])
            if price is None:
                continue
            out.append({
                'no': code,
                'breed': name,
                'spec': '',
                'unit': unit,
                'price': price,
                'tax_price': round(price * (1 + VAT_RATE), 2),
                'remark': '',
                'section': subsection or '定额项目',
                'category': '定额项目',
                'region': '',
                'city': city,
                'breed_table_kind': 'quota',
            })


# ─── 进度管理 ────────────────────────────────────────────────────────────────
def load_progress():
    if not os.path.exists(PROGRESS_FILE):
        return {'done': {}}
    with open(PROGRESS_FILE) as f:
        return json.load(f)


def save_progress(prog):
    with open(PROGRESS_FILE, 'w') as f:
        json.dump(prog, f, ensure_ascii=False, indent=2)


# ─── 入库 ────────────────────────────────────────────────────────────────────
def _doc_id(period, section, no, breed, spec, city):
    raw = f'{period}|{section}|{no}|{breed}|{spec}|{city}'
    return hashlib.md5(raw.encode('utf-8')).hexdigest()


def bulk_index(es, index, docs):
    """幂等写入（按 _id upsert）"""
    if not docs:
        return 0, 0
    body = ''
    for d in docs:
        _id = _doc_id(d['period'], d['section'], d['no'], d['breed'], d['spec'], d['city'])
        body += json.dumps({'index': {'_index': index, '_id': _id}}, ensure_ascii=False) + '\n'
        body += json.dumps(d, ensure_ascii=False) + '\n'
    resp = es.bulk(body=body, refresh=False)
    if resp.get('errors'):
        errors = sum(1 for it in resp['items'] if 'error' in it.get('index', {}))
        return len(docs) - errors, errors
    return len(docs), 0


# ─── 主流程 ──────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description='宁夏工程造价同步')
    parser.add_argument('--period', default='', help='指定周期')
    parser.add_argument('--year', type=int, default=0, help='只入库指定年份')
    parser.add_argument('--exclude-period', default='', help='排除指定周期')
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

    print(f'[ningxia] ES: {es_host}')
    print(f'[ningxia] MinIO: {cfg["minio"]["endpoint"]} / {cfg["minio"]["bucket"]}')
    print(f'[ningxia] journal_keyword: {cfg.get("journal_keyword", "")}')

    print('[ningxia] 抓取列表...')
    items = fetch_all_periods(cfg)
    print(f'[ningxia] 共 {len(items)} 期')

    journal_kw = cfg.get('journal_keyword', '')
    todo = []
    for it in items:
        if journal_kw and journal_kw not in it['title']:
            continue
        if args.period and args.period not in it['title']:
            continue
        if args.exclude_period and args.exclude_period in it['title']:
            continue
        if args.year and f'{args.year}年' not in it['title']:
            continue
        if it['detail_url'] in progress['done'] and progress['done'][it['detail_url']].get('status') == 'ok':
            continue
        todo.append(it)

    if args.latest:
        todo = todo[:1]

    print(f'[ningxia] 待处理 {len(todo)} 期')
    if not todo:
        print('[ningxia] 无新数据')
        return

    total_written = 0
    for idx, item in enumerate(todo, 1):
        print(f'\n[ningxia] [{idx}/{len(todo)}] {item["title"]}  ({item["publish_date"]})')
        start = time.time()
        try:
            # 抓详情页拿 PDF URL
            title, pdf_url, pdf_name = fetch_detail_pdf(cfg, item['detail_url'])
            if not pdf_url:
                print(f'  ✗ 详情页无 PDF 链接')
                progress['done'][item['detail_url']] = {
                    'status': 'failed',
                    'error': 'no pdf link in detail page',
                }
                save_progress(progress)
                continue
            print(f'  PDF: {pdf_url}')

            # period 从 title 提取（如 "2026年第2期"）
            m = re.search(r'(\d{4})年第(\d+)期', title or item['title'])
            if m:
                period = f'{m.group(1)}.第{m.group(2)}期'
            else:
                period = item['title'][:30]
            basename = pdf_basename(pdf_url)
            minio_key = f'{cfg["minio"]["prefix"]}/{period}/{basename}'
            print(f'  period: {period}')

            with tempfile.TemporaryDirectory() as tmpdir:
                local_pdf = os.path.join(tmpdir, 'source.pdf')
                download_file(pdf_url, local_pdf, timeout=600)

                if not args.dry_run:
                    upload_to_minio(s3, cfg['minio']['bucket'], minio_key, local_pdf)
                print(f'  minio: {minio_key}')

                rows = parse_pdf(local_pdf)
                print(f'  parsed: {len(rows)} 行')

                now = datetime.now().isoformat(timespec='seconds')
                docs = []
                for r in rows:
                    docs.append({
                        'no': r['no'],
                        'breed': r['breed'],
                        'spec': r['spec'],
                        'unit': r['unit'],
                        'price': r['price'],
                        'tax_price': r['tax_price'],
                        'remark': r.get('remark', ''),
                        'section': r['section'],
                        'category': r['category'],
                        'region': r.get('region', ''),
                        'city': r.get('city', ''),
                        'period': period,
                        'province': '宁夏',
                        'update_date': item['publish_date'],
                        'create_time': now,
                        'source_pdf': minio_key,
                        'source_url': pdf_url,
                    })

                if args.dry_run:
                    print(f'  [dry-run] 将写 {len(docs)} 条到 {cfg["es"]["ods_index"]}')
                    from collections import Counter
                    sec_counter = Counter(d['section'] for d in docs)
                    cat_counter = Counter(d['category'] for d in docs)
                    city_counter = Counter(d['city'] for d in docs)
                    print(f'  by category: {dict(cat_counter)}')
                    print(f'  by section: {dict(sec_counter)}')
                    print(f'  by city: {dict(city_counter)}')
                    print('  sample (前 3):')
                    for d in docs[:3]:
                        print(f"    {d['no']:5s} | {d['city']:8s} | {d['section'][:18]:18s} | "
                              f"{d['breed'][:25]:25s} | {d['spec'][:30]:30s} | "
                              f"{d['unit']:6s} = {d['price']}  (含税 {d['tax_price']})")
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
                    'pdf_url': pdf_url,
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
                        'pdf_url': pdf_url,
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

    print(f'\n[ningxia] 全部完成: total_written={total_written}')


if __name__ == '__main__':
    main()