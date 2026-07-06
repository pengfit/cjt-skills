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
    es_latest_period: str = "",
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
        "es_latest_period": es_latest_period or "",
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
    # 3a. 取 ES 端最新 period（按归一化 YYYYMM 数字字符串 desc）
    es_latest_period = ""
    es_period_sort = ""
    try:
        r2 = es.search(
            index=ods_index, size=1,
            sort=[{'period': 'desc'}],
            _source=['period'],
        )
        hits2 = r2['hits']['hits']
        if hits2:
            es_latest_period = hits2[0]['_source'].get('period', '') or ''
            m2 = re.match(r'(\d{4})\.(\d{1,2})月', es_latest_period)
            if m2:
                es_period_sort = f"{m2.group(1)}{int(m2.group(2)):02d}"
    except Exception as e:
        print(f'[海南] ES period 查询失败: {e}')

    # 3b. 源站最新 period 归一化为 YYYYMM
    site_period_sort = ""
    if site_year and site_month:
        m1 = re.match(r'(\d{1,2})月', site_month)
        if m1:
            site_period_sort = f"{site_year}{int(m1.group(1)):02d}"

    if es_period_sort and site_period_sort:
        if site_period_sort > es_period_sort:
            # 额外检查：源站最新期是否已在本地进度里标了 skipped_image_pdf
            # （扫描图片 PDF sync 会跳过，留待 OCR），这种情况下不再报 update
            try:
                prog_path = os.path.join(
                    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    ".hainan_sync_progress.json",
                )
                if os.path.exists(prog_path):
                    with open(prog_path, encoding="utf-8") as _f:
                        prog = json.load(_f).get("done", {})
                    # 遍历找源站最新期对应的 detail_url 是否标了 skipped_image_pdf
                    site_norm = f"{site_year}.{int(re.match(r'(\d{1,2})', site_month).group(1))}月" if site_year and site_month else ""
                    for url, info in prog.items():
                        if info.get("status") == "skipped_image_pdf" and site_norm:
                            # 这个 URL 对应的期跟源站最新期是否一致（用 progress 里的 period 字段、或 fallback title 含最新期）
                            prog_period = info.get("period", "")
                            if prog_period == site_norm or (not prog_period and site_year in info.get("error", "") + info.get("detail_url", "")):
                                print(f'[海南] · 跳过（已 OCR 标记）{site_year}年{site_month} 留待 OCR')
                                status = "ok"
                                message = f"已标记 OCR 跳过：源站 {site_year}年{site_month} 留待 OCR"
                                break
            except Exception as _e:
                print(f'[海南] progress 检查跳过: {_e}')

            if status == "unknown":
                print(f'[海南] 🔔 有更新！{site_title} ({site_year}年{site_month})')
                status = "new_data"
                message = f"源站 {site_year}年{site_month} > ES {es_latest_period}，需同步"
        else:
            print(f'[海南] ✅ 无新数据')
            status = "ok"
            message = f"无新数据（源站 {site_year}年{site_month} == ES {es_latest_period}）"
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
        es_latest_period=es_latest_period,
    )


if __name__ == '__main__':
    main()
