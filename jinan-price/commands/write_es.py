"""jinan-price/commands/write_es.py

构造 ODS 文档 + 批量写入 ES（含 period_start/period_end/period_days 推导）。

v0.1 (2026-07-03) ：
  - 模块化，参考 chongqing-price 模式
  - 必填字段：period_start / period_end / period_days（道友硬要求，2026-07-03）
  - 区间价：直接读源站 infoPriceMin / infoPriceMax（API 字段，非字符串区间）
  - 复用 gov_price_etl.parse_price 兜底（防御性，正常不会触发）

公开 API：
    make_doc(record, catalogue_id, catalogue_name, period, period_id) -> dict
    bulk_write(es_host, es_index, docs) -> int   # 成功写入条数
    write_progress(es_host, progress_index, run_id, unit, docs_count, status, duration_sec)
"""
from __future__ import annotations

import calendar
import hashlib
import json
import re
import time
import urllib3
from datetime import datetime
from typing import Optional

import requests

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


# ── 期间推导：'2026年05月材料价格信息' → period_start/end/days ──

_RE_PERIOD = re.compile(r'(\d{4})年(\d{1,2})月')


def _parse_period(period: str) -> tuple[str, str, int]:
    """从 period 字符串提取 (period_date, period_end, last_day)。

    Args:
        period: '2026年05月材料价格信息' / '2026年05月' / '2026-05' 等

    Returns:
        (period_start='2026-05-01', period_end='2026-05-31', period_days=31)
    """
    m = _RE_PERIOD.search(period)
    if not m:
        return ('1970-01-01', '1970-01-31', 31)
    y, mo = int(m.group(1)), int(m.group(2))
    if not (1 <= mo <= 12):
        return ('1970-01-01', '1970-01-31', 31)
    last_day = calendar.monthrange(y, mo)[1]
    return (
        f"{y:04d}-{mo:02d}-01",
        f"{y:04d}-{mo:02d}-{last_day:02d}",
        last_day,
    )


# ── 价格解析（API 已给 min/max，但走共享解析保证一致性）────────

def _parse_price(record: dict) -> tuple[float, float, float, float, bool]:
    """从源站 record 提取价格四元组。

    优先用 API 字段 infoPriceMin / infoPriceMax；
    缺则用 gov_price_etl.parse_price 兜底（极少触发，预留保护）。

    Returns:
        (price, tax_price, price_min, price_max, is_range)
        infoPrice = 含税价（site 字段语义）；tax_price 与 price 同步
    """
    from gov_price_etl.parse_price import parse_interval_price  # noqa: F401

    info_price = float(record.get('infoPrice') or 0.0)
    info_min = record.get('infoPriceMin')
    info_max = record.get('infoPriceMax')

    if info_min is not None and info_max is not None:
        mn, mx = float(info_min), float(info_max)
        is_range = (mn != mx)
        return (info_price, info_price, mn, mx, is_range)

    # 兜底（防御性，源站当前不会给字符串区间价）
    raw = record.get('infoPriceString') or ''
    mid, mn, mx, is_range, _raw, _notes = parse_interval_price(raw)
    return (mid or info_price, mid or info_price, mn, mx, is_range)


# ── 文档构造 ──────────────────────────────────────────────

def _doc_id_key(breed, spec, period, period_id, catalogue_id, price) -> str:
    raw = f"{breed}_{spec}_{period}_{period_id}_{catalogue_id}_{price}"
    return hashlib.md5(raw.encode('utf-8')).hexdigest()


