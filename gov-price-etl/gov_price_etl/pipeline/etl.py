"""pipeline/etl.py - ODS → DWD 主循环 + AI 分类回写

etl.py 的瘦身版：从 1107 行 → ~150 行。
原文件中的 DWD/DWS mapping、ES 客户端、bulk、indexer、attr 工具都已拆出。
"""
import json
import time
from typing import Tuple

from gov_price_etl.classify import (
    _fetch_ai_category_batch,
    get_category_system_map,
    get_category_system_name_map,
)
from gov_price_etl.config import CITY_CONFIGS
from gov_price_etl.es_client import bulk_index, get_es_client
from gov_price_etl.indexer import ensure_indices
from gov_price_etl.transform import transform_doc
from gov_price_etl.pipeline.dws_sync import sync_dws_with_ai


def etl_city(
    es_host: str,
    city: str,
    cfg: dict,
    batch_size: int = 500,
    incremental: bool = False,
    since_date: str = "",
    dry_run: bool = False,
    category: str = "",
    mark_done: bool = False,
) -> Tuple[int, int]:
    """单城市 ODS → DWD ETL。返回 (成功, 失败)。"""
    ods_idx = cfg["ods"]
    dwd_idx = cfg["dwd"]

    ensure_indices(es_host, cfg)

    session = get_es_client(es_host)
    count_resp = session.get(f"{es_host}/{ods_idx}/_count")
    if count_resp.status_code != 200:
        print(f"  [ETL] {city}: 索引 {ods_idx} 不存在或查询失败，跳过")
        return 0, 0

    total = count_resp.json()["count"]
    if total == 0:
        print(f"  [ETL] {city}: {ods_idx} 为空，跳过")
        return 0, 0

    print(f"  [ETL] {city}: {ods_idx} ({total:,} 条) → {dwd_idx}")

    # 构建查询
    must = [{"match_all": {}}]
    must_not = [{"terms": {"spec": ["/", ""]}}]
    if category and not (incremental and since_date):
        must = [{"term": {"category": category}}]
    if incremental and since_date:
        if category:
            must = [{"term": {"category": category}}]
        else:
            must = [{"range": {"update_date": {"gte": since_date}}}]
    body = {
        "query": {"bool": {"must": must, "must_not": must_not}},
        "size": min(batch_size, total),
        "sort": [{"update_date": "asc"}],
    }

    resp = session.post(f"{es_host}/{ods_idx}/_search?scroll=2m", json=body)
    if resp.status_code != 200:
        print(f"  [ETL] {city}: 查询失败: {resp.text[:200]}")
        return 0, 0

    data = resp.json()
    hits = data["hits"]["hits"]
    scroll_id = data.get("_scroll_id", "")

    etled = failed = pages = 0
    ai_pending: list = []  # [(breed_clean, doc_id), ...]

    while hits:
        pages += 1
        docs = []
        doc_ids = []

        for h in hits:
            try:
                doc = transform_doc(h["_source"], ods_idx, city)
                spec_val = doc.get("spec", "")
                if spec_val == "/":
                    doc["spec"] = ""
                    spec_val = ""
                if not spec_val:
                    # spec 为空时以 breed 填充
                    if not doc.get("breed"):
                        continue
                    doc["spec"] = doc.get("breed_clean") or doc["breed"]
                if dry_run:
                    print(f"    [dry-run] {doc['breed_clean']} → {doc['category']}")
                    continue
                if doc["category"] == "其他":
                    ai_pending.append((doc["breed_clean"], h["_id"]))
                    # AI 待分类品种：先写入 DWD（不带 category，等 AI 更新时用 update doc_as_upsert 合并）
                    ai_doc = {k: v for k, v in doc.items() if k != "category"}
                    docs.append(ai_doc)
                    doc_ids.append(h["_id"])
                    continue
                docs.append(doc)
                doc_ids.append(h["_id"])
            except Exception as e:
                failed += 1
                if failed <= 3:
                    print(f"    转换失败: {e}")

        if docs and not dry_run:
            ok, fail = bulk_index(es_host, dwd_idx, docs, doc_ids)
            etled += ok
            failed += fail

        if pages % 20 == 0:
            print(f"    pages={pages}, etled={etled}/{total}")

        resp = session.post(f"{es_host}/_search/scroll?scroll=2m",
                            json={"scroll_id": scroll_id})
        if resp.status_code != 200:
            break
        result = resp.json()
        hits = result["hits"]["hits"]
        scroll_id = result.get("_scroll_id", "")

    if scroll_id:
        session.delete(f"{es_host}/_search/scroll", json={"scroll_id": scroll_id})

    # ── 批量 AI 分类 ──
    ai_updated = 0
    if ai_pending and not dry_run:
        breeds = list(dict.fromkeys(b for b, _ in ai_pending))  # 去重保留顺序
        breed_cats: dict = {}
        _AI_BATCH_SIZE = 20
        for i in range(0, len(breeds), _AI_BATCH_SIZE):
            chunk = breeds[i:i + _AI_BATCH_SIZE]
            cats = _fetch_ai_category_batch(chunk, city)
            breed_cats.update(cats)
            if i + _AI_BATCH_SIZE < len(breeds):
                time.sleep(0.5)  # 限速
        if breed_cats:
            code_map = get_category_system_map()
            name_map = get_category_system_name_map()
            update_body = ""
            for breed_clean, doc_id in ai_pending:
                cat = breed_cats.get(breed_clean, "其他")
                code = code_map.get(cat, "")
                update_body += json.dumps({"update": {"_id": doc_id}}, ensure_ascii=False) + "\n"
                update_body += json.dumps({
                    "doc": {
                        "category": cat,
                        "category_system": code,
                        "category_system_name": name_map.get(code, ""),
                    },
                    "doc_as_upsert": True,
                }, ensure_ascii=False) + "\n"
            if update_body:
                _session = get_es_client(es_host)
                r = _session.post(
                    f"{es_host}/{dwd_idx}/_bulk",
                    data=update_body.encode("utf-8"),
                    headers={"Content-Type": "application/x-ndjson"},
                )
                result = r.json()
                errors = sum(1 for it in result.get("items", []) if "error" in it.get("update", {}))
                ai_updated = len(ai_pending) - errors
                print(f"  [AI] 批量更新: 更新 {ai_updated}/{len(ai_pending)} 条，错误 {errors}")
                if errors > 0:
                    for it in result.get("items", [])[:3]:
                        if "error" in it.get("update", {}):
                            print(f"    错误: {it['update']['error']}")
        print(f"  [AI] 批量分类 {len(ai_pending)} 条 → 更新 {ai_updated} 条")

    print(f"  [ETL] {city} 完成: → {dwd_idx} | etled={etled}, failed={failed}")
    return etled, failed


