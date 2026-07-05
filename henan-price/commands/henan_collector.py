"""henan_collector.py - henan 默认同步路径（v0.8 SyncRunner 抽象基类化, 2026-07-03）

将 henan v0.7 的 sync.py 主流程用 gov_price_etl.collectors.base.SyncRunner 重构。
参考 chongqing v0.8 试点（chongqing_collector.py）。

设计：
- 继承 SyncRunner
- 重写 _list_work_units()：抓列表 4 页 → 过滤 year → 排除已 done → 返回 list[dict]
- 重写 _process_one()：下载 PDF → 上传 MinIO → pdfplumber 解析 → bulk_index
- 重写 _on_unit_done()：写 ES progress + 保存本地进度
- 重写 _compute_unit_key()：unit.detail_url（一期 = 一个 detail_url）

v0.8 字段扩展：
  在 doc 中新增 period_start / period_end / period_days（道友要求）
  解析 'YYYY年M1-M2月' / 'YYYY年M1月' 业务期号：
    - period: 'YYYY.M月'（首月标识，幂等 _id 用）
    - period_start: m1 月第一天
    - period_end: m2 月最后一天（合刊末日）
    - period_days: m1 + m2 月总天数

unit 形状（dict）：
  {
    'period': '2026.3月',  # 期号字符串（首月）
    'title': '河南省2026年3-4月…',
    'publish_date': '2026-05-27',
    'detail_url': 'http://www.hncost.com/jcxx/004001/.../{uuid}.html',
    'pdf_url': 'http://www.hncost.com/BigFileUpLoadStorage/.../{uuid}/2026.2.pdf',
    'pdf_name': '2026.2.pdf',
    'period_start': '2026-03-01',
    'period_end': '2026-04-30',
    'period_days': 61,
  }
"""
from __future__ import annotations

