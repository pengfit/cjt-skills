"""菏泽工程造价信息 - 同步入口（v0.8 SyncRunner 抽象基类化, 2026-07-03）

v0.8 改造（道友要求）：
  - 默认走 HezeCollector（SyncRunner 化版本，commands/heze_collector.py）
  - --legacy 走原 v0.7 cmd_legacy_sync（逃生通道）
  - 内置工具函数（fetch_all_periods / fetch_detail_pdf / parse_pdf_tables / ...）保留，
    供 collector / preview 复用，不再被 main() 直接调用
  - v0.8 字段扩展：doc 和 progress 中新增 period_start / period_end / period_days

参考 chongqing v0.8 试点（chongqing_collector.py）+ henan v0.8 改造（henan_collector.py）。

流程（v0.7 主程序保留，作为 legacy / 工具函数源）：
1. POST /els-service/article/{page}/{size} 拉取列表 API，返回每期（xxid, subject, fwdate）
2. 访问详情页 HTML，提取 <a class="media" href="/upload-service/.../WY{fileid}.pdf">
3. 过滤：未入库 & 增量起点之后
4. 对每期：
   a. 下载 PDF → 本地临时文件
   b. 上传 MinIO
   c. pdfplumber 解析 → 长表（材料×规格×单位×价格），4 列单价表（全市统一价）
   d. bulk_index 到 ods_material_heze_price（幂等 _id）
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
import requests
from bs4 import BeautifulSoup

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

from utils import (
    load_config, get_es_client, get_s3_client,
    ensure_bucket, ensure_ods_index, ensure_progress_index,
    fetch_html, download_file, upload_to_minio,
)

PROGRESS_FILE = os.path.join(os.path.dirname(SCRIPT_DIR), '.heze_sync_progress.json')


# ─── 列表 API 抓取 ────────────────────────────────────────────────────────────
def fetch_list_page(cfg, page, size=15):
    """调用列表 API，返回 (items, totalPages)"""
    site = cfg['site']
    body = {
        'dw': [site['dwid']],
        'catas': [site['catas']],
        'fwzt': '3',
        'order': 'fwdate',
        'type': [1],
    }
    url = f"{site['api_url']}/{page}/{size}"
    resp = requests.post(url, json=body, timeout=site['timeout_sec'],
                         headers={'User-Agent': site['user_agent'],
                                  'Content-Type': 'application/json'})
    resp.raise_for_status()
    data = resp.json().get('data', {})
    contents = data.get('contents', [])
    items = []
    for c in contents:
        items.append({
            'title': c.get('subject', ''),
            'publish_date': c.get('fwdate', ''),
            'xxid': c.get('xxid', ''),
        })
    return items, data.get('totalPages', 1)


def fetch_all_periods(cfg):
    """抓取所有期（按 totalPages 自动翻页）"""
    items, total = fetch_list_page(cfg, 1)
    print(f'  [list] page 1: {len(items)} 期 (共 {total} 页)')
    for p in range(2, total + 1):
        more, _ = fetch_list_page(cfg, p)
        items.extend(more)
        print(f'  [list] page {p}: {len(more)} 期')
    # 去重（按 xxid）
    seen = set()
    uniq = []
    for it in items:
        if it['xxid'] in seen:
            continue
        seen.add(it['xxid'])
        uniq.append(it)
    return uniq


# 老期数详情页把 PDF 链接塞在 JS 字符串 memo 里，有几种格式：
#   1. /upload-service/0530/{dwid}/WY{fileid}.pdf                （较新的老期数）
#   2. /0530/222/{md5hash}.pdf                                   （更老的期数）
#   3. /jcms/.../downfile.jsp?classid=0&filename={hash}.pdf      （最老的期数，memo 拼接后才能用）
#      详情页 JS 会执行 split/join：memo.split('.../downfile.jsp?classid=0&filename=').join('/0530/222/')
# 新期数则在 <a class="media" href="…pdf"> 节点里。所有格式都需支持。
# 注意 JS 字符串里 / 被转义为 \/、双引号转义为 \"，需先标准化。
_PDF_HREF_RE_UPLOAD = re.compile(r'href="([^"]*?/upload-service/[^"]+?/WY\d+\.pdf)"')
_PDF_HREF_RE_0530 = re.compile(r'href="([^"]*?/0530/222/[^"]+?\.pdf)"')
# 最老的 downfile.jsp 格式：提取 filename 参数，拼接为 /0530/222/{filename}
_PDF_HREF_RE_DOWNFILE = re.compile(r'href="[^"]*?downfile\.jsp\?[^"]*?filename=([^"\s&]+\.pdf)"')
# 2018 年期 memo 用的是 UEditor 上传路径 /jcms/.../upload/file/{yyyymmdd}/{hash}.pdf
_PDF_HREF_RE_JCMS = re.compile(r'href="([^"]*?/jcms/[^"]+?/upload/file/\d+/\w+\.pdf)"')


def fetch_detail_pdf(cfg, xxid):
    """访问详情页 HTML，提取 PDF 链接 + 标题。

    解析顺序：
      1. <a class="media" href="…pdf"> 或 <div class="pdf-box"> 内的 PDF 链接
      2. 整页正则 fallback（应对老期数 JS 字符串 memo 形式）
    返回 (title, pdf_url, pdf_name, detail_url)。找不到 PDF 时 pdf_url 为空。
    """
    site = cfg['site']
    detail_url = f"{site['base_url']}/{site['dwid']}/{xxid}.html"
    html = fetch_html(detail_url, timeout=site['timeout_sec'])
    soup = BeautifulSoup(html, 'html.parser')
    title_el = soup.select_one('title')
    title = title_el.get_text(strip=True) if title_el else ''

    pdf_url = ''
    pdf_name = ''

    # 1. 新版结构：DOM 节点
    pdf_a = soup.select_one('a.media[href*=".pdf"]') or soup.select_one('div.pdf-box a[href*=".pdf"]')
    if pdf_a:
        href = pdf_a.get('href', '')
        # 排除 doc/docx/xls 等非 PDF（按扩展名严格过滤）
        if href.lower().endswith('.pdf'):
            pdf_url = urljoin(detail_url, href)
            pdf_name = pdf_a.get_text(strip=True) or ''

    # 2. fallback：整页正则（处理老期数 JS 字符串）
    if not pdf_url:
        # 先去掉 JS 字符串里的转义：\/ → / ，\" → "
        # 顺序很重要：必须先处理 \/ 再处理 \"
        html_norm = html.replace(r'\/', '/').replace(r'\"', '"')
        # 2a. /upload-service/.../WY{fileid}.pdf（新一些的老期数）
        m = _PDF_HREF_RE_UPLOAD.search(html_norm)
        if m:
            href = m.group(1)
            if href.lower().endswith('.pdf'):
                pdf_url = urljoin(detail_url, href)
        # 2b. /0530/222/{md5}.pdf（更老的期数，JSP 下载页直链）
        if not pdf_url:
            m = _PDF_HREF_RE_0530.search(html_norm)
            if m:
                href = m.group(1)
                if href.lower().endswith('.pdf'):
                    pdf_url = urljoin(detail_url, href)
        # 2c. downfile.jsp?filename={hash}.pdf（最老的期数，模拟 JS split/join）
        if not pdf_url:
            m = _PDF_HREF_RE_DOWNFILE.search(html_norm)
            if m:
                filename = m.group(1)
                if filename.lower().endswith('.pdf'):
                    pdf_url = urljoin(detail_url, f'/0530/222/{filename}')
        # 2d. /jcms/.../upload/file/{yyyymmdd}/{hash}.pdf（2018 年的期数）
        if not pdf_url:
            m = _PDF_HREF_RE_JCMS.search(html_norm)
            if m:
                href = m.group(1)
                if href.lower().endswith('.pdf'):
                    pdf_url = urljoin(detail_url, href)

    # 3. PDF 文件名从 PDF URL 里推断（如果还没拿到）
    if pdf_url and not pdf_name:
        # 文件名 = last path segment（不带 query）
        from urllib.parse import urlparse
        path = urlparse(pdf_url).path
        pdf_name = path.rsplit('/', 1)[-1] if path else ''

    return {
        'title': title,
        'pdf_url': pdf_url,
        'pdf_name': pdf_name,
        'detail_url': detail_url,
    }


def extract_period_from_title(title):
    """从标题提取周期 '《工程造价信息》2026年第1期' → '2026.1期'"""
    m = re.search(r'(\d{4})年(\d{1,2})月', title)
    if not m:
        m = re.search(r'(\d{4})\s*年第\s*(\d{1,2})\s*期', title)
    if not m:
        return ''
    return f'{m.group(1)}.{int(m.group(2))}期'


def period_to_display_name(period):
    """'2024.1期' → '《工程造价信息》2024年第1期'，用于 minio 文件名"""
    m = re.match(r'(\d{4})\.(\d{1,2})期', period or '')
    if not m:
        return period or 'source'
    return f'《工程造价信息》{m.group(1)}年第{int(m.group(2))}期'


# ─── PDF 解析（4 列单价表，全市统一价） ────────────────────────────────────
def _parse_price(s):
    """提取 float，失败返回 None。

    处理多价格并列的字符串（如 '15.11/18.28/18.86'）：取首个有效价格。
    """
    if s is None:
        return None
    s = str(s).strip()
    if not s:
        return None
    # 多价格取首个（取/分隔的第一段）
    if '/' in s:
        s = s.split('/')[0]
    s = s.replace('￥', '').replace('¥', '').replace(',', '').replace(' ', '')
    try:
        v = float(s)
        return v if v > 0 else None
    except ValueError:
        return None


def _split_breed_spec(name_spec):
    """拆分品种和规格。按优先级尝试以下启发式规则：

    1. 括号内 = 规格补充
       '钢丝网(综合)' → ('钢丝网', '综合')
       '礌石(10~30mm)' → ('礌石', '10~30mm')
    2. 第一个空格分割
       'HPB300 φ6' → ('HPB300', 'φ6')
    3. 末尾是区间型规格（数字～/~/—数字[+单位]）
       '礌石10～30mm' → ('礌石', '10～30mm')
       '成品检验口 600-800mm' → ('成品检验口', '600-800mm')
    4. 末尾是单数字 + 明确计量单位
       'T1000×500mm' → ('T1000', '×500mm') （不适用，跨后面规则）
       '12芯单模光缆' → 不动（中间不是计量单位结尾）
    5. 开头是 C/LC/HC + 数字（混凝土/管材等级）
       'C30商品混凝土' → ('商品混凝土', 'C30')
       'PE100' → 不动
    6. 末尾是 φ/DN + 数字
       '冷异型管φ200' → ('冷异型管', 'φ200')
    7. 都匹配不上，原样返回
       '黄砂过筛细砂' → ('黄砂过筛细砂', '')
    """
    if not name_spec:
        return ('', '')
    s = str(name_spec).strip()
    if not s:
        return ('', '')

    # 1. 括号内 = 规格补充
    m = re.match(r'^(.+?)\s*[（(](.+?)[)）]\s*$', s)
    if m:
        return (m.group(1).strip(), m.group(2).strip())

    # 2. 第一个空格分割（最高优先的清晰拆分）
    parts = s.split(None, 1)
    if len(parts) > 1:
        return (parts[0].strip(), parts[1].strip())

    # 以下是 无空格 场景

    # 3. 末尾是区间型规格：数字～/~/—-数字[+单位]
    m = re.search(
        r'^([^\d]*[\u4e00-\u9fa5a-zA-Z][^\d]*)(\d+(?:\.\d+)?\s*[～~—-]\s*\d+(?:\.\d+)?(?:\s*[a-zA-Z㎡%]+)?)\s*$',
        s
    )
    if m:
        return (m.group(1).strip().rstrip('，,、'), m.group(2).strip())

    # 4. 末尾是单数字 + 明确计量单位（要求 breed 部分含 1 个汉字或字母，避免 "12芯单模光缆" 被误拆）
    m = re.search(
        r'^([\u4e00-\u9fa5a-zA-Z]+[^\d]*?)(\d+(?:\.\d+)?\s*(?:mm|cm|m|kg|t|株|丛|个|根|套|块|片|只|盒|桶|袋|支|颗|米|升|公顷|亩|匹|L|MPa|kw|kW|V|kV|A|kA|W|kWh|㎡|m²|m³|号|%)[\w\/]*)\s*$',
        s
    )
    if m:
        return (m.group(1).strip(), m.group(2).strip())

    # 5. 开头是 C/LC/HC/QC + 数字（混凝土/管材等级）
    m = re.match(r'^(C\d+|LC\d+|HC\d+|QC\d+)(.+)$', s)
    if m:
        spec = m.group(1)
        breed = m.group(2).strip()
        if breed:
            return (breed, spec)

    # 6. 末尾是 φ/DN + 数字（钢筋/管材，要求 breed 部分含 1 个汉字或字母）
    m = re.search(r'^([\u4e00-\u9fa5a-zA-Z]+[^\d]*?)((?:φ|Φ|DN|d)\d+(?:\.\d+)?[a-zA-Z]*)\s*$', s)
    if m:
        return (m.group(1).strip().rstrip('，,、'), m.group(2).strip())

    # 7. 都匹配不上，原样返回（spec 为空，ETL 会以 breed 填充）
    return (s, '')


# ─── 表格 schema 推断 ─────────────────────────────────────────────────────────
# 价格列表头匹配：覆盖"价格/单价/除税价/不含税单价/含税单价/建议零售价/SN8价"
_PRICE_HEADER_RE = re.compile(r'(价|单价|price)', re.IGNORECASE)
# breed 列：含"名称/品名/类型/品种/品牌/材料名/玻璃型号/产品名称/品牌型号/产品型号/接口型式"
_BREED_HEADER_RE = re.compile(r'(名称|品名|类型|品种|品牌|材料名|材料名称|玻璃型号|产品名称|品牌型号|产品型号|型式)')
# 单独的"型号"列作为 fallback
_BARE_MODEL_HEADER_RE = re.compile(r'型号')
# spec 列：含"规格"（注意"规格型号"也命中）
_SPEC_HEADER_RE = re.compile(r'规格')
# unit 列：含"单位"
_UNIT_HEADER_RE = re.compile(r'单位')


def _infer_table_schema(header):
    """根据表头推断 schema，返回 [(col_idx, type)]。

    type: 'price' / 'breed' / 'spec' / 'unit' / 'seq' / 'note'

    优先级：price > unit > breed > spec > seq
    - 多 breed 列时只保留第一个为 breed，其余降级为 note（避免"产品名称/型号"
      两个 breed 列同时抽取造成错位）
    - 多 spec 列时全部保留（拼接为完整规格描述）
    """
    schema = []
    breed_seen = False
    for i, h in enumerate(header):
        h_norm = h.replace(' ', '').replace('\n', '')
        if _PRICE_HEADER_RE.search(h_norm):
            schema.append((i, 'price'))
        elif _UNIT_HEADER_RE.search(h_norm):
            schema.append((i, 'unit'))
        elif _SPEC_HEADER_RE.search(h_norm) and not _BREED_HEADER_RE.search(h_norm):
            schema.append((i, 'spec'))
        elif _BREED_HEADER_RE.search(h_norm):
            if not breed_seen:
                schema.append((i, 'breed'))
                breed_seen = True
            else:
                # 第二个及以后的 breed 列（如"型号"列）→ 降级为 spec
                schema.append((i, 'spec'))
        elif _BARE_MODEL_HEADER_RE.search(h_norm):
            if not breed_seen:
                schema.append((i, 'breed'))
                breed_seen = True
            else:
                # 多个型号列（罕见）→ 降级为 spec
                schema.append((i, 'spec'))
        else:
            schema.append((i, 'seq' if i == 0 else 'note'))
    return schema


def _row_cells(row, ncols_raw):
    """规范化一行数据：trim、合并空。"""
    cells = [str(c or '').replace('\n', ' ').strip() for c in row]
    while len(cells) < ncols_raw:
        cells.append('')
    return cells[:ncols_raw]


def _extract_row_data(cells, schema):
    """根据 schema 从一行抽取 (breed, spec, unit, price_str)。

    多 breed 列时只取 schema 中第一个 breed 列（避免"产品名称/型号"两个 breed 列错位）。
    多 spec 列时拼接（兼容"规格/型号"两列都是规格描述的情况）。
    """
    breed, spec, unit, price_str = '', '', '', ''
    breed_seen = False  # 是否已遇过第一个 breed 列
    spec_parts = []
    for idx, typ in schema:
        if typ == 'breed':
            if not breed_seen and cells[idx]:
                breed = cells[idx]
                breed_seen = True
        elif typ == 'spec':
            if cells[idx]:
                spec_parts.append(cells[idx])
        elif typ == 'unit':
            if not unit and cells[idx]:
                unit = cells[idx]
        elif typ == 'price':
            if not price_str and cells[idx]:
                price_str = cells[idx]
    spec = ' '.join(spec_parts) if spec_parts else ''
    return breed, spec, unit, price_str


def parse_pdf_tables(pdf_path, cities=None):
    """解析 PDF → 长表 [(breed, spec, unit, city, price, category?)]

    菏泽 PDF 表格多种 schema，本函数按表头自动识别：

      A. 单价表（4/6/7 列）：序号 | 名称规格 | 单位 | 价格（元）       ← 钢材/水泥/管材/电气等
         6/7 列扩展：产品名称 | 规格型号 | 接口型式 | 单位 | 单价（元）| 备注
                    产品名称 | 规格 | 型号 | 单位 | 单价 | 检测规范号
      B. 苗木表（5 列）：序号 | 品名 | 规格 | 单位 | 价格（元）        ← 仅当表头含"品名"才走苗木
         跨行合并：序号/品名为 None 时继承上一行。
      C. 跨页续表：表头行缺失（如 p54/p55 洁润/金潮牌续表），按上一张表的 schema 继承。

    全市统一价，city='菏泽'。
    """
    rows = []
    city = cities[0] if cities else '菏泽'
    last_schema = None  # 用于跨页续表继承

    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            tables = page.extract_tables() or []
            for tbl in tables:
                if not tbl or len(tbl) < 2:
                    continue
                ncols_raw = len(tbl[0])
                header = [str(c or '').replace('\n', '').strip() for c in tbl[0]]
                # 推断表头 schema：是否有价格列
                has_price = any(_PRICE_HEADER_RE.search(h.replace(' ', '')) for h in header)

                # ── 续表识别 ──
                # 条件：表头无价格列 & 行内容看起来像数据行（第一行 4 列长度匹配、是数字/中文）
                if not has_price and last_schema is not None and ncols_raw >= 4:
                    first_row = _row_cells(tbl[0], ncols_raw)
                    # 探测：第一行第二列是否像"数据"（含中文或数字+字母），且第一列像序号
                    looks_like_data = (
                        bool(re.match(r'^\d{1,4}$', first_row[0]))  # 首列是数字序号
                        and any(_PRICE_HEADER_RE.search(h.replace(' ', '')) for h in ['']) is False  # 头无价格
                        and bool(re.search(r'[\u4e00-\u9fa5A-Za-z0-9]', first_row[1] or first_row[2] or ''))
                    )
                    if looks_like_data:
                        # 续表：当数据行处理，继承 last_schema
                        schema = last_schema
                        data_rows = tbl  # 没有表头行
                        is_tree = False  # 续表不会是苗木
                        # 用 last_schema 处理所有行
                        for row in data_rows:
                            cells = _row_cells(row, ncols_raw)
                            breed, spec, unit, price_str = _extract_row_data(cells, schema)
                            if not breed or not unit:
                                continue
                            price = _parse_price(price_str)
                            if price is None:
                                continue
                            breed_clean, spec_clean = _split_breed_spec(breed + (' ' + spec if spec else ''))
                            rows.append({
                                'breed': breed_clean,
                                'spec': spec_clean,
                                'unit': unit,
                                'city': city,
                                'price': price,
                            })
                        continue  # 处理完，跳到下个表

                if not has_price:
                    continue

                schema = _infer_table_schema(header)
                last_schema = schema  # 缓存以备续表用
                is_tree = any(
                    typ == 'breed' and header[idx].replace(' ', '').replace('\n', '') in ('品名', '苗木', '树种', '绿化苗木')
                    for idx, typ in schema
                )

                if is_tree:
                    # B. 5 列苗木表：序号 | 品名 | 规格 | 单位 | 价格
                    cur_seq = ''
                    cur_breed = ''
                    for row in tbl[1:]:
                        cells = _row_cells(row, ncols_raw)
                        seq = cells[0] if len(cells) > 0 else ''
                        breed_cell = cells[1] if len(cells) > 1 else ''
                        spec = cells[2] if len(cells) > 2 else ''
                        unit = cells[3] if len(cells) > 3 else ''
                        price_str = cells[4] if len(cells) > 4 else ''
                        if seq:
                            cur_seq = seq
                        if breed_cell:
                            cur_breed = breed_cell
                        if not cur_breed or not spec:
                            continue
                        if not unit:
                            continue
                        price = _parse_price(price_str)
                        if price is None:
                            continue
                        rows.append({
                            'breed': cur_breed,
                            'spec': spec,
                            'unit': unit,
                            'city': city,
                            'price': price,
                            'category': '绿化苗木',
                        })
                else:
                    # A. 单价表（任意列数 4/6/7/8）：按 schema 抽取
                    # 跨行合并：name列为 None 时继承上一行（适用于同品种多规格，如
                    #   球墨铸铁聚乙烯复合管 1.6MPa DN700/DN800/DN900/...）
                    cur_breed = ''
                    for row in tbl[1:]:
                        cells = _row_cells(row, ncols_raw)
                        breed, spec, unit, price_str = _extract_row_data(cells, schema)
                        if breed:
                            cur_breed = breed
                        elif cur_breed and (spec or unit or price_str):
                            # 同一品种的延续行：继承 breed
                            breed = cur_breed
                        if not breed or not unit:
                            continue
                        price = _parse_price(price_str)
                        if price is None:
                            continue
                        breed_clean, spec_clean = _split_breed_spec(breed + (' ' + spec if spec else ''))
                        rows.append({
                            'breed': breed_clean,
                            'spec': spec_clean,
                            'unit': unit,
                            'city': city,
                            'price': price,
                        })
    return rows


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
def _doc_id(period, breed, spec, city):
    raw = f'{period}|{breed}|{spec}|{city}'
    return hashlib.md5(raw.encode('utf-8')).hexdigest()


def bulk_index(es, index, docs):
    """幂等写入（按 _id upsert）"""
    if not docs:
        return 0, 0
    body = ''
    for d in docs:
        _id = _doc_id(d['period'], d['breed'], d['spec'], d['city'])
        body += json.dumps({'index': {'_index': index, '_id': _id}}, ensure_ascii=False) + '\n'
        body += json.dumps(d, ensure_ascii=False) + '\n'
    resp = es.bulk(body=body, refresh=False)
    if resp.get('errors'):
        errors = sum(1 for it in resp['items'] if 'error' in it.get('index', {}))
        return len(docs) - errors, errors
    return len(docs), 0


# ─── 主流程 ────────────────────────────────────────────────────────────────
def cmd_legacy_sync(args):
    """v0.7 原 main 流程（逃生通道，仅在 --legacy 时调用）。

    与原 v0.7 行为等价：
      - 抓列表 → 过滤 → 下载 PDF → MinIO → 解析 → bulk_index → 进度
      - 不含 period_start / period_end / period_days 字段
    """
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

    print(f'[heze v0.7 legacy] ES: {es_host}')
    print(f'[heze v0.7 legacy] MinIO: {cfg["minio"]["endpoint"]} / {cfg["minio"]["bucket"]}')

    # 1. 抓所有期
    print('[heze v0.7 legacy] 抓取列表...')
    items = fetch_all_periods(cfg)
    print(f'[heze v0.7 legacy] 共 {len(items)} 期')

    # 2. 过滤
    todo = []
    for it in items:
        # 1) 用户指定的 period 关键字过滤
        if args.period and args.period not in it['title']:
            continue
        # 2) 年份过滤（仅当 args.year != 0）
        if args.year and f'{args.year}年' not in it['title']:
            continue
        # 3) 列表 API catas 过滤不严格，混入"竣工验收备案表"等无关文档，按标题关键字排除
        if '工程造价信息' not in it['title']:
            continue
        # 4) 跳过已成功入库的
        if it['xxid'] in progress['done'] and progress['done'][it['xxid']].get('status') == 'ok':
            continue
        todo.append(it)

    if args.latest:
        todo = todo[:1]

    print(f'[heze v0.7 legacy] 待处理 {len(todo)} 期')
    if not todo:
        print('[heze v0.7 legacy] 无新数据')
        return

    cities = cfg['cities']
    total_written = 0
    for idx, item in enumerate(todo, 1):
        print(f'\n[heze v0.7 legacy] [{idx}/{len(todo)}] {item["title"]}  ({item["publish_date"]})')
        start = time.time()
        try:
            detail = fetch_detail_pdf(cfg, item['xxid'])
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

                # minio_key: 优先用详情页中的可读文件名，老期数没可读名则统一为《工程造价信息》{period}.pdf
                if detail['pdf_name'] and not detail['pdf_name'].startswith('WY'):
                    minio_key = f'{cfg["minio"]["prefix"]}/{detail["pdf_name"]}'
                else:
                    minio_key = f'{cfg["minio"]["prefix"]}/{period_to_display_name(period)}.pdf'
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
                        'province': '山东',
                        'update_date': item['publish_date'],
                        'create_time': now,
                        'source_pdf': minio_key,
                        'source_url': detail['pdf_url'],
                    }
                    if r.get('category'):
                        doc['category'] = r['category']
                    docs.append(doc)

                if args.dry_run:
                    print(f'  [dry-run] 将写 {len(docs)} 条到 {cfg["es"]["ods_index"]}')
                    ok, err = len(docs), 0
                else:
                    ok, err = bulk_index(es, cfg['es']['ods_index'], docs)
                    print(f'  bulk: ok={ok}, err={err}')

                elapsed = time.time() - start
                progress['done'][item['xxid']] = {
                    'period': period,
                    'publish_date': item['publish_date'],
                    'xxid': item['xxid'],
                    'detail_url': detail['detail_url'],
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
                        'xxid': item['xxid'],
                        'detail_url': detail['detail_url'],
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
            progress['done'][item['xxid']] = {
                'publish_date': item['publish_date'],
                'xxid': item['xxid'],
                'status': 'failed',
                'error': str(e),
                'duration_sec': round(elapsed, 1),
            }
            save_progress(progress)

    print(f'\n[heze v0.7 legacy] 全部完成: total_written={total_written}')


def main():
    """v0.8 CLI 入口：默认走 HezeCollector（SyncRunner 化），--legacy 走 v0.7。

    字段扩展（v0.8）：doc 和 progress 中新增 period_start / period_end / period_days。
    """
    parser = argparse.ArgumentParser(
        description='菏泽工程造价材料信息同步（v0.8 SyncRunner 化）',
    )
    parser.add_argument('--period', default='', help='指定周期（如 2026.1期）')
    parser.add_argument('--year', type=int, default=datetime.now().year,
                        help='只入库指定年份的期（默认本年，0=不限制）')
    parser.add_argument('--all', action='store_true', help='同步所有未入仓的期')
    parser.add_argument('--reset', action='store_true', help='重置进度')
    parser.add_argument('--dry-run', action='store_true', help='预览，不写入（仅 legacy 支持）')
    parser.add_argument('--latest', action='store_true', help='只同步最新一期')
    parser.add_argument('--run-id', default='', help='指定 run_id（默认自动生成）')
    parser.add_argument('--legacy', action='store_true',
                        help='v0.7 兼容：走原 main 流程。默认走 Collector（推荐）。')
    parser.add_argument('--max-units', type=int, default=None,
                        help='Collector 路径：只跑前 N 个工作单元（验证用）')
    args = parser.parse_args()

    cfg_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        'config.yml',
    )

    if args.legacy:
        # v0.7 兼容路径
        print('[v0.7 兼容路径] cmd_legacy_sync 启动')
        print(f'  period={args.period}, year={args.year}, latest={args.latest}')
        cmd_legacy_sync(args)
        return

    # 默认路径：HezeCollector（v0.8 SyncRunner 抽象基类）
    from heze_collector import make_collector
    run_id = args.run_id or f"hz_run_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    print('[Collector 路径 v0.8] HezeCollector 启动')
    print(f'  year={args.year}, period={args.period}, latest={args.latest}, run_id={run_id}')

    collector = make_collector(
        cfg_path=cfg_path,
        run_id=run_id,
        year=args.year,
        period=args.period,
        latest=args.latest,
    )
    result = collector.run(reset=args.reset, max_units=args.max_units)
    print(f'\n[Collector 路径 v0.8] 完成: {result}')


if __name__ == '__main__':
    main()
