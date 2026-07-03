"""qinghai_collector.py - 青海默认同步路径（v0.8 SyncRunner 抽象基类化, 2026-07-03）

将 qinghai v0.x 的 sync.py 主流程用 gov_price_etl.collectors.base.SyncRunner 重构。
参考 chongqing v0.8 试点（chongqing_collector.py）+ henan v0.8（henan_collector.py）
+ huhehaote v0.8（huhehaote_collector.py）。

设计：
- 继承 SyncRunner
- 重写 _list_work_units()：抓列表（4 页分页）→ 过滤 journal_keyword + year/period
  → 排除本地已 done → 返回 list[dict]，每 dict 含 period 窗口字段
- 重写 _process_one()：下载 PDF → MinIO → pdfplumber 解析 → bulk_index
- 重写 _on_unit_done()：写 ES progress + 保存本地进度
- 重写 _compute_unit_key()：unit['pdf_url']

v0.8 字段扩展（道友要求）：
  在 doc 中新增 period_start / period_end / period_days
  解析 'YYYY年第N1—N2期' / 'YYYY年第N1、N2期'（双月合刊）：
    - period: 'YYYY.第N1期'（取较小期号；与 hunan v0.8 命名一致）
    - period_start: 第 N1 期对应窗口首日
    - period_end:   第 N2 期对应窗口末日
    - period_days:  (period_end - period_start).days + 1

unit 形状（dict）：
  {
    'period': '2026.第1期',
    'title': '2026年第1—2期《青海建设工程市场价格信息》',
    'publish_date': '2026-02-28',
    'pdf_url': 'http://zjt.qinghai.gov.cn/.../202602281448376974.pdf',
    'pdf_name': '202602281448376974.pdf',
    'minio_key': '',
    'period_start': '2026-01-01',
    'period_end': '2026-02-28',
    'period_days': 59,
  }
"""
from __future__ import annotations

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
_ETL_PROJECT_ROOT = "/Users/pengfit/.openclaw/workspace/skills/gov-price-etl"
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
import sync as _legacy  # fetch_all_periods, parse_pdf, parse_list_page, ...


# ─────────────────────────────────────────────────────────────
# period 窗口解析（v0.8 新增）
# ─────────────────────────────────────────────────────────────

# 青海"建设工程市场价格信息"是双月合刊：
#   '2026年第1—2期' = 第 1 期 (1-2 月)
#   '2026年第3—4期' = 第 2 期 (3-4 月)
#   '2026年第5、6期' = 第 3 期 (5-6 月)（顿号格式，2026 年新格式）
#   '2026年第7—8期' = 第 4 期 (7-8 月)
#   '2026年第9—10期' = 第 5 期 (9-10 月)
#   '2026年第11—12期' = 第 6 期 (11-12 月)
_BIMONTHLY_PERIODS = {
    1: (1, 2),
    2: (3, 4),
    3: (5, 6),
    4: (7, 8),
    5: (9, 10),
    6: (11, 12),
}


