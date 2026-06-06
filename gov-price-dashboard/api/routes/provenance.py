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
sys.path.insert(0, os.path.join(ETL_CMD_DIR, "classify"))

try:
    from parse_spec.rules.vector_store import get_vec_store
except Exception:
    get_vec_store = None

router = APIRouter()


ES_HOST = "http://localhost:59200"

# ── ETL classify/jaccard 批量写入接口 ──────────────
from rules.jaccard import batch_insert_breed_rules

# 城市配置：city key → (dws_idx, ods_idx, dwd_idx, 标签)
CITY_INDEXES = {
    "xian":      {"dws": "dws_xian_price",      "ods": "ods_material_xian_price",      "dwd": "dwd_xian_price",      "label": "西安"},
    "sichuan":   {"dws": "dws_sichuan_price",   "ods": "ods_material_sichuan_price",   "dwd": "dwd_sichuan_price",   "label": "四川"},
    "chongqing": {"dws": "dws_chongqing_price", "ods": "ods_material_chongqing_price", "dwd": "dwd_chongqing_price", "label": "重庆"},
    "jinan":     {"dws": "dws_jinan_price",     "ods": "ods_material_jinan_price",     "dwd": "dwd_jinan_price",     "label": "济南"},
    "rizhao":    {"dws": "dws_rizhao_price",    "ods": "ods_material_rizhao_price",    "dwd": "dwd_rizhao_price",    "label": "日照"},
}

# 全部城市索引汇总
ALL_INDICES = "dwd_xian_price,dwd_sichuan_price,dwd_chongqing_price,dwd_jinan_price,dwd_rizhao_price"
ALL_ODS_INDICES = "ods_material_xian_price,ods_material_sichuan_price,ods_material_chongqing_price,ods_material_jinan_price,ods_material_rizhao_price"
ALL_DWD_INDICES = "dwd_xian_price,dwd_sichuan_price,dwd_chongqing_price,dwd_jinan_price,dwd_rizhao_price"

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


from rules.jaccard import batch_insert_breed_rules

_RULES_DB = os.path.join(ETL_CMD_DIR, "parse_spec", "rules", "rules_vec.db")
_RULES_DB_CAT = os.path.join(ETL_CMD_DIR, "classify", "rules", "breed_category_rules.db")
_RULES_DB_SPEC = os.path.join(ETL_CMD_DIR, "parse_spec", "rules", "breed_spec_rules.db")

def _ensure_rules_table():
    """"确保 breed_category_rules 表存在且结构最新（幂等）"""
    if not os.path.exists(_RULES_DB_CAT):
        return
    conn = sqlite3.connect(_RULES_DB_CAT)
    c = conn.cursor()
    c.execute(
        "CREATE TABLE IF NOT EXISTS breed_category_rules ("
        "  id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "  breed TEXT UNIQUE NOT NULL, "
        "  category TEXT NOT NULL, "
        "  source TEXT DEFAULT 'ai', "
        "  confidence REAL DEFAULT 1.0, "
        "  note TEXT DEFAULT '', "
        "  created_at TEXT DEFAULT (date('now'))"
        ")"
    )
    conn.commit()
    conn.close()


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


