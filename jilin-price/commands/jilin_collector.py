"""jilin_collector.py - 吉林默认同步路径（v0.1, 2026-07-07）

参考 chongqing v0.9（SyncRunner 化）和 heze v0.8 模式，但吉林是纯 HTTP
GET 站点（不需要浏览器自动化）。

源站特性：
- URL: http://www.jlszjw.com/city/price_list.php
- 查询字符串按 GBK 编码（不是 UTF-8）
- 字段：地区、时间、名称、规格、单位、除税价、含税价、备注
- 一页 20 条记录
- 按月分页（price_time=YYYY年M月份 + page=N）

工作单元：(period, diqu) 元组
  period: '2026年1月份' 等业务期号
  diqu: '' (吉林市整体) / '吉林市-永吉县' 等

业务期窗口（period 模式标准字段）：
  period_start: '2026-01-01'
  period_end:   '2026-01-31'
  period_days:  31

名称清洗：
  "（2025年补充）干混抹灰砂浆" → "干混抹灰砂浆"
  （道友明确要求：只保留核心名称）
"""
from __future__ import annotations


def _resolve_etl_root():
    """解析 gov-price-etl 项目根路径。"""
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
import json
import os
import re
import sys
from datetime import datetime
from typing import List, Tuple

import requests

# 复用 SyncRunner 基类
_ETL_PROJECT_ROOT = _resolve_etl_root()
if _ETL_PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _ETL_PROJECT_ROOT)

from gov_price_etl.collectors.base import (
    LocalProgressStore,
    SyncRunner,
)
from gov_price_etl.indexer import ensure_progress_index

# 同目录 utils
import utils as _u


# ─────────────────────────────────────────────────────────────
# period 窗口解析
# ─────────────────────────────────────────────────────────────

PERIOD_RE = re.compile(r"(\d{4})年(\d{1,2})月份?")


def parse_period_window(period: str) -> dict:
    """'2026年1月份' → {period, period_start, period_end, period_days}"""
    m = PERIOD_RE.search(period or "")
    if not m:
        return {"period": "", "period_start": "", "period_end": "", "period_days": 0}
    y, n = int(m.group(1)), int(m.group(2))
    if not (1 <= n <= 12):
        return {"period": "", "period_start": "", "period_end": "", "period_days": 0}
    last_day = calendar.monthrange(y, n)[1]
    return {
        "period": period,
        "period_start": f"{y:04d}-{n:02d}-01",
        "period_end": f"{y:04d}-{n:02d}-{last_day:02d}",
        "period_days": last_day,
    }


# ─────────────────────────────────────────────────────────────
# JilinCollector
# ─────────────────────────────────────────────────────────────

