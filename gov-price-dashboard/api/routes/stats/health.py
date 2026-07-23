"""Phase 4 抽取: /api/stats/data-health (原 main.py 内联实现)"""
from fastapi import APIRouter, Query, HTTPException
from typing import Optional

from api.dependencies import es, ALL_ODS_INDICES
from api.skill_registry import get_all as _registry_get_all

router = APIRouter()

@router.get("/api/stats/data-health")
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

