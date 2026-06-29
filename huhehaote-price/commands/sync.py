"""呼和浩特建设工程材料市场价格信息 - 同步主程序

流程：
1. 抓取列表（单页 index.html），提取每期（标题含 PDF 链接）
2. 过滤：标题含"信息价"或"造价信息"，且 progress 未 ok
3. 对每期：
   a. 下载 PDF → 本地临时文件
   b. 上传 MinIO
   c. pdfplumber 解析 → 长表
      - 7 列表材料（编码/名称/单位/含税价/除税价/税率/备注）
        双价：price=除税价，tax_price=含税价
      - 4 列表人工成本（序号/工种/日工资/备注）
      - 5 列表机械租赁（序号/名称/型号/单位/价格）
      - 5 列表建筑安装单方造价（区间，不入库）
   d. bulk_index 到 ods_material_huhehaote_price（幂等 _id）
   e. 写进度（本地 JSON + ES progress 索引）

PDF 结构（86 页）：
- p1-p79: 呼市地区建设工程材料市场价格信息采集
  - 数字章节：01 黑色及有色金属 / 02 水泥 / ... / 32 花卉苗木
  - 7 列表（双价含税+除税）
- p80-p83: 五、旗县区
  - 1、土左旗 / 2、托克托县 / 3、和林格尔县 / 4、清水河县
  - 7 列表（每个旗县单独的简化材料价）
- p84: 呼市地区建筑工种人工成本信息（4 列表）
- p85: 呼市地区建设工程施工机械租赁价格信息（5 列表）
- p86: 二〇二五年末建筑安装工程单方造价参考信息（5 列表，区间值，参考）
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

PROGRESS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '.huhehaote_sync_progress.json')

VAT_RATE = 0.13


# ─── 列表页解析 ──────────────────────────────────────────────────────────────
def parse_list_page(html, base_url):
    """从列表页提取每期（li.div.li-left a.title + span 发布日期）"""
    soup = BeautifulSoup(html, 'html.parser')
    items = []
    for li in soup.select('li'):
        a = li.select_one('div.li-left a[href*=".html"]')
        if not a:
            continue
        href = a.get('href', '')
        title = a.get('title', '') or a.get_text(strip=True)
        span = li.select_one('div.li-left span')
        date = ''
        if span:
            date_m = re.search(r'(\d{4}-\d{2}-\d{2})', span.get_text())
            if date_m:
                date = date_m.group(1)
        items.append({
            'title': title.strip(),
            'publish_date': date,
            'detail_url': urljoin(base_url + '/bsfw_91/xzzx/zjxx/', href),
        })
    return items


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
    # 去重
    seen = set()
    uniq = []
    for it in items:
        if it['detail_url'] in seen:
            continue
        seen.add(it['detail_url'])
        uniq.append(it)
    return uniq


def fetch_detail_pdf(cfg, detail_url):
    """访问详情页，提取 PDF 链接

    PDF 链接可能在：
    - <a href="…pdf">（部分详情页）
    - JS 字符串 var fujian='…pdf';（呼和浩特详情页主要格式）
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

    # 2. 从 JS 字符串提取（呼和浩特详情页 var fujian='…pdf';）
    m = re.search(r"var\s+fujian\s*=\s*['\"]([^'\"]+\.pdf)['\"]", html)
    if m:
        pdf_url = urljoin(detail_url, m.group(1))
        return title, pdf_url, ''

    # 3. 备选：video src="…pdf"
    m = re.search(r'<video[^>]*src="([^"]+\.pdf)"', html)
    if m:
        pdf_url = urljoin(detail_url, m.group(1))
        return title, pdf_url, ''

    return title, None, None


def pdf_basename(pdf_url: str) -> str:
    from urllib.parse import urlparse
    return os.path.basename(urlparse(pdf_url).path) or 'source.pdf'


