"""济南工程造价材料信息 - 同步主程序"""
import sys, os, re, hashlib, json, time, signal, argparse
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import warnings
warnings.filterwarnings('ignore')

import requests
from datetime import datetime
from commands.utils import (
    JinAnSiteSession, ensure_index, ensure_progress_index, load_config,
    sync_catalogue_to_es
)

interrupted = False


def _signal_handler(signum, frame):
    global interrupted
    interrupted = True
    print("\n[!] 接收到中断信号，正在保存进度...")


def _print_page(page, total_pages, docs_written, dry_run):
    pct = page / total_pages * 100 if total_pages else 0
    done = "█" * int(pct / 5) + "░" * (20 - int(pct / 5))
    status = f"✓{docs_written}" if not dry_run else f"预览{docs_written}"
    sys.stdout.write(f"\r  [页 {page}/{total_pages}] {status} |{done}| {pct:.0f}%   ")
    sys.stdout.flush()


class ProgressLogger:
    STATUS_RUNNING = 'running'
    STATUS_COMPLETED = 'completed'
    STATUS_INTERRUPTED = 'interrupted'
    STATUS_ERROR = 'error'

    def __init__(self, es_host, index_name):
        self.es_host = es_host
        self.index = index_name
        self.run_id = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
        self.state = {
            "run_id": self.run_id, "status": self.STATUS_RUNNING,
            "catalogue": "", "catalogue_name": "", "period": "",
            "current_catalogue": "", "current_page": 0, "total_pages": 0, "total_records": 0,
            "docs_written": 0, "percent": 0.0, "duration_sec": 0.0,
            "last_updated": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            "error": "",
        }
        ensure_progress_index(es_host, index_name)
        self._upsert()

    def _upsert(self):
        try:
            doc = dict(self.state)
            doc_id = f"{self.run_id}_{doc.get('catalogue', 'unknown')}"
            requests.post(
                f"{self.es_host}/{self.index}/_doc/{doc_id}",
                json=doc, timeout=15, verify=False)
        except Exception:
            pass

    def set_status(self, status):
        self.state["status"] = status
        self._upsert()

    def set_catalogue(self, cat_id, cat_name, period):
        self.state["catalogue"] = cat_id
        self.state["catalogue_name"] = cat_name
        self.state["period"] = period
        self.state["status"] = self.STATUS_RUNNING
        self.state["current_catalogue"] = cat_id
        self.state["current_page"] = 0
        self._upsert()

    def page_progress(self, page, total_pages, docs_written, elapsed):
        self.state.update(
            current_page=page, total_pages=total_pages,
            docs_written=docs_written,
            percent=round(page / total_pages * 100, 2) if total_pages else 0,
            duration_sec=round(elapsed, 2),
            last_updated=datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
        self._upsert()

    def finish_catalogue(self, page, total, docs):
        self.state["status"] = self.STATUS_COMPLETED
        self.state["current_page"] = page
        self.state["total_pages"] = total
        self.state["docs_written"] = docs
        self.state["percent"] = 100.0
        self.state["current_catalogue"] = ""
        self._upsert()


class ProgressStore:
    """本地进度: catalogue_id + period_id + page"""
    def __init__(self):
        self.path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                  '.jinan_sync_progress.json')
        self.data = self._load()

    def _load(self):
        if os.path.exists(self.path):
            try:
                with open(self.path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception:
                pass
        return {}

    def save(self, catalogue_id, period_id, period_name, page, total_records, docs_written):
        self.data['catalogue_id'] = catalogue_id
        self.data['period_id'] = period_id
        self.data['period_name'] = period_name
        self.data['page'] = page
        self.data['total_records'] = total_records
        self.data['docs_written'] = docs_written
        self.data['saved_at'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        try:
            with open(self.path, 'w', encoding='utf-8') as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def get(self):
        return (
            self.data.get('catalogue_id', ''),
            self.data.get('period_id', ''),
            self.data.get('period_name', ''),
            self.data.get('page', 1),
            self.data.get('total_records', 0),
            self.data.get('docs_written', 0),
        )

    def clear(self):
        self.data = {}
        try:
            with open(self.path, 'w', encoding='utf-8') as f:
                json.dump({}, f)
        except Exception:
            pass


def _doc_id_key(breed, spec, period, period_id, catalogue_id, price):
    raw = f"{breed}_{spec}_{period}_{period_id}_{catalogue_id}_{price}"
    return hashlib.md5(raw.encode('utf-8')).hexdigest()


def _make_doc(record, catalogue_id, catalogue_name, period, period_id):
    product_name = record.get('productName', '')
    features = record.get('features', '') or ''
    spec = features.strip()
    price = record.get('infoPrice', 0.0) or 0.0
    unit = record.get('unit', '')
    code = record.get('code', '')
    publish_time = record.get('publishTime', '') or ''

    update_date = ''
    if len(publish_time) >= 10:
        update_date = publish_time[:10]
    elif period:
        m = re.search(r'(\d{4})年(\d{1,2})月', period)
        if m:
            update_date = f"{m.group(1)}-{int(m.group(2)):02d}-01"

    doc_id = _doc_id_key(product_name, spec, period, period_id, catalogue_id, str(price))
    return {
        '_id': doc_id,
        'breed': product_name,
        'spec': spec,
        'unit': unit,
        'price': price,
        'tax_price': price,  # 含税价格
        'is_tax': '含税',
        'period': period,
        'period_id': period_id,
        'province': '山东',
        'city': '济南',
        'county': '济南',
        'catalogue': catalogue_id,
        'catalogue_name': catalogue_name,
        'code': code,
        'update_date': update_date,
        'publish_time': publish_time,
        'create_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
    }


def _write_docs(es_host, es_index, docs, dry_run):
    if not docs:
        return 0
    if dry_run:
        return len(docs)
    bulk = ''
    for doc in docs:
        doc_id = doc.pop('_id')
        bulk += json.dumps({"index": {"_index": es_index, "_id": doc_id}}, ensure_ascii=False) + '\n'
        bulk += json.dumps(doc, ensure_ascii=False) + '\n'
    try:
        resp = requests.post(f"{es_host}/_bulk",
            data=bulk.encode('utf-8'),
            headers={"Content-Type": "application/x-ndjson"},
            timeout=30, verify=False)
        if resp.status_code in (200, 201):
            items = resp.json().get('items', [])
            return sum(1 for it in items if it.get('index', {}).get('result') in ('created', 'updated'))
    except Exception:
        pass
    return 0


def main():
    global interrupted
    parser = argparse.ArgumentParser(description='济南工程造价信息同步')
    parser.add_argument('--reset', action='store_true', help='重置进度，重新开始')
    parser.add_argument('--dry-run', action='store_true', help='预览模式，不写入 ES')
    parser.add_argument('--force', action='store_true', help='强制全量同步')
    parser.add_argument('--period-id', default='', help='指定 periodId')
    parser.add_argument('--size', type=int, default=100, help='每页大小')
    args = parser.parse_args()

    script_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    config = load_config(os.path.join(script_dir, 'config.yml'))
    es_host = config.get('es', {}).get('host', 'http://localhost:59200')
    es_index = config.get('es', {}).get('index', 'ods_material_jinan_price')
    progress_index = config.get('es', {}).get('progress_index', 'ods_material_jinan_price_sync_progress')
    log_index = config.get('es', {}).get('sync_log_index', 'ods_material_jinan_price_sync_log')
    size_per_page = args.size or config.get('sync', {}).get('size_per_page', 100)
    data_type = config.get('site', {}).get('data_type', '2')

    signal.signal(signal.SIGINT, _signal_handler)

    if not args.dry_run:
        ensure_index(es_host, es_index)

    print("[i] 初始化济南网站 Session...")
    session = JinAnSiteSession()

    # 获取目标周期
    if args.period_id:
        period_id = args.period_id
        period_name = session._get_period_name(period_id)
        if not period_name:
            print(f"[!] periodId {period_id} 不合法")
            return
    else:
        period_name, period_id = session.get_last_period()
        if not period_name:
            print("[!] 无法获取最新周期")
            return

    print(f"[i] 目标周期: {period_name} (id={period_id})")

    # 先同步分类目录树
    cat_index = config.get('es', {}).get('catalogue_index', f'{es_index}_catalogue')
    print("[i] 同步分类目录树...")
    cat_count = sync_catalogue_to_es(session, es_host, cat_index, period_name, period_id, data_type, args.dry_run)
    print(f"[i] 分类目录写入 {cat_count} 条")

    # 增量检测
    if not args.force and not args.reset:
        cfg = load_config(os.path.join(script_dir, 'config.yml'))
        last_period_id = cfg.get('sync', {}).get('last_period_id', '') or ''
        if last_period_id == period_id:
            print(f"[—] 上次已同步至 {period_name}，无新数据。加 --force 强制同步")
            return
        else:
            print(f"[i] 增量检测: {last_period_id or '(首次)'} → {period_name}")

    progress = ProgressStore()
    if args.reset:
        print("[i] 重置进度...")
        progress.clear()

    saved_cat_id, saved_period_id, saved_period_name, saved_page, saved_total, saved_docs = progress.get()

    logger = ProgressLogger(es_host, progress_index)
    start_time = time.time()
    total_docs = 0

    # 获取所有分类目录
    print("[i] 获取分类目录...")
    all_cat_ids = session.get_all_catalogue_ids(data_type)
    print(f"[i] 共 {len(all_cat_ids)} 个分类")

    # 跳过已完成的分类（断点续传）
    skip_cats = set()
    if saved_period_id == period_id and saved_cat_id and saved_page > 1 and not args.reset:
        skip_idx = all_cat_ids.index(saved_cat_id) if saved_cat_id in all_cat_ids else -1
        if skip_idx >= 0:
            skip_cats = set(all_cat_ids[:skip_idx])
            print(f"[i] 续传: {saved_cat_id} 第 {saved_page} 页开始")

    for cat_id in all_cat_ids:
        if cat_id in skip_cats:
            continue

        if interrupted:
            if logger:
                logger.set_status(ProgressLogger.STATUS_INTERRUPTED)
            print("\n[!] 已中断，进度已保存")
            break

        # 获取分类名称（递归查找）
        cat_name = session.find_catalogue_name_by_id(cat_id, data_type)

        print(f"\n[▼] {cat_name or cat_id}")

        # 抓取第一页获取总数
        data = session.fetch(period_id, cat_id, page=1, size=size_per_page, data_type=data_type)
        if not data:
            print(f"  [!] 抓取失败")
            continue

        records = data.get('records', [])
        total_records = data.get('total', 0) or len(records)
        total_pages = (total_records + size_per_page - 1) // size_per_page if total_records > 0 else 1
        print(f"  共 {total_records} 条，约 {total_pages} 页")

        logger.set_catalogue(cat_id, cat_name, period_name)

        start_page = saved_page if (saved_period_id == period_id and saved_cat_id == cat_id) else 1

        cat_docs = 0
        for page_num in range(start_page, min(total_pages + 1, 500)):
            if interrupted:
                print(f"\n  [!] 页 {page_num} 中断，已保存进度")
                if logger:
                    logger.set_status(ProgressLogger.STATUS_INTERRUPTED)
                progress.save(cat_id, period_id, period_name, page_num, total_records, cat_docs)
                return

            data = session.fetch(period_id, cat_id, page=page_num, size=size_per_page, data_type=data_type)
            if not data:
                print(f"\n  [!] 页 {page_num} 抓取失败")
                break

            records = data.get('records', [])
            if not records:
                break

            docs = [_make_doc(r, cat_id, cat_name, period_name, period_id) for r in records]
            written = _write_docs(es_host, es_index, docs, args.dry_run)
            _print_page(page_num, total_pages, written, args.dry_run)
            cat_docs += written
            total_docs += written

            if not args.dry_run:
                progress.save(cat_id, period_id, period_name, page_num, total_records, cat_docs)
                elapsed = time.time() - start_time
                logger.page_progress(page_num, total_pages, total_docs, elapsed)

            time.sleep(0.8)

        logger.finish_catalogue(total_pages, total_pages, cat_docs)
        print(f"\n  ✓ {cat_name or cat_id} 完成，共 {cat_docs} 条")
        saved_page = 1  # 下一分类从第1页开始

    if not interrupted:
        logger.state["current_catalogue"] = ""
        logger.set_status(ProgressLogger.STATUS_COMPLETED)
        elapsed = time.time() - start_time
        print(f"\n\n[✓] 全部完成，共写入 {total_docs} 条文档")
        print(f"[i] 耗时: {elapsed:.1f}s")

        # 更新 config.yml
        import yaml
        cfg_path = os.path.join(script_dir, 'config.yml')
        with open(cfg_path) as f:
            cfg = yaml.safe_load(f)
        cfg.setdefault('sync', {})['last_period'] = period_name
        cfg.setdefault('sync', {})['last_period_id'] = period_id
        with open(cfg_path, 'w') as f:
            yaml.dump(cfg, f, allow_unicode=True, default_flow_style=False)
        print(f"[i] 已更新 last_period: {period_name}")


if __name__ == '__main__':
    main()
