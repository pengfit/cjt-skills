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
import tempfile
import logging

# 2026-08-01: 治本验证模块 (兼容增量数据)
from bs4 import BeautifulSoup
import pdfplumber
from urllib.parse import urljoin

# 2026-08-01: 治本验证 logger (兼容增量数据)
log = logging.getLogger(__name__)
if not log.handlers:
    h = logging.StreamHandler()
    h.setFormatter(logging.Formatter('[%(name)s] %(levelname)s %(message)s'))
    log.addHandler(h)
log.setLevel(logging.WARNING)

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

# 2026-08-03: OCR 章节标题污染过滤（治标过渡）
# 5/6 月 PDF 是图片版式，rapidocr 经常把章节标题（"三、装配式建筑部品部件"等）
# 误识别为数据行。下面 4 条规则可显著降低污染率。
# 注意：rule4 (section_fullnames) 需要长名（>=4 字符）避免"玻璃"等短词误伤真数据。
RE_SECTION_NUM = re.compile(r'^[一二三四五六七八九十]{1,3}\s*[、,\s]')
_SECTION_FULL_NAMES = set(SECTION_PATTERNS.values())
_SECTION_LONG_NAMES = {n for n in _SECTION_FULL_NAMES if len(n) >= 4}


def _is_section_pollution(r: dict) -> str:
    """判定 OCR 行是否为章节标题/页眉污染。返回 None=保留；否则返回原因标签。

    规则（任一触发即视为污染）：
      R0 页眉：breed/spec 含 "市场参考价"（页眉表标题）
      R1 无序号：no 字段空（章节标题行 OCR 几乎都不认序号）
      R2 数字前缀：breed/spec 以 "一、""二、""三、"… 开头
      R3 精确等于：breed+spec 拼起来 = 章节名（短名如"钢材"/"玻璃"也命中）
      R4 长名匹配：breed+spec 拼起来属于章节长名子串（>=4 字符，避免"玻璃"误伤）
    """
    breed = (r.get('breed') or '').strip()
    spec = (r.get('spec') or '').strip()
    no = (r.get('no') or '').strip()

    # R0: 页眉
    if '市场参考价' in spec or '市场参考价' in breed:
        return 'R0_header'
    # R1: 序号缺失（强信号）
    if not no:
        return 'R1_no_seq'
    # R2: 数字前缀
    if RE_SECTION_NUM.match(breed) or RE_SECTION_NUM.match(spec):
        return 'R2_section_num'
    # R3: 精确等于章节名
    combined = (breed + spec).strip()
    if combined in _SECTION_FULL_NAMES:
        return 'R3_section_exact'
    # R4: 长名子串（保底，避免"装配式建筑"等被拆分两列仍能识别）
    if combined:
        for sn in _SECTION_LONG_NAMES:
            if combined.startswith(sn) or combined == sn:
                return f'R4_long_name:{sn}'
    return None



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


def _validate_parsed_row(breed, unit, raw_price, table_kind='5col-main'):
    """行级数据校验 - 治本验证 (兼容增量数据)

    2026-08-02: 5-col 分支已 inline 防御数字 breed / 数字 unit，本函数主要用于
    6/7/8/9-col 分支（机具 / 苗木）。当前最小实现：只挡显然坏行（price 不可解析）。
    返回 (ok, reason)。

    Args:
        breed: 品种名（str）
        unit: 单位（str）
        raw_price: 原始价格字符串（str）
        table_kind: 表型 '5col-main' / '6col-mach' / '7col-shrub' / '8col-tree' / '9col-palm'

    Returns:
        (ok: bool, reason: str) - ok=True 表示通过；ok=False 时 reason 是简短原因。
    """
    # 通用检查：原始价格必须能解析为正数
    if raw_price is None or str(raw_price).strip() == '':
        return False, 'empty_raw_price'
    if _parse_price(raw_price) is None:
        return False, f'unparseable_price:{raw_price}'
    # 5/6/7/8/9-col 都不应把数字写到 unit（除了 6-col-mach 可能允许）
    if table_kind != '6col-mach' and unit and _is_price_cell(unit):
        return False, f'unit_is_price:{unit}'
    # breed 不应为纯数字（行号污染）
    if breed and breed.isdigit() and len(breed) <= 4:
        return False, f'breed_is_seq:{breed}'
    return True, ''


