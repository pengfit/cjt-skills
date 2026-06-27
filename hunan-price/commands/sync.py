"""湖南建设工程材料价格行情 - 同步主程序

流程：
1. 抓取列表 14 页（HTML 嵌入 <a> 链接），提取每期 title / 详情 URL
2. 过滤：标题含"湖南省建设工程材料价格行情资讯"或"钢筋、水泥、砂石、混凝土材料价格行情表"
   + year 2026
3. 对每期：
   a. 访问详情页，从 <img ... pdf.gif><a href="...files/xxx.pdf"> 提取 PDF 链接
   b. 修正 PDF URL：详情页 HTML 中是相对路径，基础 URL = 详情页 URL 所在目录
      实际 URL 模式：/zjt/hnweb/xzzx/zlxx/{YYYYMM}/{id}/files/{hash}.pdf
      （详情页 URL 是 tYYYYMMDD_{id}.html，相对路径去掉 t 前缀）
   c. 下载 PDF → 本地临时文件
   d. 上传 MinIO
   e. pdfplumber 解析 → 长表
      - 单页"半月表"：14 市州 × 6 种材料价格（每种 1 价格 + 1 涨跌幅）= 84 条
      - 15 页"行情资讯"：
        * p1 表：13 市州 × 2 月 + 邵阳 7 个半月期间 × ~100 材料 = 大量
        * p2 表：涨跌幅度表（同上结构）
        * p3-5 表：全省综合价表（2019 / 2025 / 2026 三个时点）
        * p6-8 表：全省综合价指数表（定基 / 环比 / 同比）
   f. bulk_index 到 ods_material_hunan_price（幂等 _id）
   g. 写进度（本地 JSON + ES progress 索引）

PDF 结构：
- 半月表"钢筋、水泥、砂石、混凝土材料价格行情表"（1 页 PDF）：
  - 编制说明（顶部）：价格来源 / 价格组成（不含增值税）/ 适用时间 / 涨跌幅算法
  - 表格 15 列：序号 / 市州 / 6 种材料 × (价格 + 涨跌幅) / 备注
  - 14 行数据（14 市州）

- 月刊"湖南省建设工程材料价格行情资讯"（15 页 PDF）：
  - p1：各市州建设工程主要材料价格表
  - p2：各市州建设工程主要材料价格涨跌幅度表
  - p3-5：全省综合价表（含 2019/2025/2026 三个时点对比）
  - p6-8：全省综合价指数表
  - p9-14：价格走势图（图表，无法解析）
  - p15：行情报告（文本综述）
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

PROGRESS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '.hunan_sync_progress.json')

# 14 个市州（按 PDF 表头列顺序）
HUNAN_CITIES_13 = [
    '长沙市', '株洲市', '湘潭市', '岳阳市', '永州市',
    '益阳市', '怀化市', '张家界市', '常德市', '湘西自治州',
    '衡阳市', '娄底市', '郴州市',
]
# 邵阳的 7 个子期间（按 PDF 顺序）
SHAOYANG_PERIODS = ['1.1-1.10', '1.11-1.20', '1.21-1.31', '2.1-2.3', '2.4-2.10', '2.11-2.20', '2.21-2.28']

# 半月表的 14 个市州（按表格列顺序）
HUNAN_CITIES_14 = HUNAN_CITIES_13 + ['邵阳市']

# 半月表 6 种材料（含列索引信息）
HALF_MONTH_MATERIALS = [
    ('螺纹钢筋（抗震）HRB400E 20-25', 'kg'),
    ('普通硅酸盐水泥(P·O)42.5(散装)', 'kg'),
    ('天然粗砂', 'kg'),
    ('机制砂（河机砂）', 't'),
    ('碎石 10-20mm', 't'),
    ('商品混凝土（碎石）C30', 'm³'),
]


# ─── 列表页解析 ──────────────────────────────────────────────────────────────
def parse_list_page(html, base_url):
    """从列表页提取每期（<a href="...tYYYYMMDD_id.html">）"""
    soup = BeautifulSoup(html, 'html.parser')
    items = []
    for a in soup.select('a[href*="t20"][href$=".html"]'):
        href = a.get('href', '')
        title = a.get('title', '') or a.get_text(strip=True)
        # 找父 <td> 的兄弟 <td> 拿日期（但网页结构不一定统一）
        items.append({
            'title': re.sub(r'\s+', '', title.strip()),
            'publish_date': '',   # 列表页没有明确日期，从详情页或 PDF 内部取
            'detail_url': urljoin(base_url + '/zjt/hnweb/xzzx/zlxx/', href),
            'detail_path': href,
        })
    return items


def fetch_all_periods(cfg):
    """抓取所有期（首页 + 13 个分页 = 14 页）"""
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
        print(f'  [list] page {page}: {len(page_items)} 条')
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

    PDF 链接模式：<img ... pdf.gif><a href="{id}/files/{hash}.pdf">
    实际 URL = {base}/zjt/hnweb/xzzx/zlxx/{YYYYMM}/{id}/files/{hash}.pdf
    （detail_url 是 tYYYYMMDD_{id}.html，去掉 t 前缀）
    """
    html = fetch_html(detail_url, headers={'User-Agent': cfg['site']['user_agent']}, timeout=cfg['site']['timeout_sec'])
    soup = BeautifulSoup(html, 'html.parser')

    # 标题
    title = ''
    for a in soup.select('a[href$=".pdf"]'):
        title = a.get('title', '') or a.get_text(strip=True)
        break

    # PDF 相对路径
    pdf_a = soup.select_one('a[href*=".pdf"]')
    if not pdf_a:
        return title, None

    pdf_href = pdf_a.get('href', '')
    # 详情页 URL: https://zjt.hunan.gov.cn/zjt/hnweb/xzzx/zlxx/202605/t20260529_33989440.html
    # 详情页基础目录: https://zjt.hunan.gov.cn/zjt/hnweb/xzzx/zlxx/202605/
    # PDF URL: https://zjt.hunan.gov.cn/zjt/hnweb/xzzx/zlxx/202605/33989440/files/4d481c0cc3a54f86a99d7f25b7281e66.pdf
    # 即：去掉详情页 URL 中 tYYYYMMDD_{id}.html 部分，取其目录 + pdf_href
    base_dir = re.sub(r't\d{8}_\d+\.html$', '', detail_url)
    pdf_url = urljoin(base_dir + '/', pdf_href)
    return title, pdf_url


