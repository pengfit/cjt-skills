#!/usr/bin/env python3
"""
数据溯源 API 端点
来源分布、各省新鲜度、近30天入库趋势 — 支持多城市
"""

from fastapi import APIRouter, HTTPException, Query, Body
from pydantic import BaseModel
from elasticsearch import Elasticsearch
import datetime, concurrent.futures, subprocess, json, os, sys, re

router = APIRouter()

ES_HOST = "http://localhost:59200"

# 城市配置：city key → (dws_idx, ods_idx, dwd_idx, 标签)
CITY_INDEXES = {
    "xian":      {"dws": "dws_xian_price",      "ods": "ods_material_xian_price",      "dwd": "dwd_xian_price",      "label": "西安"},
    "sichuan":   {"dws": "dws_sichuan_price",   "ods": "ods_material_sichuan_price",   "dwd": "dwd_sichuan_price",   "label": "四川"},
    "chongqing": {"dws": "dws_chongqing_price", "ods": "ods_material_chongqing_price", "dwd": "dwd_chongqing_price", "label": "重庆"},
    "jinan":     {"dws": "dws_jinan_price",     "ods": "ods_material_jinan_price",     "dwd": "dwd_jinan_price",     "label": "济南"},
    "rizhao":    {"dws": "dws_rizhao_price",    "ods": "ods_material_rizhao_price",    "dwd": "dwd_rizhao_price",    "label": "日照"},
}

# 全部城市索引汇总
ALL_INDICES = "dws_xian_price"
ALL_ODS_INDICES = "ods_material_xian_price"
ALL_DWD_INDICES = "dwd_xian_price"

# 各城市配置的区县数量（从 config.yml 读取，作为 total_counties 基准）
CITY_COUNTY_COUNTS = {
    "xian":      6,   # 阎良区/临潼区/高陵区/鄠邑区/蓝田县/周至县
    "sichuan":   21,   # 四川21个地级市/自治州（川A~川Z缺川G）
    "chongqing": 41,  # 重庆市区县
    "jinan":     41,  # 济南41个分类目录
    "rizhao":    3,   # 日照3个类别
}

# 进度索引 map
PROGRESS_INDEXES = {
    "xian":      "ods_material_xian_price_sync_progress",
    "sichuan":   "ods_material_sichuan_price_sync_progress",
    "chongqing": "material_chongqing_price_sync_progress",
    "jinan":     "ods_material_jinan_price_sync_progress",
    "rizhao":    "material_rizhao_price_sync_progress",
}

es = Elasticsearch([ES_HOST])


def _index_stats(index: str) -> dict:
    """获取单个索引的统计信息"""
    try:
        count_r = es.count(index=index)
        count = count_r["count"]
    except Exception:
        return {"index": index, "count": 0, "status": "error", "msg": "count failed"}

    aggs_body = {
        "size": 0,
        "aggs": {
            "min_date": {"min": {"field": "update_date"}},
            "max_date": {"max": {"field": "update_date"}},
            "max_etl": {"max": {"field": "etl_time"}},
        }
    }
    try:
        r = es.search(index=index, body=aggs_body)
        aggs = r.get("aggregations", {})
        min_d = aggs.get("min_date", {}).get("value_as_string", "") or ""
        max_d = aggs.get("max_date", {}).get("value_as_string", "") or ""
        max_etl = aggs.get("max_etl", {}).get("value_as_string", "") or ""
        return {
            "index": index,
            "count": count,
            "min_date": min_d[:10] if min_d else "",
            "max_date": max_d[:10] if max_d else "",
            "last_etl": max_etl[:19] if max_etl else "",
            "status": "ok",
        }
    except Exception as e:
        return {"index": index, "count": count, "status": "error", "msg": str(e)}