def parse_period_window(title: str) -> dict:
    """'2026年第1—2期《青海建设工程市场价格信息》' → {period, period_start, period_end, period_days}

    解析规则：
      1. 从 title 提取年份（YYYY）+ 双月合刊范围 (M1-M2)
         - '第N1—N2期'（破折号）/ '第N1、N2期'（顿号）/ '第N1-N2期'（半角连字符）
      2. 业务期号取较小期号 N1（1, 3, 5, 7, 9, 11 → 业务期 1-6）
      3. period_start = N1 月 1 日
      4. period_end = N2 月末日（calendar.monthrange 推算）
      5. period_days = (period_end - period_start).days + 1

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

    # 模式 1：'2026年第1—2期' / '2025年第11—12期'（破折号 / 半角连字符）
    m = re.search(r'(\d{4})年第(\d{1,2})[—\-–](\d{1,2})期', title)
    if m:
        y = int(m.group(1))
        n1, n2 = int(m.group(2)), int(m.group(3))
        return _window_for_bimonth(y, n1, n2)

    # 模式 2：'2026年第5、6期'（顿号）
    m = re.search(r'(\d{4})年第(\d{1,2})[、，](\d{1,2})期', title)
    if m:
        y = int(m.group(1))
        n1, n2 = int(m.group(2)), int(m.group(3))
        return _window_for_bimonth(y, n1, n2)

    # 模式 3：'2026年第5期'（单月，兜底）- 罕见
    m = re.search(r'(\d{4})年第(\d{1,2})期', title)
    if m:
        y = int(m.group(1))
        n1, n2 = int(m.group(2)), int(m.group(2))
        return _window_for_bimonth(y, n1, n2)

    return _empty_window()


def _window_for_bimonth(y: int, n1: int, n2: int) -> dict:
    """根据年份、双月合刊期号范围生成窗口字段。

    业务期号：第 1 期=1-2 月, 第 2 期=3-4 月, ... 第 6 期=11-12 月。
    双月合刊期号 (1,2) → 业务第 1 期；(3,4) → 业务第 2 期；以此类推。
    """
    m1, m2 = n1, n2
    last_m2 = calendar.monthrange(y, m2)[1]
    # 业务期号 = (n1 - 1) // 2 + 1 → (1,2)=1, (3,4)=2, (5,6)=3, (7,8)=4, (9,10)=5, (11,12)=6
    biz_n = (n1 - 1) // 2 + 1
    period = f'{y}.第{biz_n}期'
    period_start = f'{y:04d}-{m1:02d}-01'
    period_end = f'{y:04d}-{m2:02d}-{last_m2:02d}'
    # period_days 用实际日历推算
    from datetime import date
    period_days = (date(y, m2, last_m2) - date(y, m1, 1)).days + 1
    return {
        'period': period,
        'period_start': period_start,
        'period_end': period_end,
        'period_days': period_days,
    }


def _empty_window() -> dict:
    return {
        'period': '',
        'period_start': '',
        'period_end': '',
        'period_days': 0,
    }


# ─────────────────────────────────────────────────────────────
# QinghaiCollector - qinghai v0.x sync.py 的 SyncRunner 化版本
# ─────────────────────────────────────────────────────────────

class QinghaiCollector(SyncRunner):
    """青海建设工程材料价格采集器（v0.8 SyncRunner 化, 2026-07-03）。

    工作单元形状：dict（见模块顶部注释）。
    业务期号处理：双月合刊"第N1—N2期" / "第N1、N2期" →
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
            '.qinghai_sync_progress.json',
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
        self.journal_keyword = cfg.get('journal_keyword', '青海建设工程市场价格信息')

    # ── SyncRunner 钩子实现 ──

    def _list_work_units(self) -> list[dict]:
        """抓列表（4 页分页）→ 过滤 journal_keyword + year/period → 排除已 done
        → 返回 list[dict]，每 dict 含 period 窗口字段。

        过滤逻辑（参考 v0.x sync.py 的过滤顺序）：
          1. 标题必须含 journal_keyword（"青海建设工程市场价格信息"）
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
            d = done.get(it['pdf_url'])
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
            basename = _legacy.pdf_basename(it['pdf_url'])
            unit = {
                'period': win['period'],
                'title': it['title'],
                'publish_date': it['publish_date'],
                'pdf_url': it['pdf_url'],
                'pdf_name': basename,
                'minio_key': '',
                'period_start': win['period_start'],
                'period_end': win['period_end'],
                'period_days': win['period_days'],
            }
            if win['period']:
                units.append(unit)
        return units

    def _process_one(self, unit: dict) -> tuple[int, str]:
        """处理单个工作单元：下载 PDF → MinIO → 解析 → 写 ES。

        Returns:
            (docs_count, status)，status ∈ {'completed', 'error'}。
        """
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

        # 1. 下载 PDF → 临时文件（带重试：青海政府站大文件易断流）
        with tempfile.TemporaryDirectory() as tmpdir:
            local_pdf = os.path.join(tmpdir, 'source.pdf')
            ok_dl = False
            last_err = None
            for attempt in range(3):
                try:
                    download_file(unit['pdf_url'], local_pdf, timeout=600)
                    ok_dl = True
                    break
                except Exception as e:
                    last_err = e
                    print(f"  ⚠ 下载失败(尝试 {attempt + 1}/3): {e}")
                    time.sleep(2 + attempt * 2)
            if not ok_dl:
                print(f"  ✗ 下载 PDF 最终失败: {last_err}")
                return 0, 'error'

            # 2. 上传 MinIO
            minio_key = (
                f"{cfg_minio['prefix']}/{unit['period']}/{unit['pdf_name']}"
                if unit['period']
                else f"{cfg_minio['prefix']}/unknown/{unit['pdf_name']}"
            )
            try:
                upload_to_minio(
                    self.s3, cfg_minio['bucket'], minio_key, local_pdf,
                )
            except Exception as e:
                print(f"  ✗ 上传 MinIO 失败: {e}")
                return 0, 'error'

            # 3. pdfplumber 解析 → 长表
            try:
                rows = _legacy.parse_pdf(local_pdf)
            except Exception as e:
                print(f"  ✗ PDF 解析失败: {e}")
                return 0, 'error'

            # 4. 构造 docs（含 v0.8 新字段）
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
                    'section': r.get('section', ''),
                    'category': r.get('category', '') or (
                        r['section'].split('、')[0] if r.get('section') else ''
                    ),
                    'period': unit['period'],
                    'period_start': unit['period_start'],
                    'period_end': unit['period_end'],
                    'period_days': unit['period_days'],
                    'province': '青海',
                    'city': '青海',
                    'price_kind': r.get('price_kind', ''),
                    'update_date': unit['publish_date'],
                    'create_time': now,
                    'source_pdf': minio_key,
                    'source_url': unit['pdf_url'],
                })

            unit['minio_key'] = minio_key

            # 5. bulk_index
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
                    'pdf_url': unit['pdf_url'],
                    'minio_key': unit.get('minio_key', ''),
                    'docs_written': docs_count,
                    'status': 'ok' if status == 'completed' else 'error',
                    'error': error,
                    'run_id': self.run_id,
                    'created_at': now,
                })
            except Exception as e:
                print(f"  ⚠ 写 ES progress 失败: {e}")

        # 2. 本地进度（key = pdf_url，与 v0.x 兼容）
        prog = self.progress.load()
        done_map = prog.setdefault('done', {})
        done_map[unit['pdf_url']] = {
            'period': unit['period'],
            'period_start': unit['period_start'],
            'period_end': unit['period_end'],
            'period_days': unit['period_days'],
            'publish_date': unit['publish_date'],
            'pdf_url': unit['pdf_url'],
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
            f"({unit['period_days']}天) {unit['title'][:32]}... → {docs_count} docs"
        )

    def _compute_unit_key(self, unit: dict) -> str:
        """本地进度 key = unit.pdf_url（一期 = 一个 PDF URL）。"""
        return unit['pdf_url']

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
            # 城市特化字段：section / price_kind
            mapping = build_ods_mapping(city_extension={
                'section':   {'type': 'text', 'fields': {'keyword': {'type': 'keyword', 'ignore_above': 256}}},
                'price_kind': {'type': 'keyword'},
            })
            self.es.indices.create(index=self.es_index, body=mapping)
        if not self.es.indices.exists(index=self.progress_index):
            self.es.indices.create(
                index=self.progress_index, body=build_progress_mapping(),
            )

    def _bulk_index(self, docs: list[dict]) -> tuple[int, int]:
        """幂等写入（_id = MD5(period+section+no+breed+spec)）。"""
        if not docs:
            return 0, 0
        body = ''
        for d in docs:
            raw = (
                f"{d['period']}|{d.get('section','')}|{d.get('no','')}|"
                f"{d.get('breed','')}|{d.get('spec','')}"
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
# 工厂方法
# ─────────────────────────────────────────────────────────────

def make_collector(
    cfg_path: str,
    run_id: str,
    year: int = 0,
    period: str = '',
    latest: bool = False,
) -> QinghaiCollector:
    """从 config.yml 构造 QinghaiCollector。

    用法（sync.py 默认路径）：
        cfg = load_config(cfg_path)
        collector = make_collector(cfg_path, run_id, year=2026)
        result = collector.run()
    """
    import yaml
    with open(cfg_path, encoding='utf-8') as f:
        cfg = yaml.safe_load(f) or {}
    return QinghaiCollector(
        cfg=cfg, run_id=run_id, year=year, period=period, latest=latest,
    )
