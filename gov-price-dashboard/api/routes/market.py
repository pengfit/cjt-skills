"""市场行情公开 API（不需 JWT）· 数据源:norm_*_price 跨城归一索引

v2 (2026-07-21): 数据源从 DWS 切到 norm。
  - 涨跌幅按 (normalized_breed, city) 跨城归一品种,本期 vs 上期均价对比
  - 热门品类跨 norm 索引聚合
  - 热力图行=normalized_breed,列=city
  - 周期用 period_end (date 类型,跨索引一致) 做 date_histogram,规避 norm 中
    period_id 类型不一 (xian=date,guizhou/henan/heze=text) 的坑
"""
from fastapi import APIRouter, HTTPException, Query
from elasticsearch import Elasticsearch
import os
import sys
import time
import math
from datetime import datetime
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from api.skill_registry import get_all as _registry_get_all

router = APIRouter(prefix="/api/market", tags=["market"])

ES_HOST = os.environ.get("ES_HOST", "http://localhost:59200")
es = Elasticsearch([ES_HOST], request_timeout=30)

# ── 缓存(60s)─────────────────────────────────────────────────
_city_period_cache: dict = {}
_CITY_PERIOD_TTL_S = 60


def _ms_to_date(ms) -> str:
    if not ms:
        return ""
    try:
        return datetime.utcfromtimestamp(int(ms) / 1000).strftime("%Y-%m-%d")
    except Exception:
        return ""


def _norm_indices() -> list:
    """运行时扫所有 norm_*_price 索引"""
    try:
        cat = es.cat.indices(index="norm_*_price", format="json")
        return [r["index"] for r in cat if r.get("index")]
    except Exception:
        return []


def _city_label(norm_index: str) -> str:
    """从 norm_xian_price 反查 '西安'"""
    for s in _registry_get_all():
        if s.get("dws_index"):
            # registry 用 dws_index / ods_index 反查,但 norm 跟 dws 同名(dws_xian_price → norm_xian_price)
            # 直接从 index 名推 key
            pass
        # 简化:从 index 名直接匹配,避免依赖 registry 不同字段名
        expected_norm = s.get("dws_index", "").replace("dws_", "norm_") if s.get("dws_index") else ""
        if expected_norm == norm_index:
            return s.get("label", s.get("key", ""))
        # 兜底:从 ods_index 反推(如果 dws_index 没配)
        expected_norm2 = s.get("ods_index", "").replace("ods_material_", "norm_").replace("_price", "_price")
        if expected_norm2 == norm_index:
            return s.get("label", s.get("key", ""))
    # 兜底兜底:把 index 名转换成可读 key
    return norm_index.replace("norm_", "").replace("_price", "")


def _city_latest_two_periods(norm_index: str):
    """用 runtime_mappings 把 period_end 转为 keyword,terms agg 取最近 2 个 unique 值。
    适用于所有期刊节奏 (月刊/双月刊/季刊),不依赖 date_histogram 的 bucket 粒度。
    返回 (latest_period_end_ms, prev_period_end_ms) | None
    """
    now = time.time()
    cached = _city_period_cache.get(norm_index)
    if cached and (now - cached[0]) < _CITY_PERIOD_TTL_S:
        return cached[1]
    try:
        r = es.search(
            index=norm_index,
            body={
                "size": 0,
                "runtime_mappings": {
                    "period_end_kw": {
                        "type": "keyword",
                        "script": {
                            "lang": "painless",
                            "source": "if (doc['period_end'].size() > 0) { emit(doc['period_end'].value.toString()); }",
                        },
                    }
                },
                "aggs": {
                    "by_period": {
                        "terms": {
                            "field": "period_end_kw",
                            "size": 10,
                            "order": {"_key": "desc"},
                        }
                    }
                },
            },
            ignore_unavailable=True,
            allow_no_indices=True,
        )
        buckets = r.get("aggregations", {}).get("by_period", {}).get("buckets", [])
        if len(buckets) < 2:
            return None
        # key 是 ISO 字符串 (如 "2026-06-30T00:00:00.000Z"),转 epoch ms
        result = []
        for b in buckets[:2]:
            try:
                pe_clean = b["key"].replace("Z", "+00:00")
                pe_dt = datetime.fromisoformat(pe_clean)
                result.append(int(pe_dt.timestamp() * 1000))
            except Exception:
                continue
        if len(result) < 2:
            return None
        ret = (result[0], result[1])
        _city_period_cache[norm_index] = (now, ret)
        return ret
    except Exception:
        return None