def _resolve_etl_root():
    """解析 gov-price-etl 项目根路径。

    优先级：
      1) 环境变量 GOV_PRICE_ETL_ROOT（部署/调试可显式覆盖）
      2) 自动反推：从本文件路径向上找 'gov-price-etl' 同级目录，
         不依赖硬编码的 workspace 名 / 目录深度。
      3) 兜底扫描：~/.openclaw/workspace/*/skills/gov-price-etl,
         不预设 workspace 名。
      4) 仍找不到：抛错提示用户设环境变量。绝不默默返回错误路径。
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
    workspace_root = Path.home() / ".openclaw" / "workspace"
    if workspace_root.is_dir():
        for ws in workspace_root.iterdir():
            candidate = ws / "skills" / "gov-price-etl"
            if candidate.is_dir():
                return str(candidate)
    raise FileNotFoundError(
        "找不到 gov-price-etl 项目根。"
        "请设置环境变量 GOV_PRICE_ETL_ROOT 指向项目根，"
        "或确认 ETL 已部署在 <workspace>/skills/gov-price-etl。"
    )


import calendar
import hashlib
import json
import os
import re
import sys
import tempfile
import time
from typing import Optional

import pdfplumber

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

# 复用 v0.7 sync.py 的 PDF 解析逻辑（不要重写）
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)
import sync as _legacy  # parse_pdf_tables, _CITY_NAMES, PROVINCE_CITY, VAT_RATE, ...


# ─────────────────────────────────────────────────────────────
# 18 个地市（识别"续表页"用）—— 转发到 v0.7
# ─────────────────────────────────────────────────────────────
_CITY_NAMES = _legacy._CITY_NAMES


# ─────────────────────────────────────────────────────────────
# period 窗口解析（v0.8 新增）
# ─────────────────────────────────────────────────────────────

def parse_period_window(title_or_period: str) -> dict:
    """'河南省2026年3-4月…' / '2026.3月' → {period, period_start, period_end, period_days, months}

    业务规则（源站 PDF 是双月合刊）：
      - period 取首月作为业务标识（与 _id 幂等性绑定）
      - period_start = m1 月第一天
      - period_end = m2 月最后一天（合刊末日）
      - period_days = m1 月天数 + m2 月天数

    单月（M1=M2）：period_end = period_start = 当月末日，period_days = 月天数

    Returns:
        {
            'period': 'YYYY.M月',
            'period_start': 'YYYY-MM-01',
            'period_end': 'YYYY-MM-DD',
            'period_days': int,
            'months': [m1] 或 [m1, m2],
        }
    """
    m = re.search(r'(\d{4})年(\d{1,2})(?:-(\d{1,2}))?月', title_or_period or '')
    if not m:
        return {
            'period': '', 'period_start': '', 'period_end': '',
            'period_days': 0, 'months': [],
        }
    y, m1, m2 = int(m.group(1)), int(m.group(2)), int(m.group(3) or m.group(2))
    period = f'{y}.{m1}月'
    last_m1 = calendar.monthrange(y, m1)[1]
    start = f'{y:04d}-{m1:02d}-01'
    if m2 == m1:
        end = f'{y:04d}-{m1:02d}-{last_m1:02d}'
        days = last_m1
        months = [m1]
    else:
        last_m2 = calendar.monthrange(y, m2)[1]
        end = f'{y:04d}-{m2:02d}-{last_m2:02d}'
        days = last_m1 + last_m2
        months = [m1, m2]
    return {
        'period': period,
        'period_start': start,
        'period_end': end,
        'period_days': days,
        'months': months,
    }


# ─────────────────────────────────────────────────────────────
# 18 城市集合（PDF 续表识别）
# ─────────────────────────────────────────────────────────────
_CITIES_HENAN = [
    '郑州', '濮阳', '周口', '许昌', '新乡', '洛阳', '安阳', '焦作',
    '平顶山', '信阳', '漯河', '驻马店', '南阳', '鹤壁', '三门峡',
    '济源', '开封', '商丘',
]


# ─────────────────────────────────────────────────────────────
# HenanCollector - henan v0.7 sync.py 的 SyncRunner 化版本
# ─────────────────────────────────────────────────────────────

class HenanCollector(SyncRunner):
    """河南工程造价材料采集器（v0.8 SyncRunner 化，2026-07-03）。

    工作单元形状：dict（见模块顶部注释）。
    业务期号处理：双月合刊（'M1-M2月'）→ period 用首月 + 新增 start/end/days 字段。
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
            '.henan_sync_progress.json',
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

    # ── SyncRunner 钩子实现 ──

    def _list_work_units(self) -> list[dict]:
        """抓列表 4 页 → 过滤 year/period → 排除已 done → 返回 list[dict]。

        业务期号窗口从 title 解析（'YYYY年M1-M2月' 模式），生成的 unit
        包含 period/period_start/period_end/period_days 4 个字段。
        """
        all_items = self._fetch_all_periods(self.cfg)

        # 过滤
        filtered = []
        for it in all_items:
            if self.year and f'{self.year}年' not in it['title']:
                continue
            if self.period and self.period not in it['title']:
                continue
            filtered.append(it)

        # 排除本地已 done
        local_prog = self.progress.load()
        done = local_prog.get('done', {})
        todo = [it for it in filtered if it['detail_url'] not in done]
        # 或 done 但 status != ok
        todo = [
            it for it in filtered
            if it['detail_url'] not in done
            or done.get(it['detail_url'], {}).get('status') != 'ok'
        ]

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
                'pdf_url': '',  # 等 _process_one 中从详情页提取
                'pdf_name': '',
                'period_start': win['period_start'],
                'period_end': win['period_end'],
                'period_days': win['period_days'],
                'months': win['months'],
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
            # 确保索引存在
            self._ensure_indices()
        if self.s3 is None:
            from gov_price_etl.collectors import (
                get_s3_client, ensure_bucket,
            )
            self.s3 = get_s3_client(self.cfg)
            ensure_bucket(self.s3, cfg_minio['bucket'])

        # 1. 抓详情页 → 拿 PDF URL
        try:
            detail_html = fetch_html(
                unit['detail_url'],
                headers={'User-Agent': site['user_agent']},
                timeout=site['timeout_sec'],
            )
        except Exception as e:
            print(f"  ✗ 抓详情页失败: {e}")
            return 0, 'error'

        detail = self._parse_detail_page(detail_html, site['base_url'])
        if not detail['pdf_url']:
            print(f"  ✗ 详情页未找到 PDF 链接")
            return 0, 'error'

        unit['pdf_url'] = detail['pdf_url']
        unit['pdf_name'] = detail['pdf_name']

        # 2. 下载 PDF → 临时文件
        with tempfile.TemporaryDirectory() as tmpdir:
            local_pdf = os.path.join(tmpdir, 'source.pdf')
            try:
                download_file(detail['pdf_url'], local_pdf, timeout=120)
            except Exception as e:
                print(f"  ✗ 下载 PDF 失败: {e}")
                return 0, 'error'

            # 3. 上传 MinIO
            minio_key = (
                f"{cfg_minio['prefix']}/{detail['pdf_name']}"
                if detail['pdf_name']
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
                pdf_rows = _legacy.parse_pdf_tables(local_pdf, _CITIES_HENAN)
            except Exception as e:
                print(f"  ✗ PDF 解析失败: {e}")
                return 0, 'error'

            # 5. 构造 docs（含 v0.8 新字段）
            from datetime import datetime
            now = datetime.now().isoformat(timespec='seconds')
            docs = []
            for r in pdf_rows:
                doc = {
                    'period': unit['period'],
                    'period_start': unit['period_start'],
                    'period_end': unit['period_end'],
                    'period_days': unit['period_days'],
                    'breed': r['breed'],
                    'spec': r['spec'],
                    'unit': r['unit'],
                    'price': r['price'],
                    'city': r['city'],
                    'province': '河南',
                    'update_date': unit['publish_date'],
                    'create_time': now,
                    'source_pdf': minio_key,
                    'source_url': detail['pdf_url'],
                }
                if 'tax_price' in r:
                    doc['tax_price'] = r['tax_price']
                docs.append(doc)

            # 6. bulk_index
            if not docs:
                print(f"  [warn] 解析到 0 行（空 PDF）")
                return 0, 'completed'  # 视为空期完成

            ok, err = self._bulk_index(docs)
            if err > 0:
                print(f"  ⚠ bulk 写入部分失败: ok={ok}, err={err}")
            return ok, 'completed'

    def _on_unit_done(self, unit: dict, docs_count: int, status: str, error: str = '') -> None:
        """完成后：写 ES progress + 保存本地进度。"""
        from datetime import datetime
        now = datetime.now().isoformat(timespec='seconds')

        # 1. ES progress（与 v0.7 字段保持一致 + 加 period 窗口字段）
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
                    'minio_key': (
                        f"{self.cfg['minio']['prefix']}/{unit.get('pdf_name', '')}"
                        if unit.get('pdf_name')
                        else f"{self.cfg['minio']['prefix']}/{unit['period']}/source.pdf"
                    ),
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
            'minio_key': (
                f"{self.cfg['minio']['prefix']}/{unit.get('pdf_name', '')}"
                if unit.get('pdf_name')
                else f"{self.cfg['minio']['prefix']}/{unit['period']}/source.pdf"
            ),
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
        """确保 ODS + progress 索引存在（套用 ETL 共享 mapping）。"""
        from gov_price_etl.mappings import (
            build_ods_mapping, build_progress_mapping,
        )
        if not self.es.indices.exists(index=self.es_index):
            self.es.indices.create(index=self.es_index, body=build_ods_mapping())
        if not self.es.indices.exists(index=self.progress_index):
            self.es.indices.create(
                index=self.progress_index, body=build_progress_mapping(),
            )

    def _bulk_index(self, docs: list[dict]) -> tuple[int, int]:
        """幂等写入（_id = MD5(period+breed+spec+city)）。"""
        if not docs:
            return 0, 0
        body = ''
        for d in docs:
            raw = f"{d['period']}|{d['breed']}|{d['spec']}|{d['city']}"
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

    def _fetch_all_periods(self, cfg: dict) -> list[dict]:
        """抓取所有期（4 页）。委托到 v0.7 工具函数（不重写）。"""
        return _legacy.fetch_all_periods(cfg)

    def _parse_detail_page(self, html: str, base_url: str) -> dict:
        """详情页解析。委托到 v0.7。"""
        return _legacy.parse_detail_page(html, base_url)


# ─────────────────────────────────────────────────────────────
# 工厂方法
# ─────────────────────────────────────────────────────────────

def make_collector(
    cfg_path: str,
    run_id: str,
    year: int = 0,
    period: str = '',
    latest: bool = False,
) -> HenanCollector:
    """从 config.yml 构造 HenanCollector。

    用法（sync.py 默认路径）：
        cfg = load_config(cfg_path)
        collector = make_collector(cfg_path, run_id, year=2026)
        result = collector.run()
    """
    import yaml
    with open(cfg_path, encoding='utf-8') as f:
        cfg = yaml.safe_load(f) or {}
    return HenanCollector(
        cfg=cfg, run_id=run_id, year=year, period=period, latest=latest,
    )