def make_doc(
    record: dict,
    catalogue_id: str,
    catalogue_name: str,
    period: str,
    period_id: str,
) -> dict:
    """从一条 record 构造 ODS 文档（v0.1, 2026-07-03）。

    必含字段：breed / spec / unit / price / tax_price / period /
              period_start / period_end / period_days / province / city /
              catalogue / catalogue_name / code / update_date / publish_time
    """
    product_name = (record.get('productName') or '').strip()
    features = (record.get('features') or '').strip()
    code = record.get('code') or ''
    unit = record.get('unit') or ''
    publish_time = record.get('publishTime') or ''

    # 价格
    price, tax_price, price_min, price_max, is_range = _parse_price(record)

    # 期间
    period_start, period_end, period_days = _parse_period(period)

    # update_date：优先 publishTime；缺则回退到 period_start
    update_date = publish_time[:10] if len(publish_time) >= 10 else period_start

    doc_id = _doc_id_key(product_name, features, period, period_id, catalogue_id, price)

    return {
        '_id': doc_id,
        'breed': product_name,
        'spec': features,
        'unit': unit,
        'price': price,
        'tax_price': tax_price,
        'price_min': price_min,
        'price_max': price_max,
        'is_range': is_range,
        'is_tax': '1',  # infoPrice 字段语义为含税价
        'period': period,
        'period_start': period_start,
        'period_end': period_end,
        'period_days': period_days,
        'province': '山东',
        'city': '济南',
        'county': '济南',
        'catalogue': catalogue_id,
        'catalogue_name': catalogue_name,
        'code': code,
        'update_date': update_date,
        'publish_time': publish_time,
        'create_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'source': 'jinan',
        'source_index': 'ods_material_jinan_price',
        'run_id': '',  # 写入时由 bulk_write 填充
    }


# ── 批量写入 ES ──────────────────────────────────────────

def bulk_write(
    es_host: str,
    es_index: str,
    docs: list[dict],
    run_id: str = '',
    dry_run: bool = False,
) -> int:
    """bulk 写入 ES，返回成功条数。

    Args:
        docs: make_doc 生成的文档列表（每条带 _id）
        run_id: 本次运行 ID，注入到每条 doc
        dry_run: True 时不实际写入
    """
    if not docs:
        return 0
    if dry_run:
        return len(docs)

    bulk_body = ''
    for doc in docs:
        doc_id = doc.pop('_id')
        if run_id:
            doc['run_id'] = run_id
        bulk_body += json.dumps(
            {"index": {"_index": es_index, "_id": doc_id}},
            ensure_ascii=False,
        ) + '\n'
        bulk_body += json.dumps(doc, ensure_ascii=False) + '\n'

    try:
        resp = requests.post(
            f"{es_host}/_bulk",
            data=bulk_body.encode('utf-8'),
            headers={"Content-Type": "application/x-ndjson"},
            timeout=60,
            verify=False,
        )
        if resp.status_code in (200, 201):
            items = resp.json().get('items', [])
            return sum(
                1 for it in items
                if it.get('index', {}).get('result') in ('created', 'updated')
            )
        else:
            print(f"  [!] bulk 失败 status={resp.status_code}: {resp.text[:200]}")
    except Exception as e:
        print(f"  [!] bulk 异常: {e}")
    return 0


# ── 进度上报（ES 端）─────────────────────────────────────

def write_progress(
    es_host: str,
    progress_index: str,
    run_id: str,
    period: str,
    period_id: str,
    catalogue_id: str,
    catalogue_name: str,
    page: int,
    total_pages: int,
    docs_count: int,
    status: str,
    duration_sec: float = 0.0,
    error: str = '',
) -> None:
    """写一条 progress 文档到 ES。_id 规则：run_id__period_id__catalogue_id"""
    period_start, period_end, period_days = _parse_period(period)
    doc_id = f"{run_id}__{period_id}__{catalogue_id}"
    body = {
        'run_id': run_id,
        'period': period,
        'period_id': period_id,
        'period_start': period_start,
        'period_end': period_end,
        'period_days': period_days,
        'catalogue': catalogue_id,
        'catalogue_name': catalogue_name,
        'current_page': page,
        'total_pages': total_pages,
        'docs_written': docs_count,
        'percent': round(page / total_pages * 100, 2) if total_pages else 0,
        'duration_sec': round(duration_sec, 2),
        'status': status,
        'error': error,
        'source': 'jinan',
        'city': '济南',
        'province': '山东',
        'last_updated': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
    }
    try:
        requests.put(
            f"{es_host}/{progress_index}/_doc/{doc_id}",
            json=body,
            timeout=15,
            verify=False,
        )
    except Exception:
        pass
