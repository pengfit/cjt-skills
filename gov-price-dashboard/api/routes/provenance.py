#!/usr/bin/env python3
"""
数据溯源 API 端点
来源分布、各省新鲜度、近30天入库趋势 — 支持多城市
"""

from fastapi import APIRouter, HTTPException, Query, Body
from pydantic import BaseModel
from elasticsearch import Elasticsearch, NotFoundError, RequestError
import datetime, concurrent.futures, subprocess, json, os, sys, re, functools, yaml, sqlite3

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
# etl 项目根（v0.2 重构后不再用 commands/ 路径，全部用 etl 的 paths.py 中心解析）
ETL_PROJECT_ROOT = "/Users/pengfit/.openclaw/workspace/skills/gov-price-etl"
sys.path.insert(0, ETL_PROJECT_ROOT)  # 让 `import gov_price_etl` 可用
sys.path.insert(0, os.path.join(ETL_PROJECT_ROOT, "gov_price_etl", "parse_spec", "rules"))  # 保留旧 import 路径

# DB 路径全部从 etl 的 paths.py 读（单一来源）
try:
    from gov_price_etl.paths import (
        SPEC_RULES_DB as _RULES_DB_SPEC,
        CATEGORY_V2_RULES_DB as _RULES_DB_CAT_V2,
        CATEGORY_V3_RULES_DB as _RULES_DB_CAT_V3,
        PROJECT_ROOT as _ETL_PROJECT_ROOT,
    )
    # 旧 _RULES_DB_CAT 指向 breed_category_rules.db，v1 已废（2026-06-16）
except Exception as _e:
    print(f"⚠️ etl paths 加载失败: {_e}")
    _RULES_DB_SPEC = _RULES_DB_CAT_V2 = _RULES_DB_CAT_V3 = None
    _ETL_PROJECT_ROOT = ETL_PROJECT_ROOT

try:
    from gov_price_etl.parse_spec.rules.vector_store import get_vec_store
except Exception:
    get_vec_store = None

# 集中引用 skill registry（避免 hardcode 城市 / 索引 / 进度表）
from api.skill_registry import (
    get_all as _registry_get_all,
    get as _registry_get,
)

router = APIRouter()


ES_HOST = "http://localhost:59200"


_EMPTY_SEARCH = {
    "hits": {"total": {"value": 0}, "hits": []},
    "aggregations": {},
}


def safe_search(es, index, body, default=None):
    """包 ES search：索引缺失/无数据时返回空，不报错"""
    try:
        return es.search(
            index=index,
            body=body,
            ignore_unavailable=True,
            allow_no_indices=True,
        )
    except (NotFoundError, RequestError, ConnectionError, ConnectionTimeout):
        return default if default is not None else _EMPTY_SEARCH
    except Exception as e:
        print(f"[warn] safe_search: {type(e).__name__}: {e}")
        return default if default is not None else _EMPTY_SEARCH


def safe_count(es, index, body=None, default=0):
    try:
        r = es.count(
            index=index,
            body=body or {},
            ignore_unavailable=True,
            allow_no_indices=True,
        )
        return r.get("count", default)
    except (NotFoundError, RequestError, ConnectionError, ConnectionTimeout):
        return default
    except Exception as e:
        print(f"[warn] safe_count: {type(e).__name__}: {e}")
        return default


# ── Progress _parse_area 通用 helper ──────────────────────────────
# chongqing v3 在 progress 文档 area 字段拼上"区县材料-万州区"等前缀。
# dashboard 需要从 raw 文本反推 source + 剥离名字。原本 3 处独立内嵌函数
# （provenance.py line 527/1018/3302），2026-07-02 抽出共用。
_AREA_SOURCE_PREFIX_MAP = {
    "district": "区县材料",
    "mortar":   "预拌砂浆",
    "citywide": "重庆材料信息价",
}

def _parse_area(raw_text: str) -> tuple[str, str]:
    """从 progress 文档 area/county 字段反推 (clean_county_name, source)。

    Args:
        raw_text: 原始 area 文本（可能含"区县材料-XXX"前缀，也可能裸 XXX）

    Returns:
        (clean_county_name, source) 二元组。source 默认 'district'（其他城市）。
    """
    if not raw_text:
        return "", "district"
    for src, prefix in _AREA_SOURCE_PREFIX_MAP.items():
        tag = f"{prefix}-"
        if raw_text.startswith(tag):
            return raw_text[len(tag):], src
    return raw_text, "district"


def _agg_runs_with_fallback(es, idx, body):
    """terms agg on run_id，text 类型索引报错时降级到 run_id.keyword

    背景：xinjiang 等老 progress 索引的 run_id 是 text 类型，text 字段做 terms agg
    需要加载 fielddata（默认禁用）。xian / chongqing 等索引已显式声明 run_id: keyword，
    不受影响。降级策略：失败时把 body 里所有 field='run_id' 递归替换为 'run_id.keyword' 重试。
    """
    try:
        return es.search(index=idx, body=body)
    except Exception as e:
        msg = str(e)
        if "Fielddata is disabled" not in msg and "fielddata is disabled" not in msg.lower():
            raise
        import copy
        body2 = copy.deepcopy(body)
        def _swap(node):
            if isinstance(node, dict):
                if node.get("field") == "run_id":
                    node["field"] = "run_id.keyword"
                for v in node.values():
                    _swap(v)
            elif isinstance(node, list):
                for v in node:
                    _swap(v)
        _swap(body2)
        return es.search(index=idx, body=body2)

# ── ETL classify/jaccard 批量写入接口 ──────────────

# 5 个动态字典：全部从 skill_registry 生成。
# 加新 skill：仅需在 skill.yml 配置 progress_mode / county_field / catalogue_field，
# 不再需要改 provenance.py。

def _city_indexes() -> dict:
    """city key → {dws, ods, dwd, label, progress_index, progress_mode, skill_dir}"""
    out = {}
    for s in _registry_get_all():
        dws = s.get("dws_index")
        if not dws:
            continue  # ETL 还没起就跳过
        out[s["key"]] = {
            "dws": dws,
            "ods": s.get("ods_index"),
            "dwd": s.get("dwd_index"),
            "label": s.get("label", s["key"]),
            "progress_index": s.get("progress_index"),
            "progress_mode": s.get("progress_mode", "period"),
            "skill_dir": s.get("skill_dir"),
            "cities": s.get("cities", []),
        }
    return out


def _city_county_counts() -> dict:
    """city key → cities 列表长度（period 模式默认 1；catalogue 模式默认 0，
    前端会 fallback 到 len(counties)）"""
    out = {}
    for s in _registry_get_all():
        mode = s.get("progress_mode", "period")
        cities = s.get("cities") or []
        if mode == "period":
            out[s["key"]] = 1
        elif mode == "catalogue":
            # catalogue 模式下 cities 写的是"地市级”，与实际 catalogue 数不一定一致
            # 返回 0 让前端 fallback 到进度索引实际的 catalogue 数
            out[s["key"]] = 0
        else:  # county
            out[s["key"]] = len(cities) if cities else 0
    return out


def _progress_indexes() -> dict:
    """city key → progress_index"""
    out = {}
    for s in _registry_get_all():
        pi = s.get("progress_index")
        if pi:
            out[s["key"]] = pi
    return out


def _all_ods_indices_csv() -> str:
    return ",".join(s["ods_index"] for s in _registry_get_all() if s.get("ods_index"))


def _all_dwd_indices_csv() -> str:
    return ",".join(s.get("dwd_index", "") for s in _registry_get_all() if s.get("dwd_index"))


# 兼容别名：所有调用方仍可走 CITY_INDEXES()[city]["label"] 语法
def CITY_INDEXES():
    return _city_indexes()


def CITY_COUNTY_COUNTS():
    return _city_county_counts()


def PROGRESS_INDEXES():
    return _progress_indexes()


def ALL_ODS_INDICES():
    return _all_ods_indices_csv()


def ALL_DWD_INDICES():
    return _all_dwd_indices_csv()


es = Elasticsearch([ES_HOST])



# _RULES_DB / _RULES_DB_CAT / _RULES_DB_SPEC 已在文件头部从 gov_price_etl.paths 导入
# （避免与旧路径硬编码冲突）

def _dws_attr_rate(index: str) -> dict:
    """DWS attr 解析率：含有有效 attr (nested attr.k) 的文档比例。

    逻辑：count = total 中 nested attr.k 存在的文档数；
    失败 / 异常时返回 rate=0 / count=0。
    """
    try:
        body = {
            "size": 0,
            "aggs": {
                "with_attr": {
                    "filter": {"nested": {"path": "attr", "query": {"exists": {"field": "attr.k"}}}}
                }
            }
        }
        r = es.search(index=index, body=body, ignore_unavailable=True)
        aggs = r.get("aggregations", {})
        with_attr = aggs.get("with_attr", {}).get("doc_count", 0)
        total = r.get("hits", {}).get("total", {}).get("value", 0)
        rate = (with_attr / total * 100) if total > 0 else 0
        return {"with_attr": with_attr, "total": total, "rate": round(rate, 1)}
    except Exception:
        return {"with_attr": 0, "total": 0, "rate": 0}


def _index_stats(index: str) -> dict:
    """获取单个索引的统计信息（支持逗号分隔的多索引 + ignore_unavailable）"""
    try:
        count_r = es.count(index=index, ignore_unavailable=True)
        count = count_r["count"]
    except Exception:
        return {"index": index, "count": 0, "status": "error", "msg": "count failed"}

    aggs_body = {
        "size": 0,
        "aggs": {
            "max_etl": {"max": {"field": "etl_time"}},
        }
    }
    # 对 update_date 的 min/max 聚合需要 date 类型；某些索引（如 heze）的 update_date 是 keyword，会报错
    # 先试加上 update_date 聚合，失败时也只损失 min_date/max_date，不影响主流程
    try:
        aggs_body["aggs"]["min_date"] = {"min": {"field": "update_date"}}
        aggs_body["aggs"]["max_date"] = {"max": {"field": "update_date"}}
    except Exception:
        pass

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
        # update_date keyword 报错时，回退仅查 etl_time
        try:
            fallback_body = {"size": 0, "aggs": {"max_etl": {"max": {"field": "etl_time"}}}}
            r2 = es.search(index=index, body=fallback_body)
            max_etl = r2.get("aggregations", {}).get("max_etl", {}).get("value_as_string", "") or ""
            return {
                "index": index,
                "count": count,
                "min_date": "",
                "max_date": "",
                "last_etl": max_etl[:19] if max_etl else "",
                "status": "ok",
                "msg": f"update_date aggregation skipped: {str(e)[:100]}",
            }
        except Exception as e2:
            return {"index": index, "count": count, "status": "error", "msg": str(e2)}


