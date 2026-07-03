"""海南工程造价信息 - 解析与采集纯函数模块（v0.8, 2026-07-02）

按 chongqing 模式拆分：
- parser.py：本文件，纯函数（列表 / 详情 / PDF 解析 / 幂等写入 / 周期归一化）
- hainan_collector.py：SyncRunner 基类化版本，主流程，调用本文件函数
- sync.py：CLI 入口，薄壳委托 hainan_collector
- preview.py：独立预览工具，从本文件导入函数
- check.py：独立增量检测，从本文件导入函数

业务常识：
- 5 个主要材料区域：北部（海口/澄迈/文昌/定安）/ 南部（三亚/陵水/乐东/保亭/五指山）/
  西部（儋州/临高/昌江/白沙/东方）/ 东部（琼海/万宁）/ 中部（屯昌/琼中）
- 1 个施工机具区域（全省）
- 4 个苗木子类：乔木/灌木/棕榈科/地被类（全省）
- 价格 = 除税价（不含税），tax_price = price × 1.09
- 百分号行（如 "5.00%"）是电线电缆溢价率，不是价格 → 跳过
"""
import hashlib
import json
import os
import re
import sys

from bs4 import BeautifulSoup
import pdfplumber
from urllib.parse import urljoin

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

from utils import fetch_html


VAT_RATE = 0.09   # 建设工程材料增值税率（除税→含税）


# ─── 周期辅助 ────────────────────────────────────────────────────────────────
def compute_period_range(period):
    """从 period（如 '2026.1月' / '2026.12月'）解析 (period_start, period_end, period_days)。

    v0.8 (2026-07-02) 补充：以前 sync.py 不写 period_start/end/days，但
    gov_price_etl.mappings.build_ods_mapping 里这三个字段都是标准字段，
    ES 查询时会作为过滤器/聚合使用。

    Returns:
        (period_start: str 'YYYY-MM-DD', period_end: str 'YYYY-MM-DD', period_days: int)
        period 解析失败时返回 ('', '', 0)。
    """
    m = re.search(r"(\d{4})\.(\d{1,2})", period)
    if not m:
        return "", "", 0
    year, month = int(m.group(1)), int(m.group(2))
    if not (1 <= month <= 12):
        return "", "", 0
    if month in (1, 3, 5, 7, 8, 10, 12):
        last_day = 31
    elif month == 2:
        # 闰年：能被 4 整除且不能被 100 整除，或能被 400 整除
        last_day = 29 if (year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)) else 28
    else:
        last_day = 30
    return (
        f"{year:04d}-{month:02d}-01",
        f"{year:04d}-{month:02d}-{last_day:02d}",
        last_day,
    )