def _period_norm_prices(norm_index: str, period_end_ms: int, breed_size: int = 800,
                         spec_fingerprint: Optional[str] = None):
    """聚合给定 period_end(±3 天)内的 normalized_breed → avg_price + 元数据

    如果传 spec_fingerprint,会在 query 里加 filter + runtime_mappings 生成 spec_fingerprint 字段
    返回: {normalized_breed: {"price": float, "unit": str, "l3_name": str, "l1_name": str}}
    """
    range_query = {
        "range": {
            "period_end": {
                "gte": period_end_ms - 3 * 86400000,
                "lte": period_end_ms + 3 * 86400000,
            }
        }
    }
    if spec_fingerprint:
        query = {
            "bool": {
                "must": [range_query],
                "filter": [{"term": {"spec_fingerprint": spec_fingerprint}}],
            }
        }
    else:
        query = range_query

    body = {
        "size": 0,
        "query": query,
        "aggs": {
            "by_norm": {
                "terms": {"field": "normalized_breed.keyword", "size": breed_size},
                "aggs": {
                    "avg_price": {"avg": {"field": "price"}},
                    "unit": {"terms": {"field": "unit", "size": 1}},
                    "l3_name": {"terms": {"field": "category_name_l3.keyword", "size": 1}},
                    "l1_name": {"terms": {"field": "category_name_l1.keyword", "size": 1}},
                },
            }
        },
    }
    if spec_fingerprint:
        body.update(_spec_fingerprint_mapping())

    try:
        r = es.search(
            index=norm_index,
            body=body,
            ignore_unavailable=True,
            allow_no_indices=True,
        )
        result = {}
        for b in r.get("aggregations", {}).get("by_norm", {}).get("buckets", []):
            avg = b["avg_price"]["value"]
            if not avg or avg <= 0:
                continue
            result[b["key"]] = {
                "price": float(avg),
                "unit": b["unit"]["buckets"][0]["key"] if b["unit"]["buckets"] else "",
                "l3_name": b["l3_name"]["buckets"][0]["key"] if b["l3_name"]["buckets"] else "",
                "l1_name": b["l1_name"]["buckets"][0]["key"] if b["l1_name"]["buckets"] else "",
            }
        return result
    except Exception:
        return {}


def _spec_fingerprint_mapping() -> dict:
    """runtime_mappings 内层:attr (nested k/v) 拼成 canonical spec_fingerprint
    跨城同 (breed, fingerprint) 即"同规格",可比性大幅提升
    返回的 dict 用 ** 解包进 body
    """
    return {
        "runtime_mappings": {
            "spec_fingerprint": {
                "type": "keyword",
                "script": {
                    "lang": "painless",
                    "source": (
                        "def parts = new ArrayList();"
                        "if (params._source.attr != null) {"
                        "  for (def a : params._source.attr) {"
                        "    if (a.k != null && a.v != null) { parts.add(a.k + '=' + a.v); }"
                        "  }"
                        "}"
                        "if (parts.isEmpty()) {"
                        "  if (params._source.spec != null) { parts.add(params._source.spec); }"
                        "  else { parts.add('(none)'); }"
                        "}"
                        "Collections.sort(parts);"
                        "emit(String.join('|', parts));"
                    )
                }
            }
        }
    }


