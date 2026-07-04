"""shaanxi_collector.py - 陕西工程造价材料采集器（v1.0, 2026-07-03 SyncRunner 抽象基类化）

参考 chongqing_collector（v0.9, 2026-07-02）和 qingdao_collector（v0.9, 2026-07-03）的
SyncRunner 抽象基类化模式重构。

v1.0 变更：
- 模块建构：sync.py 从一站式 main() 重写为 ShaanxiCollector，继承 SyncRunner
- 新字段：每条 doc 必含 period_start / period_end / period_days（道友硬要求，2026-07-03）
- 默认走 collector；`--legacy` 走 sync_legacy.py（逃生通道）
- 数据范围：默认 year=2026（cfg.sync.target_year）
- 复用：city_parsers.py（CITY_PARSERS）+ utils.py（fetch_html / parse_list_page / parse_detail_page /
  extract_period_from_title / extract_city_from_title / ensure_ods_index 等）
  完全不变，0 改动兼容

工作单元形状（dict）：
    {
      "period": str,             # 业务期（'2026.5月' / '2026.5期' / '2026.2期(双月刊)' / '2026.1期(季刊)'）
      "city": str,               # 设区市名（'安康'/'汉中'/...）或 '陕西'（省本级）
      "publish_date": str,       # 源站列表上的发布日期（YYYY-MM-DD）
      "detail_url": str,
      "pdf_url": str,
      "pdf_name": str,
      "title": str,
      "period_start": str,       # 推算的期间起始日
      "period_end": str,         # 推算的期间结束日
      "period_days": int,        # 期间天数
    }

进度 key：detail_url（与原 sync.py 一致，21 期已 ok 的不重抓）
"""
from __future__ import annotations

import calendar
import json
import os
import re
import sys
import tempfile
import time
from datetime import datetime, date
from typing import Optional

# 复用 gov-price-etl 的 SyncRunner 抽象基类 + 通用工具
_ETL_PROJECT_ROOT = "/Users/pengfit/.openclaw/workspace/skills/gov-price-etl"
if _ETL_PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _ETL_PROJECT_ROOT)

from gov_price_etl.collectors import (
    get_es_client,
    get_s3_client,
    ensure_bucket,
    upload_to_minio,
    fetch_html,
    download_file,
)
from gov_price_etl.collectors.base import (
    LocalProgressStore,
    SyncRunner,
)

# 复用 shaanxi 自身的工具（list/detail 解析、ES index 创建）
import utils as _u

# 复用现有的 city_parsers.py（按 city 分发到独立解析函数）
from pdf_parser import parse_pdf_pages, CITY_PARSERS

# 复用 sync.py 的 fetch_all_periods（5 页列表抓取，不动实现）
import sync as _sync_compat


PROGRESS_FILE_NAME = ".shaanxi_sync_progress.json"
PROVINCE = "陕西"


# ─────────────────────────────────────────────────────────────
# period_start / period_end / period_days 推算
# ─────────────────────────────────────────────────────────────

def _build_period_range(year: int, start_month: int, end_month: int) -> dict:
    """计算 (start_month 1日, end_month 末日, 天数)。"""
    start_d = date(year, start_month, 1)
    last_day = calendar.monthrange(year, end_month)[1]
    end_d = date(year, end_month, last_day)
    days = (end_d - start_d).days + 1
    return {
        "period_start": start_d.isoformat(),
        "period_end": end_d.isoformat(),
        "period_days": days,
    }