def run_etl(
    es_host: str,
    cities: list,
    batch_size: int = 500,
    incremental: bool = False,
    since_date: str = "",
    dry_run: bool = False,
    category: str = "",
    mark_done: bool = False,
    with_dws: bool = True,
) -> Tuple[int, int]:
    """跑全流程：每个城市先 ETL，再 DWS+AI 同步。"""
    total_etled = 0
    total_failed = 0

    for city in cities:
        if city not in CITY_CONFIGS:
            print(f"[ETL] 未知城市: {city}，跳过")
            continue

        cfg = CITY_CONFIGS[city]
        print(f"\n[ETL] 处理城市: {city} ({cfg['city_label']})")

        ok, fail = etl_city(
            es_host, city, cfg,
            batch_size=batch_size,
            incremental=incremental,
            since_date=since_date,
            dry_run=dry_run,
            category=category,
            mark_done=mark_done,
        )
        total_etled += ok
        total_failed += fail

        if with_dws and not dry_run:
            dws_ok, dws_fail = sync_dws_with_ai(es_host, city, cfg, batch_size=batch_size)
            print(f"  [DWS+AI] {city} 同步结果: ok={dws_ok}, fail={dws_fail}")

    print(f"\n[ETL] 全部完成: etled={total_etled}, failed={total_failed}")
    return total_etled, total_failed