def _period_norm_prices_by_attr(
    norm_index: str, period_end_ms: int, breed: str, filters: list,
):
    """按 (k, v) 嵌套 attr 过滤后聚合
    filters: [{"key": "thickness", "values": ["3mm", "5mm"]}, {"key": "material", "values": ["Q235"]}]
    返回: {breed: {"price": float, "unit": str, ...}}
    """
    range_query = {
        "range": {
            "period_end": {
                "gte": period_end_ms - 3 * 86400000,
                "lte": period_end_ms + 3 * 86400000,
            }
        }
    }
    nested_clauses = []
    for f in filters:
        # attr 不是 nested,需在 _source 上手动配对。虚拟字段 attr_kv = "k||v"，
        # terms filter 配合 bool/should + minimum_should_match: 1 实现每 key 至少一匹配
        kv_should = [{"term": {"attr_kv": f"{f['key']}||{v}"}} for v in f["values"]]
        nested_clauses.append({
            "bool": {
                "should": kv_should,
                "minimum_should_match": 1,
            }
        })
    bool_query = {
        "bool": {
            "must": [range_query, {"term": {"normalized_breed.keyword": breed}}] + nested_clauses
        }
    }
    body = {
        "size": 0,
        "query": bool_query,
        "runtime_mappings": {
            "attr_kv": {
                "type": "keyword",
                "script": {
                    "lang": "painless",
                    "source": "if (params._source.attr != null) { for (def a : params._source.attr) { if (a.k != null && a.v != null) { emit(a.k + '||' + a.v); } } }",
                }
            }
        },
        "aggs": {
            "by_norm": {
                "terms": {"field": "normalized_breed.keyword", "size": 5},
                "aggs": {
                    "avg_price": {"avg": {"field": "price"}},
                    "unit": {"terms": {"field": "unit", "size": 1}},
                    "l3_name": {"terms": {"field": "category_name_l3.keyword", "size": 1}},
                    "l1_name": {"terms": {"field": "category_name_l1.keyword", "size": 1}},
                },
            }
        },
    }
    try:
        r = es.search(
            index=norm_index,
            body=body,
            ignore_unavailable=True,
            allow_no_indices=True,
        )
        result = {}
        for b in r.get("aggregations", {}).get("by_norm", {}).get("buckets", []):
            avg = b["avg_price"]["value"]
            if not avg or avg <= 0:
                continue
            result[b["key"]] = {
                "price": float(avg),
                "unit": b["unit"]["buckets"][0]["key"] if b["unit"]["buckets"] else "",
                "l3_name": b["l3_name"]["buckets"][0]["key"] if b["l3_name"]["buckets"] else "",
                "l1_name": b["l1_name"]["buckets"][0]["key"] if b["l1_name"]["buckets"] else "",
            }
        return result
    except Exception:
        return {}


def _period_norm_prices_multi_specs(
    norm_index: str, period_end_ms: int, breed: str, spec_fingerprints: list,
):
    """多规格聚合: 一次 query 返回该 breed 下所有 spec_fingerprints 的均价
    返回: {spec_fingerprint: {"price": float, "unit": str, "l3_name": str, "l1_name": str}}
    """
    range_query = {
        "range": {
            "period_end": {
                "gte": period_end_ms - 3 * 86400000,
                "lte": period_end_ms + 3 * 86400000,
            }
        }
    }
    bool_query = {
        "bool": {
            "must": [
                range_query,
                {"term": {"normalized_breed.keyword": breed}},
            ],
            "filter": [{"terms": {"spec_fingerprint": spec_fingerprints}}],
        }
    }
    body = {
        "size": 0,
        "query": bool_query,
        "aggs": {
            "by_spec": {
                "terms": {"field": "spec_fingerprint", "size": len(spec_fingerprints) * 2},
                "aggs": {
                    "avg_price": {"avg": {"field": "price"}},
                    "unit": {"terms": {"field": "unit", "size": 1}},
                    "l3_name": {"terms": {"field": "category_name_l3.keyword", "size": 1}},
                    "l1_name": {"terms": {"field": "category_name_l1.keyword", "size": 1}},
                },
            }
        },
    }
    body.update(_spec_fingerprint_mapping())
    try:
        r = es.search(
            index=norm_index,
            body=body,
            ignore_unavailable=True,
            allow_no_indices=True,
        )
        result = {}
        for b in r.get("aggregations", {}).get("by_spec", {}).get("buckets", []):
            avg = b["avg_price"]["value"]
            if not avg or avg <= 0:
                continue
            result[b["key"]] = {
                "price": float(avg),
                "unit": b["unit"]["buckets"][0]["key"] if b["unit"]["buckets"] else "",
                "l3_name": b["l3_name"]["buckets"][0]["key"] if b["l3_name"]["buckets"] else "",
                "l1_name": b["l1_name"]["buckets"][0]["key"] if b["l1_name"]["buckets"] else "",
            }
        return result
    except Exception:
        return {}