def compute_period_dates(period: str) -> dict:
    """根据业务期 period 推算 period_start / period_end / period_days。

    支持 4 种 period 格式（参考 sync.py extract_period_from_title）：
      - 月报：'2026.5月'                          → 当月 1 日 ~ 当月末日
      - 月刊：'2026.5期'                          → 第 N 期 = 第 N 月，1 日 ~ 月末日
      - 双月刊：'2026.2期(双月刊)'                 → 第 N 期 = ((N-1)*2+1) 月 ~ (N*2) 月
      - 季刊：'2026.1期(季刊)'                    → 第 N 期 = ((N-1)*3+1) 月 ~ (N*3) 月

    Returns:
        {'period_start': '2026-05-01', 'period_end': '2026-05-31', 'period_days': 31}
        解析失败返回 {'period_start': None, 'period_end': None, 'period_days': None}

    实际数据校验（来自 .shaanxi_sync_progress.json 已入仓的 25 期）：
      - 2026.5月（陕西）           → 5 月 1 日 ~ 5 月 31 日（31 天）
      - 2026.5期（安康/汉中 月刊）→ 5 月 1 日 ~ 5 月 31 日（31 天）
      - 2026.3期（咸阳）           → 3 月 1 日 ~ 3 月 31 日（31 天）
      - 2026.2期（铜川）           → 2 月 1 日 ~ 2 月 28 日（28 天）
      - 2026.1期（榆林）           → 1 月 1 日 ~ 1 月 31 日（31 天）
      - 2026.2期(双月刊)（渭南）   → 3 月 1 日 ~ 4 月 30 日（61 天）
      - 2026.1期(双月刊)（渭南）   → 1 月 1 日 ~ 2 月 28 日（59 天）
      - 2026.1期(季刊)（商洛）     → 1 月 1 日 ~ 3 月 31 日（90 天）
    """
    period = period or ""

    # 1. 月报：{year}.{N}月
    m = re.search(r"(\d{4})\.(\d{1,2})月", period)
    if m:
        year, month = int(m.group(1)), int(m.group(2))
        last_day = calendar.monthrange(year, month)[1]
        return {
            "period_start": f"{year:04d}-{month:02d}-01",
            "period_end": f"{year:04d}-{month:02d}-{last_day:02d}",
            "period_days": last_day,
        }

    # 2. 季刊：{year}.{N}期(季刊) — 必须先于双月刊/月刊匹配
    m = re.search(r"(\d{4})\.(\d{1,2})期\(季刊\)", period)
    if m:
        year, issue = int(m.group(1)), int(m.group(2))
        start_month = (issue - 1) * 3 + 1
        end_month = issue * 3
        return _build_period_range(year, start_month, end_month)

    # 3. 双月刊：{year}.{N}期(双月刊)
    m = re.search(r"(\d{4})\.(\d{1,2})期\(双月刊\)", period)
    if m:
        year, issue = int(m.group(1)), int(m.group(2))
        start_month = (issue - 1) * 2 + 1
        end_month = issue * 2
        return _build_period_range(year, start_month, end_month)

    # 4. 月刊（默认）：{year}.{N}期 — N 期 = N 月
    m = re.search(r"(\d{4})\.(\d{1,2})期", period)
    if m:
        year, issue = int(m.group(1)), int(m.group(2))
        last_day = calendar.monthrange(year, issue)[1]
        return {
            "period_start": f"{year:04d}-{issue:02d}-01",
            "period_end": f"{year:04d}-{issue:02d}-{last_day:02d}",
            "period_days": last_day,
        }

    # 兜底：解析失败（理论上不会发生，sync 已 ensure period 非空）
    return {"period_start": None, "period_end": None, "period_days": None}


# ─────────────────────────────────────────────────────────────
# row_to_doc — v1.0 加 period_start/end/days
# ─────────────────────────────────────────────────────────────

def row_to_doc_v2(
    row,  # MaterialRow
    period: str,
    city: str,
    publish_date: str,
    source_pdf: str,
    source_url: str,
    now: str,
    period_dates: dict,
) -> dict:
    """MaterialRow → ES doc（v1.0 加 period_start / period_end / period_days）。

    与 sync.py 旧 row_to_doc 唯一差异：doc 中新增三个日期字段。
    """
    return {
        "code": row.code,
        "breed": row.breed,
        "spec": row.spec,
        "unit": row.unit,
        "category": row.category,
        "price": row.price,
        "tax_price": row.tax_price,
        "period": period,
        # v1.0 必含字段（道友硬要求）
        "period_start": period_dates["period_start"],
        "period_end": period_dates["period_end"],
        "period_days": period_dates["period_days"],
        "province": PROVINCE,
        "city": city,
        "county": row.county,
        "update_date": publish_date,
        "create_time": now,
        "source_pdf": source_pdf,
        "source_url": source_url,
    }