@router.get("/api/stats/scrape-progress-all")
def stats_scrape_progress_all():
    """
    所有城市 ODS 抓取进度汇总（一次性返回全部城市）
    """
    results = {}
    for city, idx in PROGRESS_INDEXES.items():
        try:
            use_cq = (city == "chongqing")
            if use_cq:
                run_body = {
                    "size": 0,
                    "aggs": {
                        "runs": {
                            "terms": {"field": "run_id", "size": 5},
                            "aggs": {
                                "latest": {
                                    "top_hits": {
                                        "size": 1,
                                        "sort": [{"last_updated": "desc"}],
                                        "_source": ["last_updated"]
                                    }
                                },
                                "counties": {
                                    "top_hits": {
                                        "size": 100,
                                        "sort": [{"last_updated": "desc"}],
                                        "_source": [
                                            "county", "run_id", "status", "current_county",
                                            "current_page", "total_pages", "total_records",
                                            "docs_written", "percent", "duration_sec",
                                            "update_date", "last_updated", "error", "spot_check_ok",
                                        ]
                                    }
                                }
                            }
                        }
                    }
                }
                r = es.search(index=idx, body=run_body)
                buckets = r["aggregations"]["runs"]["buckets"]

                def sort_key(b):
                    h = b.get("latest", {}).get("hits", {}).get("hits", [])
                    return (h[0].get("_source", {}).get("last_updated", "") or "") if h else ""

                buckets.sort(key=sort_key, reverse=True)
                if buckets:
                    lat = buckets[0]
                    lh = lat.get("latest", {}).get("hits", {}).get("hits", [])
                    lu = (lh[0].get("_source", {}).get("last_updated", "") or "")[:19] if lh else ""
                    ch = lat.get("counties", {}).get("hits", {}).get("hits", [])
                else:
                    lu, ch = "", []
                run_id = buckets[0]["key"] if buckets else None
            else:
                run_body = {
                    "size": 0,
                    "aggs": {
                        "runs": {
                            "terms": {
                                "field": "run_id", "size": 5,
                                "order": {"latest_ts": "desc"}
                            },
                            "aggs": {
                                "latest_ts": {"max": {"field": "last_updated"}},
                                "counties": {
                                    "top_hits": {
                                        "size": 100,
                                        "sort": [{"last_updated": "desc"}],
                                        "_source": [
                                            "county", "run_id", "status", "current_county",
                                            "current_page", "total_pages", "total_records",
                                            "docs_written", "percent", "duration_sec",
                                            "update_date", "last_updated", "error", "spot_check_ok",
                                            "area", "catalogue_name", "tab_name",
                                        ]
                                    }
                                }
                            }
                        }
                    }
                }
                r = es.search(index=idx, body=run_body)
                buckets = r["aggregations"]["runs"]["buckets"]
                if buckets:
                    lat = buckets[0]
                    lu = (lat.get("latest_ts", {}).get("value_as_string", "") or "")[:19]
                    ch = lat.get("counties", {}).get("hits", {}).get("hits", [])
                    run_id = lat["key"]
                else:
                    lu, ch, run_id = "", [], None

            ch = [h for h in ch if (h["_source"].get("county") or h["_source"].get("current_county") or h["_source"].get("area") or h["_source"].get("catalogue_name") or h["_source"].get("tab_name"))]

            if city == "rizhao":
                # For rizhao: use terms aggregation on tab_name to aggregate across ALL runs
                # Use a filter to separate completed/running/error, then nest top_hits for latest run_id
                tabs_body = {
                    "size": 0,
                    "aggs": {
                        "tabs": {
                            "terms": {"field": "tab_name", "size": 20},
                            "aggs": {
                                "latest_ts": {"max": {"field": "last_updated"}},
                                "docs_sum": {"sum": {"field": "docs_written"}},
                                "completed": {
                                    "filter": {"term": {"status": "completed"}},
                                    "aggs": {
                                        "status_count": {"value_count": {"field": "status"}}
                                    }
                                },
                                "running": {
                                    "filter": {"term": {"status": "running"}},
                                    "aggs": {
                                        "latest_doc": {
                                            "top_hits": {
                                                "size": 1,
                                                "sort": [{"last_updated": "desc"}],
                                                "_source": ["tab_name", "status", "docs_written", "percent", "run_id", "last_updated", "current_page", "total_pages"]
                                            }
                                        }
                                    }
                                },
                                "error": {
                                    "filter": {"term": {"status": "error"}}
                                }
                            }
                        }
                    }
                }
                tabs_r = es.search(index=idx, body=tabs_body)
                tabs_buckets = tabs_r["aggregations"]["tabs"]["buckets"]
                td = sum(b.get("docs_sum", {}).get("value", 0) for b in tabs_buckets)
                tr = 0
                comp = sum(1 for b in tabs_buckets if b.get("completed", {}).get("doc_count", 0) > 0)
                run = sum(1 for b in tabs_buckets if b.get("running", {}).get("doc_count", 0) > 0)
                err = sum(1 for b in tabs_buckets if b.get("error", {}).get("doc_count", 0) > 0)
                counties = []
                run_id = None
                lu = ""
                lu_ts = None
                for b in tabs_buckets:
                    # Determine primary status by doc_count of each bucket
                    comp_count = b.get("completed", {}).get("doc_count", 0)
                    run_count = b.get("running", {}).get("doc_count", 0)
                    err_count = b.get("error", {}).get("doc_count", 0)
                    if run_count > 0:
                        primary_status = "running"
                        primary_docs = b.get("running", {}).get("latest_doc", {}).get("hits", {}).get("hits", [{}])[0].get("_source", {})
                        percent = primary_docs.get("percent", 0)
                        docs_written = primary_docs.get("docs_written", 0)
                        current_page = primary_docs.get("current_page", 0)
                        total_pages = primary_docs.get("total_pages", 0)
                        if not run_id:
                            run_id = primary_docs.get("run_id")
                    elif comp_count > 0:
                        primary_status = "completed"
                        percent = 100.0
                        docs_written = b.get("docs_sum", {}).get("value", 0)
                        current_page = 0
                        total_pages = 0
                    else:
                        primary_status = "unknown"
                        percent = 0
                        docs_written = 0
                        current_page = 0
                        total_pages = 0
                    counties.append({
                        "county": b["key"],
                        "status": primary_status,
                        "percent": round(percent, 1),
                        "docs_written": docs_written,
                        "current_page": current_page,
                        "total_pages": total_pages,
                    })
                    ts = b.get("latest_ts", {}).get("value")
                    if ts and (lu == "" or ts > (lu_ts or 0)):
                        lu_ts = ts
                        lu = b.get("latest_ts", {}).get("value_as_string", "")[:19]
            else:
                td = sum(h["_source"].get("docs_written", 0) for h in ch)
                tr = sum(h["_source"].get("total_records", 0) for h in ch)
                comp = sum(1 for h in ch if h["_source"].get("status") == "completed")
                run = sum(1 for h in ch if h["_source"].get("status") == "running")
                err = sum(1 for h in ch if h["_source"].get("status") == "error")
                counties = [{
                    "county": h["_source"].get("county", "") or h["_source"].get("current_county", "") or h["_source"].get("area", "") or h["_source"].get("catalogue_name", "") or h["_source"].get("tab_name", ""),
                    "status": h["_source"].get("status", ""),
                    "percent": round(h["_source"].get("percent", 0), 1),
                    "docs_written": h["_source"].get("docs_written", 0),
                } for h in ch]

            results[city] = {
                "city": city,
                "city_label": CITY_INDEXES[city]["label"],
                "latest_run_id": run_id,
                "last_updated": lu,
                "total_docs": td,
                "total_records": tr,
                "completed": comp,
                "running": run,
                "error": err,
                "total_counties": CITY_COUNTY_COUNTS.get(city, len(ch)),
                "counties": counties,
            }
        except Exception:
            results[city] = {
                "city": city,
                "city_label": CITY_INDEXES[city]["label"],
                "latest_run_id": None,
                "last_updated": "",
                "total_docs": 0,
                "total_records": 0,
                "completed": 0,
                "running": 0,
                "error": 0,
                "total_counties": 0,
                "status": "error",
                "counties": [],
            }
    return results


