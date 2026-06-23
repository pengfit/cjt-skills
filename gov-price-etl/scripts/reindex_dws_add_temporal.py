#!/usr/bin/env python3
"""DWS 时序字段 reindex 脚本（2026-06-23）

加 6 个时序字段：create_time / source_publish_date / period_granularity / period_start/end/days / period_id

每个 DWS 索引流程：
  1. dws_<city>_price 旧索引 → 重命名为 dws_<city>_price_v1_bak（保留快照）
  2. 新建 dws_<city>_price（套用新 gov_dws template，自动含 6 字段）
  3. reindex from v1_bak → 新索引（用 script 补字段 + 兼容 9 城不同 period_granularity）
  4. 验证文档数一致 + 抽样检查
  5. 删 v1_bak（30 天后自动清理策略保留备份）
"""
import sys, os, json, time
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.expanduser("~/.openclaw/workspace/skills/gov-price-dashboard"))

from elasticsearch import Elasticsearch
from gov_price_etl.mappings import build_dws_mapping
from api.skill_registry import get_all  # noqa: E402  # 复用 dashboard registry

ES_HOST = "http://localhost:59200"
es = Elasticsearch([ES_HOST])


# 9 城 DWS 索引与 period_granularity 映射表
CITY_GRANULARITY = {
    "xian":      "monthly",
    "sichuan":   "monthly",
    "chongqing": "monthly",
    "jinan":     "irregular",   # jinan 不规则（按 catalogue 名）
    "rizhao":    "monthly",
    "heze":      "monthly",
    "henan":     "monthly",
    "qingdao":   "monthly",
    "weihai":    "quarterly",   # 季度
}


def derive_period_dates(doc, granularity):
    """根据文档 + 周期类型，派生 period_start / period_end / period_days

    monthly   → start=update_date 当月 1 号, end=月末
    quarterly → start=update_date 季度首, end=季度末
    """
    ud = doc.get("update_date", "")
    if not ud:
        return "", "", 0
    try:
        y, m, d = ud.split("-")[:3]
        y, m, d = int(y), int(m), int(d)
    except Exception:
        return "", "", 0

    if granularity == "monthly":
        # 月首 + 月末
        if m == 12:
            start = f"{y}-12-01"
            end = f"{y}-12-31"
        else:
            import calendar
            last_day = calendar.monthrange(y, m)[1]
            start = f"{y}-{m:02d}-01"
            end = f"{y}-{m:02d}-{last_day:02d}"
        return start, end, (int(end[-2:]) - int(start[-2:]) + 1)
    elif granularity == "quarterly":
        # 季度
        q = (m - 1) // 3 + 1   # 1-4
        start_m = (q - 1) * 3 + 1
        end_m = q * 3
        import calendar
        last_day = calendar.monthrange(y, end_m)[1]
        start = f"{y}-{start_m:02d}-01"
        end = f"{y}-{end_m:02d}-{last_day:02d}"
        return start, end, (end_m - start_m + 1) * 30
    else:  # irregular / 其它
        return ud, ud, 1


