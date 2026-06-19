"""pipeline/etl.py - ODS → DWD ETL（纯 DB 二段式，无 AI）

流程：
  ┌──────────────────────────────────────────────────────┐
  │ ODS source                                           │
  │   │                                                  │
  │   └── 2 段式 classify_v3（breed_l3_map_v3 缓存）     │
  │         - 阶段 1：精确匹配 (confidence >= 0.9)       │
  │         - 阶段 2：Jaccard 模糊召回 (confidence >= 0.9)
  │         - 命中 → transform_doc + bulk_index 写 DWD    │
  │         - 未命中 → 跳过（等 breed 补入缓存后重跑）  │
  └──────────────────────────────────────────────────────┘

数据依赖：
  - gov_price_etl.classify.category_v3（2 段式，仅 breed_l3_map_v3 匹配）
  - gov_price_etl.transform.transform_doc（ODS → DWD 单文档转换）

DWD.category 字段保留兼容（值 = v3 L1 中文名，spec 规则库按此过滤）
"""
import time
from typing import List, Tuple


from gov_price_etl.classify.category_v3 import classify_v3
from gov_price_etl.config import CITY_CONFIGS
from gov_price_etl.es_client import bulk_index, get_es_client
from gov_price_etl.indexer import ensure_indices
from gov_price_etl.transform import transform_doc
from gov_price_etl.transform.clean import clean_breed
from gov_price_etl.pipeline.dws_sync import sync_dws_with_ai

# DB 命中阈值：v2 阶段 1/2/3 都算本地命中，不送 AI
_LOCAL_HIT_SOURCES = frozenset(("db_exact_v3", "db_fuzzy_v3"))


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
    """单城市 ODS → DWD 纯 DB ETL。返回 (成功, 失败)。

    流程：
      1. 滚动 ODS 拉取
         - 每条调 classify_v3()（2 段式：db_exact → db_fuzzy，confidence >= 0.9）
         - DB 命中（db_exact_v3 / db_fuzzy_v3）→ 立即 transform_doc + bulk_index
         - DB 未命中 → 跳过（等 breed 补入缓存后重跑）
    """
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
    # spec 是 text 字段，对空字符串不过滤（term 在 text 字段上不匹配空串）
    # 必须用 spec.keyword 子字段，term 才会把空串当作有效 token 匹配
    # 所有城市统一过滤 spec='' 或 spec='/' 的脏数据文档（包括菏泽 229 条）
    # 2026-06-15 扩展：breed='' 也作为脏数据过滤（河南 single_price_cont 续表 948 条 breed 字段丢失）
    # 与 spec='' 规则同源：数据不完整 = 不进 DWD
    # ODS 保留这 948 条作为原料，未来 sync 阶段修了 breed 后可重 ETL 恢复
    must_not = [
        {"terms": {"spec.keyword": ["", "/"]}},
        {"terms": {"breed.keyword": ["", "/"]}},
    ]
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

    # ── 第一轮：滚动 ODS，DB 命中立即写，未命中攒批 ──
    uncategorized_items: List[dict] = []   # DB 未命中的 items
    uncategorized_meta: List[tuple] = []    # (doc_id, raw) 对齐 items

    docs = []
    doc_ids = []

    def _flush_buffer():
        """把当前 docs buffer 写 DWD。"""
        nonlocal etled, failed
        if not docs:
            return
        ok, fail = bulk_index(es_host, dwd_idx, docs, doc_ids)
        etled += ok
        failed += fail
        docs.clear()
        doc_ids.clear()

    while hits:
        pages += 1
        for h in hits:
            try:
                raw = h["_source"]
                breed_raw = raw.get("breed", "")
                breed_clean = clean_breed(breed_raw)
                if not breed_clean:
                    # 空 breed 跳过（跟原逻辑一致）
                    continue

                # 单条 DB-only v2 查表（阶段 4 占位 → 阶段 5 fallback）
                v2 = classify_v3(
                    breed=breed_raw,
                    spec=raw.get("spec", ""),
                    unit=raw.get("unit", ""),
                    breed_clean=breed_clean,
                )
                source = v2.get("category_v2_source", "")

                if source in _LOCAL_HIT_SOURCES:
                    # DB 命中 → 立即构 doc + 攒批
                    doc = transform_doc(raw, ods_idx, city, v2_override=v2)
                    # transform_doc 内部已完成 spec='/' 规范化和空 spec 回填
                    # 但空 breed 的空 spec 仍需跳过（doc.get('breed') 为空表示原料不合法）
                    if not doc.get("breed"):
                        continue

                    if dry_run:
                        print(f"    [dry-run DB-hit] {doc['breed_clean']} → {doc.get('category', '其他')} ({source})")
                        continue
                    docs.append(doc)
                    doc_ids.append(h["_id"])
                else:
                    # DB 未命中 → 跳过（等 breed 补入缓存后重跑 ETL）
                    uncategorized_items.append({
                        "breed": breed_raw,
                        "spec": raw.get("spec", ""),
                        "unit": raw.get("unit", ""),
                        "breed_clean": breed_clean,
                    })
                    uncategorized_meta.append((h["_id"], raw))

                    if dry_run:
                        print(f"    [dry-run DB-miss] {breed_clean} → {v2.get('category_v2_source')} → 攒批 AI")
                        continue
            except Exception as e:
                failed += 1
                if failed <= 3:
                    print(f"    转换失败: {e}")

        # 每页 flush（DB 命中部分）
        if not dry_run:
            _flush_buffer()

        if pages % 20 == 0:
            print(f"    pages={pages}, etled={etled}/{total}, uncategorized={len(uncategorized_items)}")

        resp = session.post(f"{es_host}/_search/scroll?scroll=2m",
                            json={"scroll_id": scroll_id})
        if resp.status_code != 200:
            break
        result = resp.json()
        hits = result["hits"]["hits"]
        scroll_id = result.get("_scroll_id", "")

    # ── 第二轮：未命中 DB 的项跳过（不写 DWD，等 breed 补入缓存后重跑 ETL）──
    for (doc_id, raw), item in zip(uncategorized_meta, uncategorized_items):
        failed += 1

    if scroll_id:
        session.delete(f"{es_host}/_search/scroll", json={"scroll_id": scroll_id})

    print(
        f"  [ETL] {city} 完成: → {dwd_idx} | "
        f"etled={etled}, "
        f"failed={failed}, uncategorized={len(uncategorized_items)}"
    )
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
    """跑全流程：每个城市先 ODS→DWD 二段式 ETL（v1 DB + v2 5 段），再 DWD→DWS 三段式同步。"""
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