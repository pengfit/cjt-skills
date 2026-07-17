"""山西工程造价信息 - 同步入口（v1.1.1, 2026-07-17）

源站: https://zjt.shanxi.gov.cn/fwzl/bzdexx/jgxx/
结构：HTML 静态列表页（无 AJAX），分页 index.shtml / index_2.shtml ... index_N.shtml
列表项：<li><p><a class="text_p" href='./YYYYMM/tYYYYMMDD_ID.shtml' title='...'>...</a></p>
       <a class="text_span" ...><span>YYYY-MM-DD</span></a></li>
详情页：<a href="./P020YYMMDD...pdf" OLDSRC="/protect/P020YYMM/P020YYMMDD/P020YYMMDD...pdf" download="...">

v1.1.1 PDF 解析：
  - PDF 原生是横版, 扫描存为竖版 → 旋转 90° CW 才正确
  - 旋转后标准宽表: header 行 (序号|材料名称|规格型号|单位|11市) + data 行
  - 部分 data 行无 序号 (材料名继承上一行)
"""
import argparse
import calendar
import json
import os
import re
import sys
import tempfile
from datetime import datetime, timezone, timedelta
from urllib.parse import urljoin, quote

import pdfplumber

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

from utils import (
    load_config, get_es_client, get_s3_client,
    ensure_bucket, ensure_ods_index, ensure_progress_index,
    fetch_html, download_file, upload_to_minio, get_headers,
)

PROGRESS_FILE = os.path.join(
    os.path.dirname(SCRIPT_DIR), '.shanxi_sync_progress.json',
)

CST_TZ = timezone(timedelta(hours=8))
PROVINCE = '山西'

# 列表项正则
_RE_LIST_ITEM = re.compile(
    r"<li>\s*"
    r"<p><a[^>]+class=\"text_p\"[^>]+href=['\"](?P<href>[^'\"]+)['\"][^>]*title=['\"](?P<title>[^'\"]+)['\"]",
    re.S,
)
_RE_DATE_SPAN = re.compile(
    r"<a[^>]+class=\"text_span\"[^>]*>\s*<span>\s*(?P<date>\d{4}-\d{2}-\d{2})\s*</span>",
    re.S,
)
_RE_COUNT_PAGE = re.compile(r"var\s+countPage\s*=\s*(\d+)\s*;")
_RE_DATA_COUNT = re.compile(r'parseInt\(["\'](?P<n>\d+)["\']\)')
_RE_PDF_OLD = re.compile(
    r"<a[^>]+OLDSRC=['\"](?P<oldsrc>/protect/P[^'\"]+\.pdf)['\"]",
    re.S,
)
_RE_PDF_HREF = re.compile(
    r"<a[^>]+href=['\"](?P<href>\./P[^'\"]+\.pdf)['\"]",
    re.S,
)
_RE_PDF_NAME = re.compile(
    r"download=['\"](?P<name>[^'\"]+\.pdf)['\"]",
    re.S,
)


# ─── 工具函数 ─────────────────────────────────────────────────────────

def page_url(base_url: str, list_path: str, page_index: int) -> str:
    if page_index == 0:
        return urljoin(base_url, list_path + 'index.shtml')
    return urljoin(base_url, list_path + f'index_{page_index}.shtml')


def detect_total_pages(html: str, fallback: int = 9) -> int:
    m = _RE_COUNT_PAGE.search(html)
    if m:
        try:
            return int(m.group(1))
        except ValueError:
            pass
    return fallback


def parse_list_page(html: str) -> list[dict]:
    items = []
    for li_match in re.finditer(r"<li>(?P<li>.*?)</li>", html, re.S):
        li = li_match.group('li')
        m_p = re.search(
            r"<a[^>]+class=\"text_p\"[^>]+href=['\"](?P<href>[^'\"]+)['\"]"
            r"[^>]*title=['\"](?P<title>[^'\"]+)['\"]",
            li, re.S,
        )
        if not m_p:
            continue
        m_d = re.search(
            r"<span>\s*(?P<date>\d{4}-\d{2}-\d{2})\s*</span>",
            li, re.S,
        )
        if not m_d:
            continue
        items.append({
            'title': m_p.group('title').strip(),
            'detail_path': m_p.group('href').strip(),
            'date': m_d.group('date').strip(),
        })
    return items