def _log_bad_row(reason, row, n_cols, table_kind):
    """记录被 _validate_parsed_row 拒掉的行（2026-08-02 补）

    原调用 _log_bad_row 但函数未定义，导致 6/7/8/9-col 分支 NameError。
    当前最小实现：只写入 parser 模块 logger（WARNING），不抛异常。
    """
    try:
        log.warning('bad_row table_kind=%s n_cols=%d reason=%s row=%r',
                    table_kind, n_cols, reason, row)
    except Exception:
        # 最后保险：连 logger 都炸了就静默吞掉，不阻塞解析
        pass


# ─── OCR fallback（v0.8.3, 2026-08-03）────────────────────────────────────
# 海南 5/6 月期刊改成图片版式（数据行只在图片里、文字层只有表头+说明），
# pdfplumber extract_tables 找不到任何 5 列表，文字路径失效。
# 解决：用 rapidocr（PyMuPDF 渲染 + ONNX 中文识别）逐页 OCR + 按 y-band 分行 +
# 按 x 区间映射到 5 列。text PDF（1~4 月）继续走原路径，零回归。

OCR_X_RANGES = {
    'no':    (0,    80),    # 序号：左缘窄列，纯 1-3 位数字
    'breed': (80,   400),   # 品种：中文为主
    'spec':  (400,  1100),  # 规格：常多行，常带单位词
    'unit':  (1100, 1350),  # 单位：常 1-3 字符（m/t/m²…），易漏识别
    'price': (1350, 9999),  # 价格：最右，含小数
}


def _is_image_heavy_pdf(pdf_path: str) -> bool:
    """检测 PDF 是否是图片版式（数据行不在文字层）。

    双信号判断（任一触发即视为图片 PDF）：
      1) 平均字符密度 < 600 字符/页（text 版 PDF ~1300 字符/页，图片版 ~390 字符/页）
      2) 平均图片密度 > 10 张/页（text 版 0 张，图片版 ~90 张）
    text 版 PDF（4月及更早）任一信号都不会触发；图片版（5月+）必触发至少一个。
    """
    try:
        import fitz
        doc = fitz.open(pdf_path)
        try:
            n = len(doc)
            if n == 0:
                return False
            total_chars = 0
            total_imgs = 0
            for i in range(n):
                page = doc[i]
                total_chars += len(page.get_text() or '')
                total_imgs += len(page.get_images(full=True))
            avg_chars = total_chars / n
            avg_imgs = total_imgs / n
            return avg_chars < 600 or avg_imgs > 10
        finally:
            doc.close()
    except Exception:
        return False


def _ocr_render_page(pdf_path: str, page_index: int, scale: float = 2.0) -> str:
    """用 PyMuPDF 把指定页渲染成 PNG 临时文件,返回路径。"""
    import fitz  # PyMuPDF
    doc = fitz.open(pdf_path)
    try:
        page = doc[page_index]
        pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale))
        fd, path = tempfile.mkstemp(suffix='.png')
        os.close(fd)
        pix.save(path)
        return path
    finally:
        doc.close()


