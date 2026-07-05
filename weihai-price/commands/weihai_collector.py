"""weihai_collector.py - 威海默认同步路径（参考重庆 v0.9 collector 模式）

v1.0 (2026-07-04) ：威海 sync.py 用 SyncRunner 抽象基类重构，参考 chongqing_collector 设计：
- 工作单元形状：(period, item_dict) - item_dict 含 title/detail_url/publish_date/pdf_url
- _list_work_units()：抓通知公告列表 → 过滤 → 派生 period → 转 unit
- _process_one()：下载 PDF → 解析 → 写 ODS + 写 progress（同步 ES）
- _on_unit_done()：报告结果 + 保存本地进度

每期文档写入统一带 period_start / period_end / period_days 字段（道友要求 v1.0 强制）。
progress 文档同时带 run_id / last_updated（重庆 sync_progress 兼容 dashboard 显示）。

进度索引 _id 规则（与重庆一致）：f"{run_id}__{period}"，便于同 run_id 跨周期聚合。
"""
from __future__ import annotations

def _resolve_etl_root():
    """解析 gov-price-etl 项目根路径。

    优先级：
      1) 环境变量 GOV_PRICE_ETL_ROOT（部署/调试可显式覆盖）
      2) 自动反推：从本文件路径向上找 'gov-price-etl' 同级目录，
         不依赖硬编码的 workspace 名 / 目录深度。
      3) 兜底 fallback（cjt 子目录布局），让上层 log warning，不抛异常。
    """
    import os
    from pathlib import Path
    env = os.environ.get("GOV_PRICE_ETL_ROOT")
    if env and os.path.isdir(env):
        return env
    p = Path(__file__).resolve().parent
    for _ in range(6):
        candidate = p / "gov-price-etl"
        if candidate.is_dir():
            return str(candidate)
        p = p.parent
    return str(Path.home() / ".openclaw" / "workspace" / "cjt" / "skills" / "gov-price-etl")


import hashlib
import json
import os
import re
import sys
import tempfile
import time
from datetime import datetime
from typing import Optional, Tuple
from urllib.parse import urljoin, unquote

import pdfplumber
import requests
from bs4 import BeautifulSoup

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

from utils import (
    load_config, get_es_client, get_s3_client,
    ensure_bucket, ensure_ods_index, ensure_progress_index,
    fetch_list_page, fetch_html, download_file, upload_to_minio,
    is_price_entry, quarter_period_to_dates,
)

# 复用 gov_price_etl.collectors.base 的 SyncRunner 基类
_etl_root = _resolve_etl_root()
if os.path.isdir(_etl_root) and _etl_root not in sys.path:
    sys.path.insert(0, _etl_root)
from gov_price_etl.collectors.base import (
    LocalProgressStore,
    SyncRunner,
)


# ─────────────────────────────────────────────────────────────
# 解析辅助函数（从原 sync.py 抽出，便于复用 + 单测）
# ─────────────────────────────────────────────────────────────

def parse_list_xml(xml_text: str) -> list[dict]:
    """从 dataproxy.jsp XML 响应中提取列表项"""
    soup = BeautifulSoup(xml_text, 'html.parser')
    items = []
    for rec in soup.find_all('record'):
        cdata_html = rec.get_text()
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
            'detail_url': href,
        })
    return items


def fetch_all_periods(cfg: dict) -> list[dict]:
    """抓取所有通知（jpage groupSize=3，共 7 组）"""
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


def parse_detail_page(html: str, base_url: str) -> dict:
    """从详情页 HTML 提取 PDF 下载链接 + 标题"""
    soup = BeautifulSoup(html, 'html.parser')
    title_el = soup.select_one('div.top h1, h1')
    title = title_el.get_text(strip=True) if title_el else ''
    if not title or title == '首页':
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
        for a in soup.select('a[href*=".pdf"]'):
            href = a.get('href', '')
            if '/attach/' in href or 'downfile' in href or 'old' in href.lower():
                pdf_a = a
                break
    if not pdf_a:
        return {'title': title, 'pdf_url': '', 'pdf_name': ''}
    href = pdf_a.get('href', '')
    pdf_url = urljoin(base_url, href)
    fn_match = re.search(r'filename=([^&"\']+)', href)
    if fn_match:
        pdf_name = unquote(fn_match.group(1))
    else:
        pdf_name = pdf_a.get('download', '') or pdf_a.get_text(strip=True) or os.path.basename(pdf_url)
    return {'title': title, 'pdf_url': pdf_url, 'pdf_name': pdf_name}