def parse_detail_page(html: str, detail_url: str) -> dict:
    m_href = _RE_PDF_HREF.search(html)
    m_old = _RE_PDF_OLD.search(html)
    m_name = _RE_PDF_NAME.search(html)

    if m_href:
        pdf_url = urljoin(detail_url, m_href.group('href'))
        source = 'href'
    elif m_old:
        pdf_url = urljoin(detail_url, m_old.group('oldsrc'))
        source = 'oldsrc'
    else:
        return {'pdf_url': '', 'pdf_name': '', 'source': ''}

    pdf_name = m_name.group('name') if m_name else pdf_url.rsplit('/', 1)[-1]
    return {'pdf_url': pdf_url, 'pdf_name': pdf_name, 'source': source}


def parse_period_from_title(title: str) -> dict:
    m = re.search(r"(\d{4})\s*年\s*(\d{1,2})\s*[-~]\s*(\d{1,2})\s*月", title or '')
    if not m:
        return {'period': '', 'invalid': True}
    year = int(m.group(1))
    start_m = int(m.group(2))
    end_m = int(m.group(3))
    if not (1 <= start_m <= 12 and 1 <= end_m <= 12 and start_m <= end_m):
        return {'period': '', 'year': year, 'invalid': True}
    last_day = calendar.monthrange(year, end_m)[1]
    period_start = f'{year:04d}-{start_m:02d}-01'
    period_end = f'{year:04d}-{end_m:02d}-{last_day:02d}'
    days = sum(calendar.monthrange(year, mm)[1] for mm in range(start_m, end_m + 1))
    return {
        'period': f'{year}.{start_m}-{end_m}月',
        'period_start': period_start,
        'period_end': period_end,
        'period_days': days,
        'year': year,
        'start_m': start_m,
        'end_m': end_m,
        'invalid': False,
    }


def should_include(item: dict, cfg: dict) -> tuple[bool, str]:
    title = item.get('title', '')
    sync = cfg.get('sync', {})

    target_year = sync.get('default_year', 0)
    if target_year and f'{target_year}' not in title:
        return False, f'年份不匹配 (target={target_year})'

    include_kws = sync.get('include_keywords', ['常用建设工程材料价格信息'])
    if not any(kw in title for kw in include_kws):
        return False, '标题未命中包含关键词'

    exclude_kws = sync.get('exclude_keywords', ['勘误'])
    for kw in exclude_kws:
        if kw in title:
            return False, f'命中排除关键词: {kw}'

    return True, 'OK'


# ─── 抓取主流程 ─────────────────────────────────────────────────────

def fetch_all_items(cfg: dict) -> list[dict]:
    site = cfg['site']
    base = site['base_url'] + site['list_path']

    first_html = fetch_html(page_url(site['base_url'], site['list_path'], 0),
                            headers=get_headers(cfg), timeout=site['timeout_sec'])
    total_pages = detect_total_pages(first_html, fallback=site.get('max_pages', 9))
    print(f'[sync] 检测到 {total_pages} 页 (首页 JS 解析)')

    all_items = []
    for p in range(total_pages):
        if p == 0:
            html = first_html
        else:
            html = fetch_html(page_url(site['base_url'], site['list_path'], p),
                              headers=get_headers(cfg), timeout=site['timeout_sec'])
        page_items = parse_list_page(html)
        print(f'[sync] 第 {p+1}/{total_pages} 页: {len(page_items)} 条')
        for it in page_items:
            it['page'] = p
            it['detail_url'] = urljoin(base, it['detail_path'])
        all_items.extend(page_items)

    print(f'[sync] 列表总数: {len(all_items)}')
    return all_items


