#!/usr/bin/env python3
"""build_norm_index.py — Normalizer ETL worker

职责：
- 读 dws_{city}_price 索引
- 调 normalize_batch() 批量标准化
- 写 norm_{city}_price 索引（NormalizationLayer 自己拥有）

用法：
    # 单城全量重建
    python3 -m cli.build_norm_index --city xian

    # 多城全量重建
    python3 -m cli.build_norm_index --cities xian,hainan,chongqing

    # 所有 DWS 城市
    python3 -m cli.build_norm_index --all-cities

    # 增量：只重建某 period_start 之后的数据
    python3 -m cli.build_norm_index --city xian --since 2026-06-01

    # 干跑（不写，只统计会写多少条）
    python3 -m cli.build_norm_index --city xian --dry-run

依赖：elasticsearch Python client（>=7.x）
"""

from __future__ import annotations
import sys
import os
import json
import time
import argparse
from pathlib import Path
from datetime import datetime
from typing import Optional

_HERE = Path(__file__).resolve().parent
_PKG = _HERE.parent
if str(_PKG) not in sys.path:
    sys.path.insert(0, str(_PKG))

from gov_price_normalization.pipeline import normalize_batch  # noqa: E402
from gov_price_normalization.utils import data_loader  # noqa: E402
from gov_price_normalization.utils.errors import NormalizationError  # noqa: E402

# ES 配置（与 dashboard 一致；Phase D 可统一到 .env）
ES_HOST = os.environ.get("ES_HOST", "http://localhost:59200")
ES_AUTH = os.environ.get("ES_AUTH")  # 可选 "user:pass"

try:
    from elasticsearch import Elasticsearch
    from elasticsearch.helpers import scan, bulk
except ImportError:
    print("ERROR: 需要 elasticsearch 包。安装：pip install elasticsearch>=7", file=sys.stderr)
    sys.exit(1)


def _es():
    if ES_AUTH:
        return Elasticsearch(ES_HOST, basic_auth=tuple(ES_AUTH.split(":")), request_timeout=60)
    return Elasticsearch(ES_HOST, request_timeout=60)


def _dws_index(city: str) -> str:
    return f"dws_{city}_price"


def _norm_index(city: str) -> str:
    return f"norm_{city}_price"


def _ensure_norm_index(es, city: str) -> bool:
    """如果 norm_{city}_price 不存在则创建（按 data/norm_index_settings.json 模板）。"""
    idx = _norm_index(city)
    if es.indices.exists(index=idx):
        return False
    settings = data_loader.load_json("norm_index_settings.json")
    # ES 不接受顶层 _meta（去掉）；其余原样
    body = {
        "settings": settings["settings"],
        "mappings": settings["mappings"],
    }
    es.indices.create(index=idx, body=body)
    print(f"[create] {idx}")
    return True


def _scan_dws(es, city: str, since: Optional[str] = None, size: int = 1000):
    """扫描 dws_{city}_price，可选按 period_start 过滤。"""
    idx = _dws_index(city)
    query: dict = {}
    if since:
        query = {"range": {"period_start": {"gte": since}}}
    kwargs: dict = {"index": idx, "size": size, "preserve_order": True, "request_timeout": 120}
    if query:
        kwargs["query"] = query
    return scan(es, **kwargs)


def _normalize_doc(dws_doc: dict, city: str) -> dict:
    """包装 normalize_doc：把标准化结果 + 原 DWS doc 合并成 NORM doc。"""
    src = dws_doc.get("_source", {})
    # 调 pipeline（不带 l3_code，Phase A 暂不算 price_norm 的归一；unit_norm + period_norm 会算）
    normed = normalize_batch([src], city, l3_code=None)[0]
    # 把 _id 保留下来作 _dws_id 追溯
    normed["_dws_id"] = dws_doc.get("_id")
    # 加 build 元信息
    normed.setdefault("_norm", {})
    normed["_norm"]["built_at"] = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    # 顶层冗余字段（便于 dashboard 直接 filter）
    normed["canonical_period"] = normed.get("canonical_period")
    normed["canonical_unit"] = (normed.get("unit_norm") or {}).get("normalized")
    # 注意：l3_code 没传 → price_norm 不会被设置
    return normed


def _bulk_actions(actions):
    """包装 elasticsearch.helpers.bulk，统一 success/failure 计数。"""
    success, failed = bulk(_es(), actions, raise_on_error=False, request_timeout=120)
    return success, failed