def pdf_basename(pdf_url: str) -> str:
    from urllib.parse import urlparse
    return os.path.basename(urlparse(pdf_url).path) or 'source.pdf'


# ─── PDF 解析 ────────────────────────────────────────────────────────────────
def _parse_price(s):
    """解析价格字段（支持区间 "--"、斜杠 "/"、换行、空格、人民币符号、% 趋势符）"""
    if s is None:
        return None
    s = str(s).strip()
    for ch in ['\n', '\r', '\t', ' ', ',', '￥', '¥']:
        s = s.replace(ch, '')
    if not s or s in ('—', '-', '——', '/'):
        return None
    # 区间值 "280--315" → 取平均
    m = re.match(r'^(-?\d+(?:\.\d+)?)[-—–]+(-?\d+(?:\.\d+)?)$', s)
    if m:
        try:
            return (float(m.group(1)) + float(m.group(2))) / 2
        except ValueError:
            return None
    # 负数价格（不可能，但兼容）
    try:
        v = float(s)
        return v if v != 0 else None   # 0 视为缺失
    except ValueError:
        return None


def _parse_rate(s):
    """解析涨跌幅字段 "2.43%" / "-1.79%" / "1.18" → 0.0243 (返回小数，百分数)"""
    if s is None:
        return None
    txt = str(s).strip().replace(' ', '').replace('%', '')
    if not txt or txt in ('/', '—', '-'):
        return None
    try:
        v = float(txt)
        return v / 100
    except ValueError:
        return None