def _ocr_extract_rows(img_path: str) -> list:
    """rapidocr 识别页面图片 → 按 y-band 分行 → 按 x 区间映射到 5 列 → 产出 rows。

    Returns:
        [{'no': str, 'breed': str, 'spec': str, 'unit': str, 'price': float}, ...]
        price 已转为 float；其余字段为字符串（空字符串表示该列 OCR 未识别到）。
    """
    from rapidocr_onnxruntime import RapidOCR
    engine = RapidOCR()
    result = engine(img_path)
    if not result or not result[0]:
        return []

    items = []
    for item in result[0]:
        # 兼容不同版本：(box, text, conf) 或 (box, text)
        if len(item) == 3:
            box, text, conf = item
        else:
            box, text = item[0], item[1]
            conf = 1.0
        try:
            conf = float(conf)
        except Exception:
            conf = 1.0
        if conf < 0.4:
            continue
        x_coords = [pt[0] for pt in box]
        y_coords = [pt[1] for pt in box]
        items.append({
            'x_min': min(x_coords),
            'x_max': max(x_coords),
            'y_center': (min(y_coords) + max(y_coords)) / 2,
            'text': str(text).strip(),
            'conf': conf,
        })
    if not items:
        return []

    # 1. 按 y-band 分行（同 row 中心 y 差 < 15 px）
    items.sort(key=lambda x: (x['y_center'], x['x_min']))
    rows = []
    current = []
    last_y = -1000
    for it in items:
        if it['y_center'] - last_y > 15 and current:
            rows.append(current)
            current = []
        current.append(it)
        last_y = it['y_center']
    if current:
        rows.append(current)

    # 2. 过滤表头/说明行 + 按 x 区间映射到列
    data_rows = []
    for row_blocks in rows:
        all_text = ' '.join(b['text'] for b in row_blocks)
        # 表头（同时含"材料名称"+"规格型号" 或 "除税价"+"区域"）
        if ('材料名称' in all_text and '规格型号' in all_text):
            continue
        if '除税价' in all_text and len(row_blocks) <= 6:
            continue
        # 说明/编制/标准 → 跳过
        if any(kw in all_text for kw in ['执行标准', '说明：', '注：', '编制说明', '除税价']):
            continue

        col = {'no': '', 'breed': '', 'spec': '', 'unit': '', 'price': ''}
        for b in row_blocks:
            x = (b['x_min'] + b['x_max']) / 2
            t = b['text']
            # 价格优先：x > 1350 且为正数
            if x > 1350:
                p = _parse_price(t)
                if p is not None:
                    col['price'] = t
                    continue
            # 序号：x < 80 且为 1-3 位数字
            if x < 80 and re.match(r'^\d{1,3}$', t):
                col['no'] = t
                continue
            # 按 x 区间分配
            if x < 400:
                col['breed'] += (t + ' ')
            elif x < 1100:
                col['spec'] += (t + ' ')
            elif x < 1350:
                col['unit'] += t
            else:
                # 右半边非数字文字 → 归 spec（防漏）
                col['spec'] += (t + ' ')

        col['breed'] = col['breed'].strip()
        col['spec'] = col['spec'].strip()
        col['unit'] = col['unit'].strip()

        price = _parse_price(col['price'])
        if price is None:
            continue
        if not col['breed'] and not col['spec']:
            continue

        col['price'] = price
        data_rows.append(col)

    return data_rows


