"""对外展示页聚合数据（公开访问，不需要 JWT）

聚合：
  - 城市 / 省份（来自 skill_registry）
  - DWS / DWD / ODS 三层总记录数
  - 归一品种数 + L1 类别数（走 norm_*）
  - 存储量
  - 数据最新日期
  - 按省份分组的城市列表（用于首页"覆盖矩阵"）

公开原因：/index 是对外门面页，访客不需要登录也能看到覆盖规模。
安全：只读 ES 聚合，不返回原始价格数据。
"""
from fastapi import APIRouter, HTTPException
from elasticsearch import Elasticsearch
from collections import OrderedDict
from datetime import datetime
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from api.skill_registry import get_all as _registry_get_all

router = APIRouter(prefix="/api/showcase", tags=["showcase"])

ES_HOST = os.environ.get("ES_HOST", "http://localhost:59200")
es = Elasticsearch([ES_HOST])


def _scan_indices(pattern: str) -> list:
    """按 pattern 扫 ES 索引列表"""
    try:
        cat = es.cat.indices(index=pattern, format="json")
        return [r.get("index", "") for r in cat if r.get("index")]
    except Exception:
        return []


def _safe_count(pattern: str) -> int:
    try:
        r = es.count(index=pattern, ignore_unavailable=True, allow_no_indices=True)
        return int(r.get("count", 0) or 0)
    except Exception:
        return 0


def _safe_storage_bytes(pattern: str) -> int:
    try:
        cat = es.cat.indices(index=pattern, format="json", bytes="b")
        return sum(int(r.get("store.size", "0") or 0) for r in cat)
    except Exception:
        return 0


def _ms_to_date(ms) -> str:
    if not ms:
        return ""
    try:
        return datetime.utcfromtimestamp(int(ms) / 1000).strftime("%Y-%m-%d")
    except Exception:
        return ""


@router.get("/stats")
def showcase_stats():
    """对外首页聚合数据 — 公开访问"""
    try:
        # ── 1. 城市 / 省份 ──
        all_skills = _registry_get_all()
        active_skills = [s for s in all_skills if s.get("dws_index")]

        # dedupe by key（多套 skill 可能指向同一城市）
        seen = set()
        cities_deduped = []
        for s in active_skills:
            k = s["key"]
            if k in seen:
                continue
            seen.add(k)
            cities_deduped.append({
                "key": k,
                "label": s.get("label", k),
                "province": s.get("province", ""),
                "dws_index": s.get("dws_index", ""),
            })

        provinces_set = sorted({c["province"] for c in cities_deduped if c["province"]})

        # ── 2. 三层索引 ──
        dws_indices = _scan_indices("dws_*_price")
        dwd_indices = _scan_indices("dwd_*_price")
        ods_indices = _scan_indices("ods_material_*_price")
        norm_indices = _scan_indices("norm_*_price")

        # ── 3. 三层总记录 ──
        dws_total = _safe_count("dws_*_price")
        dwd_total = _safe_count("dwd_*_price")
        ods_total = _safe_count("ods_material_*_price")
        norm_total = _safe_count("norm_*_price")

        # ── 4. 存储 ──
        storage_bytes = (
            _safe_storage_bytes("dws_*_price")
            + _safe_storage_bytes("dwd_*_price")
            + _safe_storage_bytes("ods_material_*_price")
        )
        storage_mb = round(storage_bytes / 1024 / 1024, 1)

        # ── 5. 归一品种数 ──
        breeds_count = 0
        if norm_indices:
            try:
                r = es.search(
                    index=",".join(norm_indices),
                    body={"size": 0, "aggs": {"breeds": {"cardinality": {"field": "normalized_breed.keyword"}}}},
                    ignore_unavailable=True,
                    allow_no_indices=True,
                )
                breeds_count = int(r.get("aggregations", {}).get("breeds", {}).get("value", 0) or 0)
            except Exception:
                pass

        # ── 6. L1 类别数 ──
        categories_count = 0
        if norm_indices:
            try:
                r = es.search(
                    index=",".join(norm_indices),
                    body={"size": 0, "aggs": {"l1": {"cardinality": {"field": "category_l1.keyword"}}}},
                    ignore_unavailable=True,
                    allow_no_indices=True,
                )
                categories_count = int(r.get("aggregations", {}).get("l1", {}).get("value", 0) or 0)
            except Exception:
                pass

        # ── 7. 最新数据日期（DWS） ──
        latest_update = ""
        if dws_indices:
            try:
                r = es.search(
                    index=",".join(dws_indices),
                    body={"size": 0, "aggs": {"max_date": {"max": {"field": "period_end"}}}},
                    ignore_unavailable=True,
                    allow_no_indices=True,
                )
                val = r.get("aggregations", {}).get("max_date", {}).get("value")
                latest_update = _ms_to_date(val)
            except Exception:
                pass

        # ── 8. 按省份分组的城市数据 ──
        provinces_grouped = []
        idx_map = {c["dws_index"]: c for c in cities_deduped if c.get("dws_index")}

        if dws_indices:
            try:
                r = es.search(
                    index=",".join(dws_indices),
                    body={
                        "size": 0,
                        "aggs": {
                            "by_index": {
                                "terms": {"field": "_index", "size": 50},
                                "aggs": {
                                    "max_date": {"max": {"field": "period_end"}},
                                    "count": {"value_count": {"field": "price"}},
                                },
                            }
                        },
                    },
                    ignore_unavailable=True,
                    allow_no_indices=True,
                )
                buckets = r.get("aggregations", {}).get("by_index", {}).get("buckets", [])
                tmp = {}
                for b in buckets:
                    idx = b.get("key", "")
                    city = idx_map.get(idx)
                    if not city:
                        continue
                    val = b.get("max_date", {}).get("value")
                    latest = _ms_to_date(val)
                    prov = city.get("province") or "其他"
                    if prov not in tmp:
                        tmp[prov] = []
                    tmp[prov].append({
                        "key": city["key"],
                        "label": city.get("label", city["key"]),
                        "latest": latest,
                        "count": int(b.get("doc_count", 0) or 0),
                    })
                # 保持省份列表顺序稳定
                for p in provinces_set:
                    if p in tmp:
                        tmp[p].sort(key=lambda c: c["label"])
                        provinces_grouped.append({"name": p, "cities": tmp[p]})
            except Exception:
                pass

        return {
            "cities_count": len(cities_deduped),
            "provinces_count": len(provinces_set),
            "dws_total": dws_total,
            "dwd_total": dwd_total,
            "ods_total": ods_total,
            "norm_total": norm_total,
            "total_records": dws_total + dwd_total + ods_total,
            "breeds_count": breeds_count,
            "categories_count": categories_count,
            "storage_mb": storage_mb,
            "latest_update": latest_update,
            "provinces_grouped": provinces_grouped,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