def _parse_index(s):
    """解析价格指数字段 "86.05" / "101.62" → 86.05"""
    if s is None:
        return None
    txt = str(s).strip().replace(' ', '')
    if not txt or txt in ('/', '—', '-'):
        return None
    try:
        return float(txt)
    except ValueError:
        return None


def _clean_cell(s):
    """清理单元格：去换行/多余空格"""
    if s is None:
        return ''
    return re.sub(r'\s+', ' ', str(s)).strip()


def _detect_period_kind(period_label):
    """从 period 标签识别类型：
    - "行情资讯"：综合性期刊
    - "行情表"：半月刊
    """
    if '行情资讯' in period_label:
        return 'zixun'
    if '行情表' in period_label:
        return 'hangqingbiao'
    return 'unknown'


# ─── 半月表解析 ──────────────────────────────────────────────────────────────
def parse_half_month_table(page, period):
    """解析半月表（1 页 PDF）→ 14 市州 × 6 材料 = 84 条

    表格结构：15 列
      [0]序号 [1]市州
      [2-3]材料1（价格+涨跌幅）[4-5]材料2 [6-7]材料3 [8-9]材料4 [10-11]材料5 [12-13]材料6
      [14]备注
    """
    out = []
    tables = page.extract_tables() or []
    for tbl in tables:
        if not tbl or len(tbl) < 3:
            continue
        # 表头：r0=主标题+材料名（合并列），r1=价格/涨跌幅
        # 数据从 r2 开始
        header = tbl[0]
        sub_header = tbl[1] if len(tbl) > 1 else []
        # 校验：第二列是"市州"或包含"市州"
        if not any(_clean_cell(c) == '市州' for c in (header + sub_header)):
            continue

        # 数据行
        for row in tbl[2:]:
            if not row or len(row) < 14:
                continue
            no = _clean_cell(row[0])
            if not no or not no.isdigit():
                continue
            city = _clean_cell(row[1])
            remark = _clean_cell(row[14]) if len(row) > 14 else ''
            # 6 种材料价格
            for mi, (mat_name, default_unit) in enumerate(HALF_MONTH_MATERIALS):
                price_col = 2 + mi * 2
                rate_col = price_col + 1
                price = _parse_price(row[price_col]) if price_col < len(row) else None
                change_rate = _parse_rate(row[rate_col]) if rate_col < len(row) else None
                if price is None and change_rate is None:
                    continue
                out.append({
                    'no': no,
                    'breed': mat_name,
                    'spec': '',
                    'unit': default_unit,
                    'price': price,
                    'tax_price': None,   # 半月表价格是不含税价，无法直接推含税
                    'change_rate': change_rate,
                    'index_value': None,
                    'remark': remark,
                    'category': '',
                    'section': '钢筋、水泥、砂石、混凝土材料价格行情表',
                    'period': period,
                    'period_sub': '',
                    'price_kind': '不含税',
                    'province': '湖南',
                    'city': city,
                    'county': '',
                })
    return out


# ─── 行情资讯解析 ──────────────────────────────────────────────────────────────
def parse_zixun_pdf(pdf_path, period):
    """解析行情资讯（15 页 PDF）→ 4 张表数据"""
    out = []
    with pdfplumber.open(pdf_path) as pdf:
        # p1: 各市州建设工程主要材料价格表（39 列，含邵阳 7 个子期间）
        out += parse_zixun_p1_price(pdf.pages[0], period)
        # p2: 各市州建设工程主要材料价格涨跌幅度表（同结构，值是涨跌幅）
        out += parse_zixun_p2_rate(pdf.pages[1], period)
        # p3-5: 全省综合价表（8 列）
        out += parse_zixun_comprehensive_price(pdf.pages[2:5], period)
        # p6-8: 全省综合价指数表（8 列）
        out += parse_zixun_index_table(pdf.pages[5:8], period)
    return out


