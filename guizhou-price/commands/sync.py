"""贵州工程造价信息 - 同步入口（v0.8 SyncRunner 抽象基类化, 参考 henan）。

源站: http://www.gzszj.com/Home/Policies/c2a45b5e-fb3e-43c6-a77c-000000000046
子 tab "工程造价信息" guid: c2a45b5e-fb3e-43c6-a77c-000000004601
数据获取: POST form-encoded /Home/GetPoliciesListBy 翻页
PDF: /Upload/File/{uuid}/{filename.pdf} (中文部分 URL-encoded)

v0.8 设计:
  - 默认走 GuizhouCollector（SyncRunner 化版本, commands/guizhou_collector.py）
  - --legacy 走原 v0.7 cmd_legacy_sync（逃生通道）
  - 字段扩展: doc 中新增 period_start / period_end / period_days
    period 格式: "YYYY.N期" (道友要求"时间方法 2026 年", 12 期/年 = 月刊)
"""
import argparse
import calendar
import hashlib
import json
import os
import re
import sys
import tempfile
import time
from datetime import datetime, timezone, timedelta
from urllib.parse import urljoin, quote

import pdfplumber

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

from utils import (
    load_config, get_es_client, get_s3_client,
    ensure_bucket, ensure_ods_index, ensure_progress_index,
    fetch_html, download_file, upload_to_minio, post_form,
)

PROGRESS_FILE = os.path.join(
    os.path.dirname(SCRIPT_DIR), '.guizhou_sync_progress.json',
)

CST_TZ = timezone(timedelta(hours=8))

# 贵州省份指南价统一 city 标签
PROVINCE_CITY = '贵州'


# ─── 工具函数：日期 / 期号 ────────────────────────────────────────────────────

def parse_dotnet_date(s):
    """"/Date(1784002645093)/" → 'YYYY-MM-DD' (CST, +08:00)。"""
    m = re.search(r'/Date\((\d+)\)/', s or '')
    if not m:
        return ''
    ms = int(m.group(1))
    return datetime.fromtimestamp(ms / 1000, tz=CST_TZ).strftime('%Y-%m-%d')


def parse_period_from_title(title):
    """'贵州省建设工程造价信息 2026年第6期' → 业务期号窗口。

    Returns:
        {
            'period': '2026.6期',
            'period_start': '2026-06-01',
            'period_end':   '2026-06-30',
            'period_days':  30,
            'issue':        6,
            'year':         2026,
            'invalid':      False,
        }
    若期号越界（>12 或 <1）则返回 {'invalid': True, ...}。
    """
    m = re.search(r'(\d{4})\s*年\s*第\s*(\d{1,2})\s*期', title or '')
    if not m:
        return {'period': '', 'invalid': True}
    year, issue = int(m.group(1)), int(m.group(2))
    if not (1 <= issue <= 12):
        return {'period': '', 'year': year, 'issue': issue, 'invalid': True}
    last_day = calendar.monthrange(year, issue)[1]
    return {
        'period': f'{year}.{issue}期',
        'period_start': f'{year:04d}-{issue:02d}-01',
        'period_end':   f'{year:04d}-{issue:02d}-{last_day:02d}',
        'period_days':  last_day,
        'issue':        issue,
        'year':         year,
        'invalid':      False,
    }


def make_pdf_url(base_url, file_url):
    """'uuid/贵州省...-2026第6期.pdf' → 完整可下载 URL（中文部分 URL-encoded）。"""
    return urljoin(base_url + '/', 'Upload/File/' + quote(file_url, safe='/'))


# ─── AJAX 列表页 ─────────────────────────────────────────────────────────────

def _post_list_page(cfg, page):
    """POST /Home/GetPoliciesListBy 一页。"""
    site = cfg['site']
    url = site['base_url'] + site['ajax_path']
    headers = {
        'Referer': site['base_url'] + site['list_path'],
        'X-Requested-With': 'XMLHttpRequest',
        'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
    }
    body = (
        f"guid={site['sub_tab_guid']}"
        f"&page={page}"
        f"&pagesize={site['page_size']}"
    )
    r = post_form(url, data=body, headers=headers, timeout=site['timeout_sec'])
    r.raise_for_status()
    return r.text


