#!/usr/bin/env python3
"""
数据溯源 API 端点
来源分布、各省新鲜度、近30天入库趋势 — 支持多城市
"""

from fastapi import APIRouter, HTTPException, Query, Body
from pydantic import BaseModel
from elasticsearch import Elasticsearch
import datetime, concurrent.futures, subprocess, json, os, sys, re, functools, yaml, sqlite3

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ETL_CMD_DIR = "/Users/pengfit/.openclaw/workspace/skills/gov-price-etl/commands"
sys.path.insert(0, ETL_CMD_DIR)

try:
    from parse_spec.rules.vector_store import get_vec_store
except Exception:
    get_vec_store = None

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
    "chongqing": 35,  # 重庆市区县（材料信息价）
    "jinan":     41,  # 济南41个分类目录
    "rizhao":    3,   # 日照3个类别
}

# 进度索引 map
PROGRESS_INDEXES = {
    "xian":      "ods_material_xian_price_sync_progress",
    "sichuan":   "ods_material_sichuan_price_sync_progress",
    "chongqing": "ods_chongqing_price_progress",
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
            "query": {"range": {"etl_time": {"gte": "now-30d"}}},
            "aggs": {
                "daily": {
                    "date_histogram": {
                        "field": "etl_time",
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
    # 先尝试从 rules_vec.db 读取（breed_category_rules 表）
    import sqlite3 as _sqlite3
    import os as _os
    _rules_db = _os.path.join(ETL_CMD_DIR, "parse_spec", "rules", "rules_vec.db")
    if _os.path.exists(_rules_db):
        _conn = _sqlite3.connect(_rules_db)
        _cur = _conn.cursor()
        _cur.execute("SELECT DISTINCT category FROM breed_category_rules WHERE category != '' ORDER BY category")
        _ALL_CATS = [r[0] for r in _cur.fetchall()]
        _conn.close()
    else:
        _ALL_CATS = []
    CLASSIFICATIONS_STR = "\n".join(f"{i+1}. {c}" for i, c in enumerate(_ALL_CATS))
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

# ── classify_breed_batch 用内嵌 prompt（分类细化版）─────────────────────
_BREED_BATCH_SYSTEM = ("你是一个建材品种分类专家。分类必须严格遵循下面的分类体系，不得擅自创建新分类。")

_BREED_BATCH_TEMPLATE = (
    "请对以下品种列表进行批量分类，每个品种独立判断。\n\n"
    "品种列表：\n"
    "{breeds}\n\n"
    "参考分类体系（共5大类，若某品种同时属于多个系统，取最主要用途）：\n\n"

    "【钢材/钢筋】— 各种建筑钢材\n"
    "  H型钢、工字钢、槽钢、角钢、扁钢、钢板、花纹钢板、钢绞线、钢格盖板、钢筋网片、热轧光圆钢筋、热轧带肋钢筋、方钢、热轧工字钢、热轧槽钢、热轧不等边角钢、热轧等边角钢、热轧花纹钢板、热轧薄钢板、热轧扁钢、热轧中厚钢板\n\n"

    "【水泥】— 硅酸盐水泥及特种水泥\n"
    "  普通硅酸盐水泥、矿渣硅酸盐水泥、复合硅酸盐水泥、白色硅酸盐水泥\n\n"

    "【混凝土/预制件】— 混凝土及预制构件\n"
    "  预拌混凝土、抗渗混凝土、预制管桩、混凝土实心砖、混凝土丁式道牙、混凝土乙式道牙、混凝土甲式道牙、混凝土道路平石、混凝土固定门槛单扇密闭门、混凝土固定门槛单扇防护密闭门、混凝土活门槛单扇密闭门、混凝土活门槛单扇防护密闭门、钢制防盗门\n\n"

    "【砖/砌块】— 砖瓦类墙体材料\n"
    "  承重粘土多孔砖、非承重粘土多孔砖、蒸压粉煤灰砖、页岩空心砌块、加气砼砌块、机制红砖（标准砖）、机制青砖（标准砖）、灰砂砖、砖渣多孔砖、砖渣实心砖\n\n"

    "【保温材料】— 建筑保温隔热\n"
    "  岩棉板、岩棉、挤塑聚苯板、聚苯乙烯板、发泡水泥板、橡塑板材、橡塑管壳、矿棉吸音板、矿棉板、矿棉管壳、不燃超细玻璃纤维棉、带铝箔玻璃棉板、离心玻璃棉毡、轻质复合保温免拆模板、复合免拆保温模板、阻燃型挤塑聚苯板、聚氨酯保温管壳\n\n"

    "【防水材料】— 防水卷材/涂料\n"
    "  SBS改性沥青防水卷材、SBS改性沥青耐根穿刺防水卷材、自粘聚合物改性沥青防水卷材、高分子自粘胶膜防水卷材、自粘型热塑性聚烯烃防水卷材、耐根穿刺反应粘接型高分子防水卷材、沥青基聚酯胎预铺防水卷材、现制防水卷材、双面粘反应粘接型高分子防水卷材、自粘型热塑性聚烯烃（TPO）合成高分子耐根穿刺防水卷材、自粘型热塑性聚烯烃（TPO）合成高分子防水卷材（预铺反粘法）、高分子（非沥青基胶料）自粘胶膜防水卷材\n\n"

    "【防火/密封材料】— 防火阻燃及密封填缝\n"
    "  聚硫密封膏、遇水膨胀橡胶止水条、外贴式橡胶止水带、节点防水密封膏、防火涂料、阻火圈、阻燃型挤塑聚苯板、防火门监控模块\n\n"

    "【玻璃】— 平板玻璃及制品\n"
    "  中空玻璃、单银普白中空玻璃、双银普白中空玻璃、单银超白中空玻璃、双银超白中空玻璃、普通白玻中空夹胶钢化玻璃、钢化夹胶玻璃、钢化夹胶彩釉玻璃、钢化普白玻璃、钢化超白玻璃、夹丝玻璃、浮法平板玻璃、普通白炽灯泡\n\n"

    "【门窗/金属制品】— 门窗及金属装饰构配件\n"
    "  断桥铝合金平开窗、断桥铝合金推拉窗、断桥铝合金固定窗、铝合金平开窗、铝合金推拉窗、铝合金固定窗、塑钢平开窗、塑钢推拉窗、铝合金百叶窗、铝合金百叶门、钢制防盗门、钢质防火门、木质防火门、钢质防火窗、楼宇单元门、铝合金地弹簧门、不锈钢扶手、铜扶手、拉丝不锈钢、钛金拉丝不锈钢、黑钛不锈钢、热镀锌扁钢、热镀锌角钢、热镀锌槽钢、镀锌薄钢板、热镀锌钢格栅板、热浸锌钢格栅板、铜三角踏步防滑条\n\n"

    "【板材/吊顶/隔墙】— 各种人造板及吊顶隔墙\n"
    "  石膏板、水泥压力板、埃特板（基层板）、埃特板（面层板）、中密度板、多层密度板、木工板、三合板、五合板、木质门、矿棉吸音板、矿棉板、ALC轻质墙板、KTP轻质隔墙板、VGM轻质隔墙板、聚苯颗粒水泥夹芯内隔墙复合条板、GRC隔墙板、卫生间隔断\n\n"

    "【涂料/油漆/面砖】— 表面装饰材料\n"
    "  外墙丙烯酸涂料、丙烯酸涂料、氟碳漆、防锈漆、环氧煤沥青厚浆型防锈漆、调合漆、酚醛调和漆、磁漆、外墙白色釉面砖、外墙带色釉面砖、墙面瓷砖、普通釉面地砖、全瓷地砖、玻化砖、陶瓷仿石砖、陶瓷盲道砖、陶瓷踢脚板、水泥地砖（各色）\n\n"

    "【土工/市政/沥青类】— 市政道路及土工材料\n"
    "  土工格栅、透水土工布、防渗土工膜（两布一膜）、沥青、二灰碎石、水泥稳定碎石、砾石、碎石、块石、生石灰、熟石灰、透水混凝土、中粒式沥青混凝土、粗粒式沥青混凝土、细粒式沥青混凝土、预制混凝土嵌草砖、人行道透水砖、人行道通体砖、仿石材透水砖、陶瓷透水砖、PC砖、PC盲道砖、花岗岩石材、花岗岩石材盲道、花岗岩石材止车石、花岗岩路缘石、防撞路缘石、仿天然石面板、仿花岗岩面板、天然花岗岩板材、大理石板材、大理石台板（单孔）、大理石台板（双孔）、大理石踢脚板、花岗岩踢脚板、灰色文化砖、红色陶砖、陶砖、陶瓷锦砖（马赛克）、丙式道牙、铜三角踏步防滑条、预应力碳素钢丝、预应力刻痕钢丝、低碳冷拔钢丝\n\n"

    "【机械设备】— 暖通/通风/空调/散热器\n"
    "  光排管散热器、钢制散热器片、铸铁散热器片、天花导管式排气扇、百叶窗式排气扇、条缝风口、格栅风口、方形散流器、消声静压箱、静压箱、无机玻璃钢圆形风管、无机玻璃钢矩形风管、手动对开多叶调节阀、电动对开多叶调节阀、手动铝合金多叶送风口、电动铝合金多叶送风口、密闭型电动风量调节阀、水泵控制阀、分集水器（不带箱）、阻抗复合式消声器\n\n"

    "【消防器材】— 消防系统设备\n"
    "  下垂型喷头、直立型喷头、湿式报警阀、雨淋报警阀、预作用报警阀、手提式干粉灭火器、超细干粉自动灭火装置、无源型脉冲超细干粉自动灭火装置、七氟丙烷药剂、柜式七氟丙烷灭火装置（单瓶组）、柜式七氟丙烷灭火装置（双瓶组）、钢制防火阀、钢制电动防火阀、钢制排烟防火阀、钢制排烟防火阀兼排风阀、矩形防烟防火调节阀、多叶排烟口、常闭式铝合金多叶排烟口、电动铝合金多叶防火排烟口、手动铝合金多叶防火排烟口、高气密电动排烟口、水流指示器、末端试水装置、地上水泵结合器、地下水泵结合器、墙壁水泵结合器、微型水泵结合器、室外地上消防栓、室外地下消防栓、甲型双栓消火栓箱、薄型消防水龙卷盘消火栓箱、薄型消防软管卷盘消火栓箱、双栓消防水龙卷盘消火栓箱、试验消火栓箱、光电/感烟探测器、感温探测器、火灾报警控制器、火灾声光报警器、防爆火灾声光报警器、声光报警器、扬声器、应急广播控制器、输入输出模块、单输入/输出模块、总线隔离模块、手自动启停按钮、疏散指示灯、应急吸顶灯、应急照明灯具、钢质防火门、木质防火门、防火卷帘门、钢质防火窗、防火门监控模块、防火门控制器、防火井盖、防火涂料、阻火圈、阻燃板、EPS电源、不锈钢EPS配电柜、CS195+复合防火板、木质防火板、防火型无纺布、堵漏\n\n"

    "【电气材料】— 电气/弱电/智能化\n"
    "  交联聚乙烯绝缘铜芯电缆、交联低烟无卤阻燃铜芯电缆、低烟无卤阻燃交联铜芯电缆、低烟无卤阻燃交联聚乙烯绝缘铜芯电缆、低烟无卤阻燃耐火交联聚乙烯绝缘铜芯电缆、低烟无卤阻燃耐火聚乙烯绝缘电线、阻燃交联聚乙烯绝缘铜芯电缆、阻燃低烟无卤交联聚乙烯绝缘铜芯预分支电缆、耐火交联聚乙烯绝缘铜芯电缆、柔性矿物绝缘电缆、铠装交联低烟无卤阻燃铜芯电缆、铜芯聚氯乙烯绝缘电线、铜芯聚氯乙烯绝缘软线、铜芯聚氯乙烯胶质软线、屏蔽铜芯聚氯乙烯绝缘绞型连接软电线、阻燃聚氯乙烯绝缘屏蔽双绞线、阻燃铜芯聚氯乙烯绝缘聚氯乙烯护套屏蔽双绞软导线、铜芯聚氯乙烯屏蔽线、阻燃聚氯乙烯绝缘双绞线、阻燃绝缘绞型软电线、耐火铜芯聚氯乙烯绝缘双绞线、计算机用屏蔽电缆、市话通信电缆、光缆、单模光纤、LC单模光纤尾纤、光纤跳线、光纤终端盒、机房总光纤配线箱、机架式12口光纤配线架、机架式24口光纤配线架、机架式48口光纤配线架、SFP光模块、千兆光模块、万兆光模块、光纤收发器、数据跳线、分布式电源、LED开关电源、直流电源、服务器机柜、网络机柜、列头柜设备机柜、综合布线箱、母线分线箱、总等电位端子箱、低压母线槽、钢制开关盒、钢制接线盒、塑料接线盒、金属线槽、难燃PVC电线槽、不锈钢槽式桥架、热镀锌槽式桥架、钢制喷塑槽式桥架、铝合金槽式桥架、铝合金梯式桥架、钢制防火喷塑槽式桥架、金属软管活接头、防爆金属软管活接头、柔性灯带、LED灯带、LED筒灯、LED投光灯、LED节能灯、豆胆灯、轨道射灯、洗墙灯、照树泛光灯、地埋泛光灯、埋地灯、庭院灯/高杆灯、草坪灯、隧道专用灯、铝格栅灯、吸顶灯、壁灯、投影灯、单管荧光灯、双管荧光灯、三防灯、感应隔爆灯、门磁开关、被动红外/微波双技术探测器、入侵探测器、含氧量探测器、测温光纤、温湿度变送器、温湿度探测器、缆式静压液位变送器（防爆）、智能照明控制器、智能照明专用模块、智能信号灯机、楼宇对讲系统、楼宇可视对讲系统、出入口现场控制器、门禁成套设备、电锁、开门按钮、巡更点、离线式巡查点、云巡更棒、电话暗插座、单口网络暗插座、双口网络暗插座、电话+网络暗插座、六类非屏蔽模块、四联单控暗开关、三联单控暗开关、三联双控暗开关、双联单控暗开关、双联双控暗开关、单联单控暗开关、单联双控暗开关、声光控延时暗开关、防爆开关、防水防潮隔爆型单联开关、三孔安全插座、五孔安全插座、防水防潮型单联开关、100对110配线架、24口网络配线架、六类非屏蔽双绞线、六类屏蔽双绞线\n\n"

    "【管材管件】— 给排水/燃气管路及阀门\n"
    "  热轧无缝钢管、冷拔无缝钢管、焊接钢管、螺旋焊接钢管、热镀锌钢管、加强级防腐3PE钢管、外环氧内衬水泥砂浆螺旋焊接钢管、直埋式预制保温管、直埋式预制保温管件三通、直埋式预制保温管件弯头、钢丝网骨架塑料（PE）复合管、钢塑复合管、HDPE中空壁缠绕管、HDPE双壁波纹排水管、HDPE缠绕排水管、PE排水管、PE给水管、PE穿孔管、MPVE双壁波纹排水管、MCPE复合管、PE100排水管、PPR热水管、PPR冷水管、PP-R塑料截止阀、UPVC实壁排水管、UPVC实壁螺旋消音排水管、UPVC螺旋中空静音排水管、芯层发泡PVC-U排水塑料管、不锈钢管（SUS304）、不锈钢三通（SUS304）、不锈钢压制90°弯头（SUS304）、不锈钢平焊法兰、不锈钢浮球阀、不锈钢水龙头、铜管、铜制锁闭阀、铜壳旋翼式水表、铜镀铬龙头、热镀锌平焊法兰、热镀锌沟槽法兰、热镀锌沟槽变径管、热镀锌90°沟槽弯头、热镀锌钢制正三通、热镀锌钢制沟槽正三通、热镀锌钢制沟槽正四通、热镀锌钢制沟槽异径四通、热镀锌钢制三通、碳钢平焊法兰、碳钢沟槽法兰、碳钢同心异径管、碳钢压制90°弯头、闸阀、球阀、蝶阀、截止阀、信号闸阀、止回阀、减压阀、自力式压差控制阀、泄压/持压阀、沟槽式闸阀、自动排气阀、Y型过滤器、可曲挠橡胶接头、双法兰限位伸缩接头、金属波纹管、不锈钢金属波纹补偿器、混凝土井盖、球墨铸铁井盖、复合井盖、铸铁井框盖、单篦雨水口井篦（铸铁含井圈）、环保型雨水口井篦（铸铁含井圈截污框）、铸铁卡箍、球墨铸铁给水管（含内外防腐）、球墨铸铁雨水篦、球墨铸铁井篦、可调式井框井盖、复合井框盖、混凝土预制井筒、变径井筒、钢筋混凝土排水管（承插口）、钢筋混凝土排水管（钢承口）、道路U型槽（含盖板）、U型树脂混凝土渗水沟、树脂混凝土U型槽及盖板、屏蔽式树脂成品排水沟（含配套不锈钢盖）、排水沟铸铁篦子、排水沟镀锌钢格板、钢格盖板（集水坑吊装口）、溢流雨水口（方形球墨铸铁）、干式数字冷水表、干式数码水表、数字式冷热水量表、数字式立式热水表、水平数码式热水表、水平数码水表、水平螺翼式水表、立式数码式热水表、立式数码水表、铜壳旋翼式水表、感应水龙头、入墙式龙头（淋浴花洒）、冲洗阀(冲洗龙头)、全铜水龙头、蹲便器、连体坐便器、挂墙式感应一体小便器、普通浴缸（含上下水及配件）、钢板搪瓷浴缸（含上下水及配件）、陶瓷洗脸盆\n\n"

    "请严格从以上分类中选择，不得自行发明新分类。如果品种名称不在列表中，根据其工程用途归入最接近的分类。\n\n"
    "请直接返回 JSON（不带 markdown）：\n\n"
    "{{\n"
    '  "ok": true,\n'
    '  "results": {{\n'
    '    "品种1": {{"category": "分类名", "confidence": 0.95, "note": ""}},\n'
    '    "品种2": {{"category": "分类名", "confidence": 0.88, "note": ""}}\n'
    "  }}\n"
    "}}"
)

PROMPTS["classify_breed_batch"] = {
    "system": _BREED_BATCH_SYSTEM,
    "template": _BREED_BATCH_TEMPLATE,
}

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


    try:
        return tmpl.format(breed=breed, classifications=CLASSIFICATIONS_STR)
    except (KeyError, ValueError):
        return f"品种名称：{breed}\n分类列表：{CLASSIFICATIONS_STR}"


def classify_breed_batch_prompt_fn(breeds: list[str]) -> str:
    """生成 classify-breed-batch API 的 user content"""
    prompts_cfg = PROMPTS.get("classify_breed_batch", {})
    tmpl = prompts_cfg.get("template", "")
    breeds_str = "\n".join(f"{i+1}. {b}" for i, b in enumerate(breeds))
    try:
        return tmpl.format(breeds=breeds_str, classifications=CLASSIFICATIONS_STR)
    except (KeyError, ValueError):
        return f"品种列表：\n{breeds_str}\n\n参考分类列表：\n{CLASSIFICATIONS_STR}"


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

    must_clauses = [{"term": {"needs_spec_parse": True}}]
    if category:
        must_clauses.append({"term": {"category": category}})
    query = {
        "bool": {
            "must": must_clauses,
            "must_not": [
                {"term": {"spec.keyword": "/"}},
                {"term": {"spec.keyword": ""}},
            ]
        }
    }

    try:
        total = es.count(index=idx, body={"query": query}).get("count", 0)
    except Exception:
        total = 0
    if total == 0:
        return []

    # 每个 breed 取 1 条样本（优先取 needs_spec_parse=True 的）
    seen_breeds = {}
    # 多次随机 offset 尽力采集不同 breed
    max_offset = max(0, total - sample_size)
    offset = random.randint(0, max(max_offset, 0)) if max_offset > 0 else 0
    max_allowed_offset = 10000 - sample_size
    if offset > max_allowed_offset:
        offset = random.randint(0, max_allowed_offset)

    body = {
        "size": sample_size,
        "_source": ["spec", "category", "breed", "needs_spec_parse"],
        "query": query,
        "from": offset,
        "sort": [{"_doc": "asc"}],
    }

    try:
        result = es.search(index=idx, body=body)
    except Exception:
        return []

    # 先放 needs_spec_parse=True 的样本（待解析）
    pending = []
    # 再放 needs_spec_parse=False 的样本（已解析）
    resolved = []
    for h in result.get("hits", {}).get("hits", []):
        src = h["_source"]
        spec = src.get("spec", "")
        breed = src.get("breed", "") or ""
        needs_spec_parse = src.get("needs_spec_parse", True)
        has_attr = not needs_spec_parse

        if breed in seen_breeds:
            continue
        seen_breeds[breed] = True
        entry = {
            "spec": spec,
            "category": src.get("category", ""),
            "breed": breed,
            "has_attr": has_attr,
            "needs_spec_parse": needs_spec_parse,
        }
        if needs_spec_parse:
            pending.append(entry)
        else:
            resolved.append(entry)

    # 返回：待解析样本排前面，最多 sample_size 条
    samples = (pending + resolved)[:sample_size]
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
    # needs_spec_parse: True=仍需解析, False=已解析出字段
    # ES boolean term query on missing field behaves unpredictably
    real_aggs_body = {
        "size": 0,
        "aggs": {
            "by_category": {
                "terms": {"field": "category", "size": 60},
                "aggs": {
                    "total_spec": {
                        "filter": {"bool": {"must_not": [{"term": {"spec.keyword": "/"}}, {"term": {"spec.keyword": ""}}]}}
                    },
                    # needs_spec_parse: True=仍需解析（vector无匹配/失败）, False=已解析出字段
                    # 解析成功率 = 已解析出字段的 docs / 总 spec docs
                    "parsed_ok": {
                        "filter": {"bool": {
                            "must": [{"term": {"needs_spec_parse": False}}],
                            "must_not": [{"term": {"spec.keyword": "/"}}, {"term": {"spec.keyword": ""}}]
                        }}
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




@router.get("/api/stats/rules-vector")
def stats_rules_vector(
    attr: str = Query("", description="按属性过滤（空=全部）"),
    category: str = Query("", description="按分类过滤（空=全部）"),
    search: str = Query("", description="搜索 pattern/note/代码片段"),
    page: int = Query(1, description="页码"),
    page_size: int = Query(50, description="每页条数"),
):
    """
    查询 rules_vec.db 中的规则数据（分页 + 过滤 + 搜索）。
    """
    db_path = os.path.join(ETL_CMD_DIR, "parse_spec", "rules", "rules_vec.db")
    if not os.path.exists(db_path):
        raise HTTPException(status_code=404, detail="rules_vec.db 不存在")

    import sqlite3
    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    where_clauses = []
    params = []
    if attr:
        where_clauses.append("attr = ?")
        params.append(attr)
    if category == '（空）':
        where_clauses.append("(category = '' OR category IS NULL)")
    elif category:
        where_clauses.append("category = ?")
        params.append(category)
    if search:
        where_clauses.append("(pattern LIKE ? OR note LIKE ? OR code LIKE ?)")
        s = f"%{search}%"
        params.extend([s, s, s])
    where_sql = " AND ".join(where_clauses) if where_clauses else "1=1"

    c.execute(f"SELECT COUNT(*) FROM breed_spec_rules WHERE {where_sql}", params)
    total = c.fetchone()[0]

    offset = (page - 1) * page_size
    c.execute(
        f"SELECT id, pattern, attr, note, code, breed, category, tokens, created_at "
        f"FROM breed_spec_rules WHERE {where_sql} ORDER BY id DESC LIMIT ? OFFSET ?",
        params + [page_size, offset]
    )
    rows = c.fetchall()
    conn.close()

    items = []
    for r in rows:
        items.append({
            "id": r[0],
            "pattern": r[1],
            "attr": r[2],
            "note": r[3],
            "code": r[4],
            "breed": r[5] or "",
            "category": r[6] or "",
            "tokens": r[7] or "",
            "created_at": r[8],
        })

    conn2 = sqlite3.connect(db_path)
    c2 = conn2.cursor()
    c2.execute("SELECT attr, COUNT(*) FROM breed_spec_rules GROUP BY attr ORDER BY attr")
    attr_options = [{"key": row[0], "count": row[1]} for row in c2.fetchall()]
    conn2.close()

    # Category 列表（用于下拉）
    conn3 = sqlite3.connect(db_path)
    c3 = conn3.cursor()
    c3.execute("SELECT category, COUNT(*) FROM breed_spec_rules GROUP BY category ORDER BY category")
    category_options = [{"key": row[0] or "（空）", "label": row[0] or "（空）", "count": row[1]} for row in c3.fetchall()]
    conn3.close()

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": (total + page_size - 1) // page_size if total else 1,
        "items": items,
        "attr_options": attr_options,
        "category_options": category_options,
    }

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

    # 当抽样为空时给出提示
    msg = None
    if _sample and not samples:
        if category:
            msg = f"分类「{category}」全部 spec 已解析完成，无需抽样。确认新规则后点击「分类清洗」刷新存量数据属性"
        else:
            msg = "所有分类的 spec 已解析完成，无需抽样。确认新规则后点击「分类清洗」刷新存量数据属性"

    return {
        "city": city,
        "samples": samples,
        "coverage": coverage,
        "message": msg,
    }


@router.post("/api/stats/spec-quality/refresh-category")
def refresh_category(
    city: str = Body("xian", description="城市 key"),
    category: str = Body("", description="分类名（为空则刷新全部）"),
):
    """
    直接查询 DWD 中指定分类的数据，重新清洗并回写。
    清洗逻辑与 etl.py 的 transform_doc 共用。
    规则全部确认后调用此接口。
    """
    if not category:
        return {"ok": False, "message": "category 不能为空"}

    dwd_idx_map = {
        "xian": "dwd_xian_price",
        "sichuan": "dwd_sichuan_price",
        "chongqing": "dwd_chongqing_price",
        "jinan": "dwd_jinan_price",
        "rizhao": "dwd_rizhao_price",
    }
    dws_idx_map = {
        "xian": "dws_xian_price",
        "sichuan": "dws_sichuan_price",
        "chongqing": "dws_chongqing_price",
        "jinan": "dws_jinan_price",
        "rizhao": "dws_rizhao_price",
    }
    dwd_idx = dwd_idx_map.get(city)
    if not dwd_idx:
        return {"ok": False, "message": f"未知城市: {city}"}
    dws_idx = dws_idx_map.get(city)

    try:
        sys.path.insert(0, ETL_CMD_DIR)
        from etl import transform_doc, get_parser, ensure_dwd
        import concurrent.futures

        es = Elasticsearch([ES_HOST])

        # 查询 DWD 中该分类的全部 docs
        body = {
            "query": {"term": {"category": category}},
            "size": 500,
            "sort": [{"etl_time": "asc"}],
        }

        resp = es.search(index=dwd_idx, body=body)
        hits = resp["hits"]["hits"]
        total = resp["hits"]["total"]["value"]

        if total == 0:
            return {"ok": True, "message": f"分类「{category}」无数据，跳过", "city": city}

        ok_count = 0
        fail_count = 0

        def _process_batch(batch_hits):
            nonlocal ok_count, fail_count
            for h in batch_hits:
                doc = h["_source"]
                raw = {
                    "breed": doc.get("breed", ""),"spec": doc.get("spec", ""),"unit": doc.get("unit", ""),
                    "price": doc.get("price", 0),"tax_price": doc.get("tax_price", 0),
                    "county": doc.get("county", ""),"province": doc.get("province", ""),
                    "city": doc.get("city", ""),"update_date": doc.get("update_date", ""),"create_time": doc.get("create_time", ""),
                }
                try:
                    dwd_doc = transform_doc(raw, dwd_idx, city)
                    es.index(index=dwd_idx, id=h["_id"], document=dwd_doc)
                    ok_count += 1
                except Exception:
                    fail_count += 1

        _process_batch(hits)
        processed = len(hits)

        # 分页：ES max_result_window=10000，用 search_after 翻页直到全部处理完
        while processed < total:
            last_hit = hits[-1]
            search_after = last_hit.get("sort") or [last_hit["_source"].get("etl_time", "")]
            body_page = {
                "query": {"term": {"category": category}},
                "size": 500,
                "search_after": search_after,
                "sort": [{"etl_time": "asc"}],
            }
            try:
                resp_page = es.search(index=dwd_idx, body=body_page)
            except Exception:
                break
            hits_page = resp_page["hits"]["hits"]
            if not hits_page:
                break
            _process_batch(hits_page)
            processed += len(hits_page)
            hits = hits_page

        # 清洗完成后自动同步 DWD→DWS
        sys.path.insert(0, ETL_CMD_DIR)
        from etl import flush_to_dws as _flush_to_dws
        flush_ok, flush_fail = _flush_to_dws(ES_HOST, city, {"dwd": dwd_idx, "dws": dws_idx}, category=category)


        return {
            "ok": True,
            "message": f"分类「{category}」清洗完成，DWS 同步 {flush_ok} 条（失败 {flush_fail} 条）",
            "total": total,
            "refreshed": ok_count,
            "failed": fail_count,
            "city": city,
            "dws_sync": {"ok": flush_ok, "failed": flush_fail},
        }

    except Exception as e:
        return {"ok": False, "message": str(e)}


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



def _apply_rule_to_base(code_lines: list, attr: str, note: str, pattern: str = "", breed: str = "", category: str = "") -> bool:
    """
    写入规则：向量库为唯一来源，rules/*.py 不再写入。
    """
    code = "\n".join(code_lines)
    if get_vec_store is not None:
        try:
            vs = get_vec_store()
            if pattern and attr:
                vs.insert(
                    pattern=pattern, attr=attr, note=note or "",
                    code=code, breed=breed or "", category=category or "",
                    skip_duplicate=True,
                )
            return "new"
        except Exception as e:
            import logging
            _log = logging.getLogger()
            _log.error("VecStore.insert failed: %s: %s", type(e).__name__, e)
            return False
    return False


def _run_spec_validation_quiet(spec: str = "", attr: str = "", code: str = "") -> tuple:
    """
    验证新规则能否解析指定 spec。
    对 re.search/re.sub 调用直接提取 pattern 测试；对复杂代码走 exec。
    返回 (passed, total)。
    """
    if not spec or not attr or not code:
        return (0, 0)
    try:
        import re as _re_mod, re as _re

        # 尝试直接正则测试：匹配 re.search(r'...', s) 或 re.sub(r'...', r'...', s)
        search_match = _re.search(r're\.search\((r["\'][^"\']+["\'])\s*,\s*s\)', code)
        if search_match:
            raw_pat = search_match.group(1)
            inner = raw_pat[2:-1]  # 不需要翻倍，inner 已是正确字符序列
            try:
                val = _re_mod.search(inner, spec)
                return (1, 1) if val else (0, 1)
            except Exception:
                return (0, 1)

        sub_match = _re.search(r're\.sub\((r["\'][^"\']+["\'])\s*,\s*(r["\'][^"\']+["\'])\s*,\s*s\)', code)
        if sub_match:
            raw_pat = sub_match.group(1)
            inner = raw_pat[2:-1]  # 不需要翻倍，inner 已是正确字符序列
            try:
                val = _re_mod.search(inner, spec)
                return (1, 1) if val else (0, 1)
            except Exception:
                return (0, 1)

        # 兜底：直接 exec（复杂代码场景）
        try:
            exec_globals = {"result": {}, "re": _re_mod, "s": spec}
            exec(code, exec_globals)
            val = exec_globals.get("result", {}).get(attr)
            return (1, 1) if val else (0, 1)
        except Exception:
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

        # Strip python r'...' wrapper first, then fix JSON escapes on the result
        if raw.startswith("r'") or raw.startswith('r"'):
            raw = _strip_r(raw)

        return _fix_json_escapes(raw)

    def extract_code_block_value(obj):
        value_start, marker = find_field_start(obj, "code_block")
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

        # Strip python r'...' wrapper first, then fix JSON escapes on the result
        if raw.startswith("r'") or raw.startswith('r"'):
            raw = _strip_r(raw)
        code = _fix_json_escapes(raw)
        # Strip stray JSON trailing quote/brace from AI malformed JSON
        code = code.rstrip('"}')
        return code

    pattern_val = extract_pattern_value(obj_text)
    code_val = extract_code_block_value(obj_text)
    return pattern_val, code_val



def _strip_r(s):
    """Strip python r'...' or r\"...\" raw string wrapper.
    Handles malformed cases: r'...\" (closing \" from JSON) or missing closing quote.
    """
    if not s:
        return s or ""
    s = s.strip()
    if len(s) < 4:
        return s
    if s.startswith('r"') and s.endswith('"') and len(s) > 2:
        return s[2:-1]
    if s.startswith("r'"):
        for i in range(2, len(s)):
            if s[i] == "'" and (i == 0 or s[i-1] != '\\'):
                return s[2:i]
        last_single = -1
        for i in range(len(s) - 1, 1, -1):
            if s[i] == "'" and (i == 0 or s[i-1] != '\\'):
                last_single = i
                break
        if last_single > 2:
            return s[2:last_single]
        return s[2:]
    return s

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
            # 不处理 \" → " 转换：" 是 JSON raw string 内容的合法部分
            # 由 _strip_r 处理（内嵌转义引号算作内容，不是字符串结束）
            #elif nc == '"':
            #    result.append('"')
            #    i += 2
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
        c = http.client.HTTPConnection("localhost", 18789, timeout=60)
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


@router.post("/api/stats/spec-quality/classify-breed-batch")
def classify_breed_batch_ai(req: ClassifyBreedBatchRequest = Body(...)):
    """
    批量品种分类接口：输入品种列表，AI 批量推断分类，批量写入 rules_vec.db。
    返回 {ok, results: {breed: {category, confidence, note}}}
    """
    import os, re, sqlite3
    breeds = [b.strip() for b in req.breeds if b.strip()]
    if not breeds:
        return {"ok": False, "message": "breeds 不能为空"}

    rules_db = os.path.join(ETL_CMD_DIR, "parse_spec", "rules", "rules_vec.db")
    _rule_re = re.compile(r'^\s*"([^"]+)"\s*→\s*"([^"]+)"', re.MULTILINE)

    # 1. 批量从 rules_vec.db 读取已有规则
    db_results = {}
    unmatched = []
    if os.path.exists(rules_db):
        conn = sqlite3.connect(rules_db)
        c = conn.cursor()
        placeholders = ",".join("?" for _ in breeds)
        c.execute(f"SELECT breed, category, source FROM breed_category_rules WHERE breed IN ({placeholders})", breeds)
        for row in c.fetchall():
            db_results[row[0]] = {"category": row[1], "source": f"db({row[2]})", "confidence": 1.0, "note": ""}
        conn.close()

    # 2. 未命中品种调 AI
    unmatched = [b for b in breeds if b not in db_results]
    ai_results = {}
    if unmatched:
        ai_results = _call_classify_batch_llm(unmatched)
        if not ai_results.get("ok"):
            return ai_results

        # 3. 批量写入 rules_vec.db
        results_map = ai_results.get("results", {})
        to_insert = [(b, r["category"], "ai", r.get("note", ""))
                     for b, r in results_map.items() if r.get("category")]
        if to_insert and os.path.exists(rules_db):
            try:
                conn = sqlite3.connect(rules_db)
                c = conn.cursor()
                c.executemany(
                    "INSERT OR IGNORE INTO breed_category_rules (breed, category, source, note) VALUES (?, ?, ?, ?)",
                    to_insert
                )
                conn.commit()
                conn.close()
            except Exception as e:
                return {"ok": False, "message": f"批量写入数据库失败: {e}"}

    # 4. 合并结果
    final_results = {}
    for b in breeds:
        if b in db_results:
            final_results[b] = db_results[b]
        elif b in ai_results.get("results", {}):
            ai_r = ai_results["results"][b]
            final_results[b] = {
                "category": ai_r.get("category", "其他"),
                "confidence": ai_r.get("confidence", 0),
                "note": ai_r.get("note", ""),
                "source": "ai",
            }
        else:
            final_results[b] = {"category": "其他", "confidence": 0, "note": "", "source": "unknown"}

    return {
        "ok": True,
        "total": len(breeds),
        "matched": len(breeds) - len(unmatched),
        "unmatched": len(unmatched),
        "results": final_results,
    }


def _call_classify_batch_llm(breeds: list[str]) -> dict:
    """调用 OpenClaw LLM 批量推断品种分类"""
    import urllib.request, urllib.error, http.client
    token = ""
    try:
        with open("/Users/pengfit/.openclaw/openclaw.json") as f:
            d = json.load(f)
            token = d.get("gateway", {}).get("auth", {}).get("token", "")
    except Exception:
        return {"ok": False, "message": "无法读取 OpenClaw token"}

    prompt = classify_breed_batch_prompt_fn(breeds)
    system_msg = PROMPTS.get("classify_breed_batch", {}).get("system", "")

    body = json.dumps({
        "model": "openclaw",
        "messages": [
            {"role": "system", "content": system_msg},
            {"role": "user", "content": prompt},
        ],
        "user": "classify-agent",
        "max_tokens": 2048,
        "temperature": 0.1,
    }).encode("utf-8")

    try:
        c = http.client.HTTPConnection("localhost", 18789, timeout=120)
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


@router.get("/api/stats/breed-category-rules")
def list_breed_category_rules(
    keyword: str = "",
    source: str = "",
    category_filter: str = "",
    page: int = 1,
    page_size: int = 50,
    request: Request = None,
):
    """分页查看 breed_category_rules"""
    import sqlite3
    rules_db = os.path.join(ETL_CMD_DIR, "parse_spec", "rules", "rules_vec.db")
    if not os.path.exists(rules_db):
        return {"rules": [], "total": 0, "page": page, "page_size": page_size}

    conn = sqlite3.connect(rules_db)
    c = conn.cursor()

    where = []
    params = []
    if keyword:
        where.append("breed LIKE ?")
        params.append(f"%{keyword}%")
    if source:
        where.append("source = ?")
        params.append(source)
    if category_filter:
        where.append("category = ?")
        params.append(category_filter)

    where_sql = " AND ".join(where) if where else "1=1"
    distinct = request.query_params.get("distinct_categories")
    if distinct:
        c.execute("SELECT DISTINCT category FROM breed_category_rules WHERE category != '' ORDER BY category")
        rows = c.fetchall()
        conn.close()
        return {"categories": [r[0] for r in rows]}


    c.execute(f"SELECT COUNT(*) FROM breed_category_rules WHERE {where_sql}", params)
    total = c.fetchone()[0]

    offset = (page - 1) * page_size
    c.execute(
        f"SELECT id, breed, category, source, note, jaccard_cache, created_at FROM breed_category_rules WHERE {where_sql} ORDER BY id DESC LIMIT ? OFFSET ?",
        params + [page_size, offset]
    )
    rows = c.fetchall()
    conn.close()

    rules = [
        {
            "id": r[0], "breed": r[1], "category": r[2], "source": r[3],
            "note": r[4] or "", "jaccard_cache": r[5], "created_at": r[6],
        }
        for r in rows
    ]
    return {"rules": rules, "total": total, "page": page, "page_size": page_size}


@router.post("/api/stats/breed-category-rules")
def create_breed_category_rule(req: dict = Body(...)):
    """手动添加 breed→category 规则"""
    import sqlite3
    breed = (req.get("breed") or "").strip()
    category = (req.get("category") or "").strip()
    note = (req.get("note") or "").strip()
    source = req.get("source", "manual") or "manual"

    if not breed or not category:
        return {"ok": False, "message": "breed 和 category 不能为空"}

    rules_db = os.path.join(ETL_CMD_DIR, "parse_spec", "rules", "rules_vec.db")
    try:
        conn = sqlite3.connect(rules_db)
        c = conn.cursor()
        c.execute(
            "INSERT OR REPLACE INTO breed_category_rules (breed, category, source, note) VALUES (?, ?, ?, ?)",
            (breed, category, source, note)
        )
        conn.commit()
        rule_id = c.lastrowid
        conn.close()
        return {"ok": True, "id": rule_id, "message": "规则已保存"}
    except Exception as e:
        return {"ok": False, "message": str(e)}


@router.delete("/api/stats/breed-category-rules/{rule_id}")
def delete_breed_category_rule(rule_id: int):
    """删除指定规则"""
    import sqlite3
    rules_db = os.path.join(ETL_CMD_DIR, "parse_spec", "rules", "rules_vec.db")
    try:
        conn = sqlite3.connect(rules_db)
        c = conn.cursor()
        c.execute("DELETE FROM breed_category_rules WHERE id=?", (rule_id,))
        conn.commit()
        affected = c.rowcount
        conn.close()
        return {"ok": affected > 0, "message": "已删除" if affected else "未找到"}
    except Exception as e:
        return {"ok": False, "message": str(e)}


@router.post("/api/stats/breed-category-rules/test")
def test_breed_category_rule(req: dict = Body(...)):
    """测试品种名 Jaccard 召回"""
    import sys, os as os_module
    sys.path.insert(0, ETL_CMD_DIR)
    try:
        from breed_category import jaccard_breed_classify
        breed = (req.get("breed") or "").strip()
        if not breed:
            return {"hit": False, "score": 0, "category": ""}
        cat = jaccard_breed_classify(breed)
        return {"hit": bool(cat), "score": 0, "category": cat}
    except Exception as e:
        return {"hit": False, "score": 0, "category": "", "error": str(e)}


        return {"ok": False, "message": f"AI 返回格式错误: {e}"}
    except Exception as e:
        return {"ok": False, "message": f"AI 分析异常: {e}"}




class ClassifyBreedBatchRequest(BaseModel):
    breeds: list[str]
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
        all_suggestions = list(req.suggestions) if req.suggestions else []
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
        result = _apply_rule_to_base(
            code_block, s["attr"], s["note"], s.get("pattern", ""),
            req.breed or s.get("breed", ""), req.category or s.get("category", ""),
        )
        if result is False:
            return {"ok": False, "message": "规则写入失败，已 rollback", "spec": spec}
        if result == "new":
            wrote_new = True
        code_str = "\n".join(code_block)
        passed, total = _run_spec_validation_quiet(spec, s["attr"], code_str)
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
            "message": "规则已存在，无需录入。",
            "etl_ok": True,
        }

    return {
        "ok": True,
        "mode": "confirm",
        "spec": spec,
        "expected": expected,
        "message": "规则已录入规则库。清洗请通过「分类清洗」按钮触发",
        "etl_ok": False,
    }

