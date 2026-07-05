"""xian_collector.py - 西安默认同步路径（v0.8 SyncRunner 抽象基类化, 2026-07-04）

将 xian v0.6 sync.py 主流程用 gov_price_etl.collectors.base.SyncRunner 重构，
参考 chongqing v0.8 试点（chongqing_collector.py）+ huhehaote v0.8（huhehaote_collector.py）。

v0.8 改造要点：
  1. SyncRunner 抽象基类化
     - 继承 SyncRunner
     - 重写 _list_work_units() → list[dict]，每 dict 含 period 窗口字段
     - 重写 _process_one() → 翻页抓 + 解析 + bulk_index
     - 重写 _on_unit_done() → 写 ES progress + 本地进度
     - 重写 _compute_unit_key() → f"{county}@{period}"（兼容旧 ProgressStore key 形状）

  2. period 窗口字段（道友要求）
     - 源站按"造价信息表月份"组织，每期有 gkbh 周期 ID
     - period='YYYY-MM' → period_start/end/days 简单从月末日推算
       period_start = YYYY-MM-01
       period_end   = YYYY-MM-{monthrange(year,m)[1]:02d}
       period_days  = monthrange(year,m)[1]

  3. ODS / Progress mapping 标准化
     - 委托到 gov_price_etl.mappings.build_ods_mapping / build_progress_mapping
     - city_extension = {'gkbh': keyword} （xian 源站特有）
     - 自动含 period_start / period_end / period_days（base_fields 已声明）

  4. 保留站点特化逻辑
     - 复用 utils.SiteSession（ASP.NET POST + ViewState）
     - 复用 utils.parse_* 全部解析函数

unit 形状：
    {
        'county':       '阎良区',
        'period':       '2026-01',
        'gkbh':         '0000000595',
        'period_start': '2026-01-01',
        'period_end':   '2026-01-31',
        'period_days':  31,
    }
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


import calendar
import hashlib
import json
import os
import sys
import time
from datetime import datetime
from typing import Optional

# ── ETL 公共依赖 ──
_ETL_PROJECT_ROOT = _resolve_etl_root()
if _ETL_PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _ETL_PROJECT_ROOT)

from gov_price_etl.collectors.base import (
    LocalProgressStore,
    SyncRunner,
)

# 复用 xian v0.6 的工具函数（SiteSession / 解析 / 写入）
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)
import utils as _legacy  # SiteSession, parse_*, normalize_period, COUNTY_CODES

import requests
from requests.packages.urllib3.exceptions import InsecureRequestWarning
requests.packages.urllib3.disable_warnings(InsecureRequestWarning)


# ─────────────────────────────────────────────────────────────
# period 窗口解析（v0.8 新增）
# ─────────────────────────────────────────────────────────────

def parse_period_window(period: str) -> dict:
    """'2026-01' / '2026年01月' / '2026-1' → period 窗口字段

    解析规则：
      1. 用 utils.normalize_period 标准化为 'YYYY-MM'
      2. period_start = 当月 1 日
      3. period_end   = 当月最后一日（calendar.monthrange）
      4. period_days  = monthrange(year, month)[1]
    """
    p = _legacy.normalize_period(period)
    if not p or '-' not in p:
        return _empty_window(p)

    try:
        y, m = p.split('-')
        y, m = int(y), int(m)
        if not (1 <= m <= 12):
            return _empty_window(p)
    except ValueError:
        return _empty_window(p)

    last_day = calendar.monthrange(y, m)[1]
    return {
        'period': p,
        'period_start': f'{y:04d}-{m:02d}-01',
        'period_end':   f'{y:04d}-{m:02d}-{last_day:02d}',
        'period_days':  last_day,
    }


def _empty_window(period: str = '') -> dict:
    return {
        'period': period,
        'period_start': '',
        'period_end': '',
        'period_days': 0,
    }


# ─────────────────────────────────────────────────────────────
# XianCollector - xian v0.6 sync.py 的 SyncRunner 化版本
# ─────────────────────────────────────────────────────────────

class XianCollector(SyncRunner):
    """西安工程造价材料采集器（v0.8 SyncRunner 化, 2026-07-04）。

    工作单元形状：dict（见模块顶部注释）。
    业务期：每个区县 × 每月一份"造价信息表"（gkbh 周期 ID）。
    翻页：ASP.NET POST + ViewState（复用 v0.6 utils.SiteSession）。
    """

    def __init__(
        self,
        cfg: dict,
        run_id: str,
        counties: Optional[list[str]] = None,
        periods: Optional[list[str]] = None,   # YYYY-MM 列表
        list_periods_only: bool = False,
        skip_progress: bool = False,
    ):
        progress_path = os.path.join(
            os.path.dirname(_SCRIPT_DIR),
            '.xian_sync_progress.json',
        )
        super().__init__(
            progress=LocalProgressStore(progress_path),
            es_host=cfg['es']['host'],
            es_index=cfg['es']['index'],
            progress_index=cfg['es']['progress_index'],
        )
        self.cfg = cfg
        self.run_id = run_id
        self.counties = counties or cfg['site']['counties']
        self.periods = periods or []
        self.list_periods_only = list_periods_only
        self.skip_progress = skip_progress
        # 懒加载 ES 客户端（avoids instantiate when not needed）
        self.es = None
        self._session_cache: dict[str, _legacy.SiteSession] = {}

    # ── SyncRunner 钩子实现 ──

    def _list_work_units(self) -> list[dict]:
        """根据 counties × periods 拼装工作单元。

        1. 列出每个区县每年的可用 period（用 SiteSession.list_periods）
        2. 交集用户传入的 periods 列表（如 ['2026-01','2026-02']）
        3. 解析每个 period 的 gkbh + 窗口字段
        4. 排除本地已 done
        """
        sess = _legacy.SiteSession(max_retries=2, timeout=15)
        all_periods_needed = set(self.periods)

        # 探测需要的年份（从 periods 抽 year）
        years_needed = set()
        for p in self.periods:
            p_norm = _legacy.normalize_period(p)
            if '-' in p_norm:
                years_needed.add(int(p_norm.split('-')[0]))

        # 缓存：(county, year) → list_periods 结果
        county_year_periods: dict[tuple[str, int], list[dict]] = {}
        for county in self.counties:
            for y in years_needed:
                ps = sess.list_periods(county, y)
                county_year_periods[(county, y)] = ps

        units = []
        prog = self.progress.load()
        # 兼容两种进度格式：
        #   1. 平铺：prog[key] = {...}   （SyncRunner 期望）
        #   2. 嵌套：prog['done'][key] = {...}（v0.8 首次实装时的格式）
        done_map = {}
        if 'done' in prog and isinstance(prog['done'], dict):
            done_map.update(prog['done'])
        for k, v in prog.items():
            if k in ('done', 'saved_at'):
                continue
            if isinstance(v, dict):
                done_map[k] = v

        for county in self.counties:
            for period in sorted(all_periods_needed):
                p_norm = _legacy.normalize_period(period)
                y = int(p_norm.split('-')[0])
                ps = county_year_periods.get((county, y), [])
                gkbh = ''
                for p in ps:
                    if p.get('period') == p_norm:
                        gkbh = p.get('id', '')
                        break
                if not gkbh:
                    print(f"  [!] {county} {p_norm}: 源站未找到 gkbh，跳过")
                    continue

                win = parse_period_window(p_norm)
                unit_key = f"{county}@{win['period']}"
                if unit_key in done_map:
                    # 跳过已完成单元（兼容平铺进度）
                    continue

                unit = {
                    'county':       county,
                    'period':       win['period'],
                    'gkbh':         gkbh,
                    'period_start': win['period_start'],
                    'period_end':   win['period_end'],
                    'period_days':  win['period_days'],
                }
                units.append(unit)

        return units

    def _process_one(self, unit: dict) -> tuple[int, str]:
        """处理单个 (county, period) 工作单元：翻页抓 + 解析 + bulk_index。

        Returns:
            (docs_count, status)，status ∈ {'completed', 'error'}。
        """
        county = unit['county']
        period = unit['period']
        gkbh = unit['gkbh']

        # 懒加载 ES 客户端 + 创建索引
        if self.es is None:
            from elasticsearch import Elasticsearch
            self.es = Elasticsearch(self.es_host, request_timeout=30, verify_certs=False)
            self._ensure_indices()

        sess = self._session_cache.get(county) or _legacy.SiteSession(max_retries=5, timeout=60)
        self._session_cache[county] = sess

        # 1. 抓首页
        html = sess.fetch(county, page=1, gkbh=gkbh)
        if not html:
            print(f"  ✗ {county} {period}: 第1页抓取失败")
            return 0, 'error'

        page_county = _legacy.parse_county(html)
        page_published_at = _legacy.parse_page_date(html) or ''
        total_records = _legacy.parse_total_records(html)
        total_pages = (total_records + 9) // 10 if total_records > 0 else 1

        all_docs = []
        all_rows = _legacy.parse_table_rows(html)
        if all_rows:
            page_docs = [
                _make_doc(r, county, page_published_at, period, gkbh, unit)
                for r in all_rows
            ]
            all_docs.extend(page_docs)
            self._on_page_progress(unit, page=1, total_pages=total_pages,
                                    rows=len(all_rows), docs=len(page_docs),
                                    update_date=page_published_at)

        # 2. 翻页循环
        consecutive_empty = 0
        for page in range(2, total_pages + 1):
            html = sess.fetch(county, page, gkbh=gkbh)
            if not html:
                print(f"  ✗ {county} {period}: 页 {page} 抓取失败")
                break

            page_published_at = _legacy.parse_page_date(html) or ''
            rows = _legacy.parse_table_rows(html)

            if not rows:
                consecutive_empty += 1
                if consecutive_empty >= 3:
                    print(f"  [连续3页空，停止]")
                    break
                continue
            consecutive_empty = 0

            page_docs = [
                _make_doc(r, county, page_published_at, period, gkbh, unit)
                for r in rows
            ]
            all_docs.extend(page_docs)
            self._on_page_progress(unit, page=page, total_pages=total_pages,
                                    rows=len(rows), docs=len(page_docs),
                                    update_date=page_published_at)
            time.sleep(0.5)  # 礼貌延时

        if not all_docs:
            print(f"  [warn] {county} {period}: 解析到 0 条")
            return 0, 'completed'

        # 3. bulk_index
        ok, err = self._bulk_index(all_docs)
        if err > 0:
            print(f"  ⚠ bulk 部分失败: ok={ok}, err={err}")
        return ok, ('completed' if ok > 0 else 'error')

    def _on_unit_done(self, unit: dict, docs_count: int, status: str, error: str = '') -> None:
        """完成后：写 ES progress + 本地进度。"""
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        # 1. ES progress（含 period 窗口字段 + run_id + county）
        if self.es is not None and not self.skip_progress:
            try:
                doc_id = f"{self.run_id}_{unit['county']}_{unit['period']}"
                self.es.index(index=self.progress_index, id=doc_id, body={
                    'run_id':       self.run_id,
                    'county':       unit['county'],
                    'period':       unit['period'],
                    'period_start': unit['period_start'],
                    'period_end':   unit['period_end'],
                    'period_days':  unit['period_days'],
                    'gkbh':         unit['gkbh'],
                    'docs_written': docs_count,
                    'status':       'ok' if status == 'completed' else 'error',
                    'error':        error,
                    'created_at':   now,
                })
            except Exception as e:
                print(f"  ⚠ 写 ES progress 失败: {e}")

        # 2. 本地进度（兼容旧 ProgressStore key 形状）
        prog = self.progress.load()
        key = f"{unit['county']}@{unit['period']}"
        prog[key] = {
            'county':       unit['county'],
            'period':       unit['period'],
            'gkbh':         unit['gkbh'],
            'period_start': unit['period_start'],
            'period_end':   unit['period_end'],
            'period_days':  unit['period_days'],
            'docs_written': docs_count,
            'status':       'ok' if status == 'completed' else 'error',
            'error':        error,
            'saved_at':     now,
        }
        self.progress.save(prog)

        icon = '✓' if status == 'completed' else '✗'
        print(
            f"  [{icon}] {unit['county']} {unit['period']} "
            f"{unit['period_start']}~{unit['period_end']} "
            f"({unit['period_days']}天) → {docs_count} docs"
        )

    def _compute_unit_key(self, unit: dict) -> str:
        """本地进度 key = f"{county}@{period}"（与旧 ProgressStore 兼容）。"""
        return f"{unit['county']}@{unit['period']}"

    # ── 私有方法 ──

    def _on_page_progress(self, unit: dict, page: int, total_pages: int,
                           rows: int, docs: int, update_date: str) -> None:
        """单页进度回调（打印 + 可选 ES 写入）。"""
        pct = page / total_pages * 100 if total_pages > 0 else 0
        print(
            f"  [{unit['county']} {unit['period']}] 页 {page}/{total_pages} "
            f"rows={rows} docs={docs} ({pct:.0f}%) update={update_date}"
        )

    def _ensure_indices(self) -> None:
        """确保 ODS + progress 索引存在。

        v0.8 (2026-07-04) ：委托到 gov_price_etl.mappings.build_ods_mapping。
        city_extension = {'gkbh': keyword}（xian 源站周期 ID）。
        """
        from gov_price_etl.mappings import (
            build_ods_mapping, build_progress_mapping,
        )
        if not self.es.indices.exists(index=self.es_index):
            mapping = build_ods_mapping(city_extension={
                'gkbh': {'type': 'keyword'},
            })
            self.es.indices.create(index=self.es_index, body=mapping)
            print(f"  [✓] 创建 ODS 索引: {self.es_index}")

        if not self.es.indices.exists(index=self.progress_index):
            # progress 也需要 gkbh（区分同区县不同月份的进度）
            progress_mapping = build_progress_mapping(city_extension={
                'gkbh': {'type': 'keyword'},
            })
            self.es.indices.create(
                index=self.progress_index, body=progress_mapping,
            )
            print(f"  [✓] 创建 progress 索引: {self.progress_index}")
        else:
            # 索引已存在 → PUT _mapping 加 gkbh（幂等，不会覆盖已声明字段）
            try:
                self.es.indices.put_mapping(
                    index=self.progress_index,
                    body={'properties': {'gkbh': {'type': 'keyword'}}},
                )
            except Exception as e:
                print(f"  [warn] progress mapping 加 gkbh 失败（可忽略）: {e}")

    def _bulk_index(self, docs: list[dict]) -> tuple[int, int]:
        """幂等写入（_id = MD5(breed+code+spec+county+period+price+tax_price)）。

        v0.8：键含 period（YYYY-MM），保证同一材料不同月份有不同 _id，保留价格历史。
        """
        if not docs:
            return 0, 0
        body = ''
        for d in docs:
            raw = (
                f"{d['breed']}_{d['code']}_{d['spec']}_"
                f"{d['county']}_{d['period']}_{d['price']}_{d['tax_price']}"
            )
            _id = hashlib.md5(raw.encode('utf-8')).hexdigest()
            body += json.dumps(
                {'index': {'_index': self.es_index, '_id': _id}},
                ensure_ascii=False,
            ) + '\n'
            body += json.dumps(d, ensure_ascii=False) + '\n'

        resp = self.es.bulk(body=body, refresh=False)
        if resp.get('errors'):
            errors = sum(
                1 for it in resp['items']
                if 'error' in it.get('index', {})
            )
            return len(docs) - errors, errors
        return len(docs), 0


# ─────────────────────────────────────────────────────────────
# _make_doc - 构造单条 ES 文档（含 v0.8 新字段）
# ─────────────────────────────────────────────────────────────

def _make_doc(r: dict, county: str, update_date: str,
              period: str, gkbh: str, unit: dict) -> dict:
    """构造 ES 文档。

    字段说明：
      breed / spec / unit / price / tax_price / code: 源表行解析
      county:       区县
      province:     '陕西'
      city:         '西安'
      period:       'YYYY-MM'
      gkbh:         源站周期 ID
      month:        同 period（避免 ES dynamic 推断为 date）
      period_start: 当月首日（来自 unit）
      period_end:   当月末日（来自 unit）
      period_days:  当月天数（来自 unit）
      update_date:  页脚"更新时间" YYYY-MM-DD
      published_at: 同 update_date
      create_time:  入库时间
    """
    return {
        # 业务字段
        'breed':     r.get('breed', ''),
        'code':      r.get('code', ''),
        'spec':      r.get('spec', ''),
        'unit':      r.get('unit', ''),
        'price':     r.get('price'),
        'tax_price': r.get('tax_price'),
        # 区域 / 周期
        'county':    county,
        'province':  '陕西',
        'city':      '西安',
        'period':    period,
        'gkbh':      gkbh,
        'month':     period,  # 同 period，单独字段便于按月查询
        # v0.8 新增字段（道友要求）
        'period_start': unit['period_start'],
        'period_end':   unit['period_end'],
        'period_days':  unit['period_days'],
        # 时间戳
        'update_date':  update_date or '',
        'published_at': update_date or '',
        'create_time':  datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
    }


# ─────────────────────────────────────────────────────────────
# 工厂方法 + 列出周期
# ─────────────────────────────────────────────────────────────

def make_collector(
    cfg_path: str,
    run_id: str,
    counties: Optional[list[str]] = None,
    periods: Optional[list[str]] = None,
    skip_progress: bool = False,
) -> XianCollector:
    """从 config.yml 构造 XianCollector。

    用法（sync.py 默认路径）：
        cfg = load_config(cfg_path)
        collector = make_collector(
            cfg_path, run_id,
            counties=['阎良区'], periods=['2026-01'],
        )
        result = collector.run(reset=False, max_units=None)
    """
    cfg = _legacy.load_config(cfg_path)
    return XianCollector(
        cfg=cfg,
        run_id=run_id,
        counties=counties,
        periods=periods,
        skip_progress=skip_progress,
    )


def list_available_periods(cfg_path: str, counties: Optional[list[str]] = None,
                            year: Optional[int] = None) -> dict:
    """列出每个区县 × 年的可用 period（gkbh + 窗口字段）。

    Returns:
        {
            '阎良区': {
                2026: [
                    {'period': '2026-01', 'gkbh': '0000000595',
                     'period_start': '2026-01-01', 'period_end': '2026-01-31',
                     'period_days': 31, 'name': '2026年01月造价信息表'},
                    ...
                ],
                ...
            },
            ...
        }
    """
    cfg = _legacy.load_config(cfg_path)
    sess = _legacy.SiteSession(max_retries=2, timeout=15)
    counties = counties or cfg['site']['counties']
    now = datetime.now()
    years = [year] if year else list(range(now.year, 2023, -1))

    out: dict[str, dict[int, list[dict]]] = {}
    for county in counties:
        out[county] = {}
        for y in years:
            ps = sess.list_periods(county, y)
            if not ps:
                continue
            items = []
            for p in ps:
                win = parse_period_window(p.get('period', ''))
                items.append({
                    'period':       win['period'],
                    'gkbh':         p.get('id', ''),
                    'period_start': win['period_start'],
                    'period_end':   win['period_end'],
                    'period_days':  win['period_days'],
                    'name':         p.get('name', ''),
                })
            out[county][y] = items
    return out