# ─────────────────────────────────────────────────────────────
# bulk_index — 与 sync.py 等价（幂等 _id）
# ─────────────────────────────────────────────────────────────

import hashlib


def _doc_id(period, breed, spec, city, county, code="", unit=""):
    """幂等 _id (v1.0 修复：包含 breed/spec/unit/county 避免 _id 冲突)。

    历史 bug (2026-06-26 v0.5): code 非空时仅用 (period+code+city+county) 作 _id，
    同一 code 在不同 breed/spec/unit 的 row 会被 ES bulk upsert 静默去重，
    导致 ~600 条数据丢失（堆在咸阳/铜川/榆林的 county="" 和 county=乾县 等同一 code）。
    v1.0 加入 breed/spec/unit/county 拼接，任何业务维度变化都会产生新 _id。
    """
    raw = f"{period}|{code or '_'}|{breed}|{spec}|{unit}|{city}|{county}"
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


def bulk_index_ods(es, index, docs):
    if not docs:
        return 0, 0
    body = ""
    for d in docs:
        _id = _doc_id(
            d["period"],
            d.get("breed", ""),
            d.get("spec", ""),
            d.get("city", ""),
            d.get("county", ""),
            d.get("code", "") or "",
            d.get("unit", "") or "",
        )
        body += json.dumps({"index": {"_index": index, "_id": _id}}, ensure_ascii=False) + "\n"
        body += json.dumps(d, ensure_ascii=False) + "\n"
    resp = es.bulk(body=body, refresh=False)
    if resp.get("errors"):
        errors = sum(1 for it in resp["items"] if "error" in it.get("index", {}))
        return len(docs) - errors, errors
    return len(docs), 0


# ─────────────────────────────────────────────────────────────
# ShaanxiCollector
# ─────────────────────────────────────────────────────────────