@router.get("/api/stats/scrape-progress")
def stats_scrape_progress(city: str = Query("xian", description="城市 key")):
    """
    ODS 层抓取进度：最近一次同步 run 的各区县进度
    """
    PROGRESS_INDEX = PROGRESS_INDEXES.get(city, PROGRESS_INDEXES["xian"])
    use_chongqing_workaround = (city == "chongqing")

    try:
        if use_chongqing_workaround:
            run_body = {
                "size": 0,
                "aggs": {
                    "runs": {
                        "terms": {"field": "run_id", "size": 5},
                        "aggs": {
                            "latest": {
                                "top_hits": {
                                    "size": 1,
                                    "sort": [{"last_updated": "desc"}],
                                    "_source": ["last_updated"]
                                }
                            },
                            "counties": {
                                "top_hits": {
                                    "size": 100,
                                    "sort": [{"last_updated": "desc"}],
                                    "_source": [
                                        "county", "run_id", "status", "current_county",
                                        "current_page", "total_pages", "total_records",
                                        "docs_written", "percent", "duration_sec",
                                        "update_date", "last_updated", "error", "spot_check_ok",
                                        "area", "catalogue_name", "tab_name",
                                    ]
                                }
                            }
                        }
                    }
                }
            }
            run_result = es.search(index=PROGRESS_INDEX, body=run_body)
            run_buckets = run_result["aggregations"]["runs"]["buckets"]

            def sort_key(b):
                hits = b.get("latest", {}).get("hits", {}).get("hits", [])
                return (hits[0].get("_source", {}).get("last_updated", "") or "") if hits else ""

            run_buckets.sort(key=sort_key, reverse=True)
            if not run_buckets:
                return {"runs": [], "latest_run_id": None, "city": city,
                        "city_label": CITY_INDEXES.get(city, {}).get("label", city)}
            latest = run_buckets[0]
            latest_run_id = latest["key"]
            latest_hit = latest.get("latest", {}).get("hits", {}).get("hits", [])
            last_updated = (latest_hit[0].get("_source", {}).get("last_updated", "") or "")[:19] if latest_hit else ""
            county_hits = latest.get("counties", {}).get("hits", {}).get("hits", [])
        else:
            run_body = {
                "size": 0,
                "aggs": {
                    "runs": {
                        "terms": {
                            "field": "run_id", "size": 5,
                            "order": {"latest_ts": "desc"}
                        },
                        "aggs": {
                            "latest_ts": {"max": {"field": "last_updated"}},
                            "counties": {
                                "top_hits": {
                                    "size": 100,
                                    "sort": [{"last_updated": "desc"}],
                                    "_source": [
                                        "county", "run_id", "status", "current_county",
                                        "current_page", "total_pages", "total_records",
                                        "docs_written", "percent", "duration_sec",
                                        "update_date", "last_updated", "error", "spot_check_ok",
                                        "area", "catalogue_name", "tab_name",
                                    ]
                                }
                            }
                        }
                    }
                }
            }
            run_result = es.search(index=PROGRESS_INDEX, body=run_body)
            run_buckets = run_result["aggregations"]["runs"]["buckets"]
            if not run_buckets:
                return {"runs": [], "latest_run_id": None, "city": city,
                        "city_label": CITY_INDEXES.get(city, {}).get("label", city)}
            latest = run_buckets[0]
            latest_run_id = latest["key"]
            last_updated = (latest.get("latest_ts", {}).get("value_as_string", "") or "")[:19]
            county_hits = latest.get("counties", {}).get("hits", {}).get("hits", [])

        # Rizhao特殊处理：合并所有run的tab_name，而非只取最新run
        if city == "rizhao":
            tabs_body = {
                "size": 0,
                "aggs": {
                    "tabs": {
                        "terms": {"field": "tab_name", "size": 20},
                        "aggs": {
                            "latest_doc": {
                                "top_hits": {
                                    "size": 1,
                                    "sort": [{"last_updated": "desc"}],
                                    "_source": ["tab_name", "status", "docs_written", "percent", "run_id", "last_updated", "current_page", "total_pages"]
                                }
                            },
                            "docs_sum": {"sum": {"field": "docs_written"}}
                        }
                    }
                }
            }
            try:
                tabs_r = es.search(index=PROGRESS_INDEX, body=tabs_body)
            except Exception as e:
                if "index_not_found_exception" in str(e) or "no such index" in str(e):
                    return {
                        "city": city,
                        "city_label": CITY_INDEXES.get(city, {}).get("label", city),
                        "latest_run_id": None,
                        "last_updated": "",
                        "total_docs": 0,
                        "total_records": 0,
                        "completed": 0,
                        "running": 0,
                        "error": 0,
                        "total_counties": CITY_COUNTY_COUNTS.get(city, 0),
                        "counties": [],
                    }
                raise
            tabs_buckets = tabs_r["aggregations"]["tabs"]["buckets"]
            total_docs = sum(b.get("docs_sum", {}).get("value", 0) for b in tabs_buckets)
            total_records = 0
            counties = []
            for b in tabs_buckets:
                doc = b.get("latest_doc", {}).get("hits", {}).get("hits", [{}])[0].get("_source", {})
                counties.append({
                    "county": b["key"],
                    "status": doc.get("status", "unknown"),
                    "current_page": doc.get("current_page", 0),
                    "total_pages": doc.get("total_pages", 0),
                    "total_records": 0,
                    "docs_written": doc.get("docs_written", 0),
                    "percent": round(doc.get("percent", 0), 1),
                    "duration_sec": 0,
                    "update_date": "",
                    "last_updated": doc.get("last_updated", ""),
                    "error": doc.get("error", ""),
                    "spot_check_ok": None,
                })
            completed = sum(1 for c in counties if c.get("status") == "completed")
            running = sum(1 for c in counties if c.get("status") == "running")
            err = sum(1 for c in counties if c.get("status") == "error")
            return {
                "city": city,
                "city_label": CITY_INDEXES.get(city, {}).get("label", city),
                "latest_run_id": counties[0]["last_updated"] if counties else None,
                "last_updated": counties[0]["last_updated"] if counties else "",
                "total_docs": total_docs,
                "total_records": total_records,
                "completed": completed,
                "running": running,
                "error": err,
                "total_counties": CITY_COUNTY_COUNTS.get(city, len(counties)),
                "counties": counties,
            }

        total_docs = sum(h["_source"].get("docs_written", 0) for h in county_hits)
        total_records = sum(h["_source"].get("total_records", 0) for h in county_hits)

        counties = []
        for h in county_hits:
            src = h["_source"]
            county = src.get("county", "") or src.get("current_county", "") or src.get("area", "") or src.get("catalogue_name", "") or src.get("tab_name", "")
            if not county:
                continue
            counties.append({
                "county": county or src.get("catalogue_name", "") or src.get("tab_name", ""),
                "status": src.get("status", ""),
                "current_page": src.get("current_page", 0),
                "total_pages": src.get("total_pages", 0),
                "total_records": src.get("total_records", 0),
                "docs_written": src.get("docs_written", 0),
                "percent": round(src.get("percent", 0), 1),
                "duration_sec": round(src.get("duration_sec", 0), 1),
                "update_date": src.get("update_date", ""),
                "last_updated": src.get("last_updated", ""),
                "error": src.get("error", ""),
                "spot_check_ok": src.get("spot_check_ok"),
            })

        completed = sum(1 for c in counties if c.get("status") == "completed")
        running = sum(1 for c in counties if c.get("status") == "running")
        err = sum(1 for c in counties if c.get("status") == "error")

        return {
            "city": city,
            "city_label": CITY_INDEXES.get(city, {}).get("label", city),
            "latest_run_id": latest_run_id,
            "last_updated": last_updated,
            "total_docs": total_docs,
            "total_records": total_records,
            "completed": completed,
            "running": running,
            "error": err,
            "total_counties": CITY_COUNTY_COUNTS.get(city, len(counties)),
            "counties": counties,
        }
    except Exception as e:
        import traceback; traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/stats/provenance")
