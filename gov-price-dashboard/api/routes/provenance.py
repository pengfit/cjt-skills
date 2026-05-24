#!/usr/bin/env python3
"""
数据溯源 API 端点
来源分布、各省新鲜度、近30天入库趋势 — 支持多城市
"""

from fastapi import APIRouter, HTTPException, Query, Body
from pydantic import BaseModel
from elasticsearch import Elasticsearch
import datetime, concurrent.futures, subprocess, json, os, sys, re, functools, yaml

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

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

# 从 classify/rules/ 动态获取分类列表（供 AI prompt 使用）
try:
    import sys as _sys
    _sys.path.insert(0, ETL_CMD_DIR)
    from classify.rules import get_rules
    _ALL_CATS = sorted(set(r["category"] for r in get_rules()))
    CLASSIFICATIONS_STR = "\n".join(f'{i+1}. {c}' for i, c in enumerate(_ALL_CATS))
except Exception:
    _ALL_CATS = []
    CLASSIFICATIONS_STR = ""

# 从 parse_spec/rules/_attrs.py 动态加载属性描述
try:
    import re as _re
    _attrs_file = os.path.join(ETL_CMD_DIR, "parse_spec", "rules", "_attrs.py")
    _ATTR_RE = _re.compile(r'^\s*"([^"]+)"\s*→\s*"([^"]+)"', _re.MULTILINE)
    _ATTR_MAP = {}
    with open(_attrs_file) as _f:
        for _m in _ATTR_RE.finditer(_f.read()):
            _ATTR_MAP[_m.group(1)] = _m.group(2)
    ATTR_FIELDS_MAP = _ATTR_MAP
except Exception:
    ATTR_FIELDS_MAP = {
        "diameter": "管径/口径", "thickness": "壁厚/厚度",
        "length": "长度", "width": "宽度", "height": "高度",
        "material": "材质", "grade": "等级/标号", "pressure": "公称压力",
    }

ATTR_FIELDS = list(ATTR_FIELDS_MAP.keys())
ATTR_FIELDS_STR = ", ".join(ATTR_FIELDS)  # for AI prompt
ATTR_FIELDS_DESC = ", ".join(f"{k}({v})" for k, v in ATTR_FIELDS_MAP.items())  # field(中文)

# ── AI Prompts 配置（从 prompts.yml 加载）────────────────────
PROMPTS_FILE = os.path.join(SCRIPT_DIR, "prompts.yml")

def _load_prompts():
    try:
        with open(PROMPTS_FILE) as f:
            return yaml.safe_load(f)
    except Exception:
        return {}

PROMPTS = _load_prompts()

def fix_case_prompt_fn(spec, breed="", category="", expected=None):
    """生成 fix-case API 的 user content（fix-case 端点专用）"""
    prompts_cfg = PROMPTS.get("fix_case", {})
    tmpl = prompts_cfg.get("template", "")
    breed_hint = f"\n参考商品名称：{breed}" if breed else ""
    cat_hint = f"\n所属分类：{category}" if category else ""
    attr_desc = ", ".join(f"{k}({v})" for k, v in ATTR_FIELDS_MAP.items())
    expected_json = json.dumps(expected or {}, ensure_ascii=False)
    try:
        return tmpl.format(
            spec=spec,
            breed_hint=breed_hint,
            cat_hint=cat_hint,
            expected=expected_json,
            attr_desc=attr_desc,
        )
    except (KeyError, ValueError):
        # YAML {{}} quoting escaped braces → build manually
        lines = [
            f"原始规格文本：{spec}",
            (f"参考商品名称：{breed}" if breed else ""),
            (f"所属分类：{category}" if category else ""),
            f"支持属性：{attr_desc}",
            f"期望解析：{expected_json}",
        ]
        return "\n".join(l for l in lines if l)