def reindex_city(city_key: str, dry_run: bool = False) -> dict:
    cfg = next((s for s in get_all() if s["key"] == city_key), None)
    if not cfg:
        return {"ok": False, "error": f"未知 city: {city_key}"}
    dws = cfg.get("dws_index")
    if not dws:
        return {"ok": False, "error": f"no dws_index for {city_key}"}

    granularity = CITY_GRANULARITY.get(city_key, "monthly")
    v1_name = f"{dws}_v1_bak"
    result = {"city": city_key, "dws_index": dws, "granularity": granularity, "steps": []}

    # 1. 检查源索引：优先 dws，其次 v1_bak
    if es.indices.exists(index=dws):
        src_name = dws
    elif es.indices.exists(index=v1_name):
        src_name = v1_name
    else:
        return {**result, "ok": False, "error": f"源索引不存在: {dws}（也未找到 v1_bak {v1_name}）"}
    src_count = es.count(index=src_name)["count"]
    result["src_count"] = src_count
    result["steps"].append(f"src {src_name}: {src_count} docs")

    # 2. v1_bak 已存在则跳过（避免覆盖）
    if es.indices.exists(index=v1_name):
        result["steps"].append(f"v1_bak 已存在: {v1_name}（跳过 rename）")
        # 直接 reindex from v1_bak
        old_name = v1_name
        # 如果 dws 也存在，先删（可能上次 create 了一半）
        if es.indices.exists(index=dws):
            es.indices.delete(index=dws)
            result["steps"].append(f"删已存在的空 {dws}")
    else:
        # rename dws → v1_bak
        if not dry_run:
            try:
                # clone 要求源只读，先 set blocks.write=true
                es.indices.put_settings(index=dws, body={
                    "index.blocks.write": True
                })
                es.indices.clone(index=dws, target=v1_name)
                es.indices.put_settings(index=dws, body={
                    "index.blocks.write": False
                }) if es.indices.exists(index=dws) else None
                es.indices.delete(index=dws)
                result["steps"].append(f"clone {dws} → {v1_name} OK, deleted original")
            except Exception as e:
                result["steps"].append(f"clone failed: {e}")
                # 回退：恢复 write block
                try:
                    if es.indices.exists(index=dws):
                        es.indices.put_settings(index=dws, body={"index.blocks.write": False})
                except Exception:
                    pass
                return {**result, "ok": False, "error": str(e)}
            old_name = v1_name
        else:
            result["steps"].append(f"[dry_run] clone {dws} → {v1_name}")
            old_name = dws

    # 3. 新建 dws_<city>（用新 mapping，含 6 字段）
    new_mapping = build_dws_mapping()
    if not dry_run:
        es.indices.create(index=dws, body={
            "mappings": new_mapping["mappings"],
            "settings": new_mapping["settings"],
        })
        result["steps"].append(f"created new {dws} with new mapping")
    else:
        result["steps"].append(f"[dry_run] create {dws}")

    # 4. reindex（带 script 补字段）
    body = {
        "source": {"index": old_name, "size": 1000},
        "dest": {"index": dws},
        "script": {
            "lang": "painless",
            "params": {
                "GRANULARITY": granularity,
            },
            "source": """
                // 1. period_granularity 固定（从硬编码表查）
                ctx._source.period_granularity = params.GRANULARITY;

                // 2. create_time：ODS 已有，透传；老数据若没有，fallback etl_time
                if (ctx._source.create_time == null || (ctx._source.create_time instanceof String && ((String)ctx._source.create_time).length() == 0)) {
                    if (ctx._source.containsKey('etl_time') && ctx._source.etl_time != null) {
                        ctx._source.create_time = ctx._source.etl_time;
                    }
                }

                // 3. source_publish_date：create_time 优先；否则 update_date + T00:00:00
                if (ctx._source.source_publish_date == null || (ctx._source.source_publish_date instanceof String && ((String)ctx._source.source_publish_date).length() == 0)) {
                    String ud = ctx._source.containsKey('update_date') && ctx._source.update_date != null ? (String)ctx._source.update_date : null;
                    if (ctx._source.create_time != null && (ctx._source.create_time instanceof String ? ((String)ctx._source.create_time).length() > 0 : true)) {
                        ctx._source.source_publish_date = ctx._source.create_time;
                    } else if (ud != null && ud.length() > 0) {
                        ctx._source.source_publish_date = ud + 'T00:00:00';
                    }
                }

                // 4. period_id：取原 period 字段（keyword）；缺则取 update_date
                if (ctx._source.period_id == null) {
                    Object p = ctx._source.containsKey('period') ? ctx._source.period : null;
                    String ud = ctx._source.containsKey('update_date') && ctx._source.update_date != null ? (String)ctx._source.update_date : null;
                    if (p != null && p.toString().length() > 0) {
                        ctx._source.period_id = p.toString();
                    } else if (ud != null && ud.length() > 0) {
                        ctx._source.period_id = ud;
                    } else {
                        ctx._source.period_id = 'unknown';
                    }
                }

                // 5. period_start / end / days：根据 update_date + granularity 派生
                if (ctx._source.period_start == null || (ctx._source.period_start instanceof String && ((String)ctx._source.period_start).length() == 0)) {
                    String ud = ctx._source.containsKey('update_date') && ctx._source.update_date != null ? (String)ctx._source.update_date : null;
                    if (ud != null && ud.length() >= 10) {
                        String[] parts = ud.split('-');
                        int y = Integer.parseInt(parts[0]);
                        int mo = Integer.parseInt(parts[1]);
                        if (params.GRANULARITY.equals('monthly')) {
                            int lastDay = 31;
                            if (mo == 2) lastDay = 28;
                            else if (mo == 4 || mo == 6 || mo == 9 || mo == 11) lastDay = 30;
                            String ym = parts[0] + '-' + parts[1];
                            ctx._source.period_start = ym + '-01';
                            ctx._source.period_end = ym + '-' + (lastDay < 10 ? '0' + lastDay : String.valueOf(lastDay));
                            ctx._source.period_days = lastDay;
                        } else if (params.GRANULARITY.equals('quarterly')) {
                            int q = (mo - 1) / 3 + 1;
                            int sm = (q - 1) * 3 + 1;
                            int em = q * 3;
                            String smStr = sm < 10 ? '0' + sm : String.valueOf(sm);
                            String emStr = em < 10 ? '0' + em : String.valueOf(em);
                            ctx._source.period_start = parts[0] + '-' + smStr + '-01';
                            ctx._source.period_end = parts[0] + '-' + emStr + '-30';
                            ctx._source.period_days = 90;
                        } else {
                            ctx._source.period_start = ud.substring(0, 10);
                            ctx._source.period_end = ud.substring(0, 10);
                            ctx._source.period_days = 1;
                        }
                    }
                }
            """
        }
    }
    if not dry_run:
        r = es.reindex(body=body, refresh=True, request_timeout=600)
        result["steps"].append(f"reindex: {r.get('total', 0)} reindexed, {r.get('created', 0)} created, {r.get('updated', 0)} updated, {len(r.get('failures', []))} failed")
        if r.get("failures"):
            result["failures"] = r["failures"][:3]
    else:
        result["steps"].append(f"[dry_run] reindex from {old_name} → {dws}")

    # 5. 验证文档数
    if not dry_run:
        new_count = es.count(index=dws)["count"]
        result["new_count"] = new_count
        result["steps"].append(f"verify: {dws} has {new_count} docs (was {src_count})")
        if new_count < src_count:
            result["ok"] = False
            result["error"] = f"文档数减少: {src_count} → {new_count}"
            return result

        # 6. 抽样：检查 1 条文档的时序字段
        sample = es.search(index=dws, body={"size": 1, "query": {"match_all": {}}})["hits"]["hits"]
        if sample:
            src_doc = sample[0]["_source"]
            result["sample"] = {
                "breed": src_doc.get("breed", ""),
                "create_time": src_doc.get("create_time", ""),
                "source_publish_date": src_doc.get("source_publish_date", ""),
                "period_granularity": src_doc.get("period_granularity", ""),
                "period_id": src_doc.get("period_id", ""),
                "period_start": src_doc.get("period_start", ""),
                "period_end": src_doc.get("period_end", ""),
                "period_days": src_doc.get("period_days", 0),
            }
    else:
        result["new_count"] = src_count

    # 7. 删 v1_bak（保留脚本里仅注释，运行时跑删：见 cleanup_v1_bak.sh）
    result["steps"].append(f"v1_bak 保留在 {v1_name}（待手动确认后清理）")
    result["ok"] = True
    return result


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else None
    dry = "--dry-run" in sys.argv
    cities = [target] if target else list(CITY_GRANULARITY.keys())
    print(f"{'[DRY-RUN] ' if dry else ''}Reindex {len(cities)} 城: {cities}")
    for c in cities:
        print(f"\n{'='*70}\n[{c}]\n{'='*70}")
        r = reindex_city(c, dry_run=dry)
        print(json.dumps(r, ensure_ascii=False, indent=2))
