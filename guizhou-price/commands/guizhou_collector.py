"""guizhou_collector.py - Guizhou 默认同步路径（v0.8 SyncRunner 抽象基类化）

参考 henan_collector.py 设计：
- 继承 SyncRunner
- _list_work_units()：翻所有页 → 过滤 year/period → 排除已 done → 返回 unit list
- _process_one()：下载 PDF → 上传 MinIO → pdfplumber 解析 → bulk_index
- _on_unit_done()：写 ES progress（SyncRunner 自动管本地进度）
- _compute_unit_key()：unit.detail_url（一期 = 一个 detail_url）

v0.8 字段扩展：
  doc 中新增 period_start / period_end / period_days。
  解析 'YYYY年第N期' 业务期号 → period 'YYYY.N期'。

unit 形状（dict）：
  {
      'period':         '2026.6期',
      'period_start':   '2026-06-01',
      'period_end':     '2026-06-30',
      'period_days':    30,
      'title':          '贵州省建设工程造价信息 2026年第6期',
      'publish_date':   '2026-06-22',
      'detail_url':     'http://www.gzszj.com/Home/PoliciesDetail/1800',
      'pdf_url':        'http://www.gzszj.com/Upload/File/{uuid}/{name}.pdf',
      'pdf_name':       '贵州省建设工程造价信息-2026第6期.pdf',
  }
"""
from __future__ import annotations


def _resolve_etl_root():
    """解析 gov-price-etl 项目根路径（同 sync/utils.py 模式）。"""
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


import os
import sys
import tempfile
from datetime import datetime

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
    download_file,
    upload_to_minio,
)

# 复用 v0.7 sync.py 的工具函数（不要重写）
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)
import sync as _legacy  # fetch_all_periods, parse_pdf_tables, parse_period_from_title, bulk_index, ...


# === 贵州 PDF 地州市名 → GeoJSON 名映射 ===
# PDF 用 "贵阳市区" / "黔西南州" 等简称;ECharts DataV GeoJSON 用 "贵阳市" / "黔西南布依族苗族自治州" 等全称。
# 直接做精确查表;查不到保留 raw(向后兼容)。
_GUIZHOU_CITY_NAME_MAP = {
    '贵阳市区':   '贵阳市',
    '六盘水市区': '六盘水市',
    '遵义市区':   '遵义市',
    '安顺市区':   '安顺市',
    '毕节市区':   '毕节市',
    '铜仁市区':   '铜仁市',
    '黔西南州':   '黔西南布依族苗族自治州',
    '黔东南州':   '黔东南苗族侗族自治州',
    '黔南州':     '黔南布依族苗族自治州',
}


def _normalize_guizhou_city(raw: str) -> str:
    """PDF 解析出的 city 字段做归一化,匹配 ECharts GeoJSON feature name。
    空值/未命中保留原值。"""
    if not raw:
        return '贵州'
    return _GUIZHOU_CITY_NAME_MAP.get(raw.strip(), raw)



# ─────────────────────────────────────────────────────────────
# GuizhouCollector - guizhou v0.7 sync.py 的 SyncRunner 化版本
# ─────────────────────────────────────────────────────────────