def _safe_count(pattern: str) -> int:
    try:
        return int(es.count(index=pattern, ignore_unavailable=True, allow_no_indices=True).get("count", 0) or 0)
    except Exception:
        return 0


def _short_fp(fp: str) -> str:
    """把 'diameter=20|grade=HRB400' 简化显示用(给 API row label)"""
    if not fp:
        return ""
    return fp.split("|")[:3]  # 取前 3 段,过长会被 UI 截断


# ── 端点 ──────────────────────────────────────────────────

@router.get("/overview")
def overview():
    """KPI 概览: 数据规模 / 最新期 / 整体均价变动(跨城归一后口径)"""
    norm_list = _norm_indices()
    if not norm_list:
        return {"empty": True, "message": "无 norm 数据,请先跑 ETL 归一化"}

    # 总条数
    total_records = sum(_safe_count(idx) for idx in norm_list)

    # 跨城归一品种数
    breeds_count = 0
    try:
        r = es.search(
            index=",".join(norm_list),
            body={"size": 0, "aggs": {"breeds": {"cardinality": {"field": "normalized_breed.keyword"}}}},
            ignore_unavailable=True,
            allow_no_indices=True,
        )
        breeds_count = int(r.get("aggregations", {}).get("breeds", {}).get("value", 0) or 0)
    except Exception:
        pass

    # 每城最新两期
    cities_active = 0
    cities_meta = []
    latest_end_global = 0
    prev_end_global = 0
    for idx in norm_list:
        periods = _city_latest_two_periods(idx)
        if periods:
            cities_active += 1
            latest_end, prev_end = periods
            latest_end_global = max(latest_end_global, latest_end)
            prev_end_global = max(prev_end_global, prev_end)
            cities_meta.append({
                "key": idx.replace("norm_", "").replace("_price", ""),
                "label": _city_label(idx),
                "latest_period_end": _ms_to_date(latest_end),
                "prev_period_end": _ms_to_date(prev_end),
            })

    # 整体均价变动:每城各自算本期/上期均价再取加权平均(按 common normalized_breed 数加权)
    overall_change_pct = 0.0
    weighted_sum = 0.0
    weight_total = 0
    for idx in norm_list:
        periods = _city_latest_two_periods(idx)
        if not periods:
            continue
        latest_end, prev_end = periods
        latest = _period_norm_prices(idx, latest_end, breed_size=2000)
        prev = _period_norm_prices(idx, prev_end, breed_size=2000)
        common = set(latest) & set(prev)
        if not common:
            continue
        curr_avg = sum(latest[k]["price"] for k in common) / len(common)
        prev_avg = sum(prev[k]["price"] for k in common) / len(common)
        if prev_avg > 0:
            change = (curr_avg - prev_avg) / prev_avg * 100
            weighted_sum += change * len(common)
            weight_total += len(common)
    if weight_total > 0:
        overall_change_pct = round(weighted_sum / weight_total, 2)

    return {
        "cities_count": cities_active,
        "total_records": total_records,
        "breeds_count": breeds_count,
        "overall_change_pct": overall_change_pct,
        "latest_period_end": _ms_to_date(latest_end_global),
        "prev_period_end": _ms_to_date(prev_end_global),
        "cities_meta": sorted(cities_meta, key=lambda c: c["label"]),
        "data_source": "norm_*_price",
    }


@router.get("/movers")
def movers(
    type: str = Query("up", pattern="^(up|down)$"),
    limit: int = Query(10, ge=1, le=50),
    city: Optional[str] = Query(None, description="可选:仅看某城 norm key (如 'xian')"),
):
    """涨幅榜 / 跌幅榜:每城各自取本期 vs 上期,normalized_breed 维度"""
    norm_list = _norm_indices()
    if city:
        norm_list = [f"norm_{city}_price"]

    candidates = []
    for norm_idx in norm_list:
        periods = _city_latest_two_periods(norm_idx)
        if not periods:
            continue
        latest_end, prev_end = periods

        latest_prices = _period_norm_prices(norm_idx, latest_end, breed_size=400)
        prev_prices = _period_norm_prices(norm_idx, prev_end, breed_size=400)

        city_label = _city_label(norm_idx)
        city_key = norm_idx.replace("norm_", "").replace("_price", "")

        common = set(latest_prices) & set(prev_prices)
        for breed in common:
            curr = latest_prices[breed]
            prev = prev_prices[breed]
            if prev["price"] <= 0 or curr["price"] <= 0:
                continue
            change_pct = (curr["price"] - prev["price"]) / prev["price"] * 100
            if abs(change_pct) < 0.5 or abs(change_pct) > 200:
                continue
            candidates.append({
                "breed": breed,
                "spec": "",
                "unit": curr["unit"] or prev["unit"],
                "city": city_key,
                "city_label": city_label,
                "prev_price": round(prev["price"], 2),
                "curr_price": round(curr["price"], 2),
                "change_abs": round(curr["price"] - prev["price"], 2),
                "change_pct": round(change_pct, 2),
            })

    reverse = (type == "up")
    candidates.sort(key=lambda x: x["change_pct"], reverse=reverse)
    return {"type": type, "total": len(candidates), "data": candidates[:limit]}