def extract_period_from_title(title: str) -> str:
    """从详情页标题提取 period"""
    # 数字年
    m = re.search(r'(\d{4})年(\d{1,2})(?:-(\d{1,2}))?月', title)
    if m:
        year, m1, m2 = m.group(1), m.group(2), m.group(3)
        if m2:
            return f'{year}.{int(m1)}-{int(m2)}月'
        return f'{year}.{int(m1)}月'
    # 中文数字年
    cn_year_map = {'〇': 0, '○': 0, '零': 0, '一': 1, '二': 2, '三': 3, '四': 4,
                   '五': 5, '六': 6, '七': 7, '八': 8, '九': 9}
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


# ─────────────────────────────────────────────────────────────
# PDF 解析
# ─────────────────────────────────────────────────────────────

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


def _is_header_row(cells):
    if not cells or len(cells) < 4:
        return False
    text = ' '.join(str(c or '').replace('\n', ' ').strip() for c in cells)
    text_compact = text.replace(' ', '').replace('\u3000', '')
    return ('序号' in text_compact
            and ('名称' in text_compact or '名' in text_compact)
            and ('规格' in text_compact or '规' in text_compact)
            and ('单价' in text_compact or '价' in text_compact))


def _is_category_row(cells):
    if not cells or len(cells) < 1:
        return False
    first = str(cells[0] or '').strip()
    if not first or '、' not in first:
        return False
    if first[0] not in '一二三四五六七八九十':
        return False
    rest_empty = all(not str(c or '').strip() for c in cells[1:])
    return rest_empty and len(first) < 20


def parse_pdf_tables(pdf_path: str, city: str) -> list[dict]:
    """解析 PDF → 长表 [(breed, spec, unit, price, category)]"""
    rows_out = []
    current_category = ''
    cat_pattern = re.compile(r'^([一二三四五六七八九十])、([一-鿿、·\d A-Za-z（）()]+)$')
    with pdfplumber.open(pdf_path) as pdf:
        for i, page in enumerate(pdf.pages):
            page_text = page.extract_text() or ''
            for line in page_text.split('\n'):
                ls = line.strip()
                m = cat_pattern.match(ls)
                if m and len(ls) < 20:
                    current_category = ls
            tables = page.extract_tables() or []
            for tbl in tables:
                if not tbl or len(tbl) < 2:
                    continue
                for row in tbl:
                    cells = [str(c or '').replace('\n', ' ').strip() for c in row]
                    if not any(cells):
                        continue
                    if _is_category_row(cells):
                        current_category = cells[0]
                        continue
                    if _is_header_row(cells):
                        continue
                    if len(cells) >= 5:
                        seq, breed, spec, unit, raw_price = cells[:5]
                        price = _parse_price(raw_price)
                    elif len(cells) == 4:
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


# ─────────────────────────────────────────────────────────────
# ES 写入辅助
# ─────────────────────────────────────────────────────────────

def _doc_id(period: str, breed: str, spec: str, unit: str, price: float) -> str:
    raw = f'{period}|{breed}|{spec}|{unit}|{price}'
    return hashlib.md5(raw.encode('utf-8')).hexdigest()


def _bulk_index_ods(es, index: str, docs: list) -> Tuple[int, int]:
    """bulk 写入 ODS（幂等 by _id）"""
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


def _write_progress(es, progress_index: str, run_id: str, period: str,
                    docs_written: int, status: str, error_msg: str = '',
                    duration_sec: float = 0.0, detail_url: str = '',
                    pdf_url: str = '', minio_key: str = '',
                    publish_date: str = '', title: str = '') -> bool:
    """写 progress 文档（_id = run_id + period），含 period_start/period_end/period_days"""
    period_start, period_end, period_days = quarter_period_to_dates(period)
    percent = 100.0 if status in ('completed', 'error') else 0.0
    body = {
        'run_id': run_id,
        'period': period,
        'period_start': period_start,
        'period_end': period_end,
        'period_days': period_days,
        'publish_date': publish_date,
        'detail_url': detail_url,
        'pdf_url': pdf_url,
        'minio_key': minio_key,
        'docs_written': docs_written,
        'current_page': 1,
        'total_pages': 1,
        'percent': percent,
        'status': status,
        'duration_sec': round(duration_sec, 1),
        'last_updated': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        # dashboard 兼容：_period_sync_progress 和 _scrape_period_progress 都按 created_at 倒序排
        'created_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'error': error_msg or '',
        # dashboard county_field 兼容：威海用 county=威海（全市统一价）
        'county': '威海',
        'source': 'district',
        'city': '威海',
        'province': '山东',
    }
    _id = f'{run_id}__{period}'
    try:
        r = es.index(index=progress_index, id=_id, document=body, refresh=False)
        return r.get('result') in ('created', 'updated')
    except Exception as e:
        print(f'  [!] progress 写入失败: {e}')
        return False


