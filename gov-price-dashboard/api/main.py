from fastapi import FastAPI, Query, HTTPException, Body, Request
from fastapi.middleware.cors import CORSMiddleware
from elasticsearch import Elasticsearch, NotFoundError, RequestError, ConnectionError as ESConnectionError, ConnectionTimeout
from typing import Optional
import os, sys, sqlite3
import yaml
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ES_HOST = os.environ.get("ES_HOST", "http://localhost:59200")
ES_INDEX = os.environ.get("ES_INDEX", "dwd_xian_price")

# 分类库路径（2026-07-09 起统一到 breed_canonical.db）
# 原 category_v3_rules.db 仍由 gov-price-etl 写入，但 dashboard 层改读 breed_canonical.db
# 路径统一从 api.paths 推导（单一来源，只读 SKILLS_ROOT 环境变量）
from api.paths import CATEGORY_DB  # noqa: E402

# 集中引用 skill registry（见 api/skill_registry.py）
# 新增/修改 skill 只需编辑 skills/<name>/skill.yml，重启后自动生效
from api.skill_registry import (
    get_all as _registry_get_all,
    get as _registry_get,
    reload as _registry_reload,
    dws_indices_csv as _registry_dws_csv,
    ods_indices_csv as _registry_ods_csv,
    dwd_indices_csv as _registry_dwd_csv,
)

# 启动时预热一次 registry（_registry_get_all 内部懒加载，但显式 reload 更稳）
# 2026-06-30：ALL_INDICES 改为默认走 DWS（业务层）。
# 理由：category / search / overview 等业务接口需要 attr + 有效价格 + v3 分类，
#       这些字段只在 DWS 层完整。ODS 只用于数据健康 / 同步进度 / 审计场景。
try:
    _registry_reload()
    ALL_INDICES = _registry_dws_csv()  # ← 默认 DWS
    if not ALL_INDICES:
        ALL_INDICES = "dws_xian_price,dws_sichuan_price,dws_chongqing_price,dws_jinan_price,dws_rizhao_price,dws_heze_price,dws_henan_price,dws_qingdao_price"
except Exception as _e:
    print(f"[warn] skill_registry 初始化失败: {_e}，使用默认 ALL_INDICES")
    ALL_INDICES = "dws_xian_price,dws_sichuan_price,dws_chongqing_price,dws_jinan_price,dws_rizhao_price,dws_heze_price,dws_henan_price,dws_qingdao_price"

# 兼容旧引用：保留 ALL_ODS_INDICES 指向 ODS（数据健康 / 同步进度 / 审计）


try:
    ALL_ODS_INDICES = _registry_ods_csv()
    if not ALL_ODS_INDICES:
        ALL_ODS_INDICES = "ods_material_xian_price,ods_material_sichuan_price,ods_material_chongqing_price,ods_material_jinan_price,ods_material_rizhao_price,ods_material_heze_price,ods_material_henan_price,ods_material_qingdao_price"
except Exception:
    ALL_ODS_INDICES = "ods_material_xian_price,ods_material_sichuan_price,ods_material_chongqing_price,ods_material_jinan_price,ods_material_rizhao_price,ods_material_heze_price,ods_material_henan_price,ods_material_qingdao_price"


# ── 空索引辅助（ES 清空 / 同步未跑 时返回空数据，不报错）───────────────────
_EMPTY_SEARCH = {
    "hits": {"total": {"value": 0}, "hits": []},
    "aggregations": {},
}


def safe_search(es, index, body, default=None):
    """安全 ES search：索引缺失/无文档时返回 default（默认 _EMPTY_SEARCH）"""
    try:
        return es.search(
            index=index,
            body=body,
            ignore_unavailable=True,
            allow_no_indices=True,
        )
    except (NotFoundError, RequestError, ESConnectionError, ConnectionTimeout):
        return default if default is not None else _EMPTY_SEARCH
    except Exception as e:
        # 其他错误（聚合错误、字段不存在等）也返回空
        print(f"[warn] safe_search: {type(e).__name__}: {e}")
        return default if default is not None else _EMPTY_SEARCH


def safe_count(es, index, body=None, default=0):
    """安全 ES count：索引缺失时返回 default"""
    try:
        r = es.count(
            index=index,
            body=body or {},
            ignore_unavailable=True,
            allow_no_indices=True,
        )
        return r.get("count", default)
    except (NotFoundError, RequestError, ESConnectionError, ConnectionTimeout):
        return default
    except Exception as e:
        print(f"[warn] safe_count: {type(e).__name__}: {e}")
        return default


def safe_total_count(es, index, body=None, default=0):
    """安全 ES search(track_total_hits) 返回的精确总数。
    比 safe_count 性能差一点但跨分片精确，不会被 10000 上限卡。
    用于仪表盘 total_docs 等需要精确值的场景。
    """
    try:
        payload = {"size": 0, "track_total_hits": True}
        if body:
            payload.update(body)
        r = safe_search(es, index, payload, default={"hits": {"total": {"value": default}}})
        return r.get("hits", {}).get("total", {}).get("value", default)
    except Exception as e:
        print(f"[warn] safe_total_count: {type(e).__name__}: {e}")
        return default

# 新增 ALL_DWD_INDICES（规格质量 / 分类校对 / 字段追溯场景用）
try:
    ALL_DWD_INDICES = _registry_dwd_csv()
    if not ALL_DWD_INDICES:
        ALL_DWD_INDICES = "dwd_xian_price,dwd_sichuan_price,dwd_chongqing_price,dwd_jinan_price,dwd_rizhao_price,dwd_heze_price,dwd_henan_price,dwd_qingdao_price"
except Exception:
    ALL_DWD_INDICES = "dwd_xian_price,dwd_sichuan_price,dwd_chongqing_price,dwd_jinan_price,dwd_rizhao_price,dwd_heze_price,dwd_henan_price,dwd_qingdao_price"

app = FastAPI(title="材价通 API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 2026-07-19 全局鉴权 middleware(刀切)
# 规则:/api/* 全部要求 admin JWT,仅 /api/auth/login 公开
# (因为 /api/auth/me 与 /api/auth/logout 仍需 token,不算严格公众)
# /api/health 改迁 /healthz(docker healthcheck 用),跳出 /api/
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
from api.auth import JWT_SECRET, JWT_ALG, decode_token
from jose import JWTError
_PUBLIC_PATHS = {"/api/auth/login", "/api/", "/api", "/api/showcase/stats", "/api/showcase/insight"}


class AuthMiddleware(BaseHTTPMiddleware):
    """对所有 /api/* 路径强制 JWT 鉴权(/api/auth/login 除外)"""

    async def dispatch(self, request, call_next):
        path = request.url.path
        # 非 /api/ 路径(SPA、static、/healthz 等)直接放过
        if not path.startswith("/api/") and path != "/api":
            return await call_next(request)
        # 白名单
        if path in _PUBLIC_PATHS:
            return await call_next(request)
        # 取 Bearer token
        auth = request.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            return JSONResponse(
                {"detail": "missing Authorization header"},
                status_code=401,
                headers={"WWW-Authenticate": "Bearer"},
            )
        token = auth[7:].strip()
        try:
            # 直接复用 decode_token 的逻辑,但走原始 jwt.decode 不要抛 HTTPException
            from jose import jwt as _jwt
            payload = _jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALG])
        except JWTError as e:
            return JSONResponse(
                {"detail": f"invalid token: {e}"},
                status_code=401,
                headers={"WWW-Authenticate": "Bearer"},
            )
        # 把 user 信息挂到 request.state,后续路由可以直接读
        request.state.user = payload
        return await call_next(request)


app.add_middleware(AuthMiddleware)

from api.routes.auth import router as auth_router
app.include_router(auth_router)  # 公开（登录/验证 token）
from api.auth import get_current_user
from fastapi import Depends
# 2026-07-19：所有业务路由都要求 admin JWT（/api/auth/* 与 /api/health 仍公开）
_PROTECTED = {"dependencies": [Depends(get_current_user)]}
from api.routes.provenance import router as provenance_router
app.include_router(provenance_router, **_PROTECTED)
from api.routes.trend import router as trend_router
app.include_router(trend_router, **_PROTECTED)
from api.routes.breed_recommend import router as breed_recommend_router
app.include_router(breed_recommend_router, **_PROTECTED)
from api.routes.norm_search import router as norm_search_router
app.include_router(norm_search_router, **_PROTECTED)
from api.routes.category_trend import router as category_trend_router
app.include_router(category_trend_router, **_PROTECTED)

# 2026-07-19：对外展示页聚合数据（公开，不需要 JWT）
# 只读 ES 聚合 + skill registry,无原始数据泄露
from api.routes.showcase import router as showcase_router
app.include_router(showcase_router)

es = Elasticsearch([ES_HOST])


def _scan_norm_indices() -> str:
    """运行时扫 ES 拼出 norm_<city>_price 列表（用于分类浏览等跨城统一品种场景）。

    加新城市只要对应 skill.yml + ETL 走完，restart 后此函数会自动拾到。
    返回逗号分隔字符串，没有则空串。
    """
    try:
        cat = es.cat.indices(index="norm_*_price", format="json")
        out = []
        for r in cat:
            idx = r.get("index", "")
            if idx.startswith("norm_") and idx.endswith("_price"):
                out.append(idx)
        return ",".join(sorted(out))
    except Exception as ex:
        print(f"[warn] _scan_norm_indices 失败: {ex}")
        return ""


# ── 分类 / 浏览 全场景 走 norm_*_price（归一品种名跨城统一）
NORM_INDICES = _scan_norm_indices()
if not NORM_INDICES:
    print("[warn] NORM_INDICES 为空，未扫到任何 norm_*_price，类别接口将不提供数据")
else:
    head = NORM_INDICES[:200]
    more = '...' if len(NORM_INDICES) > 200 else ''
    print(f"[info] NORM_INDICES = {head}{more}")