def fetch_all_periods(cfg: dict) -> list[dict]:
    raw = fetch_all_items(cfg)
    return [
        {
            'title': it['title'],
            'publish_date': it['date'],
            'detail_url': it['detail_url'],
            'page': it['page'],
        }
        for it in raw
    ]


# ─── PDF OCR 解析（v1.1.1 旋转版）────────────────────────────────────

def parse_pdf_tables(pdf_path: str, max_pages: int = 200) -> list[dict]:
    """山西 PDF 主解析（v1.1.1）：旋转 90° CW 后标准宽表行级抽取.

    旋转后 layout:
        header: 序号 | 材料名称 | 规格型号 | 单位 | 太原市 | ... | 吕梁市
        data:   36  | 角钢    | 边宽110mm|    | 3340.77 | ... | 3491.41
    无 序号的行: 材料名继承上一行.
    """
    try:
        import numpy as np
        from pdf2image import convert_from_path
        from rapidocr_onnxruntime import RapidOCR
    except ImportError as e:
        print(f'[sync] OCR 依赖不可用 ({e}), 回退 legacy')
        return _parse_pdf_tables_legacy(pdf_path, max_pages=max_pages)

    # 旋转后横向 header 顺序
    CITIES = [
        '太原市', '大同市', '阳泉市', '长治市', '晋城市',
        '朔州市', '晋中市', '运城市', '临汾市', '吕梁市', '忻州市',
    ]
    CITY_SET = set(CITIES)

    rows: list[dict] = []
    try:
        pages = convert_from_path(pdf_path, dpi=200, first_page=1, last_page=max_pages)
    except Exception as e:
        print(f'[sync] pdf2image 失败: {e}')
        return _parse_pdf_tables_legacy(pdf_path, max_pages=max_pages)

    engine = RapidOCR()
    from concurrent.futures import ThreadPoolExecutor, TimeoutError as _FutTimeout
    _PAGE_TIMEOUT = 60
    _executor = ThreadPoolExecutor(max_workers=1)

    for pi, pil_img in enumerate(pages, 1):
        # 旋转 90° CW（PDF 原生是横版, 扫描存为竖版）
        arr = np.array(pil_img).transpose(1, 0, 2)[:, ::-1, :]
        try:
            _future = _executor.submit(engine, arr)
            try:
                result, _ = _future.result(timeout=_PAGE_TIMEOUT)
            except _FutTimeout:
                print(f'[sync] P{pi} OCR 超时, 跳过该页')
                continue
        except Exception as e:
            print(f'[sync] P{pi} OCR 失败: {e}')
            continue
        if not result:
            continue

        page_rows = _parse_rotated_page(result, CITIES, CITY_SET, pi)

        # 第 2 OCR 路径: 原始方向, 只抽「材料名称」行 + 「单位」行
        # 原文里「单位」行 y≈1309、「材料名称」行 y≈1817、按 x 位置列对列对应
        # 按 x 位置配对 → breed→unit 映射表, 补齐 OCR 漏抓的 unit
        arr_orig = np.array(pil_img)
        try:
            _future2 = _executor.submit(engine, arr_orig)
            try:
                result_orig, _ = _future2.result(timeout=_PAGE_TIMEOUT)
            except _FutTimeout:
                print(f'[sync] P{pi} 原图 OCR 超时, 跳过 unit 映射')
                result_orig = None
        except Exception as e:
            print(f'[sync] P{pi} 原图 OCR 失败: {e}')
            result_orig = None

        if result_orig:
            unit_map = _extract_unit_map_original(result_orig)
            if unit_map:
                # 补齐数据行里 unit 为空的项
                hits = 0
                for r in page_rows:
                    if not r['unit'] and r['breed'] in unit_map:
                        r['unit'] = unit_map[r['breed']]
                        hits += 1
                print(f'[sync] P{pi} unit_map 命中 {hits}/{len(page_rows)} 行 (表 {len(unit_map)} 映射)')
            else:
                print(f'[sync] P{pi} unit_map 空（原文件「单位」行未识别出）')

        rows.extend(page_rows)

    # ── 按列 outlier 检测 (同 material×spec×unit 的 11 城市中位数裁剪) ──
    from collections import defaultdict
    grouped: dict[tuple, list[dict]] = defaultdict(list)
    for r in rows:
        key = (r['page'], r['breed'], r['spec'], r['unit'])
        grouped[key].append(r)
    cleaned: list[dict] = []
    for key, group in grouped.items():
        prices = sorted(r['price'] for r in group)
        if len(prices) >= 4:
            med = prices[len(prices) // 2]
            lo, hi = med * 0.05, med * 20.0
            kept = [r for r in group if lo <= r['price'] <= hi]
        else:
            kept = group
        cleaned.extend(kept)
    print(f'[sync] OCR 解析: {len(cleaned)} 行 (原始 {len(rows)} → outlier 裁后 {len(cleaned)})')
    return cleaned


def _parse_rotated_page(ocr_result, cities, city_set, page_no):
    """单页行级抽取（旋转后 layout）."""
    if not ocr_result:
        return []

    all_boxes = sorted(ocr_result, key=lambda b: (int(b[0][0][1]), int(b[0][0][0])))

    # 按 y 容差 15 分行, 保留 y_top
    lines: list = []
    cur: list = []
    cur_y_top = None
    last_y = -9999
    for box, text, conf in all_boxes:
        x = int(box[0][0]); y = int(box[0][1])
        if cur_y_top is None:
            cur_y_top = y
        if abs(y - last_y) <= 15:
            cur.append((x, text))
            last_y = max(last_y, y)
        else:
            if cur:
                cur.sort()
                lines.append((cur_y_top, last_y, cur))
            cur = [(x, text)]
            cur_y_top = y
            last_y = y
    if cur:
        cur.sort()
        lines.append((cur_y_top, last_y, cur))

    if len(lines) < 3:
        return []

    # 找 header 行 (≥3 城市名)
    header_idx = None
    for i, (_y0, _y1, items) in enumerate(lines):
        cities_in = sum(1 for _x, t in items if t in city_set)
        if cities_in >= 3:
            header_idx = i
            break
    if header_idx is None:
        return []

    header_items = lines[header_idx][2]
    col_x = {'breed': None, 'spec': None, 'unit': None}
    city_x: list = []
    for x, t in header_items:
        if t == '材料名称':
            col_x['breed'] = x
        elif t == '规格型号':
            col_x['spec'] = x
        elif t == '单位':
            col_x['unit'] = x
        elif t in city_set:
            city_x.append((x, t))

    # 备选: 列名在 header 下一行
    if col_x['breed'] is None:
        for i in range(header_idx + 1, len(lines)):
            for x, t in lines[i][2]:
                if t == '材料名称' and col_x['breed'] is None:
                    col_x['breed'] = x
                if t == '规格型号' and col_x['spec'] is None:
                    col_x['spec'] = x
                if t == '单位' and col_x['unit'] is None:
                    col_x['unit'] = x

    city_x.sort()
    if len(city_x) < 5:
        return []

    # 遍历 header 之后的数据行
    rows = []
    prev_breed = ''
    for i in range(header_idx + 1, len(lines)):
        _y0, _y1, items = lines[i]
        if not items:
            continue

        breed = _nearest_in_row(items, col_x['breed'], tol=30) if col_x['breed'] else ''
        spec = _nearest_in_row(items, col_x['spec'], tol=30) if col_x['spec'] else ''
        unit = _nearest_in_row(items, col_x['unit'], tol=30) if col_x['unit'] else ''
        unit = _clean_unit(unit, breed)

        prices: dict = {}
        for cx, cname in city_x:
            p = _nearest_price_in_row(items, cx, tol=30)
            if p is not None:
                prices[cname] = p

        # 页脚 / 装饰行
        if not breed and not prices:
            if len(items) == 1 and re.match(r'-\d+-$', items[0][1]):
                break
            continue
        if _is_junk_breed(breed):
            continue
        if not spec:
            continue

        # 材料名继承
        if not breed:
            breed = prev_breed
        else:
            prev_breed = breed

        for city, price in prices.items():
            rows.append({
                'breed': breed.strip(),
                'spec': spec.strip(),
                'unit': unit.strip(),
                'price': price,
                'city': city,
                'remark': '',
                'page': page_no,
            })

    return rows


def _extract_unit_map_original(ocr_result):
    """原始方向 OCR 里, 抽「材料名称」行 + 「单位」行, 按 x 位置配对.

    原文 layout:
      y ≈ 1309: 单位     [x_1] unit_1 [x_2] unit_2 ...
      y ≈ 1472: 规格型号
      y ≈ 1817: 材料名称 [x_1] breed_1 [x_2] breed_2 ...

    Returns: {breed: unit} dict
    """
    if not ocr_result:
        return {}

    all_boxes = sorted(ocr_result, key=lambda b: (int(b[0][0][1]), int(b[0][0][0])))

    # 按 y 分行
    lines: list = []
    cur: list = []
    last_y = -9999
    for box, text, conf in all_boxes:
        x = int(box[0][0]); y = int(box[0][1])
        if abs(y - last_y) <= 15:
            cur.append((x, text))
        else:
            if cur:
                cur.sort()
                lines.append(cur)
            cur = [(x, text)]
        last_y = y
    if cur:
        cur.sort()
        lines.append(cur)

    breed_line = None
    unit_line = None
    for items in lines:
        if not items:
            continue
        first_x, first_text = items[0]
        if first_x < 250 and first_text == '材料名称':
            breed_line = items[1:]
        elif first_x < 250 and first_text == '单位':
            unit_line = items[1:]

    if not breed_line or not unit_line:
        return {}

    # 按 x 位置配对: 每个 breed 找最近 unit（容差 60px）
    unit_map: dict[str, str] = {}
    for bx, breed in breed_line:
        if not breed or len(breed) < 2:
            continue
        if _is_junk_breed(breed):
            continue
        # 找最近的 unit
        cands = sorted(unit_line, key=lambda u: abs(u[0] - bx))
        if not cands:
            continue
        cx, raw_unit = cands[0]
        if abs(cx - bx) > 60:
            continue
        cleaned = _clean_unit(raw_unit, breed)
        if cleaned:
            unit_map[breed] = cleaned

    return unit_map


def _nearest_in_row(items, bx, tol: int = 30) -> str:
    """items = [(x, text), ...] 找 x ∈ [bx-tol, bx+tol] 最近的文本."""
    if bx is None or not items:
        return ''
    cands = [(abs(x - bx), x, t) for x, t in items if abs(x - bx) <= tol]
    if not cands:
        return ''
    cands.sort()
    parts = []
    used_x = set()
    for _, x, t in cands:
        if any(abs(x - ux) < 5 for ux in used_x):
            continue
        parts.append(t)
        used_x.add(x)
    return ''.join(parts)


def _nearest_price_in_row(items, bx, tol: int = 30):
    """items = [(x, text), ...] 找 x ∈ [bx-tol, bx+tol] 最近的合法价格."""
    if bx is None or not items:
        return None
    cands = []
    for x, t in items:
        if abs(x - bx) > tol:
            continue
        v = _clean_number(t)
        if v is not None and v > 0:
            cands.append((abs(x - bx), v))
    if not cands:
        return None
    cands.sort()
    return cands[0][1]


# ─── OCR 数字清洗 + 材料名过滤 ─────────────────────────────────────

_OCR_NUM_FIXES = [
    ("'", '.'),
    (' ', ''),
    ('Q', '0'), ('O', '0'), ('I', '1'), ('l', '1'),
    ('S', '5'), ('B', '8'), ('N', ''),
    ('X', ''), ('Y', ''), ('Z', ''),
]

# 材料名 → 单位 推断表（OCR 抓不到单位时 fallback）
# 顺序重要：先精确后模糊，避免“混凝土”被“土”误匹配
_UNIT_INFERENCE = [
    # 钢材类 → t
    (['钢', '型钢', '角钢', '钢板', '钢管', '钢筋', '钢丝', '钢绞线', '盘条', '罗纹', '薄板', '厚板', '钢铸', '镀锌', '花纹', '钢圈', '锡钢片', '钢护口', '锡钢板', '铬钢板', '锣钢板', '钢'], 't'),
    # 水泥/粉/灰 → t
    (['水泥', '石粉', '石灰', '灰'], 't'),
    # 混凝土/商品混凝土（需在“砂石 m³”之前, 防被“土”误判）→ m³
    (['商品混凝土', '混凝土', '混凅土', '混苔土', '水下商品混凝土'], 'm³'),
    # 砂石/碑石/场渣 → m³
    (['砂', '碎石', '卵石', '石渣', '矿渣', '炉渣', '豆石', '碑石', '粉煤灰', '天然砂砾', '河砾石', '现浇混凝土'], 'm³'),
    # 砖/砌块 → 千块
    (['砖', '砌块', '粘土', '页岩', '煤研石', '加气混凝土', '陶粒'], '千块'),
    # 木材/锯材 → m³
    (['锯材', '木龙骨', '胶合板', '细木板', '木工板', '木材'], 'm³'),
    # 模板/竹胶板/石香板 → m² （按面积计, 不能被“玻璃 m²”先匹配）
    (['模板', '木胶合模板', '竹胶板', '石香板', '保温板', '矿棉', '石膏板', '石塑', '铝塑板', '石膏线'], 'm²'),
    # 玻璃/瓷砖/面砖 → m²
    (['玻璃', '瓷砖', '面砖', '地砖', '幕墙', '地板', '饰面'], 'm²'),
    # 涂料/卷材/防水 → kg
    (['涂料', '油漆', '清漆', '磁漆', '防锈漆', '卷材', '防水', '沥青', '腻子', '防水涂', '乳胶漆'], 'kg'),
    # 钉 / 焊条 / 焊丝 / 焊剂 → kg
    (['圆钉', '钉', '焊条', '焊丝', '焊剂'], 'kg'),
    # 桥架 / 母线 / 线槽 → m （按长度计）
    (['桥架', '母线', '线槽', '桥樂', '桥梁', '梯式桥'], 'm'),
    # 电线/电缆 → m
    (['电线', '电缆'], 'm'),
    # 苗木 → 株
    (['苗木', '树'], '株'),
    # 管类 → m
    (['管', 'PE管', 'PVC管', '铟管', '聚乙烯', '铟铁管', '铜管', 'PVC', 'PE', 'PPR'], 'm'),
    # 佝件/弯头 → 个
    (['弯头', '三通', '直接', '管箍', '法兰', '佝件', '螺栓', '螺母', '垫圈'], '个'),
    # 门/窗 → 橙
    (['门', '窗'], '橙'),
    # 灯具/开关/插座/阻火圈/灭火器/消火栓/水流指示器/铸铁散热器/底盒/接线盒/穿刺 → 个
    (['灯具', '灯', '开关', '插座', '面板', '断路器', '阻火圈', '灭火器', '干粉灭火器', '水基灭火器', '消火栓', '水流指示器', '铸铁', '散热器', '底盒', '塑料暗装底盒', '接线盒', '穿刺', '线夹', '防水涂', '防水卷材', '按钮', '信号'], '个'),
    # 喁 / 阀 → 个
    (['阀', '喁'], '个'),
]

def _infer_unit(breed: str) -> str:
    """从材料名推断单位. 匹配首个命中. """
    if not breed:
        return ''
    for keywords, unit in _UNIT_INFERENCE:
        for kw in keywords:
            if kw in breed:
                return unit
    return ''


# 合法单位 集合（用于过滤噪声）
_VALID_UNITS = {'t', 'm', 'm²', 'm³', 'kg', '千块', '株', '个', '橙', '套', '台', '台班'}

# OCR 噪声单位清理（OCR 把 "100mm" 错读成 unit、² 被识别成 ? 等）
_UNIT_NOISE_FIXES = {
    # OCR 变体 → 归一
    'm.': 'm³', 'm,': 'm³', '㎡': 'm²', 'm2': 'm²',
    'M2': 'm²', 'M3': 'm³', 'm3': 'm³',
    # 残件 / spec 溢出
    'm': 'm³',           # OCR 把 "m³" 截成 "m"（缺失 3/²）
    'm?': 'm³',          # OCR 误读 ² 为 ?
    '100m': '', '100ms': '', '100ml': '',
    '之副': '', '之剖': '',
}

def _clean_unit(raw: str, breed: str = '') -> str:
    """清洗 OCR 噪声 + 推断补齐。

    1. 含数字的非合法单位 → 去掉（"100m" "100ms" 之类是 spec 残留）
    2. m3 / ㎡ / m. / m / m? 之类 OCR 变体 → 归一
    3. 之副/之剖之类废词 → 去
    4. 最终仍空 → 走 breed 推断
    """
    if not raw:
        return _infer_unit(breed)
    s = raw.strip()
    # 噪声查表
    if s in _UNIT_NOISE_FIXES:
        s = _UNIT_NOISE_FIXES[s]
    # 含数字但不是合法单位 → 当作 spec 残留丢掉
    if s and re.search(r'\d', s) and s not in _VALID_UNITS:
        s = ''
    # 空 → 推断
    if not s:
        s = _infer_unit(breed)
    return s


def _clean_number(raw: str) -> float | None:
    if not raw:
        return None
    s = raw.strip()
    digits = sum(c.isdigit() for c in s)
    if digits == 0 or digits < len(s) * 0.4:
        return None
    fixed = s
    for bad, good in _OCR_NUM_FIXES:
        fixed = fixed.replace(bad, good)
    cleaned = re.sub(r'[^\d.\-]', '', fixed)
    if not cleaned or cleaned in ('-', '.', '..', '-.'):
        return None
    try:
        v = float(cleaned)
    except ValueError:
        return None
    if v <= 0 or v > 9999:
        return None
    if v >= 1000 and '.' not in cleaned:
        return None
    return v


_JUNK_BREED_PATTERNS = [
    re.compile(r'^[一二三四五六七八九十]、'),
    re.compile(r'^[（(]\d+[）)]'),
    re.compile(r'^-\d+-$'),
    re.compile(r'^[上下左右]+\d*$'),
    re.compile(r'^\d+$'),
    re.compile(r'^(kg|kg/m|kg/㎡|kg/m³|kg/m2|kg/m3|t|m³|m2|m³|元|)$', re.I),
]

def _is_junk_breed(text: str) -> bool:
    if not text or len(text.strip()) < 2:
        return True
    s = text.strip()
    for p in _JUNK_BREED_PATTERNS:
        if p.match(s):
            return True
    return False


# ─── Legacy fallback (v1.0 文本型, 防 rapidocr 装不上) ─────────────

def _parse_pdf_tables_legacy(pdf_path: str, max_pages: int = 200) -> list[dict]:
    rows = []
    try:
        with pdfplumber.open(pdf_path) as pdf:
            for pi, page in enumerate(pdf.pages[:max_pages]):
                tables = page.extract_tables() or []
                for tbl in tables:
                    for raw_row in tbl:
                        if not raw_row:
                            continue
                        cells = [str(c or '').strip() for c in raw_row]
                        if not any(cells):
                            continue
                        price = None
                        price_idx = -1
                        for i in range(len(cells) - 1, -1, -1):
                            c = cells[i].replace(',', '').replace(' ', '')
                            try:
                                v = float(c)
                                price = v
                                price_idx = i
                                break
                            except ValueError:
                                continue
                        if price is None:
                            continue
                        unit = cells[price_idx - 1] if price_idx >= 1 else ''
                        front = [c for c in cells[:price_idx - 1] if c] if price_idx >= 2 else []
                        breed = front[0] if len(front) >= 1 else ''
                        spec = front[1] if len(front) >= 2 else ''
                        remark = front[2] if len(front) >= 3 else ''
                        rows.append({
                            'breed': breed, 'spec': spec, 'unit': unit,
                            'price': price, 'remark': remark, 'page': pi + 1,
                        })
    except Exception as e:
        print(f'[sync] legacy 解析异常: {e}')
    return rows


# ─── ES 写入 ───────────────────────────────────────────────────────

def bulk_index(es, index: str, docs: list[dict]) -> tuple[int, int]:
    from elasticsearch.helpers import bulk
    if not docs:
        return 0, 0
    actions = [{'_index': index, '_source': d} for d in docs]
    ok, err = bulk(es, actions, raise_on_error=False, request_timeout=60)
    return ok, (len(err) if isinstance(err, list) else err)


def row_to_doc(row: dict, unit: dict) -> dict:
    now = datetime.now().isoformat(timespec='seconds')
    return {
        'period':        unit['period'],
        'period_start':  unit['period_start'],
        'period_end':    unit['period_end'],
        'period_days':   unit['period_days'],
        'breed':         row.get('breed', ''),
        'spec':          row.get('spec', ''),
        'unit':          row.get('unit', ''),
        'price':         row.get('price', 0.0),
        'city':          row.get('city', PROVINCE),
        'province':      PROVINCE,
        'update_date':   unit['publish_date'],
        'create_time':   now,
        'source_pdf':    unit.get('minio_key', ''),
        'source_url':    unit.get('pdf_url', ''),
        'remark':        row.get('remark', ''),
    }


# ─── 本地进度 (v0.5 兼容) ────────────────────────────────────────

def load_progress() -> dict:
    if not os.path.exists(PROGRESS_FILE):
        return {'done': {}}
    with open(PROGRESS_FILE, encoding='utf-8') as f:
        return json.load(f)


def save_progress(prog: dict) -> None:
    with open(PROGRESS_FILE, 'w', encoding='utf-8') as f:
        json.dump(prog, f, ensure_ascii=False, indent=2)


# ─── CLI 入口 ─────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description='山西工程造价材料信息同步 (v1.1.1)')
    parser.add_argument('--period', default='', help='指定 period (如 2026.3-4月)')
    parser.add_argument('--year', type=int, default=None,
                        help='只入指定年份 (默认 cfg.sync.default_year=2026)')
    parser.add_argument('--latest', action='store_true', help='只同步最新一期')
    parser.add_argument('--reset', action='store_true', help='重置本地进度')
    parser.add_argument('--all', action='store_true', help='同步所有未入仓的期 (不限年份)')
    parser.add_argument('--dry-run', action='store_true', help='预览, 不写入')
    parser.add_argument('--run-id', default='', help='指定 run_id')
    parser.add_argument('--max-units', type=int, default=None, help='只跑前 N 个单元')
    parser.add_argument('--legacy', action='store_true', help='走 Collector 路径 (默认即)')
    args = parser.parse_args()

    cfg = load_config()
    year = args.year if args.year is not None else cfg['sync'].get('default_year', 0)
    run_id = args.run_id or f'sx_run_{datetime.now().strftime("%Y%m%d_%H%M%S")}'

    from shanxi_collector import make_collector

    cfg_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        'config.yml',
    )
    collector = make_collector(
        cfg_path=cfg_path,
        run_id=run_id,
        year=year,
        period=args.period,
        latest=args.latest,
        all_years=args.all,
    )
    if args.reset:
        collector.progress.reset()
        print('[sync] 本地进度已重置')
    result = collector.run(max_units=args.max_units)
    print(f'\n[sync] 完成: {result}')


if __name__ == '__main__':
    main()