@router.post("/api/scrape/check")
def api_scrape_check(city: str = Body("...", embed=True)):
    """
    触发指定城市的增量检测（check），判断源站是否有更新。
    实际执行 skill 目录下的 check.py 脚本。
    """
    cfg = _registry_get(city)
    if not cfg:
        raise HTTPException(status_code=400, detail=f"未知城市: {city}")

    skill_name = cfg.get("skill_dir") or f"{city}-price"
    script_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                              "skills", skill_name)
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
def stats_scrape_progress_all(year: int = 2026):
    """所有城市 ODS 抓取进度汇总（一次性返回全部城市）

    路由：每城 cfg["progress_mode"] → _scrape_period_progress / _scrape_county_progress / _scrape_catalogue_progress
    加新 skill：仅需在 skill.yml 配 progress_mode + (county_field | catalogue_field) + 可选 group_by。
    """
    results = {}
    for city in PROGRESS_INDEXES().keys():
        cfg = _registry_get(city) or {}
        mode = cfg.get("progress_mode", "period")
        idx = PROGRESS_INDEXES().get(city)
        try:
            if mode == "period":
                results[city] = _scrape_period_progress(idx, year, cfg)
            elif mode == "county":
                results[city] = _scrape_county_progress(idx, year, cfg)
            elif mode == "catalogue":
                results[city] = _scrape_catalogue_progress(idx, cfg)
            else:
                results[city] = _scrape_error_result(city, f"未知 progress_mode: {mode}")
        except Exception as e:
            results[city] = _scrape_error_result(city, e)
    return results


def _scrape_error_result(city, err) -> dict:
    label = (CITY_INDEXES().get(city) or {}).get("label", city)
    # 错误消息截短：避免 NotFoundError 完整字符串刷屏
    err_str = str(err)
    if "index_not_found_exception" in err_str or "no such index" in err_str:
        err_msg = "进度索引不存在（ES 清空后未重建）"
        status = "empty"
    else:
        err_msg = err_str[:120]
        status = "error"
    return {
        "city": city, "city_label": label, "latest_run_id": None, "last_updated": "",
        "total_docs": 0, "total_records": 0, "completed": 0, "running": 0, "error": 0,
        "total_counties": 0, "status": status, "counties": [], "error_msg": err_msg,
    }


def _scrape_period_progress(idx: str, year: int, cfg: dict) -> dict:
    """period 模式：heze / henan / qingdao / weihai 等按 PDF 期刊跟踪的 skill

    按 period 字段 terms agg，按 year 过滤；返回该年各期状态。
    """
    period_size = cfg.get("period_size", 20)
    period_field = cfg.get("period_field", "period")
    body = {
        "size": 0,
        "query": {"prefix": {period_field: f"{year}."}},
        "aggs": {
            "periods": {
                "terms": {"field": period_field, "size": period_size},
                "aggs": {
                    "docs_sum": {"sum": {"field": "docs_written"}},
                    "latest_doc": {
                        "top_hits": {
                            "size": 1, "sort": [{"created_at": "desc"}],
                            "_source": ["period", "publish_date", "status", "docs_written",
                                        "duration_sec", "created_at", "pdf_url", "minio_key"],
                        }
                    }
                }
            }
        }
    }
    r = es.search(index=idx, body=body)
    buckets = r["aggregations"]["periods"]["buckets"]
    td = sum(b.get("docs_sum", {}).get("value", 0) for b in buckets)
    counties = []
    period_created = {}
    comp = run = err = 0
    run_id = None
    lu = ""
    lu_str = ""
    for b in buckets:
        doc = b.get("latest_doc", {}).get("hits", {}).get("hits", [{}])[0].get("_source", {})
        raw_status = doc.get("status", "ok")
        if raw_status == "ok":
            primary_status = "completed"; comp += 1
        elif raw_status in ("running", "in_progress"):
            primary_status = "running"; run += 1
        else:
            primary_status = raw_status or "completed"; comp += 1
        counties.append({
            "county": b["key"], "period": b["key"],
            "publish_date": doc.get("publish_date", ""),
            "status": primary_status,
            "percent": 100.0 if primary_status == "completed" else 0,
            "docs_written": doc.get("docs_written", 0),
            "current_page": 0, "total_pages": 0,
        })
        created = doc.get("created_at", "")
        period_created[b["key"]] = created
        if created and created > lu_str:
            lu_str = created
            lu = created[:19]
            run_id = doc.get("period")
    counties.sort(key=lambda c: period_created.get(c["county"], ""), reverse=True)
    return {
        "city": cfg["key"], "city_label": cfg.get("label", cfg["key"]),
        "latest_run_id": run_id, "last_updated": lu,
        "total_docs": td, "total_records": 0,
        "completed": comp, "running": run, "error": err,
        "total_counties": len(counties), "counties": counties,
    }


def _scrape_county_progress(idx: str, year: int, cfg: dict) -> dict:
    """county 模式：xian / chongqing 等按区县抓取的 skill

    按 run_id group 取最新一个 completed run，再列其下 county_field 详情。
    xian 用 county_field=current_county；chongqing 用 county_field=area，
    还可有 summary_marker（如 area="全部完成"）。
    注意：某些 skill（chongqing）的 last_updated 是 keyword 不能 max agg，改用 top_hits sort。
    """
    county_field = cfg.get("county_field", "current_county")
    summary_marker = cfg.get("summary_marker")
    # ES top_hits 子聚合默认 size 上限为 100（max_inner_result_window）。
    # chongqing 同一 run 同一 period 有 ~44 条 unique county × N period 会超限。
    # 为保险走三个 filter bucket（completed/running/error）+ 都不限（按 status terms）
    # 用常规 terms agg 即可拿到全量 unique county。
    body = {
        "size": 0,
        "aggs": {
            "by_status": {
                "terms": {"field": "status", "size": 10},
                "aggs": {
                    "runs": {
                        # missing:"" 让无 run_id 字段的 progress 文档（如 xinjiang）也进桶
                        "terms": {"field": "run_id", "size": 5, "missing": ""},
                        "aggs": {
                            "latest_doc": {
                                "top_hits": {
                                    "size": 1, "sort": [{"last_updated": "desc"}],
                                    "_source": ["last_updated"],
                                }
                            },
                            "counties": {
                                "top_hits": {
                                    "size": 100, "sort": [{"last_updated": "desc"}],
                                    "_source": [
                                        "county", "run_id", "status", "current_county",
                                        "current_page", "total_pages", "total_records",
                                        "docs_written", "percent", "duration_sec",
                                        "period", "update_date", "last_updated",
                                        "error", "spot_check_ok",
                                        "area", "area_name", "catalogue_name", "tab_name",
                                    ]
                                }
                            },
                        }
                    }
                }
            }
        }
    }
    r = _agg_runs_with_fallback(es, idx, body)
    by_status_buckets = r["aggregations"]["by_status"]["buckets"]

    def _bucket_lu(b):
        lh = b.get("latest_doc", {}).get("hits", {}).get("hits", [])
        return lh[0]["_source"].get("last_updated", "") if lh else ""

    # 收集所有 status 桶下每个 run_id 的 counties hits，扁平去重
    all_county_hits = []
    latest_overall_lu = ""
    latest_run_id = None
    for status_b in by_status_buckets:
        # bucket 里 runs 按 last_updated desc 排
        runs_list = sorted(status_b.get("runs", {}).get("buckets", []),
                           key=_bucket_lu, reverse=True)
        for rb in runs_list:
            lu_ts = _bucket_lu(rb)
            if lu_ts and lu_ts > latest_overall_lu:
                latest_overall_lu = lu_ts
                latest_run_id = rb["key"]
            for h in rb.get("counties", {}).get("hits", {}).get("hits", []):
                all_county_hits.append(h)

    if not all_county_hits:
        return {
            "city": cfg["key"], "city_label": cfg.get("label", cfg["key"]),
            "latest_run_id": None, "last_updated": "", "total_docs": 0, "total_records": 0,
            "completed": 0, "running": 0, "error": 0,
            "total_counties": CITY_COUNTY_COUNTS().get(cfg["key"], 0), "counties": [],
        }

    ch = all_county_hits
    lu = latest_overall_lu[:19]

    if summary_marker:
        ch = [h for h in ch if h["_source"].get(county_field) != summary_marker]

    # 兼容 county / current_county / area / area_name / catalogue_name / tab_name 等多种主键
    _COUNTY_KEYS = ("county", "current_county", "area", "area_name", "catalogue_name", "tab_name")
    ch = [h for h in ch if any(h["_source"].get(k) for k in _COUNTY_KEYS)]

    # chongqing 这种 sync 会在 county/area 上拼 "区县材料-"/"预拌砂浆-"/"重庆材料信息价-"
    # 带 source 前缀的 raw 文本。_parse_area 反推 source + 剥离名字（2026-07-02
    # 已抽到模块顶部，见上方定义）。
    # 同时同一 (run, source, county) 多个 period 会有多条，去重保最新。

    # 1. 按 raw_area 去重，保留 last_updated 最大那条（chongqing 同一区县在多个 period 都留进度记录）
    deduped_map: dict[str, dict] = {}
    for h in ch:
        src = h["_source"]
        raw_area = next((src.get(k, "") for k in _COUNTY_KEYS if src.get(k)), "")
        clean_name, source_label = _parse_area(raw_area)
        lu_str = src.get("last_updated", "")
        period = src.get("period", "")
        cur = deduped_map.get(raw_area)
        if cur is None or (lu_str, period) > (cur["_last_updated"], cur["period"]):
            deduped_map[raw_area] = {
                "raw_area": raw_area,
                "county": clean_name,
                "source": source_label,
                "status": src.get("status", ""),
                "percent": round(src.get("percent", 0), 1),
                "docs_written": src.get("docs_written", 0),
                "period": period,
                "_last_updated": lu_str,
            }
    counties_raw = sorted(deduped_map.values(), key=lambda x: x["raw_area"])
    # percent fallback：部分 skill（如 xinjiang）写入 ES 时不填 percent，但 status 已标 ok/completed。
    # 这种"已知完成"场景前端显示成 0% 不合理，统一在出口处补成 100。
    # running 不强制补 0：保留原 percent（若有真实进度），否则 0。
    counties = [{
        "county": c["county"],
        "source": c["source"],
        "status": c["status"],
        "percent": (100.0 if c["status"] in ("completed", "ok") else c["percent"]),
        "docs_written": c["docs_written"],
        "period": c["period"],
    } for c in counties_raw]

    td = sum(c["docs_written"] for c in counties_raw)
    tr = sum(h["_source"].get("total_records", 0) for h in ch)
    # 兼容 'ok' 状态（xinjiang 等 skill 写入完成时的 status）
    comp = sum(1 for c in counties_raw if c["status"] in ("completed", "ok"))
    run = sum(1 for c in counties_raw if c["status"] == "running")
    err = sum(1 for c in counties_raw if c["status"] == "error")
    skip = sum(1 for c in counties_raw if c["status"] == "skipped")

    # 多 source 分组汇总（仅当实际存在多 source 才生成 source_summary；单 source 时退回老逻辑）
    source_keys = {c["source"] for c in counties_raw}
    source_summary: dict[str, dict] = {}
    if len(source_keys) > 1:
        for c in counties_raw:
            s = c["source"]
            b = source_summary.setdefault(s, {"total": 0, "completed": 0, "running": 0, "error": 0, "skipped": 0})
            b["total"] += 1
            # 兼容 'ok' 状态（xinjiang 等）
            if c["status"] in ("completed", "ok"):
                b["completed"] += 1
            elif c["status"] == "running":
                b["running"] += 1
            elif c["status"] == "error":
                b["error"] += 1
            elif c["status"] == "skipped":
                b["skipped"] += 1
        # 主项（district）完成数。若不存在 district source，仍以 comp 为准
        primary = source_summary.get("district")
        if primary:
            comp = primary["completed"]

    result = {
        "city": cfg["key"], "city_label": cfg.get("label", cfg["key"]),
        "latest_run_id": latest_run_id, "last_updated": lu,
        "total_docs": td, "total_records": tr,
        "completed": comp, "running": run, "error": err, "skipped": skip,
        "total_counties": CITY_COUNTY_COUNTS().get(cfg["key"], len(ch)),
        "counties": counties,
    }
    if source_summary:
        result["source_summary"] = source_summary
    return result