class ShaanxiCollector(SyncRunner):
    """陕西工程造价材料采集器（v1.0, 2026-07-03 SyncRunner 抽象基类化）。

    复用 sync.py 的 fetch_all_periods（5 页列表抓取）+ city_parsers.py（按 city 分发
    PDF 解析）+ utils.py（ES/MinIO/列表/详情抽取），主流程通过 SyncRunner 钩子实现。

    进度 key：unit["detail_url"] —— 与原 sync.py 一致，已入仓 21 期 ok + 4 期
    skipped_image_pdf 在新流程下天然不重抓（详情页 URL 命中 progress['done']）。
    """

    def __init__(
        self,
        cfg: dict,
        run_id: str,
        year: int = 0,
        dry_run: bool = False,
    ):
        progress_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            PROGRESS_FILE_NAME,
        )
        super().__init__(
            progress=LocalProgressStore(progress_path),
            es_host=cfg["es"]["host"],
            es_index=cfg["es"]["ods_index"],
            progress_index=cfg["es"]["progress_index"],
        )
        self.cfg = cfg
        self.run_id = run_id
        self.year = year or cfg.get("sync", {}).get("target_year", 0) or 0
        self.dry_run = dry_run
        # 缓存 ES / s3 客户端（_process_one 每个 unit 复用）
        self._es = get_es_client(cfg["es"]["host"])
        self._s3 = get_s3_client(cfg)
        if not self.dry_run:
            ensure_bucket(self._s3, cfg["minio"]["bucket"])
            _u.ensure_ods_index(self._es, cfg["es"]["ods_index"])
            _u.ensure_progress_index(self._es, cfg["es"]["progress_index"])

    # ── SyncRunner 钩子实现 ──

    def _list_work_units(self) -> list[dict]:
        """抓列表 5 页 → 拉详情（拿 PDF 链接 + period）→ 返回工作单元。

        进度过滤：
        - status in ('ok', 'partial', 'skipped_image_pdf') → 跳过（已处理）
        - status == 'failed' 或 'pending_reparse' → 重试
        - 未在进度中 → 加入队列
        """
        site = self.cfg["site"]
        headers = {
            "User-Agent": site["user_agent"],
            "Referer": site.get("referer", site["base_url"]),
        }

        items = _sync_compat.fetch_all_periods(self.cfg)
        print(f"[ShaanxiCollector] 列表共 {len(items)} 期（5 页合并）")

        progress = self.progress.load()
        done = progress.get("done", {}) or {}

        units = []
        for it in items:
            # year 过滤
            if self.year and f"{self.year}年" not in it["title"]:
                continue

            prior_status = done.get(it["detail_url"], {}).get("status")
            if prior_status in ("ok", "partial", "skipped_image_pdf"):
                # 已完成（含图像型 PDF 标记）天然跳过
                continue

            # 拉详情拿 PDF 链接 + 真实标题
            try:
                detail_html = fetch_html(
                    it["detail_url"], headers=headers, timeout=site["timeout_sec"],
                )
                detail = _u.parse_detail_page(detail_html, it["detail_url"])
                if not detail["pdf_url"]:
                    print(f"  [skip] {it['title']}：详情页未找到 PDF 链接")
                    continue
                title = detail["title"] or it["title"]
                period = _u.extract_period_from_title(title)
                if not period:
                    print(f"  [skip] {it['title']}：无法从标题推断周期")
                    continue
                city = _u.extract_city_from_title(
                    it["title"], self.cfg["city_patterns"], self.cfg["province_label"],
                )
                units.append({
                    "period": period,
                    "city": city,
                    "publish_date": it["publish_date"],
                    "detail_url": it["detail_url"],
                    "pdf_url": detail["pdf_url"],
                    "pdf_name": detail["pdf_name"],
                    "title": title,
                })
            except Exception as e:
                print(f"  [skip] {it['title']}：详情页抓取失败 {e}")
                continue
        return units

    def _process_one(self, unit: dict) -> tuple[int, str]:
        """处理单个工作单元：下载 PDF → 上传 MinIO → 按 city 解析 → bulk 写 ES。

        Returns:
            (docs_count, status)，status ∈ {'completed', 'error'}。
        """
        site = self.cfg["site"]
        headers = {
            "User-Agent": site["user_agent"],
            "Referer": site.get("referer", site["base_url"]),
        }
        bucket = self.cfg["minio"]["bucket"]
        prefix = self.cfg["minio"]["prefix"]
        period = unit["period"]
        city = unit["city"]
        period_dates = compute_period_dates(period)

        # 1. city 是否在 CITY_PARSERS（咸阳/铜川/渭南/榆林/汉中/商洛 + 陕西 省本级）。
        #    安康的 2026.1-4 期是扫描图像型 PDF，解析器不识别 → 直接标 skipped_image_pdf。
        if city not in CITY_PARSERS:
            print(f"  ⚠ city {city} 无对应 parser（已实现: {list(CITY_PARSERS.keys())}），标 skipped_no_parser")
            unit["docs_written"] = 0
            unit["minio_key"] = ""
            unit["period_start"] = period_dates["period_start"]
            unit["period_end"] = period_dates["period_end"]
            unit["period_days"] = period_dates["period_days"]
            return 0, "skipped"

        with tempfile.TemporaryDirectory() as tmpdir:
            local_pdf = os.path.join(tmpdir, "source.pdf")
            download_file(unit["pdf_url"], local_pdf, headers=headers, timeout=180)

            minio_key = (
                f"{prefix}/{period}_{unit['pdf_name']}"
                if unit["pdf_name"]
                else f"{prefix}/{period}/source.pdf"
            )
            if not self.dry_run:
                upload_to_minio(self._s3, bucket, minio_key, local_pdf)

            page_results = parse_pdf_pages(local_pdf, city)
            total_rows = sum(len(rows) for _, _, rows in page_results)
            pages_parsed = sum(
                1 for _, pt, rows in page_results if rows and not pt.startswith("error")
            )
            # OCR 兑底过（图像型 PDF）但 0 条 → skipped_image_pdf
            try:
                from pdf_parser import _OCR_CACHE as _ocr_cache
                ocr_attempted = len(_ocr_cache) > 0
            except Exception:
                ocr_attempted = False

            now = datetime.now().isoformat(timespec="seconds")
            docs = []
            seen_keys = set()  # 去重：同份 PDF 中某些 row 被 page parser 重复列出（同一 code/breed/spec/unit/county）
            for pno, ptype, rows in page_results:
                if ptype.startswith("error"):
                    continue
                for row in rows:
                    if row.price is None and row.tax_price is None:
                        continue
                    doc = row_to_doc_v2(
                        row, period, city,
                        unit["publish_date"], minio_key, unit["pdf_url"],
                        now, period_dates,
                    )
                    # 去重 key = _id 的原始哈希字符串（避免 hash 冲突影响去重判断）
                    dedup_key = (
                        f"{period}|{doc.get('code','') or '_'}|{doc.get('breed','')}|"
                        f"{doc.get('spec','')}|{doc.get('unit','')}|{city}|{doc.get('county','')}"
                    )
                    if dedup_key in seen_keys:
                        continue
                    seen_keys.add(dedup_key)
                    docs.append(doc)
            if len(seen_keys) < total_rows:
                print(
                    f"  [dedup] {period}/{city}: docs {total_rows} → {len(docs)} "
                    f"({total_rows - len(docs)} 重复)"
                )

            # 状态判定优先级：partial > skipped_image_pdf > ok
            if self.dry_run:
                status_str = "dry-run"
                ok_n = len(docs)
                err_n = 0
            elif len(docs) == 0 and ocr_attempted:
                status_str = "skipped_image_pdf"
                ok_n = 0
                err_n = 0
            else:
                status_str = "ok"
                ok_n, err_n = bulk_index_ods(self._es, self.es_index, docs)

            unit["docs_written"] = ok_n
            unit["docs_failed"] = err_n
            unit["pages_parsed"] = pages_parsed
            unit["minio_key"] = minio_key
            unit["period_start"] = period_dates["period_start"]
            unit["period_end"] = period_dates["period_end"]
            unit["period_days"] = period_dates["period_days"]
            unit["status"] = "partial" if err_n > 0 else status_str
            unit["created_at"] = now

            return (ok_n if err_n == 0 else 0), ("completed" if err_n == 0 else "error")

    def _on_unit_start(self, unit: dict) -> None:
        print(
            f"[ShaanxiCollector] >>> {unit['period']} | {unit['city']} "
            f"| {unit['publish_date']} | {unit['detail_url']}"
        )

    def _on_unit_done(self, unit: dict, docs_count: int, status: str, error: str = "") -> None:
        """完成后写本地进度 + ES progress 索引。

        进度 doc 字段对齐 sync.py 的 progress['done'][detail_url] 格式（dashboard 端
        history / check.py 都按这个 key 取）。
        """
        now = unit.get("created_at") or datetime.now().isoformat(timespec="seconds")
        progress = self.progress.load()
        done = progress.setdefault("done", {})
        done[unit["detail_url"]] = {
            "period": unit.get("period"),
            "city": unit.get("city"),
            "publish_date": unit.get("publish_date"),
            "detail_url": unit.get("detail_url"),
            "pdf_url": unit.get("pdf_url"),
            "minio_key": unit.get("minio_key"),
            "docs_written": unit.get("docs_written", docs_count),
            "pages_parsed": unit.get("pages_parsed", 0),
            "status": unit.get("status", "ok" if status == "completed" else status),
            "error": error,
            "duration_sec": 0.0,
            "created_at": now,
            # v1.0 三个新字段（道友硬要求）
            "period_start": unit.get("period_start"),
            "period_end": unit.get("period_end"),
            "period_days": unit.get("period_days"),
            "run_id": self.run_id,
        }
        self.progress.save(progress)

        # ES 进度上报（含 3 个新字段）
        if not self.dry_run:
            try:
                self._es.index(
                    index=self.progress_index,
                    body={
                        "run_id": self.run_id,
                        "period": unit.get("period"),
                        "city": unit.get("city"),
                        "province": PROVINCE,
                        "publish_date": unit.get("publish_date"),
                        "detail_url": unit.get("detail_url"),
                        "pdf_url": unit.get("pdf_url"),
                        "minio_key": unit.get("minio_key"),
                        "docs_written": unit.get("docs_written", docs_count),
                        "pages_parsed": unit.get("pages_parsed", 0),
                        "status": unit.get("status", "ok" if status == "completed" else status),
                        "error": error,
                        "title": unit.get("title"),
                        "created_at": now,
                        "last_updated": now,
                        # v1.0 三个新字段
                        "period_start": unit.get("period_start"),
                        "period_end": unit.get("period_end"),
                        "period_days": unit.get("period_days"),
                    },
                )
            except Exception as e:
                print(f"  [!] ES 进度上报失败: {e}")

        icon = "✓" if status == "completed" else "✗"
        extra = f" err={error}" if error else ""
        print(
            f"  [{icon}] {unit['period']} | {unit['city']}: "
            f"{unit.get('docs_written', docs_count)} docs ({unit.get('status', status)}){extra}"
        )

    def _compute_unit_key(self, unit: dict) -> str:
        """本地进度 key = detail_url。

        复用 sync.py 的 progress['done'][detail_url] 命名空间 —— 已入仓的 21 期 ok
        + 4 期 skipped_image_pdf 在新流程下天然不重抓。
        """
        return unit["detail_url"]