def parse_zixun_p1_price(page, period):
    """p1 各市州建设工程主要材料价格表 → melt

    表头：序号 / 编码 / 名称 / 规格 / 单位 / [13市州×2月=26列] / [邵阳7期间=7列]

    列结构：city 名在 odd 列（col 5, 7, 9, ...），sub（月份）在相邻偶数列（合并列）。
            "长沙 1月" → (col 5, "长沙", "1月")
            "长沙 2月" → (col 6, "长沙", "2月")，col 6 是合并列（city=None）
            "株洲 1月" → (col 7, "株洲", "1月")
            邵阳特殊：连续多个 col 都是 city="邵阳"，每个子期间独立成列
    """
    out = []
    tables = page.extract_tables() or []
    for tbl in tables:
        if not tbl or len(tbl) < 3:
            continue
        # 找 header row
        header_idx = None
        for i, row in enumerate(tbl[:6]):
            if row:
                cells = ' '.join(re.sub(r'\s+', '', str(c or '')) for c in row)
                if '序号' in cells and ('编码' in cells or '名称' in cells):
                    header_idx = i
                    break
        if header_idx is None:
            continue

        header = tbl[header_idx]
        sub_header = tbl[header_idx + 1] if header_idx + 1 < len(tbl) else []

        # 构建 city_subs 和 shaoyang_subs
        city_subs = []      # [(col_idx, city, sub), ...] 普通市州
        shaoyang_subs = []  # [(col_idx, '邵阳市', sub), ...] 邵阳子期间

        ci = 5
        while ci < len(header):
            city = _clean_cell(header[ci])
            sub = _clean_cell(sub_header[ci]) if sub_header and ci < len(sub_header) else ''
            if not city:
                ci += 1
                continue
            if city == '邵阳':
                # 连续多列 city=邵阳，每个 sub 独立
                # 注意：邵阳中间可能有合并列（header=None, sub=期间名）也要识别
                j = ci
                while j < len(header):
                    city_j = _clean_cell(header[j])
                    sub_j = _clean_cell(sub_header[j]) if sub_header and j < len(sub_header) else ''
                    if city_j == '邵阳' or (not city_j and sub_j):
                        # 是邵阳 / 或邵阳的合并列
                        if sub_j:
                            shaoyang_subs.append((j, '邵阳市', sub_j))
                        j += 1
                    else:
                        break
                ci = j
                continue
            # 普通市州
            city_subs.append((ci, city, sub or '1月'))
            # 检查 ci+1 是否还是这个城市的 2月（合并列）
            if ci + 1 < len(header):
                next_city = _clean_cell(header[ci + 1])
                next_sub = _clean_cell(sub_header[ci + 1]) if sub_header and ci + 1 < len(sub_header) else ''
                if not next_city and next_sub:
                    # 合并列，ci+1 的 sub 属于本城市
                    city_subs.append((ci + 1, city, next_sub))
            ci += 1

        # 数据行
        for row in tbl[header_idx + 2:]:
            if not row or len(row) < 6:
                continue
            if all(c is None or str(c).strip() == '' for c in row):
                continue
            seq = _clean_cell(row[0])
            code = _clean_cell(row[1])
            breed = _clean_cell(row[2])
            spec = _clean_cell(row[3])
            unit = _clean_cell(row[4])
            # 跳过分类行
            if not seq or not seq.isdigit():
                continue

            # 13 市州 × 2 月
            for col_idx, city, sub in city_subs:
                price = _parse_price(row[col_idx]) if col_idx < len(row) else None
                if price is None:
                    continue
                out.append({
                    'no': seq,
                    'code': code,
                    'breed': breed,
                    'spec': spec,
                    'unit': unit,
                    'price': price,
                    'tax_price': None,
                    'change_rate': None,
                    'index_value': None,
                    'remark': '',
                    'category': '',
                    'section': '各市州建设工程主要材料价格表',
                    'period': period,
                    'period_sub': sub,
                    'price_kind': '不含税',
                    'province': '湖南',
                    'city': city,
                    'county': '',
                })

            # 邵阳 × 7 子期间
            for col_idx, city, sub in shaoyang_subs:
                price = _parse_price(row[col_idx]) if col_idx < len(row) else None
                if price is None:
                    continue
                out.append({
                    'no': seq,
                    'code': code,
                    'breed': breed,
                    'spec': spec,
                    'unit': unit,
                    'price': price,
                    'tax_price': None,
                    'change_rate': None,
                    'index_value': None,
                    'remark': '',
                    'category': '',
                    'section': '各市州建设工程主要材料价格表',
                    'period': period,
                    'period_sub': sub,
                    'price_kind': '不含税',
                    'province': '湖南',
                    'city': city,
                    'county': '',
                })
    return out