def _parse_pdf_with_ocr(pdf_path: str) -> list:
    """对整个 PDF 走 OCR 路径,逐页渲染+识别,产出 ODS 格式 rows。

    与 text 版 parse_pdf 返回结构完全一致（多带 period 字段）。
    """
    import fitz

    out = []
    doc = fitz.open(pdf_path)
    try:
        for pi in range(len(doc)):
            page = doc[pi]
            page_text = page.get_text() or ''

            # 跳过目录/说明页
            if '目 录' in page_text[:50] or '编制说明' in page_text[:100]:
                continue

            # category / region
            category = ''
            region = '全省'
            if '主要材料市场参考价' in page_text:
                category = '主要材料'
                for r in REGIONS:
                    if f'{r}区域' in page_text:
                        region = r
                        break
            elif '施工机具' in page_text or '机具' in page_text:
                category = '施工机具与周转材料'
                region = '全省'
            elif '苗木' in page_text:
                category = '园林绿化苗木'
                region = '全省'

            # period（多数页文字层不携带，从 current_period 缓存）
            m_p = RE_PERIOD.search(page_text)
            if m_p:
                current_period = f'{m_p.group(1)}.{int(m_p.group(2))}月'
            if 'current_period' not in locals():
                current_period = ''

            # 章节识别（来自文字层）
            text_lines = page_text.split('\n')
            section_at_line = {}
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

            # 渲染 + OCR
            img_path = _ocr_render_page(pdf_path, pi, scale=2.0)
            try:
                page_rows = _ocr_extract_rows(img_path)
            finally:
                try:
                    os.unlink(img_path)
                except Exception:
                    pass

            # 章节标题污染过滤（治标:图片版 OCR 误识别章节行为数据行）
            filtered_rows = []
            for r in page_rows:
                if _is_section_pollution(r) is None:
                    filtered_rows.append(r)
            page_rows = filtered_rows

            current_section = list(section_at_line.values())[-1] if section_at_line else ''
            for r in page_rows:
                out.append({
                    'no': r['no'],
                    'breed': r['breed'],
                    'spec': r['spec'],
                    'unit': r['unit'],
                    'price': r['price'],
                    'tax_price': round(r['price'] * (1 + VAT_RATE), 2),
                    'remark': '',
                    'region': region,
                    'section': current_section,
                    'category': category,
                    'period': current_period or '',
                })
    finally:
        doc.close()

    # OCR 路径下 period 常空（多数页文字层没周期），用全 PDF 最后一个兜底
    last_period = ''
    for r in out:
        if r['period']:
            last_period = r['period']
    if last_period:
        for r in out:
            if not r['period']:
                r['period'] = last_period

    return out


def parse_pdf(pdf_path):
    """解析 PDF → 长表 [{...}]

    字段：no, breed, spec, unit, price, tax_price, remark,
          region, section, category
    """
    # 2026-08-03: 图片型 PDF（5/6 月期刊）走 OCR fallback
    if _is_image_heavy_pdf(pdf_path):
        log.warning('[parser] image-heavy PDF detected, switching to OCR path: %s', pdf_path)
        return _parse_pdf_with_ocr(pdf_path)

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
                        # 2026-08-02 治本修复：PDF 实际列序可能是
                        #   序号|规格(含材料名)|单位|不含税价|含税价
                        # （没有独立"材料名称"列），导致 row[1] 实际是材料名前缀（数字/空），
                        # row[3] 实际是不含税价（数字）。两处都做防御：
                        # 1) breed 是纯数字 → 清空（不写入行号当品种名，让 L1 从 spec 提）
                        # 2) unit 是数字 → 清空（不写入价格当单位）
                        if breed.isdigit():
                            breed = ''
                        if _is_price_cell(unit):
                            unit = ''
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
                        # 2026-08-01: 治本验证 (兼容增量数据)
                        ok, reason = _validate_parsed_row(breed, unit, raw_price, table_kind='6col-mach')
                        if not ok:
                            _log_bad_row(reason, row, n_cols, '6col-mach')
                            continue
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
                        # 2026-08-01: 治本验证 (兼容增量数据)
                        ok, reason = _validate_parsed_row(breed, unit, raw_price, table_kind='7col-shrub')
                        if not ok:
                            _log_bad_row(reason, row, n_cols, '7col-shrub')
                            continue
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
                        # 2026-08-01: 治本验证 (兼容增量数据)
                        ok, reason = _validate_parsed_row(breed, unit, raw_price, table_kind='8col-tree')
                        if not ok:
                            _log_bad_row(reason, row, n_cols, '8col-tree')
                            continue
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
                        # 2026-08-01: 治本验证 (兼容增量数据)
                        ok, reason = _validate_parsed_row(breed, unit, raw_price, table_kind='9col-palm')
                        if not ok:
                            _log_bad_row(reason, row, n_cols, '9col-palm')
                            continue
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
