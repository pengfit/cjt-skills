"""heze_collector.py - heze 默认同步路径（v0.8 SyncRunner 抽象基类化, 2026-07-03）

将 heze v0.7 的 sync.py 主流程用 gov_price_etl.collectors.base.SyncRunner 重构。
参考 chongqing v0.8 试点（chongqing_collector.py）+ henan v0.8 改造（henan_collector.py）。

设计：
- 继承 SyncRunner
- 重写 _list_work_units()：抓列表 → 过滤 year/period → 排除已 done → 返回 list[dict]
- 重写 _process_one()：抓详情页 → 下载 PDF → MinIO → pdfplumber 解析 → bulk_index
- 重写 _on_unit_done()：写 ES progress + 保存本地进度
- 重写 _compute_unit_key()：unit.xxid（一期 = 一个 xxid）

v0.8 字段扩展（道友要求）：
  在 doc 和 progress 中新增 period_start / period_end / period_days 三个字段。
  解析 '《工程造价信息》2026年第1期' 业务期号：
    - period: '2026.1期'（保持 v0.7 形态，幂等 _id 用）
    - period_start: 当月第 1 天
    - period_end:   当月最后 1 天
    - period_days:  当月总天数

unit 形状（dict）：
  {
    'period': '2026.1期',
    'title': '《工程造价信息》2026年第1期',
    'publish_date': '2026-04-15',
    'xxid': 'detail-page-xxid',  # 源站期号 ID
    'pdf_url': '',
    'pdf_name': '',
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
from gov_price_etl.collectors import (
    fetch_html,
    download_file,
    upload_to_minio,
)

# 复用 v0.7 sync.py 的工具函数（不要重写）
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)
import sync as _legacy  # fetch_all_periods / fetch_detail_pdf / parse_pdf_tables / extract_period_from_title / ...


# ─────────────────────────────────────────────────────────────
# period 窗口解析（v0.8 新增）
# ─────────────────────────────────────────────────────────────

def parse_period_window(title_or_period: str) -> dict:
    """'《工程造价信息》2026年第1期' / '2026.1期' → {period, period_start, period_end, period_days}

    业务规则（源站 PDF 是单月期）：
      - period: 'YYYY.N期'（与 v0.7 extract_period_from_title 形态一致，幂等 _id 用）
      - period_start: 当月第 1 天
      - period_end:   当月最后 1 天
      - period_days:  当月总天数（calendar.monthrange）

    Returns:
        {
            'period': 'YYYY.N期',
            'period_start': 'YYYY-MM-01',
            'period_end':   'YYYY-MM-DD',
            'period_days':  int,
        }
    """
    # 优先匹配 'YYYY年第N期' 模式
    m = re.search(r'(\d{4})年\s*第?\s*(\d{1,2})\s*期', title_or_period or '')
    if not m:
        # fallback: '2026.1期' 形态
        m = re.match(r'(\d{4})\.(\d{1,2})期', title_or_period or '')
        if not m:
            return {
                'period': '', 'period_start': '', 'period_end': '',
                'period_days': 0,
            }
    y, n = int(m.group(1)), int(m.group(2))
    if not (1 <= n <= 12):
        return {
            'period': '', 'period_start': '', 'period_end': '',
            'period_days': 0,
        }
    last_day = calendar.monthrange(y, n)[1]
    return {
        'period': f'{y}.{n}期',
        'period_start': f'{y:04d}-{n:02d}-01',
        'period_end': f'{y:04d}-{n:02d}-{last_day:02d}',
        'period_days': last_day,
    }


# ─────────────────────────────────────────────────────────────
# HezeCollector - heze v0.7 sync.py 的 SyncRunner 化版本
# ─────────────────────────────────────────────────────────────

class HezeCollector(SyncRunner):
    """菏泽工程造价材料采集器（v0.8 SyncRunner 化, 2026-07-03）。

    工作单元形状：dict（见模块顶部注释）。
    业务期号处理：单月期（'2026年第1期'）→ period 用 'YYYY.N期' + 新增 start/end/days 字段。
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
            '.heze_sync_progress.json',
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
        """抓列表 → 过滤 year/period → 排除已 done → 返回 list[dict]。

        业务期号窗口从 title 解析（'YYYY年第N期' 模式），生成的 unit
        包含 period/period_start/period_end/period_days 4 个字段。
        """
        all_items = self._fetch_all_periods(self.cfg)

        # 1) 标题关键字过滤（必须是《工程造价信息》刊）
        filtered = []
        for it in all_items:
            if '工程造价信息' not in it.get('title', ''):
                continue
            if self.year and f'{self.year}年' not in it['title']:
                continue
            if self.period and self.period not in it['title']:
                continue
            filtered.append(it)

        # 2) 排除本地已 done（status=ok 跳过；其他重试）
        local_prog = self.progress.load()
        done = local_prog.get('done', {})
        todo = [
            it for it in filtered
            if it['xxid'] not in done
            or done.get(it['xxid'], {}).get('status') != 'ok'
        ]

        # 3) latest: 只取第 1 个
        if self.latest:
            todo = todo[:1]

        # 4) 拼成 unit dict（含 period 窗口字段）
        units = []
        for it in todo:
            win = parse_period_window(it['title'])
            unit = {
                'period': win['period'],
                'title': it['title'],
                'publish_date': it.get('publish_date', ''),
                'xxid': it['xxid'],
                'pdf_url': '',  # 等 _process_one 中从详情页提取
                'pdf_name': '',
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
            detail = _legacy.fetch_detail_pdf(self.cfg, unit['xxid'])
        except Exception as e:
            print(f"  ✗ 抓详情页失败: {e}")
            return 0, 'error'

        if not detail.get('pdf_url'):
            print(f"  ✗ 详情页未找到 PDF 链接")
            return 0, 'error'

        unit['pdf_url'] = detail['pdf_url']
        unit['pdf_name'] = detail.get('pdf_name', '')

        # 2. 下载 PDF → 临时文件
        with tempfile.TemporaryDirectory() as tmpdir:
            local_pdf = os.path.join(tmpdir, 'source.pdf')
            try:
                download_file(detail['pdf_url'], local_pdf, timeout=120)
            except Exception as e:
                print(f"  ✗ 下载 PDF 失败: {e}")
                return 0, 'error'

            # 3. 上传 MinIO
            #    优先用详情页中的可读文件名，老期数没可读名则用《工程造价信息》{period}.pdf
            if detail.get('pdf_name') and not detail['pdf_name'].startswith('WY'):
                minio_key = f"{cfg_minio['prefix']}/{detail['pdf_name']}"
            else:
                display_name = _legacy.period_to_display_name(unit['period'])
                minio_key = f"{cfg_minio['prefix']}/{display_name}.pdf"
            try:
                upload_to_minio(
                    self.s3, cfg_minio['bucket'], minio_key, local_pdf,
                )
            except Exception as e:
                print(f"  ✗ 上传 MinIO 失败: {e}")
                return 0, 'error'

            # 4. pdfplumber 解析 → 长表
            try:
                pdf_rows = _legacy.parse_pdf_tables(
                    local_pdf, self.cfg['cities'],
                )
            except Exception as e:
                print(f"  ✗ PDF 解析失败: {e}")
                return 0, 'error'

            # 5. 构造 docs（含 v0.8 新字段）
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
                    'province': '山东',
                    'update_date': unit['publish_date'],
                    'create_time': now,
                    'source_pdf': minio_key,
                    'source_url': detail['pdf_url'],
                }
                if r.get('category'):
                    doc['category'] = r['category']
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
                    'xxid': unit['xxid'],
                    'detail_url': f"{self.cfg['site']['base_url']}/{self.cfg['site']['dwid']}/{unit['xxid']}.html",
                    'pdf_url': unit.get('pdf_url', ''),
                    'minio_key': self._minio_key(unit),
                    'docs_written': docs_count,
                    'status': 'ok' if status == 'completed' else 'error',
                    'error': error,
                    'run_id': self.run_id,
                    'created_at': now,
                })
            except Exception as e:
                print(f"  ⚠ 写 ES progress 失败: {e}")

        # 2. 本地进度（与 v0.7 形态兼容 + 加 period 窗口字段）
        prog = self.progress.load()
        done_map = prog.setdefault('done', {})
        done_map[unit['xxid']] = {
            'period': unit['period'],
            'period_start': unit['period_start'],
            'period_end': unit['period_end'],
            'period_days': unit['period_days'],
            'publish_date': unit['publish_date'],
            'xxid': unit['xxid'],
            'pdf_url': unit.get('pdf_url', ''),
            'minio_key': self._minio_key(unit),
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
        """本地进度 key = unit.xxid（一期 = 一个 xxid）。"""
        return unit['xxid']

    # ── 私有方法 ──

    def _ensure_indices(self) -> None:
        """确保 ODS + progress 索引存在（套用 ETL 共享 mapping）。

        progress 索引加 city_extension：xxid 字段（菏泽源站期 ID），
        ETL 公共 mapping 未声明，菏泽需要。
        """
        from gov_price_etl.mappings import (
            build_ods_mapping, build_progress_mapping,
        )
        if not self.es.indices.exists(index=self.es_index):
            self.es.indices.create(
                index=self.es_index, body=build_ods_mapping(),
            )
        if not self.es.indices.exists(index=self.progress_index):
            self.es.indices.create(
                index=self.progress_index,
                body=build_progress_mapping(
                    city_extension={
                        'xxid': {'type': 'keyword'},  # 菏泽源站期号 ID
                    },
                ),
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

    def _minio_key(self, unit: dict) -> str:
        """根据 unit 字段推断 minio_key（与 _process_one 中上传时一致）。"""
        cfg_minio = self.cfg['minio']
        if unit.get('pdf_name') and not unit['pdf_name'].startswith('WY'):
            return f"{cfg_minio['prefix']}/{unit['pdf_name']}"
        display_name = _legacy.period_to_display_name(unit['period'])
        return f"{cfg_minio['prefix']}/{display_name}.pdf"

    def _fetch_all_periods(self, cfg: dict) -> list[dict]:
        """抓取所有期。委托到 v0.7 工具函数（不重写）。"""
        return _legacy.fetch_all_periods(cfg)


# ─────────────────────────────────────────────────────────────
# 工厂方法
# ─────────────────────────────────────────────────────────────

def make_collector(
    cfg_path: str,
    run_id: str,
    year: int = 0,
    period: str = '',
    latest: bool = False,
) -> HezeCollector:
    """从 config.yml 构造 HezeCollector。

    用法（sync.py 默认路径）：
        cfg = load_config(cfg_path)
        collector = make_collector(cfg_path, run_id, year=2026)
        result = collector.run()
    """
    import yaml
    with open(cfg_path, encoding='utf-8') as f:
        cfg = yaml.safe_load(f) or {}
    return HezeCollector(
        cfg=cfg, run_id=run_id, year=year, period=period, latest=latest,
    )