def build_city(es, city: str, since: Optional[str] = None, dry_run: bool = False, batch_size: int = 500) -> dict:
    """重建/增量单个城市的 NORM 索引。返回统计。"""
    started = time.time()
    dws_idx = _dws_index(city)
    norm_idx = _norm_index(city)

    # 0. 检查 DWS 索引存在
    if not es.indices.exists(index=dws_idx):
        return {"city": city, "ok": False, "error": f"DWS 索引不存在：{dws_idx}"}

    # 1. 准备 NORM 索引（全量时强制重建；增量时不重建）
    created = False
    if not dry_run:
        if not since:
            if es.indices.exists(index=norm_idx):
                print(f"[rebuild] {norm_idx} → delete + recreate")
                es.indices.delete(index=norm_idx)
            created = _ensure_norm_index(es, city)
        else:
            created = _ensure_norm_index(es, city)

    # 2. scan DWS
    print(f"[scan] {dws_idx} (since={since or 'all'})")
    scanned = 0
    written = 0
    failed = 0
    err_samples = []
    actions = []
    for hit in _scan_dws(es, city, since=since):
        scanned += 1
        try:
            normed = _normalize_doc(hit, city)
        except Exception as e:
            failed += 1
            if len(err_samples) < 3:
                err_samples.append(f"normalize: {e}")
            continue

        if dry_run:
            if scanned <= 2:
                print(f"[dry-run sample] _id={hit.get('_id')[:20]}... canonical_period={normed.get('canonical_period')}")
            continue

        actions.append({
            "_op_type": "index",
            "_index": norm_idx,
            "_source": normed,
        })

        if len(actions) >= batch_size:
            s, f = bulk(es, actions, raise_on_error=False, stats_only=True, request_timeout=120)
            written += s
            failed += f
            actions = []
            if scanned % (batch_size * 5) == 0:
                print(f"[progress] scanned={scanned} written={written} failed={failed}")

    if actions and not dry_run:
        s, f = bulk(es, actions, raise_on_error=False, stats_only=True, request_timeout=120)
        written += s
        failed += f

    # 3. 强制 refresh（方便 dashboard 立刻读到）
    if not dry_run and written > 0:
        try:
            es.indices.refresh(index=norm_idx)
        except Exception as e:
            print(f"[warn] refresh failed: {e}")

    elapsed = time.time() - started
    summary = {
        "city": city,
        "ok": True,
        "dws_index": dws_idx,
        "norm_index": norm_idx,
        "norm_created": created,
        "dry_run": dry_run,
        "scanned": scanned,
        "written": written,
        "failed": failed,
        "elapsed_sec": round(elapsed, 2),
        "rate": round(scanned / elapsed, 1) if elapsed > 0 else 0,
        "err_samples": err_samples,
    }
    print(f"\n[summary] {json.dumps(summary, ensure_ascii=False)}")
    return summary


def main():
    ap = argparse.ArgumentParser(description="Normalizer ETL worker（DWS → NORM）")
    ap.add_argument("--city", help="单城市，如 xian")
    ap.add_argument("--cities", help="逗号分隔多城市，如 xian,hainan,chongqing")
    ap.add_argument("--all-cities", action="store_true", help="扫所有 dws_*_price 索引")
    ap.add_argument("--since", help="增量重建：period_start >= 此值 (YYYY-MM-DD)")
    ap.add_argument("--dry-run", action="store_true", help="干跑：不写 NORM，只扫描统计")
    ap.add_argument("--batch-size", type=int, default=500)
    ap.add_argument("--es-host", default=ES_HOST, help="ES 地址")
    args = ap.parse_args()

    if not any([args.city, args.cities, args.all_cities]):
        ap.error("必须传 --city / --cities / --all-cities 之一")

    cities = []
    if args.city:
        cities = [args.city]
    elif args.cities:
        cities = [c.strip() for c in args.cities.split(",") if c.strip()]
    elif args.all_cities:
        es = _es()
        # 扫所有 dws_*_price
        resp = es.indices.get(index="dws_*_price", ignore_unavailable=True)
        for idx in resp.keys():
            # dws_xian_price → xian
            slug = idx.replace("dws_", "").replace("_price", "")
            if slug:
                cities.append(slug)

    print(f"[plan] cities={cities} since={args.since} dry_run={args.dry_run}")

    es = _es()
    results = []
    for city in cities:
        try:
            r = build_city(es, city, since=args.since, dry_run=args.dry_run, batch_size=args.batch_size)
        except Exception as e:
            r = {"city": city, "ok": False, "error": str(e)}
            print(f"[ERROR] {city}: {e}")
        results.append(r)

    print("\n========= FINAL =========")
    print(json.dumps(results, ensure_ascii=False, indent=2))

    # exit code：有失败则 1
    if any(not r.get("ok") or r.get("failed", 0) > 0 for r in results):
        sys.exit(1)


if __name__ == "__main__":
    main()