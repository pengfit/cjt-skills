"""jinan-price/commands/jinan_collector.py

济南材料价格采集器（v0.1, 2026-07-03）。

参考 chongqing-price v0.9 模式，继承 gov_price_etl.collectors.base.SyncRunner。
工作单元形状：(period_id, period_name, cat_id, cat_name) 四元组。

设计：
- 初始化时一次拿全所有 2026 periods + 41 个 leaf catalogue
- _list_work_units() 笛卡尔积 = 5 periods × 41 cats = 205 units
- _process_one() 拉该 (period, cat) 下所有分页 → 写 ES
- _compute_unit_key() = "done_<period_id>_<cat_id>"

断点续传：LocalProgressStore 持久化已完成 key。
SIGINT：基类 SignalHandler 自动管理。
"""
from __future__ import annotations

import os
import re
import sys
import time
from typing import List, Optional, Tuple

# 复用 chongqing v3 / gov-price-etl 的基类
_ETL_PROJECT_ROOT = "/Users/pengfit/.openclaw/workspace/skills/gov-price-etl"
if _ETL_PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _ETL_PROJECT_ROOT)

from gov_price_etl.collectors.base import LocalProgressStore, SyncRunner  # noqa: E402

# 同目录工具
from commands.utils import (  # noqa: E402
    JinAnSiteSession,
    ensure_index,
    ensure_progress_index,
    load_config,
)
from commands import write_es  # noqa: E402


# 工作单元形状：4 元组
Unit = Tuple[str, str, str, str]  # (period_id, period_name, cat_id, cat_name)


# ─────────────────────────────────────────────────────────────
# JinanCollector - 济南材料价格采集器
# ─────────────────────────────────────────────────────────────