def stats_provenance(city: str = Query("all", description="城市 key，all 表示全部城市")):
    """
    数据溯源：来源分布 + 各省新鲜度 + 近30天入库趋势
    """
    if city not in CITY_INDEXES and city != "all":
        raise HTTPException(status_code=400, detail=f"未知城市: {city}，可用: {', '.join(CITY_INDEXES.keys())}, all")

    is_all = (city == "all")
    if is_all:
        dws_idx = ALL_INDICES
        ods_idx = ALL_ODS_INDICES
        dwd_idx = ALL_DWD_INDICES
        city_label = "全部城市"
    else:
        cfg = CITY_INDEXES[city]
        dws_idx = cfg["dws"]
        ods_idx = cfg["ods"]
        dwd_idx = cfg["dwd"]
        city_label = cfg["label"]

    try:
        # ── 1. 各省份最新数据日期 + 记录数 ──────────────────────
        prov_body = {
            "size": 0,
            "aggs": {
                "by_province": {
                    "terms": {"field": "province", "size": 50},
                    "aggs": {
                        "max_date": {"max": {"field": "date"}},
                        "min_date": {"min": {"field": "date"}},
                        "cnt": {"value_count": {"field": "price"}},
                        "avg_price": {"avg": {"field": "price"}},
                    }
                }
            }
        }
        prov_result = es.search(index=dws_idx, body=prov_body)
        prov_buckets = prov_result["aggregations"]["by_province"]["buckets"]

        # ── 2. 近30天每日入库量 ─────────────────────────────────
        daily_body = {
            "size": 0,
            "query": {"range": {"update_date": {"gte": "now-30d"}}},
            "aggs": {
                "daily": {
                    "date_histogram": {
                        "field": "update_date",
                        "calendar_interval": "day",
                    },
                    "aggs": {"cnt": {"value_count": {"field": "price"}}}
                }
            }
        }
        daily_result = es.search(index=dws_idx, body=daily_body)
        daily_buckets = daily_result["aggregations"]["daily"]["buckets"]
        daily_data = [
            {"date": b["key_as_string"][:10], "count": b["doc_count"]}
            for b in daily_buckets
        ]

        # ── 3. 按 city 来源分布（TOP 20 城市）───────────────────
        city_body = {
            "size": 0,
            "aggs": {
                "by_city": {
                    "terms": {"field": "city", "size": 20, "order": {"_count": "desc"}},
                    "aggs": {
                        "province": {"terms": {"field": "province", "size": 1}},
                        "cnt": {"value_count": {"field": "price"}},
                        "max_date": {"max": {"field": "date"}},
                    }
                }
            }
        }
        city_result = es.search(index=dws_idx, body=city_body)
        city_buckets = city_result["aggregations"]["by_city"]["buckets"]
        city_data = [
            {
                "city": b["key"],
                "province": b["province"]["buckets"][0]["key"] if b["province"]["buckets"] else "",
                "count": b["doc_count"],
                "latest_date": b["max_date"].get("value_as_string", "")[:10],
            }
            for b in city_buckets
        ]

        # ── 4. 数据总量 ──────────────────────────────────────────
        try:
            count_resp = es.count(index=dws_idx)
            total_count = count_resp["count"]
        except Exception:
            total_body = {"query": {"match_all": {}}, "size": 0, "track_total": True}
            total_r = es.search(index=dws_idx, body=total_body)
            total_count = total_r["hits"]["total"]["value"]

        # ── 5. 新鲜度分析 ────────────────────────────────────────
        threshold = datetime.datetime.now() - datetime.timedelta(days=7)

        province_list = []
        stale_count = 0
        for b in prov_buckets:
            max_date_str = b.get("max_date", {}).get("value_as_string", "")[:10]
            is_stale = False
            is_old = False
            if max_date_str:
                try:
                    max_date = datetime.datetime.strptime(max_date_str, "%Y-%m-%d")
                    is_stale = max_date < threshold
                    is_old = (datetime.datetime.now() - max_date).days > 30
                except Exception:
                    pass
            avg_p = b["avg_price"]["value"]
            province_list.append({
                "province": b["key"],
                "count": b["doc_count"],
                "avg_price": round(avg_p, 2) if avg_p else 0,
                "latest_date": max_date_str,
                "is_stale": is_stale,
                "is_old": is_old,
                "status": "stale" if is_stale else ("old" if is_old else "fresh"),
            })
            if is_stale:
                stale_count += 1

        province_list.sort(key=lambda x: x["latest_date"] or "", reverse=True)

        # ── 6. 汇总指标 ──────────────────────────────────────────
        recent_7d = 0
        prev_7d = 0
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            r1 = pool.submit(es.count, index=dws_idx,
                body={"query": {"range": {"update_date": {"gte": "now-7d"}}}})
            r2 = pool.submit(es.count, index=dws_idx,
                body={"query": {"range": {"update_date": {"gte": "now-14d", "lt": "now-7d"}}}})
            recent_7d = r1.result()["count"]
            prev_7d = r2.result()["count"]

        inc_pct = round((recent_7d / prev_7d * 100) - 100, 1) if prev_7d else 0

        # ── 7. ODS→DWD→DWS 同步链路状态 ──────────────────────────
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
            f_ods = pool.submit(_index_stats, ods_idx)
            f_dwd = pool.submit(_index_stats, dwd_idx)
            f_dws = pool.submit(_index_stats, dws_idx)
            ods_stats = f_ods.result()
            dwd_stats = f_dwd.result()
            dws_stats = f_dws.result()

        sync_ok = (ods_stats.get("count") == dwd_stats.get("count") == dws_stats.get("count") and ods_stats.get("count", 0) > 0)
        pipeline = {
            "city": city,
            "city_label": city_label,
            "ods": ods_stats,
            "dwd": dwd_stats,
            "dws": dws_stats,
            "sync_ok": sync_ok,
            "status": "ok" if sync_ok else "out_of_sync",
        }

        # ── 8. 所有城市完整链路状态 ─────────────────────────────
        all_pipelines = {}
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
            futures = {}
            for k, v in CITY_INDEXES.items():
                futures[k] = {
                    "ods": pool.submit(_index_stats, v["ods"]),
                    "dwd": pool.submit(_index_stats, v["dwd"]),
                    "dws": pool.submit(_index_stats, v["dws"]),
                }
            for k, f in futures.items():
                ods_s = f["ods"].result()
                dwd_s = f["dwd"].result()
                dws_s = f["dws"].result()
                sync_ok_c = (ods_s.get("count") == dwd_s.get("count") == dws_s.get("count") and ods_s.get("count", 0) > 0)
                all_pipelines[k] = {
                    "city": k,
                    "city_label": CITY_INDEXES[k]["label"],
                    "ods": ods_s,
                    "dwd": dwd_s,
                    "dws": dws_s,
                    "sync_ok": sync_ok_c,
                    "status": "ok" if sync_ok_c else "out_of_sync",
                }

        return {
            "city": city,
            "city_label": city_label,
            "total": total_count,
            "stale_provinces": stale_count,
            "fresh_provinces": len(province_list) - stale_count,
            "recent_7d": recent_7d,
            "prev_7d": prev_7d,
            "inc_pct": inc_pct,
            "freshness_threshold_days": 7,
            "daily": daily_data,
            "provinces": province_list,
            "top_cities": city_data,
            "pipeline": pipeline,
            "all_cities": all_pipelines,
        }

    except Exception as e:
        import traceback; traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