def _scrape_catalogue_progress(idx: str, cfg: dict) -> dict:
    """catalogue 模式：sichuan / jinan / rizhao 等按分类目录抓取的 skill

    - sichuan：catalogue_field=area, group_by=run_id
    - jinan / rizhao：group_by=latest（按最新 last_updated 去重）
    """
    catalogue_field = cfg.get("catalogue_field", "catalogue")

    # percent 兜底派生 helper（rizhao 历史文档漏写 percent，靠 docs/total_records 补）
    def _scrape_derive_percent(d: dict) -> float:
        raw = d.get("percent")
        if raw is not None and raw != 0:
            return round(float(raw), 1)
        dw = d.get("docs_written", 0) or 0
        tr = d.get("total_records", 0) or d.get("total_count", 0) or 0
        if dw and tr:
            return round(dw / tr * 100, 1)
        return 0.0
    group_by = cfg.get("group_by", "run_id")

    if catalogue_field == "tab_name":
        # 兼容 rizhao 旧聚合（terms agg + completed/running 桶）
        body = {
            "size": 0,
            "aggs": {
                "tabs": {
                    "terms": {"field": "tab_name", "size": 20},
                    "aggs": {
                        "latest_ts": {"max": {"field": "last_updated"}},
                        "docs_sum": {"sum": {"field": "docs_written"}},
                        "completed": {"filter": {"term": {"status": "completed"}},
                                       "aggs": {"status_count": {"value_count": {"field": "status"}}}},
                        "running": {"filter": {"term": {"status": "running"}},
                                    "aggs": {"latest_doc": {
                                        "top_hits": {"size": 1, "sort": [{"last_updated": "desc"}],
                                                     "_source": ["tab_name", "status", "docs_written", "percent", "run_id", "last_updated", "current_page", "total_pages"]}}}},
                        "error": {"filter": {"term": {"status": "error"}}},
                    }
                }
            }
        }
        r = es.search(index=idx, body=body)
        buckets = r["aggregations"]["tabs"]["buckets"]
        td = sum(b.get("docs_sum", {}).get("value", 0) for b in buckets)
        comp = sum(1 for b in buckets if b.get("completed", {}).get("doc_count", 0) > 0)
        run = sum(1 for b in buckets if b.get("running", {}).get("doc_count", 0) > 0)
        err = sum(1 for b in buckets if b.get("error", {}).get("doc_count", 0) > 0)
        counties = []
        run_id = None
        lu = ""
        lu_ts = None
        for b in buckets:
            comp_count = b.get("completed", {}).get("doc_count", 0)
            run_count = b.get("running", {}).get("doc_count", 0)
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
                percent = docs_written = current_page = total_pages = 0
            counties.append({
                "county": b["key"], "status": primary_status,
                "percent": round(percent, 1), "docs_written": docs_written,
                "current_page": current_page, "total_pages": total_pages,
            })
            ts = b.get("latest_ts", {}).get("value")
            if ts and (lu == "" or ts > (lu_ts or 0)):
                lu_ts = ts
                lu = b.get("latest_ts", {}).get("value_as_string", "")[:19]
    else:
        body = {
            "size": 0,
            "aggs": {
                "cats": {
                    "terms": {"field": catalogue_field, "size": 100, "exclude": ""},
                    "aggs": {
                        "latest_ts": {"max": {"field": "last_updated"}},
                        "latest_doc": {
                            "top_hits": {
                                "size": 1, "sort": [{"last_updated": "desc"}],
                                "_source": [catalogue_field, f"{catalogue_field}_name", "catalogue_name",
                                            "area_name", "tab_name",
                                            "status", "docs_written", "percent",
                                            "last_updated", "current_page", "total_pages", "total_records",
                                            "run_id"],
                            }
                        }
                    }
                }
            }
        }
        r = es.search(index=idx, body=body)
        buckets = r["aggregations"]["cats"]["buckets"]
        td = sum((b.get("latest_doc", {}).get("hits", {}).get("hits", [{}])[0].get("_source", {}).get("docs_written", 0)) for b in buckets)
        counties = []
        run_id = None
        lu = ""
        lu_ts = None
        comp = run = err = 0
        for b in buckets:
            doc = b.get("latest_doc", {}).get("hits", {}).get("hits", [{}])[0].get("_source", {})
            status = doc.get("status", "completed")
            # 状态归一化：'ok' 视为 'completed'（兼容 rizhao 历史写入格式）
            if status == "ok":
                status_norm = "completed"
            else:
                status_norm = status
            # 取中文名（兼容 sichuan area_name / jinan catalogue_name / rizhao tab_name）
            cat_name = (doc.get(f"{catalogue_field}_name", "")
                        or doc.get("catalogue_name", "")
                        or doc.get("area_name", "")
                        or doc.get("tab_name", "")
                        or "")
            if status_norm == "completed":
                comp += 1
            elif status_norm == "running":
                run += 1
            else:
                err += 1
            counties.append({
                "county": b["key"], "status": status_norm,
                "catalogue_name": cat_name,
                "area_name": cat_name if catalogue_field == "area" else "",
                "tab_name": cat_name if catalogue_field == "tab_name" else "",
                "name": cat_name or b["key"],
                # percent 兜底派生：优先 ES 原值，缺失则用 docs_written/total_records 派生
                "percent": _scrape_derive_percent(doc),
                "docs_written": doc.get("docs_written", 0),
                "current_page": doc.get("current_page", 0),
                "total_pages": doc.get("total_pages", 0),
            })
            ts = b.get("latest_ts", {}).get("value")
            if ts and (lu == "" or ts > (lu_ts or 0)):
                lu_ts = ts
                lu = b.get("latest_ts", {}).get("value_as_string", "")[:19]
                run_id = doc.get("run_id")

    return {
        "city": cfg["key"], "city_label": cfg.get("label", cfg["key"]),
        "latest_run_id": run_id, "last_updated": lu,
        "total_docs": td, "total_records": 0,
        "completed": comp, "running": run, "error": err,
        "total_counties": (CITY_COUNTY_COUNTS().get(cfg["key"], 0) or len(counties)),
        "counties": counties,
    }