# ─── PDF 解析 ────────────────────────────────────────────────────────────────
def _parse_price(s):
    """解析价格字段（支持 \n ↑ ↓ 趋势箭头、空格、人民币符号）"""
    if s is None:
        return None
    s = str(s).strip()
    for ch in ['\n', '\r', '\t', ' ', ',', '￥', '¥', '↑', '↓']:
        s = s.replace(ch, '')
    if not s or s in ('—', '-', '——', '/'):
        return None
    try:
        v = float(s)
        return v if v > 0 else None
    except ValueError:
        return None


def _is_section_row(row):
    """判断是否是章节标题行（如 "01 黑色及有色金属"，row[0]='01' 短码 + row[1] 是中文分类）"""
    if not row or len(row) < 2:
        return False
    code = str(row[0] or '').strip()
    name = str(row[1] or '').strip()
    # 编码 1-2 位数字 + 名称（中文）
    if re.match(r'^\d{1,2}$', code) and name and re.search(r'[\u4e00-\u9fff]', name):
        # 且名称没有规格符号
        if not re.search(r'[×Φ\d]+[A-Za-z]', name):
            return True
    return False


def _is_data_row(row, n_cols):
    """判断是否是有效数据行（材料编码 6-12 位数字）"""
    if not row or len(row) < n_cols:
        return False
    code = str(row[0] or '').strip()
    return bool(re.match(r'^\d{6,12}$', code))


def _is_county_row(row):
    """判断是否是旗县标题行（如 "1、土默特左旗" / "2、托克托县"）"""
    if not row or len(row) < 2:
        return False
    first = str(row[0] or '').strip()
    # 1、中文 / 1、土默特左旗 等
    return bool(re.match(r'^\d{1,2}[、，,]', first)) and len(first) < 30


# 旗县名识别（从表格"1、土默特左旗"行的 row[0] 或 row[1] 提取）
COUNTY_RE = re.compile(r'^(\d{1,2})[、，,](.+)$')


# 大章节识别（按页眉"呼和浩特地区建设工程材料市场价格信息采集"）
PDF_MAIN_TITLES = {
    '呼和浩特地区建设工程材料市场价格信息采集': '材料价格',
    '呼市地区建筑工种人工成本信息': '人工成本',
    '呼市地区建设工程施工机械租赁价格信息': '机械租赁',
    '二〇二五年末建筑安装工程单方造价参考信息': '单方造价参考',
}


def _detect_main_section(text, current_section):
    """从页眉识别主章节"""
    for title, section in PDF_MAIN_TITLES.items():
        if title in text:
            return section
    return current_section


def _detect_sub_section(text, current_subsection):
    """从页眉识别数字小章节（"01 黑色及有色金属"）

    只检查页眉位置（前 3 行），避免把表格内的数据行误识别为章节。
    要求章节名是中文为主的字符串，长度 ≤ 20，排除"编者按"等说明性行。
    """
    # 中文大类（一、二、...）在第 1-3 行
    for line in (text.split('\n') if text else [])[:3]:
        stripped = line.strip()
        # 排除"编者按"等说明性行
        if '编者按' in stripped or '注：' in stripped:
            continue
        # 排除长说明句（> 25 字符）
        if len(stripped) > 25:
            continue
        m = re.match(r'^[一二三四五六七八九十]+、(.+?)$', stripped)
        if m:
            grp = m.group(1).strip()
            if len(grp) <= 20:
                return grp
    # 数字小节（"01 黑色及有色金属"）在第 1-3 行
    for line in (text.split('\n') if text else [])[:3]:
        stripped = line.strip()
        if '编者按' in stripped or '注：' in stripped:
            continue
        m = re.match(r'^(\d{1,2})\s+([\u4e00-\u9fff][\u4e00-\u9fff、（）()（） ]+)$', stripped)
        if m and len(stripped) < 30:
            return m.group(2).strip()
    return current_subsection