class JilinCollector(SyncRunner):
    """吉林工程造价材料采集器。

    源站特性（重要）：
      - price_time 是精确匹配（如 "2026年1月份" 只返回 2026-01 月份数据）。
      - 一页 20 条。翻页终止："rows < page_size" 或 "page=1 无数据"。
      - 不传 price_time 时全量（7566 页），传了之后数据量锐减（46 页/月左右）。
    同步策略（按月切分）：
      每个月 1 个 unit：(period, diqu) 元组。
      默认按 diqu=空 跑遍 7 个月，每月 1-50 页，全量 < 350 页。
      客户端按 year 过滤（道友要求只保留 2026 年）。
    """

    def __init__(
        self,
        cfg: dict,
        run_id: str,
        year: int = 2026,
        diqu: str = "",
        max_month: int = 0,
    ):
        progress_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            ".jilin_sync_progress.json",
        )
        super().__init__(
            progress=LocalProgressStore(progress_path),
            es_host=cfg["es"]["host"],
            es_index=cfg["es"]["index"],
            progress_index=cfg["es"]["progress_index"],
        )
        self.cfg = cfg
        self.run_id = run_id
        self.year = year
        self.diqu = diqu
        self.max_month = max_month
        self.session = None  # lazy
        self.es = None  # lazy

    # ── SyncRunner 钩子实现 ──

    def _list_work_units(self) -> List[Tuple[str, str]]:
        """按月份铺开工作单元。每个月 1 个 unit。"""
        now = datetime.now()
        last_m = self.max_month if self.max_month > 0 else now.month
        units = []
        for m in range(1, last_m + 1):
            period = f"{self.year}年{m}月份"
            units.append((period, self.diqu))
        return units

    def _process_one(self, unit: Tuple[str, str]) -> tuple[int, str]:
        """抓 1 个月数据：分页抓所有页 → 解析 → 清洗 → 写 ES。

        Returns:
            (docs_count, status) — status ∈ {'completed', 'error'}。
        """
        period, diqu = unit

        # 0. 懒加载
        if self.session is None:
            self.session = requests.Session()
            r = self.session.get(
                self.cfg["site"]["base_url"] + f"?city={self.cfg['site']['city_id']}",
                headers=utils_headers(),
                timeout=self.cfg.get("sync", {}).get("request_timeout", 30),
            )
            r.raise_for_status()
        if self.es is None:
            self.es = requests  # 用 requests 直接调 bulk API（最简）
            self._ensure_indices()

        # 1. 翻页抓数据（price_time 精确匹配）
        max_retries = self.cfg.get("sync", {}).get("max_retries", 3)
        timeout = self.cfg.get("sync", {}).get("request_timeout", 30)
        page = 1
        all_rows = []
        consecutive_empty = 0
        while page <= 500:  # 单月防护上限（实测每月份 < 50 页）
            try:
                html = _u.fetch_list_page(
                    self.session,
                    base_url=self.cfg["site"]["base_url"],
                    city_id=self.cfg["site"]["city_id"],
                    diqu=diqu,
                    price_time=period,
                    page=page,
                    timeout=timeout,
                    max_retries=max_retries,
                )
            except Exception as e:
                print(f"  ✗ 抓 {period} page={page} 失败: {e}")
                if page == 1:
                    return 0, "error"
                break

            rows = _u.parse_rows(html)
            if not rows:
                consecutive_empty += 1
                if consecutive_empty >= 1 or page == 1:
                    break
                page += 1
                continue
            consecutive_empty = 0
            all_rows.extend(rows)
            print(f"  page {page}: +{len(rows)} rows (累计 {len(all_rows)})")

            # 末页判断：rows < 20 = 末页
            if len(rows) < self.cfg.get("sync", {}).get("page_size", 20):
                break
            page += 1

        if not all_rows:
            print(f"  [skip] {period}: 无数据（可能尚未发布）")
            return 0, "completed"

        # 客户端防串（源站偶尔会出现 period 不严格匹配的情况）
        all_rows = [r for r in all_rows if r.get("period", "") == period]
        if not all_rows:
            print(f"  [skip] {period}: 客户端过滤后无数据")
            return 0, "completed"

        # 3. 构造 docs（按 period 分组，每组写一条 progress）
        from collections import defaultdict
        per_period = defaultdict(list)
        for r in all_rows:
            per_period[r["period"]].append(r)

        now_iso = datetime.now().isoformat(timespec="seconds")
        all_docs = []
        for period, p_rows in per_period.items():
            win = parse_period_window(period)
            for r in p_rows:
                county_clean = _u.normalize_county(r["county"], city=self.cfg["site"]["city_name"])
                all_docs.append({
                    "breed": r["breed"],                # 清洗后品种名（去括号前缀）
                    "breed_clean": r["breed_clean"],    # 拆分后品种名（去末尾型号/规格）
                    "breed_raw": r["breed_raw"],        # 源站原文（调试/追溯）
                    "spec": r["spec"],
                    "unit": r["unit"],
                    "price": r["price"] or 0.0,
                    "tax_price": r["tax_price"] or 0.0,
                    "is_tax": "含税" if (r["tax_price"] or 0) > 0 else "不含税",
                    "period": period,
                    "period_start": win["period_start"],
                    "period_end": win["period_end"],
                    "period_days": win["period_days"],
                    "province": "吉林",
                    "city": "吉林市",
                    "county": county_clean,
                    "remarks": r.get("remarks", ""),
                    "update_date": win["period_end"],
                    "create_time": now_iso,
                    "source": "jlszjw",
                })

        docs = all_docs

        # 4. bulk_index
        ok, err = self._bulk_index(docs)
        if err > 0:
            print(f"  ⚠ bulk 写入部分失败: ok={ok}, err={err}")
        return ok, "completed"

    def _on_unit_done(self, unit, docs_count: int, status: str, error: str = "") -> None:
        """完成后写 ES progress + 保存本地进度。"""
        period, diqu = unit
        now_iso = datetime.now().isoformat(timespec="seconds")
        win = parse_period_window(period)
        # dashboard prefix 查询需要 period 以 "2026." 开头。
        period_dash = _u.to_dashboard_period(period)

        # 本地进度
        progress = self.progress.load()
        done_list = progress.setdefault("done", [])
        key = f"{diqu}|{period}"
        if key not in done_list:
            done_list.append(key)
        self.progress.save(progress)

        # ES progress（只用标准 progress mapping 字段，避免 strict dynamic 拒绝）
        progress_doc = {
            "run_id": self.run_id,
            "period": period_dash,  # dashboard 格式
            "period_start": win["period_start"],
            "period_end": win["period_end"],
            "period_days": win["period_days"],
            "status": status,
            "docs_written": docs_count,
            "current_page": 0,
            "total_pages": 0,
            "duration_sec": 0.0,
            "last_updated": now_iso,
            "error": error,
        }
        try:
            _id = f"{self.run_id}__{diqu}__{period}"
            self.es.put(
                f"{self.es_host}/{self.progress_index}/_doc/{_id}",
                json=progress_doc,
                headers={"Content-Type": "application/json"},
                timeout=15,
            )
        except Exception as e:
            print(f"  [warn] 写 progress 失败: {e}")

        icon = "✓" if status == "completed" else "✗"
        print(f"  [{icon}] {period} (diqu={diqu or '吉林市'}): {docs_count} docs")

    def _compute_unit_key(self, unit) -> str:
        period, diqu = unit
        return f"{diqu}|{period}"

    # ── 私有方法 ────────────────────────────────────────────────

    def _ensure_indices(self) -> None:
        """确保 ODS 索引和 progress 索引存在。"""
        # ODS
        if not _index_exists(self.es_host, self.es_index):
            mapping = _build_ods_mapping()
            r = self.es.put(
                f"{self.es_host}/{self.es_index}",
                json=mapping,
                headers={"Content-Type": "application/json"},
                timeout=15,
            )
            if r.status_code not in (200, 201):
                print(f"  [warn] 创建 {self.es_index} 失败: {r.status_code}")
            else:
                print(f"  [idx] 创建 ODS {self.es_index} 成功")
        # progress（用 etl 的标准模板）
        try:
            ensure_progress_index(self.es_host, self.progress_index)
        except Exception as e:
            print(f"  [warn] 创建 progress 失败: {e}")

    def _bulk_index(self, docs: list) -> tuple[int, int]:
        """bulk 写入 ES。返回 (成功数, 失败数)。"""
        if not docs:
            return 0, 0
        bulk = ""
        for doc in docs:
            # _id = province + period + county + breed + spec + price（幂等重跑）
            _id = _doc_id(doc)
            bulk += json.dumps({"index": {"_index": self.es_index, "_id": _id}}, ensure_ascii=False) + "\n"
            bulk += json.dumps(doc, ensure_ascii=False) + "\n"
        try:
            r = self.es.post(
                f"{self.es_host}/_bulk",
                data=bulk.encode("utf-8"),
                headers={"Content-Type": "application/x-ndjson"},
                timeout=120,
            )
        except Exception as e:
            print(f"  [error] bulk 请求失败: {e}")
            return 0, len(docs)
        if r.status_code not in (200, 201):
            print(f"  [error] bulk 响应 {r.status_code}: {r.text[:200]}")
            return 0, len(docs)
        items = r.json().get("items", [])
        ok = sum(1 for it in items if it.get("index", {}).get("result") in ("created", "updated"))
        err = len(items) - ok
        return ok, err