@router.get("/api/stats/scrape-progress")
def stats_scrape_progress(city: str = Query("xian", description="城市 key"), year: int = 2026):
    """
    ODS 层抓取进度：最近一次同步 run 的各区县进度
    """
    PROGRESS_INDEX = PROGRESS_INDEXES().get(city, PROGRESS_INDEXES()["xian"])
    use_chongqing_workaround = (city == "chongqing")
    use_henan_periods = (city == "henan")

    try:
        # 索引缺失/无文档 → 直接返回空数据（不报错）
        try:
            es.search(index=PROGRESS_INDEX, body={"size": 0}, ignore_unavailable=True, allow_no_indices=True)
        except (NotFoundError, RequestError):
            return {
                "city": city,
                "city_label": CITY_INDEXES().get(city, {}).get("label", city),
                "latest_run_id": None,
                "last_updated": "",
                "total_docs": 0,
                "total_records": 0,
                "completed": 0,
                "running": 0,
                "error": 0,
                "total_counties": CITY_COUNTY_COUNTS().get(city, 0),
                "counties": [],
                "status": "empty",
                "message": "进度索引不存在（ES 清空后未重建），跑采集脚本后会自动恢复",
            }
        if use_henan_periods:
            # Henan: 按 period 跟踪，created_at 是 keyword 不能 max 聚合
            # 按 year 过滤（period 字段格式 YYYY.M月）
            period_body = {
                "size": 0,
                "query": {
                    "prefix": {"period": f"{year}."}
                },
                "aggs": {
                    "periods": {
                        "terms": {"field": "period", "size": 20},
                        "aggs": {
                            "docs_sum": {"sum": {"field": "docs_written"}},
                            "latest_doc": {
                                "top_hits": {
                                    "size": 1,
                                    "sort": [{"created_at": "desc"}],
                                    "_source": ["period", "publish_date", "status", "docs_written", "duration_sec", "created_at"]
                                }
                            }
                        }
                    }
                }
            }
            period_r = es.search(index=PROGRESS_INDEX, body=period_body)
            period_buckets = period_r["aggregations"]["periods"]["buckets"]
            total_docs = sum(b.get("docs_sum", {}).get("value", 0) for b in period_buckets)
            total_records = 0
            counties = []
            run_id = None
            lu = ""
            lu_str = ""
            comp = 0
            run = 0
            err = 0
            period_created = {}
            for b in period_buckets:
                doc = b.get("latest_doc", {}).get("hits", {}).get("hits", [{}])[0].get("_source", {})
                raw_status = doc.get("status", "ok")
                if raw_status == "ok":
                    primary_status = "completed"
                    comp += 1
                elif raw_status in ("running", "in_progress"):
                    primary_status = "running"
                    run += 1
                else:
                    primary_status = raw_status or "completed"
                    comp += 1
                counties.append({
                    "county": b["key"],
                    "status": primary_status,
                    "current_page": 0,
                    "total_pages": 0,
                    "total_records": 0,
                    "docs_written": doc.get("docs_written", 0),
                    "percent": 100.0 if primary_status == "completed" else 0,
                    "duration_sec": round(doc.get("duration_sec", 0), 1),
                    "update_date": doc.get("publish_date", ""),
                    "last_updated": doc.get("created_at", ""),
                    "error": "",
                    "spot_check_ok": None,
                })
                created = doc.get("created_at", "")
                period_created[b["key"]] = created
                if created and created > lu_str:
                    lu_str = created
                    lu = created[:19]
                    run_id = doc.get("period")
            counties.sort(key=lambda c: period_created.get(c["county"], ""), reverse=True)
            return {
                "city": city,
                "city_label": CITY_INDEXES().get(city, {}).get("label", city),
                "latest_run_id": run_id,
                "last_updated": lu,
                "total_docs": total_docs,
                "total_records": total_records,
                "completed": comp,
                "running": run,
                "error": err,
                "total_counties": len(counties),
                "counties": counties,
            }

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
            run_result = _agg_runs_with_fallback(es, PROGRESS_INDEX, run_body)
            run_buckets = run_result["aggregations"]["runs"]["buckets"]

            def sort_key(b):
                hits = b.get("latest", {}).get("hits", {}).get("hits", [])
                return (hits[0].get("_source", {}).get("last_updated", "") or "") if hits else ""

            run_buckets.sort(key=sort_key, reverse=True)
            if not run_buckets:
                return {"runs": [], "latest_run_id": None, "city": city,
                        "city_label": CITY_INDEXES().get(city, {}).get("label", city)}
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
            run_result = _agg_runs_with_fallback(es, PROGRESS_INDEX, run_body)
            run_buckets = run_result["aggregations"]["runs"]["buckets"]
            if not run_buckets:
                return {"runs": [], "latest_run_id": None, "city": city,
                        "city_label": CITY_INDEXES().get(city, {}).get("label", city)}
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
                        "city_label": CITY_INDEXES().get(city, {}).get("label", city),
                        "latest_run_id": None,
                        "last_updated": "",
                        "total_docs": 0,
                        "total_records": 0,
                        "completed": 0,
                        "running": 0,
                        "error": 0,
                        "total_counties": CITY_COUNTY_COUNTS().get(city, 0),
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
                "city_label": CITY_INDEXES().get(city, {}).get("label", city),
                "latest_run_id": counties[0]["last_updated"] if counties else None,
                "last_updated": counties[0]["last_updated"] if counties else "",
                "total_docs": total_docs,
                "total_records": total_records,
                "completed": completed,
                "running": running,
                "error": err,
                "total_counties": CITY_COUNTY_COUNTS().get(city, len(counties)),
                "counties": counties,
            }

        total_docs = sum(h["_source"].get("docs_written", 0) for h in county_hits)
        total_records = sum(h["_source"].get("total_records", 0) for h in county_hits)

        # 通用兜底：county/area 可能被 sync 端拼上 "区县材料-"/"预拌砂浆-"/"重庆材料信息价-"
        # 等带 source 前缀的 raw 文本。_parse_area（2026-07-02 抽到模块顶部）按前缀
        # 推断 source 并剥离，避免前端显示错误名字。

        raw_rows = []
        for h in county_hits:
            src = h["_source"]
            raw_area = src.get("county", "") or src.get("current_county", "") or src.get("area", "") or src.get("catalogue_name", "") or src.get("tab_name", "")
            if not raw_area:
                continue
            clean_name, source = _parse_area(raw_area)
            raw_rows.append({
                "raw_area": raw_area,
                "county": clean_name,
                "source": source,
                "status": src.get("status", ""),
                "current_page": src.get("current_page", 0),
                "total_pages": src.get("total_pages", 0),
                "total_records": src.get("total_records", 0),
                "docs_written": src.get("docs_written", 0),
                "percent": round(src.get("percent", 0), 1),
                "duration_sec": round(src.get("duration_sec", 0), 1),
                "period": src.get("period", ""),
                "update_date": src.get("update_date", ""),
                "last_updated": src.get("last_updated", ""),
                "error": src.get("error", ""),
                "spot_check_ok": src.get("spot_check_ok"),
            })

        # 去重：同一 raw_area 保留最新一条（last_updated desc, period desc）
        # chongqing 同一 county 在多个 period 都会留记录，去重后才能给出真实进度。
        deduped_map: dict[str, dict] = {}
        period_rank = {}
        for r in raw_rows:
            key = r["raw_area"]
            cur = deduped_map.get(key)
            if cur is None or (r["last_updated"], r["period"]) > (cur["last_updated"], cur["period"]):
                deduped_map[key] = r
        counties = sorted(deduped_map.values(), key=lambda x: x["raw_area"])

        completed = sum(1 for c in counties if c.get("status") == "completed")
        running = sum(1 for c in counties if c.get("status") == "running")
        err = sum(1 for c in counties if c.get("status") == "error")

        return {
            "city": city,
            "city_label": CITY_INDEXES().get(city, {}).get("label", city),
            "latest_run_id": latest_run_id,
            "last_updated": last_updated,
            "total_docs": total_docs,
            "total_records": total_records,
            "completed": completed,
            "running": running,
            "error": err,
            "total_counties": CITY_COUNTY_COUNTS().get(city, len(counties)),
            "counties": counties,
        }
    except (NotFoundError, RequestError) as e:
        # 索引缺失，返回空数据
        return {
            "city": city,
            "city_label": CITY_INDEXES().get(city, {}).get("label", city),
            "latest_run_id": None,
            "last_updated": "",
            "total_docs": 0,
            "total_records": 0,
            "completed": 0,
            "running": 0,
            "error": 0,
            "total_counties": CITY_COUNTY_COUNTS().get(city, 0),
            "counties": [],
            "status": "empty",
            "message": "进度索引不存在（ES 清空后未重建）",
        }
    except Exception as e:
        # print stack for debug (disabled)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/stats/provenance")
