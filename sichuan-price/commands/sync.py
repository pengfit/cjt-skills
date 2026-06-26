"""四川工程造价信息 - 同步主程序"""
import sys, os, re
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import warnings
warnings.filterwarnings('ignore')

import hashlib, json, time, signal, argparse
import requests
from datetime import datetime

CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'config.yml')
from commands.utils import (
    SiteSession, parse_page, ensure_index, ensure_progress_index, load_config,
    AREA_CODES, get_all_periods, get_latest_period
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


def _doc_id_key(breed, spec, period, price, tax_price, city, county):
    raw = f"{breed}_{spec}_{period}_{price}_{tax_price}_{city}_{county}"
    return hashlib.md5(raw.encode('utf-8')).hexdigest()


def _make_doc(row, city, county, period, update_date):
    price = row.get('price', 0.0)
    tax_price = round(price * 1.1, 2) if row.get('is_tax') == '不含税' else price
    doc_id = _doc_id_key(
        row.get('breed', ''), row.get('spec', ''),
        period, str(price), str(tax_price),
        city, county
    )
    return {
        '_id': doc_id,
        'breed': row.get('breed', ''),
        'spec': row.get('spec', ''),
        'unit': row.get('unit', ''),
        'price': price,
        'tax_price': tax_price,
        'is_tax': row.get('is_tax', ''),
        'period': period,
        'province': '四川',
        'city': city,
        'county': county,
        'update_date': update_date,
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


# area_name 简称 → 全称（与地图 features / ES 聚合对齐）
AREA_NAME_FULL = {
    '阿坝州': '阿坝藏族羌族自治州',
    '甘孜州': '甘孜藏族自治州',
    '凉山州': '凉山彝族自治州',
}


def _normalize_county_name(county_name: str, city_name: str, mapping: dict) -> str:
    """county 名称归一为地图 features 全称。
    输入可能是简称（"五通"）、主城代表（"成都市区"）、区域描述（"盐边北部"）等。
    """
    import re as _re
    if not county_name:
        return county_name
    # 1. 自身就是 mapping 里的全称
    if county_name in mapping:
        return county_name
    # 2. 特殊情况: county == city (主城「乐山市」=「市中区」)
    if county_name == city_name:
        for k, v in mapping.items():
            if v == city_name and k == '市中区':
                return k
        # fallback: 找最短的区
        districts = [k for k, v in mapping.items() if v == city_name and k.endswith('区')]
        if districts:
            return min(districts, key=len)
    # 3. 「X市区」主城简称（"成都市区" "自贡市区" "攀枝花市区"）→ 取该市第一个中心区
    m = _re.match(r"^(.+)市区$", county_name)
    if m:
        x = m.group(1)
        # 优先取 mapping 里该市的「市中区」「东区」等中心区
        for k, v in mapping.items():
            if v == x + '市' and k in ('市中区', '东区', '锦江区'):
                return k
    # 4. 「X其他乡镇」「X北部/南部」区域描述
    m = _re.match(r"^(.+?)其他乡镇$", county_name)
    if m:
        x = m.group(1)
        for k, v in mapping.items():
            if v == city_name and (k == x + '县' or k == x + '市' or k == x + '区' or k.startswith(x)):
                return k
    m = _re.match(r"^(.+?)(北部|南部|东部|西部)$", county_name)
    if m:
        x = m.group(1)
        for k, v in mapping.items():
            if v == city_name and k.startswith(x):
                return k
    # 5. 去后缀(县/区/市)再 prefix 匹配
    base = _re.sub(r'(县|区|市)$', '', county_name)
    for k, v in mapping.items():
        if v == city_name and (k.startswith(county_name) or (base and k.startswith(base))):
            return k
    # 6. substring 匹配
    for k, v in mapping.items():
        if v == city_name and (county_name in k or base in k):
            return k
    return county_name


def _build_docs(rows, city_headers, period, area_name):
    """每行材料 × 每个城市列 → 1条文档"""
    import os, sys
    _cm_dir = os.path.dirname(os.path.abspath(__file__))
    if _cm_dir not in sys.path:
        sys.path.insert(0, _cm_dir)
    from sichuan_city_mapping import SICHUAN_CITY_MAPPING  # noqa: E402
    docs = []
    update_date = period.replace('年', '-').replace('月', '-01') if period else datetime.now().strftime('%Y-%m-%d')
    # city 字段用全称（与地图 features 对齐）；不修改 area_name 本身，保持 progress / 日志兼容
    city_name = AREA_NAME_FULL.get(area_name, area_name)
    for row in rows:
        if not row.get('breed'):
            continue
        main_price = row.get('price', 0.0)
        cp = row.get('city_prices', [])
        for i, county_raw in enumerate(city_headers):
            # city 字段 = 地市级（如"乐山市"），county 字段 = 区/县全称（如"五通桥区"）
            county_name = _normalize_county_name(county_raw, city_name, SICHUAN_CITY_MAPPING)
            if i < len(cp) and cp[i]:
                try:
                    price = float(re.sub(r'[￥,，元\-\s]', '', cp[i]))
                except Exception:
                    price = main_price
            else:
                price = main_price
            docs.append(_make_doc(row, city_name, county_name, period, update_date))
    return docs


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
            "area": "", "period": "", "current_page": 0, "total_pages": 0,
            "docs_written": 0, "percent": 0.0, "duration_sec": 0.0,
            "last_updated": datetime.now().strftime('%Y-%m-%d %H:%M:%S'), "error": "",
        }
        ensure_progress_index(es_host, index_name)
        self._upsert()

    def _upsert(self):
        """写入当前地区的进度（每个地区一条独立记录）"""
        try:
            doc = dict(self.state)
            doc_id = f"{self.run_id}_{doc.get('area', 'unknown')}"
            requests.post(
                f"{self.es_host}/{self.index}/_doc/{doc_id}",
                json=doc, timeout=15, verify=False)
        except Exception:
            pass

    def set_status(self, status):
        self.state["status"] = status
        self._upsert()

    def page_progress(self, page, total, docs, elapsed):
        self.state.update(
            current_page=page, total_pages=total, docs_written=docs,
            percent=round(page / total * 100, 2) if total else 0,
            duration_sec=round(elapsed, 2),
            last_updated=datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
        # 每页更新一次当前地区记录
        self._upsert()

    def set_area_period(self, area, period):
        # 上一地区状态写入（保持 completed/running 不变，仅切换 area）
        self.state["area"] = area
        self.state["period"] = period
        self._upsert()
    
    def finish_area(self, page, total, docs):
        """地区完成时更新状态为 completed"""
        self.state["status"] = self.STATUS_COMPLETED
        self.state["current_page"] = page
        self.state["total_pages"] = total
        self.state["docs_written"] = docs
        self.state["percent"] = 100.0
        self._upsert()


class ProgressStore:
    """本地进度: area + period + page"""
    def __init__(self):
        self.path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                  '.sichuan_sync_progress.json')
        self.data = self._load()
    def _load(self):
        if os.path.exists(self.path):
            try:
                with open(self.path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception:
                pass
        return {}
    def save(self, area, period, page):
        self.data['area'] = area; self.data['period'] = period; self.data['page'] = page
        with open(self.path, 'w', encoding='utf-8') as f:
            json.dump(self.data, f, ensure_ascii=False)
    def get(self):
        return self.data.get('area', ''), self.data.get('period', ''), self.data.get('page', 1)
    def clear(self):
        self.data = {}
        with open(self.path, 'w', encoding='utf-8') as f:
            json.dump({}, f)


def main():
    global interrupted
    parser = argparse.ArgumentParser(description='四川工程造价信息同步')
    parser.add_argument('--reset', action='store_true', help='重置进度，重新开始')
    parser.add_argument('--dry-run', action='store_true', help='预览模式，不写入 ES')
    parser.add_argument('--force', action='store_true', help='强制全量同步')
    parser.add_argument('--period', default='', help='指定周期（如 2026年03月），默认自动获取最新）')
    parser.add_argument('--max-pages', type=int, default=2000, help='最大页数')
    parser.add_argument('--no-check', action='store_true', help='跳过增量检测，直接同步')
    args = parser.parse_args()

    script_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    config = load_config(os.path.join(script_dir, 'config.yml'))
    es_host = config.get('es', {}).get('host', 'http://localhost:59200')
    es_index = config.get('es', {}).get('index', 'ods_material_sichuan_price')
    progress_index = config.get('es', {}).get('progress_index', 'ods_material_sichuan_price_sync_progress')

    signal.signal(signal.SIGINT, _signal_handler)

    if not args.dry_run:
        ensure_index(es_host, es_index)

    # 解析目标周期
    if args.period:
        periods = get_all_periods()
        period_map = {p['PeriodName']: p['Guid'] for p in periods}
        period_guid = period_map.get(args.period, '')
        if not period_guid:
            print(f"[!] 未找到周期 '{args.period}'，自动获取最新周期")
            period_name, period_guid = get_latest_period()
        else:
            period_name = args.period
    else:
        period_name, period_guid = get_latest_period()

    print(f"[i] 目标周期: {period_name} (Guid={period_guid})")

    # 增量检测（当 args.no_check 为 False 时）
    if not args.no_check:
        cfg = load_config(CONFIG_PATH)
        last_period = cfg.get('sync', {}).get('last_period', '') or ''
        if last_period == period_name and not args.force:
            print(f"[—] 上次已同步至 {period_name}，无新数据。如需强制同步，加 --force")
            print(f"    检查新周期请运行: ./run.sh check")
            return
        elif last_period and last_period > period_name:
            print(f"[!] config 中记录的周期 {last_period} 晚于目标周期 {period_name}")
            return
        else:
            print(f"[i] 增量检测通过: {last_period or '(首次)'} → {period_name}")

    progress = ProgressStore()
    if args.reset:
        print("[i] 重置进度...")
        progress.clear()

    saved_area, saved_period, saved_page = progress.get()

    logger = ProgressLogger(es_host, progress_index)
    session = SiteSession()
    start_time = time.time()
    total_docs = 0

    # 跳过的已完成地区（用于断点续传）
    skip_areas = set()
    if saved_period == period_name and saved_area and saved_page > 1 and not args.reset:
        skip_areas = {a for a in AREA_CODES
                      if list(AREA_CODES.keys()).index(a) < list(AREA_CODES.keys()).index(saved_area)}
        print(f"[i] 续传：{saved_area} 第 {saved_page} 页开始")

    for area_code in sorted(AREA_CODES.keys(),
                            key=lambda x: (x in skip_areas, list(AREA_CODES.keys()).index(x))):
        if area_code in skip_areas:
            continue
        area_name = AREA_CODES[area_code]
        print(f"\n[▼] {area_name} ({area_code})")

        # 获取第一页，确定总页数
        html, _, period_str = session.fetch(area_code, period_guid, 1)
        if not html:
            print(f"  [!] 抓取失败")
            continue
        _, _, total_records, page_size, _ = parse_page(html)
        total_pages = (total_records + page_size - 1) // page_size if total_records > 0 else 1
        print(f"  共 {total_records} 条，约 {total_pages} 页")
        logger.set_area_period(area_name, period_str)

        start_page = saved_page if (saved_area == area_code and saved_period == period_name) else 1

        page_docs = 0
        for page in range(start_page, min(total_pages + 1, args.max_pages + 1)):
            if interrupted:
                print(f"\n  [!] 页 {page} 中断，已保存进度")
                logger.set_status(ProgressLogger.STATUS_INTERRUPTED)
                progress.save(area_code, period_name, page)
                return

            html, _, period_str = session.fetch(area_code, period_guid, page)
            if not html:
                print(f"\n  [!] 页 {page} 抓取失败")
                break

            city_headers, rows, _, _, _ = parse_page(html)
            docs = _build_docs(rows, city_headers, period_str, area_name)
            written = _write_docs(es_host, es_index, docs, args.dry_run)
            _print_page(page, total_pages, written, args.dry_run)
            page_docs += written
            total_docs += written

            if not args.dry_run:
                progress.save(area_code, period_name, page)
                elapsed = time.time() - start_time
                logger.page_progress(page, total_pages, total_docs, elapsed)

            time.sleep(0.8)

        saved_page = 1
        # 写入该地区完成状态
        logger.finish_area(total_pages, total_pages, page_docs)
        print(f"\n  ✓ {area_name} 完成，共 {page_docs} 条")

    if not interrupted:
        logger.set_status(ProgressLogger.STATUS_COMPLETED)
        elapsed = time.time() - start_time
        print(f"\n\n[✓] 全部完成，共写入 {total_docs} 条文档")
        print(f"[i] 耗时: {elapsed:.1f}s")

        # 更新 config.yml 中的 last_period
        import yaml
        cfg_path = CONFIG_PATH
        with open(cfg_path) as f:
            cfg = yaml.safe_load(f)
        cfg.setdefault('sync', {})['last_period'] = period_name
        with open(cfg_path, 'w') as f:
            yaml.dump(cfg, f, allow_unicode=True, default_flow_style=False)
        print(f"[i] 已更新 last_period: {period_name}")


if __name__ == '__main__':
    main()