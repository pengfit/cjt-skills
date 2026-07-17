"""shanxi_collector.py - Shanxi 默认同步路径（v1.0 SyncRunner 抽象基类化）

参考 guizhou_collector / shaanxi_collector 设计：
- 继承 SyncRunner
- _list_work_units()：翻所有页 → 过滤 year → 排除 done → 返回 unit list
- _process_one()：下载 PDF → 上传 MinIO → pdfplumber 解析 → bulk_index
- _on_unit_done()：写 ES progress（SyncRunner 自动管本地进度）
- _compute_unit_key()：unit.detail_url（一期 = 一个 detail_url）

unit 形状（dict）：
  {
      'period':         '2026.3-4月',
      'period_start':   '2026-03-01',
      'period_end':     '2026-04-30',
      'period_days':    61,
      'title':          '2026年3-4月山西省各市常用建设工程材料价格信息(不含税)',
      'publish_date':   '2026-05-21',
      'detail_url':     'https://zjt.shanxi.gov.cn/fwzl/bzdexx/jgxx/202605/t20260521_10131405.shtml',
      'pdf_url':        'https://zjt.shanxi.gov.cn/protect/P0202605/P020260521/P020260521595406680195.pdf',
      'pdf_name':       '2026年3-4月山西省各市常用建设工程材料价格信息(不含税).pdf',
  }
"""
from __future__ import annotations


def _resolve_etl_root():
    """解析 gov-price-etl 项目根路径（同 sync.py 模式）。"""
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

# 复用 sync.py 的工具函数（不要重写）
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)
import sync as _legacy  # fetch_all_periods, parse_pdf_tables, parse_period_from_title, bulk_index, row_to_doc, should_include, ...


# ─────────────────────────────────────────────────────────────
# ShanxiCollector - Shanxi v1.0 SyncRunner 化版本
# ─────────────────────────────────────────────────────────────