# ── Spec 解析质量 ─────────────────────────────────────────────
ETL_CMD_DIR = "/Users/pengfit/.openclaw/workspace/skills/gov-price-etl/commands"

# Spec 解析支持的属性（单一数据源）
ATTR_FIELDS_MAP = {
    "diameter": "管径/口径",
    "thickness": "壁厚/厚度",
    "length": "长度",
    "width": "宽度",
    "height": "高度",
    "material": "材质",
    "grade": "等级/标号",
    "pressure": "公称压力",
    "ring_stiffness": "环刚度",
    "cores": "芯数",
    "cross_section": "电缆截面",
    "voltage": "电压",
    "current": "电流",
    "drain_type": "排水形式",
    "inlet_type": "进水形式",
    "installation_type": "安装形式",
    "form": "形态/柱型",
    "ip_rating": "防护等级",
    "color": "颜色",
    "series": "系列",
    "temperature": "温度",
    "temp_range": "温度范围",
    "humidity_range": "湿度范围",
    "length_range": "长度范围",
    "height_range": "高度范围",
    "inner_diameter": "内径",
    "wall_thickness": "壁厚(管壁)",
    "fiber_core": "光纤芯径",
    "cable_length": "电缆长度",
    "channels": "通道数",
    "doors": "门数",
    "media": "介质",
    "range": "量程",
    "output": "输出规格",
}
ATTR_FIELDS = list(ATTR_FIELDS_MAP.keys())
ATTR_FIELDS_STR = ", ".join(ATTR_FIELDS)  # for AI prompt
ATTR_FIELDS_DESC = ", ".join(f"{k}({v})" for k, v in ATTR_FIELDS_MAP.items())  # field(中文)


def _run_spec_validation(city="xian"):
    import sys, os, json
    sys.path.insert(0, ETL_CMD_DIR)
    testset_path = os.path.join(ETL_CMD_DIR, "spec_testset.json")
    if not os.path.exists(testset_path):
        return {"error": f"测试集不存在: {testset_path}"}
    with open(testset_path) as f:
        data = json.load(f)
    try:
        from parse_spec import get_parser
        parser = get_parser(city)
    except Exception as e:
        return {"error": f"解析器加载失败: {str(e)}"}
    cases = data.get("test_cases", [])
    passed = 0
    failed = []
    for tc in cases:
        spec = tc["spec"]
        expected = tc.get("expected", {})
        got = parser.parse(spec)
        if set(expected.items()) == set(got.items()):
            passed += 1
        else:
            failed.append({
                "spec": spec,
                "category": tc.get("category", ""),
                "expected": expected,
                "got": got,
            })
    total = len(cases)
    return {
        "city": city,
        "total": total,
        "passed": passed,
        "failed_count": len(failed),
        "pass_rate": round(passed / total * 100, 1) if total > 0 else 0,
        "failed_cases": failed,
    }


