"""qingdao_collector.py - 青岛工程造价材料信息采集器（v0.9, 2026-07-03）

将青岛 v0.8 一站式 sync.py 用 SyncRunner 抽象基类重构，参考 chongqing_collector.py
的 v0.9 写法。提供：
- 列表抓取 + 过滤（年份/未 done）
- 详情页 PDF 链接提取
- PDF 下载（带 Referer 头）+ MinIO 上传
- pdfplumber 解析 + bulk 写入 ES
- 三个新字段填充：period_start / period_end / period_days

工作单元形状：dict
    {
        'period': '2026.5月',         # 业务期（'YYYY.M月'）
        'publish_date': '2026-06-09',  # 列表发布日期
        'detail_url': '...',           # 详情页 URL（也是本地进度 key）
        'pdf_url': '...',              # PDF 直链
        'pdf_name': '...',             # 下载文件名
        'title': '2026年5月青岛市建设工程材料价格',
    }

设计：
- 继承 gov_price_etl.collectors.base.SyncRunner
- 重写 _list_work_units()：抓列表 → 过滤 → 拉详情 → 拉 PDF 链接
- 重写 _process_one()：下载 PDF → 上传 MinIO → 解析 → bulk 写 ES
- 重写 _compute_unit_key()：用 detail_url
- 重写 _on_unit_done()：写 ES progress + 本地进度
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
from datetime import date, datetime
from typing import Optional
from urllib.parse import urljoin

# 复用 gov-price-etl 的基类 + 工具
_ETL_PROJECT_ROOT = _resolve_etl_root()
if _ETL_PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _ETL_PROJECT_ROOT)

from gov_price_etl.collectors import (
    get_es_client, get_s3_client, ensure_bucket, upload_to_minio,
    fetch_html, download_file,
)
from gov_price_etl.collectors.base import (
    LocalProgressStore,
    SignalHandler,
    SyncRunner,
)

# 同目录工具
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import utils as _u  # 同目录 commands/utils.py


# ─────────────────────────────────────────────────────────────
# 周期字段工具
# ─────────────────────────────────────────────────────────────

def _parse_year_month_from_period(period: str) -> Optional[tuple[int, int]]:
    """'2026.5月' → (2026, 5)；'2026年5月' → (2026, 5)"""
    m = re.search(r"(\d{4})[.\u5e74](\d{1,2})\u6708", period)
    if not m:
        return None
    return int(m.group(1)), int(m.group(2))


def compute_period_dates(period: str) -> dict:
    """根据业务期 period 推算 period_start / period_end / period_days。

    规则：月报 → 当月第一天 / 当月最后一天 / 当月天数。
    例：'2026.5月' → ('2026-05-01', '2026-05-31', 31)
    例：'2026年2月' → ('2026-02-01', '2026-02-29', 29)  # 闰年 2026 不闰

    Returns:
        {'period_start': '2026-05-01', 'period_end': '2026-05-31', 'period_days': 31}
    """
    ym = _parse_year_month_from_period(period)
    if ym is None:
        # 兜底：返回 None（ES dynamic=strict 不会拒收 null 字段）
        return {"period_start": None, "period_end": None, "period_days": None}
    year, month = ym
    last_day = calendar.monthrange(year, month)[1]
    return {
        "period_start": f"{year:04d}-{month:02d}-01",
        "period_end": f"{year:04d}-{month:02d}-{last_day:02d}",
        "period_days": last_day,
    }


# ─────────────────────────────────────────────────────────────
# 列表 / 详情页 / PDF 解析
# ─────────────────────────────────────────────────────────────

def parse_list_page(html: str, base_url: str) -> list[dict]:
    """从列表页 HTML 提取每期信息（与 v0.8 sync.py 等价）。"""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    items = []
    for li in soup.select('li[trs-attr="chip"]'):
        a = li.select_one('a[href*="t20"][href$=".html"]')
        if not a:
            continue
        href = a.get("href", "")
        title = a.get("title", "") or a.get_text(strip=True)
        date_el = li.select_one("div.div_list_li_width_right")
        publish_date = ""
        if date_el:
            m = re.search(r"\[?(\d{4}-\d{2}-\d{2})\]?", date_el.get_text(strip=True))
            if m:
                publish_date = m.group(1)
        items.append({
            "title": re.sub(r"\s+", " ", title).strip(),
            "publish_date": publish_date,
            "detail_url": urljoin(base_url, href),
        })
    return items


def parse_detail_page(html: str, base_url: str, detail_url: str = "") -> dict:
    """从详情页提取 PDF 链接 + 标题（与 v0.8 sync.py 等价）。"""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    title_el = soup.select_one("div.head_7 h2")
    title = title_el.get_text(strip=True) if title_el else ""
    pdf_a = None
    for a in soup.select('a[href*=".pdf"]'):
        href = a.get("href", "")
        if href.startswith("./P") or href.startswith("P") or "/P" in href:
            pdf_a = a
            break
    if not pdf_a:
        pdf_a = soup.select_one('a[href*=".pdf"]')
    if not pdf_a:
        return {"title": title, "pdf_url": "", "pdf_name": ""}
    href = pdf_a.get("href", "")
    pdf_url = href
    if not pdf_url.startswith("http"):
        pdf_url = urljoin(detail_url or base_url, pdf_url)
    pdf_name = (
        pdf_a.get("download", "")
        or pdf_a.get_text(strip=True)
        or os.path.basename(pdf_url)
    )
    return {"title": title, "pdf_url": pdf_url, "pdf_name": pdf_name}


def extract_period_from_title(title: str) -> str:
    """'2026年5月青岛市建设工程材料价格' → '2026.5月'"""
    m = re.search(r"(\d{4})年(\d{1,2})月", title)
    if not m:
        return ""
    return f"{m.group(1)}.{int(m.group(2))}月"


def _parse_price(s):
    """从含中文符号/逗号的字符串中提取 float，失败返回 None。"""
    if s is None:
        return None
    s = str(s).strip()
    if not s:
        return None
    s = s.replace("￥", "").replace("¥", "").replace(",", "").replace(" ", "")
    try:
        v = float(s)
        return v if v > 0 else None
    except ValueError:
        return None


def _is_header_row(cells) -> bool:
    """判断一行是否是 5 列表头：序号|名称|规格型号|单位|含税价(元)"""
    if not cells or len(cells) < 4:
        return False
    text = " ".join(str(c or "").replace("\n", " ").strip() for c in cells)
    text_compact = text.replace(" ", "").replace("\u3000", "")
    return (
        "序号" in text_compact
        and ("名称" in text_compact or "名" in text_compact)
        and ("规格" in text_compact or "规" in text_compact)
        and "含税价" in text
    )


def parse_pdf_tables(pdf_path: str, vat_rate: float) -> list[dict]:
    """PDF → 长表 [(breed, spec, unit, price, tax_price)]（与 v0.8 等价）。

    青岛 PDF 结构：Page 3-8 为材料价格表，表头 5 列。
    全部为含税价 → 按 vat_rate 反推 price。
    """
    import pdfplumber
    rows_out = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            tables = page.extract_tables() or []
            for tbl in tables:
                if not tbl or len(tbl) < 2:
                    continue
                header_idx = None
                for j, row in enumerate(tbl[:3]):
                    if _is_header_row(row):
                        header_idx = j
                        break
                if header_idx is None:
                    continue
                for row in tbl[header_idx + 1:]:
                    cells = [str(c or "").replace("\n", " ").strip() for c in row]
                    if not cells or not any(cells):
                        continue
                    if len(cells) >= 5:
                        seq, breed, spec, unit, raw_price = cells[:5]
                        tax_price = _parse_price(raw_price)
                    elif len(cells) == 4:
                        seq, breed, spec, unit = cells[:4]
                        tax_price = _parse_price(cells[3]) if _parse_price(cells[3]) else _parse_price(cells[2])
                    else:
                        continue
                    if not breed and not spec:
                        continue
                    if tax_price is None or tax_price <= 0:
                        continue
                    price_excl = round(tax_price / (1 + vat_rate), 2)
                    rows_out.append({
                        "breed": breed,
                        "spec": spec,
                        "unit": unit,
                        "price": price_excl,
                        "tax_price": tax_price,
                    })
    return rows_out


# ─────────────────────────────────────────────────────────────
# ES bulk 写入（幂等 _id）
# ─────────────────────────────────────────────────────────────

def _doc_id(period: str, breed: str, spec: str, unit: str, price: float) -> str:
    raw = f"{period}|{breed}|{spec}|{unit}|{price}"
    return hashlib.md5(raw.encode("utf-8")).hexdigest()


def bulk_index_ods(es, index: str, docs: list[dict]) -> tuple[int, int]:
    """bulk 写入（按 _id upsert），返回 (ok, err) 计数。"""
    if not docs:
        return 0, 0
    body = ""
    for d in docs:
        _id = _doc_id(d["period"], d["breed"], d["spec"], d["unit"], d["price"])
        body += json.dumps({"index": {"_index": index, "_id": _id}}, ensure_ascii=False) + "\n"
        body += json.dumps(d, ensure_ascii=False) + "\n"
    resp = es.bulk(body=body, refresh=False)
    if resp.get("errors"):
        errors = sum(1 for it in resp["items"] if "error" in it.get("index", {}))
        return len(docs) - errors, errors
    return len(docs), 0


# ─────────────────────────────────────────────────────────────
# QingdaoCollector
# ─────────────────────────────────────────────────────────────

class QingdaoCollector(SyncRunner):
    """青岛工程造价材料采集器（v0.9, 2026-07-03 SyncRunner 化）。

    工作单元：list item dict（见模块 docstring）
    钩子实现：_list_work_units / _process_one / _compute_unit_key / _on_unit_done
    """

    def __init__(self, cfg: dict, run_id: str, year: int = 0, dry_run: bool = False):
        progress_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            ".qingdao_sync_progress.json",
        )
        super().__init__(
            progress=LocalProgressStore(progress_path),
            es_host=cfg["es"]["host"],
            es_index=cfg["es"]["ods_index"],
            progress_index=cfg["es"]["progress_index"],
        )
        self.cfg = cfg
        self.run_id = run_id
        self.year = year or cfg.get("sync", {}).get("default_year", 0) or 0
        self.dry_run = dry_run
        # 缓存 ES / s3 客户端（_process_one 每个 unit 复用）
        self._es = get_es_client(cfg["es"]["host"])
        self._s3 = get_s3_client(cfg)
        ensure_bucket(self._s3, cfg["minio"]["bucket"])
        _u.ensure_ods_index(self._es, cfg["es"]["host"], cfg["es"]["ods_index"])
        _u.ensure_progress_index(self._es, cfg["es"]["progress_index"])

    # ── SyncRunner 钩子实现 ──

    def _list_work_units(self) -> list[dict]:
        """抓列表 + 拉详情（拿 PDF 链接）→ 返回工作单元 list。"""
        site = self.cfg["site"]
        base_url = site["base_url"]
        url = base_url + site["list_path"]
        html = fetch_html(url, headers={"User-Agent": site["user_agent"]}, timeout=site["timeout_sec"])
        items = parse_list_page(html, base_url)
        # 去重
        seen = set()
        uniq = []
        for it in items:
            if it["detail_url"] in seen:
                continue
            seen.add(it["detail_url"])
            uniq.append(it)
        print(f"[QingdaoCollector] 列表共 {len(uniq)} 期")

        # 进度过滤
        progress = self.progress.load()
        done = progress.get("done", {}) or {}

        units = []
        for it in uniq:
            if self.year and f"{self.year}年" not in it["title"]:
                continue
            if it["detail_url"] in done and done[it["detail_url"]].get("status") == "ok":
                continue
            # 拉详情拿 PDF 链接（每期一次）
            try:
                detail_html = fetch_html(
                    it["detail_url"],
                    headers={"User-Agent": site["user_agent"]},
                    timeout=site["timeout_sec"],
                )
                detail = parse_detail_page(detail_html, base_url, detail_url=it["detail_url"])
                if not detail["pdf_url"]:
                    print(f"  [skip] {it['title']}：详情页未找到 PDF 链接")
                    continue
                period = extract_period_from_title(detail["title"] or it["title"])
                if not period:
                    print(f"  [skip] {it['title']}：无法从标题推断周期")
                    continue
                unit = {
                    "period": period,
                    "publish_date": it["publish_date"],
                    "detail_url": it["detail_url"],
                    "pdf_url": detail["pdf_url"],
                    "pdf_name": detail["pdf_name"],
                    "title": detail["title"] or it["title"],
                }
                units.append(unit)
            except Exception as e:
                print(f"  [skip] {it['title']}：详情页抓取失败 {e}")
                continue
        return units

    def _process_one(self, unit: dict) -> tuple[int, str]:
        """处理单个工作单元：下载 PDF → 上传 MinIO → 解析 → bulk 写 ES。

        Returns:
            (docs_count, status) — status ∈ {'completed', 'error'}
        """
        site = self.cfg["site"]
        vat_rate = self.cfg.get("vat", {}).get("rate", 0.09)
        city = self.cfg.get("city", "青岛")
        province = self.cfg.get("province", "山东")
        bucket = self.cfg["minio"]["bucket"]
        prefix = self.cfg["minio"]["prefix"]
        period = unit["period"]
        period_dates = compute_period_dates(period)

        with tempfile.TemporaryDirectory() as tmpdir:
            local_pdf = os.path.join(tmpdir, "source.pdf")
            # 关键：青岛住建局 PDF 必须带 Referer 头指向详情页
            download_file(
                unit["pdf_url"],
                local_pdf,
                referer=unit["detail_url"],
                timeout=120,
            )
            if os.path.getsize(local_pdf) < 1024:
                raise ValueError(f"PDF 太小（{os.path.getsize(local_pdf)} bytes），可能下载失败")

            minio_key = f"{prefix}/{period}/{unit['pdf_name']}" if unit["pdf_name"] else f"{prefix}/{period}/source.pdf"
            if not self.dry_run:
                upload_to_minio(self._s3, bucket, minio_key, local_pdf)

            pdf_rows = parse_pdf_tables(local_pdf, vat_rate)
            now = datetime.now().isoformat(timespec="seconds")

            docs = []
            for r in pdf_rows:
                doc = {
                    "period": period,
                    "breed": r["breed"],
                    "spec": r["spec"],
                    "unit": r["unit"],
                    "price": r["price"],
                    "tax_price": r["tax_price"],
                    "city": city,
                    "province": province,
                    "update_date": unit["publish_date"],
                    "create_time": now,
                    "source_pdf": minio_key,
                    "source_url": unit["pdf_url"],
                    # 三个 v0.9 新增字段（道友硬要求：不能缺少）
                    "period_start": period_dates["period_start"],
                    "period_end": period_dates["period_end"],
                    "period_days": period_dates["period_days"],
                    "run_id": self.run_id,
                }
                docs.append(doc)

            if self.dry_run:
                print(f"  [dry-run] {period}：将写 {len(docs)} 条")
                return len(docs), "completed"

            ok, err = bulk_index_ods(self._es, self.es_index, docs)
            unit["docs_written"] = ok
            unit["docs_failed"] = err
            unit["minio_key"] = minio_key
            return (ok if err == 0 else 0), ("completed" if err == 0 else "error")

    def _on_unit_start(self, unit: dict) -> None:
        print(f"[QingdaoCollector] >>> {unit['period']}  ({unit['publish_date']})  {unit['detail_url']}")

    def _on_unit_done(self, unit: dict, docs_count: int, status: str, error: str = "") -> None:
        """完成后写 ES progress + 保存本地进度。"""
        now = datetime.now().isoformat(timespec="seconds")
        progress = self.progress.load()
        done = progress.setdefault("done", {})
        done[unit["detail_url"]] = {
            "period": unit.get("period"),
            "publish_date": unit.get("publish_date"),
            "detail_url": unit.get("detail_url"),
            "pdf_url": unit.get("pdf_url"),
            "minio_key": unit.get("minio_key"),
            "docs_written": unit.get("docs_written", docs_count),
            "status": "ok" if status == "completed" else status,
            "error": error,
            "created_at": now,
            "run_id": self.run_id,
        }
        self.progress.save(progress)

        # ES 进度上报
        if not self.dry_run:
            try:
                self._es.index(
                    index=self.progress_index,
                    body={
                        "run_id": self.run_id,
                        "period": unit.get("period"),
                        "publish_date": unit.get("publish_date"),
                        "detail_url": unit.get("detail_url"),
                        "pdf_url": unit.get("pdf_url"),
                        "minio_key": unit.get("minio_key"),
                        "docs_written": unit.get("docs_written", docs_count),
                        "status": "ok" if status == "completed" else status,
                        "error": error,
                        "city": self.cfg.get("city", "青岛"),
                        "province": self.cfg.get("province", "山东"),
                        "created_at": now,
                        "last_updated": now,
                    },
                )
            except Exception as e:
                print(f"  [!] ES 进度上报失败: {e}")

        icon = "✓" if status == "completed" else "✗"
        print(f"  [{icon}] {unit['period']}: {docs_count} docs ({status}){(' err=' + error) if error else ''}")

    def _compute_unit_key(self, unit: dict) -> str:
        return unit["detail_url"]


# ─────────────────────────────────────────────────────────────
# 工厂方法
# ─────────────────────────────────────────────────────────────

def make_collector(
    cfg_path: str,
    run_id: str,
    year: int = 0,
    dry_run: bool = False,
) -> QingdaoCollector:
    """从 config.yml 构造 QingdaoCollector。"""
    cfg = _u.load_config()
    return QingdaoCollector(
        cfg=cfg,
        run_id=run_id,
        year=year,
        dry_run=dry_run,
    )