class GuizhouCollector(SyncRunner):
    """贵州工程造价材料采集器（v0.8 SyncRunner 化）。

    工作单元形状：dict（见模块顶部注释）。
    业务期号处理：12 期/年（月刊, 'YYYY年第N期' → period 'YYYY.N期'）。
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
            '.guizhou_sync_progress.json',
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
        self.s3 = None  # lazy
        self.es = None  # lazy

    # ── SyncRunner 钩子实现 ──

    def _list_work_units(self) -> list[dict]:
        """抓列表（POST AJAX 翻页）→ 过滤 year/period → 排除已 done → 返回 list[dict]。"""
        all_items = _legacy.fetch_all_periods(self.cfg)

        # 过滤 year / period
        filtered = []
        for it in all_items:
            if self.year and f'{self.year}年' not in it['title']:
                continue
            if self.period and self.period not in it['title']:
                continue
            filtered.append(it)

        # 排除本地已 done
        todo = [it for it in filtered if not self.progress.is_done(it['detail_url'])]

        # latest: 只取第一个
        if self.latest:
            todo = todo[:1]

        # 拼成 unit dict（含 period 窗口字段）
        units = []
        for it in todo:
            win = _legacy.parse_period_from_title(it['title'])
            if not win or win.get('invalid'):
                print(
                    f"  [warn] 跳过无法解析期号的条目: {it['title']!r}"
                )
                continue
            unit = {
                'period':       win['period'],
                'period_start': win['period_start'],
                'period_end':   win['period_end'],
                'period_days':  win['period_days'],
                'title':        it['title'],
                'publish_date': it['publish_date'],
                'detail_url':   it['detail_url'],
                'pdf_url':      it['pdf_url'],
                'pdf_name':     it['pdf_name'],
            }
            units.append(unit)
        return units

    def _process_one(self, unit: dict) -> tuple[int, str]:
        """处理单个工作单元：下载 PDF → MinIO → 解析 → bulk_index。

        Returns:
            (docs_count, status), status ∈ {'completed', 'error'}。
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

        with tempfile.TemporaryDirectory() as tmpdir:
            local_pdf = os.path.join(tmpdir, 'source.pdf')

            # 1. 下载 PDF
            try:
                download_file(unit['pdf_url'], local_pdf, timeout=120)
            except Exception as e:
                print(f"  ✗ 下载 PDF 失败: {e}")
                return 0, 'error'

            # 2. 上传 MinIO
            minio_key = f"{cfg_minio['prefix']}/{unit['pdf_name']}"
            try:
                upload_to_minio(
                    self.s3, cfg_minio['bucket'], minio_key, local_pdf,
                )
            except Exception as e:
                print(f"  ✗ 上传 MinIO 失败: {e}")
                return 0, 'error'

            # 3. PDF 解析（best-effort）
            try:
                pdf_rows = _legacy.parse_pdf_tables(local_pdf)
            except Exception as e:
                print(f"  ✗ PDF 解析失败: {e}")
                return 0, 'error'

            # 4. 构造 docs
            now = datetime.now().isoformat(timespec='seconds')
            docs = []
            if pdf_rows:
                for r in pdf_rows:
                    docs.append({
                        'period':        unit['period'],
                        'period_start':  unit['period_start'],
                        'period_end':    unit['period_end'],
                        'period_days':   unit['period_days'],
                        'breed':         r.get('breed', ''),
                        'spec':          r.get('spec', ''),
                        'unit':          r.get('unit', ''),
                        'price':         r['price'],
                        'city':          _normalize_guizhou_city(r.get('city', '贵州')),
                        'province':      '贵州',
                        'update_date':   unit['publish_date'],
                        'create_time':   now,
                        'source_pdf':    minio_key,
                        'source_url':    unit['pdf_url'],
                        'remark':        r.get('remark', ''),
                    })
            else:
                # PDF 解析失败 — 插 1 条 placeholder 标记已归档
                docs.append({
                    'period':        unit['period'],
                    'period_start':  unit['period_start'],
                    'period_end':    unit['period_end'],
                    'period_days':   unit['period_days'],
                    'breed': '', 'spec': '', 'unit': '',
                    'price': 0.0,
                    'city': '贵州', 'province': '贵州',
                    'update_date':   unit['publish_date'],
                    'create_time':   now,
                    'source_pdf':    minio_key,
                    'source_url':    unit['pdf_url'],
                    'parse_status':  'unparsed',
                })

            # 5. bulk_index
            ok, err = _legacy.bulk_index(self.es, self.es_index, docs)
            if err > 0:
                print(f"  ⚠ bulk 写入部分失败: ok={ok}, err={err}")
            return ok, 'completed'

    def _on_unit_done(self, unit: dict, docs_count: int, status: str,
                      error: str = '') -> None:
        """完成后：写 ES progress。SyncRunner 会自动同步本地进度。"""
        if self.es is not None:
            try:
                self.es.index(
                    index=self.progress_index,
                    body={
                        'period':        unit['period'],
                        'period_start':  unit['period_start'],
                        'period_end':    unit['period_end'],
                        'period_days':   unit['period_days'],
                        'publish_date':  unit['publish_date'],
                        'detail_url':    unit['detail_url'],
                        'pdf_url':       unit['pdf_url'],
                        'minio_key':     f"{self.cfg['minio']['prefix']}/{unit['pdf_name']}",
                        'docs_written':  docs_count,
                        'status':        'ok' if status == 'completed' else 'error',
                        'error':         error,
                        'run_id':        self.run_id,
                        'created_at':    datetime.now().isoformat(timespec='seconds'),
                    },
                )
            except Exception as e:
                print(f"  ⚠ 写 ES progress 失败: {e}")

        icon = '✓' if status == 'completed' else '✗'
        print(
            f"  [{icon}] {unit['period']} {unit['period_start']}~{unit['period_end']} "
            f"({unit['period_days']}天) {unit['title'][:30]}... "
            f"→ {docs_count} docs"
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
            self.es.indices.create(
                index=self.es_index,
                body=build_ods_mapping(),
            )
        if not self.es.indices.exists(index=self.progress_index):
            self.es.indices.create(
                index=self.progress_index,
                body=build_progress_mapping(),
            )


# ─────────────────────────────────────────────────────────────
# 工厂方法
# ─────────────────────────────────────────────────────────────

def make_collector(
    cfg_path: str,
    run_id: str,
    year: int = 0,
    period: str = '',
    latest: bool = False,
) -> GuizhouCollector:
    """从 config.yml 构造 GuizhouCollector。

    用法（sync.py 默认路径）：
        collector = make_collector(cfg_path, run_id, year=2026)
        result = collector.run()
    """
    import yaml
    with open(cfg_path, encoding='utf-8') as f:
        cfg = yaml.safe_load(f) or {}
    return GuizhouCollector(
        cfg=cfg, run_id=run_id, year=year, period=period, latest=latest,
    )