def fetch_all_periods(cfg):
    """翻所有页（直到 Total 用尽），返回 list[dict]。

    每条 dict keys: id, title, publish_date, detail_url, pdf_url, pdf_name。
    """
    site = cfg['site']
    page_size = site['page_size']
    page = 1
    items = []
    seen_ids = set()
    while True:
        resp_text = _post_list_page(cfg, page)
        try:
            data = json.loads(resp_text)
        except json.JSONDecodeError:
            break
        page_rows = data.get('Rows') or []
        if not page_rows:
            break
        for r in page_rows:
            rid = r.get('ID')
            if rid in seen_ids:
                continue
            seen_ids.add(rid)
            atts = r.get('PoliciesAttachmentDTOS') or []
            if not atts:
                continue
            file_url = atts[0].get('FileUrl') or ''
            if not file_url:
                continue
            pdf_url = make_pdf_url(site['base_url'], file_url)
            pdf_name = file_url.split('/')[-1]
            detail_url = f"{site['base_url']}/Home/PoliciesDetail/{rid}"
            items.append({
                'id': rid,
                'title': r['Name'],
                'publish_date': parse_dotnet_date(r.get('EntryDate', '')),
                'detail_url': detail_url,
                'pdf_url': pdf_url,
                'pdf_name': pdf_name,
            })
        total = data.get('Total') or 0
        if total and len(items) >= total:
            break
        if len(page_rows) < page_size:
            break
        page += 1
        if page > 50:  # 安全阀（理论 7 页 = 20/页）
            break
    return items


# ─── PDF 解析（贵州特定） ────────────────────────────────────────────────
# 贵州省 PDF：每月一期, 6 列固定结构（序号|产品/材料/苗木名称|规格或型号|
# 单位|除税价格(元)|备注）。9 个地市分块（贵阳/遵义/六盘水/安顺/毕节/铜仁/
# 黔东南/黔南/黔西南），每块首页文字含段标题如"2026年6月份贵阳市区…"。
HEADER_KEYWORDS = {
    'breed':  ['产品名称', '材料名称', '苗木名称', '材料', '品名', '名称'],
    'spec':   ['规格或型号', '规格（cm）', '规格', '型号', '规格型号'],
    'unit':   ['单位'],
    'price':  ['除税价格', '除税价', '含税价格', '含税价',
               '不含税价', '信息价', '市场价', '参考价', '单价', '价格', '金额'],
    'remark': ['备注', '备 注', '注'],
}

# 段标题（用于推断 city）："2026年6月份贵阳市区主要..." → "贵阳市区"
# 严格要求以 (州|市)区 或 (州|市)（xxx区） 结尾, 避免被后面"主要建筑…市场…"吃掉
SECTION_RE = re.compile(
    r'(\d{4})年(\d{1,2})月份?'
    r'([\u4e00-\u9fa5]{1,6}(?:州|市)(?:区|（[\u4e00-\u9fa5]+(?:州|市)区）)?)'
)

# TOC 页面分割点："(17)" 或 "（17）"，后面接 "2026年6月份..." 标题
# 用 re.split 按这个分割点切, 避免单条 title 被非贪心 truncate
TOC_SPLIT_RE = re.compile(r'[（(](\d{1,3})[）)]')


def _normalize_cell(s):
    """全角 ASCII (０xFF01-0xFF5E) → 半角; 全角空格 → 半角空格; 去换行。

    PDF 表格里大量 "２９", "１００", "ｍ２", "（元）" 这种字形。
    """
    if s is None:
        return ''
    s = str(s)
    out = []
    for c in s:
        code = ord(c)
        if 0xFF01 <= code <= 0xFF5E:
            out.append(chr(code - 0xFEE0))
        elif c == '　':
            out.append(' ')
        else:
            out.append(c)
    s = ''.join(out)
    s = s.replace('．', '.').replace('（', '(').replace('）', ')')
    return s.replace('\n', ' ').strip()