def parse_pdf(pdf_path):
    """解析 PDF → 长表 [{...}]"""
    out = []
    current_main_section = ''   # 主章节（材料价格 / 旗县区材料 / 人工成本 / 机械租赁 / 单方造价参考）
    current_subsection = ''     # 数字小节（01 黑色及有色金属...）
    current_county = ''         # 旗县区（土默特左旗 / 托克托县 / ...）

    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            try:
                text = page.extract_text() or ''
            except Exception:
                continue
            if not text:
                continue

            # 主章节识别（页眉）
            new_main = _detect_main_section(text, current_main_section)
            if new_main != current_main_section:
                current_main_section = new_main
                current_subsection = ''
                current_county = ''
            # 小节识别
            sub = _detect_sub_section(text, current_subsection)
            if sub:
                current_subsection = sub

            tables = page.extract_tables() or []
            for tbl in tables:
                if not tbl or len(tbl) < 2:
                    continue
                n_cols = len(tbl[0]) if tbl[0] else 0

                # 先扫表内旗县标题（更新 current_county）
                for row in tbl:
                    if _is_county_row(row):
                        first = str(row[0] or '').strip()
                        m = COUNTY_RE.match(first)
                        if m:
                            current_county = m.group(2).strip()

                # ─── 7 列表材料价格 ───
                if n_cols == 7 and current_main_section in ('材料价格', '旗县区材料'):
                    _parse_material_table(tbl, current_main_section, current_subsection, current_county, out)

                # ─── 4 列表人工成本 ───
                elif n_cols == 4 and current_main_section == '人工成本':
                    _parse_labor_table(tbl, current_subsection, out)

                # ─── 5 列表机械租赁 ───
                elif n_cols == 5 and current_main_section == '机械租赁':
                    _parse_machine_table(tbl, current_subsection, out)

                # ─── 5 列表单方造价 ───
                elif n_cols == 5 and current_main_section == '单方造价参考':
                    # 区间值，参考信息，不入库（暂）
                    pass

    return out


def _parse_material_table(tbl, main_section, subsection, county, out):
    """7 列表材料价格 → 双价（price=除税, tax_price=含税）"""
    for row in tbl:
        if not row or len(row) < 7:
            continue
        if all(c is None or str(c).strip() == '' for c in row):
            continue
        # 章节标题行（"01 黑色及有色金属"）→ 跳过
        if _is_section_row(row):
            continue
        # 旗县标题行 → 跳过
        if _is_county_row(row):
            continue
        # 8 位材料编码
        if not _is_data_row(row, 7):
            continue
        code = str(row[0] or '').strip()
        name = str(row[1] or '').strip()
        unit = str(row[2] or '').strip()
        tax_price = _parse_price(row[3])   # 含税
        price = _parse_price(row[4])      # 除税
        vat_rate = _parse_price(row[5])    # 平均税率
        remark = str(row[6] or '').strip() if row[6] else ''
        if price is None and tax_price is None:
            continue

        # PDF 表头为"材料名称及规格型号"（合并列），无法在解析阶段拆分；
        # 将整段同时写入 breed 和 spec，确保下游 ETL 的 must_not (spec=["","/"])
        # 不再过滤此类数据，attr 解析阶段会基于 spec 抽取规格属性。
        out.append({
            'no': code,
            'breed': name,
            'spec': name,
            'unit': unit,
            'price': price if price is not None else tax_price,
            'tax_price': tax_price if tax_price is not None else price,
            'remark': remark,
            'vat_rate': vat_rate,
            'section': subsection or main_section,
            'category': main_section,
            'region': county,
            'city': county or '呼和浩特',
        })


def _parse_labor_table(tbl, subsection, out):
    """4 列表人工成本（序号 / 工种 / 日工资 / 备注）"""
    for row in tbl:
        if not row or len(row) < 4:
            continue
        if all(c is None or str(c).strip() == '' for c in row):
            continue
        seq = str(row[0] or '').strip()
        if not seq.isdigit():
            continue
        name = str(row[1] or '').strip()
        price = _parse_price(row[2])
        remark = str(row[3] or '').strip() if row[3] else ''
        if price is None:
            continue
        # 人工成本工种无规格字段，但 ETL must_not 会过滤 spec="" 的数据；
        # 把工种名同步填入 spec 字段，避免被过滤（attr 解析阶段按 breed 处理）。
        out.append({
            'no': seq,
            'breed': name,
            'spec': name,
            'unit': '日',
            'price': price,
            'tax_price': price,
            'remark': remark,
            'vat_rate': None,
            'section': subsection or '人工成本',
            'category': '人工成本',
            'region': '',
            'city': '呼和浩特',
        })


