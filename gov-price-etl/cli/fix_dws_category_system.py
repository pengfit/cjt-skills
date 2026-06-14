#!/usr/bin/env python3
"""cli/fix_dws_category_system - 补全 DWS 中缺失的 category_system / category_system_name

背景：
  部分 DWS 文档的 category_system / category_system_name 为空（漏同步、字段映射缺失等）。
  这些值都可以从对应 DWD 文档里获取（DWS._id == DWD._id）。

策略（按优先级）：
  1. 从 DWD._id 取 → 直接用 DWD.category_system / category_system_name
  2. 若 DWD 也没，但 DWD.category 非空 → 查 data/category_in_system.json 计算
  3. 若 DWD 完全没有（如 henan 有 20 条 breed 还在但 category 字段缺失）→ 留空
     （脚本会打印提示，需另行分类）

用法：
  ./cli/fix_dws_category_system.py                  # 全量（所有城市）
  ./cli/fix_dws_category_system.py --city sichuan   # 指定城市
  ./cli/fix_dws_category_system.py --dry-run        # 预览，不写 ES
  ./cli/fix_dws_category_system.py --batch-size 500 # 自定义批量
"""
import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import requests  # noqa: E402

from gov_price_etl.classify import (  # noqa: E402
    get_category_system_map,
    get_category_system_name_map,
)
from gov_price_etl.config import CITY_CONFIGS, get_es_host  # noqa: E402
from gov_price_etl.es_client import get_es_client  # noqa: E402


def query_dws_broken_ids(session, es_host: str, dws_idx: str, batch_size: int):
    """滚动拉 DWS 中 category_system 缺失/为空的 doc_id。"""
    body = {
        "query": {
            "bool": {
                "should": [
                    {"bool": {"must_not": [{"exists": {"field": "category_system"}}]}},
                    {"term": {"category_system": ""}},
                ],
                "minimum_should_match": 1,
            }
        },
        "_source": ["category_system", "category_system_name", "category", "etl_time"],
        "size": batch_size,
        "sort": [{"etl_time": "asc"}, {"_id": "asc"}],
    }
    while True:
        resp = session.post(f"{es_host}/{dws_idx}/_search", json=body, timeout=60)
        if resp.status_code != 200:
            print(f"  [ERR] 查询 {dws_idx} 失败: {resp.text[:300]}")
            return
        hits = resp.json()["hits"]["hits"]
        if not hits:
            return
        for h in hits:
            yield h["_id"], h["_source"]
        last = hits[-1]
        # search_after 必须用 sort 的实际值（etl_time 存的是 epoch_millis）
        sort_vals = last.get("sort", [])
        if sort_vals:
            body["search_after"] = sort_vals
        else:
            return


def mget_dwd(session, es_host: str, dwd_idx: str, doc_ids: list) -> dict:
    """按 _id 批量取 DWD 文档。"""
    if not doc_ids:
        return {}
    resp = session.post(
        f"{es_host}/{dwd_idx}/_mget",
        json={"ids": doc_ids},
        timeout=60,
    )
    if resp.status_code != 200:
        return {}
    out = {}
    for d in resp.json().get("docs", []):
        if d.get("found"):
            out[d["_id"]] = d["_source"]
    return out


def bulk_update_dws(es_host: str, dws_idx: str, updates: list) -> tuple:
    """bulk _update DWS 文档的 category_system / category_system_name。

    Args:
        updates: [(doc_id, new_cs, new_csn), ...]
    Returns:
        (ok, err, skipped)
    """
    if not updates:
        return 0, 0, 0
    body = ""
    for doc_id, cs, csn in updates:
        body += json.dumps({"update": {"_index": dws_idx, "_id": doc_id}}, ensure_ascii=False) + "\n"
        body += json.dumps(
            {"doc": {"category_system": cs, "category_system_name": csn}},
            ensure_ascii=False,
        ) + "\n"
    resp = requests.post(
        f"{es_host}/_bulk",
        data=body.encode("utf-8"),
        headers={"Content-Type": "application/x-ndjson"},
        timeout=120,
    )
    if resp.status_code not in (200, 201):
        print(f"  [ERR] bulk 更新失败: {resp.text[:300]}")
        return 0, len(updates), 0
    items = resp.json().get("items", [])
    ok = err = skipped = 0
    for it in items:
        result = it.get("update", {})
        if result.get("error"):
            err += 1
        else:
            res = result.get("result", "")
            if res == "noop":
                skipped += 1
            else:
                ok += 1
    return ok, err, skipped