def _filter_existing_indices(csv: str) -> str:
    """过滤掉 ES 中不存在的索引（用于 DWS 索引可能缺失的情况）"""
    indices = [i.strip() for i in csv.split(",") if i.strip()]
    if not indices:
        return csv
    keep = []
    for idx in indices:
        try:
            if es.indices.exists(index=idx):
                keep.append(idx)
        except Exception:
            pass
    if not keep:
        return csv
    dropped = [i for i in indices if i not in keep]
    if dropped:
        print(f"[info] ALL_INDICES 过滤掉缺失索引: {dropped}")
    return ",".join(keep)


# DWD/DWS 索引若尚未跑 ETL 不会创建；启动时过滤掉不存在的，避免搜索接口 500
ALL_INDICES = _filter_existing_indices(ALL_INDICES)


def _build_bool_query(must_clauses, filter_clauses):
    """构建 bool 查询，处理空列表情况"""
    must_clause = must_clauses if must_clauses else [{"match_all": {}}]
    if filter_clauses:
        return {"bool": {"must": must_clause, "filter": filter_clauses}}
    return {"bool": {"must": must_clause}}


# @app.get("/") 原返回 JSON，现改为 SPA 路由处理（让 Vue index.html 占领根路径）
# API 信息改为 /api/ 路径，避免与 SPA fallback 冲突
@app.get("/api/", include_in_schema=False)
def api_info():
    return {"message": "材价通 API", "version": "1.0.0", "docs": "/healthz"}


@app.get("/api/taxonomy/v3/tree")
def taxonomy_v3_tree():
    """返回 L1→L2→L3 分类树（纯分类体系，无 ES 计数）"""
    db_path = CATEGORY_DB
    if not os.path.isfile(db_path):
        return {"ok": False, "error": f"分类库不存在: {db_path}", "tree": []}
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        rows = conn.execute(
            "SELECT l1, name_l1, l2, name_l2, l3, name_l3 "
            "FROM category_v3 WHERE l4 = 'UNCLASSIFIED' "
            "ORDER BY l1, l2, l3"
        ).fetchall()
        conn.close()
    except Exception as e:
        return {"ok": False, "error": str(e), "tree": []}

    # 组装树
    tree = []
    l1_map = {}
    for l1, name_l1, l2, name_l2, l3, name_l3 in rows:
        if l1 not in l1_map:
            node = {"l1": l1, "name_l1": name_l1, "children": []}
            l1_map[l1] = node
            tree.append(node)
        l1_node = l1_map[l1]
        l2_node = None
        for c in l1_node["children"]:
            if c["l2"] == l2:
                l2_node = c
                break
        if not l2_node:
            l2_node = {"l2": l2, "name_l2": name_l2, "children": []}
            l1_node["children"].append(l2_node)
        l2_node["children"].append({
            "l3": l3, "name_l3": name_l3,
        })

    return {"ok": True, "tree": tree}