# ─── 列表页解析 ────────────────────────────────────────────────────────────────
def parse_list_page(html, base_url):
    """从列表页 HTML 提取每期信息（li.line_u7_N 结构）"""
    soup = BeautifulSoup(html, 'html.parser')
    items = []
    for li in soup.select('li[id^="line_u7_"]'):
        a = li.select_one('a[href*="/dejgxx/"]')
        if not a:
            continue
        href = a.get('href', '')
        if not re.search(r'/\d{6}/[0-9a-f]{32}\.shtml$', href):
            continue
        title = a.get('title', '') or a.get_text(strip=True)
        # 清理 title：移除首尾日期标记
        title = re.sub(r'\s*\d{4}-\d{2}-\d{2}\s*', '', title).strip()
        # 取日期（span 中的 YYYY-MM-DD）
        date_el = li.select_one('span')
        publish_date = date_el.get_text(strip=True) if date_el else ''
        items.append({
            'title': title,
            'publish_date': publish_date,
            'detail_url': urljoin(base_url, href),
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


def parse_detail_page(html, base_url, detail_url=None):
    """从详情页提取 PDF 链接 + 标题

    base_url: 站点根 URL（用于构造 PDF URL）
    detail_url: 详情页 URL（PDF 相对路径的基准）
    """
    soup = BeautifulSoup(html, 'html.parser')
    # 找带 .pdf 的链接
    pdf_a = soup.select_one('a[href$=".pdf"]')
    pdf_href = pdf_a.get('href', '') if pdf_a else ''
    # PDF 相对路径是相对详情页的，所以用 detail_url 作为基准
    pdf_base = detail_url or base_url
    pdf_url = urljoin(pdf_base, pdf_href) if pdf_href else ''
    pdf_name = pdf_a.get_text(strip=True) if pdf_a else ''
    return {'pdf_url': pdf_url, 'pdf_name': pdf_name}


def extract_period_from_title(title):
    """从标题提取周期 '2026年1月' → '2026.1月'"""
    m = re.search(r'(\d{4})年(\d{1,2})月', title)
    if not m:
        return ''
    return f'{m.group(1)}.{int(m.group(2))}月'


# ─── PDF 解析 ────────────────────────────────────────────────────────────────
# 章节识别（PDF 内部"一、二、..."一级分类）
SECTION_PATTERNS = {
    '一、钢材': '钢材',
    '二、水泥、砂石、墙体材料和预制桩': '水泥、砂石、墙体材料和预制桩',
    '三、装配式建筑部品部件': '装配式建筑部品部件',
    '四、水泥混凝土和砂浆': '水泥混凝土和砂浆',
    '五、木材': '木材',
    '五 、 木材': '木材',
    '六、玻璃': '玻璃',
    '六 、 玻璃': '玻璃',
    '七、铝合金门窗和铝合金型材': '铝合金门窗和铝合金型材',
    '七 、 铝合金门窗和铝合金型材': '铝合金门窗和铝合金型材',
    '八、防水材料': '防水材料',
    '八 、 防水材料': '防水材料',
    '九、电线电缆': '电线电缆',
    '九 、 电线电缆': '电线电缆',
    '十、塑料管材': '塑料管材',
    '十 、 塑料管材': '塑料管材',
    '十一、保温隔热材料': '保温隔热材料',
    '十一 、 保温隔热材料': '保温隔热材料',
    '十二、沥青和沥青混凝土': '沥青和沥青混凝土',
    '十二 、 沥青和沥青混凝土': '沥青和沥青混凝土',
    '十三、油品': '油品',
    '十三 、 油品': '油品',
}

REGIONS = ['北部', '南部', '西部', '东部', '中部']

# PDF 章节标题前缀识别
RE_SECTION = re.compile(r'^\s*([一二三四五六七八九十]+)\s*[、,]\s*(\S[^.。\n]{1,30})')
RE_PERIOD = re.compile(r'(\d{4})\s*年\s*(\d{1,2})\s*月')


def _is_price_cell(s):
    """判断是否是数字价格（排除百分号、说明文字等）"""
    if s is None:
        return False
    s = str(s).strip()
    if not s:
        return False
    if '%' in s:
        return False
    # 去除货币符号、空格、逗号
    s_clean = s.replace('￥', '').replace('¥', '').replace(',', '').replace(' ', '')
    try:
        v = float(s_clean)
        return v > 0
    except ValueError:
        return False


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


def _is_data_row(row, n_cols):
    """判断一行是否是有效数据行（不是表头/说明/空）"""
    if not row or len(row) < n_cols:
        return False
    # 序号列必须是数字
    seq = str(row[0] or '').strip()
    if not seq or not seq.isdigit():
        return False
    return True


def _find_header_row(tbl):
    """在表前 5 行中找带'除税价'的表头行"""
    for i, row in enumerate(tbl[:5]):
        cells = ' '.join(str(c or '') for c in row)
        if '除税价' in cells:
            return i
    return None


def _find_section_for_row(seq, text_lines, section_at_line, default):
    """给定数据行的序号，在 page text 中定位'该序号'所在行，
    返回该行之前最近的章节名（用于一表中多章节的情况）。"""
    if not section_at_line or not text_lines or not seq:
        return default
    seq_str = str(seq).strip()
    # 在 text 中找以 "seq " 或 "seq\t" 开头的行
    target_line_idx = None
    for li, line in enumerate(text_lines):
        s = line.lstrip()
        if s == seq_str or s.startswith(seq_str + ' ') or s.startswith(seq_str + '\t'):
            target_line_idx = li
            break
    if target_line_idx is None:
        return default
    # 找 < target_line_idx 的最大 section_at_line 键
    candidates = [li for li in section_at_line if li < target_line_idx]
    if not candidates:
        return default
    return section_at_line[max(candidates)]


def parse_pdf(pdf_path):
    """解析 PDF → 长表 [{...}]

    字段：no, breed, spec, unit, price, tax_price, remark,
          region, section, category
    """
    out = []
    current_period = None
    current_region = None
    current_category = None
    current_section = None
    last_no = None       # 苗木表"继承"序号
    last_breed = None    # 苗木表"继承"名称

    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ''
            if not text:
                continue

            # 0. 跳过目录/说明页
            stripped = text.strip()
            if stripped.startswith('目 录') or '编制说明' in text[:100] or '目  录' in text[:50]:
                continue

            # 1. 提取周期
            m_p = RE_PERIOD.search(text)
            if m_p:
                current_period = f'{m_p.group(1)}.{int(m_p.group(2))}月'

            # 2. 识别 category 和 region
            if '主要材料市场参考价' in text:
                current_category = '主要材料'
                # 识别区域（页眉）
                for r in REGIONS:
                    if f'{r}区域' in text:
                        current_region = r
                        break
            elif '施工机具与周转材料租赁市场参考价' in text:
                current_category = '施工机具与周转材料'
                current_region = '全省'
            elif '园林绿化苗木市场参考价' in text:
                current_category = '园林绿化苗木'
                current_region = '全省'
                m = re.search(r'（(乔木|灌木|棕榈科植物|地被类植物)）', text)
                if m:
                    sec = m.group(1)
                    current_section = {'乔木': '苗木-乔木', '灌木': '苗木-灌木',
                                       '棕榈科植物': '苗木-棕榈科', '地被类植物': '苗木-地被类'}.get(sec, sec)

            # 3. 识别一级章节（一、钢材 / 二、水泥...）
            # 按 (行号, 章节名) 列表保存，用于表格数据行的章节归属
            text_lines = text.split('\n')
            section_at_line = {}   # line_idx -> section_name
            for li, line in enumerate(text_lines):
                m = re.match(r'^\s*([一二三四五六七八九十]+)\s*[、,]\s*(\S.+?)$', line)
                if m:
                    sec_name = m.group(2).strip()
                    sec_name = re.sub(r'\s+', '', sec_name)
                    matched = None
                    for key, val in SECTION_PATTERNS.items():
                        if key.replace(' ', '').replace('、', '').startswith(sec_name[:4]) or sec_name.startswith(val[:4]):
                            matched = val
                            break
                    if not matched and 2 <= len(sec_name) <= 20:
                        matched = sec_name
                    if matched:
                        section_at_line[li] = matched
            # 更新 current_section 为本页最后一个章节（后续表格兜底用）
            if section_at_line:
                current_section = list(section_at_line.values())[-1]

            # 4. 解析表格
            tables = page.extract_tables() or []
            for tbl in tables:
                if not tbl or len(tbl) < 2:
                    continue
                n_cols = len(tbl[0]) if tbl[0] else 0
                if n_cols < 5:
                    continue
                if n_cols == 1:
                    continue

                # 找表头行
                header_idx = _find_header_row(tbl)
                # 兜底：没找到表头但第一行第一列是数字 + 列数 5/6/7/8/9 → 当数据表
                if header_idx is None:
                    first_seq = str(tbl[0][0] or '').strip() if tbl[0] else ''
                    if first_seq.isdigit() and n_cols in (5, 6, 7, 8, 9):
                        header_idx = -1
                        data_start = 0
                    else:
                        continue

                if header_idx >= 0:
                    # 跳过表头行（可能 1-2 行表头）
                    data_start = header_idx + 1
                    if data_start < len(tbl) and all(c is None or str(c).strip() == '' for c in tbl[data_start]):
                        data_start += 1
                    # 苗木表第二行表头（如"胸 径(cm) / 自然高度(m) / ..."，首列为 None）也要跳过
                    if data_start < len(tbl):
                        row = tbl[data_start]
                        if row and (row[0] is None or not str(row[0]).strip().isdigit()):
                            nones = sum(1 for c in row if c is None or str(c).strip() == '')
                            # 多个空 + 首列不是数字 → 当作二级表头
                            if nones >= 2:
                                data_start += 1
                # else: data_start 已经在上面设了 0

                for row in tbl[data_start:]:
                    if not row or len(row) < n_cols:
                        continue
                    # 跳过空行
                    if all(c is None or str(c).strip() == '' for c in row):
                        continue

                    seq = str(row[0] or '').strip()
                    # 按"该序号在 text 中的位置"定 section（处理同页多章节）
                    row_section = _find_section_for_row(seq, text_lines, section_at_line, current_section)
                    # 苗木分类下加'苗木-'前缀以区分主要材料的同名章节
                    if current_category == '园林绿化苗木' and row_section:
                        # 规范化名字：去除"植物"后缀
                        norm = row_section.rstrip('植物')
                        if not norm.startswith('苗木-'):
                            row_section = f'苗木-{norm}'

                    # ── 5列：主要材料主表 ──
                    if n_cols == 5:
                        # 序号 | 材料名称 | 规格型号 | 单位 | 除税价
                        breed, spec, unit, raw_price = row[1], row[2], row[3], row[4]
                        breed = str(breed or '').strip()
                        spec = str(spec or '').strip()
                        unit = str(unit or '').strip()
                        price = _parse_price(raw_price)
                        if price is None:
                            # 百分号行/无效行 → 跳过
                            if seq and breed:
                                pass  # 调试： print(f'skip 5col: {seq} {breed} {raw_price}')
                            continue
                        last_no, last_breed = seq, breed
                        out.append({
                            'no': seq,
                            'breed': breed,
                            'spec': spec,
                            'unit': unit,
                            'price': price,
                            'tax_price': round(price * (1 + VAT_RATE), 2),
                            'remark': '',
                            'region': current_region or '全省',
                            'section': row_section or current_section or '',
                            'category': current_category or '',
                            'period': current_period or '',
                        })

                    # ── 6列：机具表 / 苗木-地被类 ──
                    elif n_cols == 6:
                        # 两种结构：
                        # (A) 机具: 序号|名称|规格型号|除税价|单位|备注
                        # (B) 地被: 序号|名称|株高|蓬径|单位|除税价
                        c1, c2, c3, c4, c5, c6 = [str(c or '').strip() for c in row[:6]]
                        # 判断：看 c3（第三列）是数字还是说明文字
                        # 机具 c3=规格型号, c4=除税价（数字）, c5=单位
                        # 地被 c3=株高, c4=蓬径, c5=单位, c6=除税价
                        if _is_price_cell(c4) and not _is_price_cell(c6):
                            # 机具：c4 是价格
                            breed, spec, raw_price, unit, remark = c1, c2, c4, c5, c6
                        elif _is_price_cell(c6) and not _is_price_cell(c4):
                            # 地被：c6 是价格
                            breed, spec1, spec2, unit, raw_price = c1, c2, c3, c5, c6
                            spec = f'{spec1} × {spec2}' if spec1 and spec2 else (spec1 or spec2)
                            remark = ''
                        else:
                            # 默认按机具处理
                            breed, spec, raw_price, unit, remark = c1, c2, c4, c5, c6

                        price = _parse_price(raw_price)
                        if price is None:
                            continue
                        # 苗木有"继承"逻辑
                        if not breed and last_breed:
                            breed = last_breed
                            seq = last_no or seq
                        else:
                            last_no, last_breed = seq, breed
                        out.append({
                            'no': seq,
                            'breed': breed,
                            'spec': spec,
                            'unit': unit,
                            'price': price,
                            'tax_price': round(price * (1 + VAT_RATE), 2),
                            'remark': remark,
                            'region': current_region or '全省',
                            'section': row_section or current_section or ('机具租赁' if current_category == '施工机具与周转材料' else ''),
                            'category': current_category or '',
                            'period': current_period or '',
                        })

                    # ── 7列：苗木-灌木 ──
                    elif n_cols == 7:
                        # 序号|名称|自然高度|冠幅|袋规格|单位|除税价
                        breed, c1, c2, c3, unit, raw_price = [str(c or '').strip() for c in row[1:7]]
                        spec_parts = [c1, c2, c3]
                        spec = ' × '.join([p for p in spec_parts if p])
                        price = _parse_price(raw_price)
                        if price is None:
                            continue
                        if not breed and last_breed:
                            breed = last_breed
                            seq = last_no or seq
                        else:
                            last_no, last_breed = seq, breed
                        out.append({
                            'no': seq,
                            'breed': breed,
                            'spec': spec,
                            'unit': unit,
                            'price': price,
                            'tax_price': round(price * (1 + VAT_RATE), 2),
                            'remark': '',
                            'region': current_region or '全省',
                            'section': row_section or current_section or '苗木-灌木',
                            'category': current_category or '园林绿化苗木',
                            'period': current_period or '',
                        })

                    # ── 8列：苗木-乔木/灌木 ──
                    elif n_cols == 8:
                        # 序号|名称|胸径|自然高度|冠幅|土球直径|单位|除税价
                        breed, c1, c2, c3, c4, unit, raw_price = [str(c or '').strip() for c in row[1:8]]
                        spec_parts = [c1, c2, c3, c4]
                        spec = ' × '.join([p for p in spec_parts if p])
                        price = _parse_price(raw_price)
                        if price is None:
                            continue
                        if not breed and last_breed:
                            breed = last_breed
                            seq = last_no or seq
                        else:
                            last_no, last_breed = seq, breed
                        out.append({
                            'no': seq,
                            'breed': breed,
                            'spec': spec,
                            'unit': unit,
                            'price': price,
                            'tax_price': round(price * (1 + VAT_RATE), 2),
                            'remark': '',
                            'region': current_region or '全省',
                            'section': row_section or current_section or '苗木-乔木',
                            'category': current_category or '园林绿化苗木',
                            'period': current_period or '',
                        })

                    # ── 9列：苗木-棕榈科 ──
                    elif n_cols == 9:
                        # 序号|名称|胸径/地径|自然高度|净杆高|尾径|土球直径|单位|除税价
                        breed, c1, c2, c3, c4, c5, unit, raw_price = [str(c or '').strip() for c in row[1:9]]
                        spec_parts = [c1, c2, c3, c4, c5]
                        spec = ' × '.join([p for p in spec_parts if p])
                        price = _parse_price(raw_price)
                        if price is None:
                            continue
                        if not breed and last_breed:
                            breed = last_breed
                            seq = last_no or seq
                        else:
                            last_no, last_breed = seq, breed
                        out.append({
                            'no': seq,
                            'breed': breed,
                            'spec': spec,
                            'unit': unit,
                            'price': price,
                            'tax_price': round(price * (1 + VAT_RATE), 2),
                            'remark': '',
                            'region': current_region or '全省',
                            'section': row_section or current_section or '苗木-棕榈科',
                            'category': current_category or '园林绿化苗木',
                            'period': current_period or '',
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


# ─── 入库 ────────────────────────────────────────────────────────────────
def _doc_id(period, region, section, no, breed, spec):
    raw = f'{period}|{region}|{section}|{no}|{breed}|{spec}'
    return hashlib.md5(raw.encode('utf-8')).hexdigest()


def bulk_index(es, index, docs):
    """幂等写入（按 _id upsert）"""
    if not docs:
        return 0, 0
    body = ''
    for d in docs:
        _id = _doc_id(d['period'], d['region'], d['section'], d['no'], d['breed'], d['spec'])
        body += json.dumps({'index': {'_index': index, '_id': _id}}, ensure_ascii=False) + '\n'
        body += json.dumps(d, ensure_ascii=False) + '\n'
    resp = es.bulk(body=body, refresh=False)
    if resp.get('errors'):
        errors = sum(1 for it in resp['items'] if 'error' in it.get('index', {}))
        return len(docs) - errors, errors
    return len(docs), 0


# ─── 主流程 ────────────────────────────────────────────────────────────────