def parse_zixun_p2_rate(page, period):
    """p2 各市州建设工程主要材料价格涨跌幅度表 → melt（同结构，值是涨跌幅）"""
    out = []
    tables = page.extract_tables() or []
    for tbl in tables:
        if not tbl or len(tbl) < 3:
            continue
        header_idx = None
        for i, row in enumerate(tbl[:6]):
            if row:
                cells = ' '.join(re.sub(r'\s+', '', str(c or '')) for c in row)
                if '序号' in cells and '编码' in cells:
                    header_idx = i
                    break
        if header_idx is None:
            continue

        header = tbl[header_idx]
        sub_header = tbl[header_idx + 1] if header_idx + 1 < len(tbl) else []

        # 同 p1 构建 city_subs 和 shaoyang_subs
        city_subs = []
        shaoyang_subs = []
        ci = 5
        while ci < len(header):
            city = _clean_cell(header[ci])
            sub = _clean_cell(sub_header[ci]) if sub_header and ci < len(sub_header) else ''
            if not city:
                ci += 1
                continue
            if city == '邵阳':
                # 注意：邵阳中间可能有合并列（header=None, sub=期间名）也要识别
                j = ci
                while j < len(header):
                    city_j = _clean_cell(header[j])
                    sub_j = _clean_cell(sub_header[j]) if sub_header and j < len(sub_header) else ''
                    if city_j == '邵阳' or (not city_j and sub_j):
                        if sub_j:
                            shaoyang_subs.append((j, '邵阳市', sub_j))
                        j += 1
                    else:
                        break
                ci = j
                continue
            city_subs.append((ci, city, sub or '1月'))
            if ci + 1 < len(header):
                next_city = _clean_cell(header[ci + 1])
                next_sub = _clean_cell(sub_header[ci + 1]) if sub_header and ci + 1 < len(sub_header) else ''
                if not next_city and next_sub:
                    city_subs.append((ci + 1, city, next_sub))
            ci += 1

        for row in tbl[header_idx + 2:]:
            if not row or len(row) < 6:
                continue
            if all(c is None or str(c).strip() == '' for c in row):
                continue
            seq = _clean_cell(row[0])
            code = _clean_cell(row[1])
            breed = _clean_cell(row[2])
            spec = _clean_cell(row[3])
            unit = _clean_cell(row[4])
            if not seq or not seq.isdigit():
                continue

            for col_idx, city, sub in city_subs:
                rate = _parse_rate(row[col_idx]) if col_idx < len(row) else None
                if rate is None:
                    continue
                out.append({
                    'no': seq,
                    'code': code,
                    'breed': breed,
                    'spec': spec,
                    'unit': unit,
                    'price': None,
                    'tax_price': None,
                    'change_rate': rate,
                    'index_value': None,
                    'remark': '',
                    'category': '',
                    'section': '各市州建设工程主要材料价格涨跌幅度表',
                    'period': period,
                    'period_sub': sub,
                    'price_kind': '',
                    'province': '湖南',
                    'city': city,
                    'county': '',
                })

            for col_idx, city, sub in shaoyang_subs:
                rate = _parse_rate(row[col_idx]) if col_idx < len(row) else None
                if rate is None:
                    continue
                out.append({
                    'no': seq,
                    'code': code,
                    'breed': breed,
                    'spec': spec,
                    'unit': unit,
                    'price': None,
                    'tax_price': None,
                    'change_rate': rate,
                    'index_value': None,
                    'remark': '',
                    'category': '',
                    'section': '各市州建设工程主要材料价格涨跌幅度表',
                    'period': period,
                    'period_sub': sub,
                    'price_kind': '',
                    'province': '湖南',
                    'city': city,
                    'county': '',
                })
    return out