def _parse_price(s):
    """cell → float, 失败返回 None。"""
    s = _normalize_cell(s)
    if not s:
        return None
    s = s.replace('￥', '').replace('¥', '').replace(',', '').replace(' ', '')
    try:
        v = float(s)
        return v if v > 0 else None
    except ValueError:
        return None


def _detect_section(text):
    """'2026年6月份贵阳市区主要建筑安装材料…' → (section_title, city).

    Returns:
        (section, city). city 可能含 '（凯里市区）' 等括号尾注。
    """
    if not text:
        return '', ''
    m = SECTION_RE.search(text)
    if not m:
        return '', ''
    return m.group(0), m.group(3)


def _parse_toc(text):
    """从 TOC 文本解析 (page_num, city, section_title) 列表。

    源站 TOC 例：
      (17) 2026年6月份贵阳市区主要建筑安装材料市场综合参考价
      (29) 2026年6月份贵阳市区园林绿化工程植物市场综合参考价
      (37) 2026年6月份遵义市区主要建筑安装材料市场综合参考价
      (105) 2026年6月份黔南州（都匀市区）主要建筑安装材料市场综合参考价

    实现：re.split 按 "(N)" 切分（仅切含数字的 (N)，不会切 "(凯里市区)" 这种），
    然后从每段中抽 page_num + 抽 title（按 "YYYY年N月份" 锚定起点）+ 用
    SECTION_RE 抽 city。
    """
    if not text:
        return []
    norm = _normalize_cell(text).replace(' / ', '  ').replace('/', ' ')
    entries = []
    parts = TOC_SPLIT_RE.split(norm)
    # parts: ['leading', '17', ' 2026年6月份贵阳市区...  ', '29', ' ...', ...]
    for i in range(1, len(parts), 2):
        try:
            page_num = int(parts[i])
        except (ValueError, IndexError):
            continue
        title = parts[i + 1].strip() if i + 1 < len(parts) else ''
        # 截到 "YYYY年N月份" 起点（防 split 切偏）
        m_year = re.search(r'\d{4}\s*年\s*\d{1,2}\s*月份?', title)
        if m_year:
            title = title[m_year.start():].strip()
        if not title:
            continue
        city_m = SECTION_RE.search(title)
        city = city_m.group(3) if city_m else ''
        entries.append((page_num, city, title))
    return entries


def _classify_cols(header):
    """表头 → {'breed': idx, 'spec': idx, 'unit': idx, 'price': idx, ...} 子集。"""
    col_map = {}
    if not header:
        return col_map
    for i, h in enumerate(header):
        s = _normalize_cell(h)
        if not s:
            continue
        for key, kws in HEADER_KEYWORDS.items():
            if key in col_map:
                continue
            for kw in kws:
                if kw in s:
                    col_map[key] = i
                    break
    return col_map


def _row_to_item(cells, col_map, default_city='贵州', section=''):
    """一行 cells → dict | None。"""
    out = {'city': default_city, 'section': section}
    if col_map.get('breed') is not None and col_map['breed'] < len(cells):
        out['breed'] = _normalize_cell(cells[col_map['breed']])
    if col_map.get('spec') is not None and col_map['spec'] < len(cells):
        out['spec'] = _normalize_cell(cells[col_map['spec']])
    if col_map.get('unit') is not None and col_map['unit'] < len(cells):
        out['unit'] = _normalize_cell(cells[col_map['unit']])
    if col_map.get('price') is not None and col_map['price'] < len(cells):
        out['price'] = _parse_price(cells[col_map['price']])
    if col_map.get('remark') is not None and col_map['remark'] < len(cells):
        out['remark'] = _normalize_cell(cells[col_map['remark']])
    if (out.get('price') is None or out.get('price') <= 0
            or not out.get('breed')):
        return None
    return out