# ─────────────────────────────────────────────────────────────
# 工厂方法
# ─────────────────────────────────────────────────────────────

def make_collector(cfg_path: str, run_id: str, year: int = 2026, diqu: str = "", max_month: int = 0) -> JilinCollector:
    cfg = _u.load_config(cfg_path)
    return JilinCollector(
        cfg=cfg,
        run_id=run_id,
        year=year,
        diqu=diqu,
        max_month=max_month,
    )


# ─────────────────────────────────────────────────────────────
# 模块级辅助函数
# ─────────────────────────────────────────────────────────────

def utils_headers() -> dict:
    """utils 默认 headers（_process_one 中懒加载 session 用）。"""
    return dict(_u.DEFAULT_HEADERS)


def _index_exists(es_host: str, idx: str) -> bool:
    try:
        r = requests.head(f"{es_host}/{idx}", timeout=10)
        return r.status_code == 200
    except Exception:
        return False


def _doc_id(doc: dict) -> str:
    """构造幂等 _id。

    字段选择:
      - `breed`        = 清洗后品种名（与 xinjiang/heze/shaanxi 一致）
      - `breed_clean`  = 拆完的品种名（拆后可能比 breed 更短）
      - `spec`         = 拆出的规格 + 原 spec 合并
    """
    parts = [
        doc.get("province", ""),
        doc.get("period", ""),
        doc.get("county", ""),
        doc.get("breed", ""),
        doc.get("breed_clean", ""),
        doc.get("spec", ""),
        doc.get("unit", ""),
        str(doc.get("price", "")),
        str(doc.get("tax_price", "")),
    ]
    import hashlib
    return hashlib.md5("|".join(parts).encode("utf-8")).hexdigest()


def _build_ods_mapping() -> dict:
    return {
        "mappings": {
            "properties": {
                "breed": {"type": "text", "fields": {"keyword": {"type": "keyword", "ignore_above": 512}}},
                "breed_clean": {"type": "text", "fields": {"keyword": {"type": "keyword", "ignore_above": 512}}},
                "breed_raw": {"type": "text"},
                "spec": {"type": "text", "fields": {"keyword": {"type": "keyword", "ignore_above": 512}}},
                "unit": {"type": "keyword"},
                "price": {"type": "float"},
                "tax_price": {"type": "float"},
                "is_tax": {"type": "keyword"},
                "period": {"type": "keyword"},
                "period_start": {"type": "date", "format": "yyyy-MM-dd"},
                "period_end": {"type": "date", "format": "yyyy-MM-dd"},
                "period_days": {"type": "integer"},
                "province": {"type": "keyword"},
                "city": {"type": "keyword"},
                "county": {"type": "keyword"},
                "remarks": {"type": "text"},
                "update_date": {"type": "date", "format": "yyyy-MM-dd"},
                "create_time": {"type": "date", "format": "yyyy-MM-dd HH:mm:ss||strict_date_optional_time"},
                "source": {"type": "keyword"},
            }
        }
    }