"""海南 - 增量检测：对比 ES 最新 update_date vs 源站最新发布日期

v0.8.1（2026-07-03）：在 main() 末尾写 /tmp/gov-check-status/hainan.json，
供 dashboard `/sync` 顶部「定时检查状态」chip 复用（chongqing v0.8 已
有同款机制，本文件对齐）。
"""
import json
import os
import re
import sys
import time

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

from utils import load_config, get_es_client
from parser import fetch_all_periods

# ─── check_status 落盘（dashboard /sync 复用） ────────────────────────
CHECK_STATUS_DIR = "/tmp/gov-check-status"
CHECK_STATUS_FILE = os.path.join(CHECK_STATUS_DIR, "hainan.json")


def _parse_year_month_from_title(title: str) -> tuple[str, str]:
    """从源站标题解析 (year, month)。

    例：
      '2026年5月海南省建设工程主要材料…参考价' → ('2026', '5月')
      '2026年5月…'                              → ('2026', '5月')

    Returns:
        (year_str, month_str) 解析失败时返回 ('', '')。
    """
    if not title:
        return "", ""
    m = re.search(r"(\d{4})\s*年\s*(\d{1,2})\s*月", title)
    if not m:
        return "", ""
    return m.group(1), f"{int(m.group(2))}月"


def _write_check_status(
    site_title, site_publish_date, site_year, site_month,
    es_update_date, status, message,
):
    """写检查状态到 /tmp/gov-check-status/hainan.json

    字段格式与 chongqing 一致（API /stats/check-status 透传给前端）：
      status: 'ok' | 'update' | 'error' | 'pending'
      has_update: True / False
    """
    status_map = {
        "ok":         ("ok", False),
        "new_data":   ("update", True),
        "no_es_data": ("update", True),
        "no_site":    ("error", False),
        "unknown":    ("error", False),
    }
    chip_status, has_update = status_map.get(status, ("error", False))

    doc = {
        "city": "hainan",
        "label": "海南",
        "status": chip_status,
        "output": message or "",
        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
        "has_update": has_update,
        "site_latest_title": site_title or "",
        "site_latest_period": f"{site_year}年{site_month}" if site_year and site_month else "",
        "site_latest_year": site_year or "",
        "site_latest_month": site_month or "",
        "site_latest_publish_date": site_publish_date or "",
        "es_latest_period": "",
        "es_latest_update_date": es_update_date or "",
    }

    os.makedirs(CHECK_STATUS_DIR, exist_ok=True)
    with open(CHECK_STATUS_FILE, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=2)
    print(f"[海南] check_status → {CHECK_STATUS_FILE}")


def main():
    cfg = load_config()
    es = get_es_client(cfg['es']['host'])
    ods_index = cfg['es']['ods_index']

    # 1. 获取 ES 最新 update_date
    es_latest = ''
    try:
        r = es.search(
            index=ods_index, size=1,
            sort=[{'update_date': 'desc'}],
            _source=['update_date'],
        )
        hits = r['hits']['hits']
        if hits:
            es_latest = hits[0]['_source'].get('update_date', '') or ''
    except Exception as e:
        print(f'[海南] ES 查询失败: {e}')

    # 2. 获取源站最新发布
    site_latest = ''
    site_title = ''
    try:
        items = fetch_all_periods(cfg)
        if items:
            items_sorted = sorted(
                items, key=lambda x: x.get('publish_date', ''), reverse=True,
            )
            site_latest = items_sorted[0].get('publish_date', '')
            site_title = items_sorted[0].get('title', '')
    except Exception as e:
        print(f'[海南] 源站查询失败: {e}')

    print(f'[海南] 源站最新: {site_title} ({site_latest})')
    print(f'[海南] ES 最新:   {es_latest or "无"}')

    # 3. 对比
    site_year, site_month = _parse_year_month_from_title(site_title)
    status = "unknown"
    message = ""
    if es_latest and site_latest:
        if site_latest > str(es_latest)[:10]:
            print(f'[海南] 🔔 有更新！{site_title}')
            status = "new_data"
            message = f"源站 {site_latest} > ES {es_latest}，需同步"
        else:
            print(f'[海南] ✅ 无新数据')
            status = "ok"
            message = f"无新数据（源站 == ES = {site_latest}）"
    elif site_latest:
        print(f'[海南] 🔔 源站有数据，ES 无记录，需首次同步')
        status = "no_es_data"
        message = f"ES 无记录，源站 {site_latest} 待首次同步"
    else:
        print(f'[海南] ⚠️ 无法获取源站数据')
        status = "no_site"
        message = "无法获取源站数据"

    # 4. 写 dashboard status（顶部「定时检查状态」chip 复用）
    _write_check_status(
        site_title, site_latest, site_year, site_month,
        es_latest, status, message,
    )


if __name__ == '__main__':
    main()