def parse_zixun_comprehensive_price(pages, period):
    """p3-5 全省综合价表（8 列）→ 每行 3 个时点"""
    out = []
    for page in pages:
        tables = page.extract_tables() or []
        for tbl in tables:
            if not tbl or len(tbl) < 3:
                continue
            # 找 header（含"全省综合价"）
            header_idx = None
            for i, row in enumerate(tbl[:6]):
                if row:
                    cells = ' '.join(re.sub(r'\s+', '', str(c or '')) for c in row)
                    if '序号' in cells and ('编码' in cells or '名称' in cells):
                        header_idx = i
                        break
            if header_idx is None:
                continue

            header = tbl[header_idx]
            # 时点列：通常 3 列（2019 / 2025 / 2026）或多列
            time_points = []  # [(col_idx, year_label), ...]
            for ci in range(5, len(header)):
                cell = _clean_cell(header[ci])
                if cell:
                    # 提取年份（如"2019年1-2月"）
                    m = re.search(r'(\d{4})\s*年', cell)
                    year_label = cell if m else cell
                    time_points.append((ci, cell))

            for row in tbl[header_idx + 1:]:
                if not row or len(row) < 6:
                    continue
                if all(c is None or str(c).strip() == '' for c in row):
                    continue
                seq = _clean_cell(row[0])
                code = _clean_cell(row[1])
                breed = _clean_cell(row[2])
                spec = _clean_cell(row[3])
                unit = _clean_cell(row[4])
                if not seq or not seq.isdigit():
                    continue

                for col_idx, time_label in time_points:
                    price = _parse_price(row[col_idx]) if col_idx < len(row) else None
                    if price is None:
                        continue
                    out.append({
                        'no': seq,
                        'code': code,
                        'breed': breed,
                        'spec': spec,
                        'unit': unit,
                        'price': price,
                        'tax_price': None,
                        'change_rate': None,
                        'index_value': None,
                        'remark': '',
                        'category': '',
                        'section': '建设工程主要材料全省综合价表',
                        'period': period,
                        'period_sub': time_label,
                        'price_kind': '不含税',
                        'province': '湖南',
                        'city': '湖南省',
                        'county': '',
                    })
    return out


def parse_zixun_index_table(pages, period):
    """p6-8 全省综合价指数表（8 列）→ 每行 3 个指数（定基/环比/同比）"""
    out = []
    for page in pages:
        tables = page.extract_tables() or []
        for tbl in tables:
            if not tbl or len(tbl) < 3:
                continue
            header_idx = None
            for i, row in enumerate(tbl[:6]):
                if row:
                    cells = ' '.join(re.sub(r'\s+', '', str(c or '')) for c in row)
                    if '序号' in cells and ('指数' in cells or '定基' in cells):
                        header_idx = i
                        break
            if header_idx is None:
                continue

            header = tbl[header_idx]
            index_cols = []
            for ci in range(5, len(header)):
                cell = _clean_cell(header[ci])
                if cell:
                    index_cols.append((ci, cell))

            for row in tbl[header_idx + 1:]:
                if not row or len(row) < 6:
                    continue
                if all(c is None or str(c).strip() == '' for c in row):
                    continue
                seq = _clean_cell(row[0])
                code = _clean_cell(row[1])
                breed = _clean_cell(row[2])
                spec = _clean_cell(row[3])
                unit = _clean_cell(row[4])
                if not seq or not seq.isdigit():
                    continue

                for col_idx, index_label in index_cols:
                    val = _parse_index(row[col_idx]) if col_idx < len(row) else None
                    if val is None:
                        continue
                    out.append({
                        'no': seq,
                        'code': code,
                        'breed': breed,
                        'spec': spec,
                        'unit': unit,
                        'price': None,
                        'tax_price': None,
                        'change_rate': None,
                        'index_value': val,
                        'remark': '',
                        'category': '',
                        'section': '建设工程主要材料全省综合价指数表',
                        'period': period,
                        'period_sub': index_label,
                        'price_kind': '',
                        'province': '湖南',
                        'city': '湖南省',
                        'county': '',
                    })
    return out


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
def _doc_id(period, section, no, code, breed, spec, city, period_sub, extra=''):
    raw = f'{period}|{section}|{no}|{code}|{breed}|{spec}|{city}|{period_sub}|{extra}'
    return hashlib.md5(raw.encode('utf-8')).hexdigest()


