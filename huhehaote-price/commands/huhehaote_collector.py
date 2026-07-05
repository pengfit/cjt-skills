"""huhehaote_collector.py - 呼和浩特默认同步路径（v0.8 SyncRunner 抽象基类化, 2026-07-03）

将 huhehaote v0.x 的 sync.py 主流程用 gov_price_etl.collectors.base.SyncRunner 重构。
参考 chongqing v0.8 试点（chongqing_collector.py）+ henan v0.8（henan_collector.py）。

设计：
- 继承 SyncRunner
- 重写 _list_work_units()：抓列表（单页）→ 过滤 year/period → 排除已 done
  → 返回 list[dict]，每 dict 含 period 窗口字段
- 重写 _process_one()：抓详情 → 下载 PDF → MinIO → pdfplumber 解析 → bulk_index
- 重写 _on_unit_done()：写 ES progress + 保存本地进度
- 重写 _compute_unit_key()：unit['detail_url']

v0.8 字段扩展（道友要求）：
  在 doc 中新增 period_start / period_end / period_days
  解析 'YYYY年信息价N期' / 'YYYY年第N期（M1-M2月份）' 业务期号：
    - period: 'YYYY.第N期'
    - period_start: 第 N 期对应窗口首日
    - period_end:   第 N 期对应窗口末日
    - period_days:  (period_end - period_start).days + 1

unit 形状（dict）：
  {
    'period': '2026.第1期',
    'title': '2026年信息价1期',
    'publish_date': '2026-03-31',
    'detail_url': 'http://zfcxjsj.huhhot.gov.cn/.../t20260331_1987221.html',
    'pdf_url': '',       # 等 _process_one 中从详情页提取
    'pdf_name': '',
    'minio_key': '',
    'period_start': '2026-01-01',
    'period_end': '2026-02-28',
    'period_days': 59,
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
import re
import sys
import tempfile
import time
from typing import Optional
from urllib.parse import urljoin, urlparse

# ── ETL 公共依赖 ──
_ETL_PROJECT_ROOT = _resolve_etl_root()
if _ETL_PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _ETL_PROJECT_ROOT)

from gov_price_etl.collectors.base import (
    LocalProgressStore,
    SyncRunner,
)
from gov_price_etl.collectors import (
    fetch_html,
    download_file,
    upload_to_minio,
)

# 复用 v0.x sync.py 的 PDF 解析逻辑（不重写）
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)
import sync as _legacy  # fetch_all_periods, fetch_detail_pdf, parse_pdf, _parse_material_table, ...


# ─────────────────────────────────────────────────────────────
# period 窗口解析（v0.8 新增）
# ─────────────────────────────────────────────────────────────

# 呼和浩特"造价信息"为双月刊：每期覆盖 2 个连续月份
# 第 N 期 → (2N-1, 2N) 月
_BIMONTHLY_PERIODS = {
    1: (1, 2),
    2: (3, 4),
    3: (5, 6),
    4: (7, 8),
    5: (9, 10),
    6: (11, 12),
}


def parse_period_window(title: str) -> dict:
    """'2026年信息价1期' / '2025年第六期（11-12月份）' → {period, period_start, period_end, period_days}

    解析规则：
      1. 从 title 提取年份（YYYY）+ 期号（N）
      2. 优先从 title 抽 (M1-M2月) 范围（如"（11-12月份）"）
      3. 否则按双月刊规律：第 N 期 = (2N-1, 2N) 月
      4. period_end 末日 = calendar.monthrange(year, m2)[1]

    Returns:
        {
            'period': 'YYYY.第N期',
            'period_start': 'YYYY-MM-01',
            'period_end': 'YYYY-MM-DD',
            'period_days': int,
        }
    """
    if not title:
        return _empty_window()

    # 模式 1：'2025年第六期（11-12月份）' 或 '2025年第4期（7-8月份）'
    m = re.search(r'(\d{4})年第([一二三四五六\d]+)期[（(](\d{1,2})[-–](\d{1,2})月份?[）)]', title)
    if m:
        y = int(m.group(1))
        n = _cn_to_int(m.group(2))
        m1, m2 = int(m.group(3)), int(m.group(4))
        return _window_for_bimonth(y, n, m1, m2)

    # 模式 2：'2026年信息价1期'（无月份范围，按双月刊规律推算）
    m = re.search(r'(\d{4})年信息价(\d+)期', title)
    if m:
        y = int(m.group(1))
        n = int(m.group(2))
        bi = _BIMONTHLY_PERIODS.get(n)
        if bi:
            m1, m2 = bi
            return _window_for_bimonth(y, n, m1, m2)

    # 模式 3：'造价信息2022年第4期'（无月份范围）
    m = re.search(r'(\d{4})年第([一二三四五六\d]+)期', title)
    if m:
        y = int(m.group(1))
        n = _cn_to_int(m.group(2))
        bi = _BIMONTHLY_PERIODS.get(n)
        if bi:
            m1, m2 = bi
            return _window_for_bimonth(y, n, m1, m2)

    return _empty_window()


def _window_for_bimonth(y: int, n: int, m1: int, m2: int) -> dict:
    """根据年份、期号、月份范围生成窗口字段。"""
    last_m2 = calendar.monthrange(y, m2)[1]
    period = f'{y}.第{n}期'
    return {
        'period': period,
        'period_start': f'{y:04d}-{m1:02d}-01',
        'period_end': f'{y:04d}-{m2:02d}-{last_m2:02d}',
        'period_days': last_m2 + calendar.monthrange(y, m1)[1],
    }


def _empty_window() -> dict:
    return {
        'period': '',
        'period_start': '',
        'period_end': '',
        'period_days': 0,
    }


def _cn_to_int(s: str) -> int:
    """中文数字转 int（含阿拉伯数字兜底）。"""
    cn_map = {'一': 1, '二': 2, '三': 3, '四': 4, '五': 5, '六': 6, '七': 7, '八': 8, '九': 9, '十': 10}
    if s.isdigit():
        return int(s)
    return cn_map.get(s, 0)


# ─────────────────────────────────────────────────────────────
# HuhehaoteCollector - huhehaote v0.x sync.py 的 SyncRunner 化版本
# ─────────────────────────────────────────────────────────────

class HuhehaoteCollector(SyncRunner):
    """呼和浩特建设工程材料价格采集器（v0.8 SyncRunner 化，2026-07-03）。

    工作单元形状：dict（见模块顶部注释）。
    业务期号处理：双月刊"信息价N期" / "第N期（M1-M2月份）" →
        period_start/end/days 从 M1~M2 月份范围推算。
    """

    def __init__(
        self,
        cfg: dict,
        run_id: str,
        year: int = 0,
        period: str = '',
        latest: bool = False,
    ):
        progress_path = os.path.join(
            os.path.dirname(_SCRIPT_DIR),
            '.huhehaote_sync_progress.json',
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
        self.period = period
        self.latest = latest
        self.s3 = None  # lazy init
        self.es = None  # lazy init
        self.journal_keyword = cfg.get('journal_keyword', '信息价')

    # ── SyncRunner 钩子实现 ──

    def _list_work_units(self) -> list[dict]:
        """抓列表（单页）→ 过滤 journal_keyword + year/period → 排除已 done
        → 返回 list[dict]，每 dict 含 period 窗口字段。

        过滤逻辑（参考 v0.x sync.py 的过滤顺序）：
          1. 标题必须含 journal_keyword（"信息价"）
          2. --year 时只保留标题含"YYYY年"的期
          3. --period 时只保留标题含该字符串的期
          4. --latest 时只取第 1 个
          5. 排除本地已 done 且 status='ok' 的期
        """
        all_items = _legacy.fetch_all_periods(self.cfg)

        # 过滤
        filtered = []
        for it in all_items:
            if self.journal_keyword and self.journal_keyword not in it['title']:
                continue
            if self.year and f'{self.year}年' not in it['title']:
                continue
            if self.period and self.period not in it['title']:
                continue
            filtered.append(it)

        # 排除本地已 done
        prog = self.progress.load()
        done = prog.get('done', {})
        todo = []
        for it in filtered:
            d = done.get(it['detail_url'])
            if d and d.get('status') == 'ok':
                continue
            todo.append(it)

        # latest: 只取第 1 个
        if self.latest:
            todo = todo[:1]

        # 拼成 unit dict（含 period 窗口字段）
        units = []
        for it in todo:
            win = parse_period_window(it['title'])
            unit = {
                'period': win['period'],
                'title': it['title'],
                'publish_date': it['publish_date'],
                'detail_url': it['detail_url'],
                'pdf_url': '',
                'pdf_name': '',
                'minio_key': '',
                'period_start': win['period_start'],
                'period_end': win['period_end'],
                'period_days': win['period_days'],
            }
            if win['period']:
                units.append(unit)
        return units

    def _process_one(self, unit: dict) -> tuple[int, str]:
        """处理单个工作单元：抓详情 → 下载 PDF → MinIO → 解析 → 写 ES。

        Returns:
            (docs_count, status)，status ∈ {'completed', 'error'}。
        """
        site = self.cfg['site']
        cfg_minio = self.cfg['minio']

        # 0. 懒加载 ES / s3 客户端
        if self.es is None:
            from gov_price_etl.collectors import get_es_client
            self.es = get_es_client(self.es_host)
            self._ensure_indices()
        if self.s3 is None:
            from gov_price_etl.collectors import (
                get_s3_client, ensure_bucket,
            )
            self.s3 = get_s3_client(self.cfg)
            ensure_bucket(self.s3, cfg_minio['bucket'])

        # 1. 抓详情页 → 拿 PDF URL
        try:
            detail_title, pdf_url, pdf_link_text = _legacy.fetch_detail_pdf(
                self.cfg, unit['detail_url'],
            )
        except Exception as e:
            print(f"  ✗ 抓详情页失败: {e}")
            return 0, 'error'

        if not pdf_url:
            print(f"  ✗ 详情页未找到 PDF 链接")
            return 0, 'error'

        unit['pdf_url'] = pdf_url
        unit['pdf_name'] = pdf_link_text or pdf_basename(pdf_url)

        # 2. 下载 PDF → 临时文件
        with tempfile.TemporaryDirectory() as tmpdir:
            local_pdf = os.path.join(tmpdir, 'source.pdf')
            try:
                download_file(pdf_url, local_pdf, timeout=600)
            except Exception as e:
                print(f"  ✗ 下载 PDF 失败: {e}")
                return 0, 'error'

            # 3. 上传 MinIO
            minio_key = (
                f"{cfg_minio['prefix']}/{unit['period']}/{unit['pdf_name']}"
                if unit['pdf_name']
                else f"{cfg_minio['prefix']}/{unit['period']}/source.pdf"
            )
            try:
                upload_to_minio(
                    self.s3, cfg_minio['bucket'], minio_key, local_pdf,
                )
            except Exception as e:
                print(f"  ✗ 上传 MinIO 失败: {e}")
                return 0, 'error'

            # 4. pdfplumber 解析 → 长表
            try:
                rows = _legacy.parse_pdf(local_pdf)
            except Exception as e:
                print(f"  ✗ PDF 解析失败: {e}")
                return 0, 'error'

            # 5. 构造 docs（含 v0.8 新字段）
            from datetime import datetime
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
                    'period': unit['period'],
                    'period_start': unit['period_start'],
                    'period_end': unit['period_end'],
                    'period_days': unit['period_days'],
                    'province': '内蒙古',
                    'update_date': unit['publish_date'],
                    'create_time': now,
                    'source_pdf': minio_key,
                    'source_url': pdf_url,
                })

            unit['minio_key'] = minio_key

            # 6. bulk_index
            if not docs:
                print(f"  [warn] 解析到 0 行（空 PDF）")
                return 0, 'completed'

            ok, err = self._bulk_index(docs)
            if err > 0:
                print(f"  ⚠ bulk 写入部分失败: ok={ok}, err={err}")
            return ok, 'completed'

    def _on_unit_done(self, unit: dict, docs_count: int, status: str, error: str = '') -> None:
        """完成后：写 ES progress + 保存本地进度。"""
        from datetime import datetime
        now = datetime.now().isoformat(timespec='seconds')

        # 1. ES progress（含 period 窗口字段）
        if self.es is not None:
            try:
                self.es.index(index=self.progress_index, body={
                    'period': unit['period'],
                    'period_start': unit['period_start'],
                    'period_end': unit['period_end'],
                    'period_days': unit['period_days'],
                    'publish_date': unit['publish_date'],
                    'detail_url': unit['detail_url'],
                    'pdf_url': unit.get('pdf_url', ''),
                    'minio_key': unit.get('minio_key', ''),
                    'docs_written': docs_count,
                    'status': 'ok' if status == 'completed' else 'error',
                    'error': error,
                    'run_id': self.run_id,
                    'created_at': now,
                })
            except Exception as e:
                print(f"  ⚠ 写 ES progress 失败: {e}")

        # 2. 本地进度
        prog = self.progress.load()
        done_map = prog.setdefault('done', {})
        done_map[unit['detail_url']] = {
            'period': unit['period'],
            'period_start': unit['period_start'],
            'period_end': unit['period_end'],
            'period_days': unit['period_days'],
            'publish_date': unit['publish_date'],
            'detail_url': unit['detail_url'],
            'pdf_url': unit.get('pdf_url', ''),
            'minio_key': unit.get('minio_key', ''),
            'docs_written': docs_count,
            'status': 'ok' if status == 'completed' else 'error',
            'error': error,
            'created_at': now,
        }
        prog['saved_at'] = now
        self.progress.save(prog)

        icon = '✓' if status == 'completed' else '✗'
        print(
            f"  [{icon}] {unit['period']} {unit['period_start']}~{unit['period_end']} "
            f"({unit['period_days']}天) {unit['title'][:30]}... → {docs_count} docs"
        )

    def _compute_unit_key(self, unit: dict) -> str:
        """本地进度 key = unit.detail_url（一期 = 一个 detail_url）。"""
        return unit['detail_url']

    # ── 私有方法 ──

    def _ensure_indices(self) -> None:
        """确保 ODS + progress 索引存在（套用 ETL 共享 mapping）。

        v0.8: ODS 与 progress mapping 来自 gov_price_etl.mappings，自动含
        period_start / period_end / period_days 字段。
        """
        from gov_price_etl.mappings import (
            build_ods_mapping, build_progress_mapping,
        )
        if not self.es.indices.exists(index=self.es_index):
            # 城市特化字段：section / price_kind / vat_rate / region
            mapping = build_ods_mapping(city_extension={
                'section':   {'type': 'text', 'fields': {'keyword': {'type': 'keyword', 'ignore_above': 256}}},
                'price_kind': {'type': 'keyword'},
                'vat_rate':  {'type': 'float'},
                'region':    {'type': 'keyword'},
            })
            self.es.indices.create(index=self.es_index, body=mapping)
        if not self.es.indices.exists(index=self.progress_index):
            self.es.indices.create(
                index=self.progress_index, body=build_progress_mapping(),
            )

    def _bulk_index(self, docs: list[dict]) -> tuple[int, int]:
        """幂等写入（_id = MD5(period+section+no+breed+city+spec)）。"""
        if not docs:
            return 0, 0
        body = ''
        for d in docs:
            raw = (
                f"{d['period']}|{d.get('section','')}|{d['no']}|"
                f"{d['breed']}|{d.get('city','')}|{d.get('spec','')}"
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
# 工具：PDF 文件名提取
# ─────────────────────────────────────────────────────────────

def pdf_basename(pdf_url: str) -> str:
    """从 PDF URL 提取文件名（兜底用）。"""
    return os.path.basename(urlparse(pdf_url).path) or 'source.pdf'


# ─────────────────────────────────────────────────────────────
# 工厂方法
# ─────────────────────────────────────────────────────────────

def make_collector(
    cfg_path: str,
    run_id: str,
    year: int = 0,
    period: str = '',
    latest: bool = False,
) -> HuhehaoteCollector:
    """从 config.yml 构造 HuhehaoteCollector。

    用法（sync.py 默认路径）：
        cfg = load_config(cfg_path)
        collector = make_collector(cfg_path, run_id, year=2026)
        result = collector.run()
    """
    import yaml
    with open(cfg_path, encoding='utf-8') as f:
        cfg = yaml.safe_load(f) or {}
    return HuhehaoteCollector(
        cfg=cfg, run_id=run_id, year=year, period=period, latest=latest,
    )