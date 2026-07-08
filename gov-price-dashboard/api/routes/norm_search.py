"""api/routes/norm_search.py

跨城 NORM 索引品种统一搜索：扫码 norm_*_price 的 normalized_breed 字段，
返回每个匹配品种 → 命中城市 + 文档数，用于 trend / breed-rec 等需要"统一品种跨城对比"的场景。

- 端点：GET /api/norm/breeds/search
- 默认跨全部 norm_*_price 索引，可选 ?cities=a,b,c 限定
- 查询策略：terms agg + include=regex（比 match_phrase 更稳，子串模糊命中）
"""
from __future__ import annotations
import re
import os
from fastapi import APIRouter, Query
from elasticsearch import Elasticsearch

router = APIRouter()

ES_HOST = os.environ.get("ES_HOST", "http://localhost:59200")
es = Elasticsearch([ES_HOST], request_timeout=15)


def _list_norm_indices(cities: str = "") -> list[str]:
    """根据 cities 参数决定要查的 norm_*_price 索引列表。

    空 → 所有 norm_*_price（通过 _cat/indices 实时拉）
    非空 → norm_<c>_price 形式拼
    """
    if cities.strip():
        out = []
        for c in cities.split(","):
            c = c.strip()
            if not c:
                continue
            out.append(f"norm_{c}_price")
        return out
    try:
        cat = es.cat.indices(index="norm_*_price", format="json")
        out = []
        for r in cat:
            idx = r.get("index", "")
            if idx.startswith("norm_") and idx.endswith("_price"):
                out.append(idx)
        return out
    except Exception:
        return []


def _make_city_label_map() -> dict[str, str]:
    """city key → 中文标签，便于前端展示。

    来源：api/skill_registry.get_all()（成功注册的话），否则就 key 本身。
    """
    try:
        from api.skill_registry import get_all  # type: ignore
        return {s["key"]: s.get("label", s["key"]) for s in get_all()}
    except Exception:
        return {}


@router.get("/api/norm/breeds/search")
def norm_breed_search(
    keyword: str = Query(..., min_length=1, max_length=64, description="匹配关键字（子串模糊）"),
    cities: str = Query("", description="逗号分隔的城市 key；留空查所有 norm_*_price"),
    limit: int = Query(20, ge=1, le=50, description="返回条数上限"),
    min_count: int = Query(1, ge=0, description="最小文档数（过滤偶发 1-2 条散样本）"),
):
    """跨城 NORM 索引品种统一搜索。

    返回按 total_docs desc，每条形如：
    {
      "normalized_breed": "商品沥青砼",
      "total_docs": 1041,
      "cities": [{"key": "sichuan", "label": "四川", "docs": 1041}, ...]
    }
    """
    kw = keyword.strip()
    if not kw:
        return {"ok": False, "error": "keyword 不能为空", "results": []}

    indices = _list_norm_indices(cities)
    if not indices:
        return {"ok": True, "keyword": kw, "results": [], "queried_indices": [],
                "note": "no norm_*_price indices available"}

    # 过滤掉 ES 里真实不存在的（ignore_unavailable 兜底但我们提前瘦身日志）
    keep = []
    for idx in indices:
        try:
            if es.indices.exists(index=idx):
                keep.append(idx)
        except Exception:
            continue
    if not keep:
        return {"ok": True, "keyword": kw, "results": [], "queried_indices": [],
                "note": "no requested indices exist"}
    indices_str = ",".join(keep)

    label_map = _make_city_label_map()

    # 转义后拼成正则：用户输入 "C20" / "商品砼" 都能作为子串匹配
    # 长关键词（≥3）做正则；过短的（如 "C"）做精确前缀避免爆炸
    if len(kw) <= 1:
        # 单字符 → 精确 term（避免 include=.*C.* 把所有含 C 字符的都拉出来）
        body = {
            "size": 0,
            "aggs": {
                "b": {
                    "terms": {
                        "field": "normalized_breed.keyword",
                        "size": limit * 5,
                        "include": re.escape(kw),
                    },
                    "aggs": {
                        "cities": {"terms": {"field": "_index", "size": 50}},
                    },
                }
            },
        }
    else:
        # 子串模糊
        body = {
            "size": 0,
            "aggs": {
                "b": {
                    "terms": {
                        "field": "normalized_breed.keyword",
                        "size": limit * 5,
                        "include": f".*{re.escape(kw)}.*",
                    },
                    "aggs": {
                        "cities": {"terms": {"field": "_index", "size": 50}},
                    },
                }
            },
        }

    try:
        res = es.search(index=indices_str, body=body, ignore_unavailable=True)
    except Exception as ex:
        return {"ok": False, "error": f"ES 查询失败: {ex}", "results": [], "queried_indices": indices}

    buckets = res.get("aggregations", {}).get("b", {}).get("buckets", [])
    results = []
    for b in buckets:
        total = b.get("doc_count", 0)
        if total < min_count:
            continue
        cities_out = []
        for c in b.get("cities", {}).get("buckets", []):
            # _index 形如 norm_sichuan_price → key='sichuan'
            idx_name = c.get("key", "")
            m = re.match(r"^norm_(.+?)_price$", idx_name)
            if not m:
                continue
            ck = m.group(1)
            cities_out.append({
                "key": ck,
                "label": label_map.get(ck, ck),
                "docs": c.get("doc_count", 0),
            })
        # 按 cities docs desc
        cities_out.sort(key=lambda x: -x["docs"])
        results.append({
            "normalized_breed": b["key"],
            "total_docs": total,
            "cities": cities_out,
        })

    results.sort(key=lambda x: -x["total_docs"])
    results = results[:limit]

    return {
        "ok": True,
        "keyword": kw,
        "results": results,
        "queried_indices": indices_str.split(","),
        "result_count": len(results),
    }


__all__ = ["router"]
