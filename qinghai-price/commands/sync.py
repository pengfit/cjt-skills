"""青海建设工程市场价格信息 - 同步主程序（v0.8 SyncRunner 抽象基类化, 2026-07-03）

v0.8 改造：
  - 默认走 QinghaiCollector（SyncRunner 化版本，commands/qinghai_collector.py）
  - --legacy 走原 v0.x cmd_legacy_sync（逃生通道）
  - 内置工具函数（fetch_all_periods / parse_pdf / parse_list_page / ...）保留，
    供 collector / legacy / preview 复用，不再被 main() 直接调用
  - v0.8 字段扩展：doc 中新增 period_start / period_end / period_days

参考 chongqing v0.8 试点（chongqing_collector.py）+ henan v0.8（henan_collector.py）
+ huhehaote v0.8（huhehaote_collector.py）——
P2 阶段（2026-07-02 启动）的核心目标：把通用基础设施（SIGINT / 进度 / 汇总）抽到
SyncRunner 基类，各 city 保留站点特化逻辑。

PDF 结构（268 页，双月合刊）：
- 5 列基础表：序号 / 材料名称 / 规格型号 / 单位 / 单价
- 6 列双价表：序号 / 材料名称 / 规格型号 / 单位 / 除税价 / 含税价
- 7-10 列扩展表（型号/强度/牌号 等）：简单抽取关键列
- 部分页是"厂商名录 + 部分产品报价"格式（含联系人、地址）
- 价格 = 含税价为主，price=除税价（反推），tax_price=含税价
- 增值税率 13% (vat_rate)
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
from urllib.parse import urljoin, urlparse

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

PROGRESS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '.qinghai_sync_progress.json')

VAT_RATE = 0.13   # 建设工程材料增值税率


# ─── 列表页解析 ──────────────────────────────────────────────────────────────
def parse_list_page(html, base_url):
    """从列表页 HTML 提取每期信息（li.doc_list > a[href$=pdf]）"""
    soup = BeautifulSoup(html, 'html.parser')
    items = []
    for a in soup.select('li a[href$=".pdf"]'):
        href = a.get('href', '')
        title = a.get('title', '') or a.get_text(strip=True)
        # 找同 li 下的日期 span
        li = a.find_parent('li')
        date_el = li.select_one('.listdate') if li else None
        publish_date = date_el.get_text(strip=True) if date_el else ''
        items.append({
            'title': title.strip(),
            'publish_date': publish_date,
            'pdf_url': urljoin(base_url, href),
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
            url = base + site['list_page_pattern'].format(n=page - 1)
        try:
            html = fetch_html(url, headers=headers, timeout=site['timeout_sec'])
        except Exception as e:
            print(f'  [list] page {page}: 失败 {e}')
            break
        page_items = parse_list_page(html, base)
        print(f'  [list] page {page}: {len(page_items)} 期')
        all_items.extend(page_items)
    # 去重（按 pdf_url）
    seen = set()
    uniq = []
    for it in all_items:
        if it['pdf_url'] in seen:
            continue
        seen.add(it['pdf_url'])
        uniq.append(it)
    return uniq


def pdf_basename(pdf_url: str) -> str:
    """从 PDF URL 提取 basename（含 .pdf）"""
    from urllib.parse import urlparse
    return os.path.basename(urlparse(pdf_url).path) or 'source.pdf'


# ─── PDF 解析 ────────────────────────────────────────────────────────────────
def _is_price_cell(s):
    """判断是否是数字价格（排除百分号、说明文字等）"""
    if s is None:
        return False
    s = str(s).strip()
    if not s:
        return False
    if '%' in s:
        return False
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
    if not row or len(row) < n_cols:
        return False
    seq = str(row[0] or '').strip()
    if not seq or not seq.isdigit():
        return False
    return True


# 章节标题识别（页眉 "■木、竹材及制品"、"黑色及有色金属"、"水泥、砖瓦灰砂石及混凝土制品" 等）
SECTION_KEYWORDS = [
    '黑色及有色金属',
    '水泥、砖瓦灰砂石及混凝土制品',
    '木、竹材及制品',
    '玻璃、陶瓷及面砖',
    '装饰石材及地板',
    '墙面、天蓬装饰及屋面材料',
    '门窗制品及门窗五金',
    '涂料及防腐防水材料',
    '油品、化工原料及橡胶制品',
    '电线、电缆及电工器材',
    '五金制品',
    '绿色建材、装配式部品部件',
    '周转材料及五金工具',
]


def _detect_section(text: str, default: str = '') -> str:
    """从页眉文本识别章节（一级类目）"""
    if not text:
        return default
    for kw in SECTION_KEYWORDS:
        if kw in text:
            return kw
    return default


def parse_pdf(pdf_path):
    """解析 PDF → 长表 [{...}]

    字段：no, breed, spec, unit, price, tax_price, remark, section, category
    """
    out = []
    current_section = ''
    seen_sections = set()

    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ''
            if not text:
                continue

            # 跳过目录/封面
            stripped = text.strip()[:30]
            if '目 录' in stripped or '目录' in stripped or ('青海建设工程市场价格信息' in stripped.split('\n')[0] and '部分产品报价' not in text[:500] and len(text) < 300):
                continue

            # 章节识别（页眉）
            section = _detect_section(text)
            if section:
                current_section = section
                seen_sections.add(section)

            tables = page.extract_tables() or []
            for tbl in tables:
                if not tbl or len(tbl) < 2:
                    continue
                n_cols = len(tbl[0]) if tbl[0] else 0
                if n_cols < 5:
                    continue

                # 找数据起始行
                header_idx = None
                for i, row in enumerate(tbl[:5]):
                    if row:
                        cells = ' '.join(str(c or '') for c in row)
                        if '序号' in cells and ('材料' in cells or '产品' in cells or '名称' in cells):
                            header_idx = i
                            break

                data_start = 0
                if header_idx is not None:
                    data_start = header_idx + 1
                    if data_start < len(tbl):
                        row = tbl[data_start]
                        if row and (row[0] is None or not str(row[0]).strip().isdigit()):
                            nones = sum(1 for c in row if c is None or str(c).strip() == '')
                            if nones >= 2:
                                data_start += 1
                else:
                    first_seq = str(tbl[0][0] or '').strip() if tbl[0] else ''
                    if not first_seq.isdigit() or n_cols < 5 or n_cols > 10:
                        continue

                if data_start >= len(tbl):
                    continue

                for row in tbl[data_start:]:
                    if not row or len(row) < n_cols:
                        continue
                    if all(c is None or str(c).strip() == '' for c in row):
                        continue
                    seq = str(row[0] or '').strip()
                    if not seq.isdigit():
                        continue

                    cells = [str(c or '').strip() for c in row]

                    # ── 5 列：序号 / 材料 / 规格 / 单位 / 单价 ──
                    if n_cols == 5:
                        breed, spec, unit, raw_price = cells[1], cells[2], cells[3], cells[4]
                        price = _parse_price(raw_price)
                        if price is None:
                            continue
                        tax_price = price
                        price_excl = round(price / (1 + VAT_RATE), 2)
                        out.append({
                            'no': seq, 'breed': breed, 'spec': spec, 'unit': unit,
                            'price': price_excl, 'tax_price': tax_price,
                            'remark': '', 'section': current_section,
                            'price_kind': '含税',
                        })

                    # ── 6 列：序号 / 材料 / 规格 / 单位 / 除税价 / 含税价 ──
                    elif n_cols == 6:
                        breed, spec, unit, raw_excl, raw_incl = cells[1], cells[2], cells[3], cells[4], cells[5]
                        p_excl = _parse_price(raw_excl)
                        p_incl = _parse_price(raw_incl)
                        if p_excl is None and p_incl is None:
                            continue
                        if p_excl is not None:
                            price_excl = p_excl
                            tax_price = p_incl if p_incl is not None else round(p_excl * (1 + VAT_RATE), 2)
                        else:
                            price_excl = round(p_incl / (1 + VAT_RATE), 2)
                            tax_price = p_incl
                        out.append({
                            'no': seq, 'breed': breed, 'spec': spec, 'unit': unit,
                            'price': price_excl, 'tax_price': tax_price,
                            'remark': '', 'section': current_section,
                            'price_kind': '双价',
                        })

                    # ── 7-10 列扩展表 ──
                    elif 7 <= n_cols <= 10:
                        last_col = cells[n_cols - 1]
                        second_last = cells[n_cols - 2]
                        price = _parse_price(last_col)
                        if price is None:
                            price = _parse_price(second_last)
                            if price is not None:
                                unit = cells[n_cols - 3]
                            else:
                                continue
                        else:
                            unit = second_last

                        breed = cells[1] if len(cells) > 1 else ''
                        spec_parts = [c for c in cells[2:n_cols - 2] if c]
                        spec = ' | '.join(spec_parts)
                        tax_price = price
                        price_excl = round(price / (1 + VAT_RATE), 2)
                        out.append({
                            'no': seq, 'breed': breed, 'spec': spec, 'unit': unit,
                            'price': price_excl, 'tax_price': tax_price,
                            'remark': '', 'section': current_section,
                            'price_kind': '含税',
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
        json.dump(prog, prog, ensure_ascii=False, indent=2) if False else json.dump(prog, f, ensure_ascii=False, indent=2)


# ─── 入库 ────────────────────────────────────────────────────────────────────
def _doc_id(period, section, no, breed, spec):
    raw = f'{period}|{section}|{no}|{breed}|{spec}'
    return hashlib.md5(raw.encode('utf-8')).hexdigest()


def bulk_index(es, index, docs):
    """幂等写入（按 _id upsert）"""
    if not docs:
        return 0, 0
    body = ''
    for d in docs:
        _id = _doc_id(d['period'], d['section'], d['no'], d['breed'], d['spec'])
        body += json.dumps({'index': {'_index': index, '_id': _id}}, ensure_ascii=False) + '\n'
        body += json.dumps(d, ensure_ascii=False) + '\n'
    resp = es.bulk(body=body, refresh=False)
    if resp.get('errors'):
        errors = sum(1 for it in resp['items'] if 'error' in it.get('index', {}))
        return len(docs) - errors, errors
    return len(docs), 0


# ─── 主流程（v0.x 兼容路径） ────────────────────────────────────────────────
def cmd_legacy_sync(args):
    """v0.x 原 main 流程（逃生通道，仅在 --legacy 时调用）。

    与原 v0.x 行为等价：
      - 抓列表 → 过滤 → 下载 PDF → MinIO → 解析 → bulk_index → 进度
      - v0.8 字段扩展：doc 中也补 period_start / period_end / period_days
        （通过 qinghai_collector.parse_period_window 复用解析逻辑）
    """
    # v0.8 字段扩展：复用 collector 的窗口解析
    from qinghai_collector import parse_period_window

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

    print(f'[qinghai v0.x legacy] ES: {es_host}')
    print(f'[qinghai v0.x legacy] MinIO: {cfg["minio"]["endpoint"]} / {cfg["minio"]["bucket"]}')
    print(f'[qinghai v0.x legacy] journal_keyword: {cfg.get("journal_keyword", "")}')

    print('[qinghai v0.x legacy] 抓取列表...')
    items = fetch_all_periods(cfg)
    print(f'[qinghai v0.x legacy] 共 {len(items)} 期')

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
        if it['pdf_url'] in progress['done'] and progress['done'][it['pdf_url']].get('status') == 'ok':
            continue
        todo.append(it)

    if args.latest:
        todo = todo[:1]

    print(f'[qinghai v0.x legacy] 待处理 {len(todo)} 期')
    if not todo:
        print('[qinghai v0.x legacy] 无新数据')
        return

    total_written = 0
    for idx, item in enumerate(todo, 1):
        win = parse_period_window(item['title'])
        period = win['period'] or item['title'][:30]
        print(f'\n[qinghai v0.x legacy] [{idx}/{len(todo)}] {item["title"]}  ({item["publish_date"]})')
        print(f'  period: {period}  {win["period_start"]}~{win["period_end"]}  ({win["period_days"]}天)')
        start = time.time()
        try:
            basename = pdf_basename(item['pdf_url'])
            minio_key = f'{cfg["minio"]["prefix"]}/{period}/{basename}'

            with tempfile.TemporaryDirectory() as tmpdir:
                local_pdf = os.path.join(tmpdir, 'source.pdf')
                # v0.8.1：青海政府站大文件（~95-275MB）易断流，加 3 次重试
                ok_dl = False
                last_err = None
                for attempt in range(3):
                    try:
                        download_file(item['pdf_url'], local_pdf, timeout=600)
                        ok_dl = True
                        break
                    except Exception as e:
                        last_err = e
                        print(f"  ⚠ 下载失败(尝试 {attempt + 1}/3): {e}")
                        time.sleep(2 + attempt * 2)
                if not ok_dl:
                    raise RuntimeError(f'下载 PDF 最终失败: {last_err}')

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
                        'section': r.get('section', ''),
                        'category': r.get('section', '').split('、')[0] if r.get('section') else '',
                        'period': period,
                        # v0.8 字段扩展
                        'period_start': win['period_start'],
                        'period_end': win['period_end'],
                        'period_days': win['period_days'],
                        'province': '青海',
                        'city': '青海',
                        'price_kind': r.get('price_kind', ''),
                        'update_date': item['publish_date'],
                        'create_time': now,
                        'source_pdf': minio_key,
                        'source_url': item['pdf_url'],
                    })

                if args.dry_run:
                    print(f'  [dry-run] 将写 {len(docs)} 条到 {cfg["es"]["ods_index"]}')
                    from collections import Counter
                    sec_counter = Counter(d['section'] for d in docs)
                    print(f'  by section: {dict(sec_counter)}')
                    print('  sample (前 3):')
                    for d in docs[:3]:
                        print(f"    {d['no']:5s} | {d['section'][:18]:18s} | {d['breed'][:25]:25s} | {d['spec'][:30]:30s} | {d['unit']:6s} = {d['price']} (含税 {d['tax_price']})")
                    ok = len(docs)
                    err = 0
                else:
                    ok, err = bulk_index(es, cfg['es']['ods_index'], docs)
                    print(f'  bulk: ok={ok}, err={err}')

                elapsed = time.time() - start
                progress['done'][item['pdf_url']] = {
                    'period': period,
                    'period_start': win['period_start'],
                    'period_end': win['period_end'],
                    'period_days': win['period_days'],
                    'publish_date': item['publish_date'],
                    'pdf_url': item['pdf_url'],
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
                        'period_start': win['period_start'],
                        'period_end': win['period_end'],
                        'period_days': win['period_days'],
                        'publish_date': item['publish_date'],
                        'pdf_url': item['pdf_url'],
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
            progress['done'][item['pdf_url']] = {
                'publish_date': item['publish_date'],
                'pdf_url': item['pdf_url'],
                'status': 'failed',
                'error': str(e),
                'duration_sec': round(elapsed, 1),
            }
            save_progress(progress)

    print(f'\n[qinghai v0.x legacy] 全部完成: total_written={total_written}')


# ─── CLI 入口（v0.8） ──────────────────────────────────────────────────────
def main():
    """v0.8 CLI 入口：默认走 QinghaiCollector（SyncRunner 化），--legacy 走 v0.x。

    字段扩展（v0.8）：doc 中新增 period_start / period_end / period_days。
    """
    parser = argparse.ArgumentParser(
        description='青海建设工程材料价格同步（v0.8 SyncRunner 化）',
    )
    parser.add_argument('--period', default='', help='指定周期（如"2026年第1—2期"）')
    parser.add_argument('--year', type=int, default=datetime.now().year,
                        help='只入库指定年份的期（默认本年，0=不限制）')
    parser.add_argument('--exclude-period', default='', help='排除指定周期')
    parser.add_argument('--all', action='store_true', help='同步所有未入仓的期')
    parser.add_argument('--reset', action='store_true', help='重置进度')
    parser.add_argument('--dry-run', action='store_true', help='预览，不写入（仅 legacy 支持）')
    parser.add_argument('--latest', action='store_true', help='只同步最新一期')
    parser.add_argument('--run-id', default='', help='指定 run_id（默认自动生成）')
    parser.add_argument('--legacy', action='store_true',
                        help='v0.x 兼容：走原 main 流程。默认走 Collector（推荐）。')
    parser.add_argument('--max-units', type=int, default=None,
                        help='Collector 路径：只跑前 N 个工作单元（验证用）')
    args = parser.parse_args()

    cfg_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        'config.yml',
    )

    if args.legacy:
        # v0.x 兼容路径
        print('[v0.x 兼容路径] cmd_legacy_sync 启动')
        print(f'  period={args.period}, year={args.year}, latest={args.latest}, dry-run={args.dry_run}')
        cmd_legacy_sync(args)
        return

    # 默认路径：QinghaiCollector（v0.8 SyncRunner 抽象基类）
    from qinghai_collector import make_collector
    run_id = args.run_id or f"qinghai_run_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    print('[Collector 路径 v0.8] QinghaiCollector 启动')
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