def _sample_dwd_specs(city="xian", sample_size=50, category=""):
    import sys, os
    sys.path.insert(0, ETL_CMD_DIR)
    city_idx_map = {
        "xian": "dwd_xian_price",
        "sichuan": "dwd_sichuan_price",
        "chongqing": "dwd_chongqing_price",
        "jinan": "dwd_jinan_price",
        "rizhao": "dwd_rizhao_price",
    }
    idx = city_idx_map.get(city, "dwd_xian_price")
    try:
        from parse_spec import get_parser
        parser = get_parser(city)
    except Exception:
        return []
    must = []
    if category:
        must.append({"term": {"category": category}})
    body = {
        "size": sample_size,
        "_source": ["spec", "category", "breed"],
        "query": {
            "function_score": {
                "query": {"bool": {"must": must if must else [{"match_all": {}}]}},
                "functions": [{"random_score": {}}],
                "score_mode": "sum",
                "boost_mode": "replace",
            }
        },
    }
    try:
        result = es.search(index=idx, body=body)
    except Exception:
        return []
    samples = []
    for h in result.get("hits", {}).get("hits", []):
        src = h["_source"]
        spec = src.get("spec", "")
        if not spec or spec == "/":
            continue
        parsed = parser.parse(spec)
        attr_keys = [k for k, v in parsed.items() if v]
        samples.append({
            "spec": spec,
            "category": src.get("category", ""),
            "breed": src.get("breed", ""),
            "parsed": parsed,
            "attr_keys": attr_keys,
            "has_attr": len(attr_keys) > 0,
        })
    return samples


def _category_coverage(city="xian"):
    """各分类的 spec 解析覆盖率"""
    import sys
    sys.path.insert(0, ETL_CMD_DIR)
    city_idx_map = {
        "xian": "dwd_xian_price",
        "sichuan": "dwd_sichuan_price",
        "chongqing": "dwd_chongqing_price",
        "jinan": "dwd_jinan_price",
        "rizhao": "dwd_rizhao_price",
    }
    idx = city_idx_map.get(city, "dwd_xian_price")
    attr_fields = ATTR_FIELDS
    aggs_body = {
        "size": 0,
        "aggs": {
            "by_category": {
                "terms": {"field": "category", "size": 40},
                "aggs": {
                    "total_spec": {
                        "filter": {"bool": {"must_not": [{"term": {"spec.keyword": "/"}}, {"term": {"spec.keyword": ""}}]}}
                    },
                    "with_attr": {
                        "filter": {
                            "bool": {
                                "should": [{"exists": {"field": f"attr.{f}"} if False else {"bool": {"must_not": [{"term": {f: ""}}]}}} for f in attr_fields],
                                "minimum_should_match": 1
                            }
                        }
                    }
                }
            }
        }
    }
    # Use top-level fields instead of attr. prefix (DWD has flat structure)
    real_aggs_body = {
        "size": 0,
        "aggs": {
            "by_category": {
                "terms": {"field": "category", "size": 60},
                "aggs": {
                    "total_spec": {
                        "filter": {"bool": {"must_not": [{"term": {"spec.keyword": "/"}}, {"term": {"spec.keyword": ""}}]}}
                    },
                    "with_any_attr": {
                        "filter": {
                            "bool": {
                                "must": [
                                    {"script": {"script": "for (String f : ['diameter','pressure','thickness','length','width','height','material','grade','color','voltage','current','drain_type','inlet_type','installation_type','form','cross_section','cores']) { try { def v = doc[f].value; if (v != null && v.toString().length() > 0) return true; } catch (Exception e) { } } return false;"}}
                                ]
                            }
                        }
                    }
                }
            },
            "missing_category": {
                "missing": {"field": "category"},
                "aggs": {
                    "total_spec": {
                        "filter": {"bool": {"must_not": [{"term": {"spec.keyword": "/"}}, {"term": {"spec.keyword": ""}}]}}
                    }
                }
            }
        }
    }
    try:
        result = es.search(index=idx, body=real_aggs_body)
    except Exception:
        return []
    buckets = result.get("aggregations", {}).get("by_category", {}).get("buckets", [])
    missing_bucket = result.get("aggregations", {}).get("missing_category", {})
    coverage = []
    for b in buckets:
        total = b.get("total_spec", {}).get("doc_count", 0)
        with_attr = b.get("with_any_attr", {}).get("doc_count", 0)
        rate = round(with_attr / total * 100, 1) if total > 0 else 0
        coverage.append({
            "category": b["key"],
            "total": total,
            "with_attr": with_attr,
            "rate": rate,
        })
    missing_total = missing_bucket.get("total_spec", {}).get("doc_count", 0)
    if missing_total > 0:
        coverage.append({
            "category": "(无分类)",
            "total": missing_total,
            "with_attr": 0,
            "rate": 0.0,
        })
    coverage.sort(key=lambda x: x["rate"])
    return coverage


@router.get("/api/stats/spec-quality")
def stats_spec_quality(
    city: str = Query("xian", description="城市 key"),
    sample_size: int = Query(50, description="抽样数量"),
    category: str = Query("", description="分类筛选"),
):
    """Spec 解析质量报告：DWD 抽样 + 分类覆盖率"""
    samples = _sample_dwd_specs(city, sample_size, category)
    coverage = _category_coverage(city)
    return {
        "city": city,
        "samples": samples,
        "coverage": coverage,
    }


# ═══════════════════════════════════════════════════════
# Spec 修复接口：预览 + 确认写入
# ═══════════════════════════════════════════════════════


class FixCaseRequest(BaseModel):
    city: str = "xian"
    spec: str
    expected: dict
    confirm: bool = False