def stats_provenance(city: str = Query("all", description="城市 key，all 表示全部城市")):
    """
    数据溯源：来源分布 + 各省新鲜度 + 近30天入库趋势
    """
    if city not in CITY_INDEXES() and city != "all":
        raise HTTPException(status_code=400, detail=f"未知城市: {city}，可用: {', '.join(CITY_INDEXES().keys())}, all")

    is_all = (city == "all")
    if is_all:
        ods_idx = ALL_ODS_INDICES()
        dwd_idx = ALL_DWD_INDICES()
        dws_idx = dwd_idx
        city_label = "全部城市"
    else:
        cfg = CITY_INDEXES()[city]
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
        prov_result = safe_search(es, dwd_idx, prov_body)
        prov_buckets = prov_result.get("aggregations", {}).get("by_province", {}).get("buckets", [])

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
        daily_result = safe_search(es, dwd_idx, daily_body)
        daily_buckets = daily_result.get("aggregations", {}).get("daily", {}).get("buckets", [])
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
        city_result = safe_search(es, dwd_idx, city_body)
        city_buckets = city_result.get("aggregations", {}).get("by_city", {}).get("buckets", [])
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
            count_resp = es.count(index=dwd_idx, ignore_unavailable=True)
            total_count = count_resp["count"]
        except Exception:
            total_body = {"query": {"match_all": {}}, "size": 0, "track_total": True}
            total_r = es.search(index=dwd_idx, body=total_body, ignore_unavailable=True)
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
                body={"query": {"range": {"etl_time": {"gte": "now-7d"}}}}, ignore_unavailable=True)
            r2 = pool.submit(es.count, index=dwd_idx,
                body={"query": {"range": {"etl_time": {"gte": "now-14d", "lt": "now-7d"}}}}, ignore_unavailable=True)
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

        # sync_ok：ODS 全部入仓（严格相等） 或 DWD/DWS 有数据且 DWD<=ODS（允许 ETL 过滤无 spec 的记录，如菏泽）
        ods_c = ods_stats.get("count", 0)
        dwd_c = dwd_stats.get("count", 0)
        dws_c = dws_stats.get("count", 0)
        strict_ok = (ods_c == dwd_c == dws_c and ods_c > 0)
        loose_ok = (dwd_c > 0 and dws_c > 0 and dwd_c <= ods_c and abs(dwd_c - dws_c) <= 1)
        sync_ok = strict_ok or loose_ok
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

        # ── 8.5. 各城市 7 日 sparkline（一次性复合聚合）───────
        sparkline_all = {}
        try:
            # 用 city 字段聚合，但匹配 CITY_INDEXES() 的 label（部分同省同 key 的合并需要去重）
            # size 必须足够大以包含所有 7 个城市（四川有 30+ 个区县 city 字段）
            sparkline_body = {
                "size": 0,
                "query": {"range": {"etl_time": {"gte": "now-7d"}}},
                "aggs": {
                    "by_city": {
                        "terms": {"field": "city", "size": 300},
                        "aggs": {
                            "daily": {
                                "date_histogram": {
                                    "field": "etl_time",
                                    "calendar_interval": "day",
                                    "min_doc_count": 0,
                                    "extended_bounds": {"min": "now-7d", "max": "now"},
                                }
                            }
                        }
                    }
                }
            }
            sparkline_result = es.search(index=dwd_idx, body=sparkline_body, ignore_unavailable=True)

            # 反向映射：ES 返回的是中文 label，存到 sparkline_all 时用 city key
            # ES 的 city 字段是"市"级（如"重庆市"、"乐山市"、"日照市"），与 CITY_INDEXES() 的 label 可能差一字
            label_to_key = {v["label"]: k for k, v in CITY_INDEXES().items()}
            # ES 实际可能出现的别名 → city key
            city_alias = {
                "重庆市": "chongqing", "乐山市": "sichuan", "五通": "sichuan",
                "井研": "sichuan", "夹江": "sichuan", "峨眉山市": "sichuan",
                "峨边": "sichuan", "沐川": "sichuan", "沙湾": "sichuan",
                "犍为": "sichuan", "金口河": "sichuan", "马边": "sichuan",
                "广元市": "sichuan", "内江市区": "sichuan", "威远县": "sichuan",
                "资中县": "sichuan", "隆昌县": "sichuan", "攀枝花市区": "sichuan",
                "米易县": "sichuan", "盐边县": "sichuan", "盐边北部": "sichuan",
                "南溪区": "sichuan", "宜宾市区": "sichuan", "兴文县": "sichuan",
                "屏山县": "sichuan", "屏山其他乡镇": "sichuan",
                "日照市": "rizhao", "重庆": "chongqing",
                # jinan / xian / henan 标签与 ES 一致，不需别名
            }
            for cb in sparkline_result['aggregations']['by_city']['buckets']:
                key = city_alias.get(cb["key"]) or label_to_key.get(cb["key"])
                if not key:
                    continue
                # 同省多 city 累加（如四川包含乐山/五通/井研...）
                if key in sparkline_all:
                    # 累加
                    prev = sparkline_all[key]
                    cur = [b["doc_count"] for b in cb["daily"]["buckets"]]
                    sparkline_all[key] = [p + c for p, c in zip(prev, cur)]
                else:
                    sparkline_all[key] = [b["doc_count"] for b in cb["daily"]["buckets"]]
        except Exception as e:
            # print stack for debug (disabled)
            # sparkline 是增值表，失败不应阻塞主接口
            pass
        all_pipelines = {}
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
            futures = {}
            for k, v in CITY_INDEXES().items():
                futures[k] = {
                    "ods": pool.submit(_index_stats, v["ods"]),
                    "dwd": pool.submit(_index_stats, v["dwd"]),
                    "dws": pool.submit(_index_stats, v["dws"]),
                    "dws_attr": pool.submit(_dws_attr_rate, v["dws"]),
                }
            for k, f in futures.items():
                ods_s = f["ods"].result()
                dwd_s = f["dwd"].result()
                dws_s = f["dws"].result()
                dws_attr_s = f["dws_attr"].result()
                ods_c2 = ods_s.get("count", 0)
                dwd_c2 = dwd_s.get("count", 0)
                dws_c2 = dws_s.get("count", 0)
                strict_ok_c = (ods_c2 == dwd_c2 == dws_c2 and ods_c2 > 0)
                loose_ok_c = (dwd_c2 > 0 and dws_c2 > 0 and dwd_c2 <= ods_c2 and abs(dwd_c2 - dws_c2) <= 1)
                sync_ok_c = strict_ok_c or loose_ok_c
                scrape_k = scrape_all.get(k, {})
                # scrape_fresh：抓取任务是否已完成（供"数据抓取"页面卡片用，与 sync_ok 的 ETL 一致性语义不同）
                _sc_total   = scrape_k.get("total_counties", 0)
                _sc_done    = scrape_k.get("completed", 0)
                _sc_running = scrape_k.get("running", 0)
                _sc_error   = scrape_k.get("error", 0)
                _sc_skip    = scrape_k.get("skipped", 0)
                # scrape_fresh：完成 + 跳过（预期空） >= total，且无运行中、无错误
                scrape_fresh_c = (_sc_total > 0 and (_sc_done + _sc_skip) >= _sc_total and _sc_running == 0 and _sc_error == 0)
                all_pipelines[k] = {
                    "city": k,
                    "city_label": CITY_INDEXES()[k]["label"],
                    "ods": ods_s,
                    "dwd": dwd_s,
                    "dws": dws_s,
                    "dws_attr_rate": dws_attr_s,
                    "sync_ok": sync_ok_c,
                    "scrape_fresh": scrape_fresh_c,
                    "status": "ok" if sync_ok_c else "out_of_sync",
                    "sparkline_7d": sparkline_all.get(k, []),
                    "scrape": {
                        "latest_run_id": scrape_k.get("latest_run_id"),
                        "last_updated": scrape_k.get("last_updated", ""),
                        "total_docs": scrape_k.get("total_docs", 0),
                        "completed": scrape_k.get("completed", 0),
                        "running": scrape_k.get("running", 0),
                        "error": scrape_k.get("error", 0),
                        "skipped": scrape_k.get("skipped", 0),
                        "total_counties": scrape_k.get("total_counties", 0),
                        "counties": scrape_k.get("counties", []),
                        "source_summary": scrape_k.get("source_summary"),
                    },
                }

        return {
            "city": city,
            "city_label": city_label,
            "total": total_count,
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
        # print stack for debug (disabled)
        raise HTTPException(status_code=500, detail=str(e))

# ── Spec 解析质量 ─────────────────────────────────────────────
# ETL_CMD_DIR 别名（仅为了不破坏下面残存的旧代码）
ETL_CMD_DIR = os.path.join(_ETL_PROJECT_ROOT, "gov_price_etl")

# 从 gov_price_etl/parse_spec/rules/_attrs.py 动态加载属性描述
try:
    import re as _re
    _attrs_file = os.path.join(_ETL_PROJECT_ROOT, "gov_price_etl", "parse_spec", "rules", "_attrs.py")
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
        names = [r[0] for r in cur.fetchall()]
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
    testset_path = os.path.join(_ETL_PROJECT_ROOT, "data", "spec_testset.json")
    if not os.path.exists(testset_path):
        return {"error": f"测试集不存在: {testset_path}"}
    with open(testset_path) as f:
        data = json.load(f)
    try:
        from gov_price_etl.parse_spec import get_parser
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
            from gov_price_etl.parse_spec import get_parser
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
        "henan": "dwd_henan_price",
        "heze": "dwd_heze_price",
        "qingdao": "dwd_qingdao_price",
    }
    idx = city_idx_map.get(city, "dwd_xian_price")
    parser = _get_cached_parser(city)
    if parser is None:
        return []

    must_clauses = []
    if category:
        must_clauses.append({"term": {"category": category}})
    # 重点：仅查询 spec 非空 且 attr 为空的文档（需要解析的目标）
    query = {
        "bool": {
            "must": must_clauses,
            "must_not": [
                {"term": {"spec.keyword": "/"}},
                {"term": {"spec.keyword": ""}},
                # attr 中没有 attr.k 的文档
                {"nested": {"path": "attr", "query": {"exists": {"field": "attr.k"}}}},
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
        "henan": "dwd_henan_price",
        "heze": "dwd_heze_price",
        "qingdao": "dwd_qingdao_price",
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
                    # 待解析总数：spec 非空 且 attr 为空
                    "needs_parse": {
                        "filter": {"bool": {
                            "must_not": [
                                {"term": {"spec.keyword": "/"}},
                                {"term": {"spec.keyword": ""}},
                                {"nested": {"path": "attr", "query": {"exists": {"field": "attr.k"}}}},
                            ]
                        }}
                    },
                    # 已解析成功：spec 非空 且 attr 已有字段
                    "parsed_ok": {
                        "filter": {"bool": {
                            "must_not": [
                                {"term": {"spec.keyword": "/"}},
                                {"term": {"spec.keyword": ""}}
                            ],
                            "must": [
                                {"nested": {"path": "attr", "query": {"exists": {"field": "attr.k"}}}}
                            ]
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
        needs = b.get("needs_parse", {}).get("doc_count", 0)
        parsed_ok = b.get("parsed_ok", {}).get("doc_count", 0)
        # 分母 = needs_parse（待解析数） + parsed_ok（已解析数）= spec 有效的文档总数
        total = needs + parsed_ok
        # 覆盖率 = 1 - 待解析占比
        rate = round(parsed_ok / max(1, total) * 100, 1)
        coverage.append({
            "category": b["key"],
            "total": total,
            "with_attr": parsed_ok,
            "needs_parse": needs,
            "rate": rate,
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
        "henan": "dwd_henan_price",
        "heze": "dwd_heze_price",
    }
    dws_idx_map = {
        "xian": "dws_xian_price",
        "sichuan": "dws_sichuan_price",
        "chongqing": "dws_chongqing_price",
        "jinan": "dws_jinan_price",
        "rizhao": "dws_rizhao_price",
        "henan": "dws_henan_price",
    }
    dwd_idx = dwd_idx_map.get(city)
    if not dwd_idx:
        return {"ok": False, "message": f"未知城市: {city}"}
    dws_idx = dws_idx_map.get(city)

    try:
        sys.path.insert(0, ETL_CMD_DIR)
        from gov_price_etl.transform import transform_doc; from gov_price_etl.parse_spec import get_parser; from gov_price_etl.indexer import ensure_dwd
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
        from gov_price_etl.pipeline.dws_sync import sync_dws_with_ai
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
        "henan":     "dwd_henan_price",
        "heze":      "dwd_heze_price",
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
        from gov_price_etl.transform import transform_doc

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
        from gov_price_etl.pipeline.dws_sync import sync_dws_with_ai
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
                # 规范 attr 命名：去掉 attr_ 前缀，统一为"干净"名称
                # 兼容 AI 按 prompts.yml 要求生成的 attr_xxx 格式
                norm_attr = attr[5:] if attr.startswith("attr_") else attr
                ok = vs.insert(
                    pattern=pattern, attr=norm_attr, note=note or "",
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
        "user": "spec-fix-agent"
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


@router.post("/api/stats/spec-quality/batch-spec-parse")
def batch_spec_parse(req: BatchSpecParseRequest = Body(...)):
    """
    单条规格解析接口：输入 [{spec, breed, category}, ...]，逐条同步调用 AI 解析为 attr 结构。
    成功后可选写入规则库（write_rules=True）。
    返回 {ok, results: [{spec, ok, attr, failed_reason}], rules_written}
    """
    items = [{"spec": i.get("spec", ""), "breed": i.get("breed", ""), "category": i.get("category", "")}
             for i in req.items if i.get("spec")]
    if not items:
        return {"ok": False, "message": "items 不能为空"}

    all_results = []
    rules_written = 0

    ai_result = _call_batch_spec_parse_llm(items, len(items))
    if not ai_result.get("ok"):
        return {
            "ok": False,
            "message": ai_result.get("message", "AI 调用失败"),
            "results": [],
            "rules_written": 0,
        }
    results = ai_result.get("results", [])

    for i, item in enumerate(items):
        spec = item["spec"]
        r = results[i] if i < len(results) else {}
        suggestions = r.get("suggestions", [])
        ok = r.get("ok", False)
        attr = {}
        for s in suggestions:
            attr_name = s.get("attr", "")
            if not attr_name:
                continue
            code_block = s.get("code_block", "")
            # attr_natural 兜底：code_block 为空时，将原始 spec 值写入 attr_natural
            if attr_name == "attr_natural" and not code_block:
                attr["attr_natural"] = spec
                continue
            if code_block:
                try:
                    import re as re_mod
                    raw = code_block if isinstance(code_block, str) else "\n".join(code_block)
                    lines = raw.split("\n")
                    base_indent = None
                    for l in lines[1:]:
                        stripped = l.lstrip(" ")
                        if stripped:
                            base_indent = len(l) - len(stripped)
                            break
                    if base_indent is None:
                        base_indent = 0
                    clean_lines = []
                    for l in lines:
                        stripped = l.lstrip(" ")
                        if stripped:
                            ws = len(l) - len(stripped)
                            clean_lines.append(l[base_indent:] if ws >= base_indent else l[ws:])
                        else:
                            clean_lines.append("")
                    cb = "\n".join(clean_lines)
                    exec_globals = {"result": {}, "re": re_mod, "s": spec}
                    exec(cb, exec_globals)
                    attr.update(exec_globals.get("result", {}))
                except Exception:
                    pass
        all_results.append({
            "spec": spec,
            "ok": ok,
            "suggestions": suggestions,
        })
        if req.write_rules and ok and suggestions:
            if get_vec_store is not None:
                vs = get_vec_store()
                # 反查补全 category：请求为空时，从 category_v2_rules.db 反查（_resolve_category_for_breed 待实现）
                _breed_for_item = item.get("breed", "")
                _cat_for_item = item.get("category", "") or _resolve_category_for_breed(_breed_for_item)
                for s in suggestions:
                    attr_key = s.get("attr", "")
                    ok2 = vs.insert(
                        pattern=s.get("pattern", ""),
                        attr=attr_key,
                        note=s.get("note", "ai-single"),
                        code=s.get("code_block", "") if isinstance(s["code_block"], str) else "\n".join(s["code_block"]),
                        breed=_breed_for_item,
                        category=_cat_for_item,
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
        # 反查补全 category：请求为空时，从 category_v2_rules.db 反查（_resolve_category_for_breed 待实现）
        _s_breed = req.breed or s.get("breed", "")
        _s_category = req.category or s.get("category", "") or _resolve_category_for_breed(_s_breed)
        result = _apply_rule_to_base(
            code_block, s["attr"], s["note"], s.get("pattern", ""),
            _s_breed, _s_category,
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



# ── 清洗维度汇总（方案 A：分类清洗 + 规格清洗两个汇总面板）────────────
@router.get("/api/stats/clean-summary")
def clean_summary(
    dim: str = Query("category", pattern="^(category|spec)$", description="聚合维度: category=一级分类, spec=规格"),
    top_n: int = Query(30, ge=1, le=100, description="返回 top N 项"),
):
    """
    清洗维度汇总：按 category / spec 维度聚合全国 8 城 DWD 数据。

    返回每项：
      - key:         维度值
      - doc_count:   全国总文档数
      - city_count:  覆盖城市数（最大 8）
      - cities:      覆盖城市 key 列表
      - parse_rate:  attr 解析率（0-1，attr 字段存在的文档比例）
    """
    # spec 是 text 字段，聚合用 .keyword 子字段
    field = "category" if dim == "category" else "spec.keyword"

    def _query_city(city_key: str, dwd_idx: str):
        body = {
            "size": 0,
            "aggs": {
                "by_dim": {
                    "terms": {"field": field, "size": top_n},
                    "aggs": {
                        "with_attr": {
                            "filter": {
                                "nested": {
                                    "path": "attr",
                                    "query": {"match_all": {}}
                                }
                            }
                        }
                    }
                }
            }
        }
        r = safe_search(es, dwd_idx, body)
        return city_key, r.get("aggregations", {}).get("by_dim", {}).get("buckets", [])

    # 8 城并行查（每城一个 DWD 索引）
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(_query_city, k, v["dwd"]) for k, v in CITY_INDEXES().items()]
        # 每线程先聚合自己城市的数据，最后主线程串行 merge（避免 race）
        per_city: dict = {}
        for f in concurrent.futures.as_completed(futures):
            city_key, buckets = f.result()
            inner: dict = {}
            for b in buckets:
                k = b["key"]
                if k is None or k == "":
                    continue
                inner[k] = {
                    "count": b["doc_count"],
                    "with_attr": b["with_attr"]["doc_count"],
                }
            per_city[city_key] = inner

    # 串行 merge
    merged: dict = {}
    for city_key, dim_map in per_city.items():
        for k, v in dim_map.items():
            slot = merged.get(k)
            if slot is None:
                slot = {"key": k, "doc_count": 0, "cities": set(), "with_attr": 0}
                merged[k] = slot
            slot["doc_count"] += v["count"]
            slot["cities"].add(city_key)
            slot["with_attr"] += v["with_attr"]

    # 排序 + 序列化（set → sorted list）
    sorted_merged = sorted(merged.values(), key=lambda x: -x["doc_count"])
    items = []
    for v in sorted_merged[:top_n]:
        items.append({
            "key": v["key"],
            "doc_count": v["doc_count"],
            "city_count": len(v["cities"]),
            "cities": sorted(v["cities"]),
            "parse_rate": round(v["with_attr"] / v["doc_count"], 3) if v["doc_count"] else 0,
        })

    return {
        "dim": dim,
        "total": sum(v["doc_count"] for v in sorted_merged),  # 全国全量（不仅 top_n）
        "items": items,
        "cities_total": len(CITY_INDEXES()),
    }


# ══════════════════════════════════════════════════════════════
# category_v3_rules.db 查询端点（2026-06-18 起 v3 替代 v2）
# ──────────────────────────────────────────────────────────────
# 表 1：category_v3 (145 行) — 4 级分类体系（L1/L2/L3/L4 + 名称 + GB50500 + IFC + Uniclass）
#       严格按 GB 50854-2013 / GB/T 50856-2024 / GB 50857-2013 / GB 50858-2013 章节重建
# 表 2：breed_l3_map_v3 — 品种→L3 映射
# ══════════════════════════════════════════════════════════════


def _ensure_cat_v3_tables():
    """确保 category_v3_rules.db 的两张表存在（幂等）"""
    if not _RULES_DB_CAT_V3 or not os.path.exists(_RULES_DB_CAT_V3):
        return False
    try:
        conn = sqlite3.connect(_RULES_DB_CAT_V3)
        c = conn.cursor()
        c.execute(
            "CREATE TABLE IF NOT EXISTS category_v3 ("
            "  l1 TEXT NOT NULL, l2 TEXT NOT NULL, l3 TEXT NOT NULL, l4 TEXT NOT NULL,"
            "  gb_50500 TEXT NOT NULL,"
            "  ifc_class TEXT DEFAULT '', uniclass_ss TEXT DEFAULT '',"
            "  eng_part TEXT DEFAULT '', eng_stage TEXT DEFAULT '',"
            "  main_or_aux TEXT DEFAULT '', unit TEXT DEFAULT '',"
            "  billing_unit TEXT DEFAULT '', cost_method TEXT DEFAULT '',"
            "  name_l1 TEXT NOT NULL, name_l2 TEXT NOT NULL,"
            "  name_l3 TEXT NOT NULL, name_l4 TEXT DEFAULT '',"
            "  PRIMARY KEY (l1, l2, l3, l4)"
            ")"
        )
        c.execute(
            "CREATE TABLE IF NOT EXISTS breed_l3_map_v3 ("
            "  breed_clean TEXT PRIMARY KEY,"
            "  l3 TEXT NOT NULL,"
            "  source TEXT DEFAULT 'ai',"
            "  confidence REAL DEFAULT 1.0,"
            "  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,"
            "  updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP"
            ")"
        )
        conn.commit()
        conn.close()
        return True
    except Exception:
        return False


@router.get("/api/stats/category-v2-stats")
def category_v2_stats():
    """category_v3_rules.db 整体统计：分类法条数 / 映射条数 / 来源分布 / L3 覆盖率

    端点路径保持 v2 名称（向前兼容），但底层数据来自 v3。
    """
    if not _ensure_cat_v3_tables():
        return {"ok": False, "message": "category_v3_rules.db 不存在或无法访问"}

    conn = sqlite3.connect(_RULES_DB_CAT_V3)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    # 分类法表
    c.execute("SELECT COUNT(*) AS n FROM category_v3")
    taxonomy_total = c.fetchone()["n"]
    c.execute("SELECT COUNT(DISTINCT l1) AS n FROM category_v3")
    l1_count = c.fetchone()["n"]
    c.execute("SELECT COUNT(DISTINCT l2) AS n FROM category_v3")
    l2_count = c.fetchone()["n"]
    c.execute("SELECT COUNT(DISTINCT l3) AS n FROM category_v3")
    l3_total = c.fetchone()["n"]
    c.execute("SELECT COUNT(DISTINCT l4) AS n FROM category_v3 WHERE l4 != 'UNCLASSIFIED'")
    l4_count = c.fetchone()["n"]

    # 品种映射表
    c.execute("SELECT COUNT(*) AS n FROM breed_l3_map_v3")
    map_total = c.fetchone()["n"]
    c.execute(
        "SELECT source, COUNT(*) AS n FROM breed_l3_map_v3 GROUP BY source ORDER BY n DESC"
    )
    source_buckets = [{"source": r["source"], "count": r["n"]} for r in c.fetchall()]
    c.execute(
        "SELECT confidence, COUNT(*) AS n FROM breed_l3_map_v3 "
        "GROUP BY ROUND(confidence, 2) ORDER BY confidence DESC"
    )
    confidence_buckets = [
        {"confidence": round(r["confidence"], 2), "count": r["n"]} for r in c.fetchall()
    ]
    # L3 命中率（映射的 l3 是否都存在于分类法）
    c.execute(
        "SELECT COUNT(DISTINCT m.l3) AS n "
        "FROM breed_l3_map_v3 m "
        "WHERE m.l3 IN (SELECT l3 FROM category_v3)"
    )
    l3_hit = c.fetchone()["n"]
    c.execute(
        "SELECT COUNT(DISTINCT m.l3) AS n FROM breed_l3_map_v3 m "
        "WHERE m.l3 NOT IN (SELECT l3 FROM category_v3)"
    )
    l3_miss = c.fetchone()["n"]
    conn.close()

    return {
        "ok": True,
        "taxonomy": {
            "total": taxonomy_total,
            "l1": l1_count,
            "l2": l2_count,
            "l3": l3_total,
            "l4": l4_count,
        },
        "map": {
            "total": map_total,
            "source_buckets": source_buckets,
            "confidence_buckets": confidence_buckets,
            "l3_in_taxonomy": l3_hit,
            "l3_not_in_taxonomy": l3_miss,
        },
    }


@router.get("/api/stats/category-v2-taxonomy")
def category_v2_taxonomy(
    l1: str = "",
    l2: str = "",
    keyword: str = "",
    sort_by: str = "l3",
    sort_dir: str = "asc",
    page: int = 1,
    page_size: int = 50,
):
    """查询 category_v2（3 级分类体系），支持 L1/L2 过滤 + 关键字搜索（按名称/编码/GB50500）+ 排序"""
    if not _ensure_cat_v3_tables():
        return {"rows": [], "total": 0, "page": page, "page_size": page_size}

    # 白名单防 SQL 注入
    sort_cols = {"l1", "l2", "l3", "gb_50500", "name_l1", "name_l3", "eng_part", "main_or_aux", "unit"}
    sort_col = sort_by if sort_by in sort_cols else "l3"
    sort_d = "DESC" if str(sort_dir).lower() == "desc" else "ASC"

    conn = sqlite3.connect(_RULES_DB_CAT_V3)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    where = []
    params = []
    if l1:
        where.append("l1 = ?")
        params.append(l1)
    if l2:
        where.append("l2 = ?")
        params.append(l2)
    if keyword:
        kw = f"%{keyword}%"
        where.append(
            "(name_l1 LIKE ? OR name_l2 LIKE ? OR name_l3 LIKE ? "
            "OR l1 LIKE ? OR l2 LIKE ? OR l3 LIKE ? "
            "OR gb_50500 LIKE ? OR ifc_class LIKE ? OR uniclass_ss LIKE ?)"
        )
        params.extend([kw] * 9)

    where_sql = " AND ".join(where) if where else "1=1"

    c.execute(f"SELECT COUNT(*) AS n FROM category_v3 WHERE {where_sql}", params)
    total = c.fetchone()["n"]

    offset = (page - 1) * page_size
    # 主排序 + 次排序保证稳定
    secondary = "l1, l2" if sort_col not in ("l1", "l2") else "l3"
    c.execute(
        f"SELECT l1, l2, l3, gb_50500, ifc_class, uniclass_ss, "
        f"eng_part, eng_stage, main_or_aux, unit, billing_unit, cost_method, "
        f"name_l1, name_l2, name_l3 "
        f"FROM category_v3 WHERE {where_sql} "
        f"ORDER BY {sort_col} {sort_d}, {secondary} LIMIT ? OFFSET ?",
        params + [page_size, offset],
    )
    rows = [dict(r) for r in c.fetchall()]

    # 过滤选项（L1/L2 下拉用）
    c.execute("SELECT DISTINCT l1 FROM category_v3 ORDER BY l1")
    l1_options = [r["l1"] for r in c.fetchall()]
    c.execute("SELECT DISTINCT l1, l2 FROM category_v3 ORDER BY l1, l2")
    l2_options = [{"l1": r["l1"], "l2": r["l2"]} for r in c.fetchall()]
    conn.close()

    return {
        "rows": rows,
        "total": total,
        "page": page,
        "page_size": page_size,
        "l1_options": l1_options,
        "l2_options": l2_options,
    }


@router.get("/api/stats/category-v2-breed-map")
def category_v2_breed_map(
    keyword: str = "",
    l3: str = "",
    source: str = "",
    min_confidence: float = Query(0.0, ge=0.0, le=1.0),
    page: int = 1,
    page_size: int = 50,
):
    """查询 breed_l3_map（品种→L3 映射），支持品种关键字 / L3 过滤 / 来源过滤 / 置信度阈值"""
    if not _ensure_cat_v3_tables():
        return {"rows": [], "total": 0, "page": page, "page_size": page_size}

    conn = sqlite3.connect(_RULES_DB_CAT_V3)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    where = []
    params = []
    if keyword:
        where.append("breed_clean LIKE ?")
        params.append(f"%{keyword}%")
    if l3:
        where.append("m.l3 = ?")
        params.append(l3)
    if source:
        where.append("source = ?")
        params.append(source)
    if min_confidence and min_confidence > 0:
        where.append("confidence >= ?")
        params.append(min_confidence)

    where_sql = " AND ".join(where) if where else "1=1"

    # 关联分类法表拿 name_l3
    c.execute(
        f"SELECT m.breed_clean, m.l3, m.source, m.confidence, m.created_at, m.updated_at, "
        f"t.name_l1, t.name_l2, t.name_l3 "
        f"FROM breed_l3_map_v3 m "
        f"LEFT JOIN category_v3 t ON m.l3 = t.l3 "
        f"WHERE {where_sql} "
        f"ORDER BY m.confidence DESC, m.breed_clean LIMIT ? OFFSET ?",
        params + [page_size, (page - 1) * page_size],
    )
    rows = [dict(r) for r in c.fetchall()]

    c.execute(
        f"SELECT COUNT(*) AS n FROM breed_l3_map_v3 m WHERE {where_sql}", params
    )
    total = c.fetchone()["n"]

    # 过滤选项
    c.execute("SELECT DISTINCT source FROM breed_l3_map_v3 ORDER BY source")
    source_options = [r["source"] for r in c.fetchall()]
    c.execute("SELECT DISTINCT l3 FROM breed_l3_map_v3 ORDER BY l3")
    l3_options = [r["l3"] for r in c.fetchall()]
    conn.close()

    return {
        "rows": rows,
        "total": total,
        "page": page,
        "page_size": page_size,
        "source_options": source_options,
        "l3_options": l3_options,
    }


@router.get("/api/stats/category-v2-l3-detail")
def category_v2_l3_detail(l3: str = Query(...)):
    """查询指定 L3 的完整信息 + 该 L3 下所有品种映射（聚合）"""
    if not _ensure_cat_v3_tables():
        return {"ok": False, "message": "category_v2_rules.db 不存在或无法访问"}

    conn = sqlite3.connect(_RULES_DB_CAT_V3)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    # 分类法里该 L3 的所有 L4 行
    c.execute(
        "SELECT l1, l2, l3, l4, gb_50500, ifc_class, uniclass_ss, "
        "eng_part, eng_stage, main_or_aux, unit, billing_unit, cost_method, "
        "name_l1, name_l2, name_l3, name_l4 "
        "FROM category_v3 WHERE l3 = ? ORDER BY l4",
        (l3,),
    )
    taxonomy_rows = [dict(r) for r in c.fetchall()]

    # 该 L3 下的品种数 + 来源分布
    c.execute(
        "SELECT source, COUNT(*) AS n FROM breed_l3_map_v3 WHERE l3 = ? GROUP BY source",
        (l3,),
    )
    source_dist = [{"source": r["source"], "count": r["n"]} for r in c.fetchall()]
    c.execute("SELECT COUNT(*) AS n FROM breed_l3_map_v3 WHERE l3 = ?", (l3,))
    breed_count = c.fetchone()["n"]
    c.execute(
        "SELECT AVG(confidence) AS avg_conf FROM breed_l3_map_v3 WHERE l3 = ?",
        (l3,),
    )
    avg_conf = c.fetchone()["avg_conf"] or 0
    conn.close()

    return {
        "ok": True,
        "l3": l3,
        "taxonomy_rows": taxonomy_rows,
        "source_dist": source_dist,
        "breed_count": breed_count,
        "avg_confidence": round(avg_conf, 4),
    }


# ── 定时检查任务状态 ────────────────────────────────────────────────────

STATUS_DIR = "/tmp/gov-check-status"


@router.get("/api/stats/check-status")
def api_check_status():
    """返回各城市定时检查任务的最新状态（从 skill registry 动态发现城市）"""
    results = {}
    for s in _registry_get_all():
        city = s["key"]
        label = s.get("label", city)
        fpath = os.path.join(STATUS_DIR, f"{city}.json")
        if os.path.exists(fpath):
            try:
                with open(fpath) as f:
                    results[city] = json.load(f)
            except Exception:
                results[city] = {"city": city, "label": label, "status": "error", "output": "读取失败"}
        else:
            results[city] = {"city": city, "label": label, "status": "pending", "output": ""}
    return {"ok": True, "cities": results}


# ── 通用 sync-progress 端点（按 progress_mode 分发）──────────────────────
# 替代原 main.py 中 9 个手写 *sync-progress 端点
# 加新 skill：只需在 skill.yml 设 progress_mode + (county_field|catalogue_field) + 可选 group_by/summary_marker
# 不再需要改 dashboard 代码

def _read_last_period_from_cfg(cfg_path: str, key: str = "last_period") -> str:
    """从 skill config.yml 读 last_period / last_update_date"""
    if not cfg_path or not os.path.exists(cfg_path):
        return ""
    try:
        with open(cfg_path, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
        return (cfg.get("sync", {}) or {}).get(key, "") or ""
    except Exception:
        return ""


def _period_sync_progress(cfg: dict) -> dict:
    """period 模式：heze / henan / qingdao / weihai 等按 PDF 期刊跟踪的 skill

    进度索引里每期一条 status=ok 的记录，按 created_at 倒序列出详情。
    """
    progress_index = cfg.get("progress_index")
    data_index = cfg.get("ods_index")
    cfg_path = cfg.get("config_path", "")

    all_hits = es.search(index=progress_index, body={
        "size": 50,
        "sort": [{"created_at": "desc"}],
        "query": {"match_all": {}}
    }, ignore_unavailable=True)
    records = all_hits.get("hits", {}).get("hits", [])

    period_details = []
    total_docs = 0
    completed = 0
    running = 0
    errored = 0
    latest_period = ""
    latest_created_at = ""
    latest_doc = None

    for h in records:
        src = h["_source"]
        raw_status = src.get("status", "ok")
        if raw_status == "ok":
            status_norm = "completed"
            completed += 1
        elif raw_status in ("running", "in_progress"):
            status_norm = "running"
            running += 1
        else:
            status_norm = raw_status or "completed"
            completed += 1
        docs_written = src.get("docs_written", 0) or 0
        total_docs += docs_written
        period_details.append({
            "period": src.get("period", ""),
            "publish_date": src.get("publish_date", ""),
            "status": status_norm,
            "percent": 100.0 if status_norm == "completed" else 0,
            "docs_written": docs_written,
            "duration_sec": src.get("duration_sec", 0),
            "created_at": src.get("created_at", ""),
            "pdf_url": src.get("pdf_url", ""),
            "minio_key": src.get("minio_key", ""),
        })
        ca = src.get("created_at", "")
        if ca and ca > latest_created_at:
            latest_created_at = ca
            latest_period = src.get("period", "")
            latest_doc = src

    overall_status = "ok" if running == 0 and errored == 0 else ("running" if running else "error")
    last_updated = latest_created_at[:19] if latest_created_at else ""

    last_sync_period = _read_last_period_from_cfg(cfg_path, "last_period")
    es_latest_period = latest_period
    if last_sync_period and es_latest_period:
        has_incremental = es_latest_period > last_sync_period
    elif es_latest_period and not last_sync_period:
        has_incremental = True
    else:
        has_incremental = False

    period_doc_count: dict = {}
    try:
        cnt = es.search(index=data_index, body={
            "size": 0,
            "aggs": {"by_period": {"terms": {"field": "period", "size": 20}}}
        })
        period_doc_count = {b["key"]: b["doc_count"] for b in cnt.get("aggregations", {}).get("by_period", {}).get("buckets", [])}
    except Exception:
        pass

    return {
        "run_id": latest_period,
        "status": overall_status,
        "period": latest_period,
        "duration_sec": (latest_doc or {}).get("duration_sec", 0),
        "last_updated": last_updated,
        "error": (latest_doc or {}).get("error", ""),
        "total_docs": total_docs,
        "total_written": total_docs,
        "current_page": 0,
        "total_pages": 0,
        "current_period": latest_period,
        "completed_periods": completed,
        "total_periods": len(period_details),
        "period_details": period_details,
        "has_incremental": has_incremental,
        "last_sync_period": last_sync_period,
        "es_latest_period": es_latest_period,
        "period_doc_count": period_doc_count,
    }


def _county_sync_progress(cfg: dict) -> dict:
    """county 模式：xian / chongqing 等按区县抓取的 skill

    - 多数 skill（xian 等）：county_field 标记主键（current_county / area），group_by=run_id
    - chongqing：progress 文档有"汇总"占位（area="全部完成"），用 summary_marker 区分
    """
    progress_index = cfg.get("progress_index")
    data_index = cfg.get("ods_index")
    cfg_path = cfg.get("config_path", "")
    county_field = cfg.get("county_field", "current_county")
    group_by = cfg.get("group_by", "run_id")
    summary_marker = cfg.get("summary_marker")
    county_total = len(cfg.get("cities", []) or [0])

    total_docs = 0
    try:
        total_docs = es.count(index=data_index).get("count", 0)
    except Exception:
        pass

    all_hits = es.search(index=progress_index, body={
        "size": 200,
        "query": {
            "bool": {
                "must": [{"exists": {"field": county_field}}],
                "must_not": [{"term": {county_field: ""}}],
            }
        }
    }, ignore_unavailable=True).get("hits", {}).get("hits", [])

    if not all_hits:
        return {
            "run_id": "", "status": "", "current_county": "",
            "current_page": 0, "total_pages": 0, "total_records": 0,
            "docs_written": 0, "percent": 0, "duration_sec": 0,
            "update_date": "", "last_updated": "", "error": "",
            "completed_counties": 0, "total_counties": county_total,
            "total_docs": total_docs, "county_details": [],
            "has_incremental": False,
        }

    # 取最新 run_id / 最新 last_updated
    if group_by == "run_id":
        # 按 run_id 倒序取最新一个
        all_hits.sort(key=lambda r: (r["_source"].get("run_id", ""), r["_source"].get("last_updated", "")), reverse=True)
        latest_run_id = all_hits[0]["_source"].get("run_id", "")
        run_records = [r for r in all_hits if r["_source"].get("run_id", "") == latest_run_id]
    else:
        # 按 last_updated desc 取最新一条
        all_hits.sort(key=lambda r: r["_source"].get("last_updated", ""), reverse=True)
        run_records = all_hits

    # 分离 summary（可选，chongqing 用 area="全部完成"）
    summary_record = None
    county_records = run_records
    if summary_marker:
        for r in run_records:
            if r["_source"].get(county_field) == summary_marker:
                summary_record = r
                break
        county_records = [r for r in run_records if r["_source"].get(county_field) != summary_marker]

    # 去重（county_field 相同取最新）
    seen = set()
    unique = []
    for r in county_records:
        c = r["_source"].get(county_field, "")
        if c and c not in seen:
            seen.add(c)
            unique.append(r)
    county_records = unique

    # chongqing 特殊处理：area 字段会被 sync 端写成 "区县材料-万州区"/"预拌砂浆-..."
    # 这种带前缀的 raw 文本，原样返回会让前端和进度计数都出错。
    # 这里按 area 前缀反推 source、剥离前缀，保证返回的 county 字段是纯净的区县名，
    # _parse_area 已抽到模块顶部（2026-07-02）。
    # 同时给前端一个 source_summary 做分组统计（其他 city：source 默认 district，行为不变）。

    county_details = sorted([{
        "county": _parse_area(r["_source"].get(county_field, ""))[0],
        "source": _parse_area(r["_source"].get(county_field, ""))[1],
        "status": r["_source"].get("status", ""),
        "current_page": r["_source"].get("current_page", 0),
        "total_pages": r["_source"].get("total_pages", 0),
        "total_records": r["_source"].get("total_records", 0),
        "docs_written": r["_source"].get("docs_written", 0),
        "doc_count": r["_source"].get("docs_written", 0),
        "percent": round(r["_source"].get("percent", 0), 2),
        "period": r["_source"].get("period", ""),
        "update_date": r["_source"].get("update_date", ""),
        "last_updated": r["_source"].get("last_updated", ""),
        "duration_sec": round(r["_source"].get("duration_sec", 0), 2),
        "error": r["_source"].get("error", ""),
    } for r in county_records], key=lambda x: x["county"])

    # 整体状态
    if summary_record:
        overall_status = summary_record["_source"].get("status", "completed")
        overall_duration = round(summary_record["_source"].get("duration_sec", 0), 2)
        overall_last_updated = summary_record["_source"].get("last_updated", "")
    else:
        overall_status = "completed"
        for d in county_details:
            if d["status"] == "running":
                overall_status = "running"
                break
            if d["status"] == "interrupted":
                overall_status = "interrupted"
        overall_duration = 0
        overall_last_updated = county_details[-1]["last_updated"] if county_details else ""

    # 主任务（district 区县）的完成数。若所有条目都是同一 source（比如 xian），
    # 行为退化为按 status 全量统计，等价于老逻辑。
    source_set = {d.get("source", "district") for d in county_details}
    if len(source_set) > 1:
        # 多 source 的 skill（如 chongqing）：只统计主项区县
        # 兼容 'ok' 状态（xinjiang 等 skill 写入的完成状态）
        completed_counties = sum(
            1 for d in county_details
            if d.get("status") in ("completed", "ok") and d.get("source") == "district"
        )
    else:
        completed_counties = sum(1 for d in county_details if d.get("status") in ("completed", "ok"))

    # 多 source 分组汇总：返回每个 source 的总数 / 完成 / 错误
    source_summary: dict[str, dict] = {}
    for d in county_details:
        src = d.get("source", "district")
        bucket = source_summary.setdefault(src, {"total": 0, "completed": 0, "error": 0, "running": 0})
        bucket["total"] += 1
        st = d.get("status", "")
        # 兼容 'ok'（xinjiang）。'partial' 单独归到 partial 桶，不算 completed
        if st in ("completed", "ok"):
            bucket["completed"] += 1
        elif st == "partial":
            bucket.setdefault("partial", 0)
            bucket["partial"] += 1
        elif st == "error":
            bucket["error"] += 1
        elif st == "running":
            bucket["running"] += 1
    running = next((d for d in county_details if d["status"] == "running"), None)
    current_county = running.get("county", "") if running else ""
    current_page = running.get("current_page", 0) if running else 0
    total_pages = running.get("total_pages", 0) if running else 0

    # 增量检测：last_period 对比 ES 最新 period
    last_sync_period = _read_last_period_from_cfg(cfg_path, "last_period")
    es_latest_period = ""
    if county_details:
        for d in reversed(county_details):
            if d.get("period"):
                es_latest_period = d["period"]
                break
    if last_sync_period and es_latest_period:
        has_incremental = es_latest_period > last_sync_period
    elif es_latest_period and not last_sync_period:
        has_incremental = True
    else:
        has_incremental = False

    return {
        "run_id": (summary_record or run_records[0])["_source"].get("run_id", "") if run_records else "",
        "status": overall_status,
        "period": (summary_record or run_records[0])["_source"].get("period", "") if run_records else "",
        "current_county": current_county,
        "current_page": current_page,
        "total_pages": total_pages,
        "docs_written": sum(d.get("docs_written", 0) for d in county_details),
        "duration_sec": overall_duration,
        "last_updated": overall_last_updated,
        "error": (summary_record or {}).get("_source", {}).get("error", "") if summary_record else "",
        "completed_counties": completed_counties,
        "total_counties": county_total,
        "total_docs": total_docs,
        "county_details": county_details,
        "source_summary": source_summary,
        "has_incremental": has_incremental,
        "last_sync_period": last_sync_period,
        "es_latest_period": es_latest_period,
        # 兼容 xian 旧字段（spot_check）
        "spot_check_ok": (run_records[0]["_source"].get("spot_check_ok") if run_records else None) if county_field == "current_county" else None,
        "spot_check_details": (run_records[0]["_source"].get("spot_check_details", "") if run_records else "") if county_field == "current_county" else "",
    }


def _catalogue_sync_progress(cfg: dict) -> dict:
    """catalogue 模式：sichuan / jinan / rizhao 等按分类目录抓取的 skill

    - sichuan：catalogue_field=area, group_by=run_id
    - jinan / rizhao：group_by=latest（按最新 last_updated 去重）
    """
    progress_index = cfg.get("progress_index")
    data_index = cfg.get("ods_index")
    cfg_path = cfg.get("config_path", "")
    catalogue_field = cfg.get("catalogue_field", "catalogue")
    group_by = cfg.get("group_by", "run_id")

    total_docs = 0
    try:
        total_docs = es.count(index=data_index).get("count", 0)
    except Exception:
        pass

    all_hits = es.search(index=progress_index, body={
        "size": 100,
        "query": {
            "bool": {
                "must": [{"exists": {"field": catalogue_field}}],
                "must_not": [{"term": {catalogue_field: ""}}],
            }
        }
    }, ignore_unavailable=True).get("hits", {}).get("hits", [])

    if not all_hits:
        return {
            "run_id": "", "status": "", "period": "", "duration_sec": 0,
            "last_updated": "", "error": "", "total_docs": total_docs,
            "catalogue_details": [],
        }

    if group_by == "run_id":
        all_hits.sort(key=lambda r: (r["_source"].get("run_id", ""), r["_source"].get("last_updated", "")), reverse=True)
        latest_run_id = all_hits[0]["_source"].get("run_id", "")
        records = [r for r in all_hits if r["_source"].get("run_id", "") == latest_run_id]
    else:
        all_hits.sort(key=lambda r: r["_source"].get("last_updated", ""), reverse=True)
        records = all_hits

    # 去重（catalogue_field 相同取最新）
    seen = set()
    unique = []
    for r in records:
        c = r["_source"].get(catalogue_field, "")
        if c and c not in seen:
            seen.add(c)
            unique.append(r)

    # 详情字段映射：默认 "catalogue_details" 列表元素以 catalogue/catalogue_name 为 id
    def _derive_percent(src: dict) -> float:
        """percent 兜底派生：优先用 ES 文档原值，缺失时用 docs_written/total_records 派生。

        触发场景：rizhao v1.0 collector 写 ES progress 时漏写 percent 字段，
        但 docs_written/total_records 都有，足以派生（unit 完成时 = 100%）。
        """
        raw = src.get("percent")
        if raw is not None and raw != 0:
            return round(float(raw), 2)
        dw = src.get("docs_written", 0) or 0
        tr = src.get("total_records", 0) or src.get("total_count", 0) or 0
        if dw and tr:
            return round(dw / tr * 100, 2)
        return 0.0

    cat_details = sorted([{
        "catalogue": r["_source"].get(catalogue_field, ""),
        "catalogue_name": r["_source"].get(f"{catalogue_field}_name", "") or r["_source"].get("catalogue_name", "") or r["_source"].get("tab_name", ""),
        "tab_type": r["_source"].get("tab_type", ""),
        "tab_name": r["_source"].get("tab_name", ""),
        # 状态归一化：'ok' → 'completed'（兼容 rizhao 历史写入格式）
        "status": "completed" if r["_source"].get("status") == "ok" else r["_source"].get("status", ""),
        "period": r["_source"].get("period", ""),
        "current_page": r["_source"].get("current_page", 0),
        "total_pages": r["_source"].get("total_pages", 0),
        "total_records": r["_source"].get("total_records", 0) or r["_source"].get("total_count", 0),
        "docs_written": r["_source"].get("docs_written", 0),
        "percent": _derive_percent(r["_source"]),
        "last_updated": r["_source"].get("last_updated", ""),
        "duration_sec": round(r["_source"].get("duration_sec", 0), 2),
    } for r in unique], key=lambda x: x.get("catalogue_name") or x.get("catalogue"))

    latest_record = all_hits[0]["_source"]
    # 状态归一化：'ok' → 'completed'
    _raw_status = latest_record.get("status", "completed")
    overall_status = "completed" if _raw_status == "ok" else _raw_status
    overall_run_id = latest_record.get("run_id", "")
    overall_duration = round(latest_record.get("duration_sec", 0), 2)
    last_updated = latest_record.get("last_updated", "")
    total_written = sum(d.get("docs_written", 0) for d in cat_details)

    running_cat = next((d for d in cat_details if d["status"] == "running"), None)
    current_page = running_cat.get("current_page", 0) if running_cat else 0
    total_pages = running_cat.get("total_pages", 0) if running_cat else 0

    # 增量检测
    last_sync_period = _read_last_period_from_cfg(cfg_path, "last_period")
    es_latest_period = ""
    try:
        es_res = es.search(index=data_index, body={
            "size": 1, "sort": [{"update_date": "desc"}], "_source": ["period"]
        })
        es_h = es_res.get("hits", {}).get("hits", [])
        if es_h:
            es_latest_period = es_h[0]["_source"].get("period", "")
    except Exception:
        pass
    if last_sync_period and es_latest_period:
        has_incremental = es_latest_period > last_sync_period
    elif es_latest_period and not last_sync_period:
        has_incremental = True
    else:
        has_incremental = False

    return {
        "run_id": overall_run_id,
        "status": overall_status,
        "period": latest_record.get("period", ""),
        "duration_sec": overall_duration,
        "last_updated": last_updated,
        "error": latest_record.get("error", ""),
        "total_docs": total_docs,
        "total_written": total_written,
        "current_page": current_page,
        "total_pages": total_pages,
        "current_catalogue": running_cat.get("catalogue", "") if running_cat else "",
        "current_catalogue_name": running_cat.get("catalogue_name", "") if running_cat else "",
        "current_tab": latest_record.get("tab_name", ""),
        "catalogue_details": cat_details,
        "has_incremental": has_incremental,
        "last_sync_period": last_sync_period,
        "es_latest_period": es_latest_period,
    }


# 模式分发
_MODE_DISPATCH = {
    "period": _period_sync_progress,
    "county": _county_sync_progress,
    "catalogue": _catalogue_sync_progress,
}


def sync_progress(cfg: dict) -> dict:
    """通用 sync-progress 入口：按 cfg["progress_mode"] 分发到对应 mode 函数"""
    mode = cfg.get("progress_mode", "period")
    fn = _MODE_DISPATCH.get(mode)
    if not fn:
        raise HTTPException(status_code=400, detail=f"未知 progress_mode: {mode}")
    return fn(cfg)