def parse_pdf_tables(pdf_path):
    """提取 PDF 价格表（两阶段：TOC → page-by-page）。

    页面的 extract_text() 不含段标题（pdfplumber 漏抽），所以从 TOC
    （page 3, 文本形式 "(17) 2026年6月份贵阳市区主要..."）反查
    page_num → (city, title) 映射，逐页 apply。

    每表需表头同时含 '序号' + '名称/材料' 才认作价格表（避免封面元数据）。
    """
    items = []
    page_to_section = {}  # 1-based page_num → (city, section_title)
    current_city = ''
    current_section = ''

    try:
        with pdfplumber.open(pdf_path) as pdf:
            # Stage 1: 抓 TOC（前 5 页，源站 TOC 在 page 3）
            for page in pdf.pages[:5]:
                text = page.extract_text() or ''
                for page_num, city, title in _parse_toc(text):
                    page_to_section[page_num] = (city, title)

            # Stage 2: 处理每页
            for pi, page in enumerate(pdf.pages):
                page_num = pi + 1  # PDF 页号 1-based
                if page_num in page_to_section:
                    current_city, current_section = page_to_section[page_num]

                try:
                    tables = page.extract_tables() or []
                except Exception:
                    continue
                for tbl in tables:
                    if not tbl or all(not any(row) for row in tbl):
                        continue
                    # 找表头：必须同时含 '序号' + '名称/材料'
                    header = None
                    data_start = 0
                    for hi, row in enumerate(tbl[:5]):
                        row_text = ' '.join(str(c or '') for c in row)
                        if '序号' in row_text and (
                            '名称' in row_text or '材料' in row_text
                        ):
                            header = row
                            data_start = hi + 1
                            break
                    if header is None:
                        continue
                    col_map = _classify_cols(header)
                    if 'breed' not in col_map or 'price' not in col_map:
                        continue
                    for row in tbl[data_start:]:
                        cells = [str(c or '') for c in row]
                        if not any(cells):
                            continue
                        item = _row_to_item(
                            cells, col_map,
                            default_city=current_city or PROVINCE_CITY,
                            section=current_section,
                        )
                        if item:
                            items.append(item)
    except Exception:
        pass
    return items


# ─── 进度管理 ────────────────────────────────────────────────────────────────

def load_progress():
    if not os.path.exists(PROGRESS_FILE):
        return {'done': {}}
    with open(PROGRESS_FILE) as f:
        return json.load(f)


def save_progress(prog):
    with open(PROGRESS_FILE, 'w') as f:
        json.dump(prog, f, ensure_ascii=False, indent=2)


# ─── ES bulk_index ──────────────────────────────────────────────────────────

def _doc_id(period, breed, spec, city):
    raw = f'{period}|{breed}|{spec}|{city}'
    return hashlib.md5(raw.encode('utf-8')).hexdigest()


def bulk_index(es, index, docs):
    """幂等写入（按 _id upsert）。

    placeholder 行 (remark='unparsed') 用 source_pdf 区分,
    确保同一期重复同步不重复插。
    """
    if not docs:
        return 0, 0
    body = ''
    for d in docs:
        sig_parts = [
            d['period'],
            d.get('breed', ''),
            d.get('spec', ''),
            d.get('city', ''),
        ]
        if d.get('remark') == 'unparsed':
            sig_parts.append(d.get('source_pdf', ''))
        raw = '|'.join(sig_parts)
        _id = hashlib.md5(raw.encode('utf-8')).hexdigest()
        body += json.dumps(
            {'index': {'_index': index, '_id': _id}}, ensure_ascii=False,
        ) + '\n'
        body += json.dumps(d, ensure_ascii=False) + '\n'
    resp = es.bulk(body=body, refresh=False)
    if resp.get('errors'):
        errors = sum(
            1 for it in resp['items']
            if 'error' in it.get('index', {})
        )
        return len(docs) - errors, errors
    return len(docs), 0