# ─────────────────────────────────────────────────────────────
# 工厂方法
# ─────────────────────────────────────────────────────────────

def make_collector(
    cfg_path: Optional[str] = None,
    run_id: str = "",
    year: int = 0,
    dry_run: bool = False,
) -> ShaanxiCollector:
    """从 config.yml 构造 ShaanxiCollector。

    Args:
        cfg_path: 配置文件路径，默认走 skill 根目录的 config.yml
        run_id: 本次采集运行 ID
        year: 只入指定年份（0 = 用 cfg.sync.target_year，默认 2026）
        dry_run: 是否只预览不写入
    """
    if cfg_path is None:
        cfg_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "config.yml",
        )
    cfg = _u.load_config()
    if not run_id:
        run_id = f"sn_run_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    return ShaanxiCollector(
        cfg=cfg,
        run_id=run_id,
        year=year,
        dry_run=dry_run,
    )


# ─────────────────────────────────────────────────────────────
# CLI 调试入口
# ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="ShaanxiCollector CLI")
    parser.add_argument("--year", type=int, default=0, help="指定年份（默认 cfg.sync.target_year=2026）")
    parser.add_argument("--dry-run", action="store_true", help="预览不写入")
    parser.add_argument("--reset", action="store_true", help="重置本地进度")
    parser.add_argument("--max-units", type=int, default=None, help="只跑前 N 个 unit（验证用）")
    parser.add_argument("--run-id", default="", help="指定 run_id")
    args = parser.parse_args()

    coll = make_collector(run_id=args.run_id, year=args.year, dry_run=args.dry_run)
    result = coll.run(reset=args.reset, max_units=args.max_units)
    print(f"\n[Result] {result}")