class JinanCollector(SyncRunner):
    """济南工程造价材料信息采集器（v0.1, 2026-07-03）。

    工作单元：(period_id, period_name, catalogue_id, catalogue_name)
    一次拉全 (period × catalogue) 下所有分页。
    """

    def __init__(
        self,
        cfg: dict,
        run_id: str,
        periods: Optional[List[Tuple[str, str]]] = None,
        data_type: str = '2',
        dry_run: bool = False,
    ):
        progress_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            ".jinan_sync_progress.json",
        )
        super().__init__(
            progress=LocalProgressStore(progress_path),
            es_host=cfg['es']['host'],
            es_index=cfg['es']['index'],
            progress_index=cfg['es'].get('progress_index', 'ods_material_jinan_price_sync_progress'),
        )
        self.cfg = cfg
        self.run_id = run_id
        self.data_type = data_type
        self.dry_run = dry_run
        self.size_per_page = cfg.get('sync', {}).get('size_per_page', 100)
        # 显式传入的 periods（[(period_id, period_name), ...]）
        self._periods_arg = periods
        # lazy init
        self._session: Optional[JinAnSiteSession] = None
        self._periods: Optional[List[Tuple[str, str]]] = None
        self._cat_ids: Optional[List[str]] = None
        self._cat_id_to_name: dict = {}

    # ── SyncRunner 钩子 ──

    def _list_work_units(self) -> List[Unit]:
        # 第一次调用时确保 ES 索引 mapping 正确（后续跳过）
        if not self.dry_run and not getattr(self, '_index_ensured', False):
            ensure_index(self.es_host, self.es_index)
            ensure_progress_index(
                self.es_host, self.progress_index,
                city_extension={
                    "period_id":      {"type": "keyword"},
                    "catalogue_id":   {"type": "keyword"},
                    "catalogue_name": {"type": "keyword"},
                    "city":           {"type": "keyword"},
                    "province":       {"type": "keyword"},
                },
            )
            self._index_ensured = True
        session = self._get_session()
        periods = self._periods or self._fetch_periods(session)
        cat_ids = self._cat_ids or session.get_all_catalogue_ids(self.data_type)
        # 缓存 catalogue id → name
        if not self._cat_id_to_name:
            for cid in cat_ids:
                self._cat_id_to_name[cid] = session.find_catalogue_name_by_id(cid, self.data_type) or cid

        units: List[Unit] = []
        for period_id, period_name in periods:
            for cat_id in cat_ids:
                key = self._unit_key(period_id, cat_id)
                if self.progress.is_done(key):
                    continue
                cat_name = self._cat_id_to_name.get(cat_id, cat_id)
                units.append((period_id, period_name, cat_id, cat_name))
        return units

    def _process_one(self, unit: Unit) -> Tuple[int, str]:
        period_id, period_name, cat_id, cat_name = unit
        session = self._get_session()

        # 1. 抓第一页拿总数
        first = session.fetch(period_id, cat_id, page=1, size=self.size_per_page, data_type=self.data_type)
        if first is None:
            return 0, "error"
        records = first.get('records') or []
        total = first.get('total') or 0
        if not records and total == 0:
            return 0, "skipped"  # 该 (period, cat) 无数据

        total_pages = (total + self.size_per_page - 1) // self.size_per_page if total else 1
        all_docs = [write_es.make_doc(r, cat_id, cat_name, period_name, period_id) for r in records]

        # 2. 翻页（如果 > 1 页）
        page = 2
        while page <= total_pages:
            time.sleep(0.5)  # 礼貌限速
            data = session.fetch(period_id, cat_id, page=page, size=self.size_per_page, data_type=self.data_type)
            if not data:
                break
            for r in (data.get('records') or []):
                all_docs.append(write_es.make_doc(r, cat_id, cat_name, period_name, period_id))
            page += 1

        # 3. bulk 写 ES（dry_run 时只统计不实际写入）
        n = write_es.bulk_write(
            self.es_host, self.es_index, all_docs,
            run_id=self.run_id, dry_run=self.dry_run,
        )
        return n, ("completed" if n > 0 else "error")

    def _on_unit_done(self, unit, docs_count: int, status: str, error: str = "") -> None:
        period_id, period_name, cat_id, cat_name = unit
        icon = "✓" if status == "completed" else ("⊘" if status == "skipped" else "✗")
        prefix = "[DRY-RUN] " if self.dry_run else ""
        print(f"  {prefix}[{icon}] {period_name} | {cat_name}: {docs_count} docs ({status})")

        # ES 端 progress 上报（dry_run 时也写一份，方便回放）
        write_es.write_progress(
            self.es_host, self.progress_index, self.run_id,
            period=period_name, period_id=period_id,
            catalogue_id=cat_id, catalogue_name=cat_name,
            page=1, total_pages=1, docs_count=docs_count,
            status=("dry_run" if self.dry_run and status == "completed" else status),
            duration_sec=0.0, error=error,
        )

        # 本地进度：标记 unit 完成（断点续传依据，参考 chongqing v0.9）
        if not self.dry_run:
            progress = self.progress.load()
            key = self._unit_key(period_id, cat_id)
            progress.setdefault(key, [])
            if 'done' not in progress[key]:
                progress[key].append('done')
            self.progress.save(progress)

    def _compute_unit_key(self, unit) -> str:
        period_id, period_name, cat_id, cat_name = unit
        return self._unit_key(period_id, cat_id)

    # ── 私有方法 ──

    def _unit_key(self, period_id: str, cat_id: str) -> str:
        return f"done_{period_id}_{cat_id}"

    def _get_session(self) -> JinAnSiteSession:
        if self._session is None:
            print("[i] 初始化济南网站 Session（Playwright）...")
            self._session = JinAnSiteSession()
        return self._session

    def _fetch_periods(self, session: JinAnSiteSession) -> List[Tuple[str, str]]:
        """获取要同步的周期列表 [(period_id, period_name), ...]

        优先用构造时传入的 periods；否则从 session 拉所有周期，
        再用 config.sync.periods 名称列表过滤（白名单）。
        """
        if self._periods_arg:
            self._periods = self._periods_arg
            return self._periods

        # 从 config 拿白名单
        whitelist_names = self.cfg.get('sync', {}).get('periods', [])
        all_periods_raw = session.get_all_periods()
        all_periods = [(str(p.get('id')), p.get('periodName', '')) for p in all_periods_raw]

        if whitelist_names:
            # 按名称白名单过滤（精确匹配）
            wl = set(whitelist_names)
            filtered = [(pid, pn) for pid, pn in all_periods if pn in wl]
            if not filtered:
                # 兜底：尝试宽松匹配（如 "2026年05月" 也能匹配 "2026年05月材料价格信息"）
                filtered = [(pid, pn) for pid, pn in all_periods
                            if any(pn.startswith(w) for w in wl)]
            self._periods = filtered
        else:
            # 没白名单：拉所有
            self._periods = all_periods
        return self._periods


# ── 工厂方法 ──────────────────────────────────────────────

def make_collector(
    cfg_path: str,
    run_id: str,
    periods: Optional[List[Tuple[str, str]]] = None,
    dry_run: bool = False,
) -> JinanCollector:
    """从 config.yml 构造 JinanCollector。

    用法（sync.py 默认路径）：
        collector = make_collector(cfg_path, run_id, periods, dry_run=dry_run)
        result = collector.run()
    """
    cfg = load_config(cfg_path)
    return JinanCollector(
        cfg=cfg,
        run_id=run_id,
        periods=periods,
        data_type=cfg.get('site', {}).get('data_type', '2'),
        dry_run=dry_run,
    )