# ─── v0.7 legacy ─────────────────────────────────────────────────────────────

def cmd_legacy_sync(args):
    """v0.7 等价流程：抓 → 过滤 → 下载 → MinIO → 解析 → bulk → 进度。

    与 v0.8 Collector 行为等价, 但不走 SIGINT / 进度批量优化。
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

    print(f'[guizhou v0.7 legacy] ES: {es_host}')
    print(f'[guizhou v0.7 legacy] MinIO: {cfg["minio"]["endpoint"]} / {cfg["minio"]["bucket"]}')

    print('[guizhou v0.7 legacy] 抓取列表（POST AJAX 翻页）...')
    items = fetch_all_periods(cfg)
    print(f'[guizhou v0.7 legacy] 共 {len(items)} 期')

    todo = []
    for it in items:
        if args.period and args.period not in it['title']:
            continue
        if args.year and f'{args.year}年' not in it['title']:
            continue
        if it['detail_url'] in progress['done'] and \
                progress['done'][it['detail_url']].get('status') == 'ok':
            continue
        todo.append(it)
    if args.latest:
        todo = todo[:1]

    print(f'[guizhou v0.7 legacy] 待处理 {len(todo)} 期')
    if not todo:
        print('[guizhou v0.7 legacy] 无新数据')
        return

    total_written = 0
    for idx, item in enumerate(todo, 1):
        print(
            f'\n[guizhou v0.7 legacy] [{idx}/{len(todo)}] '
            f'{item["title"]}  ({item["publish_date"]})'
        )
        start = time.time()
        try:
            win = parse_period_from_title(item['title'])
            if not win or win.get('invalid'):
                raise ValueError(f'无法解析期号: {item["title"]}')
            period = win['period']
            print(
                f'  period: {period}  '
                f'({win["period_start"]} ~ {win["period_end"]}, '
                f'{win["period_days"]}天)'
            )

            with tempfile.TemporaryDirectory() as tmpdir:
                local_pdf = os.path.join(tmpdir, 'source.pdf')
                download_file(item['pdf_url'], local_pdf, timeout=120)

                minio_key = f"{cfg['minio']['prefix']}/{item['pdf_name']}"
                if not args.dry_run:
                    upload_to_minio(
                        s3, cfg['minio']['bucket'], minio_key, local_pdf,
                    )
                print(f'  minio: {minio_key}')

                pdf_rows = parse_pdf_tables(local_pdf)
                print(f'  parsed rows: {len(pdf_rows)}')

                now = datetime.now().isoformat(timespec='seconds')
                docs = []
                if pdf_rows:
                    for r in pdf_rows:
                        docs.append({
                            'period': period,
                            'period_start': win['period_start'],
                            'period_end': win['period_end'],
                            'period_days': win['period_days'],
                            'breed': r.get('breed', ''),
                            'spec': r.get('spec', ''),
                            'unit': r.get('unit', ''),
                            'price': r['price'],
                            'city': r.get('city', '贵州'),
                            'province': '贵州',
                            'update_date': item['publish_date'],
                            'create_time': now,
                            'source_pdf': minio_key,
                            'source_url': item['pdf_url'],
                            'remark': r.get('remark', ''),
                        })
                else:
                    # PDF 没解析到表格 — 插一条 placeholder 标记已归档
                    docs.append({
                        'period': period,
                        'period_start': win['period_start'],
                        'period_end': win['period_end'],
                        'period_days': win['period_days'],
                        'breed': '', 'spec': '', 'unit': '',
                        'price': 0.0,
                        'city': '贵州', 'province': '贵州',
                        'update_date': item['publish_date'],
                        'create_time': now,
                        'source_pdf': minio_key,
                        'source_url': item['pdf_url'],
                        'remark': 'unparsed',
                    })

                if args.dry_run:
                    print(
                        f'  [dry-run] 将写 {len(docs)} 条到 '
                        f'{cfg["es"]["ods_index"]}'
                    )
                    ok, err = len(docs), 0
                else:
                    ok, err = bulk_index(es, cfg['es']['ods_index'], docs)
                    print(f'  bulk: ok={ok}, err={err}')

                elapsed = time.time() - start
                progress['done'][item['detail_url']] = {
                    'period': period,
                    'publish_date': item['publish_date'],
                    'detail_url': item['detail_url'],
                    'pdf_url': item['pdf_url'],
                    'minio_key': minio_key,
                    'docs_written': ok,
                    'parsed_rows': len(pdf_rows),
                    'status': 'ok' if err == 0 else 'partial',
                    'duration_sec': round(elapsed, 1),
                    'created_at': now,
                }
                save_progress(progress)

                if not args.dry_run:
                    es.index(
                        index=cfg['es']['progress_index'], body={
                            'period': period,
                            'period_start': win['period_start'],
                            'period_end': win['period_end'],
                            'period_days': win['period_days'],
                            'publish_date': item['publish_date'],
                            'detail_url': item['detail_url'],
                            'pdf_url': item['pdf_url'],
                            'minio_key': minio_key,
                            'docs_written': ok,
                            'parsed_rows': len(pdf_rows),
                            'status': 'ok' if err == 0 else 'partial',
                            'duration_sec': round(elapsed, 1),
                            'created_at': now,
                        },
                    )

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

    print(f'\n[guizhou v0.7 legacy] 全部完成: total_written={total_written}')


# ─── main 入口 ──────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description='贵州工程造价材料信息同步（v0.8 SyncRunner 化）',
    )
    parser.add_argument(
        '--period', default='',
        help='指定周期（如 2026.6期）',
    )
    parser.add_argument(
        '--year', type=int, default=None,
        help='只入库指定年份的期（默认 config.default_year=2026；传 0 = 不限）',
    )
    parser.add_argument(
        '--all', action='store_true',
        help='同步所有未入仓的期（不限年份）',
    )
    parser.add_argument('--reset', action='store_true', help='重置进度')
    parser.add_argument(
        '--dry-run', action='store_true',
        help='预览，不写入（仅 legacy 支持）',
    )
    parser.add_argument('--latest', action='store_true', help='只同步最新一期')
    parser.add_argument(
        '--run-id', default='',
        help='指定 run_id（默认自动生成）',
    )
    parser.add_argument(
        '--legacy', action='store_true',
        help='v0.7 兼容：走原 main 流程。默认走 Collector（推荐）。',
    )
    parser.add_argument(
        '--max-units', type=int, default=None,
        help='Collector 路径：只跑前 N 个工作单元（验证用）',
    )
    args = parser.parse_args()

    cfg_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        'config.yml',
    )

    if args.legacy:
        if args.year is None:
            args.year = datetime.now().year
        print('[v0.7 兼容路径] cmd_legacy_sync 启动')
        print(f'  period={args.period}, year={args.year}, latest={args.latest}')
        cmd_legacy_sync(args)
        return

    from guizhou_collector import make_collector
    run_id = args.run_id or (
        f"gz_run_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    )
    # year=0 表示不限; --all 显式置 0
    if args.all:
        year = 0
    elif args.year is not None:
        year = args.year
    else:
        # 没传: 用 config 默认值（道友要求 2026）
        try:
            cfg = load_config()
            year = int(cfg.get('sync', {}).get('default_year', 2026))
        except Exception:
            year = 2026
    print('[Collector 路径 v0.8] GuizhouCollector 启动')
    print(
        f'  year={year}, period={args.period}, latest={args.latest}, '
        f'run_id={run_id}'
    )

    collector = make_collector(
        cfg_path=cfg_path,
        run_id=run_id,
        year=year,
        period=args.period,
        latest=args.latest,
    )
    result = collector.run(reset=args.reset, max_units=args.max_units)
    print(f'\n[Collector 路径 v0.8] 完成: {result}')


if __name__ == '__main__':
    main()
