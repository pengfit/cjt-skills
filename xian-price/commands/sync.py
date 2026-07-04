"""同步入口 - 默认走 xian_collector（v0.8 SyncRunner 抽象基类化, 2026-07-04）

v0.8 改造：
  - 默认走 XianCollector（commands/xian_collector.py，SyncRunner 化版本）
  - --legacy 走原 v0.6 main 流程（逃生通道，保留全部 v0.6 行为）
  - 字段扩展（道友要求）：doc 中新增 period_start / period_end / period_days
  - 通用基础设施（SIGINT / 进度 / 汇总）由 SyncRunner 基类提供

模块建构参考 chongqing v0.8 试点 + huhehaote v0.8。

CLI 速览：
  # 抓 2026 年所有月份（6 区县 × 5 月 = 30 个 unit）
  python3 commands/sync.py --periods-year 2026

  # 指定区县 / 月份
  python3 commands/sync.py --period 2026-01 --counties "阎良区,周至县"

  # 多周期
  python3 commands/sync.py --periods "2026-01,2026-02,2026-03" --counties 阎良区

  # 列出所有区县 × 年的可用周期
  python3 commands/sync.py --list-periods
  python3 commands/sync.py --list-periods --counties 阎良区 --list-year 2026

  # 重置 / 限制 / 兼容
  python3 commands/sync.py --periods-year 2026 --reset
  python3 commands/sync.py --periods-year 2026 --max-units 1  # 验证用
  python3 commands/sync.py --periods-year 2026 --legacy        # 走 v0.6 老流程
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import warnings
warnings.filterwarnings('ignore')

import argparse
import hashlib
import json
import time
import signal
from datetime import datetime

import requests
from commands.utils import (
    SiteSession, parse_page_date, parse_county, parse_total_records, parse_table_rows,
    get_last_update_date, get_last_update_date_by_county, spot_check_county, save_sync_time, ensure_index, load_config, COUNTY_CODES,
    list_all_years, normalize_period,
)

interrupted = False


def _signal_handler(signum, frame):
    global interrupted
    interrupted = True
    print("\n[!] 接收到中断信号，正在保存进度...")


def _print_page_line(page, total_pages, rows_len, docs_written, dry_run):
    """动态刷新单行进度，同行覆写。"""
    pct = page / total_pages * 100 if total_pages else 0
    done = "█" * int(pct / 5) + "░" * (20 - int(pct / 5))
    status = f"✓{docs_written}" if not dry_run else f"预览{docs_written}"
    line = f"\r  [页 {page}/{total_pages}] {rows_len}条 {status} |{done}| {pct:.0f}%   "
    sys.stdout.write(line)
    sys.stdout.flush()


class ProgressStore:
    """本地进度持久化

    key 格式:
        - 旧格式: <county>  （不指定 period 时使用）
        - 新格式: <county>@<period>  （指定 period 时使用）
    """

    def __init__(self, store_dir=None):
        if store_dir is None:
            store_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.path = os.path.join(store_dir, '.sync_progress.json')
        self.data = self._load()

    def _load(self):
        if os.path.exists(self.path):
            try:
                with open(self.path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception:
                pass
        return {}

    @staticmethod
    def _key(county, period=''):
        if period:
            return f"{county}@{period}"
        return county

    def save(self, county, page, update_date, total_records, docs_written, period=''):
        self.data[self._key(county, period)] = {
            'county': county,
            'period': period,
            'page': page,
            'update_date': update_date,
            'total_records': total_records,
            'docs_written': docs_written,
            'saved_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        }
        try:
            with open(self.path, 'w', encoding='utf-8') as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def get_page(self, county, period=''):
        return self.data.get(self._key(county, period), {}).get('page', 1)

    def clear(self, county, period=''):
        key = self._key(county, period)
        if key in self.data:
            del self.data[key]
            try:
                with open(self.path, 'w', encoding='utf-8') as f:
                    json.dump(self.data, f, ensure_ascii=False, indent=2)
            except Exception:
                pass

    def clear_county(self, county):
        """清除该区县所有 period 的进度"""
        keys = [k for k in self.data if k == county or k.startswith(f"{county}@")]
        for k in keys:
            del self.data[k]
        if keys:
            try:
                with open(self.path, 'w', encoding='utf-8') as f:
                    json.dump(self.data, f, ensure_ascii=False, indent=2)
            except Exception:
                pass


class ProgressLogger:
    """同步进度实时写入 ES（material_xian_price_sync_progress），每个区县一条记录"""

    PROGRESS_INDEX = "ods_material_xian_price_sync_progress"

    STATUS_RUNNING = "running"
    STATUS_COMPLETED = "completed"
    STATUS_INTERRUPTED = "interrupted"
    STATUS_ERROR = "error"

    def __init__(self, es_host, progress_index=None):
        self.es_host = es_host
        self.index = progress_index or self.PROGRESS_INDEX
        self.run_id = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
        self.state = {
            "run_id": self.run_id,
            "status": self.STATUS_RUNNING,
            "current_county": "",
            "current_page": 0,
            "total_pages": 0,
            "total_records": 0,
            "docs_written": 0,
            "percent": 0.0,
            "duration_sec": 0.0,
            "update_date": "",
            "last_updated": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            "error": "",
            "spot_check_ok": None,
            "spot_check_details": "",
        }
        self._ensure_index()

    def _ensure_index(self):
        """v0.6 (2026-07-02) ：委托到 gov_price_etl.indexer.ensure_progress_index。"""
        try:
            from gov_price_etl.indexer import ensure_progress_index
            ensure_progress_index(self.es_host, self.index)
        except Exception:
            # 头项控例：如 gov_price_etl 不可用，原 fall back 静默略过（保持旧行为）
            pass

    def _upsert(self):
        """写入当前区县进度记录，_id = run_id_current_county"""
        county = self.state.get("current_county", "unknown")
        doc = dict(self.state)
        doc["last_updated"] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        doc_id = f"{self.run_id}_{county}"
        try:
            requests.post(
                f"{self.es_host}/{self.index}/_doc/{doc_id}",
                json=doc, timeout=10, verify=False
            )
        except Exception:
            pass

    def set_county(self, county):
        """切换到新区县（写入上一区县记录，然后切换）"""
        self.state["current_county"] = county
        self._upsert()

    def page_progress(self, page, total_pages, docs_written, total_records, update_date, duration_sec=0.0):
        """每页抓取后调用，更新当前区县进度"""
        self.state.update(
            current_page=page,
            total_pages=total_pages,
            total_records=total_records,
            docs_written=docs_written,
            percent=round((page / total_pages * 100) if total_pages > 0 else 0, 2),
            duration_sec=round(duration_sec, 2),
            update_date=update_date or "",
        )
        self._upsert()

    def finish_county(self, docs_written, duration_sec=0.0):
        """区县完成"""
        self.state["status"] = self.STATUS_COMPLETED
        self.state["docs_written"] = docs_written
        self.state["percent"] = 100.0
        self.state["duration_sec"] = round(duration_sec, 2)
        self._upsert()

    def set_spot_check(self, ok, details):
        """抽检结果写入 spot_check 记录"""
        doc_id = f"{self.run_id}_spot"
        doc = {
            "run_id": self.run_id,
            "spot_check_ok": ok,
            "spot_check_details": details,
            "last_updated": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        }
        try:
            requests.post(
                f"{self.es_host}/{self.index}/_doc/{doc_id}",
                json=doc, timeout=10, verify=False
            )
        except Exception:
            pass


def _doc_id(breed, code, spec, county, update_date, price="", tax_price="", period=""):
    """计算 ES doc _id

    优先用 period（YYYY-MM）作维度粒度，保证同一材料不同月份有不同 _id。
    无 period 时退化为 update_date（兼容旧版）。
    """
    period_key = period or update_date or ''
    raw = f"{breed}_{code}_{spec}_{county}_{period_key}_{price}_{tax_price}"
    return hashlib.md5(raw.encode('utf-8')).hexdigest()


def _make_doc(r, county, update_date, period="", gkbh="", published_at=""):
    """构建写入 ES 的 doc

    字段语义:
        update_date:   页脚"更新时间" YYYY-MM-DD（始终保持原行为，保证 ES date 映射合法）
        period:        YYYY-MM（所属月份，传了才写入）
        gkbh:          源站周期 ID（传了才写入）
        published_at:  与 update_date 同义（传了才写入，查询起来语义更清晰）
    """
    breed = r.get('breed', '')
    code = r.get('code', '')
    spec = r.get('spec', '')
    doc_id = _doc_id(breed, code, spec, county, update_date or '', price=r.get('price',''), tax_price=r.get('tax_price',''), period=period)
    doc = {
        **r,
        '_id': doc_id,
        'county': county,
        'province': '陕西',
        'city': '西安',
        'update_date': update_date or '',
        'create_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
    }
    if period:
        doc['month'] = period  # 用 'month' 避免被 ES dynamic mapping 推断为 date
    if gkbh:
        doc['gkbh'] = gkbh
    if published_at:
        doc['published_at'] = published_at
    return doc


def _parse_args_for_legacy():
    """v0.6 老 main 流程用的 argparse（与新 CLI 兼容）。"""
    import argparse
    parser = argparse.ArgumentParser(description='同步西安材料价格数据（v0.6 兼容）')
    parser.add_argument('--config', type=str, default=None)
    parser.add_argument('--force', action='store_true')
    parser.add_argument('--max-pages', type=int, default=2000)
    parser.add_argument('--counties', type=str, default=None)
    parser.add_argument('--resume-from', type=str, default=None)
    parser.add_argument('--reset', action='store_true')
    parser.add_argument('--no-log', action='store_true')
    parser.add_argument('--no-spot-check', action='store_true')
    # 周期筛选（按区县 X 造价信息表月份 抓取）
    parser.add_argument('--period', type=str, default=None,
                        help='指定周期，逗号分隔，如 2026-01,2026-02')
    parser.add_argument('--periods-year', type=int, default=None,
                        help='指定整年的所有月份，如 2026')
    parser.add_argument('--periods-all', action='store_true',
                        help='抓取所有有数据的年月（源站 2024 至今）')
    parser.add_argument('--list-periods', action='store_true',
                        help='只列出可用周期，不抓取')
    parser.add_argument('--dry-run', action='store_true',
                        help='预览模式（不写入 ES）')
    return parser


def cmd_legacy_sync(args=None):
    """v0.6 老同步流程（保留全部旧行为，作为 --legacy 逃生通道）。"""
    start_time = time.time()

    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    if args is None:
        args = _parse_args_for_legacy().parse_args()

    script_dir = __file__.rsplit('/', 1)[0]
    config_path = args.config or f"{script_dir}/../config.yml"
    config = load_config(config_path)

    es_host = config['es']['host']
    es_index = config['es']['index']
    log_index = config['es'].get('sync_log_index', 'ods_material_xian_price_sync_log')
    counties = config['site']['counties']
    last_update_date = config['sync'].get('last_update_date', '')

    logger = ProgressLogger(es_host, progress_index=config['es'].get('progress_index')) if not args.no_log else None

    # ── --list-periods 模式：只列可用周期，不抓取 ──
    if args.list_periods:
        print("\n[i] 可用周期列表（按区县×年）：")
        list_sess = SiteSession(max_retries=2, timeout=15)
        list_counties = counties
        if args.counties:
            list_counties = [c.strip() for c in args.counties.split(',')]
        years = [args.periods_year] if args.periods_year else list_all_years(list_counties[0], list_sess) if list_counties else list_all_years('阎良区', list_sess)
        for county in list_counties:
            print(f"\n  === {county} ===")
            for y in (years or []):
                ps = list_sess.list_periods(county, y)
                if not ps:
                    continue
                # 按 period 升序
                ps_sorted = sorted([p for p in ps if p.get('period')], key=lambda x: x['period'])
                for p in ps_sorted:
                    print(f"    {p['period']:8s}  gkbh={p['id']}  {p['name']}")
        sys.exit(0)

    # ── 增量抽检（可跳过）──
    has_period = bool(args.period or args.periods_year or args.periods_all)
    if not args.no_spot_check and not has_period:
        print("\n[i] 增量抽检：ES入库最早10条 vs 网站首页记录")
        spot_issues = []
        try:
            spot_session = SiteSession(max_retries=3, timeout=30)
            for county in counties:
                html = spot_session.fetch(county, page=1)
                site_date = parse_page_date(html) if html else None
                site_rows = parse_table_rows(html) if html else []
                result = spot_check_county(es_host, es_index, county, site_rows)
                if result["consistent"]:
                    print(f"  [{county}] {site_date or '?'} ✓ 一致")
                else:
                    n = len(result["mismatches"])
                    print(f"  [{county}] {site_date or '?'} ✗ 不一致（{n}条记录不同）")
                    for m in result["mismatches"][:3]:
                        print(f"      - {m['es_breed'][:20]} | {m['es_spec'][:15]} | {m['es_unit']} | 含税:{m['es_tax_price']} | 录入:{m['es_update']} | {m['reason']}")
                    spot_issues.append({"county": county, "mismatches": result["mismatches"]})
            if spot_issues:
                print(f"\n  [!] 发现 {len(spot_issues)} 个区县存在不一致：")
                for item in spot_issues:
                    print(f"      {item['county']}: {len(item['mismatches'])} 条记录不同")
                if logger:
                    details = "; ".join([f"{it['county']}({len(it['mismatches'])}条不同)" for it in spot_issues])
                    logger.set_spot_check(False, details)
            else:
                print(f"\n  [i] 抽检通过，所有区县已同步至最新")
                if logger:
                    logger.set_spot_check(True, "全部6区县一致")
        except Exception as e:
            print(f"  [!] 抽检异常: {e}")

    if args.counties:
        specified = [c.strip() for c in args.counties.split(',')]
        invalid = [c for c in specified if c not in counties]
        if invalid:
            print(f"[!] 未知区县: {', '.join(invalid)}")
            sys.exit(1)
        counties = specified

    resume_county = args.resume_from
    if resume_county:
        if resume_county not in counties:
            print(f"[!] resume-from 区县不在列表中: {resume_county}")
            sys.exit(1)
        idx = counties.index(resume_county)
        counties = counties[idx:]
        print(f"[i] 恢复同步从 {resume_county} 开始")

    dry_run = '--dry-run' in sys.argv
    force = '--force' in sys.argv

    if not dry_run:
        ensure_index(es_host, es_index)

    effective_last_date = last_update_date
    if not effective_last_date and not force:
        es_last = get_last_update_date(es_host, es_index)
        if es_last:
            effective_last_date = es_last
            print(f"[i] 从 ES 读取到上次更新时间: {effective_last_date}")
        else:
            print("[i] 首次全量同步")

    progress = ProgressStore()

    if args.reset:
        for county in counties:
            progress.clear_county(county)
        print("[i] 已重置所有进度")

    # ── 构建抓取任务列表（带 period 时返回 jobs，否则返回空走老逻辑）──
    jobs_sess = SiteSession(max_retries=2, timeout=15)
    jobs = _build_jobs(counties, args, jobs_sess)
    if jobs:
        print(f"[i] 按周期抓取：共 {len(jobs)} 个任务")
        for j in jobs:
            print(f"     - {j['county']} {j['period']} (gkbh={j['gkbh']})")


    print(f"\n{'='*60}")
    print(f"  西安工程造价材料信息同步")
    print(f"  目标索引: {es_index}")
    print(f"  进度索引: {logger.index if logger else '关闭'}")
    print(f"  上次更新时间: {effective_last_date or '首次全量'}")
    print(f"  模式: {'dry-run' if dry_run else '正式同步'}")
    print(f"{'='*60}\n")

    total_docs = 0
    new_update_date = None
    county_start_time = None

    # 构造循环列表：job = {'county', 'period', 'gkbh'}；period='' 走老逻辑
    loop_jobs: list = jobs if jobs else [{'county': c, 'period': '', 'gkbh': ''} for c in counties]

    for job in loop_jobs:
        if interrupted:
            if logger:
                logger.state["status"] = logger.STATUS_INTERRUPTED
                logger.state["current_page"] = start_page
                logger.state["docs_written"] = county_docs
                logger._upsert()
            print("\n[!] 已中断，进度已保存")
            break

        county = job['county']
        period = job.get('period', '')
        gkbh = job.get('gkbh', '')

        start_page = progress.get_page(county, period)
        if start_page > 1 and not args.reset:
            label = f"{county} {period}".strip() if period else county
            print(f"[i] 检测到 {label} 上次同步到第 {start_page} 页，自动续传")
        else:
            start_page = 1
            progress.clear(county, period)

        county_start_time = time.time()
        job_label = f"{county} {period}".strip() if period else county
        print(f"\n[▼] 任务: {job_label}" + (f"  (gkbh={gkbh})" if gkbh else ""))
        session = SiteSession(max_retries=5, timeout=60)

        html = session.fetch(county, page=start_page, gkbh=gkbh or None)
        if not html:
            msg = f"第{start_page}页抓取失败"
            print(f"  [!] {msg}")
            if logger:
                logger.state["status"] = logger.STATUS_ERROR; logger.state["error"] = msg; logger._upsert()
            continue

        page_county = parse_county(html)
        page_published_at = parse_page_date(html)
        total_records = parse_total_records(html)
        rows = parse_table_rows(html)
        total_pages = (total_records + 9) // 10 if total_records > 0 else 0

        # update_date 始终用页脚 YYYY-MM-DD（ES date 映射要求）
        # month（YYYY-MM）和 gkbh 是另外两个独立字段，供周期查询用
        doc_update_date = page_published_at or ''
        # 无 period 模式：不写 published_at（避免与 update_date 冗余）
        published_at = page_published_at or '' if period else ''

        marker = f"@{start_page}起始" if start_page > 1 else ""
        period_label = f" 周期={period}" if period else ""
        print(f"  [{page_county or county}{marker}{period_label}] | 页脚={page_published_at} | 共{total_records}条 | 约{total_pages}页")

        if logger:
            logger.state["current_county"] = job_label
            logger.state["status"] = logger.STATUS_RUNNING
            logger.state["current_page"] = start_page
            logger.state["total_pages"] = total_pages
            logger.state["total_records"] = total_records
            logger.state["docs_written"] = 0
            logger.state["percent"] = 0.0
            logger.state["update_date"] = doc_update_date or ""
            logger.state["error"] = ""
            logger._upsert()

        _print_page_line(start_page, total_pages, len(rows), 0, dry_run)

        county_docs = 0

        if rows:
            page_docs = _write_docs(es_host, es_index, rows, county, doc_update_date, dry_run,
                                     period=period, gkbh=gkbh, published_at=published_at)
            _print_page_line(start_page, total_pages, len(rows), page_docs, dry_run)
            county_docs += page_docs
            total_docs += page_docs

        if doc_update_date and (new_update_date is None or doc_update_date > new_update_date):
            new_update_date = doc_update_date

        if total_pages == 0 or total_pages > args.max_pages:
            total_pages = args.max_pages

        if not dry_run:
            progress.save(county, start_page, doc_update_date, total_records, county_docs, period=period)
            if logger:
                elapsed = time.time() - start_time
                logger.page_progress(start_page, total_pages, county_docs, total_records, doc_update_date or '', elapsed)

        consecutive_empty = 0

        for page in range(start_page + 1, total_pages + 1):
            if interrupted:
                print(f"\n[!] 页 {page} 中断，已保存进度")
                if logger:
                    logger.state["status"] = logger.STATUS_INTERRUPTED
                    logger.state["current_page"] = page
                    logger.state["docs_written"] = county_docs
                    logger._upsert()
                break

            html = session.fetch(county, page, gkbh=gkbh or None)
            if not html:
                msg = f"页 {page} 抓取失败"
                print(f"\n  [!] {msg}")
                if logger:
                    logger.state["status"] = logger.STATUS_ERROR; logger.state["error"] = msg; logger._upsert()
                break

            page_published_at = parse_page_date(html)
            rows = parse_table_rows(html)
            doc_update_date = page_published_at or ''
            published_at = page_published_at or '' if period else ''

            _print_page_line(page, total_pages, len(rows), 0, dry_run)

            if not rows:
                sys.stdout.write(" [空]")
                sys.stdout.flush()
                consecutive_empty += 1
                if consecutive_empty >= 3:
                    print(" 连续3页空，停止")
                    break
                page += 1
                time.sleep(1)
                continue
            consecutive_empty = 0

            if not period and doc_update_date and effective_last_date and not force and doc_update_date < effective_last_date:
                # 仅无 period 模式（YYYY-MM-DD 粒度）才做增量判断
                print(f"\n  [✓] 停止：{doc_update_date} < {effective_last_date}")
                break

            page_docs = _write_docs(es_host, es_index, rows, county, doc_update_date, dry_run,
                                     period=period, gkbh=gkbh, published_at=published_at)
            _print_page_line(page, total_pages, len(rows), page_docs, dry_run)
            county_docs += page_docs
            total_docs += page_docs

            if doc_update_date and (new_update_date is None or doc_update_date > new_update_date):
                new_update_date = doc_update_date

            progress.save(county, page, doc_update_date, total_records, county_docs, period=period)
            if logger:
                elapsed = time.time() - start_time
                logger.page_progress(page, total_pages, county_docs, total_records, doc_update_date or '', elapsed)

            if interrupted:
                print(f"\n  [!] 页 {page} 中断，已保存进度")
                if logger:
                    logger.state["status"] = logger.STATUS_INTERRUPTED
                    logger.state["current_page"] = page
                    logger.state["docs_written"] = county_docs
                    logger._upsert()
                break

            time.sleep(0.8)

        if interrupted:
            # 中断时页码已由上面循环内的 if 处理
            print(f"\n  [{job_label}] 中断于页 ~{page}，进度已保存")
        else:
            progress.clear(county, period)
            duration = time.time() - county_start_time
            print(f"\n  [{job_label}] ✓ 完成 (写入 {county_docs} 条, {duration:.0f}s)")
            if logger:
                logger.finish_county(county_docs, duration)

    duration_sec = time.time() - start_time
    print(f"\n{'='*60}")
    print(f"  同步完成: 共 {total_docs} 条文档")
    if new_update_date:
        print(f"  最新更新时间: {new_update_date}")
        if not dry_run:
            save_sync_time(config_path, new_update_date)
    print(f"  总耗时: {duration_sec:.0f}s")

    if interrupted:
        print(f"  ⚠ 程序被中断，进度已自动保存，重启后可继续")
    print(f"{'='*60}")


def _build_jobs(counties: list, args, session: SiteSession) -> list:
    """根据 --period/--periods-year/--periods-all 构建抓取任务列表

    Returns:
        [
            {'county': '阎良区', 'period': '2026-01', 'gkbh': '0000000595'},
            {'county': '阎良区', 'period': '2026-02', 'gkbh': '0000000617'},
            ...
        ]

        若三个参数都没传，返回空列表，调用方走 "全量页码" 逻辑。
    """
    has_period = bool(args.period or args.periods_year or args.periods_all)
    if not has_period:
        return []

    wanted_periods: set = set()
    if args.period:
        for p in args.period.split(','):
            p = normalize_period(p)
            if p:
                wanted_periods.add(p)
    if args.periods_year:
        y = args.periods_year
        for m in range(1, 13):
            wanted_periods.add(f"{y}-{m:02d}")
    # --periods-all: 调用 list_all_years 获取所有有数据的年份
    years_to_scan = []
    if args.periods_all or args.periods_year:
        # 全量扫描：由 list_all_years 决定
        if args.periods_all:
            for c in counties:
                ys = list_all_years(c, session)
                for y in ys:
                    if y not in years_to_scan:
                        years_to_scan.append(y)
        else:
            years_to_scan = [args.periods_year]

    jobs = []
    for county in counties:
        # 合并：该区县在 wanted_periods 中的 + 该区县在扫描年里的所有 period
        county_periods = set()
        if wanted_periods:
            county_periods |= wanted_periods
        if years_to_scan:
            for y in years_to_scan:
                ps = session.list_periods(county, y)
                for p in ps:
                    if p.get('period'):
                        county_periods.add(p['period'])
        if not county_periods:
            print(f"  [!] {county}: 未找到匹配的周期")
            continue
        for period in sorted(county_periods):
            # 拿 gkbh
            y = int(period.split('-')[0])
            ps = session.list_periods(county, y)
            gkbh = ''
            for p in ps:
                if p.get('period') == period:
                    gkbh = p.get('id', '')
                    break
            if not gkbh:
                print(f"  [!] {county} {period}: 未在源站找到 gkbh，跳过")
                continue
            jobs.append({'county': county, 'period': period, 'gkbh': gkbh})
    return jobs


def _write_docs(es_host, es_index, rows, county, update_date, dry_run, period="", gkbh="", published_at=""):
    if not rows:
        return 0
    docs = [_make_doc(r, county, update_date, period=period, gkbh=gkbh, published_at=published_at) for r in rows]

    if dry_run:
        return len(docs)

    bulk_body = ''
    for doc in docs:
        doc_id = doc.pop('_id')
        bulk_body += json.dumps({"index": {"_index": es_index, "_id": doc_id}}, ensure_ascii=False) + '\n'
        bulk_body += json.dumps(doc, ensure_ascii=False) + '\n'

    try:
        resp = requests.post(
            f"{es_host}/_bulk",
            data=bulk_body.encode('utf-8'),
            headers={"Content-Type": "application/x-ndjson"},
            timeout=30,
            verify=False
        )
        if resp.status_code in (200, 201):
            items = resp.json().get('items', [])
            written = sum(
                1 for item in items
                if item.get('index', {}).get('result') in ('created', 'updated')
            )
            errors = sum(1 for item in items if item.get('index', {}).get('error'))
            if errors:
                print(f"  [!]{errors}条失败", end='', flush=True)
            return written
    except Exception:
        return 0

    return 0


# ─────────────────────────────────────────────────────────────
# CLI 入口（v0.8 新版）
# ─────────────────────────────────────────────────────────────

def _build_periods(args) -> list[str]:
    """根据 --period / --periods / --periods-year 拼装 periods 列表（YYYY-MM）。"""
    out: list[str] = []
    if getattr(args, 'period', None):
        for p in args.period.split(','):
            p_norm = normalize_period(p.strip())
            if p_norm:
                out.append(p_norm)
    if getattr(args, 'periods', None):
        for p in args.periods.split(','):
            p_norm = normalize_period(p.strip())
            if p_norm:
                out.append(p_norm)
    if getattr(args, 'periods_year', None):
        y = args.periods_year
        for m in range(1, 13):
            out.append(f"{y}-{m:02d}")
    # 去重 + 排序
    return sorted(set(out))


def _list_periods_cli(cfg_path: str, counties: list[str], year: int | None) -> None:
    """打印所有 (county, year, period) 组合。"""
    from commands.xian_collector import list_available_periods
    data = list_available_periods(cfg_path, counties=counties, year=year)
    print(f"\n[i] 可用周期列表：")
    for county, year_map in data.items():
        print(f"\n  === {county} ===")
        for y in sorted(year_map.keys(), reverse=True):
            print(f"    -- {y}年 --")
            for p in year_map[y]:
                print(f"      {p['period']:8s}  gkbh={p['gkbh']:14s}  "
                      f"{p['period_start']}~{p['period_end']} ({p['period_days']}天)  "
                      f"{p['name']}")


def main():
    """v0.8 CLI 入口：默认走 XianCollector（SyncRunner 化），--legacy 走 v0.6。"""
    parser = argparse.ArgumentParser(
        description='西安工程造价材料信息同步（v0.8 SyncRunner 化）',
    )
    parser.add_argument('--config', default=None, help='config.yml 路径（默认 skill 根目录）')
    # Collector 路径参数（推荐）
    parser.add_argument('--period', default='', help='单周期，如 2026-01')
    parser.add_argument('--periods', default='', help='多周期，逗号分隔，如 "2026-01,2026-02"')
    parser.add_argument('--periods-year', type=int, default=0,
                        help='整年所有月份，如 2026')
    parser.add_argument('--counties', default='', help='指定区县，逗号分隔，如 "阎良区,周至县"')
    parser.add_argument('--list-periods', action='store_true', help='只列出可用周期，不抓取')
    parser.add_argument('--list-year', type=int, default=0, help='--list-periods 时限定年份')
    parser.add_argument('--reset', action='store_true', help='重置进度')
    parser.add_argument('--max-units', type=int, default=None, help='只跑前 N 个 unit（验证用）')
    parser.add_argument('--run-id', default='', help='指定 run_id（默认自动生成）')
    parser.add_argument('--legacy', action='store_true',
                        help='v0.6 兼容：走原 main 流程。默认走 Collector。')
    parser.add_argument('--no-progress', action='store_true', help='不写 ES progress 索引')

    args = parser.parse_args()

    cfg_path = args.config or os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        'config.yml',
    )

    # ── --legacy：走 v0.6 老 main 流程 ──
    if args.legacy:
        print('[v0.6 兼容路径] cmd_legacy_sync 启动')
        legacy_args = _parse_args_for_legacy().parse_args()
        # 同步新 CLI 的参数到 legacy（让两者行为一致）
        if args.counties:
            legacy_args.counties = args.counties
        if args.period:
            legacy_args.period = args.period
        if args.periods:
            legacy_args.period = args.periods
        if args.periods_year:
            legacy_args.periods_year = args.periods_year
        if args.reset:
            legacy_args.reset = True
        cmd_legacy_sync(legacy_args)
        return

    # ── 默认路径：XianCollector（v0.8 SyncRunner 抽象基类） ──
    from commands.xian_collector import make_collector

    # --list-periods
    if args.list_periods:
        counties = [c.strip() for c in args.counties.split(',')] if args.counties else None
        _list_periods_cli(cfg_path, counties=counties, year=args.list_year or None)
        return

    # 没有指定任何 period → 默认 2026 年（道友要求范围）
    periods = _build_periods(args)
    if not periods:
        periods = [f"2026-{m:02d}" for m in range(1, 13)]
        print(f"[i] 未指定 period，默认 2026 年（{len(periods)} 个月份）")

    # 区县过滤
    counties: list[str] = []
    if args.counties:
        counties = [c.strip() for c in args.counties.split(',') if c.strip()]
    # counties 为空 → 走默认从 config 读（在 make_collector 内部处理）

    run_id = args.run_id or f"xian_v08_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    print(f'[Collector 路径 v0.8] XianCollector 启动')
    print(f'  run_id      = {run_id}')
    print(f'  periods     = {periods}')
    print(f'  counties    = {counties or "<全部 6 区县>"}')
    print(f'  reset       = {args.reset}')
    print(f'  max_units   = {args.max_units}')

    collector = make_collector(
        cfg_path=cfg_path,
        run_id=run_id,
        counties=counties or None,
        periods=periods,
        skip_progress=args.no_progress,
    )
    result = collector.run(reset=args.reset, max_units=args.max_units)
    print(f'\n[Collector 路径 v0.8] 完成: {result}')


if __name__ == '__main__':
    main()
