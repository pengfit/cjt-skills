"""威海工程造价信息 - 同步主程序

流程：
1. 抓通知公告列表（21 页 × 15 条，jpage POST 接口）
2. 过滤：含"主要工程建设材料信息价" + 未入库 + 目标年份
3. 对每期：
   a. 访问详情页 → 解析 PDF 下载链接（/module/download/downfile.jsp）
   b. 下载 PDF（302 → /attach/0/xxx.pdf）→ 本地临时文件
   c. 上传 MinIO
   d. pdfplumber 解析 → 长表（材料×规格×单位×信息价）
      * 每页一个分类（一、水泥、地材；二、钢材；...；十、市政材料）
      * 表头固定：序号|名称|规格|单位|单价（元）
      * 跨页续表：前一页的分类行号延续（如 Page 4 序号 30 是钢材的最后一条）
   e. bulk_index 到 ods_material_weihai_price（幂等 _id）
   f. 写进度（本地 JSON + ES progress 索引）
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
from bs4 import BeautifulSoup

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

from utils import (
    load_config, get_es_client, get_s3_client,
    ensure_bucket, ensure_ods_index, ensure_progress_index,
    fetch_list_page, fetch_html, download_file, upload_to_minio,
)

PROGRESS_FILE = os.path.join(os.path.dirname(SCRIPT_DIR), '.weihai_sync_progress.json')


# ─── 列表页解析 ────────────────────────────────────────────────────────────────
# 识别"主要工程建设材料信息价"条目（注意：2026 起改名，2019-2024 是"材料指导价格"，
# 2025 起逐步统一为"主要工程建设材料信息价"，按道友要求只入库 2026 年的）
PRICE_KEYWORDS = ['主要工程建设材料信息价', '部分工程建设材料指导价格']


def _is_price_entry(title):
    return any(kw in title for kw in PRICE_KEYWORDS)


def parse_list_xml(xml_text):
    """从 dataproxy.jsp XML 响应中提取列表项

    响应结构（XML）：
      <datastore>
        <totalrecord>301</totalrecord>
        <totalpage>21</totalpage>
        <recordset>
          <record><![CDATA[<li><span>2026-05-25</span><a href='/art/.../art_28584_6376026.html'
            title='威海市2026年1-3月份主要工程建设材料信息价'>...]]></record>
          ...
        </recordset>
      </datastore>

    每条 <record> 内 CDATA 包裹一段 <li>...</li>，包含日期 span + 链接 a。
    """
    soup = BeautifulSoup(xml_text, 'html.parser')
    items = []
    for rec in soup.find_all('record'):
        cdata_html = rec.get_text()  # CDATA 内容即 <li> HTML
        if not cdata_html:
            continue
        li_soup = BeautifulSoup(cdata_html, 'html.parser')
        li = li_soup.find('li')
        if not li:
            continue
        date_el = li.find('span')
        a = li.find('a')
        if not a:
            continue
        href = a.get('href', '')
        title = a.get('title', '') or a.get_text(strip=True)
        publish_date = date_el.get_text(strip=True) if date_el else ''
        items.append({
            'title': re.sub(r'\s+', ' ', title).strip(),
            'publish_date': publish_date,
            'detail_url': href,  # 相对路径，调用方 urljoin 到 base_url
        })
    return items


def fetch_all_periods(cfg):
    """抓取所有期（21 页 × 15 条，totalRecord=301）

    jpage 插件 groupSize=3，每次抓 3 页 = 45 条 + 1 头；共 7 次抓完。
    """
    site = cfg['site']
    total = site.get('list_total_record', 301)
    per_page = site['list_per_page']
    group_size = 3
    total_groups = (total + per_page * group_size - 1) // (per_page * group_size)
    all_items = []
    for page in range(1, total_groups + 1):
        xml = fetch_list_page(cfg, page)
        page_items = parse_list_xml(xml)
        print(f'  [list] group {page}/{total_groups}: {len(page_items)} 条')
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


# ─── 详情页解析 ────────────────────────────────────────────────────────────────
def parse_detail_page(html, base_url):
    """从详情页 HTML 提取 PDF 下载链接 + 标题

    威海详情页结构：
      <div class="top">
        <h1>威海市2026年1-3月份主要工程建设材料信息价</h1>
        ...
      </div>
      <p><a href="/module/download/downfile.jsp?classid=0&showname=...pdf&filename=...pdf">威海市...pdf</a></p>
    """
    soup = BeautifulSoup(html, 'html.parser')
    # 优先取 .top h1（避免匹配到面包屑 .bt_link=首页）
    title_el = soup.select_one('div.top h1, h1')
    title = title_el.get_text(strip=True) if title_el else ''
    if not title or title == '首页':
        # 兜底：meta ArticleTitle
        meta = soup.find('meta', attrs={'name': 'ArticleTitle'})
        if meta and meta.get('content'):
            title = meta['content']

    pdf_a = None
    for a in soup.select('a[href*="downfile.jsp"]'):
        href = a.get('href', '')
        if '.pdf' in href.lower():
            pdf_a = a
            break
    if not pdf_a:
        # 兜底：找所有含 .pdf 的 a
        for a in soup.select('a[href*=".pdf"]'):
            href = a.get('href', '')
            if '/attach/' in href or 'downfile' in href or 'old' in href.lower():
                pdf_a = a
                break
    if not pdf_a:
        return {'title': title, 'pdf_url': '', 'pdf_name': ''}

    href = pdf_a.get('href', '')
    pdf_url = urljoin(base_url, href)

    # 从 filename=xxx.pdf 提取真实文件名
    fn_match = re.search(r'filename=([^&"\']+)', href)
    if fn_match:
        from urllib.parse import unquote
        pdf_name = unquote(fn_match.group(1))
    else:
        pdf_name = pdf_a.get('download', '') or pdf_a.get_text(strip=True) or os.path.basename(pdf_url)
    return {'title': title, 'pdf_url': pdf_url, 'pdf_name': pdf_name}


def extract_period_from_title(title):
    """从详情页标题提取周期

    支持的命名格式：
      '威海市2026年1-3月份主要工程建设材料信息价'  → '2026.1-3月'
      '威海市2024年4-6月份部分工程建设材料指导价格' → '2024.4-6月'
      '威海市二○二四年7-9月份部分工程建设材料指导价格' → '2024.7-9月'
    """
    # 数字年
    m = re.search(r'(\d{4})年(\d{1,2})(?:-(\d{1,2}))?月', title)
    if m:
        year, m1, m2 = m.group(1), m.group(2), m.group(3)
        if m2:
            return f'{year}.{int(m1)}-{int(m2)}月'
        return f'{year}.{int(m1)}月'
    # 中文数字年（二○二四 = 2024，二〇二三 = 2023）
    cn_year_map = {
        '〇': 0, '○': 0, '零': 0, '一': 1, '二': 2, '三': 3, '四': 4,
        '五': 5, '六': 6, '七': 7, '八': 8, '九': 9,
    }
    cn_match = re.search(r'([〇○零一二三四五六七八九]{2,4})年(\d{1,2})(?:-(\d{1,2}))?月', title)
    if cn_match:
        cn_y = cn_match.group(1)
        try:
            year = int(''.join(str(cn_year_map[c]) for c in cn_y))
            m1, m2 = cn_match.group(2), cn_match.group(3)
            if m2:
                return f'{year}.{int(m1)}-{int(m2)}月'
            return f'{year}.{int(m1)}月'
        except (KeyError, ValueError):
            pass
    return ''


# ─── PDF 解析 ────────────────────────────────────────────────────────────────
def _parse_price(s):
    """从含中文符号/逗号的字符串中提取 float，失败返回 None"""
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


def _is_header_row(cells):
    """判断一行是否是 5 列表头：序号|名称|规格|单位|单价（元）

    威海 PDF 表头可能是：'序号' / '名 称'（带空格）/ '规 格' / '单 位' / '单价（元）' 等。
    """
    if not cells or len(cells) < 4:
        return False
    text = ' '.join(str(c or '').replace('\n', ' ').strip() for c in cells)
    text_compact = text.replace(' ', '').replace('\u3000', '')
    return ('序号' in text_compact
            and ('名称' in text_compact or '名' in text_compact)
            and ('规格' in text_compact or '规' in text_compact)
            and ('单价' in text_compact or '价' in text_compact))


def _is_category_row(cells):
    """判断一行是否是分类标题行：'一、水泥、地材'（5 列中第 1 列有值，其余为 None）

    威海 PDF 实际：['一、水泥、地材', None, None, None, None]
    """
    if not cells or len(cells) < 1:
        return False
    first = str(cells[0] or '').strip()
    if not first or '、' not in first:
        return False
    if first[0] not in '一二三四五六七八九十':
        return False
    # 其余列应基本为空
    rest_empty = all(not str(c or '').strip() for c in cells[1:])
    return rest_empty and len(first) < 20


def parse_pdf_tables(pdf_path, city):
    """解析 PDF → 长表 [(breed, spec, unit, price, category)]

    威海 PDF 结构：
      - 27~29 页，每页一个或多个分类（一、水泥、地材 / 二、钢材 / ... / 十、市政材料）
      - 表头固定：序号|名称|规格|单位|单价（元）
      - 跨页续表：前一页的分类序号延续
      - 信息价（不含税价），price 字段 = 不含税价；不存 tax_price

    容错：
      - 某些 PDF（如“附件2 公示版”）的分类行在 body text 中不在表里，
        本函数从每页 extract_text() 中主动扫描 "X、Y" 模式作为 category。
    """
    rows_out = []
    current_category = ''
    cat_pattern = re.compile(r'^([一二三四五六七八九十])、([一-鿿、·\d A-Za-z（）()]+)$')
    with pdfplumber.open(pdf_path) as pdf:
        for i, page in enumerate(pdf.pages):
            # 预扫该页文字，找分类行（“一、水泥、地材”等）
            page_text = page.extract_text() or ''
            for line in page_text.split('\n'):
                ls = line.strip()
                m = cat_pattern.match(ls)
                if m and len(ls) < 20:
                    current_category = ls
            # 再从表里抽数据
            tables = page.extract_tables() or []
            for tbl in tables:
                if not tbl or len(tbl) < 2:
                    continue
                for row in tbl:
                    cells = [str(c or '').replace('\n', ' ').strip() for c in row]
                    if not any(cells):
                        continue
                    # 分类标题行
                    if _is_category_row(cells):
                        current_category = cells[0]
                        continue
                    # 表头行
                    if _is_header_row(cells):
                        continue
                    # 数据行：标准 5 列
                    if len(cells) >= 5:
                        seq, breed, spec, unit, raw_price = cells[:5]
                        price = _parse_price(raw_price)
                    elif len(cells) == 4:
                        # 偶尔 pdfplumber 抽错列数：可能是 名称|规格|单位|单价
                        breed, spec, unit, raw_price = cells
                        price = _parse_price(raw_price)
                    else:
                        continue
                    if not breed and not spec:
                        continue
                    if price is None or price <= 0:
                        continue
                    rows_out.append({
                        'breed': breed,
                        'spec': spec,
                        'unit': unit,
                        'price': price,
                        'category': current_category,
                    })
    return rows_out


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
def _doc_id(period, breed, spec, unit, price):
    raw = f'{period}|{breed}|{spec}|{unit}|{price}'
    return hashlib.md5(raw.encode('utf-8')).hexdigest()


def bulk_index(es, index, docs):
    """幂等写入（按 _id upsert）"""
    if not docs:
        return 0, 0
    body = ''
    for d in docs:
        _id = _doc_id(d['period'], d['breed'], d['spec'], d['unit'], d['price'])
        body += json.dumps({'index': {'_index': index, '_id': _id}}, ensure_ascii=False) + '\n'
        body += json.dumps(d, ensure_ascii=False) + '\n'
    resp = es.bulk(body=body, refresh=False)
    if resp.get('errors'):
        errors = sum(1 for it in resp['items'] if 'error' in it.get('index', {}))
        return len(docs) - errors, errors
    return len(docs), 0


# ─── 主流程 ────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description='威海工程造价材料信息同步')
    parser.add_argument('--period', default='', help='指定周期（如 2026.1-3月）')
    parser.add_argument('--year', type=int, default=None, help='只入库指定年份（默认走 config.yml 的 default_year，0=不限制）')
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

    # 年份默认：config.yml 的 default_year（道友好 2026）
    if args.year is None:
        args.year = cfg.get('sync', {}).get('default_year', 0) or 0

    print(f'[weihai] ES: {es_host}')
    print(f'[weihai] MinIO: {cfg["minio"]["endpoint"]} / {cfg["minio"]["bucket"]}')
    print(f'[weihai] city={cfg.get("city", "威海")}  province={cfg.get("province", "山东")}  year_filter={args.year}')

    # 1. 抓所有期
    print('[weihai] 抓取通知公告列表（21 页 × 15 条）...')
    items = fetch_all_periods(cfg)
    print(f'[weihai] 共 {len(items)} 条通知')

    # 2. 过滤：材料价格相关条目
    price_items = [it for it in items if _is_price_entry(it['title'])]
    print(f'[weihai] 价目相关条目: {len(price_items)}')
    for it in price_items[:5]:
        print(f'  · {it["publish_date"]}  {it["title"]}')

    todo = []
    for it in price_items:
        if args.period and args.period not in it['title']:
            continue
        if args.year and f'{args.year}年' not in it['title']:
            continue
        if it['detail_url'] in progress['done'] and progress['done'][it['detail_url']].get('status') == 'ok':
            continue
        todo.append(it)

    if args.latest:
        todo = todo[:1]

    print(f'[weihai] 待处理 {len(todo)} 期')
    if not todo:
        print('[weihai] 无新数据')
        return

    # 3. 逐期处理
    city = cfg.get('city', '威海')
    province = cfg.get('province', '山东')
    base_url = cfg['site']['base_url']
    total_written = 0
    for idx, item in enumerate(todo, 1):
        print(f'\n[weihai] [{idx}/{len(todo)}] {item["title"]}  ({item["publish_date"]})')
        start = time.time()
        try:
            detail_url = urljoin(base_url, item['detail_url'])
            detail_html = fetch_html(
                detail_url,
                headers={'User-Agent': cfg['site']['user_agent']},
                timeout=cfg['site']['timeout_sec'],
            )
            detail = parse_detail_page(detail_html, base_url)
            if not detail['pdf_url']:
                raise ValueError('详情页未找到 PDF 链接')
            print(f'  PDF: {detail["pdf_url"]}')

            with tempfile.TemporaryDirectory() as tmpdir:
                local_pdf = os.path.join(tmpdir, 'source.pdf')
                download_file(
                    detail['pdf_url'],
                    local_pdf,
                    referer=detail_url,
                    timeout=120,
                )
                # 验证下载到的是 PDF
                if os.path.getsize(local_pdf) < 1024:
                    raise ValueError(f'PDF 太小（{os.path.getsize(local_pdf)} bytes），可能下载失败')

                period = extract_period_from_title(detail['title'] or item['title'])
                if not period:
                    raise ValueError(f'无法从标题推断周期: {detail["title"]}')
                print(f'  period: {period}')

                # minio key 形如 weihai-price/2026.1-3月/威海市2026年1-3月份主要工程建设材料信息价.pdf
                safe_pdf_name = re.sub(r'[\\/:*?"<>|]', '_', detail['pdf_name']) if detail['pdf_name'] else 'source.pdf'
                minio_key = f'{cfg["minio"]["prefix"]}/{period}/{safe_pdf_name}'
                if not args.dry_run:
                    upload_to_minio(s3, cfg['minio']['bucket'], minio_key, local_pdf)
                print(f'  minio: {minio_key}')

                pdf_rows = parse_pdf_tables(local_pdf, city)
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
                        'category': r['category'],
                        'city': city,
                        'province': province,
                        'update_date': item['publish_date'],
                        'create_time': now,
                        'source_pdf': minio_key,
                        'source_url': detail['pdf_url'],
                    }
                    docs.append(doc)

                if args.dry_run:
                    print(f'  [dry-run] 将写 {len(docs)} 条到 {cfg["es"]["ods_index"]}')
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
                        'detail_url': item['detail_url'],
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
            progress['done'][item['detail_url']] = {
                'publish_date': item['publish_date'],
                'detail_url': item['detail_url'],
                'status': 'failed',
                'error': str(e),
                'duration_sec': round(elapsed, 1),
            }
            save_progress(progress)

    print(f'\n[weihai] 全部完成: total_written={total_written}')


if __name__ == '__main__':
    main()