def bulk_index(es, index, docs):
    """幂等写入（按 _id upsert）"""
    if not docs:
        return 0, 0
    body = ''
    for d in docs:
        # 半月表无 code 字段，用 no+breed 区分；其它用 code
        code = d.get('code', '')
        # 把 price/change_rate/index_value 任一非空的字段作为 extra（同一材料同一期同一城市不应有重复值类型）
        extra = ''
        if d.get('change_rate') is not None:
            extra = 'rate'
        elif d.get('index_value') is not None:
            extra = 'idx'
        _id = _doc_id(d['period'], d['section'], d['no'], code, d['breed'], d['spec'],
                      d.get('city', ''), d.get('period_sub', ''), extra)
        body += json.dumps({'index': {'_index': index, '_id': _id}}, ensure_ascii=False) + '\n'
        body += json.dumps(d, ensure_ascii=False) + '\n'
    resp = es.bulk(body=body, refresh=False)
    if resp.get('errors'):
        errors = sum(1 for it in resp['items'] if 'error' in it.get('index', {}))
        return len(docs) - errors, errors
    return len(docs), 0


# ─── 主流程 ──────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description='湖南建设工程材料价格行情同步')
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

    print(f'[hunan] ES: {es_host}')
    print(f'[hunan] MinIO: {cfg["minio"]["endpoint"]} / {cfg["minio"]["bucket"]}')
    print(f'[hunan] journal_keywords: {cfg.get("journal_keywords", [])}')

    print('[hunan] 抓取列表...')
    items = fetch_all_periods(cfg)
    print(f'[hunan] 共 {len(items)} 条')

    keywords = cfg.get('journal_keywords', [])
    todo = []
    for it in items:
        # 必须含至少一个关键字
        if not any(kw in it['title'] for kw in keywords):
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

    print(f'[hunan] 待处理 {len(todo)} 期')
    if not todo:
        print('[hunan] 无新数据')
        return

    total_written = 0
    for idx, item in enumerate(todo, 1):
        print(f'\n[hunan] [{idx}/{len(todo)}] {item["title"]}')
        start = time.time()
        try:
            title, pdf_url = fetch_detail_pdf(cfg, item['detail_url'])
            if not pdf_url:
                print(f'  ✗ 详情页无 PDF 链接')
                progress['done'][item['detail_url']] = {
                    'status': 'failed',
                    'error': 'no pdf link in detail page',
                }
                save_progress(progress)
                continue
            print(f'  PDF: {pdf_url}')

            # period 从 title 提取
            m = re.search(r'(\d{4})\s*年\s*第?([\d-]+)期|（(\d+)-(\d+)\s*月份）', item['title'])
            if '行情资讯' in item['title']:
                # "2026年第一期（1-2月份）湖南省建设工程材料价格行情资讯"
                mm = re.search(r'(\d{4})\s*年\s*第?([一二三四五六七八九十\d]+)期', item['title'])
                if mm:
                    period = f'{mm.group(1)}.第{mm.group(2)}期(行情资讯)'
                else:
                    period = item['title'][:30]
            elif '行情表' in item['title']:
                # "2026年全省第八期钢筋、水泥、砂石、混凝土材料价格行情表"
                mm = re.search(r'(\d{4})\s*年\s*全省\s*第?([\d]+)期', item['title'])
                if mm:
                    period = f'{mm.group(1)}.第{mm.group(2)}期(行情表)'
                else:
                    period = item['title'][:30]
            else:
                period = item['title'][:30]
            print(f'  period: {period}')

            basename = pdf_basename(pdf_url)
            minio_key = f'{cfg["minio"]["prefix"]}/{period}/{basename}'

            with tempfile.TemporaryDirectory() as tmpdir:
                local_pdf = os.path.join(tmpdir, 'source.pdf')
                download_file(pdf_url, local_pdf, timeout=600)

                if not args.dry_run:
                    upload_to_minio(s3, cfg['minio']['bucket'], minio_key, local_pdf)
                print(f'  minio: {minio_key}')

                # 解析
                if '行情资讯' in item['title']:
                    rows = parse_zixun_pdf(local_pdf, period)
                elif '行情表' in item['title']:
                    with pdfplumber.open(local_pdf) as pdf:
                        rows = parse_half_month_table(pdf.pages[0], period)
                else:
                    rows = []
                print(f'  parsed: {len(rows)} 行')

                now = datetime.now().isoformat(timespec='seconds')
                docs = []
                for r in rows:
                    docs.append({
                        'no': r['no'],
                        'code': r.get('code', ''),
                        'breed': r['breed'],
                        'spec': r['spec'],
                        'unit': r['unit'],
                        'price': r['price'],
                        'tax_price': r['tax_price'],
                        'change_rate': r.get('change_rate'),
                        'index_value': r.get('index_value'),
                        'remark': r.get('remark', ''),
                        'category': r.get('category', ''),
                        'section': r['section'],
                        'period': r['period'],
                        'period_sub': r.get('period_sub', ''),
                        'price_kind': r.get('price_kind', ''),
                        'province': '湖南',
                        'city': r.get('city', ''),
                        'county': r.get('county', ''),
                        'update_date': item.get('publish_date', ''),
                        'create_time': now,
                        'source_pdf': minio_key,
                        'source_url': pdf_url,
                    })

                if args.dry_run:
                    print(f'  [dry-run] 将写 {len(docs)} 条到 {cfg["es"]["ods_index"]}')
                    from collections import Counter
                    sec_counter = Counter(d['section'] for d in docs)
                    city_counter = Counter(d['city'] for d in docs)
                    period_sub_counter = Counter(d['period_sub'] for d in docs)
                    print(f'  by section: {dict(sec_counter)}')
                    print(f'  by city (TOP 15): {dict(city_counter.most_common(15))}')
                    print(f'  by period_sub (TOP 10): {dict(period_sub_counter.most_common(10))}')
                    print('  sample (前 5):')
                    for d in docs[:5]:
                        print(f"    {d['no']:5s} | {d['city']:10s} | {d['section'][:30]:30s} | "
                              f"{d['period_sub']:10s} | {d['breed'][:25]:25s} | "
                              f"{d['unit']:6s} = {d['price']} (rate {d['change_rate']}) (idx {d['index_value']})")
                    ok = len(docs)
                    err = 0
                else:
                    ok, err = bulk_index(es, cfg['es']['ods_index'], docs)
                    print(f'  bulk: ok={ok}, err={err}')

                elapsed = time.time() - start
                progress['done'][item['detail_url']] = {
                    'period': period,
                    'publish_date': item.get('publish_date', ''),
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
                        'publish_date': item.get('publish_date', ''),
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
            import traceback
            traceback.print_exc()
            progress['done'][item['detail_url']] = {
                'publish_date': item.get('publish_date', ''),
                'detail_url': item['detail_url'],
                'status': 'failed',
                'error': str(e),
                'duration_sec': round(elapsed, 1),
            }
            save_progress(progress)

    print(f'\n[hunan] 全部完成: total_written={total_written}')


if __name__ == '__main__':
    main()