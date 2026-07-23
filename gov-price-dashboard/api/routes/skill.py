"""Phase 5 抽取: /api/skill-updates + /api/skill-registry + /api/skill-registry/reload (原 main.py 内联实现)"""
from datetime import datetime
import concurrent.futures
import requests
from fastapi import APIRouter, Request

from api.dependencies import es, ALL_INDICES, ALL_ODS_INDICES
from api.helpers.es_safe import filter_existing_indices
from api.skill_registry import (
    get_all as _registry_get_all,
    reload as _registry_reload,
    ods_indices_csv as _registry_ods_csv,
)

router = APIRouter()


@router.get("/api/skill-updates")
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

@router.get("/api/skill-registry")
def skill_registry():
    """返回所有已注册 skill 的清单（前端 v-for 驱动）"""
    return {
        "count": len(_registry_get_all()),
        "skills": _registry_get_all(),
    }


@router.post("/api/skill-registry/reload")
def skill_registry_reload():
    """手动重新扫描 skill.yml（开发调试用）+ 热更新 ALL_INDICES / ALL_ODS_INDICES"""
    global ALL_INDICES, ALL_ODS_INDICES
    skills = _registry_reload()
    # 重新计算索引列表：与启动邇辑一致，过滤掉 ES 中不存在的索引
    new_csv = _registry_ods_csv() or ALL_INDICES
    ALL_INDICES = filter_existing_indices(es, new_csv, log_label="ALL_INDICES")
    ALL_ODS_INDICES = new_csv
    return {
        "count": len(skills),
        "skills": skills,
        "all_indices": ALL_INDICES,
        "message": f"重载完成，扫描到 {len(skills)} 个 skill，ALL_INDICES 已热更新",
    }