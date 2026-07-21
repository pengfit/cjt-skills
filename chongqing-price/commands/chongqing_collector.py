"""chongqing_collector.py - chongqing 默认同步路径（v0.9 默认, 2026-07-02）

将 chongqing v3 的 cmd_sync 主流程用 SyncRunner 抽象基类重构，2026-07-02 起
切为 sync.py 默认路径。已在 2026-07-02 生产试跑 1 次（run_id=v08_pilot_full_20260702，
5 个月全量：district + mortar + citywide）。

已知非问题（原网站结构）：
- citywide 下的「装配式建筑工程成品构件」+「城市轨道交通工程材料」两个分类
  在原网站页面存在但未发布任何材料数据，collector 抓取为空属预期（不是 bug）

设计：
- 继承 gov_price_etl.collectors.base.SyncRunner
- 重写 _list_work_units()：扁平化 (source, item, period) 三元组
- 重写 _process_one()：浏览器点击 + 抓数据 + 写 ES
- 重写 _compute_unit_key()：本地进度 key = 'done_<source>_<period>' 列表项

迁移收益：
- 主流程结构与原 cmd_sync 等价，但解耦到 SyncRunner 基类
- 通用基础设施（SIGINT / 进度 / 汇总）由基类提供
- 未来加新城市可直接复用 SyncRunner 框架
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


import json
import os
import sys
import time
from typing import Optional, List

# 复用 chongqing v3 的工具函数（浏览器 API / 解析 / ES 写入）
_ETL_PROJECT_ROOT = _resolve_etl_root()
if _ETL_PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _ETL_PROJECT_ROOT)

from gov_price_etl.collectors.base import (
    LocalProgressStore,
    SyncRunner,
)

# 复用 chongqing v3 的所有工具函数（不重写）
import write_es as _w  # 同目录 commands/write_es.py


# ─────────────────────────────────────────────────────────────
# ChongqingCollector - chongqing v3 的 SyncRunner 化版本
# ─────────────────────────────────────────────────────────────

class ChongqingCollector(SyncRunner):
    """重庆工程造价材料采集器（v0.8 试点，SyncRunner 化）。

    工作单元形状：(source, item, period) 三元组
        source:  'district' | 'mortar' | 'citywide'
        item:    区县名（district/mortar）或 category 名（citywide）
        period:  '2026年05月' 等业务期

    浏览器初始化（点击 source tab + 选月份）缓存在 _initialized_sources
    字典里，避免每个 unit 重复初始化（与原 _run_sync_source 等价）。
    """

    def __init__(
        self,
        cfg: dict,
        tab_id: str,
        run_id: str,
        periods: list[str],
        sources: list[str] = ("district", "mortar", "citywide"),
    ):
        progress_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            ".chongqing_sync_progress.json",
        )
        super().__init__(
            progress=LocalProgressStore(progress_path),
            es_host=cfg["es"]["host"],
            es_index=cfg["es"]["index"],
            progress_index=cfg["es"]["progress_index"],
        )
        self.cfg = cfg
        self.tab_id = tab_id
        self.run_id = run_id
        self.periods = periods
        self.sources = sources
        # 浏览器初始化缓存：{(source, period): bool}
        self._initialized: dict[tuple[str, str], bool] = {}

    # ── SyncRunner 钩子实现 ──

    def _list_work_units(self) -> list[tuple[str, str, str]]:
        """扁平化所有工作单元：(source, item, period)。

        例：35 county × 3 source × 5 period = 525 units
        """
        units = []
        progress = self.progress.load()  # 读本地进度用于过滤
        for period in self.periods:
            for source in self.sources:
                done_key = f"done_{source}_{period}"
                done = set(progress.get(done_key, []))
                for item in self._items_for(source):
                    if item in done:
                        continue
                    units.append((source, item, period))
        return units

    def _process_one(self, unit: tuple[str, str, str]) -> tuple[int, str]:
        """处理单个工作单元：浏览器初始化 → 抓数据 → 写 ES → 报告进度。

        与原 _run_sync_source 内的 unit 处理逻辑等价。
        返回 (docs_count, status)，status ∈ {'completed', 'error'}。
        """
        source, item, period = unit
        cfg = _w.SOURCE_CONFIG.get(source, {})
        div_id = cfg.get("div_id", "")

        # 1. 浏览器初始化（按 (source, period) 缓存，避免重复点击）
        init_key = (source, period)
        if not self._initialized.get(init_key):
            if not self._init_browser_for_source(source, div_id):
                return 0, "error"
            month_num = self._parse_month_from_period(period)
            if not _w._select_month(month_num, source):
                return 0, "error"
            time.sleep(1)
            self._initialized[init_key] = True

        # 2. 点击 item（区县 / category）
        if source == "citywide":
            county_for_write = "主城区"
            if not _w._click_category(item, div_id):
                return 0, "error"
            time.sleep(_w.random.randint(3, 5))
        else:
            county_for_write = item
            if not _w._click_county(item, source):
                return 0, "error"
            time.sleep(_w.random.randint(3, 5))

        # 3. 抓所有页（等 AJAX + 翻页 + 累加）
        all_rows = self._extract_all_pages(source)
        if all_rows is None:
            return 0, "error"

        # 4. 检查空数据（原站该分类无任何条目）
        # 例：chongqing citywide 下「装配式建筑工程成品构件」和「城市轨道交通工程材料」
        # 原网站页面存在但未发布任何材料数据，collector 抓不到不算 error
        if not all_rows:
            print(f"  [skipped] {item} [{source}/{period}]：原站无数据，跳过")
            return 0, "skipped"

        # 5. 写 ES
        n = _w.cmd_write(
            self.run_id, county_for_write, period,
            json.dumps({"rows": all_rows}),
            source=source,
            category=(item if source == "citywide" else ""),
        )
        return n, ("completed" if n > 0 else "error")

    def _on_unit_done(self, unit, docs_count: int, status: str, error: str = "") -> None:
        """重写钩子：完成后写 ES progress + 保存本地进度（与原 _run_sync_source 等价）。"""
        source, item, period = unit
        duration = 0.0  # 简化：原代码在循环内 t0/t1 计时，本类在 _process_one 内不重计
        _w.cmd_progress(self.run_id, item, period, 1, 1, docs_count, status, error, duration, source)

        # 保存本地进度
        progress = self.progress.load()
        done_key = f"done_{source}_{period}"
        progress.setdefault(done_key, [])
        if item not in progress[done_key]:
            progress[done_key].append(item)
        self.progress.save(progress)

        icon = "✓" if status == "completed" else "✗"
        print(f"  [{icon}] {item} [{source}/{period}]: {docs_count} docs ({status})")

    def _compute_unit_key(self, unit) -> str:
        """本地进度 key：done_<source>_<period> 列表项。

        chongqing v3 的 _save_progress_all 用 `prog[done_key].append(item)`，
        所以 is_done 检查列表是否包含 item。
        """
        source, item, period = unit
        return f"done_{source}_{period}__{item}"

    # ── 私有方法（不暴露给 SyncRunner） ──

    def _items_for(self, source: str) -> list[str]:
        """返回 source 对应的所有 item（区县 / category）。"""
        cfg = _w.SOURCE_CONFIG.get(source, {})
        if source == "citywide":
            return cfg.get("categories", [])
        return cfg.get("counties", [])

    def _parse_month_from_period(self, period: str) -> Optional[str]:
        """'2026年05月' → '05'"""
        import re
        m = re.search(r"(\d{1,2})月", period)
        if m:
            return m.group(1).zfill(2)
        return None

    def _init_browser_for_source(self, source: str, div_id: str) -> bool:
        """浏览器初始化：聚焦 tab + 点击材料信息价 + 点击 source tab。

        与原 _run_sync_source 的初始化部分等价（不含 _select_month）。
        """
        if not _w._focus_tab(self.tab_id):
            print(f"[!] 聚焦标签页失败")
            return False
        if not _w._click_material_price_tab():
            print(f"[!] 点击材料信息价标签页失败")
            return False
        time.sleep(2)
        if not _w._click_source_tab(source):
            print(f"[!] 点击子tab失败: {source}")
            return False
        time.sleep(2)
        return True

    def _extract_all_pages(self, source: str) -> Optional[list]:
        """抓所有分页数据（AJAX 等待 + 翻页累加）。

        Returns:
            list: 抓到的 rows。**可能为空**，意味着该分类下原站没发布数据，应被
                  上层 collector 当作 skipped（不是 error）。
            None: AJAX 未响应 / tbody 没渲染 / 点击失败等真错误。

        与原 _run_sync_source 的 _extract_page 循环等价，但区分了：
          * 原站「未发布」→ tbody 存在但 0 行 → 返回 []
          * 抓取层「未响应」→ {err: 'no tbody' / 'no tab'} → 返回 None
        """
        # 等 AJAX 响应
        last_data: Optional[dict] = None
        for _ in range(15):
            data = _w._extract_page(source)
            last_data = data
            rows = data.get("rows", [])
            if rows:
                break
            time.sleep(1)
        else:
            # 15s 还没 rows：分两种情况
            if last_data and last_data.get("err"):
                return None  # AJAX 没响应（真错误）
            return []  # tbody 渲染了但站点下没数据（合法 skipped）

        all_rows = []
        page = 1
        while page <= 50:
            data = _w._extract_page(source)
            rows = data.get("rows", [])
            total_pages = data.get("totalPages", 1)
            has_next = data.get("hasNext", False)
            all_rows.extend(rows)
            print(f"  page {page}/{total_pages}: +{len(rows)} rows")

            if page >= total_pages or not has_next:
                break

            if not _w._click_next(source):
                break
            next_page = page + 1
            for _ in range(12):
                time.sleep(1)
                data2 = _w._extract_page(source)
                if data2.get("currentPage") == next_page:
                    break
            page = next_page

        return all_rows


# ─────────────────────────────────────────────────────────────
# 工厂方法
# ─────────────────────────────────────────────────────────────

def make_collector(
    cfg_path: str,
    tab_id: str,
    periods: list[str],
    run_id: str,
    sources: Optional[list[str]] = None,
) -> ChongqingCollector:
    """从 config.yml 构造 ChongqingCollector。

    用法（sync.py 默认路径）：
        cfg = load_config(cfg_path)
        collector = make_collector(cfg_path, tab_id, periods, run_id, sources=sources)
        result = collector.run()
        # result = {total, done, failed, skipped, docs_written, duration_sec, interrupted}

    Args:
        sources: 限定 source 列表（None=默认 3 sources）。
    """
    # 委托到 chongqing utils.py 的 load_config（避免重新实现）
    import sys as _sys
    cmds_dir = os.path.dirname(os.path.abspath(__file__))
    if cmds_dir not in _sys.path:
        _sys.path.insert(0, cmds_dir)
    import utils
    cfg = utils.load_config(cfg_path)
    return ChongqingCollector(
        cfg=cfg,
        tab_id=tab_id,
        run_id=run_id,
        periods=periods,
        sources=sources or ("district", "mortar", "citywide"),
    )