def fix_city(es_host: str, city: str, cfg: dict, batch_size: int, dry_run: bool):
    """对单个城市执行修复。"""
    dwd_idx = cfg["dwd"]
    dws_idx = cfg["dws"]
    session = get_es_client(es_host)

    code_map = get_category_system_map()      # name → code
    name_map = get_category_system_name_map() # code → name

    print(f"\n=== {city} | DWS={dws_idx} <- DWD={dwd_idx} ===")

    # 1. 拉所有 DWS 异常文档
    dws_broken: dict = {}  # id -> DWS _source
    for doc_id, src in query_dws_broken_ids(session, es_host, dws_idx, batch_size):
        dws_broken[doc_id] = src
    total_broken = len(dws_broken)
    if total_broken == 0:
        print(f"  ✅ 无需修复")
        return {"broken": 0, "fixed_from_dwd": 0, "fixed_from_category": 0, "still_empty": 0, "no_dwd_doc": 0}
    print(f"  发现 {total_broken} 条 DWS 文档 category_system 缺失/为空")

    # 2. 批量从 DWD 取
    fix_from_dwd: list = []   # [(id, cs, csn), ...] 直接从 DWD 拿到的
    fix_from_cat: list = []   # [(id, cs, csn), ...] 从 DWD.category 算的
    no_dwd_doc: list = []     # DWD 里也没有
    need_dwd = list(dws_broken.keys())
    dwd_docs = mget_dwd(session, es_host, dwd_idx, need_dwd)

    # 2. 批量从 DWD 取
    fix_from_dwd: list = []   # [(id, cs, csn), ...] 直接从 DWD 拿到的
    fix_from_cat: list = []   # [(id, cs, csn), ...] 从 DWD.category 算的
    no_dwd_doc: list = []     # DWD 里也没有
    need_dwd = list(dws_broken.keys())
    dwd_docs = mget_dwd(session, es_host, dwd_idx, need_dwd)

    other_cats: dict = {}  # 统计无法修复的 category 分布
    none_cats = 0
    for doc_id in need_dwd:
        dwd_src = dwd_docs.get(doc_id)
        dws_src = dws_broken[doc_id]

        if dwd_src:
            dwd_cs = dwd_src.get("category_system", "") or ""
            dwd_csn = dwd_src.get("category_system_name", "") or ""

            if dwd_cs and dwd_csn:
                # ✅ 路径 1：DWD 直接有
                fix_from_dwd.append((doc_id, dwd_cs, dwd_csn))
            else:
                # DWD 也没，尝试用 DWD.category 算
                dwd_cat = dwd_src.get("category", "") or ""
                if dwd_cat and dwd_cat in code_map:
                    cs = code_map[dwd_cat]
                    csn = name_map.get(cs, dwd_cat)
                    fix_from_cat.append((doc_id, cs, csn))
                elif dwd_cat:
                    # category 有值但不在体系（如 '其他'）
                    other_cats[dwd_cat] = other_cats.get(dwd_cat, 0) + 1
                else:
                    # category 为空/None
                    none_cats += 1
        else:
            # DWD 里也没这条（极少见，可能跨版本被删）
            no_dwd_doc.append(doc_id)

    # 3. 合并：能修复的
    all_fixes = fix_from_dwd + fix_from_cat
    print(f"    从 DWD 直接取: {len(fix_from_dwd)} 条")
    print(f"    从 DWD.category 算: {len(fix_from_cat)} 条")
    print(f"    DWD 中不存在: {len(no_dwd_doc)} 条")
    still_empty = total_broken - len(all_fixes) - len(no_dwd_doc)
    if other_cats:
        print(f"    ⚠️  DWD.category 不在体系中（按设计留空）:")
        for cat, cnt in sorted(other_cats.items(), key=lambda x: -x[1]):
            print(f"        '{cat}': {cnt} 条")
    if none_cats > 0:
        print(f"    ⚠️  DWD.category 为空/缺失: {none_cats} 条（需重新分类）")

    # 4. 写回 DWS
    if dry_run:
        print(f"  [DRY-RUN] 将更新 {len(all_fixes)} 条")
        if no_dwd_doc[:3]:
            print(f"  [DRY-RUN] DWD 不存在的样例: {no_dwd_doc[:3]}")
    else:
        ok, err, skipped = bulk_update_dws(es_host, dws_idx, all_fixes)
        print(f"  ✅ 写入 DWS: ok={ok}, noop={skipped}, err={err}")

    return {
        "broken": total_broken,
        "fixed_from_dwd": len(fix_from_dwd),
        "fixed_from_category": len(fix_from_cat),
        "still_empty": still_empty,
        "no_dwd_doc": len(no_dwd_doc),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="补全 DWS 中缺失的 category_system / category_system_name")
    parser.add_argument("--city", default="", help=f"指定城市（空=全部）可用: {', '.join(CITY_CONFIGS.keys())}")
    parser.add_argument("--dry-run", action="store_true", help="预览模式（不写入 ES）")
    parser.add_argument("--batch-size", type=int, default=500, help="DWD mget 批次大小")
    args = parser.parse_args()

    es_host = get_es_host()
    cities = [args.city] if args.city else list(CITY_CONFIGS.keys())

    print(f"ES: {es_host}")
    print(f"城市: {', '.join(cities)}")
    print(f"模式: {'DRY-RUN' if args.dry_run else 'WRITE'}")
    print()

    total_stats = {
        "broken": 0, "fixed_from_dwd": 0, "fixed_from_category": 0,
        "still_empty": 0, "no_dwd_doc": 0,
    }
    for city in cities:
        cfg = CITY_CONFIGS[city]
        stats = fix_city(es_host, city, cfg, args.batch_size, args.dry_run)
        for k in total_stats:
            total_stats[k] += stats[k]

    print("\n" + "=" * 60)
    print("汇总")
    print("=" * 60)
    print(f"  DWS 异常文档总数:         {total_stats['broken']}")
    print(f"  ✅ 从 DWD 直接取:          {total_stats['fixed_from_dwd']}")
    print(f"  ✅ 从 DWD.category 计算:   {total_stats['fixed_from_category']}")
    print(f"  ⚠️  DWD.category 也空:     {total_stats['still_empty']}  （'其他'/None，保持原样）")
    print(f"  ❌ DWD 中无对应文档:       {total_stats['no_dwd_doc']}")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
