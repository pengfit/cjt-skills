"""hainan_collector.py - hainan 默认同步路径（v0.8 Collector 化，参照 chongqing_collector）

将 hainan 原有 sync.py 的主流程用 SyncRunner 抽象基类重构。
- 工作单元：一个 period（'2026年5月'）= 1 期 = 1 个 PDF
- _list_work_units()：抓列表 → 过滤 → 扁平化 period 列表
- _process_one(period)：抓详情页 → 解析 PDF → bulk 写 ES
- _on_unit_done()：写本地进度 + ES progress

参照实现：chongqing_collector.py（v0.8，2026-07-02）。

设计取舍：
- 不复用 chongqing 的 `write_es as _w` 模式，hainan 是 PDF 流程（requests + pdfplumber），
  与 chongqing 的浏览器自动化范式差异过大，强行复用反而绕
- 复用现有 sync.py 的纯函数（parse_list_page / fetch_all_periods / parse_detail_page /
  parse_pdf / extract_period_from_title / bulk_index / _doc_id），不重写解析逻辑
- 进度 key 用 period 字符串（'done_<period>'），与 chongqing 的 'done_<source>_<period>__<item>'
  形状不同但语义一致：每个 period 是独立任务
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


import argparse
import json
import os
import sys
import tempfile
import time
from datetime import datetime
from urllib.parse import urljoin

# 复用 hainan 现有 commands 模块（不重写解析逻辑）
_SELF_DIR = os.path.dirname(os.path.abspath(__file__))
if _SELF_DIR not in sys.path:
    sys.path.insert(0, _SELF_DIR)

from utils import (  # noqa: E402
    load_config, get_es_client, get_s3_client,
    ensure_bucket, ensure_ods_index, ensure_progress_index,
    fetch_html, download_file, upload_to_minio,
)
import parser as _h  # noqa: E402  （复用 parse_list_page / parse_pdf / 等纯函数）

# 接入 gov_price_etl.collectors 抽象基类
_ETL_PROJECT_ROOT = _resolve_etl_root()
if _ETL_PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _ETL_PROJECT_ROOT)

from gov_price_etl.collectors.base import (  # noqa: E402
    LocalProgressStore,
    SyncRunner,
)


def _is_image_pdf(pdf_path: str, img_threshold: float = 10.0, samples: int = 5) -> bool:
    """检测 PDF 是否为「表格在图片里」型 PDF（v0.8.2, 2026-07-06）。

    判定依据（组合指标，【平均图片数/页】为主）：
      纯文本 PDF（4 月期）：平均 < 1 图/页
      文字+图片混合 PDF（5 月期）：平均 ~90 图/页（表格被扫成图片）
      纯扫描图片 PDF：平均 ~1 图/页 但总页数=图片数（即整页一张图）

    主信号：平均图片数/页 ≥ img_threshold → 表格在图片里，pdfplumber 抽不到。
      阈值依据：5 月 PDF 90 图/页，4 月 PDF < 1 图/页，阈值 10 能可靠区分。

    Returns:
        True → 表格数据在图片里（应跳过入库，留待 OCR）
        False → 可正常 pdfplumber 解析

    Exceptions:
        静默吞掉异常返回 False（不阻塞正常 sync）。
    """
    try:
        import fitz  # PyMuPDF
        doc = fitz.open(pdf_path)
        n = len(doc)
        if n == 0:
            return False
        sample_indices = [min(int(n * pct), n - 1) for pct in (0.2, 0.3, 0.5, 0.7, 0.8)]
        total_imgs = sum(len(doc[i].get_images()) for i in sample_indices)
        avg_imgs_per_page = total_imgs / len(sample_indices)
        return avg_imgs_per_page >= img_threshold
    except Exception:
        return False


# ─────────────────────────────────────────────────────────────
# HainanCollector - 海南工程造价材料采集器（v0.8 Collector 化）
# ─────────────────────────────────────────────────────────────

class HainanCollector(SyncRunner):
    """海南工程造价材料采集器（v0.8 Collector 化，参照 chongqing）。

    工作单元形状：单个 period 字符串（'2026年5月'，与列表页 title 一致）。
    每个 unit 处理：详情页 → PDF 下载 → minio → pdfplumber 解析 → ES bulk 写入。

    与 chongqing collector 的差异：
    - chongqing：(source, item, period) 三元组；浏览器自动化
    - hainan：period 单值；requests + pdfplumber，无浏览器
    """

    def __init__(
        self,
        cfg: dict,
        run_id: str,
        year: int = 0,
        exclude_period: str = "",
        dry_run: bool = False,
    ):
        progress_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            ".hainan_sync_progress.json",
        )
        # 注意：hainan 旧进度文件结构是 {'done': {detail_url: {...}}}，
        # SyncRunner 默认用 key → str(unit)（这里 unit 本身就是 period），
        # 所以本 collector **重写 _load_done_keys** 用本地 'done' 字典对齐。
        super().__init__(
            progress=LocalProgressStore(progress_path),
            es_host=cfg["es"]["host"],
            es_index=cfg["es"]["ods_index"],
            progress_index=cfg["es"]["progress_index"],
        )
        self.cfg = cfg
        self.run_id = run_id
        self.year = year
        self.exclude_period = exclude_period
        self.dry_run = dry_run
        # 在 __init__ 期就拉列表，缓存为 self._all_periods
        self._all_periods = _h.fetch_all_periods(cfg)

    # ── SyncRunner 钩子实现 ──

    def _list_work_units(self) -> list[str]:
        """扁平化所有工作单元：列表 → 过滤 → period 字符串列表。

        过滤规则（与旧 sync.py 等价）：
        - --period / --year / --exclude-period
        - 本地进度中 status='ok' 的跳过
        """
        old_progress = self._load_old_progress()
        units = []
        for item in self._all_periods:
            if self.year and f"{self.year}年" not in item["title"]:
                continue
            if self.exclude_period and self.exclude_period in item["title"]:
                continue
            cached = old_progress.get(item["detail_url"])
            if cached and cached.get("status") == "ok":
                continue
            units.append(item)  # unit 仍是 dict，_process_one 用 detail_url
        return units

    def _process_one(self, unit: dict) -> tuple[int, str]:
        """处理单个 period：详情页 → PDF → minio → 解析 → ES。

        返回 (docs_count, status)，status ∈ {'completed', 'error', 'skipped'}。
        异常会向上抛，由 SyncRunner.run() 捕获后调用 _on_unit_done 带 error=str(e)。
        """
        cfg = self.cfg
        title = unit["title"]
        detail_url = unit["detail_url"]
        publish_date = unit["publish_date"]

        # 1. 详情页 → PDF 链接
        detail_html = fetch_html(detail_url, timeout=cfg["site"]["timeout_sec"])
        detail = _h.parse_detail_page(detail_html, cfg["site"]["base_url"], detail_url=detail_url)
        pdf_url = detail["pdf_url"]
        if not pdf_url:
            raise ValueError(f"详情页未找到 PDF 链接: {detail_url}")
        print(f"  PDF: {pdf_url}")

        with tempfile.TemporaryDirectory() as tmpdir:
            local_pdf = os.path.join(tmpdir, "source.pdf")
            # PDF 下载偶尔出现 IncompleteRead（hainan 网站中间会断连），加 3 次重试
            last_err = None
            for attempt in range(1, 4):
                try:
                    download_file(pdf_url, local_pdf, timeout=600)
                    last_err = None
                    break
                except Exception as e:
                    last_err = e
                    print(f"  [download retry {attempt}/3] {type(e).__name__}: {e}")
                    time.sleep(3 * attempt)
            if last_err:
                raise last_err

            # 2. period 归一化（'2026.1月'）
            period = _h.extract_period_from_title(title)
            if not period:
                raise ValueError(f"无法从 title 推断 period: {title}")
            print(f"  period: {period}")

            # 3. minio 上传
            minio_key = (
                f"{cfg['minio']['prefix']}/{period}/{detail['pdf_name']}.pdf"
                if detail.get("pdf_name")
                else f"{cfg['minio']['prefix']}/{period}/source.pdf"
            )
            if not self.dry_run:
                s3 = get_s3_client(cfg)
                upload_to_minio(s3, cfg["minio"]["bucket"], minio_key, local_pdf)
            print(f"  minio: {minio_key}")

            # 4. 检测是否为扫描图片 PDF（v0.8.2, 2026-07-06）
            #    扫描图片 PDF 文字密度极低（PDF 是图片拼起来的，没文本层），
            #    pdfplumber 抽不到结构化字段（no/breed/spec/unit 全空），
            #    写 ES 会污染数据。这种情况跳过入库，标 skipped_image_pdf。
            if _is_image_pdf(local_pdf):
                print(f"  [skip] 检测到扫描图片 PDF，需 OCR 才能解析，跳过入库（PDF 已上传 minio 留底）")
                return 0, "skipped_image_pdf"

            # 5. pdfplumber 解析
            rows = _h.parse_pdf(local_pdf)
            print(f"  parsed: {len(rows)} 行")

            # 6. 组装 ES 文档（字段映射与旧 main() 等价）
            # period 例 '2026.1月' → 同步补 period_start/end/days（标准 ODS 字段）
            period_start, period_end, period_days = _h.compute_period_range(period)
            now = datetime.now().isoformat(timespec="seconds")
            docs = []
            for r in rows:
                p = r.get("period") or period
                docs.append({
                    "no": r["no"],
                    "breed": r["breed"],
                    "spec": r["spec"],
                    "unit": r["unit"],
                    "price": r["price"],
                    "tax_price": r["tax_price"],
                    "remark": r.get("remark", ""),
                    "region": r["region"],
                    "section": r["section"],
                    "category": r["category"],
                    "period": p,
                    "period_start": period_start,
                    "period_end": period_end,
                    "period_days": period_days,
                    "province": "海南",
                    "city": "海南",
                    "update_date": publish_date,
                    "create_time": now,
                    "source_pdf": minio_key,
                    "source_url": pdf_url,
                })

            if self.dry_run:
                print(f"  [dry-run] 将写 {len(docs)} 条到 {cfg['es']['ods_index']}")
                return 0, "skipped"

            # 7. bulk 写 ES
            es = get_es_client(cfg["es"]["host"])
            ensure_ods_index(es, cfg["es"]["host"], cfg["es"]["ods_index"])
            ensure_progress_index(es, cfg["es"]["progress_index"])
            ok, err = _h.bulk_index(es, cfg["es"]["ods_index"], docs)
            print(f"  bulk: ok={ok}, err={err}")
            return ok, ("completed" if err == 0 else "error")

    def _on_unit_done(self, unit, docs_count: int, status: str, error: str = "") -> None:
        """重写钩子：完成后写 ES progress + 保存本地进度（与旧 main() 等价）。"""
        item = unit
        period = _h.extract_period_from_title(item["title"])

        # 本地进度：复用旧 .hainan_sync_progress.json 格式（{'done': {detail_url: {...}}}）
        progress = self._load_old_progress()
        if status == "completed":
            progress[item["detail_url"]] = {
                "period": period,
                "publish_date": item["publish_date"],
                "detail_url": item["detail_url"],
                "docs_written": docs_count,
                "status": "ok",
                "duration_sec": 0.0,
                "created_at": datetime.now().isoformat(timespec="seconds"),
            }
        else:
            # status ∈ {'error', 'skipped'}；原 sync.py 统一标 failed + error 消息
            progress[item["detail_url"]] = {
                "publish_date": item["publish_date"],
                "detail_url": item["detail_url"],
                "status": "failed" if status == "error" else status,
                "error": error or "",
                "duration_sec": 0.0,
            }
        os.makedirs(os.path.dirname(self.progress.path), exist_ok=True)
        with open(self.progress.path, "w", encoding="utf-8") as f:
            json.dump({"done": progress}, f, ensure_ascii=False, indent=2)

        # ES progress（仅成功时写）
        if status == "completed" and not self.dry_run:
            try:
                es = get_es_client(self.es_host)
                ensure_progress_index(es, self.progress_index)
                es.index(index=self.progress_index, body={
                    "run_id": self.run_id,
                    "period": period,
                    "publish_date": item["publish_date"],
                    "detail_url": item["detail_url"],
                    "docs_written": docs_count,
                    "status": "ok",
                    "created_at": datetime.now().isoformat(timespec="seconds"),
                })
            except Exception as e:
                print(f"  [warn] ES progress 写入失败: {e}")

        icon = "✓" if status == "completed" else ("⊘" if status == "skipped_image_pdf" else ("·" if status == "skipped" else "✗"))
        err_msg = f" — {error}" if error else ""
        print(f"  [{icon}] {item['title'][:60]}...  {docs_count} docs ({status}){err_msg}")

    def _compute_unit_key(self, unit) -> str:
        """本地进度 key：用 detail_url（旧格式以 detail_url 作 key）。"""
        return unit["detail_url"]

    # ── 私有工具方法 ──

    def _load_old_progress(self) -> dict:
        """加载旧格式本地进度 {'done': {detail_url: {...}}}，向后兼容。

        旧文件结构是顶层包了 'done' 键；新 SyncRunner 默认按 key-字符串存，这里做个桥接。
        """
        raw = self.progress.load()
        if isinstance(raw, dict) and "done" in raw:
            return raw["done"]
        # 第一次跑或文件不存在：返回空 dict
        return {}


# ─────────────────────────────────────────────────────────────
# 工厂方法
# ─────────────────────────────────────────────────────────────

def make_collector(
    cfg: dict,
    run_id: str,
    year: int = 0,
    exclude_period: str = "",
    dry_run: bool = False,
) -> HainanCollector:
    """构造 HainanCollector。"""
    return HainanCollector(
        cfg=cfg,
        run_id=run_id,
        year=year,
        exclude_period=exclude_period,
        dry_run=dry_run,
    )


# ─────────────────────────────────────────────────────────────
# CLI 入口（与 chongqing sync.py 形态对齐）
# ─────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="海南工程造价材料信息同步（Collector 版）")
    parser.add_argument("--period", default="", help="指定周期（substring 匹配 title）")
    parser.add_argument("--year", type=int, default=0, help="只入库指定年份的期")
    parser.add_argument("--exclude-period", default="", help="排除指定周期（substring 匹配）")
    parser.add_argument("--all", action="store_true", help="同步所有未入仓的期")
    parser.add_argument("--latest", action="store_true", help="只同步最新一期")
    parser.add_argument("--reset", action="store_true", help="重置本地进度")
    parser.add_argument("--dry-run", action="store_true", help="预览，不写入 ES/minio")
    parser.add_argument("--max-units", type=int, default=0, help="最多处理多少 unit（测试用）")
    args = parser.parse_args()

    cfg = load_config()
    run_id = f"v08_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    # latest / --period 模式：构造期间/年份过滤器
    year = args.year
    exclude = args.exclude_period

    collector = make_collector(
        cfg=cfg,
        run_id=run_id,
        year=year,
        exclude_period=exclude,
        dry_run=args.dry_run,
    )

    # 先确保桶/索引存在（即便 dry_run 也建桶，安全）
    try:
        s3 = get_s3_client(cfg)
        ensure_bucket(s3, cfg["minio"]["bucket"])
        es = get_es_client(cfg["es"]["host"])
        ensure_ods_index(es, cfg["es"]["host"], cfg["es"]["ods_index"])
        ensure_progress_index(es, cfg["es"]["progress_index"])
    except Exception as e:
        print(f"[warn] init 失败（首次跑可忽略）: {e}")

    # --latest / --period / --all 不直接映射 SyncRunner run()，
    # 这里在工厂方法后再补一层过滤（用 list 切片，最简实现）
    if args.latest:
        all_units = collector._list_work_units()
        if not all_units:
            print("[hainan] 无新数据")
            return
        # 只保留最新一条
        first = all_units[0]
        # 替换 progress key 让 SyncRunner 不跳过
        # 用 monkey-patch：把 _list_work_units 包成单元素
        collector._list_work_units = lambda: [first]
    elif args.period:
        # --period substring 匹配 title
        old_list = collector._list_work_units
        collector._list_work_units = lambda: [
            u for u in old_list() if args.period in u["title"]
        ]

    print(f"[hainan] run_id={run_id}")
    print(f"[hainan] filters: year={year or '-'}  exclude={exclude or '-'}  period={args.period or '-'}  latest={args.latest}")

    if args.dry_run:
        # dry-run 模式：仍跑全流程但 _process_one 返回 skipped，不写 ES/minio
        pass

    result = collector.run(max_units=args.max_units or None, reset=args.reset)

    # 汇总
    print()
    print("=" * 60)
    print(f"[hainan] 总单元: {result['total']}")
    print(f"[hainan] 完成:   {result['done']}")
    print(f"[hainan] 失败:   {result['failed']}")
    print(f"[hainan] 跳过:   {result['skipped']}")
    print(f"[hainan] 写入:   {result['docs_written']} 条")
    print(f"[hainan] 耗时:   {result['duration_sec']:.1f}s")
    if result["interrupted"]:
        print("[hainan] ⚠️  被 SIGINT 中断（已保留进度）")


if __name__ == "__main__":
    main()