@router.post("/api/scrape/check")
def api_scrape_check(city: str = Body("...", embed=True)):
    """
    触发指定城市的增量检测（check），判断源站是否有更新。
    实际执行 skill 目录下的 check.py 脚本。
    """
    city_script_map = {
        "xian":      ("xa-material-price",   "check"),
        "sichuan":   ("sichuan-price",        "check"),
        "chongqing": ("chongqing-price",      "check"),
        "jinan":     ("jinan-price",          "check"),
        "rizhao":    ("rizhao-price",         "check"),
    }
    if city not in city_script_map:
        raise HTTPException(status_code=400, detail=f"未知城市: {city}")

    skill_name, cmd = city_script_map[city]
    script_dir = f"/Users/pengfit/.openclaw/workspace/skills/{skill_name}"
    run_sh = os.path.join(script_dir, "run.sh")

    try:
        result = subprocess.run(
            [run_sh, cmd],
            capture_output=True, text=True, timeout=120,
            cwd=script_dir,
        )
        return {
            "ok": True,
            "city": city,
            "returncode": result.returncode,
            "stdout": result.stdout[:2000],
            "stderr": result.stderr[:1000],
        }
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=408, detail="增量检测超时（120s）")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


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
                runs_buckets = r["aggregations"]["runs"]["buckets"]

                if runs_buckets:
                    lat = runs_buckets[0]
                    lu = (lat.get("latest_ts", {}).get("value_as_string", "") or "")[:19]
                    ch = lat.get("counties", {}).get("hits", {}).get("hits", [])
                    run_id = lat["key"]
                else:
                    lu, ch = "", []
                    run_id = None

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
        ods_idx = ALL_ODS_INDICES
        dwd_idx = ALL_DWD_INDICES
        dws_idx = dwd_idx
        city_label = "全部城市"
    else:
        cfg = CITY_INDEXES[city]
        ods_idx = cfg["ods"]
        dwd_idx = cfg["dwd"]
        dws_idx = cfg["dws"]
        city_label = cfg["label"]

    try:
        # ── 1. 各省份最新数据日期 + 记录数 ──────────────────────
        prov_body = {
            "size": 0,
            "aggs": {
                "by_province": {
                    "terms": {"field": "province", "size": 50},
                    "aggs": {
                        "max_date": {"max": {"field": "etl_time"}},
                        "min_date": {"min": {"field": "date"}},
                        "cnt": {"value_count": {"field": "price"}},
                    }
                }
            }
        }
        prov_result = es.search(index=dwd_idx, body=prov_body)
        prov_buckets = prov_result["aggregations"]["by_province"]["buckets"]

        # ── 2. 近30天每日入库量 ─────────────────────────────────
        daily_body = {
            "size": 0,
            "query": {"range": {"etl_time": {"gte": "now-7d"}}},
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
        daily_result = es.search(index=dwd_idx, body=daily_body)
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
                        "max_date": {"max": {"field": "etl_time"}},
                    }
                }
            }
        }
        city_result = es.search(index=dwd_idx, body=city_body)
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
            count_resp = es.count(index=dwd_idx)
            total_count = count_resp["count"]
        except Exception:
            total_body = {"query": {"match_all": {}}, "size": 0, "track_total": True}
            total_r = es.search(index=dwd_idx, body=total_body)
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
            province_list.append({
                "province": b["key"],
                "count": b["doc_count"],
                
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
            r1 = pool.submit(es.count, index=dwd_idx,
                body={"query": {"range": {"etl_time": {"gte": "now-7d"}}}})
            r2 = pool.submit(es.count, index=dwd_idx,
                body={"query": {"range": {"etl_time": {"gte": "now-14d", "lt": "now-7d"}}}})
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

        # ── 8. 所有城市完整链路状态（ODS→DWD→DWS + 抓取进度）───
        scrape_all = stats_scrape_progress_all()
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
                scrape_k = scrape_all.get(k, {})
                all_pipelines[k] = {
                    "city": k,
                    "city_label": CITY_INDEXES[k]["label"],
                    "ods": ods_s,
                    "dwd": dwd_s,
                    "dws": dws_s,
                    "sync_ok": sync_ok_c,
                    "status": "ok" if sync_ok_c else "out_of_sync",
                    "scrape": {
                        "latest_run_id": scrape_k.get("latest_run_id"),
                        "last_updated": scrape_k.get("last_updated", ""),
                        "total_docs": scrape_k.get("total_docs", 0),
                        "completed": scrape_k.get("completed", 0),
                        "running": scrape_k.get("running", 0),
                        "error": scrape_k.get("error", 0),
                        "total_counties": scrape_k.get("total_counties", 0),
                        "counties": scrape_k.get("counties", []),
                    },
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
            return yaml.safe_load(f) or {}
    except Exception:
        return {}

PROMPTS = _load_prompts()

def _reload_prompts():
    global PROMPTS, _ATTR_NAMES_CACHE
    PROMPTS = _load_prompts()
    _ATTR_NAMES_CACHE = ([], 0.0)  # 清空属性名缓存，下次使用时重新加载
    print("[prompts] reloaded")

@router.post("/api/prompts/reload")
def reload_prompts():
    """热重载 prompts.yml"""
    _reload_prompts()
    return {"ok": True, "keys": list(PROMPTS.keys())}

def _get_ref_attr_names_from_db() -> list[str]:
    """从 breed_spec_rules.db 读取已有属性名（去 attr_ 前缀）"""
    try:
        conn = sqlite3.connect(_RULES_DB_SPEC)
        cur = conn.cursor()
        cur.execute("SELECT DISTINCT attr FROM breed_spec_rules")
        names = [r[0].replace("attr_", "") for r in cur.fetchall() if r[0].startswith("attr_")]
        conn.close()
        return sorted(names)
    except Exception:
        return []

# 缓存属性名列表（每 5 分钟刷新一次）
_ATTR_NAMES_CACHE: tuple[list[str], float] = ([], 0.0)

def _get_ref_attr_names() -> str:
    global _ATTR_NAMES_CACHE
    import time
    names, ts = _ATTR_NAMES_CACHE
    if not names or (time.time() - ts) > 300:
        names = _get_ref_attr_names_from_db()
        _ATTR_NAMES_CACHE = (names, time.time())
    return ", ".join(names)

def fix_case_prompt_fn(spec, breed="", category="", expected=None):
    """生成 fix-case API 的 user content（fix-case 端点专用）"""
    prompts_cfg = PROMPTS.get("fix_case", {})
    tmpl = prompts_cfg.get("template", "")
    breed_hint = f"{breed}" if breed else ""
    cat_hint = f"{category}" if category else ""
    attr_desc = ", ".join(f"{k}({v})" for k, v in ATTR_FIELDS_MAP.items())
    expected_json = json.dumps(expected or {}, ensure_ascii=False)
    ref_attr_names = _get_ref_attr_names()
    return tmpl.format(
            spec=spec,
            breed_hint=breed_hint,
            cat_hint=cat_hint,
            ref_attr_names=ref_attr_names,
        )


def classify_breed_batch_prompt_fn(breeds: list[str]) -> str:
    """生成 classify-breed-batch API 的 user content"""
    prompts_cfg = PROMPTS.get("classify_breed_batch", {})
    tmpl = prompts_cfg.get("template", "")
    breeds_str = "\n".join(f"{i+1}. {b}" for i, b in enumerate(breeds))
    try:
        return tmpl.format(breeds=breeds_str)
    except (KeyError, ValueError):
        return f"品种列表：\n{breeds_str}\n\n参考分类列表：\n"


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

    must_clauses = []
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

    # 每个 breed 取 1 条样本
    seen_breeds = {}
    # 多次随机 offset 尽力采集不同 breed
    max_offset = max(0, total - sample_size)
    offset = random.randint(0, max(max_offset, 0)) if max_offset > 0 else 0
    max_allowed_offset = 10000 - sample_size
    if offset > max_allowed_offset:
        offset = random.randint(0, max_allowed_offset)

    body = {
        "size": sample_size,
        "_source": ["spec", "category", "breed"],
        "query": query,
        "from": offset,
        "sort": [{"_doc": "asc"}],
    }

    try:
        result = es.search(index=idx, body=body)
    except Exception:
        return []

    resolved = []
    for h in result.get("hits", {}).get("hits", []):
        src = h["_source"]
        spec = src.get("spec", "")
        breed = src.get("breed", "") or ""
        has_attr = bool(src.get("attr"))

        if breed in seen_breeds:
            continue
        seen_breeds[breed] = True
        entry = {
            "spec": spec,
            "category": src.get("category", ""),
            "breed": breed,
            "has_attr": has_attr,
        }
        resolved.append(entry)

    samples = resolved[:sample_size]
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
    real_aggs_body = {
        "size": 0,
        "aggs": {
            "by_category": {
                "terms": {"field": "category", "size": 60},
                "aggs": {
                    "total_spec": {
                        "filter": {"bool": {"must_not": [{"term": {"spec.keyword": "/"}}, {"term": {"spec.keyword": ""}}]}}
                    },
                    # 解析成功率 = 已解析出字段的 docs / 总 spec docs
                    "parsed_ok": {
                        "filter": {"bool": {
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
    coverage.sort(key=lambda x: x["rate"], reverse=True)
    return coverage




@router.get("/api/stats/rules-vector")
def stats_rules_vector(
    attr: str = Query("", description="按属性过滤（空=全部）"),
    category: str = Query("", description="按分类过滤（空=全部）"),
    search: str = Query("", description="搜索 pattern/note/代码片段"),
    order: str = Query("desc", description="排序方向：asc / desc"),
    page: int = Query(1, description="页码"),
    page_size: int = Query(50, description="每页条数"),
):
    """
    查询 rules_vec.db 中的规则数据（分页 + 过滤 + 搜索）。
    """
    db_path = _RULES_DB_SPEC
    if not os.path.exists(db_path):
        raise HTTPException(status_code=404, detail="breed_spec_rules.db 不存在")

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
    order = order.lower() if order.lower() in ("asc", "desc") else "desc"
    c.execute(
        f"SELECT id, pattern, attr, note, code, breed, category, tokens, created_at "
        f"FROM breed_spec_rules WHERE {where_sql} ORDER BY id {order.upper()} LIMIT ? OFFSET ?",
        params + [page_size, offset]
    )
    rows = c.fetchall()
    conn.close()

    def _cat_sys_map():
        import json
        p = os.path.join(ETL_CMD_DIR, "classify", "rules", "category_in_system.json")
        try:
            with open(p) as f:
                raw = json.load(f) or {}
            result = {}
            for cat in raw.get("categories", []):
                sys_name = cat.get("name", "")
                for child in cat.get("children", []):
                    cat_name = child.get("name", "")
                    if cat_name and sys_name:
                        result[cat_name] = sys_name
            return result
        except Exception:
            return {}

    cat_sys_map = _cat_sys_map()

    items = []
    for r in rows:
        cat = r[6] or ""
        items.append({
            "id": r[0],
            "pattern": r[1],
            "attr": r[2],
            "note": r[3],
            "code": r[4],
            "breed": r[5] or "",
            "category": cat,
            "category_system": cat_sys_map.get(cat, ""),
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
        body_total = {
            "query": {"bool": {"must": [{"term": {"category": category}}]}},
            "size": 0,
        }
        resp_total = es.search(index=dwd_idx, body=body_total)
        total = resp_total["hits"]["total"]["value"]

        body = {
            "query": {"bool": {"must": [{"term": {"category": category}}]}},
            "size": 500,
            "sort": [{"etl_time": "asc"}],
        }

        resp = es.search(index=dwd_idx, body=body)
        hits = resp["hits"]["hits"]

        if total == 0:
            return {"ok": True, "message": f"分类「{category}」无待清洗数据", "city": city}

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
                "query": {"bool": {"must": [{"term": {"category": category}}]}},
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


@router.post("/api/stats/provenance/flush-city")
def flush_city_dws(
    city: str = Body(..., embed=True),
):
    """
    与 refresh-category 逻辑一致：
    1. 查询 DWD 中的全部记录
    2. 用 transform_doc（规则库，非 AI）重新解析并回写 DWD
    3. 调用 flush_to_dws 同步到 DWS
    """
    dwd_idx_map = {
        "xian":      "dwd_xian_price",
        "sichuan":   "dwd_sichuan_price",
        "chongqing": "dwd_chongqing_price",
        "jinan":     "dwd_jinan_price",
        "rizhao":    "dwd_rizhao_price",
    }
    dws_idx_map = {
        "xian":      "dws_xian_price",
        "sichuan":   "dws_sichuan_price",
        "chongqing": "dws_chongqing_price",
        "jinan":     "dws_jinan_price",
        "rizhao":    "dws_rizhao_price",
    }
    dwd_idx = dwd_idx_map.get(city)
    dws_idx = dws_idx_map.get(city)
    if not dwd_idx:
        return {"ok": False, "message": f"未知城市: {city}"}

    try:
        sys.path.insert(0, ETL_CMD_DIR)
        from etl import transform_doc

        es = Elasticsearch([ES_HOST])

        # 统计待清洗记录数
        body_total = {
            "query": {"bool": {"must": []}},
            "size": 0,
        }
        resp_total = es.search(index=dwd_idx, body=body_total)
        total = resp_total["hits"]["total"]["value"]

        if total == 0:
            return {
                "ok": True,
                "city": city,
                "message": "无待解析数据，跳过 DWS 同步",
                "dwd_reparsed": 0,
                "dws_synced": 0,
                "dws_failed": 0,
            }

        body = {
            "query": {"bool": {"must": []}},
            "size": 500,
            "sort": [{"etl_time": "asc"}],
        }
        resp = es.search(index=dwd_idx, body=body)
        hits = resp["hits"]["hits"]

        ok_count = 0
        fail_count = 0

        def _process_batch(batch_hits):
            nonlocal ok_count, fail_count
            for h in batch_hits:
                doc = h["_source"]
                raw = {
                    "breed": doc.get("breed", ""),
                    "spec": doc.get("spec", ""),
                    "unit": doc.get("unit", ""),
                    "price": doc.get("price", 0),
                    "tax_price": doc.get("tax_price", 0),
                    "county": doc.get("county", ""),
                    "province": doc.get("province", ""),
                    "city": doc.get("city", ""),
                    "update_date": doc.get("update_date", ""),
                    "create_time": doc.get("create_time", ""),
                }
                try:
                    dwd_doc = transform_doc(raw, dwd_idx, city)
                    es.index(index=dwd_idx, id=h["_id"], document=dwd_doc)
                    ok_count += 1
                except Exception:
                    fail_count += 1

        _process_batch(hits)
        processed = len(hits)

        while processed < total:
            last_hit = hits[-1]
            search_after = last_hit.get("sort") or [last_hit["_source"].get("etl_time", "")]
            body_page = {
                "query": {"bool": {"must": []}},
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

        # 解析完成后同步 DWD→DWS
        # 先 refresh DWD，确保 flush_to_dws 能读到最新解析结果
        es.indices.refresh(index=dwd_idx)
        from etl import flush_to_dws as _flush_to_dws
        flush_ok, flush_fail = _flush_to_dws(ES_HOST, city, {"dwd": dwd_idx, "dws": dws_idx})

        return {
            "ok": True,
            "city": city,
            "dwd_reparsed": ok_count,
            "dwd_failed": fail_count,
            "dws_synced": flush_ok,
            "dws_failed": flush_fail,
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


def _apply_rule_to_base(code_lines: list, attr: str, note: str, pattern: str = "", breed: str = "", category: str = "") -> str | bool:
    """
    写入规则：向量库为唯一来源，rules/*.py 不再写入。
    skip_duplicate=True 时：
      - insert 成功（新增）→ 返回 "new"
      - insert 返回 False（规则已存在）→ 返回 "duplicate"（非失败）
      - 异常 → 返回 False
    """
    code = "\n".join(code_lines)
    if get_vec_store is not None:
        try:
            vs = get_vec_store()
            if pattern and attr:
                ok = vs.insert(
                    pattern=pattern, attr=attr, note=note or "",
                    code=code, breed=breed or "", category=category or "",
                    skip_duplicate=True,
                )
                if ok:
                    return "new"
                # skip_duplicate=True: insert 返回 False = 规则已存在
                return "duplicate"
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
        import re as _re_mod
        exec_globals = {"result": {}, "re": _re_mod, "s": spec}
        exec(code, exec_globals)
        val = exec_globals.get("result", {}).get(attr)
        return (1, 1) if val else (0, 1)
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

    def _extract_json_string_field(obj, field_name):
        """Extract a JSON string field value by finding unescaped closing quote.
        Properly handles JSON field values that contain escaped quotes.
        """
        # Find "fieldname":
        idx = obj.find('"' + field_name + '":')
        if idx < 0:
            return ""
        # Find the opening " of the value (first " after the field name)
        search_start = idx + len(field_name) + 3  # +3 for '": '
        first_quote = obj.find('"', search_start)
        if first_quote < 0:
            return ""
        # Find the closing unescaped "
        i = first_quote + 1
        while i < len(obj):
            if obj[i] == '\\':
                i += 2
            elif obj[i] == '"':
                return obj[first_quote+1:i]
            else:
                i += 1
        return ""

    def extract_pattern_value(obj):
        raw = _extract_json_string_field(obj, "pattern")
        if raw.startswith("r'") or raw.startswith('r"') or raw.startswith('r\\"'):
            raw = _strip_r(raw)
        return _fix_json_escapes(raw)

    def extract_code_block_value(obj):
        raw = _extract_json_string_field(obj, "code_block")
        if raw.startswith("r'") or raw.startswith('r"') or raw.startswith('r\\"'):
            raw = _strip_r(raw)
        code = _fix_json_escapes(raw)
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
    # Handle r\"..." (JSON-escaped double quotes from AI)
    if s.startswith('r\"') and len(s) > 4:
        end_pattern = '\"'
        end_idx = s.rfind(end_pattern)
        if end_idx > 3:
            return s[3:end_idx]
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
    import re, sqlite3
    breeds = [b.strip() for b in req.breeds if b.strip()]
    if not breeds:
        return {"ok": False, "message": "breeds 不能为空"}

    _ensure_rules_table()
    _rule_re = re.compile(r'^\s*"([^"]+)"\s*→\s*"([^"]+)"', re.MULTILINE)

    # 1. 批量从 breed_category_rules.db 读取已有规则
    db_results = {}
    unmatched = []
    if os.path.exists(_RULES_DB_CAT):
        conn = sqlite3.connect(_RULES_DB_CAT)
        c = conn.cursor()
        placeholders = ",".join("?" for _ in breeds)
        c.execute(f"SELECT breed, category, source, confidence FROM breed_category_rules WHERE breed IN ({placeholders})", breeds)
        for row in c.fetchall():
            db_results[row[0]] = {"category": row[1], "source": f"db({row[2]})", "confidence": row[3] if row[3] is not None else 1.0, "note": ""}
        conn.close()

    # 2. 未命中品种调 AI
    unmatched = [b for b in breeds if b not in db_results]
    ai_results = {}
    if unmatched:
        ai_results = _call_classify_batch_llm(unmatched)
        if not ai_results.get("ok"):
            return ai_results

        # 3. 批量写入 breed_category_rules.db
        results_map = ai_results.get("results", {})
        to_insert = [(b, r["category"], "ai", r.get("confidence", 1.0), r.get("note", ""))
                     for b, r in results_map.items() if r.get("category")]
        if to_insert:
            batch_insert_breed_rules(to_insert)

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


@router.delete("/api/stats/breed-category-rules")
def delete_breed_category_rules():
    """清空 breed_category_rules 全部规则"""
    import sqlite3
    _ensure_rules_table()
    if not os.path.exists(_RULES_DB_CAT):
        return {"ok": True, "deleted": 0}
    conn = sqlite3.connect(_RULES_DB_CAT)
    c = conn.cursor()
    c.execute("DELETE FROM breed_category_rules")
    deleted = c.rowcount
    conn.commit()
    conn.close()
    return {"ok": True, "deleted": deleted}

@router.get("/api/stats/breed-category-rules")
def list_breed_category_rules(
    keyword: str = "",
    source: str = "",
    category_filter: str = "",
    distinct_categories: int = 0,
    page: int = 1,
    page_size: int = 50,
):
    """分页查看 breed_category_rules
    - distinct_categories=1: 返回所有分类列表（用于下拉）
    """
    import sqlite3
    _ensure_rules_table()
    if not os.path.exists(_RULES_DB_CAT):
        return {"rules": [], "total": 0, "page": page, "page_size": page_size}

    conn = sqlite3.connect(_RULES_DB_CAT)
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
    if distinct_categories:
        c.execute("SELECT DISTINCT category FROM breed_category_rules WHERE category != '' ORDER BY category")
        rows = c.fetchall()
        conn.close()
        return {"categories": [r[0] for r in rows]}


    c.execute(f"SELECT COUNT(*) FROM breed_category_rules WHERE {where_sql}", params)
    total = c.fetchone()[0]

    offset = (page - 1) * page_size
    c.execute(
        f"SELECT id, breed, category, source, confidence, note, created_at FROM breed_category_rules WHERE {where_sql} ORDER BY id DESC LIMIT ? OFFSET ?",
        params + [page_size, offset]
    )
    rows = c.fetchall()
    conn.close()

    rules = [
        {
            "id": r[0], "breed": r[1], "category": r[2], "source": r[3],
            "confidence": r[4], "note": r[5] or "", "created_at": r[6],
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

    _ensure_rules_table()
    try:
        conn = sqlite3.connect(_RULES_DB_CAT)
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
    _ensure_rules_table()
    try:
        conn = sqlite3.connect(_RULES_DB_CAT)
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
        sys.path.insert(0, os.path.join(ETL_CMD_DIR, 'classify', 'rules'))
        from jaccard import jaccard_breed_classify
        breed = (req.get("breed") or "").strip()
        if not breed:
            return {"hit": False, "score": 0, "category": ""}
        cat, score = jaccard_breed_classify(breed)
        return {"hit": bool(cat), "score": round(score, 3), "category": cat}
    except Exception as e:
        return {"hit": False, "score": 0, "category": "", "error": str(e)}

class ClassifyBreedBatchRequest(BaseModel):
    breeds: list[str]
    city: str = "xian"


class BatchSpecParseRequest(BaseModel):
    items: list[dict]  # [{spec, breed, category}, ...]
    batch_size: int = 30
    city: str = "xian"
    write_rules: bool = True  # 是否将成功的解析写回规则库


def batch_spec_parse_prompt_fn(items: list[dict], batch_size: int = 30) -> str:
    """生成批量规格解析的 user content（继承 fix_case 规则体系）"""
    prompts_cfg = PROMPTS.get("batch_spec_parse", {})
    tmpl = prompts_cfg.get("template", "")
    ref_attr_names = _get_ref_attr_names()
    lines = []
    for i, item in enumerate(items[:batch_size]):
        spec = item.get("spec", "")
        breed = item.get("breed", "")
        cat = item.get("category", "")
        lines.append(f'规格文本: {spec} ，产品提示: {breed} ，分类提示: {cat}')
    specs_str = "\n".join(lines)
    try:
        return tmpl.replace("{specs_str}", specs_str).replace("{batch_size}", str(batch_size)).replace("{ref_attr_names}", ref_attr_names)
    except (KeyError, ValueError):
        specs_sample = "\n".join(lines)
        return f"specs:\n{specs_sample}\n\nbatch_size: {batch_size}\n"

def _call_batch_spec_parse_llm(items: list[dict], batch_size: int = 30) -> dict:
    """调用 OpenClaw LLM 批量解析规格文本，返回 [{spec, ok, attr, failed_reason}, ...]"""
    import urllib.request, urllib.error, http.client
    token = ""
    try:
        with open("/Users/pengfit/.openclaw/openclaw.json") as f:
            d = json.load(f)
            token = d.get("gateway", {}).get("auth", {}).get("token", "")
    except Exception:
        return {"ok": False, "message": "无法读取 OpenClaw token"}

    prompt = batch_spec_parse_prompt_fn(items, batch_size)
    system_msg = PROMPTS.get("batch_spec_parse", {}).get("system", "你是一个建材规格解析专家。")

    body = json.dumps({
        "model": "openclaw",
        "messages": [
            {"role": "system", "content": system_msg},
            {"role": "user", "content": prompt},
        ],
        "user": "batch-spec-parse-agent",
        "max_tokens": 4096,
        "temperature": 0.1,
    }).encode("utf-8")

    try:
        c = http.client.HTTPConnection("localhost", 18789, timeout=300)
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
        # 解析 JSON 数组
        result = json.loads(content)
        if isinstance(result, list):
            return {"ok": True, "results": result}
        return {"ok": False, "message": "AI 返回不是 JSON 数组"}
    except urllib.error.URLError as e:
        return {"ok": False, "message": f"OpenClaw 连接失败: {e}"}
    except json.JSONDecodeError as e:
        return {"ok": False, "message": f"AI 返回格式错误: {e}"}
    except Exception as e:
        return {"ok": False, "message": f"AI 分析异常: {e}"}


@router.post("/api/stats/spec-quality/batch-spec-parse")
def batch_spec_parse(req: BatchSpecParseRequest = Body(...)):
    """
    批量规格解析接口：输入 [{spec, breed, category}, ...]，AI 批量解析为 attr 结构。
    成功后可选写入规则库（write_rules=True）。
    返回 {ok, results: [{spec, ok, attr, failed_reason}], rules_written}
    """
    items = [{"spec": i.get("spec", ""), "breed": i.get("breed", ""), "category": i.get("category", "")}
             for i in req.items if i.get("spec")]
    if not items:
        return {"ok": False, "message": "items 不能为空"}

    # 按 category 分批，避免混淆
    from collections import defaultdict
    by_cat: dict[str, list] = defaultdict(list)
    for item in items:
        by_cat[item["category"]].append(item)

    all_results = []
    rules_written = 0

    for cat, cat_items in by_cat.items():
        for i in range(0, len(cat_items), req.batch_size):
            batch = cat_items[i:i + req.batch_size]
            ai_result = _call_batch_spec_parse_llm(batch, req.batch_size)
            if not ai_result.get("ok"):
                # 本批失败，标记全部为失败
                for item in batch:
                    all_results.append({"spec": item["spec"], "ok": False, "attr": {}, "failed_reason": ai_result.get("message", "")})
                continue
            results = ai_result.get("results", [])
            for r in results:
                suggestions = r.get("suggestions", [])
                ok = r.get("ok", False)
                # 从 suggestions 提取 attr
                attr = {}
                for s in suggestions:
                    attr_name = s.get("attr", "")
                    if not attr_name:
                        continue
                    # 提取 value
                    code_block = s.get("code_block", "")
                    pattern = s.get("pattern", "")
                    # 从 code_block 执行结果取 value（简化）
                    if code_block:
                        try:
                            import re as re_mod
                            exec_globals = {"result": {}, "re": re_mod, "s": r.get("spec", "")}
                            exec(code_block if isinstance(code_block, str) else "\n".join(code_block), exec_globals)
                            attr.update(exec_globals.get("result", {}))
                        except Exception:
                            pass
                all_results.append({
                    "spec": r.get("spec", ""),
                    "ok": ok,
                    "suggestions": suggestions,
                })
                # 写入规则库
                if req.write_rules and ok and suggestions:
                    if get_vec_store is not None:
                        vs = get_vec_store()
                        for s in suggestions:
                            ok2 = vs.insert(
                                pattern=s.get("pattern", ""),
                                attr=s.get("attr", ""),
                                note=s.get("note", "ai-batch"),
                                code=s.get("code_block", "") if isinstance(s["code_block"], str) else "\n".join(s["code_block"]),
                                breed=r.get("breed", ""),
                                category=cat,  # 用批次级 category（AI 结果不含 category 字段）
                                skip_duplicate=True,
                            )
                            if ok2:
                                rules_written += 1

    return {
        "ok": True,
        "total": len(all_results),
        "ok_count": sum(1 for r in all_results if r["ok"]),
        "failed_count": sum(1 for r in all_results if not r["ok"]),
        "results": all_results,
        "rules_written": rules_written,
    }


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
                code_block = s["code_block"] if isinstance(s["code_block"], list) else s["code_block"].replace("\\n", "\n").split("\n")
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
        code_block = s["code_block"] if isinstance(s["code_block"], list) else s["code_block"].replace("\\n", "\n").split("\n")
        result = _apply_rule_to_base(
            code_block, s["attr"], s["note"], s.get("pattern", ""),
            req.breed or s.get("breed", ""), req.category or s.get("category", ""),
        )
        if result is False:
            return {"ok": False, "message": "规则写入失败，已 rollback", "spec": spec}
        if result in ("new", "duplicate"):
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