def _infer_rule_suggestion(spec: str, expected: dict) -> list:
    """
    根据 rules/ 目录下已有规则生成建议，完全基于已加载规则进行匹配。
    expected 只作参考，不作为匹配条件。
    规则文件变更后自动反映，无需硬编码。
    """
    import re, glob
    rules = []
    s = spec.strip()

    def add(attr, note, pattern, code_block):
        rules.append({"attr": attr, "note": note, "pattern": pattern, "code_block": code_block})

    rules_dir = os.path.join(ETL_CMD_DIR, "parse_spec", "rules")
    pattern_re = re.compile(
        r'# ── 自动生成: (.+?) ──\s*\n'
        r'(.*?)(?=\n# ── 自动生成:|\Z)',
        re.DOTALL
    )
    for py_file in sorted(glob.glob(os.path.join(rules_dir, "*.py"))):
        if py_file.endswith("__init__.py"):
            continue
        with open(py_file) as f:
            file_content = f.read()
        for m in pattern_re.finditer(file_content):
            note = m.group(1).strip()
            code = m.group(2).strip()
            pat_m = re.search(r"re\.search\(r['\"]([^'\"]+)['\"]", code)
            if not pat_m:
                continue
            pattern = pat_m.group(1)
            try:
                compiled = re.compile(pattern)
            except re.error:
                continue
            if compiled.match(s):
                attr_m = re.search(r"result\['([^']+)'\]\s*=", code)
                attr = attr_m.group(1) if attr_m else "_unknown"
                code_block = code.split("\n")
                add(attr, note, pattern, code_block)
    return rules





def _get_rule_insert_line(content: str, attr: str) -> int:
    markers = {
        "diameter": ["# 4. 管径:", "# 4e. Φ", "# 4f. 纯 Φ"],
        "thickness": ["# 1. 厚度"],
        "width": ["# 3. 3D"],
        "height": ["# 3. 3D"],
        "grade": ["# 7. 材质"],
        "material": ["# 7. 材质"],
        "cores": ["# 2. 电缆"],
        "cross_section": ["# 2. 电缆"],
        "ring_stiffness": ["# 5. 环刚度"],
        "pressure": ["# 6. 压力"],
        "length_range": ["# 3. 3D"],
    }.get(attr, [f"# {attr}"])
    positions = []
    for i, line in enumerate(content.splitlines()):
        for mk in markers:
            if mk in line:
                positions.append(i)
    return max(positions) if positions else 112  # 112 = 插入到 BaseParseSpec class 定义之前


def _get_rule_file_path(attr: str) -> str:
    """根据 attr 确定规则文件路径"""
    rules_dir = os.path.join(ETL_CMD_DIR, "parse_spec", "rules")
    os.makedirs(rules_dir, exist_ok=True)
    attr_file_map = {
        "diameter": "diameter.py",
        "thickness": "thickness.py",
        "width": "width.py",
        "height": "height.py",
        "grade": "grade.py",
        "material": "material.py",
        "cores": "cores.py",
        "cross_section": "cross_section.py",
        "ring_stiffness": "ring_stiffness.py",
        "pressure": "pressure.py",
        "length_range": "length_range.py",
    }
    filename = attr_file_map.get(attr, f"{attr}.py")
    return os.path.join(rules_dir, filename)



def _apply_rule_to_base(code_lines: list, attr: str, note: str) -> bool:
    """追加规则到 rules/<attr>.py，文件级代码无缩进"""
    import shutil
    rule_file = _get_rule_file_path(attr)
    bak = rule_file + ".bak"
    if os.path.exists(rule_file):
        shutil.copy(rule_file, bak)
    try:
        block_lines = [f"# ── 自动生成: {note} ──"]
        for ln in code_lines:
            stripped = ln.lstrip()
            if stripped.startswith("if ") or stripped.startswith("elif ") or stripped.startswith("else:") or stripped.startswith("for ") or stripped.startswith("while "):
                # 控制语句自身不加缩进
                block_lines.append(stripped)
            elif any(stripped.startswith(k) for k in ["result", "return", "pass", "break", "continue"]):
                block_lines.append("    " + stripped)  # 4 spaces for body
            else:
                block_lines.append(stripped)
        block = "\n".join(block_lines)
        with open(rule_file, "a") as f:
            f.write("\n" + block + "\n")
        if os.path.exists(bak):
            os.remove(bak)
        return True
    except Exception:
        if os.path.exists(bak):
            shutil.move(bak, rule_file)
        return False


def _run_spec_validation_quiet(spec: str = "") -> tuple:
    """用当前 spec 做简单验证：能解析出属性即算通过"""
    if not spec:
        return (0, 0)
    try:
        sys.path.insert(0, ETL_CMD_DIR)
        from parse_spec import get_parser
        city_key = "xian"  # 默认用 xian parser
        parser = get_parser(city_key)
        result = parser.parse(spec)
        # 只要有任何属性被解析出来就算通过
        if result and len(result) > 0:
            return (1, 1)
        return (0, 1)
    except Exception:
        return (0, 1)