# ─────────────────────────────────────────────────────────────
# WeihaiCollector
# ─────────────────────────────────────────────────────────────

class WeihaiCollector(SyncRunner):
    """威海工程造价材料采集器（v1.0 SyncRunner 化版本）。

    工作单元形状：(period, item_dict)
        period: '2026.1-3月'（业务期，从详情页标题解析）
        item_dict: 含 title / publish_date / detail_url / pdf_url 等

    与重庆区别：
    - 无浏览器操作，纯 HTTP 下载 PDF + pdfplumber 解析
    - 全市统一价，没有 county 维度
    - period 是季度（如 2026.1-3月），需要推算 period_start/end/days
    """

    def __init__(
        self,
        cfg: dict,
        run_id: str,
        year: int,
        period_filter: str = '',
        latest: bool = False,
    ):
        progress_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            '.weihai_sync_progress.json',
        )
        super().__init__(
            progress=LocalProgressStore(progress_path),
            es_host=cfg['es']['host'],
            es_index=cfg['es']['ods_index'],
            progress_index=cfg['es']['progress_index'],
        )
        self.cfg = cfg
        self.run_id = run_id
        self.year = year
        self.period_filter = period_filter
        self.latest = latest
        self.city = cfg.get('city', '威海')
        self.province = cfg.get('province', '山东')
        self.base_url = cfg['site']['base_url']
        # ES + S3 客户端（懒加载，首次 _process_one 时建）
        self._es = None
        self._s3 = None

    def _ensure_clients(self):
        """懒加载 ES + MinIO 客户端 + 索引创建"""
        if self._es is None:
            self._es = get_es_client(self.es_host)
            ensure_bucket(self._s3 if self._s3 else get_s3_client(self.cfg),
                          self.cfg['minio']['bucket'])
            ensure_ods_index(self._es, self.es_host, self.es_index)
            ensure_progress_index(self._es, self.progress_index)
        if self._s3 is None:
            self._s3 = get_s3_client(self.cfg)
            ensure_bucket(self._s3, self.cfg['minio']['bucket'])

    # ── SyncRunner 钩子实现 ──

    def _list_work_units(self) -> list:
        """抓列表 → 过滤 → 派生 period → 转 unit"""
        print(f'[weihai] 抓取通知公告列表...')
        items = fetch_all_periods(self.cfg)
        price_items = [it for it in items if is_price_entry(it['title'])]
        print(f'[weihai] 价目相关条目: {len(price_items)}')
        for it in price_items[:5]:
            print(f'  · {it["publish_date"]}  {it["title"]}')

        todo = []
        for it in price_items:
            if self.period_filter and self.period_filter not in it['title']:
                continue
            if self.year and f'{self.year}年' not in it['title']:
                continue
            period = extract_period_from_title(it['title'])
            if not period:
                continue
            todo.append((period, it))

        # 升序：先抓早的，再抓晚的（便于补齐 + 断点续传）
        todo.sort(key=lambda x: (x[0], x[1]['detail_url']))

        if self.latest:
            todo = todo[-1:] if todo else []

        # 去重（同一 period 可能多个 PDF：最终版 + 公示版）
        # 注意：这里不去重，让 _process_one 自己跑，_id 幂等保证数据不重复
        return todo

    def _process_one(self, unit) -> Tuple[int, str]:
        """处理单个工作单元：详情页 → 下载 PDF → 解析 → 写 ODS + progress

        Returns:
            (docs_count, status)，status ∈ {'completed', 'error'}。
        """
        period, item = unit
        self._ensure_clients()

        start = time.time()
        try:
            detail_url = urljoin(self.base_url, item['detail_url'])
            detail_html = fetch_html(
                detail_url,
                headers={'User-Agent': self.cfg['site']['user_agent']},
                timeout=self.cfg['site']['timeout_sec'],
            )
            detail = parse_detail_page(detail_html, self.base_url)
            if not detail['pdf_url']:
                raise ValueError('详情页未找到 PDF 链接')

            with tempfile.TemporaryDirectory() as tmpdir:
                local_pdf = os.path.join(tmpdir, 'source.pdf')
                download_file(
                    detail['pdf_url'],
                    local_pdf,
                    referer=detail_url,
                    timeout=120,
                )
                if os.path.getsize(local_pdf) < 1024:
                    raise ValueError(f'PDF 太小（{os.path.getsize(local_pdf)} bytes），可能下载失败')

                actual_period = extract_period_from_title(detail['title'] or item['title'])
                if not actual_period:
                    raise ValueError(f'无法从标题推断周期: {detail["title"]}')

                safe_pdf_name = re.sub(r'[\\/:*?"<>|]', '_', detail['pdf_name']) if detail['pdf_name'] else 'source.pdf'
                minio_key = f'{self.cfg["minio"]["prefix"]}/{actual_period}/{safe_pdf_name}'
                upload_to_minio(self._s3, self.cfg['minio']['bucket'], minio_key, local_pdf)

                pdf_rows = parse_pdf_tables(local_pdf, self.city)
                print(f'  [{actual_period}] parsed: {len(pdf_rows)} 行')

                now = datetime.now().isoformat(timespec='seconds')
                period_start, period_end, period_days = quarter_period_to_dates(actual_period)
                docs = []
                for r in pdf_rows:
                    doc = {
                        'period': actual_period,
                        'period_start': period_start,
                        'period_end': period_end,
                        'period_days': period_days,
                        'breed': r['breed'],
                        'spec': r['spec'],
                        'unit': r['unit'],
                        'price': r['price'],
                        'category': r['category'],
                        'city': self.city,
                        'province': self.province,
                        'update_date': item['publish_date'],
                        'create_time': now,
                        'source_pdf': minio_key,
                        'source_url': detail['pdf_url'],
                    }
                    docs.append(doc)

                ok, err = _bulk_index_ods(self._es, self.es_index, docs)
                elapsed = time.time() - start
                status = 'completed' if err == 0 and ok > 0 else ('partial' if ok > 0 else 'error')

                # 写 progress（统一字段）
                _write_progress(
                    self._es, self.progress_index,
                    run_id=self.run_id,
                    period=actual_period,
                    docs_written=ok,
                    status=status if status != 'partial' else 'completed',
                    error_msg='' if err == 0 else f'{err} docs failed',
                    duration_sec=elapsed,
                    detail_url=item['detail_url'],
                    pdf_url=detail['pdf_url'],
                    minio_key=minio_key,
                    publish_date=item['publish_date'],
                    title=item['title'],
                )

                return ok, ('completed' if ok > 0 else 'error')
        except Exception as e:
            elapsed = time.time() - start
            err_msg = str(e)
            print(f'  ✗ 失败: {err_msg}')
            # 失败也要写 progress（让 dashboard 知道有这期失败）
            try:
                _write_progress(
                    self._es, self.progress_index,
                    run_id=self.run_id,
                    period=period,
                    docs_written=0,
                    status='error',
                    error_msg=err_msg[:200],
                    duration_sec=elapsed,
                    detail_url=item['detail_url'],
                    publish_date=item['publish_date'],
                    title=item['title'],
                )
            except Exception:
                pass
            return 0, 'error'

    def _on_unit_done(self, unit, docs_count: int, status: str, error: str = '') -> None:
        """完成后：保存本地进度 + 控制台输出"""
        period, item = unit
        progress = self.progress.load()
        done_key = f'done__{period}'
        progress.setdefault(done_key, [])
        if item['detail_url'] not in progress[done_key]:
            progress[done_key].append(item['detail_url'])
        self.progress.save(progress)

        icon = '✓' if status == 'completed' else '✗'
        print(f'  [{icon}] {period}  {item["title"]} → {docs_count} docs ({status})')

    def _on_unit_start(self, unit) -> None:
        period, item = unit
        print(f'[weihai] >>> {period}  {item["title"]}')

    def _compute_unit_key(self, unit) -> str:
        """本地进度 key：f'done__{period}__{detail_url}'"""
        period, item = unit
        return f'done__{period}__{item["detail_url"]}'


# ─────────────────────────────────────────────────────────────
# 工厂方法
# ─────────────────────────────────────────────────────────────

def make_collector(cfg_path: str, year: int, run_id: str,
                   period_filter: str = '', latest: bool = False) -> WeihaiCollector:
    """从 config.yml 构造 WeihaiCollector。

    用法（sync.py 默认路径）：
        cfg = load_config(cfg_path)
        collector = make_collector(cfg_path, year=2026, run_id='wh_2026_20260704')
        result = collector.run(reset=False)
    """
    cfg = load_config()
    return WeihaiCollector(
        cfg=cfg,
        run_id=run_id,
        year=year,
        period_filter=period_filter,
        latest=latest,
    )
