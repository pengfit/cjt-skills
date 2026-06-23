#!/usr/bin/env python3
"""一次性补齐 9 城 DWS 索引的 period_start / period_id

之前 reindex 时 monthly 错误地把 period_start 设成 update_date 本身。
本次用 _update_by_query + painless 原地修正：
  monthly:   period_start = update_date 的月首
  quarterly: period_start = update_date 的季度首
  irregular: 不动（已经是 update_date）
  period_id: 统一成 "YYYY-MM" 或 "YYYY-Qn"（与 period_start 同步）
"""
import sys, os, json
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
sys.path.insert(0, os.path.expanduser("~/.openclaw/workspace/skills/gov-price-dashboard"))

from elasticsearch import Elasticsearch
from api.skill_registry import get_all

es = Elasticsearch(['http://localhost:59200'])


# painless：检查 granularity，monthly 改月首，quarterly 改季首
SCRIPT = """
String granularity = ctx._source.period_granularity;
String ud = ctx._source.update_date instanceof String ? (String)ctx._source.update_date : null;
if (ud != null && ud.length() >= 7) {
    int mo = Integer.parseInt(ud.substring(5, 7));
    if (granularity == null || granularity.equals('monthly')) {
        // monthly: period_start = 月首, period_id = YYYY-MM
        String ym = ud.substring(0, 7);
        ctx._source.period_start = ym + '-01';
        ctx._source.period_id = ym;
    } else if (granularity.equals('quarterly')) {
        // quarterly: period_start = 季首, period_id = YYYY-Qn
        int q = (mo - 1) / 3 + 1;
        int sm = (q - 1) * 3 + 1;
        String smStr = sm < 10 ? '0' + sm : String.valueOf(sm);
        ctx._source.period_start = ud.substring(0, 4) + '-' + smStr + '-01';
        ctx._source.period_id = ud.substring(0, 4) + '-Q' + q;
    }
    // irregular: 不动
}
"""


def fix_city(city_key: str) -> dict:
    cfg = next((s for s in get_all() if s["key"] == city_key), None)
    if not cfg:
        return {"ok": False, "error": f"未知 city: {city_key}"}
    dws = cfg.get("dws_index")
    if not dws:
        return {"ok": False, "error": f"no dws_index for {city_key}"}
    if not es.indices.exists(index=dws):
        return {"ok": False, "error": f"索引不存在: {dws}"}

    result = {"city": city_key, "dws_index": dws, "steps": []}

    # 1. update_by_query
    r = es.update_by_query(
        index=dws,
        body={
            "script": {
                "lang": "painless",
                "source": SCRIPT,
            },
            "query": {"match_all": {}},
        },
        refresh=True,
        conflicts="proceed",
        request_timeout=600,
    )
    result["steps"].append(f"updated: {r.get('updated', 0)}, failures: {len(r.get('failures', []))}, total: {r.get('total', 0)}")
    if r.get("failures"):
        result["failures_sample"] = r["failures"][:3]

    # 2. 抽样验证
    sample = es.search(index=dws, body={"size": 3, "_source": ["breed", "update_date", "period_granularity", "period_id", "period_start", "period_end", "period_days"]})["hits"]["hits"]
    if sample:
        result["sample"] = []
        for h in sample:
            result["sample"].append(h["_source"])

    result["ok"] = True
    return result


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else None
    cities = [target] if target else ["xian", "sichuan", "chongqing", "jinan", "rizhao", "heze", "henan", "qingdao", "weihai"]
    print(f"补齐 period_start: {cities}")
    for c in cities:
        print(f"\n{'='*60}\n[{c}]\n{'='*60}")
        r = fix_city(c)
        print(json.dumps(r, ensure_ascii=False, indent=2))