@app.get("/api/search")
def search(
    keyword: Optional[str] = Query(None),
    province: Optional[str] = Query(None),
    city: Optional[str] = Query(None),
    county: Optional[str] = Query(None),
    unit: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    category_l1: Optional[str] = Query(None),
    category_l2: Optional[str] = Query(None),
    category_l3: Optional[str] = Query(None),
    price_min: Optional[float] = Query(None),
    price_max: Optional[float] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
):
    must_clauses = []
    filter_clauses = []

    if keyword:
        kw_len = len(keyword)
        if kw_len <= 2:
            # 短词（≤2字符）：精确 keyword 匹配 + 宽松 fuzzy 容错
            must_clauses.append({
                "bool": {
                    "should": [
                        {"match": {"breed": keyword}},
                        {"match": {"breed": {"query": keyword, "fuzziness": "AUTO", "boost": 5}}},
                    ]
                }
            })
        else:
            # 较长词（≥3字符）：match_phrase 精确匹配 + match 宽松匹配
            must_clauses.append({
                "bool": {
                    "should": [
                        {"match_phrase": {"breed": {"query": keyword, "boost": 20}}},
                        {"match": {"breed": {"query": keyword, "boost": 10}}},
                    ]
                }
            })
    if province:
        filter_clauses.append({"term": {"province": province}})
    if city:
        filter_clauses.append({"term": {"city": city}})
    if county:
        filter_clauses.append({"term": {"county": county}})
    if unit:
        filter_clauses.append({"term": {"unit": unit}})
    if category:
        filter_clauses.append({"term": {"category": category}})
    if category_l1:
        filter_clauses.append({"term": {"category_l1": category_l1}})
    if category_l2:
        filter_clauses.append({"term": {"category_l2": category_l2}})
    if category_l3:
        filter_clauses.append({"term": {"category_l3": category_l3}})
    if price_min is not None and price_max is not None and price_min <= price_max:
        filter_clauses.append({"range": {"price": {"gte": price_min, "lte": price_max}}})
    elif price_min is not None and price_min >= 0:
        filter_clauses.append({"range": {"price": {"gte": price_min}}})
    elif price_max is not None and price_max >= 0:
        filter_clauses.append({"range": {"price": {"lte": price_max}}})

    query = _build_bool_query(must_clauses, filter_clauses)
    from_idx = (page - 1) * page_size

    body = {
        "query": query,
        "from": from_idx,
        "size": page_size,
        "sort": [
            {"period_end": {"order": "desc", "missing": "_last", "unmapped_type": "date"}},
            {"_score": {"order": "desc"}},
        ],
        "aggs": {}
    }

    try:
        result = safe_search(es, ALL_INDICES, body)
        total = result["hits"]["total"]["value"]

        # avg_price_map and prev_price_map removed - multi-index has inconsistent field types

        hits = [
            {
                "id": h["_id"],
                "breed": h["_source"].get("breed", ""),
                "category": h["_source"].get("category", ""),
                "spec": h["_source"].get("spec", ""),
                "attr": h["_source"].get("attr", {}),
                "unit": h["_source"].get("unit", ""),
                "price": h["_source"].get("price"),
                "price_t": h["_source"].get("price_t"),
                "price_unit": h["_source"].get("unit", ""),
                "tax_price": h["_source"].get("tax_price"),
                "province": h["_source"].get("province", ""),
                "city": h["_source"].get("city", ""),
                "county": h["_source"].get("county", ""),
                "date": h["_source"].get("update_date", ""),
                "avg_price": 0,
                "prev_price": 0,
            }
            for h in result["hits"]["hits"]
        ]
        return {
            "total": total,
            "page": page,
            "size": page_size,
            "pages": (total + page_size - 1) // page_size,
            "data": hits
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/stats/overview")
def overview(
    keyword: Optional[str] = Query(None),
    province: Optional[str] = Query(None),
    city: Optional[str] = Query(None),
    unit: Optional[str] = Query(None),
):
    must_clauses = []
    filter_clauses = []

    if keyword:
        kw_len = len(keyword)
        if kw_len <= 2:
            must_clauses.append({
                "bool": {
                    "should": [
                        {"match": {"breed": keyword}},
                        {"match": {"breed": {"query": keyword, "fuzziness": "AUTO", "boost": 5}}}
                    ]
                }
            })
        else:
            must_clauses.append({
                "bool": {
                    "should": [
                        {"match_phrase": {"breed": {"query": keyword, "boost": 20}}},
                        {"match": {"breed": {"query": keyword, "operator": "and", "minimum_should_match": "100%", "boost": 10}}}
                    ]
                }
            })
    if province:
        filter_clauses.append({"term": {"province": province}})
    if city:
        filter_clauses.append({"term": {"city": city}})
    if unit:
        filter_clauses.append({"term": {"unit": unit}})

    query = _build_bool_query(must_clauses, filter_clauses)
    body = {
        "query": query,
        "size": 0,
        "aggs": {
            "provinces": {"cardinality": {"field": "province"}},
            "cities": {"cardinality": {"field": "city"}},
            # 价贝用 percentiles 而非 raw max/min，过滤掉异常值（fix 2026-07-12）
            # p99.9 约 40万，能涵盖 99.9% 数据，避开 8亿 outlier
            "avg_price": {"avg": {"field": "price"}},
            "max_price": {"percentiles": {"field": "price", "percents": [99.9]}},
            "min_price": {"percentiles": {"field": "price", "percents": [1.0]}},
            "by_province": {
                "terms": {"field": "province", "size": 30},
                "aggs": {
                    "avg_price": {"avg": {"field": "price"}},
                    "count": {"value_count": {"field": "price"}}
                }
            },
            "by_category": {
                "terms": {"field": "category", "size": 30, "order": {"_count": "desc"}},
                "aggs": {
                    "avg_price": {"avg": {"field": "price"}},
                    "count": {"value_count": {"field": "price"}}
                }
            }
        }
    }
    # ES 索引可能为空（清空后未重建），返回空数据而非报错
    total_docs = safe_count(es, ALL_INDICES, body={"query": query})
    if total_docs == 0:
        return {
            "total_docs": 0,
            "total_provinces": 0,
            "total_cities": 0,
            "avg_price": 0,
            "max_price": 0,
            "min_price": 0,
            "by_province": [],
            "by_category": [],
            "categories": [],
            "empty": True,
            "message": "ES 中无业务数据，请先运行采集/ETL 重建数据",
        }
    try:
        # search 返回的是 hits.total.value，不是 count 字段（fix 2026-07-12）
        # track_total_hits=true 让 ES 返回精确总数（否则默认 10000 上限）
        total_docs = safe_total_count(es, ALL_INDICES, {"query": query})

        result = safe_search(es, ALL_INDICES, body)
        aggs = result.get("aggregations", {})
        province_buckets = aggs.get("by_province", {}).get("buckets", [])
        return {
            "total_docs": total_docs,
            "total_provinces": aggs.get("provinces", {}).get("value", 0),
            "total_cities": aggs.get("cities", {}).get("value", 0),
            "avg_price": round(aggs.get("avg_price", {}).get("value") or 0, 2),
            # percentiles 返回 {"99.9": 12345.6}，取值与 0 兜底
            "max_price": round((aggs.get("max_price", {}).get("values", {}) or {}).get("99.9", 0) or 0, 2),
            "min_price": round((aggs.get("min_price", {}).get("values", {}) or {}).get("1.0", 0) or 0, 2),
            "by_province": [
                {
                    "province": b["key"],
                    "count": b["count"]["value"],
                    "avg_price": round(b["avg_price"]["value"], 2) if b["avg_price"]["value"] else 0
                }
                for b in province_buckets
            ],
            "by_category": [
                {"category": b["key"], "count": b["count"]["value"],
                 "avg_price": round(b["avg_price"]["value"], 2) if b["avg_price"]["value"] else 0}
                for b in aggs.get("by_category", {}).get("buckets", [])
            ],
            "categories": [b["key"] for b in aggs.get("by_category", {}).get("buckets", [])]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/filter-options")
def filter_options():
    """返回省份/城市/区县列表（用于下拉筛选）"""
    province_city_agg = safe_search(es, ALL_INDICES, {
        "size": 0,
        "aggs": {
            "by_province": {
                "terms": {"field": "province", "size": 50, "order": {"_count": "desc"}},
                "aggs": {
                    "cities": {
                        "terms": {"field": "city", "size": 100},
                        "aggs": {
                            "counties": {
                                "terms": {"field": "county", "size": 100}
                            }
                        }
                    }
                }
            }
        }
    })
    city_list = []
    county_list = []
    province_city_map = {}
    for pb in province_city_agg.get("aggregations", {}).get("by_province", {}).get("buckets", []):
        prov = pb["key"]
        province_city_map[prov] = []
        for cb in pb.get("cities", {}).get("buckets", []):
            city_key = cb["key"]
            if city_key:
                city_list.append({"key": city_key, "count": cb["doc_count"], "province": prov})
                province_city_map[prov].append({"key": city_key, "count": cb["doc_count"]})
                for tb in cb.get("counties", {}).get("buckets", []):
                    county_key = tb["key"]
                    if county_key:
                        county_list.append({"key": county_key, "count": tb["doc_count"], "province": prov, "city": city_key})
    return {
        "cities": city_list,
        "counties": county_list,
        "provinceCityMap": province_city_map,
        "empty": len(city_list) == 0,
        "message": "ES 中无业务数据，请先运行采集/ETL 重建数据" if len(city_list) == 0 else "",
    }


@app.get("/api/stats/province-ranges")
def province_ranges(
    provinces: Optional[str] = Query(None, description="comma-separated province names"),
    category: Optional[str] = Query(None),
    keyword: Optional[str] = Query(None),
    unit: Optional[str] = Query(None),
):
    """返回多个省份的价格区间分布，一次调用完成"""
    must_clauses = []
    filter_clauses = []

    if category:
        filter_clauses.append({"term": {"category": category}})
    if keyword:
        kw_len = len(keyword)
        if kw_len <= 2:
            must_clauses.append({
                "bool": {
                    "should": [
                        {"match": {"breed": keyword}},
                        {"match": {"breed": {"query": keyword, "fuzziness": "AUTO", "boost": 5}}}
                    ]
                }
            })
        else:
            must_clauses.append({
                "bool": {
                    "should": [
                        {"match_phrase": {"breed": {"query": keyword, "boost": 20}}},
                        {"match": {"breed": {"query": keyword, "operator": "and", "minimum_should_match": "100%", "boost": 10}}}
                    ]
                }
            })
    if unit:
        filter_clauses.append({"term": {"unit": unit}})

    prov_list = [p.strip() for p in provinces.split(",")] if provinces else []

    query = _build_bool_query(must_clauses, filter_clauses)
    body = {
        "query": query,
        "size": 0,
        "aggs": {
            "by_province": {
                "terms": {"field": "province", "size": 30},
                "aggs": {
                    "ranges": {
                        "range": {
                            "field": "price",
                            "ranges": [
                                {"key": "50-100",    "from": 50,  "to": 100},
                                {"key": "100-200",   "from": 100, "to": 200},
                                {"key": "200-500",   "from": 200, "to": 500},
                                {"key": "500-700",   "from": 500, "to": 700},
                                {"key": "700-1000",  "from": 700, "to": 1000},
                                {"key": "1000-2000", "from": 1000, "to": 2000},
                                {"key": "2000-3000", "from": 2000, "to": 3000},
                                {"key": "3000-4000", "from": 3000, "to": 4000},
                                {"key": "4000-5000", "from": 4000, "to": 5000},
                                {"key": ">5000",      "from": 5000},
                            ]
                        },
                        "aggs": {
                            "avg_price": {"avg": {"field": "price"}}
                        }
                    }
                }
            }
        }
    }
    try:
        result = safe_search(es, ALL_INDICES, body)
        buckets = result.get("aggregations", {}).get("by_province", {}).get("buckets", [])
        data = {}
        for b in buckets:
            prov = b["key"]
            if prov_list and prov not in prov_list:
                continue
            range_buckets = b["ranges"]["buckets"]
            data[prov] = [
                {
                    "range": rb["key"],
                    "count": rb["doc_count"],
                    "avg_price": round(rb["avg_price"]["value"], 2) if rb["avg_price"]["value"] else 0,
                }
                for rb in range_buckets
            ]
        return {"data": data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/stats/price-distribution")
def price_distribution(
    province: Optional[str] = Query(None),
    city: Optional[str] = Query(None),
    keyword: Optional[str] = Query(None),
    unit: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
):
    must_clauses = []
    filter_clauses = []

    if category:
        filter_clauses.append({"term": {"category": category}})

    if keyword:
        kw_len = len(keyword)
        if kw_len <= 2:
            must_clauses.append({
                "bool": {
                    "should": [
                        {"match": {"breed": keyword}},
                        {"match": {"breed": {"query": keyword, "fuzziness": "AUTO", "boost": 5}}}
                    ]
                }
            })
        else:
            must_clauses.append({
                "bool": {
                    "should": [
                        {"match_phrase": {"breed": {"query": keyword, "boost": 20}}},
                        {"match": {"breed": {"query": keyword, "operator": "and", "minimum_should_match": "100%", "boost": 10}}}
                    ]
                }
            })
    if province:
        filter_clauses.append({"term": {"province": province}})
    if city:
        filter_clauses.append({"term": {"city": city}})
    if unit:
        filter_clauses.append({"term": {"unit": unit}})

    query = _build_bool_query(must_clauses, filter_clauses)

    body = {
        "query": query,
        "size": 0,
        "aggs": {
            "ranges": {
                "range": {
                    "field": "price",
                    "ranges": [
                        {"key": "50-100",     "from": 50,      "to": 100},
                        {"key": "100-200",    "from": 100,     "to": 200},
                        {"key": "200-500",    "from": 200,     "to": 500},
                        {"key": "500-700",    "from": 500,     "to": 700},
                        {"key": "700-1000",   "from": 700,     "to": 1000},
                        {"key": "1000-2000",  "from": 1000,    "to": 2000},
                        {"key": "2000-3000",  "from": 2000,    "to": 3000},
                        {"key": "3000-4000",  "from": 3000,    "to": 4000},
                        {"key": "4000-5000",  "from": 4000,    "to": 5000},
                        {"key": ">5000",      "from": 5000},

                    ]
                },
                "aggs": {
                    "avg_price": {"avg": {"field": "price"}}
                }
            }
        }
    }
    try:
        result = safe_search(es, ALL_INDICES, body)
        buckets = result.get("aggregations", {}).get("ranges", {}).get("buckets", [])
        return {
            "data": [
                {
                    "range": b["key"],
                    "count": b["doc_count"],
                    "avg_price": round(b["avg_price"]["value"], 2) if b["avg_price"]["value"] else 0,
                }
                for b in buckets
            ]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/stats/categories")
def stats_categories(size: int = Query(100, ge=1, le=500)):
    """返回所有产品类别及数据量（走 norm_*_price，保证跨城统一品种名）"""
    if not NORM_INDICES:
        return {"data": [], "warning": "NORM_INDICES 为空（未扫到 norm_*_price，请确认 ETL 已跑过归一化）"}
    try:
        body = {
            "size": 0,
            "aggs": {
                "categories": {
                    # NORM 里 category 是 text 类型，必须用 category.keyword 才能 terms agg
                    "terms": {"field": "category.keyword", "size": size}
                }
            }
        }
        result = safe_search(es, NORM_INDICES, body)
        buckets = result.get("aggregations", {}).get("categories", {}).get("buckets", [])
        return {
            "data": [
                {
                    "key": b["key"],
                    "count": b["doc_count"],
                }
                for b in buckets
            ]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/stats/category-detail")
def stats_category_detail(
    category: str = Query(...),
    province_limit: int = Query(20, ge=1, le=50),
    breed_limit: int = Query(20, ge=1, le=100),
):
    """返回指定类别的省份分布、热门品种（走 norm_*_price，跨城归一品种）"""
    if not NORM_INDICES:
        return {"data": {}, "warning": "NORM_INDICES 为空"}
    try:
        # query：兼容中文 cat ("建筑工程") 和 L3 code ("01.05.07")
        body = {
            "query": {
                "bool": {
                    "should": [
                        {"term": {"category": category}},
                        {"term": {"category.keyword": category}},
                        {"term": {"category_l3.keyword": category}},
                    ],
                    "minimum_should_match": 1,
                }
            },
            "size": 0,
            "aggs": {
                "avg_price": {"avg": {"field": "price"}},
                "max_price": {"max": {"field": "price"}},
                "provinces": {
                    "terms": {"field": "province", "size": province_limit}
                },
                "breeds": {
                    "terms": {"field": "normalized_breed.keyword", "size": breed_limit},
                    "aggs": {
                        "province": {"terms": {"field": "province", "size": 1}},
                        "specs": {"terms": {"field": "spec", "size": 3}},
                        "units": {
                            "terms": {"field": "unit", "size": 10},
                            "aggs": {
                                "avg_price": {"avg": {"field": "price"}},
                                "min_price": {"min": {"field": "price"}},
                                "max_price": {"max": {"field": "price"}},
                                "cnt": {"value_count": {"field": "price"}}
                            }
                        }
                    }
                },
                "breed_count": {
                    "cardinality": {"field": "normalized_breed.keyword"}
                }
            }
        }
        result = safe_search(es, NORM_INDICES, body)
        aggs = result.get("aggregations", {})

        provinces = [
            {"key": b["key"], "count": b["doc_count"]}
            for b in aggs.get("provinces", {}).get("buckets", [])
        ]

        breeds = []
        for b in aggs.get("breeds", {}).get("buckets", []):
            unit_buckets = b["units"]["buckets"]
            if unit_buckets:
                primary = unit_buckets[0]
                avg_price = round(primary["avg_price"]["value"], 2) if primary["avg_price"]["value"] else 0
                min_price = round(primary["min_price"]["value"], 2) if primary["min_price"]["value"] else 0
                max_price = round(primary["max_price"]["value"], 2) if primary["max_price"]["value"] else 0
                unit_fixed = primary["key"]
            else:
                avg_price = min_price = max_price = 0
                unit_fixed = ""
            breeds.append({
                "key": b["key"],
                "count": b["doc_count"],
                "province": b["province"]["buckets"][0]["key"] if b["province"]["buckets"] else "",
                "avg_price": avg_price,
                "min_price": min_price,
                "max_price": max_price,
                "unit": unit_fixed,
                "specs": [s["key"] for s in b["specs"]["buckets"]],
            })

        avg_val = aggs.get("avg_price", {}).get("value")
        max_val = aggs.get("max_price", {}).get("value")
        return {
            "data": {
                "category": category,
                "avg_price": round(avg_val, 2) if isinstance(avg_val, (int, float)) else 0,
                "max_price": round(max_val, 2) if isinstance(max_val, (int, float)) else 0,
                "provinces": provinces,
                "breeds": breeds,
                "breed_count": aggs.get("breed_count", {}).get("value", 0) or 0,
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/stats/category-price-ranges")
def category_price_ranges(category: str = Query(...)):
    """返回指定类别的动态价格区间，按分位数分为5段，每段覆盖约20%数据（走 norm_*_price）"""
    if not NORM_INDICES:
        return {"data": [], "stats": {"min": 0, "max": 0, "avg": 0}, "warning": "NORM_INDICES 为空"}
    try:
        # Get percentiles to build equal-frequency ranges
        stats_body = {
            "query": {
                "bool": {
                    "should": [
                        {"term": {"category.keyword": category}},
                        {"term": {"category_l3.keyword": category}},
                    ],
                    "minimum_should_match": 1,
                }
            },
            "size": 0,
            "aggs": {
                "min_price": {"min": {"field": "price"}},
                "max_price": {"max": {"field": "price"}},
                "avg_price": {"avg": {"field": "price"}},
                "price_percentiles": {
                    "percentiles": {
                        "field": "price",
                        "percents": [15, 35, 50, 65, 85]
                    }
                }
            }
        }
        stats_result = safe_search(es, NORM_INDICES, stats_body)
        aggs = stats_result.get("aggregations", {})
        min_p = aggs.get("min_price", {}).get("value", []) or 0
        max_p = aggs.get("max_price", {}).get("value", []) or 0
        avg_p = aggs.get("avg_price", {}).get("value", []) or 0

        if max_p <= 0:
            return {"data": [], "stats": {"min": 0, "max": 0, "avg": 0}}

        vals = aggs.get("price_percentiles", {}).get("values", [])
        def pct(key):
            key_str = str(key)
            key_float = float(key)
            if key_str in vals:
                return float(vals[key_str])
            for k, v in vals.items():
                if abs(float(k) - key_float) < 0.01:
                    return float(v)
            raise KeyError(key)
        t1 = pct(15.0)
        t2 = pct(35.0)
        t3 = pct(50.0)
        t4 = pct(65.0)
        t5 = pct(85.0)

        def round100(v): return float(round(v / 100) * 100)

        r0 = min_p
        r1 = round100(t1)
        r2 = round100(t2)
        r3 = round100(t3)
        r4 = round100(t4)
        r5 = round100(t5)
        r6 = max_p

        # Avoid zero-width or inverted ranges
        if r1 <= r0: r1 = r0 + 100
        if r2 <= r1: r2 = r1 + 100
        if r3 <= r2: r3 = r2 + 100
        if r4 <= r3: r4 = r3 + 100
        if r5 <= r4: r5 = r4 + 100

        def fmt(lo, hi):
            def k_str(v):
                if v >= 10000:
                    return f"{int(v/1000)}k"
                elif v >= 1000:
                    if v % 1000 == 0:
                        return f"{int(v/1000)}k"
                    return str(int(v))
                else:
                    return str(int(v))
            return f"{k_str(lo)}-{k_str(hi)}"

        def fmt_single(v):
            if v >= 10000:
                return f"{int(v/1000)}k"
            elif v >= 1000:
                if v % 1000 == 0:
                    return f"{int(v/1000)}k"
                return str(int(v))
            else:
                return str(int(v))

        ranges_config = [
            {"key": "远低于均价", "from": r0, "to": r1},
            {"key": "低于均价",   "from": r1,  "to": r2},
            {"key": "接近均价",   "from": r2,  "to": r3},
            {"key": "高于均价",   "from": r3,  "to": r4},
            {"key": "远高于均价", "from": r4,  "to": r5 + 1},
        ]

        body = {
            "query": {"match_all": {}},
            "size": 0,
            "aggs": {
                "ranges": {
                    "range": {
                        "field": "price",
                        "ranges": ranges_config
                    },
                    "aggs": {
                        "avg_price": {"avg": {"field": "price"}}
                    }
                }
            }
        }
        result = safe_search(es, ALL_INDICES, body)
        buckets = result.get("aggregations", {}).get("ranges", {}).get("buckets", [])

        data = []
        for b in buckets:
            from_val = b["from"]
            to_val = b["to"]
            is_last = (b["key"] == "远高于均价")
            if is_last:
                label = "> " + fmt_single(from_val)
            else:
                label = fmt(from_val, to_val)
            data.append({
                "range": label,
                "desc": b["key"],
                "count": b["doc_count"],
                "avg_price": round(b["avg_price"]["value"], 2) if b["avg_price"]["value"] else 0,
            })

        return {
            "data": data,
            "stats": {
                "min": round(min_p, 2),
                "max": round(max_p, 2),
                "avg": round(avg_p, 2),
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/stats/category-breeds")
def stats_category_breeds(
    category: str = Query(...),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
):
    """返回指定类别的去重品种列表（分页）——走 norm_*_price，使用 normalized_breed 跨城统一品种名。"""
    if not NORM_INDICES:
        return {"data": {"category": category, "breeds": []}, "total": 0, "warning": "NORM_INDICES 为空"}
    try:
        body = {
            "query": {
                "bool": {
                    "should": [
                        {"term": {"category": category}},
                        {"term": {"category.keyword": category}},
                        {"term": {"category_l3.keyword": category}},
                    ],
                    "minimum_should_match": 1,
                }
            },
            "size": 0,
            "aggs": {
                "all_breeds": {
                    "terms": {"field": "normalized_breed.keyword", "size": 10000},
                    "aggs": {
                        "cities": {"terms": {"field": "_index", "size": 50}},
                        "province": {"terms": {"field": "province", "size": 1}},
                        "specs": {"terms": {"field": "spec", "size": 3}},
                        "units": {
                            "terms": {"field": "unit", "size": 10},
                            "aggs": {
                                "avg_price": {"avg": {"field": "price"}},
                                "min_price": {"min": {"field": "price"}},
                                "max_price": {"max": {"field": "price"}},
                                "cnt": {"value_count": {"field": "price"}}
                            }
                        }
                    }
                }
            }
        }
        result = safe_search(es, NORM_INDICES, body)
        aggs = result.get("aggregations", {})
        all_buckets = aggs.get("all_breeds", {}).get("buckets", [])

        start = (page - 1) * page_size
        end = start + page_size
        page_buckets = all_buckets[start:end]

        import re as _re
        breeds = []
        for b in page_buckets:
            # 按 unit_fixed 分组，取最大计数量的单位组作为主价格
            unit_buckets = b["units"]["buckets"]
            if unit_buckets:
                primary = unit_buckets[0]  # 按 doc_count 排序，第一位数量最多
                avg_price = round(primary["avg_price"]["value"], 2) if primary["avg_price"]["value"] else 0
                min_price = round(primary["min_price"]["value"], 2) if primary["min_price"]["value"] else 0
                max_price = round(primary["max_price"]["value"], 2) if primary["max_price"]["value"] else 0
                unit_fixed = primary["key"]
            else:
                avg_price = min_price = max_price = 0
                unit_fixed = ""

            # 跨城命中城市：_index='norm_sichuan_price' → city='sichuan'
            cities = []
            for c in b.get("cities", {}).get("buckets", []):
                m = _re.match(r"^norm_(.+?)_price$", c.get("key", ""))
                if m:
                    cities.append(m.group(1))

            breeds.append({
                "key": b["key"],
                "count": b["doc_count"],
                "province": b["province"]["buckets"][0]["key"] if b["province"]["buckets"] else "",
                "avg_price": avg_price,
                "min_price": min_price,
                "max_price": max_price,
                "unit": unit_fixed,
                "specs": [s["key"] for s in b["specs"]["buckets"]],
                "cities": cities,
                "city_count": len(cities),
            })

        return {
            "data": {
                "category": category,
                "breeds": breeds,
            },
            "total": len(all_buckets),
            "page": page,
            "page_size": page_size,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/stats/breed-detail")
def stats_breed_detail(
    category: str = Query(...),
    breed: str = Query(...),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
):
    """返回指定品种的详细规格价格分析（按单位→规格分层聚合）——走 norm_*_price。"""
    if not NORM_INDICES:
        return {"data": {"breed": breed, "category": category, "units": [], "total_records": 0}, "warning": "NORM_INDICES 为空"}
    try:
        # normalized_breed 优先，原 breed 兌底（覆盖不同城市口径差异）
        body = {
            "query": {
                "bool": {
                    "should": [
                        {"term": {"normalized_breed.keyword": breed}},
                        {"term": {"breed.keyword": breed}},
                    ],
                    "minimum_should_match": 1,
                }
            },
            "size": 0,
            "aggs": {
                "by_unit": {
                    "terms": {
                        "script": {
                            "source": "def u = doc['unit'].value; return (u != null && u.length() > 0 && u != '/') ? u : '/';",
                            "lang": "painless"
                        },
                        "size": 20
                    },
                    "aggs": {
                        "cnt": {"value_count": {"field": "price"}},
                        "avg_p": {"avg": {"field": "price"}},
                        "by_spec": {
                            "terms": {"field": "spec", "size": 200},
                            "aggs": {
                                "cnt": {"value_count": {"field": "price"}},
                                "avg_p": {"avg": {"field": "price"}},
                                "min_p": {"min": {"field": "price"}},
                                "max_p": {"max": {"field": "price"}},
                                "by_prov": {"terms": {"field": "province", "size": 1}}
                            }
                        }
                    }
                }
            }
        }
        result = safe_search(es, NORM_INDICES, body)
        aggs = result.get("aggregations", {})
        units_data = []
        for ub in aggs.get("by_unit", {}).get("buckets", []):
            unit_key = ub["key"]
            specs_data = []
            spec_buckets = ub["by_spec"]["buckets"]

            # Pagination within specs
            start = (page - 1) * page_size
            end = start + page_size
            page_specs = spec_buckets[start:end]

            for sb in page_specs:
                prov = sb["by_prov"]["buckets"][0]["key"] if sb["by_prov"]["buckets"] else ""
                avg_v = sb["avg_p"]["value"]
                min_v = sb["min_p"]["value"]
                max_v = sb["max_p"]["value"]
                specs_data.append({
                    "key": sb["key"],
                    "count": sb["cnt"]["value"],
                    "avg_price": round(avg_v, 2) if avg_v else 0,
                    "min_price": round(min_v, 2) if min_v else 0,
                    "max_price": round(max_v, 2) if max_v else 0,
                    "province": prov
                })

            unit_avg = ub["avg_p"]["value"]
            units_data.append({
                "key": unit_key,
                "count": ub["cnt"]["value"],
                "avg_price": round(unit_avg, 2) if unit_avg else 0,
                "specs": specs_data,
                "spec_total": len(spec_buckets),
                "page": page,
                "page_size": page_size
            })

        total_records = sum(u["count"] for u in units_data)

        return {
            "data": {
                "breed": breed,
                "category": category,
                "total_records": result["hits"]["total"]["value"],
                "units": units_data
            }
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/stats/data-health")
def stats_data_health():
    """数据健康度监控：每日数据量、各省份最新日期、增量异常检测

    查 ODS 索引（原料层），反映"抓取入仓"真实进度。
    DWS 是 ETL 后的成品，数量受 ETL 性能影响，不适合做"健康度"指标。
    """
    try:
        # 1. 每日数据量（最近30天）
        # ODS 各城 update_date 字段类型不一致：xian/jinan/sichuan/chongqing/rizhao 是
        # `date` 类型（doc value 返回 ISO 8601 字符串如 "2026-06-24T00:00Z"），
        # qingdao/henan/heze/weihai 是 `keyword` 类型（doc value 返回 "2026-05-25"）。
        # 用 runtime_mappings 统一转 date，对两种情况分别处理：
        #   - date 类型：value.toString() 已经是带 T 的完整时间串，直接 parse
        #   - keyword 类型：value 是纯日期串，补 T00:00:00Z 再 parse
        daily_body = {
            "size": 0,
            "runtime_mappings": {
                "date_dt": {
                    "type": "date",
                    "script": {
                        "lang": "painless",
                        "source": "if (doc['update_date'].size() > 0) { String s = doc['update_date'].value.toString(); if (!s.contains('T')) { s = s + 'T00:00:00Z'; } emit(ZonedDateTime.parse(s).toInstant().toEpochMilli()); }"
                    }
                }
            },
            "query": {"range": {"date_dt": {"gte": "now-30d/d", "lte": "now/d"}}},
            "aggs": {
                "daily": {
                    "date_histogram": {
                        "field": "date_dt",
                        "calendar_interval": "day",
                        "min_doc_count": 0,
                        "extended_bounds": {"min": "now-30d/d", "max": "now/d"},
                    },
                    "aggs": {"count": {"value_count": {"field": "price"}}}
                }
            }
        }
        daily_result = es.search(index=ALL_ODS_INDICES, body=daily_body)
        daily_buckets = daily_result.get("aggregations", {}).get("daily", {}).get("buckets", [])
        daily_data = [
            {"date": b["key_as_string"][:10], "count": b["doc_count"]}
            for b in daily_buckets
        ]

        # 2. 各城市/省份最新数据日期（按 _index 分组）
        # ODS 各 city mapping 不一致（province 有些是 text 有些是 keyword），
        # 改用 _index 分组 + skill_registry 反查省份。
        province_body = {
            "size": 0,
            "aggs": {
                "by_index": {
                    "terms": {"field": "_index", "size": 30},
                    "aggs": {
                        "latest": {
                            "top_hits": {
                                "size": 1,
                                "sort": [{"update_date": {"order": "desc"}}],
                                "_source": ["update_date"],
                            }
                        },
                        "count": {"value_count": {"field": "price"}}
                    }
                }
            }
        }
        province_result = es.search(index=ALL_ODS_INDICES, body=province_body)
        province_buckets = province_result.get("aggregations", {}).get("by_index", {}).get("buckets", [])

        # 反查 _index → province 映射
        idx2province: dict = {s.get("ods_index"): s.get("province", "?") for s in _registry_get_all() if s.get("ods_index")}

        provinces_data = []
        for b in province_buckets:
            latest_hits = b.get("latest", {}).get("hits", {}).get("hits", [])
            latest_date = latest_hits[0]["_source"].get("update_date", "") if latest_hits else ""
            provinces_data.append({
                "province": idx2province.get(b["key"], b["key"]),  # 查不到就用索引名
                "city_index": b["key"],
                "latest_date": latest_date,
                "count": b["doc_count"],
            })
        provinces_data.sort(key=lambda x: x["latest_date"], reverse=True)

        # 3. 总览
        # Use ES _count API for accurate total (bypasses 10000 hit cap)
        try:
            count_resp = es.count(index=ALL_ODS_INDICES)
            total_count = count_resp["count"]
        except Exception:
            # Fallback: use match_all with track_total=true
            total_body = {"query": {"match_all": {}}, "size": 0, "track_total": True}
            total_result = es.search(index=ALL_ODS_INDICES, body=total_body)
            total_count = total_result["hits"]["total"]["value"]

        # 4. 分类分布（并发）—— ODS 各城 mapping 不一致，cat 字段不全有，best-effort
        cat_data = []
        try:
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                cat_body = {"size": 0, "aggs": {"by_category": {"terms": {"field": "category.keyword", "size": 20}}}}
                cat_future = pool.submit(es.search, index=ALL_ODS_INDICES, body=cat_body, ignore_unavailable=True)
            cat_result = cat_future.result()
            cat_buckets = cat_result.get("aggregations", {}).get("by_category", {}).get("buckets", [])
            cat_data = [
                {
                    "category": b["key"],
                    "count": b["doc_count"],
                }
                for b in cat_buckets
            ]
        except Exception:
            # ODS 没 category 字段（部分城市）—— 跳过，不让 health 崩
            pass

        return {
            "total_docs": total_count,
            "province_count": len(provinces_data),
            "daily": daily_data,
            "provinces": provinces_data,
            "categories": cat_data,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def _get_county_sync_details(es, es_index="ods_material_xian_price"):
    """从 material_xian_price 按区县聚合，返回各区县同步状态"""
    ALL_COUNTIES = ["阎良区", "临潼区", "高陵区", "鄠邑区", "蓝田县", "周至县"]
    try:
        body = {
            "size": 0,
            "aggs": {
                "by_county": {
                    "terms": {"field": "county", "size": 20},
                    "aggs": {
                        "max_date": {"max": {"field": "update_date"}},
                        "min_date": {"min": {"field": "update_date"}},
                        "min_create": {"min": {"field": "create_time"}},
                        "max_create": {"max": {"field": "create_time"}},
                        "count": {"value_count": {"field": "price"}}
                    }
                }
            }
        }
        res = es.search(index=es_index, body=body)
        buckets = res.get("aggregations", {}).get("by_county", {}).get("buckets", [])
        county_map = {}
        for b in buckets:
            max_d = b.get("max_date", {}).get("value_as_string", "")[:10]
            min_d = b.get("min_date", {}).get("value_as_string", "")[:10]
            county_map[b["key"]] = {
                "county": b["key"],
                "doc_count": b["doc_count"],
                "es_max_date": max_d or min_d,
                "es_min_date": min_d,
                "es_max_create": b.get("max_create", {}).get("value_as_string", "")[:19] if b.get("max_create", {}).get("value_as_string") else None,
                "status": "ok"
            }
        # Fill missing counties as never synced
        for c in ALL_COUNTIES:
            if c not in county_map:
                county_map[c] = {"county": c, "doc_count": 0, "es_max_date": None, "es_min_date": None, "status": "not_synced"}
        return list(county_map.values())
    except Exception:
        return [{"county": c, "doc_count": 0, "es_max_date": None, "status": "error"} for c in ALL_COUNTIES]

@app.get("/api/stats/{city}-sync-progress")
def stats_sync_progress(city: str):
    """通用 sync-progress 端点（替代原 9 个手写端点）

    按 city key 从 skill registry 读 cfg，按 progress_mode 分发到：
      - period: heze/henan/qingdao/weihai
      - county: xian/chongqing
      - catalogue: sichuan/jinan/rizhao
    加新 skill：只需在 skill.yml 设 progress_mode + county_field/catalogue_field，
    无需改 dashboard 代码。
    """
    from api.routes.provenance import sync_progress as _prov_sync_progress
    cfg = _registry_get(city)
    if not cfg:
        raise HTTPException(status_code=404, detail=f"未知 skill: {city}")
    try:
        return _prov_sync_progress(cfg)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/skill-updates")
def skill_updates(request: Request):
    """各城市 skill 同步检查：调用 7 城 *_sync-progress 端点，返回 last_updated + 距今时长。

    返回：
      {
        "now": "2026-06-15T10:55:00",
        "updates": [
          {
            "city": "xian",
            "city_label": "西安",
            "last_updated": "2026-06-15T06:00:00",
            "hours_since": 4.5,
            "status": "fresh"  // fresh(<24h) / stale(1-7d) / very_stale(>7d) / no_data
            "latest_period": "2026.3月",
            "completed_periods": 1,
            "total_periods": 1,
            "has_incremental": false,
          },
          ...
        ]
      }
    """
    from datetime import datetime
    import concurrent.futures
    import requests  # 内调 sync-progress 端点需要

    # 透传调用方的 Authorization header（fix 2026-07-19:以前没传导致 sync-progress 全部 401）
    auth_header = request.headers.get("Authorization", "")

    # 城市列表从 skill registry 动态拼（新增 skill 不用改这里）
    cities = [
        (s["key"], s.get("label", s["key"]), s["key"])
        for s in _registry_get_all()
    ]
    if not cities:
        cities = [
            ("xian", "西安", "xian"),
            ("sichuan", "四川", "sichuan"),
            ("chongqing", "重庆", "chongqing"),
            ("jinan", "济南", "jinan"),
            ("rizhao", "日照", "rizhao"),
            ("heze", "菏泽", "heze"),
            ("henan", "河南", "henan"),
        ]

    def fetch_one(city_key, path):
        try:
            headers = {"Authorization": auth_header} if auth_header else {}
            r = requests.get(
                f"http://localhost:5200/api/stats/{path}-sync-progress",
                timeout=10,
                headers=headers,
            )
            if r.status_code == 200:
                return city_key, r.json()
        except Exception:
            pass
        return city_key, None

    with concurrent.futures.ThreadPoolExecutor(max_workers=7) as pool:
        futures = {pool.submit(fetch_one, ck, p): ck for ck, _, p in cities}
        results = {}
        for f in concurrent.futures.as_completed(futures):
            city_key, payload = f.result()
            results[city_key] = payload

    # 兜底：从 ES DWS 索引取最新 period_end 作为 last_updated（fix 2026-07-12）
    # 新疆/西安等 sync-progress 端点未填 last_updated 时使用这个
    def fetch_es_fallback(city_key):
        """从 ES 该城市的 DWS 索引聚合最新 period_end"""
        try:
            # 从 skill registry 查 dws_index
            for s in _registry_get_all():
                if s.get("key") == city_key:
                    dws = s.get("dws_index")
                    if not dws:
                        return None
                    r = es.search(
                        index=dws,
                        body={"size": 0, "aggs": {"max_date": {"max": {"field": "period_end"}}}},
                        ignore_unavailable=True,
                        allow_no_indices=True,
                    )
                    val = r.get("aggregations", {}).get("max_date", {}).get("value")
                    if val:
                        # ES 返回的是毫秒时间戳，转 ISO
                        return datetime.fromtimestamp(val / 1000).isoformat(timespec="seconds")
                    return None
        except Exception:
            return None

    now = datetime.now()
    updates = []
    for city_key, city_label, _ in cities:
        data = results.get(city_key) or {}
        last_updated = data.get("last_updated", "")
        # 兜底：如果 sync-progress 没填，且 data 里有 ds_total > 0，去 ES 查 DWS 最新 period_end
        if not last_updated and (data.get("total_docs") or 0) > 0:
            es_fallback = fetch_es_fallback(city_key)
            if es_fallback:
                last_updated = es_fallback
        hours_since = None
        status = "no_data"
        if last_updated:
            dt = None
            # 尝试 ISO 8601（含 T）
            try:
                lu = last_updated.replace("Z", "+00:00")
                dt = datetime.fromisoformat(lu)
            except Exception:
                pass
            # 尝试 YYYY-MM-DD HH:MM:SS 空格分隔
            if dt is None:
                for fmt in ("%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S", "%Y-%m-%d", "%Y/%m/%d"):
                    try:
                        dt = datetime.strptime(last_updated, fmt)
                        break
                    except Exception:
                        continue
            if dt is not None:
                if dt.tzinfo:
                    dt = dt.astimezone().replace(tzinfo=None)
                hours_since = (now - dt).total_seconds() / 3600
                if hours_since < 0:
                    hours_since = 0
                if hours_since < 24:
                    status = "fresh"
                elif hours_since < 24 * 7:
                    status = "stale"
                else:
                    status = "very_stale"

        # latest_period 容错：
        # - 按期城市（sichuan/rizhao/jinan/heze）有 period 字段
        # - 按区县城市（xian/chongqing）有 update_date 字段但无 period
        # - henan 没 sync-progress 端点 → 留空
        latest_period = (
            data.get("es_latest_period")
            or data.get("period")
            or data.get("update_date")
            or ""
        )
        # 进度数：优先 period 期数（heze 等），fallback 到 区县数（xian/chongqing）
        completed_periods = data.get("completed_periods")
        if completed_periods is None:
            completed_periods = data.get("completed_counties") or 0
        total_periods = data.get("total_periods")
        if total_periods is None:
            total_periods = data.get("total_counties") or 0
        has_incremental = bool(data.get("has_incremental", False))

        # 重复添加，删掉
        updates.append({
            "city": city_key,
            "city_label": city_label,
            "last_updated": last_updated,
            "hours_since": round(hours_since, 1) if hours_since is not None else None,
            "status": status,
            "latest_period": latest_period,
            "completed_periods": completed_periods,
            "total_periods": total_periods,
            "has_incremental": has_incremental,
        })

    # 按 last_updated 倒序（最近更新的在前）
    updates.sort(key=lambda x: x.get("last_updated") or "", reverse=True)

    return {
        "now": now.isoformat(timespec="seconds"),
        "updates": updates,
    }


# ── Skill Registry：供前端动态发现（不写死城市清单）───────────

@app.get("/api/skill-registry")
def skill_registry():
    """返回所有已注册 skill 的清单（前端 v-for 驱动）"""
    return {
        "count": len(_registry_get_all()),
        "skills": _registry_get_all(),
    }


@app.get("/api/stats/available-cities")
def available_cities():
    """返回所有可查询的城市下拉选项（key + label）。

    CategoryTrendView 等用：只关心城市 key / label，不需要 progress / indices 等元数据。
    数据源与 /api/skill-registry 同源（扫盘 skill.yml）。
    """
    cities = [
        {"key": s["key"], "label": s.get("label", s["key"])}
        for s in _registry_get_all()
    ]
    return {"ok": True, "cities": cities}


@app.post("/api/skill-registry/reload")
def skill_registry_reload():
    """手动重新扫描 skill.yml（开发调试用）+ 热更新 ALL_INDICES / ALL_ODS_INDICES"""
    global ALL_INDICES, ALL_ODS_INDICES
    skills = _registry_reload()
    # 重新计算索引列表：与启动邇辑一致，过滤掉 ES 中不存在的索引
    new_csv = _registry_ods_csv() or ALL_INDICES
    ALL_INDICES = _filter_existing_indices(new_csv)
    ALL_ODS_INDICES = new_csv
    return {
        "count": len(skills),
        "skills": skills,
        "all_indices": ALL_INDICES,
        "message": f"重载完成，扫描到 {len(skills)} 个 skill，ALL_INDICES 已热更新",
    }


# ============================================================
# 地理分布聚合（地图可视化）
# ============================================================
# 中国省份名 → adcode 映射（DataV.GeoAtlas 用 adcode 标识省份）
_PROVINCE_ADCODE = {
    "北京": 110000, "天津": 120000, "河北": 130000, "山西": 140000,
    "内蒙古": 150000, "辽宁": 210000, "吉林": 220000, "黑龙江": 230000,
    "上海": 310000, "江苏": 320000, "浙江": 330000, "安徽": 340000,
    "福建": 350000, "江西": 360000, "山东": 370000, "河南": 410000,
    "湖北": 420000, "湖南": 430000, "广东": 440000, "广西": 450000,
    "海南": 460000, "重庆": 500000, "四川": 510000, "贵州": 520000,
    "云南": 530000, "西藏": 540000, "陕西": 610000, "甘肃": 620000,
    "青海": 630000, "宁夏": 640000, "新疆": 650000, "台湾": 710000,
}


@app.get("/api/stats/geo-distribution")
def geo_distribution(
    level: str = Query("province", pattern="^(province|city|county)$"),
    parent: Optional[str] = Query(None, description="level=city 时传 province；level=county 时传 city"),
    parent2: Optional[str] = Query(None, description="level=county 时传 province"),
    category: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None, description="YYYY-MM-DD"),
    date_to: Optional[str] = Query(None, description="YYYY-MM-DD"),
    breed: Optional[str] = Query(None, description="产品名关键词"),
):
    """
    地理分布聚合（地图着色用）
    - level=province: 全省聚合
    - level=city:     parent=省份，下钻到地市
    - level=county:   parent=省份，parent2=地市，下钻到区县
    返回：[{name, adcode, value(均价), count, min, max}]
    """
    # 1. 过滤条件
    filter_clauses = []
    if level == "city" and parent:
        filter_clauses.append({"term": {"province": parent}})
    if level == "county":
        if parent2:
            filter_clauses.append({"term": {"province": parent2}})
        if parent:
            filter_clauses.append({"term": {"city": parent}})
    if category:
        filter_clauses.append({"term": {"category": category}})
    if breed:
        filter_clauses.append({"match": {"breed": breed}})
    if date_from or date_to:
        date_range = {}
        if date_from:
            date_range["gte"] = date_from
        if date_to:
            date_range["lte"] = date_to
        filter_clauses.append({"range": {"update_date": date_range}})

    # 2. 聚合字段
    field_map = {"province": "province", "city": "city", "county": "county"}
    agg_field = field_map[level]
    size_map = {"province": 40, "city": 50, "county": 100}
    agg_size = size_map[level]
    # 四川省下钻时 ES 中 city 字段实际存的是区/县级粒度（未归一），
    # 同地市不同区/县值不同，需要放大 size 拿到所有桶再归一
    if level == "city" and parent == "四川":
        agg_size = 300

    body = {
        "size": 0,
        "query": _build_bool_query([], filter_clauses),
        "aggs": {
            "by_region": {
                "terms": {"field": agg_field, "size": agg_size, "missing": "[未知]"},
                "aggs": {
                    "avg_price": {"avg": {"field": "price"}},
                    "min_price": {"min": {"field": "price"}},
                    "max_price": {"max": {"field": "price"}},
                    "count": {"value_count": {"field": "price"}},
                },
            }
        },
    }
    try:
        result = safe_search(es, ALL_INDICES, body)
        buckets = result.get("aggregations", {}).get("by_region", {}).get("buckets", [])
        items = []
        for b in buckets:
            name = b["key"]
            # 给省级数据加 adcode（便于 ECharts 地图匹配）
            adcode = _PROVINCE_ADCODE.get(name) if level == "province" else None
            items.append({
                "name": name,
                "adcode": adcode,
                "value": round(b["avg_price"]["value"], 2) if b["avg_price"]["value"] else 0,
                "count": int(b["count"]["value"] or 0),
                "min": round(b["min_price"]["value"], 2) if b["min_price"]["value"] else 0,
                "max": round(b["max_price"]["value"], 2) if b["max_price"]["value"] else 0,
            })
        # 四川省下钻特殊处理：ES 中 city/county 字段存的是区/县级粒度（未归一），
        # 需要按 doc_count 分桶去重 + 映射到 21 个地市名/区/县全称，与地图 features 对齐。
        # level=city: parent 是省份「四川」；level=county: parent2 是省份「四川」
        is_sichuan = (level == "city" and parent == "四川") or (level == "county" and parent2 == "四川")
        if is_sichuan and items:
            from api.sichuan_city_mapping import SICHUAN_CITY_MAPPING
            if level == "city":
                items = _normalize_sichuan_cities(items, SICHUAN_CITY_MAPPING)
            elif level == "county":
                # parent 是地市名（如「乐山市」）
                items = _normalize_sichuan_counties(items, SICHUAN_CITY_MAPPING, parent)

        # 直辖市下钻特殊处理：重庆 ES 中 city=「重庆」本身（1 个聚合桶），实际区/县在 county 字段。
        # 下钻时按 county 聚合 + 归一匹配 GeoJSON 38 个 feature。
        # 仅对当前有数据的重庆生效；北京/上海/天津 如未来入库，可扩展相同逻辑。
        is_chongqing_city_drill = level == "city" and parent == "重庆"
        if is_chongqing_city_drill and items:
            # 重新按 county 聚合一次，替换 items
            cq_query = _build_bool_query([], [{"term": {"province": "重庆"}}] + filter_clauses[1:])
            cq_body = {
                "size": 0,
                "query": cq_query,
                "aggs": {
                    "by_region": {
                        "terms": {"field": "county", "size": 100, "missing": "[未知]"},
                        "aggs": {
                            "avg_price": {"avg": {"field": "price"}},
                            "min_price": {"min": {"field": "price"}},
                            "max_price": {"max": {"field": "price"}},
                            "count": {"value_count": {"field": "price"}},
                        },
                    }
                },
            }
            try:
                cq_result = es.search(index=ALL_INDICES, body=cq_body)
                cq_buckets = cq_result.get("aggregations", {}).get("by_region", {}).get("buckets", [])
                raw_items = [{
                    "name": b["key"], "adcode": None,
                    "value": round(b["avg_price"]["value"], 2) if b["avg_price"]["value"] else 0,
                    "count": int(b["count"]["value"] or 0),
                    "min": round(b["min_price"]["value"], 2) if b["min_price"]["value"] else 0,
                    "max": round(b["max_price"]["value"], 2) if b["max_price"]["value"] else 0,
                } for b in cq_buckets]
                from api.chongqing_county_mapping import normalize as _normalize_cq
                items = _normalize_cq(raw_items)
            except Exception as _cq_e:
                # 归一失败不要阻断整体响应，回退到原 items
                print(f"[chongqing drill] normalize failed: {_cq_e}")

        # 河南全省指导价：河南 sync.py 把省级单列价格记为 city=「河南」（与 province 同名），
        # 业务上不归属任何地市，地图上不应误着色为某个地市。拆出到 province_wide。
        province_wide = None
        if level == "city" and parent and items:
            wide_idx = next((i for i, it in enumerate(items) if it.get("name") == parent), None)
            if wide_idx is not None:
                w = items.pop(wide_idx)
                province_wide = {
                    "name": parent,
                    "label": f"{parent}省本级指导价",
                    "count": w["count"],
                    "value": w["value"],
                    "min": w["min"],
                    "max": w["max"],
                }

        # 海南特殊处理：海南住建厅发布的 PDF 按「方位」（北部/东部/中部/南部/西部/全省）划分，
        # 不按市县。ES city 字段统一是「海南」，city level 聚合后只有 1 个桶 + 无任何市县项。
        # 改为按 region 字段重新聚合，返回「方位」分布明细，让前端可以展示省级指导价结构。
        if level == "city" and parent == "海南" and not items:
            hn_query = _build_bool_query([], [{"term": {"province": "海南"}}] + filter_clauses[1:])
            hn_body = {
                "size": 0,
                "query": hn_query,
                "aggs": {
                    "by_region": {
                        "terms": {"field": "region.keyword", "size": 30, "missing": "[未知]"},
                        "aggs": {
                            "avg_price": {"avg": {"field": "price"}},
                            "min_price": {"min": {"field": "price"}},
                            "max_price": {"max": {"field": "price"}},
                            "count": {"value_count": {"field": "price"}},
                        },
                    }
                },
            }
            try:
                hn_result = es.search(index=ALL_INDICES, body=hn_body)
                hn_buckets = hn_result.get("aggregations", {}).get("by_region", {}).get("buckets", [])
                # 方位列表（名称加「海南省·方位」以避免与海南地图市县 feature 重名）
                region_items = [{
                    "name": b["key"],
                    "adcode": None,
                    "value": round(b["avg_price"]["value"], 2) if b["avg_price"]["value"] else 0,
                    "count": int(b["count"]["value"] or 0),
                    "min": round(b["min_price"]["value"], 2) if b["min_price"]["value"] else 0,
                    "max": round(b["max_price"]["value"], 2) if b["max_price"]["value"] else 0,
                } for b in hn_buckets]
                total_cnt = sum(it["count"] for it in region_items)
                if total_cnt > 0:
                    avg_val = sum(it["value"] * it["count"] for it in region_items) / total_cnt
                    province_wide = {
                        "name": "海南",
                        "label": "海南省本级指导价（按方位划分）",
                        "count": total_cnt,
                        "value": round(avg_val, 2),
                        "min": min((it["min"] for it in region_items if it["count"] > 0), default=0),
                        "max": max((it["max"] for it in region_items if it["count"] > 0), default=0),
                        "items": region_items,   # 方位列表，供前端展示
                    }
            except Exception as _hn_e:
                print(f"[hainan drill] by-region failed: {_hn_e}")
        return {
            "level": level,
            "parent": parent,
            "parent2": parent2,
            "total": len(items),
            "items": items,
            "province_wide": province_wide,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def _normalize_sichuan_cities(items: list, mapping: dict) -> list:
    """
    四川省 city 归一化：ES 中 city 字段实际存的是区/县级粒度（如「五通」= 乐山市五通桥区），
    同一地市下的不同区/县 doc_count 相同（数据冗余）。按 count 分桶去重，再用 mapping 表把
    代表名归一为地市级（如「乐山市」）。
    """
    import re as _re
    from collections import Counter
    city_set = set(mapping.values())
    city_set |= {"阿坝州", "甘孜州", "凉山州"}

    def _normalize(name: str):
        if name in city_set:
            return name
        if name in mapping:
            return mapping[name]
        m = _re.match(r"^(.+)市区$", name)
        if m and (m.group(1) + "市") in city_set:
            return m.group(1) + "市"
        m = _re.match(r"^(.+?)(北部|南部|东部|西部|其他.+|市区)$", name)
        if m:
            x = m.group(1)
            for k in mapping:
                if k.startswith(x) or x in k:
                    return mapping[k]
            if (x + "市") in city_set:
                return x + "市"
        return None

    # 按 count 分桶（同一地市下不同区/县 doc_count 相同）
    buckets: dict = {}
    for it in items:
        buckets.setdefault(it["count"], []).append(it)

    normalized = []
    for cnt, grp in buckets.items():
        # 找桶里能归一到地市的项
        candidates = []
        for it in grp:
            norm = _normalize(it["name"])
            if norm:
                candidates.append((it, norm))
        if not candidates:
            # 整桶无法归一，跳过（理论上不应该发生）
            continue
        # 选出现次数最多的归一值作为代表
        norm_counter = Counter(n for _, n in candidates)
        rep_name, _ = norm_counter.most_common(1)[0]
        # 聚合桶内统计：avg/min/max 用桶里任一项（值相同），count 用一份（避免重复累加）
        sample = candidates[0][0]
        normalized.append({
            **sample,
            "name": rep_name,
        })
    # 按 count 降序
    normalized.sort(key=lambda x: -x["count"])
    return normalized


def _normalize_sichuan_counties(items: list, mapping: dict, parent_city: str) -> list:
    """
    四川省 county 归一化：ES 中 county 字段存的是区/县简称（如「五通」= 五通桥区），
    与地图 features 全称不匹配。在 parent_city 名下，按 prefix/substring 匹配把简称归一为
    mapping 表里的全称（如「五通桥区」）。
    """
    import re as _re
    from collections import Counter

    # 取该地市下所有 mapping key
    city_counties = [k for k, v in mapping.items() if v == parent_city]
    if not city_counties:
        return items  # 没数据,原样返回

    # 各城市「市区」简称 → 多个中心区（同一 doc_count 重复展开）
    CITY_CENTRAL_DISTRICTS = {
        '成都市': ['锦江区', '金牛区', '武侯区', '成华区', '青羊区'],
        '自贡市': ['自流井区', '贡井区', '大安区', '沿滩区'],
        '攀枝花市': ['东区', '西区', '仁和区'],
        '泸州市': ['江阳区', '纳溪区', '龙马潭区'],
        '德阳市': ['旌阳区'],
        '绵阳市': ['涪城区', '游仙区'],
        '广元市': ['利州区'],
        '遂宁市': ['船山区', '安居区'],
        '内江市': ['市中区'],
        '乐山市': ['市中区'],
        '南充市': ['顺庆区', '高坪区', '嘉陵区'],
        '眉山市': ['东坡区'],
        '宜宾市': ['翠屏区', '南溪区', '叙州区'],
        '广安市': ['广安区', '前锋区'],
        '达州市': ['通川区'],
        '雅安市': ['雨城区'],
        '巴中市': ['巴州区', '恩阳区'],
        '资阳市': ['雁江区'],
    }

    def _expand_one(name: str) -> list:
        """把 county 名归一为全称,特殊处理「X市区」展开为多个中心区。
        返回 1+ 个最终 county 名。
        """
        if not name:
            return [name]
        # 「X市区」模式：展开为该地市多个中心区
        m = _re.match(r"^(.+)市区$", name)
        if m:
            x = m.group(1)  # 如 "成都"
            # dict key 是「X市」形式 ("成都市")，用 x + "市" 查
            central = CITY_CENTRAL_DISTRICTS.get(x + "市", CITY_CENTRAL_DISTRICTS.get(x, []))
            matched = [c for c in central if c in city_counties]
            if matched:
                return matched
            # fallback: 最短的区
            districts = [k for k in city_counties if k.endswith("区")]
            if districts:
                return [min(districts, key=len)]
            return [name]
        if name in city_counties:
            return [name]
        # 「X其他乡镇」模式（如「屏山其他乡镇」→ 屏山县）
        m = _re.match(r"^(.+?)其他乡镇$", name)
        if m:
            x = m.group(1)
            for k in city_counties:
                if k == x + "县" or k == x + "市" or k == x + "区" or k.startswith(x):
                    return [k]
        # 「X北部/南部」模式
        m = _re.match(r"^(.+?)(北部|南部|东部|西部)$", name)
        if m:
            x = m.group(1)
            for k in city_counties:
                if k.startswith(x):
                    return [k]
        # 去后缀(县/区/市)再 prefix 匹配
        base = _re.sub(r'(县|区|市)$', '', name)
        for k in city_counties:
            if k.startswith(name) or (base and k.startswith(base)):
                return [k]
        # 特殊情况: county == parent_city（主城「乐山市」=「市中区」）
        if name == parent_city:
            for k in city_counties:
                if k == "市中区":
                    return [k]
            districts = [k for k in city_counties if k.endswith("区")]
            if districts:
                return [min(districts, key=len)]
        # substring 匹配
        for k in city_counties:
            if name in k or base in k:
                return [k]
        return [name]

    # 按 count 分桶（同地市下不同区/县 doc_count 相同）
    buckets: dict = {}
    for it in items:
        buckets.setdefault(it["count"], []).append(it)

    normalized = []
    for cnt, grp in buckets.items():
        expanded = []
        for it in grp:
            for new_name in _expand_one(it["name"]):
                expanded.append({**it, "name": new_name})
        # 去重
        seen = set()
        deduped = []
        for it in expanded:
            if it["name"] not in seen:
                seen.add(it["name"])
                deduped.append(it)
        normalized.extend(deduped)

    # 按 count 降序
    normalized.sort(key=lambda x: -x["count"])
    return normalized


@app.get("/api/stats/geo-regions")
def geo_regions():
    """
    返回所有有数据的省份/城市/区县列表（地图下钻决策用）
    让前端知道哪些省份/城市有数据，避免空白下钻
    """
    try:
        body = {
            "size": 0,
            "aggs": {
                "provinces": {
                    "terms": {"field": "province", "size": 50},
                    "aggs": {
                        "cities": {
                            "terms": {"field": "city", "size": 50},
                            "aggs": {
                                "counties": {
                                    "terms": {"field": "county", "size": 50}
                                }
                            }
                        }
                    }
                }
            }
        }
        result = safe_search(es, ALL_INDICES, body)
        prov_buckets = result.get("aggregations", {}).get("provinces", {}).get("buckets", [])
        provinces = []
        for pb in prov_buckets:
            cities = []
            for cb in pb["cities"]["buckets"]:
                counties = [c["key"] for c in cb["counties"]["buckets"] if c["key"] and c["key"] != "[未知]"]
                cities.append({
                    "name": cb["key"],
                    "count": int(cb["doc_count"]),
                    "counties": counties,
                })
            provinces.append({
                "name": pb["key"],
                "adcode": _PROVINCE_ADCODE.get(pb["key"]),
                "count": int(pb["doc_count"]),
                "cities": cities,
            })
        return {"provinces": provinces}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============ 前端静态服务（Docker 部署）============
# Dockerfile 构建时 COPY frontend/dist → /app/static
# 仅当 /app/static 存在时挂载（开发环境没 dist 也不报错）
import os as _os
from fastapi.staticfiles import StaticFiles as _StaticFiles
from fastapi.responses import FileResponse as _FileResponse
from fastapi import HTTPException as _HTTPException

_STATIC_DIR = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "..", "static")
_STATIC_DIR = _os.path.normpath(_STATIC_DIR)

if _os.path.isdir(_STATIC_DIR):
    # 1) 静态资源（/assets/* → /app/static/assets/*）
    _assets_dir = _os.path.join(_STATIC_DIR, "assets")
    if _os.path.isdir(_assets_dir):
        app.mount("/assets", _StaticFiles(directory=_assets_dir), name="assets")

    # 2) /healthz 健康检查(Docker healthcheck 用)
    #    2026-07-19 迁出 /api/* 以合规:所有 /api/* 必须鉴权
    @app.get("/healthz", include_in_schema=False)
    async def _health():
        return {"ok": True, "service": "gov-price-dashboard"}

    # 3) SPA fallback（Vue Router history 模式）
    #    非 /api/* 请求全部返回 index.html，路由由前端处理
    @app.get("/{full_path:path}", include_in_schema=False)
    async def _spa_fallback(full_path: str):
        # 不拦 /api（已被上面 router 处理，这里仅作为 catch-all）
        if full_path.startswith("api/"):
            raise _HTTPException(status_code=404, detail="API not found")

        # 静态文件（favicon.ico 等）直接返回
        file_path = _os.path.join(_STATIC_DIR, full_path)
        if _os.path.isfile(file_path):
            # /assets/* 走永久缓存（vite 自带 hash 文件名, 文件名变了才重新下载）
            # 其他静态文件 (favicon.ico, geo/, img/) 用 1h 缓存
            if full_path.startswith("assets/"):
                return _FileResponse(file_path, headers={"Cache-Control": "public, max-age=31536000, immutable"})
            return _FileResponse(file_path, headers={"Cache-Control": "public, max-age=3600"})

        # SPA fallback: index.html 永远 no-cache, 浏览器每次重新校验
        # 配合 vite hash 文件名, 部署新版本用户立即看到
        index_path = _os.path.join(_STATIC_DIR, "index.html")
        if _os.path.isfile(index_path):
            return _FileResponse(
                index_path,
                headers={
                    "Cache-Control": "no-cache, no-store, must-revalidate",
                    "Pragma": "no-cache",
                    "Expires": "0",
                },
            )
        raise _HTTPException(status_code=404, detail="index.html not found")
        index_path = _os.path.join(_STATIC_DIR, "index.html")
        if _os.path.isfile(index_path):
            return _FileResponse(index_path)

        raise _HTTPException(status_code=404, detail="Frontend not built")
else:
    # 开发环境没 dist 时，只暴露 /healthz
    @app.get("/healthz", include_in_schema=False)
    async def _health():
        return {"ok": True, "service": "gov-price-dashboard", "frontend": "not_built"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=5200)


# ============================================================


# ── 归一申请（fix 2026-07-12：趋势页一键申请归一）────────────
@app.post("/api/stats/norm-request")
def norm_request(req: dict = Body(...)):
    """记录用户提交的归一申请。
    落地路径：写入 workspace/scripts/norm_requests.log，便于离线批处理。
    重复提交去重（同品种 24h 内不重复记录）。
    """
    breed = (req.get("breed") or "").strip()
    if not breed:
        raise HTTPException(status_code=400, detail="breed 必填")

    import os
    from pathlib import Path
    log_path = Path.home() / ".openclaw" / "workspace" / "scripts" / "norm_requests.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)

    # 24h 内去重
    now = datetime.now()
    if log_path.exists():
        with open(log_path) as f:
            for line in f.readlines()[-50:]:  # 只看最近 50 行
                parts = line.strip().split("\t")
                if len(parts) >= 2 and parts[1] == breed:
                    try:
                        last_ts = datetime.fromisoformat(parts[0])
                        if (now - last_ts).total_seconds() < 86400:
                            return {"ok": True, "duplicate": True, "breed": breed}
                    except Exception:
                        pass

    with open(log_path, "a") as f:
        f.write(f"{now.isoformat()}\t{breed}\tuser_requested\n")
    return {"ok": True, "breed": breed, "logged": str(log_path)}
