"""同步命令 - 抓取西安材料价格数据并写入 ES（支持增量+断点续传+执行日志）"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import warnings
warnings.filterwarnings('ignore')

import hashlib
import json
import time
import signal

import requests
from datetime import datetime
from commands.utils import (
    SiteSession, parse_page_date, parse_county, parse_total_records, parse_table_rows,
    get_last_update_date, get_last_update_date_by_county, spot_check_county, save_sync_time, ensure_index, load_config, COUNTY_CODES
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
    """本地进度持久化"""

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

    def save(self, county, page, update_date, total_records, docs_written):
        self.data[county] = {
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

    def get_page(self, county):
        return self.data.get(county, {}).get('page', 1)

    def clear(self, county):
        if county in self.data:
            del self.data[county]
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
        try:
            resp = requests.head(f"{self.es_host}/{self.index}", timeout=10, verify=False)
            if resp.status_code == 200:
                return
        except Exception:
            pass
        mapping = {
            "mappings": {
                "properties": {
                    "run_id":              {"type": "keyword"},
                    "status":              {"type": "keyword"},
                    "current_county":      {"type": "keyword"},
                    "current_page":        {"type": "integer"},
                    "total_pages":         {"type": "integer"},
                    "total_records":       {"type": "integer"},
                    "docs_written":        {"type": "integer"},
                    "percent":             {"type": "float"},
                    "duration_sec":        {"type": "float"},
                    "update_date":         {"type": "keyword"},
                    "last_updated":        {"type": "date", "format": "yyyy-MM-dd HH:mm:ss"},
                    "error":               {"type": "text"},
                    "spot_check_ok":       {"type": "boolean"},
                    "spot_check_details":  {"type": "text"},
                }
            }
        }
        try:
            requests.put(f"{self.es_host}/{self.index}", json=mapping, timeout=10, verify=False)
        except Exception:
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


def _doc_id(breed, code, spec, county, update_date, price="", tax_price=""):
    raw = f"{breed}_{code}_{spec}_{county}_{update_date}_{price}_{tax_price}"
    return hashlib.md5(raw.encode('utf-8')).hexdigest()


def _make_doc(r, county, update_date):
    """构建写入 ES 的 doc，_id = MD5(breed+code+spec+county+update_date)，幂等"""
    breed = r.get('breed', '')
    code = r.get('code', '')
    spec = r.get('spec', '')
    doc_id = _doc_id(breed, code, spec, county, update_date or '', price=r.get('price',''), tax_price=r.get('tax_price',''))
    doc = {
        **r,
        '_id': doc_id,
        'county': county,
        'province': '陕西',
        'city': '西安',
        'update_date': update_date or '',
        'create_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
    }
    return doc


def main():
    start_time = time.time()

    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    import argparse
    parser = argparse.ArgumentParser(description='同步西安材料价格数据')
    parser.add_argument('--config', type=str, default=None)
    parser.add_argument('--force', action='store_true')
    parser.add_argument('--max-pages', type=int, default=2000)
    parser.add_argument('--counties', type=str, default=None)
    parser.add_argument('--resume-from', type=str, default=None)
    parser.add_argument('--reset', action='store_true')
    parser.add_argument('--no-log', action='store_true')
    parser.add_argument('--no-spot-check', action='store_true')
    args = parser.parse_args()

    script_dir = __file__.rsplit('/', 1)[0]
    config_path = args.config or f"{script_dir}/../config.yml"
    config = load_config(config_path)

    es_host = config['es']['host']
    es_index = config['es']['index']
    log_index = config['es'].get('sync_log_index', 'ods_material_xian_price_sync_log')
    counties = config['site']['counties']
    last_update_date = config['sync'].get('last_update_date', '')

    logger = ProgressLogger(es_host, progress_index=config['es'].get('progress_index')) if not args.no_log else None

    # ── 增量抽检（可跳过）──
    if not args.no_spot_check:
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
            progress.clear(county)
        print("[i] 已重置所有进度")


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

    for county in counties:
        if interrupted:
            if logger:
                logger.state["status"] = logger.STATUS_INTERRUPTED
                logger.state["current_page"] = start_page
                logger.state["docs_written"] = county_docs
                logger._upsert()
            print("\n[!] 已中断，进度已保存")
            break

        start_page = progress.get_page(county)
        if start_page > 1 and not args.reset:
            print(f"[i] 检测到 {county} 上次同步到第 {start_page} 页，自动续传")
        else:
            start_page = 1
            progress.clear(county)

        county_start_time = time.time()
        print(f"\n[▼] 区县: {county}")
        session = SiteSession(max_retries=5, timeout=60)

        html = session.fetch(county, page=start_page)
        if not html:
            msg = f"第{start_page}页抓取失败"
            print(f"  [!] {msg}")
            if logger:
                logger.state["status"] = logger.STATUS_ERROR; logger.state["error"] = msg; logger._upsert()
            continue

        page_county = parse_county(html)
        update_date = parse_page_date(html)
        total_records = parse_total_records(html)
        rows = parse_table_rows(html)
        total_pages = (total_records + 9) // 10 if total_records > 0 else 0

        marker = f"@{start_page}起始" if start_page > 1 else ""
        print(f"  [{page_county}{marker}] | {update_date} | 共{total_records}条 | 约{total_pages}页")

        if logger:
            logger.state["current_county"] = county
            logger.state["status"] = logger.STATUS_RUNNING
            logger.state["current_page"] = start_page
            logger.state["total_pages"] = total_pages
            logger.state["total_records"] = total_records
            logger.state["docs_written"] = 0
            logger.state["percent"] = 0.0
            logger.state["update_date"] = update_date or ""
            logger.state["error"] = ""
            logger._upsert()

        _print_page_line(start_page, total_pages, len(rows), 0, dry_run)

        county_docs = 0

        if rows:
            page_docs = _write_docs(es_host, es_index, rows, county, update_date, dry_run)
            _print_page_line(start_page, total_pages, len(rows), page_docs, dry_run)
            county_docs += page_docs
            total_docs += page_docs

        if update_date and (new_update_date is None or update_date > new_update_date):
            new_update_date = update_date

        if total_pages == 0 or total_pages > args.max_pages:
            total_pages = args.max_pages

        if not dry_run:
            progress.save(county, start_page, update_date, total_records, county_docs)
            if logger:
                elapsed = time.time() - start_time
                logger.page_progress(start_page, total_pages, county_docs, total_records, update_date or '', elapsed)

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

            html = session.fetch(county, page)
            if not html:
                msg = f"页 {page} 抓取失败"
                print(f"\n  [!] {msg}")
                if logger:
                    logger.state["status"] = logger.STATUS_ERROR; logger.state["error"] = msg; logger._upsert()
                break

            update_date = parse_page_date(html)
            rows = parse_table_rows(html)

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

            if update_date and effective_last_date and not force and update_date < effective_last_date:
                print(f"\n  [✓] 停止：{update_date} < {effective_last_date}")
                break

            page_docs = _write_docs(es_host, es_index, rows, county, update_date, dry_run)
            _print_page_line(page, total_pages, len(rows), page_docs, dry_run)
            county_docs += page_docs
            total_docs += page_docs

            if update_date and (new_update_date is None or update_date > new_update_date):
                new_update_date = update_date

            progress.save(county, page, update_date, total_records, county_docs)
            if logger:
                elapsed = time.time() - start_time
                logger.page_progress(page, total_pages, county_docs, total_records, update_date or '', elapsed)

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
            print(f"\n  [{county}] 中断于页 ~{page}，进度已保存")
        else:
            progress.clear(county)
            duration = time.time() - county_start_time
            print(f"\n  [{county}] ✓ 完成 (写入 {county_docs} 条, {duration:.0f}s)")
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


def _write_docs(es_host, es_index, rows, county, update_date, dry_run):
    if not rows:
        return 0
    docs = [_make_doc(r, county, update_date) for r in rows]

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


if __name__ == '__main__':
    main()