def _parse_machine_table(tbl, subsection, out):
    """5 列表机械租赁（序号 / 名称 / 型号 / 单位 / 价格）"""
    for row in tbl:
        if not row or len(row) < 5:
            continue
        if all(c is None or str(c).strip() == '' for c in row):
            continue
        seq = str(row[0] or '').strip()
        if not seq.isdigit():
            continue
        name = str(row[1] or '').strip()
        spec = str(row[2] or '').strip()
        unit = str(row[3] or '').strip()
        price = _parse_price(row[4])
        if price is None:
            continue
        out.append({
            'no': seq,
            'breed': name,
            'spec': spec,
            'unit': unit,
            'price': price,
            'tax_price': price,
            'remark': '',
            'vat_rate': None,
            'section': subsection or '机械租赁',
            'category': '机械租赁',
            'region': '',
            'city': '呼和浩特',
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
def _doc_id(period, section, no, breed, city, spec=''):
    raw = f'{period}|{section}|{no}|{breed}|{city}|{spec}'
    return hashlib.md5(raw.encode('utf-8')).hexdigest()


def bulk_index(es, index, docs):
    if not docs:
        return 0, 0
    body = ''
    for d in docs:
        _id = _doc_id(d['period'], d['section'], d['no'], d['breed'], d['city'], d.get('spec', ''))
        body += json.dumps({'index': {'_index': index, '_id': _id}}, ensure_ascii=False) + '\n'
        body += json.dumps(d, ensure_ascii=False) + '\n'
    resp = es.bulk(body=body, refresh=False)
    if resp.get('errors'):
        errors = sum(1 for it in resp['items'] if 'error' in it.get('index', {}))
        return len(docs) - errors, errors
    return len(docs), 0


# ─── 主流程 ──────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description='呼和浩特建设工程材料价格同步')
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

    print(f'[huhehaote] ES: {es_host}')
    print(f'[huhehaote] MinIO: {cfg["minio"]["endpoint"]} / {cfg["minio"]["bucket"]}')
    print(f'[huhehaote] journal_keyword: {cfg.get("journal_keyword", "")}')

    print('[huhehaote] 抓取列表...')
    items = fetch_all_periods(cfg)
    print(f'[huhehaote] 共 {len(items)} 期')

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

    print(f'[huhehaote] 待处理 {len(todo)} 期')
    if not todo:
        print('[huhehaote] 无新数据')
        return

    total_written = 0
    for idx, item in enumerate(todo, 1):
        print(f'\n[huhehaote] [{idx}/{len(todo)}] {item["title"]}  ({item["publish_date"]})')
        start = time.time()
        try:
            title, pdf_url, _ = fetch_detail_pdf(cfg, item['detail_url'])
            if not pdf_url:
                print(f'  ✗ 详情页无 PDF 链接')
                progress['done'][item['detail_url']] = {
                    'status': 'failed',
                    'error': 'no pdf link in detail page',
                }
                save_progress(progress)
                continue
            print(f'  PDF: {pdf_url}')

            # period 从 title 提取（如"2026年信息价1期"）
            m = re.search(r'(\d{4})年信息价(\d+)期', title or item['title'])
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
                        'vat_rate': r.get('vat_rate'),
                        'section': r['section'],
                        'category': r['category'],
                        'region': r.get('region', ''),
                        'city': r.get('city', ''),
                        'period': period,
                        'province': '内蒙古',
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
                    print(f'  by category: {dict(cat_counter)}')
                    print(f'  by city: {dict(city_counter)}')
                    print(f'  by section (TOP 10): {dict(sec_counter.most_common(10))}')
                    print('  sample (前 5):')
                    for d in docs[:5]:
                        print(f"    {d['no']:8s} | {d['city']:8s} | {d['section'][:18]:18s} | "
                              f"{d['breed'][:25]:25s} | {d['spec'][:25]:25s} | "
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

    print(f'\n[huhehaote] 全部完成: total_written={total_written}')


if __name__ == '__main__':
    main()