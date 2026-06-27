"""江西建设工程材料信息参考价 - 同步主程序

流程：
1. 抓取列表（var articleList = [...] 直接嵌入 HTML），提取每期
2. 过滤：标题含"江西省材料价格参考信息" + 年份
3. 对每期：
   a. 列表里直接给出 articleFiles[0].filePath → PDF URL（无需访问详情页）
   b. 下载 PDF → 本地临时文件
   c. 上传 MinIO
   d. pdfplumber 解析 → 长表
      - 17 列表格（含"南昌"/"九江"/..."鹰潭"列）：全省表 → melt
      - ≥10 列表格（含"县"列）：县汇总表 → melt
      - 7 列表格（"序号 / 材料价格 / 规格型号 / 单位 / 信息参考价 / 税率 / 备注"）：
        设区市补充表 → 直接长表
   e. bulk_index 到 ods_material_jiangxi_price（幂等 _id）
   f. 写进度（本地 JSON + ES progress 索引）

PDF 结构（92 页）：
- p1 封面 / p2 编制说明 / p3 编制人员 / p4 目录
- p6-p16 全省各设区市价格信息汇总表（17 列：序号/类别/名称/规格/单位/11城市/税率）
- p17-p33 南昌市补充部分地材信息参考价（7 列：序号/材料价格/规格/单位/信息参考价/税率/备注）
- p36-p40 南昌市补充（续）
- p41-p45 九江市补充部分地材信息参考价
- p46-p48 九江市各县（市、区）工程常用材料价格汇总表（17 列：序号/名称/规格/单位/12县/税率/备注）
- p49-p50 上饶市补充
- p51-p53 上饶市各县汇总（17 列：12 县/三清山）
- p54-p55 抚州市补充 / 抚州市各县汇总（16 列：11 县）
- p58-p60 宜春市补充 / 宜春市各县汇总（14 列：9 县市）
- p61-p65 吉安市补充 / 吉安市各县汇总
- p66-p69 赣州市补充（地材）
- p70-p74 赣州市中心城区园林苗木信息参考价
- p75-p76 赣州市宁都县常用材料价格汇总表（7 列：单县表）
- p80-p82 景德镇市补充 / 景德镇乐平市汇总
- p83-p85 萍乡市补充
- p86-p87 萍乡市各县汇总
- p88-p90 新余市补充
- p91 鹰潭市补充
- p92 勘误（不解析）

每张表都有"增值税税率"列（13% / 3% / 9%），价格已是含税价。
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

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

from utils import (
    load_config, get_es_client, get_s3_client,
    ensure_bucket, ensure_ods_index, ensure_progress_index,
    fetch_html, download_file, upload_to_minio,
)

PROGRESS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '.jiangxi_sync_progress.json')


# 江西省 11 个设区市（用于识别全省表列名）
JIANGXI_CITIES = [
    '南昌', '九江', '上饶', '抚州', '宜春', '吉安', '赣州', '景德镇', '萍乡', '新余', '鹰潭',
]

# 全省表 / 县表共有的列：表头第 1-4 列
COMMON_HEADER_KEYS = {
    '序号': 0,
    '材料类别': 1,   # 仅全省表
    '材料名称': 1,   # 全省表 / 多县表
    '材料价格': 1,   # 设区市补充表
    '规格型号': 2,
    '规格及型号': 2,
    '单位': 3,
}

# 全省表 11 城市列位置（5-15）
PROVINCE_TABLE_CITY_START = 5
PROVINCE_TABLE_CITY_END = 16   # 16 是"增值税税率"列

# 设区市补充表（7 列）列位置
CITY_TABLE_PRICE_COL = 4
CITY_TABLE_VAT_COL = 5
CITY_TABLE_REMARK_COL = 6

# 多县表（≥10 列）共性：前 4 列固定 + 多个县列 + 倒数 2 列是"增值税税率"+"备注"
COUNTY_TABLE_DATA_START = 4
COUNTY_TABLE_VAT_REMARK_TAIL = 2   # 末尾 2 列固定是税率 + 备注


# ─── 列表页解析 ──────────────────────────────────────────────────────────────
ARTICLE_LIST_RE = re.compile(r'var\s+articleList\s*=\s*(\[.*?\]);', re.DOTALL)


def parse_list_page(html, base_url):
    """从列表页提取每期（var articleList = [...] 嵌入 JSON）"""
    m = ARTICLE_LIST_RE.search(html)
    if not m:
        return []
    try:
        raw = m.group(1)
        items = json.loads(raw)
    except Exception as e:
        print(f'  [list] JSON 解析失败: {e}')
        return []

    out = []
    for it in items:
        title = re.sub(r'<[^>]+>', '', it.get('title', '')).strip()
        pub = it.get('pubDate', '') or ''   # "2026-06-05 15:19"
        publish_date = pub.split(' ')[0] if pub else ''

        # PDF URL：从 articleFiles[0] 提取
        article_files = it.get('articleFiles') or []
        pdf_url = ''
        if article_files:
            af = article_files[0]
            domain = af.get('domainName', '') or base_url
            file_path = af.get('filePath', '') or ''
            if file_path:
                pdf_url = domain.rstrip('/') + file_path
            else:
                # 备选：从 url 字段
                url_path = af.get('url', '') or ''
                if url_path.startswith('http'):
                    pdf_url = url_path
                elif url_path:
                    pdf_url = domain.rstrip('/') + url_path

        # 详情页 URL（备用）
        urls_obj = it.get('urls') or ''
        detail_url = ''
        try:
            urls = json.loads(urls_obj) if urls_obj else {}
            detail_url = urljoin(base_url + '/jxszfhcxjst/gqcyc/pc/list.html', urls.get('pc', ''))
        except Exception:
            detail_url = ''

        out.append({
            'title': title,
            'publish_date': publish_date,
            'detail_url': detail_url,
            'pdf_url': pdf_url,
            'id': it.get('id', ''),
        })
    return out


def fetch_all_periods(cfg):
    """抓取所有期（单页列表）"""
    site = cfg['site']
    url = site['base_url'] + site['list_path']
    try:
        html = fetch_html(url, headers={'User-Agent': site['user_agent']}, timeout=site['timeout_sec'])
    except Exception as e:
        print(f'  [list] 失败: {e}')
        return []
    items = parse_list_page(html, site['base_url'])
    print(f'  [list] 共 {len(items)} 期')
    # 去重（按 id）
    seen = set()
    uniq = []
    for it in items:
        if it['id'] in seen:
            continue
        seen.add(it['id'])
        uniq.append(it)
    return uniq


def pdf_basename(pdf_url: str) -> str:
    from urllib.parse import urlparse
    return os.path.basename(urlparse(pdf_url).path) or 'source.pdf'


# ─── PDF 解析 ────────────────────────────────────────────────────────────────
def _parse_price(s):
    """解析价格字段（支持区间 "280--315"、斜杠 "/"、换行、空格、人民币符号）"""
    if s is None:
        return None
    s = str(s).strip()
    for ch in ['\n', '\r', '\t', ' ', ',', '￥', '¥']:
        s = s.replace(ch, '')
    if not s or s in ('—', '-', '——', '/'):
        return None
    # 区间值 "280--315" → 取平均
    m = re.match(r'^(\d+(?:\.\d+)?)[-—–]+(\d+(?:\.\d+)?)$', s)
    if m:
        try:
            return (float(m.group(1)) + float(m.group(2))) / 2
        except ValueError:
            return None
    # 多值 "106/140" → 取第一个
    if '/' in s:
        first = s.split('/')[0]
        try:
            v = float(first)
            return v if v > 0 else None
        except ValueError:
            return None
    try:
        v = float(s)
        return v if v > 0 else None
    except ValueError:
        return None


def _parse_vat_rate(s):
    """解析税率字段 "13%" / "3%" / "9%" / "13" → 0.13"""
    if s is None:
        return None
    txt = str(s).strip().replace(' ', '').replace('%', '')
    if not txt or txt == '/':
        return None
    try:
        v = float(txt)
        if v > 0:
            return v / 100
    except ValueError:
        return None
    return None


def _clean_cell(s):
    """清理单元格：去换行/多余空格"""
    if s is None:
        return ''
    return re.sub(r'\s+', ' ', str(s)).strip()


def _detect_page_kind(text, current_kind):
    """从页眉识别页面类型（页头第 1-3 行）"""
    head_lines = [l.strip() for l in (text or '').split('\n')[:5] if l.strip()]
    head_text = ' '.join(head_lines)
    # 折叠重复字符（PDF 字间距问题）
    folded = re.sub(r'(.)\1+', r'\1', head_text)

    if '全省各设区市价格信息' in folded:
        return 'province'
    if '各县' in folded and '价格信息' in folded:
        return 'county_summary'
    if '价格信息' in folded:
        return 'city_supplement'
    if '勘误' in folded:
        return 'errata'
    return current_kind or 'unknown'


def _detect_current_city(text, current_city):
    """从页头识别当前设区市（优先识别单县/单市）"""
    head_lines = [l.strip() for l in (text or '').split('\n')[:3] if l.strip()]
    head_text = ' '.join(head_lines)
    # 折叠重复字符（PDF 字间距问题，如"景景德德镇镇市市"）
    folded = re.sub(r'(.)\1+', r'\1', head_text)
    # 优先识别"X市Y县/Y市价格信息"中的 Y（单县表 / 单市表）
    m = re.search(r'([\u4e00-\u9fff]{2,3})市([\u4e00-\u9fff]{2,3}[县市])价格信息', folded)
    if m:
        inner = m.group(2)
        if inner in ('宁都县', '乐平市'):
            return inner
    # 备选：找"宁都县" / "乐平市"字样
    for special in ['宁都县', '乐平市']:
        if special in folded:
            return special
    # 备选：head_text 含"乐平"（不带"市"字）且 current_city 是"乐平市"，继承
    if '乐平' in folded and current_city == '乐平市':
        return '乐平市'
    if '宁都' in folded and current_city == '宁都县':
        return '宁都县'
    # 设区市（返回加"市"字）
    for city in JIANGXI_CITIES:
        if f'{city}市' in folded:
            return city + '市'
    return current_city


def _detect_table_kind(header_row):
    """识别表格类型：province / county_summary / city_supplement / unknown

    province: 列头含 ≥8 个城市名（南昌/九江/.../鹰潭）
    county_summary: 列头含"县"或"区"，且 ≥10 列，且不含城市组合关键字
    city_supplement: 6/7 列结构（序号/材料价格/规格/单位/信息参考价/税率/可选备注）
    """
    if not header_row:
        return 'unknown'
    n_cols = len(header_row)
    # cells_text 去掉换行符，避免"增值税税\n率"导致"税率"匹配失败
    cells_text = ' '.join(re.sub(r'\s+', '', str(c or '')) for c in header_row)

    # 检测"省/设区市/县"等地理列
    city_hits = sum(1 for c in JIANGXI_CITIES if c in cells_text)
    has_county = ('县' in cells_text) or ('区' in cells_text)
    has_county_or_city = has_county or ('市' in cells_text)

    # 全省表：11 个设区市至少 8 个出现 + 17 列
    if city_hits >= 8 and n_cols == 17:
        return 'province'

    # 县汇总表：列头有"县"或"区"等地理名 + 列数 ≥10
    if has_county and n_cols >= 10:
        return 'county_summary'

    # 设区市补充表：6-7 列结构（含"信息参考价"+"税率"或单县/单市+"税率"等）
    if n_cols in (6, 7):
        if '信息参考价' in cells_text and '税率' in cells_text:
            return 'city_supplement'
        # 单县表（如宁都县 7 列：序号/材料名称/规格/单位/宁都县/税率/备注）
        # 单市表（如乐平市 6 列：序号/材料名称/规格/单位/乐平市/税率）
        if has_county_or_city and '税率' in cells_text:
            return 'city_supplement'

    # 园林苗木表：9 列结构（序号/苗木名称/胸径/地径/高度/冠幅/单位/信息参考价/税率）
    if n_cols == 9 and '苗木名称' in cells_text and '胸径' in cells_text:
        return 'plant'

    return 'unknown'


def _extract_county_columns(header_row):
    """从多县表头提取县名列"""
    counties = []
    for cell in header_row[COUNTY_TABLE_DATA_START:]:
        c = str(cell or '').strip()
        if c and '税率' not in c and '备注' not in c and c not in ('增值税', '率', '率（%）'):
            counties.append(c)
    return counties


def _parse_province_table(tbl, header_idx, section_name, out):
    """17 列全省表 → melt 成长表（每个设区市一行）"""
    if header_idx + 1 >= len(tbl):
        return
    header = tbl[header_idx]
    # 城市列位置 5-15（11 个设区市）
    city_cols = []
    for ci in range(PROVINCE_TABLE_CITY_START, PROVINCE_TABLE_CITY_END):
        if ci < len(header):
            city_name = _clean_cell(header[ci])
            # 去掉"增值税"等误识别（防最后列混入）
            if city_name and city_name not in ('增值税', '税率', '增值税税率'):
                city_cols.append((ci, city_name))

    data_rows = tbl[header_idx + 1:]
    for row in data_rows:
        if not row or len(row) < 17:
            continue
        if all(c is None or str(c).strip() == '' for c in row):
            continue
        seq = _clean_cell(row[0])
        if not seq.isdigit():
            continue
        category = _clean_cell(row[1])   # 材料类别
        breed = _clean_cell(row[1])      # 实际"材料名称"在 row[2] 全省表 17 列
        # 全省表实际列：0=序号 1=材料类别 2=材料名称 3=规格 4=单位 5-15=城市 16=税率
        # 修正：上面写错了，重读
        if len(row) >= 17:
            category = _clean_cell(row[1])   # 材料类别
            breed = _clean_cell(row[2])      # 材料名称
            spec = _clean_cell(row[3])
            unit = _clean_cell(row[4])
            vat_rate = _parse_vat_rate(row[16])
        else:
            continue

        for col_idx, city_name in city_cols:
            price = _parse_price(row[col_idx])
            if price is None:
                continue
            out.append({
                'no': seq,
                'breed': breed,
                'spec': spec,
                'unit': unit,
                'price': price,
                'tax_price': price,  # PDF 给的是含税价
                'remark': '',
                'category': category,
                'section': section_name,
                'region': '',
                'city': city_name,
                'vat_rate': vat_rate,
            })


def _parse_county_table(tbl, header_idx, section_name, parent_city, out):
    """多县表 → melt（每个县一行）"""
    if header_idx + 1 >= len(tbl):
        return
    header = tbl[header_idx]
    n_cols = len(header)

    # 县列位置 = header[4..N-3]（倒数第 3 是税率，倒数 2 是备注，列 0-3 是固定）
    # 但有时税率列在倒数第 2（无备注）
    # 简化：遍历 header[4..]，含"税率"和"备注"标志的列排除
    county_cols = []
    for ci, cell in enumerate(header[4:], start=4):
        c_raw = _clean_cell(cell)
        if not c_raw:
            continue
        # 折叠空白后判断（如"增值税税\n率（%）" 折叠为"增值税税率（%）"）
        c_fold = re.sub(r'\s+', '', c_raw)
        if '税率' in c_fold:
            continue
        if '备注' in c_fold:
            continue
        county_cols.append((ci, c_raw))

    data_rows = tbl[header_idx + 1:]
    for row in data_rows:
        if not row or len(row) < 6:
            continue
        if all(c is None or str(c).strip() == '' for c in row):
            continue
        seq = _clean_cell(row[0])
        if not seq.isdigit():
            continue
        # 多县表表头：序号 / 材料名称 / 规格及型号 / 单位 / 县价... / 税率 / 备注
        breed = _clean_cell(row[1])
        spec = _clean_cell(row[2])
        unit = _clean_cell(row[3])
        # 税率列在倒数第 2（无备注）或 倒数第 1（有备注）
        vat_rate = None
        remark = ''
        if len(row) >= 2:
            tail1 = _clean_cell(row[-1])
            tail2 = _clean_cell(row[-2]) if len(row) >= 2 else ''
            if _parse_vat_rate(tail1) is not None:
                vat_rate = _parse_vat_rate(tail1)
                remark = ''
            elif _parse_vat_rate(tail2) is not None:
                vat_rate = _parse_vat_rate(tail2)
                remark = tail1
            else:
                # 兜底：最后一列做备注
                remark = tail1

        for col_idx, county_name in county_cols:
            price = _parse_price(row[col_idx])
            if price is None:
                continue
            out.append({
                'no': seq,
                'breed': breed,
                'spec': spec,
                'unit': unit,
                'price': price,
                'tax_price': price,
                'remark': remark,
                'category': '',
                'section': section_name,
                'region': county_name,
                'city': parent_city or '',
                'vat_rate': vat_rate,
            })


def _parse_plant_table(tbl, header_idx, section_name, parent_city, out):
    """9 列园林苗木表 → 长表

    表头：序号 / 苗木名称 / 胸径 / 地径 / 高度 / 冠幅 / 单位 / 信息参考价 / 增值税税率
    """
    if header_idx + 1 >= len(tbl):
        return
    data_rows = tbl[header_idx + 1:]
    for row in data_rows:
        if not row or len(row) < 9:
            continue
        if all(c is None or str(c).strip() == '' for c in row):
            continue
        seq = _clean_cell(row[0])
        if not seq.isdigit():
            continue
        breed = _clean_cell(row[1])
        # 规格由胸径/地径/高度/冠幅组合
        spec_parts = []
        for col_idx, label in [(2, '胸径'), (3, '地径'), (4, '高度'), (5, '冠幅')]:
            v = _clean_cell(row[col_idx])
            if v and v != '/':
                spec_parts.append(f'{label}{v}')
        spec = ' '.join(spec_parts) if spec_parts else '/'
        unit = _clean_cell(row[6])
        price = _parse_price(row[7])
        vat_rate = _parse_vat_rate(row[8])
        if price is None:
            continue
        out.append({
            'no': seq,
            'breed': breed,
            'spec': spec,
            'unit': unit,
            'price': price,
            'tax_price': price,
            'remark': '',
            'category': '园林苗木',
            'section': section_name,
            'region': '',
            'city': parent_city or section_name,
            'vat_rate': vat_rate,
        })


def _parse_city_supplement_table(tbl, header_idx, section_name, parent_city, out):
    """6/7 列设区市补充表 / 单县表 → 直接长表

    表头（7 列）：序号 / 材料价格(或材料名称) / 规格型号 / 单位 / 信息参考价 / 增值税税率 / 备注
    表头（6 列，如抚州市 p54）：序号 / 材料价格 / 规格型号 / 单位 / 信息参考价 / 增值税税率
    单县表（如宁都县 7 列）：序号 / 材料名称 / 规格 / 单位 / 县名 / 税率 / 备注
    """
    if header_idx + 1 >= len(tbl):
        return
    data_rows = tbl[header_idx + 1:]
    for row in data_rows:
        if not row or len(row) < 6:
            continue
        if all(c is None or str(c).strip() == '' for c in row):
            continue
        seq = _clean_cell(row[0])
        if not seq.isdigit():
            continue
        # 设区市补充：0=序号 1=材料价格/名称 2=规格 3=单位 4=信息参考价 5=税率 (6=备注)
        breed = _clean_cell(row[1])
        spec = _clean_cell(row[2])
        unit = _clean_cell(row[3])
        price = _parse_price(row[4])
        vat_rate = _parse_vat_rate(row[5])
        remark = _clean_cell(row[6]) if len(row) > 6 else ''
        if price is None:
            continue

        out.append({
            'no': seq,
            'breed': breed,
            'spec': spec,
            'unit': unit,
            'price': price,
            'tax_price': price,
            'remark': remark,
            'category': '',
            'section': section_name,
            'region': parent_city if parent_city and ('县' in section_name or '区' in section_name) else '',
            'city': parent_city or section_name,
            'vat_rate': vat_rate,
        })


def parse_pdf(pdf_path):
    """解析 PDF → 长表 [{...}]"""
    out = []
    current_kind = ''           # 页面类型（province / county_summary / city_supplement / errata）
    current_city = ''           # 当前设区市
    current_section = ''        # 当前 section 标签（如"全省" / "南昌市补充" / "九江县汇总"）

    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            try:
                text = page.extract_text() or ''
            except Exception:
                continue
            if not text:
                continue

            # 页头识别
            new_kind = _detect_page_kind(text, current_kind)
            if new_kind != current_kind:
                current_kind = new_kind
                current_section = ''
            if current_kind == 'errata':
                continue

            # 当前设区市
            new_city = _detect_current_city(text, current_city)
            if new_city != current_city:
                current_city = new_city
                # 注意：城市切换时不完全重置 current_section（让"乐平市"续表能继承）
                # 只在 page_kind 变化时重置 section

            # 章节标题识别（页面前 5 行内）
            head_lines = [l.strip() for l in text.split('\n')[:6] if l.strip()]
            head_text = ' '.join(head_lines)
            # 折叠重复字符（PDF 字间距问题）
            head_folded = re.sub(r'(.)\1+', r'\1', head_text)
            # "2026 年 5 月xx市补充部分地材信息参考价" / "xx市宁都县常用材料价格汇总表" → 章节名
            # 精确模式：补充部分地材信息参考价 / 常用材料价格汇总表 / 中心城区园林苗木信息参考价
            #  / 工程常用材料信息参考价 / 工程常用地方材料信息参考价 / 工程材料信息参考价
            m = re.search(
                r'\d{4}\s*年\s*\d{1,2}\s*月(.+?(?:补充部分地材信息参考价|常用材料价格汇总表|中心城区园林苗木信息参考价|补充材料价格信息汇总表|工程常用材料信息参考价|工程常用地方材料信息参考价|工程材料信息参考价|汇总表))',
                head_folded
            )
            if m:
                current_section = m.group(1).strip()

            tables = page.extract_tables() or []
            for tbl in tables:
                if not tbl or len(tbl) < 2:
                    continue
                # 找表头行（含"序号"+"材料/项目/价格/苗木/名称"等）
                header_idx = None
                for i, row in enumerate(tbl[:6]):
                    if row:
                        # cells 去除换行符，避免"序\n号"导致"序号"匹配失败
                        cells = ' '.join(re.sub(r'\s+', '', str(c or '')) for c in row)
                        if '序号' in cells and ('材料' in cells or '项目' in cells or '价格' in cells
                                                or '苗木' in cells or '信息参考价' in cells or '名称' in cells):
                            header_idx = i
                            break
                if header_idx is None:
                    continue

                header_row = tbl[header_idx]
                n_cols = len(header_row)
                kind = _detect_table_kind(header_row)
                if kind == 'unknown':
                    continue

                # 决定 section 名称
                if kind == 'province':
                    section_name = '全省各设区市'
                    _parse_province_table(tbl, header_idx, section_name, out)
                elif kind == 'county_summary':
                    # section 名 = 设区市 + "各县汇总"
                    section_name = (current_city or '') + '各县汇总'
                    _parse_county_table(tbl, header_idx, section_name, current_city, out)
                elif kind == 'city_supplement':
                    # 优先用 current_section（如"赣州市宁都县常用材料价格汇总表"）避免多级包含丢失
                    if current_section and current_section != (current_city or '') + '补充':
                        section_name = current_section
                    else:
                        section_name = (current_city or '') + '补充'
                    _parse_city_supplement_table(tbl, header_idx, section_name, current_city, out)
                elif kind == 'plant':
                    # 园林苗木表：section 优先用 current_section
                    section_name = current_section or (current_city + '园林苗木')
                    _parse_plant_table(tbl, header_idx, section_name, current_city, out)

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
def _doc_id(period, section, no, breed, spec, city, county=''):
    raw = f'{period}|{section}|{no}|{breed}|{spec}|{city}|{county}'
    return hashlib.md5(raw.encode('utf-8')).hexdigest()


def bulk_index(es, index, docs):
    """幂等写入（按 _id upsert）"""
    if not docs:
        return 0, 0
    body = ''
    for d in docs:
        _id = _doc_id(d['period'], d['section'], d['no'], d['breed'], d['spec'], d.get('city', ''), d.get('region', ''))
        body += json.dumps({'index': {'_index': index, '_id': _id}}, ensure_ascii=False) + '\n'
        body += json.dumps(d, ensure_ascii=False) + '\n'
    resp = es.bulk(body=body, refresh=False)
    if resp.get('errors'):
        errors = sum(1 for it in resp['items'] if 'error' in it.get('index', {}))
        return len(docs) - errors, errors
    return len(docs), 0


# ─── 主流程 ──────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description='江西建设工程材料价格同步')
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

    print(f'[jiangxi] ES: {es_host}')
    print(f'[jiangxi] MinIO: {cfg["minio"]["endpoint"]} / {cfg["minio"]["bucket"]}')
    print(f'[jiangxi] journal_keyword: {cfg.get("journal_keyword", "")}')

    print('[jiangxi] 抓取列表...')
    items = fetch_all_periods(cfg)
    print(f'[jiangxi] 共 {len(items)} 期')

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
        if not it['pdf_url']:
            continue
        if it['id'] in progress['done'] and progress['done'][it['id']].get('status') == 'ok':
            continue
        todo.append(it)

    if args.latest:
        todo = todo[:1]

    print(f'[jiangxi] 待处理 {len(todo)} 期')
    if not todo:
        print('[jiangxi] 无新数据')
        return

    total_written = 0
    for idx, item in enumerate(todo, 1):
        print(f'\n[jiangxi] [{idx}/{len(todo)}] {item["title"]}  ({item["publish_date"]})')
        start = time.time()
        try:
            pdf_url = item['pdf_url']
            print(f'  PDF: {pdf_url}')

            # period 从 title 提取（如"江西省材料价格参考信息2026年第5期"）
            m = re.search(r'(\d{4})年第(\d+)期', item['title'])
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
                        'category': r.get('category', ''),
                        'section': r['section'],
                        'region': r.get('region', ''),
                        'city': r.get('city', ''),
                        'vat_rate': r.get('vat_rate'),
                        'price_kind': '含税',  # PDF 给的是含税价
                        'period': period,
                        'province': '江西',
                        'update_date': item['publish_date'],
                        'create_time': now,
                        'source_pdf': minio_key,
                        'source_url': pdf_url,
                    })

                if args.dry_run:
                    print(f'  [dry-run] 将写 {len(docs)} 条到 {cfg["es"]["ods_index"]}')
                    from collections import Counter
                    cat_counter = Counter(d['category'] for d in docs)
                    city_counter = Counter(d['city'] for d in docs)
                    sec_counter = Counter(d['section'] for d in docs)
                    vat_counter = Counter(d['vat_rate'] for d in docs)
                    print(f'  by section: {dict(sec_counter)}')
                    print(f'  by city (TOP 15): {dict(city_counter.most_common(15))}')
                    print(f'  by category (TOP 10): {dict(cat_counter.most_common(10))}')
                    print(f'  by vat_rate: {dict(vat_counter)}')
                    print('  sample (前 5):')
                    for d in docs[:5]:
                        print(f"    {d['no']:5s} | {d['city']:8s} | {d['section'][:20]:20s} | "
                              f"{d['breed'][:25]:25s} | {d['spec'][:30]:30s} | "
                              f"{d['unit']:6s} = {d['price']:>10}  (税率 {d['vat_rate']})")
                    ok = len(docs)
                    err = 0
                else:
                    ok, err = bulk_index(es, cfg['es']['ods_index'], docs)
                    print(f'  bulk: ok={ok}, err={err}')

                elapsed = time.time() - start
                progress['done'][item['id']] = {
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
            import traceback
            traceback.print_exc()
            progress['done'][item['id']] = {
                'publish_date': item['publish_date'],
                'detail_url': item['detail_url'],
                'status': 'failed',
                'error': str(e),
                'duration_sec': round(elapsed, 1),
            }
            save_progress(progress)

    print(f'\n[jiangxi] 全部完成: total_written={total_written}')


if __name__ == '__main__':
    main()