def classify_breed_prompt_fn(breed):
    """生成 classify-breed API 的 user content"""
    prompts_cfg = PROMPTS.get("classify_breed", {})
    tmpl = prompts_cfg.get("template", "")
    try:
        return tmpl.format(breed=breed, classifications=CLASSIFICATIONS_STR)
    except (KeyError, ValueError):
        return f"品种名称：{breed}\n分类列表：{CLASSIFICATIONS_STR}"


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


# Parser 实例缓存（避免每次请求都重新 import + 加载规则）
_PARSER_CACHE = {}

def _get_cached_parser(city: str):
    """返回 city 对应的 parse_spec 实例，带缓存"""
    if city not in _PARSER_CACHE:
        try:
            from parse_spec import get_parser
            _PARSER_CACHE[city] = get_parser(city)
        except Exception:
            _PARSER_CACHE[city] = None
    return _PARSER_CACHE[city]


def _sample_dwd_specs(city="xian", sample_size=50, category=""):
    import sys, os, random
    sys.path.insert(0, ETL_CMD_DIR)
    city_idx_map = {
        "xian": "dwd_xian_price",
        "sichuan": "dwd_sichuan_price",
        "chongqing": "dwd_chongqing_price",
        "jinan": "dwd_jinan_price",
        "rizhao": "dwd_rizhao_price",
    }
    idx = city_idx_map.get(city, "dwd_xian_price")
    parser = _get_cached_parser(city)
    if parser is None:
        return []

    # Use random offset sampling for all cases.
    # This avoids function_score/random_score which fails on this ES cluster
    # with "failed to create query" error.
    # Filter: exclude spec="/" and empty spec at query level (no need to sample them)
    if category:
        query = {"bool": {"must": [{"term": {"category": category}}], "must_not": [{"term": {"spec.keyword": "/"}}, {"term": {"spec.keyword": ""}}]}}
    else:
        query = {"bool": {"must_not": [{"term": {"spec.keyword": "/"}}, {"term": {"spec.keyword": ""}}]}}

    try:
        total = es.count(index=idx, body={"query": query}).get("count", 0)
    except Exception:
        total = 0
    if total == 0:
        return []

    max_offset = max(0, total - sample_size)
    # ES index.max_result_window default is 10000; clamp offset to avoid overflow
    offset = random.randint(0, max(max_offset, 0)) if max_offset > 0 else 0
    # Cap at 9999 to stay within ES result window (from + size <= 10000)
    max_allowed_offset = 10000 - sample_size
    if offset > max_allowed_offset:
        offset = random.randint(0, max_allowed_offset)
    body = {
        "size": sample_size,
        "_source": ["spec", "category", "breed", "needs_review"],
        "query": query,
        "from": offset,
        "sort": [{"_doc": "asc"}],
    }

    try:
        result = es.search(index=idx, body=body)
    except Exception:
        return []

    samples = []
    for h in result.get("hits", {}).get("hits", []):
        src = h["_source"]
        spec = src.get("spec", "")
        # NEW ETL logic: needs_review=True → 规则命中（待人工审核）
        # Missing needs_review field = old doc, treat as False
        needs_review = src.get("needs_review", False)
        has_attr = needs_review
        samples.append({
            "spec": spec,
            "category": src.get("category", ""),
            "breed": src.get("breed", ""),
            "has_attr": has_attr,
            "needs_review": needs_review,
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
    # Use needs_review field from DWD: needs_review=True means needs manual review.
    # ES boolean fields can behave unpredictably with term queries;
    # use a script filter for reliable count.
    real_aggs_body = {
        "size": 0,
        "aggs": {
            "by_category": {
                "terms": {"field": "category", "size": 60},
                "aggs": {
                    "total_spec": {
                        "filter": {"bool": {"must_not": [{"term": {"spec.keyword": "/"}}, {"term": {"spec.keyword": ""}}]}}
                    },
                    # NEW ETL logic (since 2026-05-24):
                    # - needs_review=True  → 规则命中（待人工审核/确认规则是否正确）
                    # - needs_review=False → 规则未命中 或 spec="/"（无需细分）
                    # 覆盖率的 "解析成功" = 规则命中 → needs_review=True
                    "parsed_ok": {
                        "filter": {"bool": {"must": [{"term": {"needs_review": True}}], "must_not": [{"term": {"spec.keyword": "/"}}, {"term": {"spec.keyword": ""}}]}}
                    }
                }
            },
            "missing_category": {
                "missing": {"field": "category"}
            }
        }
    }
    try:
        result = es.search(index=idx, body=real_aggs_body)
    except Exception:
        return []
    buckets = result.get("aggregations", {}).get("by_category", {}).get("buckets", [])
    coverage = []
    for b in buckets:
        total = b.get("total_spec", {}).get("doc_count", 0)
        parsed_ok = b.get("parsed_ok", {}).get("doc_count", 0)
        coverage.append({
            "category": b["key"],
            "total": total,
            "with_attr": parsed_ok,
            "rate": round(parsed_ok / max(1, total) * 100, 1),
        })
    coverage.sort(key=lambda x: x["rate"])
    return coverage


@router.get("/api/stats/spec-quality")
def stats_spec_quality(
    city: str = Query("xian", description="城市 key"),
    sample_size: int = Query(50, description="抽样数量"),
    category: str = Query("", description="分类筛选"),
    _sample: bool = Query(True, description="是否返回抽样明细（打开页面时传 false 避免无用查询）"),
):
    """Spec 解析质量报告：DWD 抽样 + 分类覆盖率"""
    samples = _sample_dwd_specs(city, sample_size, category) if _sample else []
    coverage = _category_coverage(city)
    return {
        "city": city,
        "samples": samples,
        "coverage": coverage,
    }


@router.post("/api/stats/spec-quality/refresh-category")
def refresh_category(
    city: str = Body("xian", description="城市 key"),
    category: str = Body("", description="分类名（为空则刷新全部）"),
):
    """
    按分类触发 DWD 清洗（重新 ETL 指定分类下的所有数据）。
    前端：同一分类下的规格规则全部确认后，点击清洗。
    """
    import subprocess, sys
    if not category:
        return {"ok": False, "message": "category 不能为空"}

    city_idx_map = {
        "xian": "dwd_xian_price",
        "sichuan": "dwd_sichuan_price",
        "chongqing": "dwd_chongqing_price",
        "jinan": "dwd_jinan_price",
        "rizhao": "dwd_rizhao_price",
    }
    etl_ok = False
    try:
        etl_script = os.path.join(ETL_CMD_DIR, "etl.py")
        r = subprocess.run(
            [sys.executable, etl_script, "--city", city, "--category", category],
            capture_output=True, text=True, timeout=1800,
        )
        etl_ok = (r.returncode == 0)
    except Exception:
        etl_ok = False

    # 分类清洗（refresh-category）时：规则已全部确认，全部标记 needs_review=False

    return {
        "ok": etl_ok,
        "message": f"分类「{category}」DWD 清洗{'成功' if etl_ok else '失败'}",
        "city": city,
        "category": category,
    }


# ═══════════════════════════════════════════════════════
# Spec 修复接口：预览 + 确认写入
# ═══════════════════════════════════════════════════════


class FixCaseRequest(BaseModel):
    city: str = "xian"
    spec: str
    expected: dict
    confirm: bool = False
    suggestions: list = []
    breed: str = ""
    category: str = ""


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
            if compiled.search(s):
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



def _apply_rule_to_base(code_lines: list, attr: str, note: str, pattern: str = "") -> bool:
    """追加规则到 rules/<attr>.py，文件级代码无缩进。attr+pattern 相同则跳过写入"""
    import shutil
    rule_file = _get_rule_file_path(attr)
    # ── 去重检查：attr + pattern 已存在则跳过 ──
    if pattern and os.path.exists(rule_file):
        with open(rule_file) as rf:
            existing = rf.read()
        check1 = 're.search(r"' + pattern + '"'
        check2 = "re.search(r'" + pattern + "'"
        if check1 in existing or check2 in existing:
            return "skip"  # 已存在，跳过写入
    bak = rule_file + ".bak"
    if os.path.exists(rule_file):
        shutil.copy(rule_file, bak)
    try:
        block_lines = [f"# ── 自动生成: {note} ──"]
        for ln in code_lines:
            stripped = ln.lstrip()
            if stripped.startswith("if ") or stripped.startswith("elif ") or stripped.startswith("else:") or stripped.startswith("for ") or stripped.startswith("while "):
                block_lines.append(stripped)
            elif any(stripped.startswith(k) for k in ["result", "return", "pass", "break", "continue"]):
                block_lines.append("    " + stripped)
            else:
                block_lines.append(stripped)
        block = "\n".join(block_lines)
        with open(rule_file, "a") as f:
            f.write("\n" + block + "\n")
        if os.path.exists(bak):
            os.remove(bak)
        return "new"  # 新写入成功
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
        from parse_spec.base import _build_cache
        _build_cache()  # 新增规则后刷新缓存
        city_key = "xian"  # 默认用 xian parser
        parser = get_parser(city_key)
        result = parser.parse(spec)
        # 只要有任何属性被解析出来就算通过
        if result and len(result) > 0:
            return (1, 1)
        return (0, 1)
    except Exception:
        return (0, 1)



def _parse_ai_json(content):
    r"""解析 AI 返回的可能格式错误的 JSON，容忍未转义的新行符和单引号。

    AI 在 pattern/code_block 字段中使用 python r'...' 语法，导致 JSON 被破坏。
    例如："pattern":"r'-(YJ\\w+)-','code_block":"..."
    其中 r'...' 是 python raw string，内部的 \' 是转义的单引号。
    JSON 标准只允许 \" \\ \/ \b \f \n \r \t \uXXXX 作为转义序列。
    本函数先用标准 json.loads 尝试，失败后逐个 suggestion 对象解析。
    """
    import re as _re

    if content.startswith("```"):
        parts = content.split("```")
        content = parts[1] if len(parts) > 1 else parts[0]
        if content.startswith("json"):
            content = content[4:]
    content = content.strip()
    first = content.find('{')
    last = content.rfind('}')
    if first < 0 or last <= first:
        raise ValueError("不是有效的 JSON")
    json_str = content[first:last+1]

    # Step 1: unescape newlines inside JSON string values
    result = []
    i = 0
    in_str = False
    while i < len(json_str):
        c = json_str[i]
        if c == '"' and (i == 0 or json_str[i-1] != '\\'):
            in_str = not in_str
            result.append(c)
            i += 1
        elif c == '\\' and in_str:
            result.append(c)
            i += 1
            if i < len(json_str):
                result.append(json_str[i])
                i += 1
        elif c in '\n\r' and in_str:
            i += 1
        else:
            result.append(c)
            i += 1
    fixed = ''.join(result)

    # Step 2: try standard json.loads first
    try:
        return json.loads(fixed)
    except json.JSONDecodeError:
        pass

    # Step 3: AI broke JSON by embedding python raw string syntax in field values.
    # Parse suggestion objects one by one by tracking {depth}.
    suggestions = []
    arr_match = _re.search(r'"suggestions":\s*\[(.*)\]\s*\}', fixed, _re.DOTALL)
    if not arr_match:
        raise ValueError("无法解析 AI 返回内容 - 缺少 suggestions 数组")

    arr_content = arr_match.group(1)

    # Find each suggestion object
    obj_positions = []
    depth = 0
    start_pos = -1
    for i, c in enumerate(arr_content):
        if c == '{':
            if depth == 0:
                start_pos = i
            depth += 1
        elif c == '}':
            depth -= 1
            if depth == 0 and start_pos >= 0:
                obj_positions.append((start_pos, i+1))
                start_pos = -1

    for start, obj_end in obj_positions:
        obj_text = arr_content[start:obj_end]

        attr_m = _re.search(r'"attr":\s*"([^"]*)"', obj_text)
        note_m = _re.search(r'"note":\s*"([^"]*)"', obj_text)
        if not attr_m or not note_m:
            continue

        attr = attr_m.group(1)
        note = note_m.group(1)
        pattern_val, code_val = _extract_suggestion_fields(obj_text)

        suggestions.append({
            "attr": attr,
            "note": note,
            "pattern": pattern_val,
            "code_block": code_val,
        })

    if suggestions:
        return {"ok": True, "suggestions": suggestions}

    raise ValueError("无法解析 AI 返回内容")


def _extract_suggestion_fields(obj_text):
    """从单个 suggestion 对象的 JSON 文本中提取 pattern 和 code_block 字段。

    AI 将 python raw string 语法 r'...' 嵌入 JSON 字段值，导致字段合并。
    """
    import re as _re

    def find_field_start(obj, field_name):
        for marker in ['"' + field_name + '":', "\\'" + field_name + '":']:
            m = _re.search(marker, obj)
            if m:
                return m.end(), marker
        return None, None

    def extract_pattern_value(obj):
        value_start, marker = find_field_start(obj, "pattern")
        if value_start is None:
            return ""
        raw = obj[value_start:]

        # Skip the opening " of the JSON string value
        if raw.startswith('"'):
            raw = raw[1:]

        # Find the next JSON field separator
        next_markers_raw = [
            ',"attr":', ',"note":', ',"pattern":', ',"code_block":',
            ",'attr:", ",'note:", ",'pattern:", ",'code_block:"
        ]
        next_pos = len(raw)
        for marker2 in next_markers_raw:
            m2 = _re.search(marker2, raw)
            if m2:
                next_pos = min(next_pos, m2.start())

        raw = raw[:next_pos]

        # If raw starts with r' (python raw string), find closing '
        if raw.startswith("r'"):
            i = 2
            while i < len(raw):
                if raw[i] == "'":
                    if i > 0 and raw[i-1] == '\\':
                        i += 1
                    elif i + 1 < len(raw) and raw[i+1] == "'":
                        i += 2
                    else:
                        raw = raw[:i]
                        break
                else:
                    i += 1

        return _fix_json_escapes(raw)

    def extract_code_block_value(obj):
        value_start, marker = find_field_start(obj, "code_block")
        if value_start is None:
            return ""
        raw = obj[value_start:]

        # Skip the opening " of the JSON string value
        if raw.startswith('"'):
            raw = raw[1:]

        # Value goes to end of object (before final })
        endbrace = raw.rfind('}')
        if endbrace > 0:
            raw = raw[:endbrace]

        return _fix_json_escapes(raw)

    pattern_val = extract_pattern_value(obj_text)
    code_val = extract_code_block_value(obj_text)
    return pattern_val, code_val



def _fix_json_escapes(s):
    result = []
    i = 0
    while i < len(s):
        c = s[i]
        if c == '\\' and i + 1 < len(s):
            nc = s[i+1]
            if nc == '\\':
                result.append('\\')
                i += 2
            elif nc == 'n':
                result.append('\n')
                i += 2
            elif nc == 'r':
                result.append('\r')
                i += 2
            elif nc == 't':
                result.append('\t')
                i += 2
            elif nc == "'":
                result.append("'")
                i += 2
            elif nc == '"':
                result.append('"')
                i += 2
            else:
                result.append(c)
                i += 1
        else:
            result.append(c)
            i += 1
    return ''.join(result)


def _call_openclaw_llm(spec: str, expected: dict, breed: str = "", category: str = "") -> dict:
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

    prompt = fix_case_prompt_fn(spec, breed=breed, category=category, expected=expected)
    system_msg = PROMPTS.get("fix_case", {}).get("system", "")

    body = json.dumps({
        "model": "openclaw",
        "messages": [
            {"role": "system", "content": system_msg},
            {"role": "user", "content": prompt},
        ],
        "user": "spec-fix-agent",
        "max_tokens": 4096,
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
        c = http.client.HTTPConnection("localhost", 18789, timeout=30)
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
        result = _parse_ai_json(content)
        return result
    except urllib.error.URLError as e:
        return {"ok": False, "message": f"OpenClaw 连接失败: {e}"}
    except json.JSONDecodeError as e:
        return {"ok": False, "message": f"AI 返回格式错误: {e}"}
    except Exception as e:
        return {"ok": False, "message": f"AI 分析异常: {e}"}


@router.post("/api/stats/spec-quality/classify-breed")
def classify_breed_ai(req: ClassifyBreedRequest = Body(...)):
    """
    输入品种名（breed），AI 推断分类并自动写入 classify/rules/keyword.py。
    用于 ETL 清洗时规则未命中的品种，自动补充分类规则。
    """
    import os, sys
    breed = req.breed.strip()
    if not breed:
        return {"ok": False, "message": "breed 不能为空"}

    # 先尝试从本地 rules/ 读取规则（无需 import classify）
    rules_dir = os.path.join(ETL_CMD_DIR, "classify", "rules")
    keyword_file = os.path.join(rules_dir, "keyword.py")
    _rule_re = __import__("re").compile(r'^\s*"([^"]+)"\s*→\s*"([^"]+)"', __import__("re").MULTILINE)
    try:
        with open(keyword_file) as f:
            content = f.read()
        for m in _rule_re.finditer(content):
            kw, cat = m.group(1), m.group(2)
            if kw in breed or breed in kw:
                return {"ok": True, "mode": "cached", "breed": breed,
                        "category": cat, "source": "local", "message": "本地已有规则"}
        breed_file = os.path.join(rules_dir, "breed.py")
        with open(breed_file) as f:
            content = f.read()
        for m in _rule_re.finditer(content):
            kw, cat = m.group(1), m.group(2)
            if kw in breed or breed in kw:
                return {"ok": True, "mode": "cached", "breed": breed,
                        "category": cat, "source": "local", "message": "本地已有规则"}
    except FileNotFoundError:
        pass

    # 本地无规则，调用 AI
    ai_result = _call_classify_llm(breed)
    if not ai_result.get("ok"):
        return ai_result

    category = ai_result.get("category", "")
    confidence = ai_result.get("confidence", 0)
    note = ai_result.get("note", "")
    if not category:
        return {"ok": False, "message": "AI 未返回分类"}

    # 写入 keyword.py（带文件锁防止多进程并发写入重复规则）
    import fcntl
    lock_file = keyword_file + ".lock"
    new_rule = f'# {note}\n"{breed}" → "{category}"\n'
    try:
        with open(lock_file, "w") as lf:
            fcntl.flock(lf.fileno(), fcntl.LOCK_EX)
            try:
                # 检查是否已有该规则
                with open(keyword_file) as f:
                    existing = f.read()
                # 去重：如果 breed 或其包含关系已存在则跳过
                skip = False
                for m in _rule_re.finditer(existing):
                    kw, cat = m.group(1), m.group(2)
                    if kw in breed or breed in kw:
                        skip = True
                        break
                if not skip:
                    with open(keyword_file, "a") as f:
                        f.write(new_rule)
                    written = True
                else:
                    written = False
            finally:
                fcntl.flock(lf.fileno(), fcntl.LOCK_UN)
    except Exception as e:
        return {"ok": False, "message": f"写入规则失败: {e}"}

    if written:
        return {
            "ok": True, "mode": "written", "breed": breed,
            "category": category, "confidence": confidence, "note": note,
            "source": "ai", "message": f"已写入 {keyword_file}",
        }
    else:
        return {
            "ok": True, "mode": "skipped", "breed": breed,
            "category": category, "confidence": confidence, "note": note,
            "source": "ai", "message": "规则已存在，跳过写入",
        }


def _call_classify_llm(breed: str) -> dict:
    """调用 OpenClaw LLM 推断品种分类"""
    import urllib.request, urllib.error, http.client
    token = ""
    try:
        with open("/Users/pengfit/.openclaw/openclaw.json") as f:
            d = json.load(f)
            token = d.get("gateway", {}).get("auth", {}).get("token", "")
    except Exception:
        return {"ok": False, "message": "无法读取 OpenClaw token"}

    prompt = classify_breed_prompt_fn(breed)
    system_msg = PROMPTS.get("classify_breed", {}).get("system", "")

    body = json.dumps({
        "model": "openclaw",
        "messages": [
            {"role": "system", "content": system_msg},
            {"role": "user", "content": prompt},
        ],
        "user": "classify-agent",
        "max_tokens": 256,
        "temperature": 0.1,
    }).encode("utf-8")

    try:
        c = http.client.HTTPConnection("localhost", 18789, timeout=30)
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


class ClassifyBreedRequest(BaseModel):
    breed: str
    city: str = "xian"


@router.post("/api/stats/spec-quality/fix-case")
def fix_spec_case(req: FixCaseRequest = Body(...)):
    """
    confirm=False（默认）：分析返回规则建议（预览）
    confirm=True：用户确认后写入 rules/ 目录，触发 ETL
    suggestions 由前端直接传入，跳过 AI 生成
    """
    import shutil, re as re_mod

    city = req.city
    spec = req.spec.strip()
    expected = req.expected

    if req.confirm:
        # confirm=True: 使用前端传入的 suggestions 直接写入，不调 AI
        if req.suggestions:
            all_suggestions = list(req.suggestions)
        else:
            return {"ok": False, "message": "confirm=True 但无 suggestions，请先预览", "spec": spec}
    else:
        # 预览模式：先尝试本地规则库，再用 AI 生成建议
        all_suggestions = list(req.suggestions) if req.suggestions else _infer_rule_suggestion(spec, expected)
        if not all_suggestions:
            ai_result = _call_openclaw_llm(
                spec, expected,
                req.breed if hasattr(req, "breed") and req.breed else "",
                req.category if hasattr(req, "category") and req.category else "",
            )
            if ai_result.get("ok"):
                ai_suggestions = ai_result.get("suggestions", [])
                if ai_suggestions:
                    all_suggestions = ai_suggestions
            if not all_suggestions:
                return {
                    "ok": False,
                    "message": ai_result.get("message", "无法为此 spec 生成规则建议"),
                    "spec": spec,
                    "expected": expected,
                }

    if not req.confirm:
        # 预览模式：模拟解析结果
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
            "source": "ai" if not req.suggestions else "local",
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
    wrote_new = False
    for s in all_suggestions:
        code_block = s["code_block"] if isinstance(s["code_block"], list) else s["code_block"].split("\n")
        result = _apply_rule_to_base(code_block, s["attr"], s["note"], s.get("pattern", ""))
        if result is False:
            return {"ok": False, "message": "规则写入失败，已 rollback", "spec": spec}
        if result == "new":
            wrote_new = True
        passed, total = _run_spec_validation_quiet(spec)
        if not (passed == total and total > 0):
            return {
                "ok": False,
                "mode": "confirm",
                "message": f"测试集 {passed}/{total} 不通过，rollback",
                "spec": spec,
            }
        applied_note = s["note"]

    if not wrote_new:
        return {
            "ok": True,
            "mode": "confirm",
            "spec": spec,
            "expected": expected,
            "message": "规则已存在，无需写入。ETL 未触发",
            "etl_ok": True,
        }

    return {
        "ok": True,
        "mode": "confirm",
        "spec": spec,
        "expected": expected,
        "message": "规则已写入。ETL 请通过分类清洗按钮触发",
        "etl_ok": False,
    }