@router.get("/hot-categories")
def hot_categories(limit: int = Query(20, ge=1, le=50)):
    """热门品类(复合打分):跨城覆盖 × 数据密度 × 品种丰富度 × 时效"""
    norm_list = _norm_indices()
    if not norm_list:
        return {"data": []}
    try:
        # norm 的 update_date 是 date 类型(跨索引一致),无需 runtime_mappings
        r = es.search(
            index=",".join(norm_list),
            body={
                "size": 0,
                "aggs": {
                    "by_l3": {
                        "terms": {"field": "category_l3.keyword", "size": 200},
                        "aggs": {
                            "l3_name": {"terms": {"field": "category_name_l3.keyword", "size": 1}},
                            "l1_name": {"terms": {"field": "category_name_l1.keyword", "size": 1}},
                            "breeds": {"cardinality": {"field": "normalized_breed.keyword"}},
                            "cities": {"cardinality": {"field": "city"}},
                            "max_update": {"max": {"field": "update_date"}},
                            "avg_price": {"avg": {"field": "price"}},
                        },
                    }
                },
            },
            ignore_unavailable=True,
            allow_no_indices=True,
        )
        buckets = r.get("aggregations", {}).get("by_l3", {}).get("buckets", [])
        now_ms = int(datetime.now().timestamp() * 1000)

        results = []
        for b in buckets:
            l3 = b["key"]
            if not l3:
                continue
            breeds_n = int(b["breeds"]["value"])
            cities_n = int(b["cities"]["value"])
            records_n = b["doc_count"]
            latest_update = int(b["max_update"]["value"]) if b["max_update"]["value"] else 0
            days_old = max(0, (now_ms - latest_update) / 86400000) if latest_update else 365
            l3_name = b["l3_name"]["buckets"][0]["key"] if b["l3_name"]["buckets"] else l3
            l1_name = b["l1_name"]["buckets"][0]["key"] if b["l1_name"]["buckets"] else ""

            # 复合打分(归一到 0-100):
            # - 跨城覆盖 cities_n / 20 → 30 分
            # - 数据密度 log10(records_n)/6 → 20 分
            # - 品种丰富度 log10(breeds_n)/3 → 20 分
            # - 时效 1/(1+days_old/30) → 30 分
            score = (
                min(cities_n / 20, 1) * 30 +
                min(math.log10(records_n + 1) / 6, 1) * 20 +
                min(math.log10(breeds_n + 1) / 3, 1) * 20 +
                (1 / (1 + days_old / 30)) * 30
            )
            results.append({
                "category_l3": l3,
                "category_name_l3": l3_name,
                "category_name_l1": l1_name,
                "breeds_count": breeds_n,
                "cities_count": cities_n,
                "records_count": records_n,
                "days_old": round(days_old, 1),
                "score": round(score, 2),
            })

        results.sort(key=lambda x: x["score"], reverse=True)
        return {"data": results[:limit]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/change-heatmap")
def change_heatmap(
    top_n: int = Query(15, ge=1, le=30),
    breed: Optional[str] = Query(None, description="指定归一种"),
    attr_filters: Optional[str] = Query(None, description="按 k=v 过滤: 'k1:v1,v2;k2:v3'(AND 关系)"),
):
    """品类 × 城市 热力图。模式:
    1) 无参数: top N 热门归一种 × 城市
    2) ?breed=X: 单归一种 × 城市(混合,无规格对齐)
    3) ?breed=X&attr_filters=k:v,k:v: 按 attr k=v 嵌套过滤,1 行结果
    """
    norm_list = _norm_indices()
    if not norm_list:
        return {"breeds": [], "cities": [], "matrix": []}

    # 解析 attr_filters
    filters = []
    if attr_filters:
        for kv in attr_filters.split(";"):
            if ":" not in kv:
                continue
            k, vs = kv.split(":", 1)
            values = [v for v in vs.split(",") if v]
            if k and values:
                filters.append({"key": k, "values": values})

    # 1) 选行
    if breed and filters:
        # 过滤模式:1 行(filter 表达式作为标签)
        filter_label = " + ".join(
            f"{f['key']}={'/'.join(f['values'])}" for f in filters
        )
        breeds = [{
            "breed": breed,
            "category_name_l3": "",
            "category_name_l1": "",
            "records": 0,
            "filter_label": filter_label,
        }]
        row_keys = [breed]
    elif breed:
        breeds = [{"breed": breed, "category_name_l3": "", "category_name_l1": "", "records": 0}]
        row_keys = [breed]
    else:
        # Top N
        try:
            r = es.search(
                index=",".join(norm_list),
                body={
                    "size": 0,
                    "aggs": {
                        "top_breeds": {
                            "terms": {"field": "normalized_breed.keyword", "size": top_n * 3},
                            "aggs": {
                                "l3_name": {"terms": {"field": "category_name_l3.keyword", "size": 1}},
                                "l1_name": {"terms": {"field": "category_name_l1.keyword", "size": 1}},
                            },
                        }
                    },
                },
                ignore_unavailable=True,
                allow_no_indices=True,
            )
            top_breeds = r["aggregations"]["top_breeds"]["buckets"]
            breeds = []
            row_keys = []
            for b in top_breeds[:top_n]:
                l3_name = b["l3_name"]["buckets"][0]["key"] if b["l3_name"]["buckets"] else ""
                l1_name = b["l1_name"]["buckets"][0]["key"] if b["l1_name"]["buckets"] else ""
                breeds.append({
                    "breed": b["key"],
                    "category_name_l3": l3_name,
                    "category_name_l1": l1_name,
                    "records": b["doc_count"],
                })
                row_keys.append(b["key"])
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    # 2) 城市列表
    cities = []
    idx_set = set(norm_list)
    for s in _registry_get_all():
        dws = s.get("dws_index")
        if dws:
            norm_equiv = dws.replace("dws_", "norm_")
            if norm_equiv in idx_set:
                cities.append({"key": s["key"], "label": s.get("label", s["key"])})
    cities.sort(key=lambda c: c["label"])

    # 3) 每城查最新两期,构建矩阵
    matrix = [[None] * len(cities) for _ in row_keys]

    for ci, city_info in enumerate(cities):
        norm_idx = next(
            (idx for idx in norm_list if idx.replace("norm_", "").replace("_price", "") == city_info["key"]),
            None,
        )
        if not norm_idx:
            continue
        periods = _city_latest_two_periods(norm_idx)
        if not periods:
            continue
        latest_end, prev_end = periods

        if breed and filters:
            # attr 过滤:一次 query 拿所有匹配 docs 的均价
            latest = _period_norm_prices_by_attr(norm_idx, latest_end, breed, filters)
            prev = _period_norm_prices_by_attr(norm_idx, prev_end, breed, filters)
            if breed in latest and breed in prev:
                curr_p = latest[breed]["price"]
                prev_p = prev[breed]["price"]
                if prev_p > 0:
                    matrix[0][ci] = round((curr_p - prev_p) / prev_p * 100, 2)
        else:
            # Top N 或单 breed 模式(混合,无规格对齐)
            latest = _period_norm_prices(norm_idx, latest_end, breed_size=1500)
            prev = _period_norm_prices(norm_idx, prev_end, breed_size=1500)
            for bi, breed_key in enumerate(row_keys):
                if breed_key in latest and breed_key in prev:
                    curr_p = latest[breed_key]["price"]
                    prev_p = prev[breed_key]["price"]
                    if prev_p > 0:
                        matrix[bi][ci] = round((curr_p - prev_p) / prev_p * 100, 2)

    return {
        "breeds": breeds,
        "cities": cities,
        "matrix": matrix,
        "attr_filters": filters,
    }


@router.get("/attr-keys")
def attr_keys(
    breed: str = Query(..., description="归一品种名"),
    limit_per_value: int = Query(30, ge=1, le=100),
):
    """列出某归一种下所有 (k, [v1, v2, ...]) 组合 + 文档数
    用于前端 k=v 自由组合选择。attr 在 norm 索引中不是 nested,是普通 object 配 k/v 平行数组。
    用 runtime_mappings 虚拟字段 attr_kv = 'k||v' 做聚合。
    """
    from collections import defaultdict
    norm_list = _norm_indices()
    if not norm_list:
        return {"data": []}

    # 跨索引聚合(runtime_mappings 解决了 mapping 不一致问题)
    body = {
        "size": 0,
        "query": {"term": {"normalized_breed.keyword": breed}},
        "runtime_mappings": {
            "attr_kv": {
                "type": "keyword",
                "script": {
                    "lang": "painless",
                    "source": "if (params._source.attr != null) { for (def a : params._source.attr) { if (a.k != null && a.v != null) { emit(a.k + '||' + a.v); } } }",
                },
            }
        },
        "aggs": {
            "kv_pairs": {
                "terms": {"field": "attr_kv", "size": limit_per_value * 5},
            }
        },
    }
    try:
        r = es.search(
            index=",".join(norm_list),
            body=body,
            ignore_unavailable=True,
            allow_no_indices=True,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    # 拼装:{k: {v: docs}}
    key_agg: dict = defaultdict(lambda: defaultdict(int))
    for b in r.get("aggregations", {}).get("kv_pairs", {}).get("buckets", []):
        kv = b["key"]
        if "||" not in kv:
            continue
        k, v = kv.split("||", 1)
        key_agg[k][v] += b["doc_count"]

    result = []
    for k, vs in key_agg.items():
        values = [{"value": v, "docs": docs} for v, docs in sorted(vs.items(), key=lambda x: x[1], reverse=True)]
        total = sum(vs.values())
        result.append({"key": k, "values": values, "total_docs": total})
    result.sort(key=lambda x: x["total_docs"], reverse=True)
    return {"data": result}


@router.get("/spec-fingerprints")
def spec_fingerprints(
    breed: str = Query(..., description="归一品种名 (normalized_breed)"),
    min_cities: int = Query(2, ge=1, le=20, description="最小城市覆盖数(过滤稀疏)"),
    limit: int = Query(20, ge=1, le=50),
):
    """列出某归一种下所有跨城共现的规格指纹,按城市覆盖数倒序
    用法: GET /api/market/spec-fingerprints?breed=热轧等边角钢
    返回: {"data": [{"fingerprint": "..."", "cities_count": N, "records": M, "sample_spec": "..."}]}
    """
    norm_list = _norm_indices()
    if not norm_list:
        return {"data": []}
    try:
        body = {
            "size": 0,
            "query": {"term": {"normalized_breed.keyword": breed}},
            "aggs": {
                "by_fp": {
                    "terms": {"field": "spec_fingerprint", "size": 200},
                    "aggs": {
                        "cities": {"cardinality": {"field": "city"}},
                        "sample": {"top_hits": {"size": 1, "_source": ["spec"]}},
                    },
                }
            },
        }
        body.update(_spec_fingerprint_mapping())
        r = es.search(
            index=",".join(norm_list),
            body=body,
            ignore_unavailable=True,
            allow_no_indices=True,
        )
        buckets = r.get("aggregations", {}).get("by_fp", {}).get("buckets", [])
        results = []
        for b in buckets:
            cities_n = int(b["cities"]["value"])
            if cities_n < min_cities:
                continue
            hits = b.get("sample", {}).get("hits", {}).get("hits", [])
            sample_spec = hits[0].get("_source", {}).get("spec", "") if hits else ""
            results.append({
                "fingerprint": b["key"],
                "cities_count": cities_n,
                "records": b["doc_count"],
                "sample_spec": sample_spec,
            })
        results.sort(key=lambda x: (x["cities_count"], x["records"]), reverse=True)
        return {"data": results[:limit]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))