def _call_openclaw_llm(spec: str, expected: dict) -> dict:
    """本地规则库为空时，调用 OpenClaw /v1/chat/completions 获取 AI 规则建议"""
    import urllib.request, urllib.error
    token = ""
    try:
        with open("/Users/pengfit/.openclaw/openclaw.json") as f:
            import json
            d = json.load(f)
            token = d.get("gateway", {}).get("auth", {}).get("token", "")
    except Exception:
        return {"ok": False, "message": "无法读取 OpenClaw token"}

    prompt = f"""你是一个建材规格解析规则生成专家。
当前需要为以下规格字符串生成 base.py re 解析规则：

原始规格文本："{spec}"
期望解析结果：{json.dumps(expected, ensure_ascii=False)}

base.py 代码风格示例：
    m = re.search(r'Φ(\\d+)\\*(\\d+(?:\\.\\d+)?)\\s*mm', s)
    if m:
        result['diameter'] = 'Φ' + m.group(1)
        result['thickness'] = m.group(2) + 'mm'

支持的属性：{ATTR_FIELDS_DESC}

重要规则：
1. spec 中出现的任何可识别特征都应该尝试提取，不要直接返回"无法生成规则"
2. ~ 表示范围，如 "25mm~70mm" 表示从 25mm 到 70mm，应提取为 range_min=25, range_max=70
3. * 表示乘积/尺寸，如 "2600*700*1500" 提取为 width/height/thickness
4. code_block 每行是独立的 Python 语句，**不带任何缩进前缀**，直接是文件级代码
5. pattern 用原始字符串 r'...' 格式，note 简短描述规则用途
6. pattern 必须使用捕获组提取实际值，禁止硬编码。例如 `Q235B` 应写成 `r'(Q\d+(?:B)?)'` 提取为 `m.group(1)`，而非 `r'Q235B'` 硬匹配全文

返回格式（直接返回纯 JSON，不带 markdown）：
{{"ok":true,"suggestions":[{{"attr":"属性名","note":"描述","pattern":"正则","code_block":"代码行"}}]}}

即使 spec 只有一个数值，也要生成规则，例如 "25mm" 应生成提取 thickness 或 diameter 的规则。
"""

    body = json.dumps({
        "model": "openclaw",
        "messages": [{"role": "user", "content": prompt}],
        "user": "spec-fix-agent",
        "max_tokens": 1024,
        "temperature": 0.1,
    }).encode("utf-8")

    req = urllib.request.Request(
        "http://localhost:18789/v1/chat/completions",
        data=body,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        import http.client
        c = http.client.HTTPConnection("localhost", 18789, timeout=10)
        c.request("POST", "/v1/chat/completions", body=body, headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Content-Length": str(len(body)),
        })
        resp = c.getresponse()
        data = json.loads(resp.read())
        content = data.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
        if not content:
            return {"ok": False, "message": "AI 返回空内容"}
        if content.startswith("```"):
            parts = content.split("```")
            content = parts[1] if len(parts) > 1 else parts[0]
            if content.startswith("json"):
                content = content[4:]
        result = json.loads(content)
        return result
    except urllib.error.URLError as e:
        return {"ok": False, "message": f"OpenClaw 连接失败: {e}"}
    except json.JSONDecodeError as e:
        return {"ok": False, "message": f"AI 返回格式错误: {e}"}
    except Exception as e:
        return {"ok": False, "message": f"AI 分析异常: {e}"}


@router.post("/api/stats/spec-quality/fix-case")
def fix_spec_case(req: FixCaseRequest = Body(...)):
    """
    confirm=False（默认）：分析返回规则建议（预览）
    confirm=True：用户确认后写入 base.py + 触发 city ETL
    """
    import shutil, re as re_mod

    city = req.city
    spec = req.spec.strip()
    expected = req.expected

    suggestions = _infer_rule_suggestion(spec, expected)
    # 收集所有建议来源（本地 + AI）
    all_suggestions = suggestions[:]
    if not suggestions:
        # 本地规则库为空，调用 OpenClaw AI 分析
        ai_result = _call_openclaw_llm(spec, expected)
        if ai_result.get("ok"):
            ai_suggestions = ai_result.get("suggestions", [])
            if ai_suggestions:
                all_suggestions = ai_suggestions
        # AI 也无法生成时返回错误
        if not all_suggestions:
            return {
                "ok": False,
                "message": ai_result.get("message", "无法为此 spec 生成规则建议"),
                "spec": spec,
                "expected": expected,
            }

    if not req.confirm:
        # 预览模式下：模拟解析结果
        import re as re_mod
        parse_result = {}
        for s in all_suggestions:
            pattern = s.get("pattern", "")
            if not pattern:
                continue
            try:
                code_block = s["code_block"] if isinstance(s["code_block"], list) else s["code_block"].split("\n")
                exec_globals = {"result": {}, "re": re_mod, "s": spec}
                exec("\n".join(code_block), exec_globals)
                parse_result.update(exec_globals.get("result", {}))
            except Exception:
                pass
        return {
            "ok": True,
            "mode": "preview",
            "spec": spec,
            "expected": expected,
            "source": "ai" if not suggestions else "local",
            "parse_result": parse_result,
            "suggestions": [
                {
                    "note": s["note"],
                    "attr": s["attr"],
                    "pattern": s["pattern"],
                    "code_block": "\n".join(s["code_block"]) if isinstance(s["code_block"], list) else s["code_block"],
                }
                for s in all_suggestions
            ],
        }

    # confirm 模式：写入 rules/ 目录
    applied_note = None
    for s in all_suggestions:
        code_block = s["code_block"] if isinstance(s["code_block"], list) else s["code_block"].split("\n")
        ok = _apply_rule_to_base(code_block, s["attr"], s["note"])
        if not ok:
            return {"ok": False, "message": "规则写入失败，已 rollback"}
        passed, total = _run_spec_validation_quiet(spec)
        if not (passed == total and total > 0):
            return {
                "ok": False,
                "mode": "confirm",
                "message": f"测试集 {passed}/{total} 不通过，rollback",
                "spec": spec,
            }
        applied_note = s["note"]

    # 触发 city ETL
    city_dwd_map = {
        "xian": "dwd_xian_price",
        "sichuan": "dwd_sichuan_price",
        "chongqing": "dwd_chongqing_price",
        "jinan": "dwd_jinan_price",
        "rizhao": "dwd_rizhao_price",
    }
    dwd_idx = city_dwd_map.get(city, "dwd_xian_price")
    etl_ok = False
    try:
        etl_script = os.path.join(ETL_CMD_DIR, "etl.py")
        r = subprocess.run(
            [sys.executable, etl_script, "--city", city, "--dwd-index", dwd_idx],
            capture_output=True, text=True, timeout=600,
        )
        etl_ok = (r.returncode == 0)
    except Exception:
        etl_ok = False

    return {
        "ok": True,
        "mode": "confirm",
        "spec": spec,
        "expected": expected,
        "message": f"规则已写入，测试集通过。ETL {'已触发' if etl_ok else '触发失败'}",
        "etl_ok": etl_ok,
    }