class ShanxiCollector(SyncRunner):
    """山西工程造价材料采集器（v1.0 SyncRunner 化）。

    工作单元形状：dict（见模块顶部注释）。
    业务期号处理：'YYYY年M-N月' → period 'YYYY.M-N月'。
    """

    def __init__(
        self,
        cfg: dict,
        run_id: str,
        year: int = 0,
        period: str = '',
        latest: bool = False,
        all_years: bool = False,
    ):
        progress_path = os.path.join(
            os.path.dirname(_SCRIPT_DIR),
            '.shanxi_sync_progress.json',
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
        self.all_years = all_years
        self.s3 = None  # lazy
        self.es = None  # lazy

    # ── SyncRunner 钩子实现 ──

    def _list_work_units(self) -> list[dict]:
        """抓列表 → 过滤 year/period/keyword → 排除已 done → 返回 list[dict]。"""
        # 1. 抓全量列表
        all_items = _legacy.fetch_all_periods(self.cfg)

        # 2. 过滤 year / period / 关键词
        filtered = []
        for it in all_items:
            # period 关键字过滤（CLI --period）
            if self.period and self.period not in it['title']:
                continue
            # year 过滤（默认 cfg.sync.default_year=2026）
            if self.year and not self.all_years:
                if f'{self.year}' not in it['title']:
                    continue
            # include/exclude 关键词过滤（2026 + 建设工程材料价格信息 + 排除勘误等）
            include, reason = _legacy.should_include(it, self.cfg)
            if not include:
                continue
            filtered.append(it)

        print(f'[collector] 列表 {len(all_items)} 条 → 过滤后 {len(filtered)} 条')

        # 3. 排除本地已 done
        todo = [it for it in filtered if not self.progress.is_done(it['detail_url'])]

        # 4. latest: 只取第一个
        if self.latest:
            todo = todo[:1]

        # 5. 拼成 unit dict（含 period 窗口字段）
        units = []
        for it in todo:
            win = _legacy.parse_period_from_title(it['title'])
            if not win or win.get('invalid'):
                print(f"  [warn] 跳过无法解析期号的条目: {it['title']!r}")
                continue
            unit = {
                'period':       win['period'],
                'period_start': win['period_start'],
                'period_end':   win['period_end'],
                'period_days':  win['period_days'],
                'title':        it['title'],
                'publish_date': it['publish_date'],
                'detail_url':   it['detail_url'],
                'page':         it.get('page', 0),
                # pdf_url / pdf_name 在 _process_one 阶段按需抓详情页
            }
            units.append(unit)
        return units

    def _process_one(self, unit: dict) -> tuple[int, str]:
        """处理单个工作单元：抓详情 → 下载 PDF → MinIO → 解析 → bulk_index。

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

            # 1. 抓详情页,提取 PDF URL
            detail_html = _legacy.fetch_html(
                unit['detail_url'],
                headers=_legacy.get_headers(self.cfg),
                timeout=self.cfg['site']['timeout_sec'],
            )
            pdf_info = _legacy.parse_detail_page(detail_html, unit['detail_url'])
            if not pdf_info.get('pdf_url'):
                print(f"  ✗ 详情页未找到 PDF 链接: {unit['detail_url']}")
                return 0, 'error'
            unit['pdf_url'] = pdf_info['pdf_url']
            unit['pdf_name'] = pdf_info['pdf_name']

            # 2. 下载 PDF
            try:
                download_file(unit['pdf_url'], local_pdf, timeout=120)
            except Exception as e:
                print(f"  ✗ 下载 PDF 失败: {e}")
                return 0, 'error'

            # 3. 上传 MinIO
            minio_key = f"{cfg_minio['prefix']}/{unit['pdf_name']}"
            unit['minio_key'] = minio_key
            try:
                upload_to_minio(
                    self.s3, cfg_minio['bucket'], minio_key, local_pdf,
                )
            except Exception as e:
                print(f"  ✗ 上传 MinIO 失败: {e}")
                return 0, 'error'

            # 4. PDF 解析（best-effort）
            try:
                pdf_rows = _legacy.parse_pdf_tables(local_pdf)
            except Exception as e:
                print(f"  ✗ PDF 解析失败: {e}")
                return 0, 'error'

            # 5. 构造 docs
            now = datetime.now().isoformat(timespec='seconds')
            docs = []
            if pdf_rows:
                for r in pdf_rows:
                    docs.append(_legacy.row_to_doc(r, {
                        'period':        unit['period'],
                        'period_start':  unit['period_start'],
                        'period_end':    unit['period_end'],
                        'period_days':   unit['period_days'],
                        'publish_date':  unit['publish_date'],
                        'pdf_url':       unit['pdf_url'],
                        'minio_key':     minio_key,
                    }))
            else:
                # PDF 解析失败 — 插 1 条 placeholder 标记已归档
                docs.append({
                    'period':        unit['period'],
                    'period_start':  unit['period_start'],
                    'period_end':    unit['period_end'],
                    'period_days':   unit['period_days'],
                    'breed': '', 'spec': '', 'unit': '',
                    'price': 0.0,
                    'city': _legacy.PROVINCE, 'province': _legacy.PROVINCE,
                    'update_date':   unit['publish_date'],
                    'create_time':   now,
                    'source_pdf':    minio_key,
                    'source_url':    unit['pdf_url'],
                    'parse_status':  'unparsed',
                })

            # 6. bulk_index
            ok, err = _legacy.bulk_index(self.es, self.es_index, docs)
            if err > 0:
                print(f"  ⚠ bulk 写入部分失败: ok={ok}, err={err}")
            return ok, 'completed'

    def _on_unit_done(self, unit: dict, docs_count: int, status: str,
                      error: str = '') -> None:
        """完成后：写 ES progress + 保存本地进度（参考 chongqing v0.8）。"""
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
                        'pdf_url':       unit.get('pdf_url', ''),
                        'minio_key':     unit.get('minio_key', ''),
                        'docs_written':  docs_count,
                        'status':        'ok' if status == 'completed' else 'error',
                        'error':         error,
                        'run_id':        self.run_id,
                        'created_at':    datetime.now().isoformat(timespec='seconds'),
                    },
                )
            except Exception as e:
                print(f"  ⚠ 写 ES progress 失败: {e}")

        # 保存本地进度（ETL LocalProgressStore.is_done 检查 list 非空）
        if status == 'completed':
            try:
                progress = self.progress.load()
                key = self._compute_unit_key(unit)
                bucket = progress.setdefault(key, [])
                marker = 'ok' if status == 'completed' else 'error'
                if marker not in bucket:
                    bucket.append(marker)
                self.progress.save(progress)
            except Exception as e:
                print(f"  ⚠ 保存本地进度失败: {e}")

        icon = '✓' if status == 'completed' else '✗'
        print(
            f"  [{icon}] {unit['period']} {unit['period_start']}~{unit['period_end']} "
            f"({unit['period_days']}天) {unit['title'][:40]}... "
            f"→ {docs_count} docs"
        )

    def _compute_unit_key(self, unit: dict) -> str:
        """本地进度 key = unit.detail_url（一期 = 一个 detail_url）。"""
        return unit['detail_url']

    # ── 私有方法 ──

    def _ensure_indices(self) -> None:
        """确保 ODS + progress 索引存在（套用 ETL 共享 mapping）。

        shanxi 特化：scan 型 PDF, 占位符需要 `parse_status` 字段区分。
        ETL 默认 ODS mapping 是 strict, 必须先声明字段才能写。
        """
        from gov_price_etl.mappings import (
            build_ods_mapping, build_progress_mapping,
        )
        # shanxi 特化字段：parse_status 用于标识扫描 PDF 未解析占位
        city_ext = {
            'parse_status': {'type': 'keyword'},  # unparsed / partial / ok
        }
        if not self.es.indices.exists(index=self.es_index):
            self.es.indices.create(
                index=self.es_index,
                body=build_ods_mapping(city_extension=city_ext),
            )
        else:
            # 索引已存在: PUT mapping 增量加字段（strict 模式下必须先声明）
            try:
                self.es.indices.put_mapping(
                    index=self.es_index,
                    body={'properties': city_ext},
                )
            except Exception as e:
                print(f'  ⚠ put_mapping 失败（可能是字段已存在）: {e}')
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
    all_years: bool = False,
) -> ShanxiCollector:
    """从 config.yml 构造 ShanxiCollector。

    用法（sync.py 默认路径）：
        collector = make_collector(cfg_path, run_id, year=2026)
        result = collector.run()
    """
    import yaml
    with open(cfg_path, encoding='utf-8') as f:
        cfg = yaml.safe_load(f) or {}
    return ShanxiCollector(
        cfg=cfg, run_id=run_id, year=year, period=period,
        latest=latest, all_years=all_years,
    )