"""pipeline/etl.py - ODS → DWD 三段式 ETL（明确节点）

新数据流（v0.3 重构）：
  ┌─────────────────────────────────────────────────────────────────────┐
  │ ODS source                                                          │
  │   │                                                                 │
  │   ├── 阶段 1：本地库 breed_category_rules.db 精确匹配                │
  │   │     - transform_doc 内置（不调 AI）                              │
  │   │     - category_source = 'db_exact'                              │
  │   │                                                                 │
  │   ├── 阶段 2：本地库 DB + Jaccard 模糊召回                            │
  │   │     - transform_doc 内置（不调 AI）                              │
  │   │     - category_source = 'db_fuzzy'                              │
  │   │                                                                 │
  │   └── 阶段 3：未命中 → AI classify_breed_batch 串行批次              │
  │         - etl_city 攒批（默认 20/批）                                │
  │         - category_source = 'ai' | 'ai_fallback'                    │
  │         - 回写 DWD category（category_source 标识来源）              │
  └─────────────────────────────────────────────────────────────────────┘

每条 DWD 文档带 `category_source` 字段，标识分类来源：
  'db_exact'    阶段 1 命中
  'db_fuzzy'    阶段 2 命中
  'ai'          阶段 3 AI 分类成功
  'ai_fallback' 阶段 3 AI 失败兜底

etl.py 主体瘦身：从混合 ~150 行拆为显式三段编排。
"""
import json
import time
from typing import Tuple

from gov_price_etl.classify import classify_breed_with_stages
from gov_price_etl.config import CITY_CONFIGS
from gov_price_etl.es_client import bulk_index, get_es_client
from gov_price_etl.indexer import ensure_indices
from gov_price_etl.transform import transform_doc
from gov_price_etl.pipeline.dws_sync import sync_dws_with_ai


# ── AI 分类串行批次大小（道友要求"串行"，默认 20/批，逐批调用 AI） ────────
AI_CATEGORY_BATCH_SIZE = 20
AI_CATEGORY_BATCH_SLEEP_S = 0.5  # 批间限速，避免压垮 gateway


def _ai_classify_pending(
    es_host: str,
    dwd_idx: str,
    ai_pending: list,
    city: str,
) -> int:
    """阶段 3：AI classify_breed_batch 串行批次分类 + 回写 DWD。

    Args:
        es_host:    ES 地址
        dwd_idx:    DWD 索引名
        ai_pending: [(breed_clean, doc_id), ...] —— 阶段 1+2 都未命中的品种
        city:       城市 key（缓存分区用）

    Returns:
        成功更新数
    """
    if not ai_pending:
        return 0

    # 去重保留顺序
    breeds = list(dict.fromkeys(b for b, _ in ai_pending))
    print(f"  [STG3 AI] {city}: 待 AI 分类品种 {len(breeds)} 种 ({len(ai_pending)} 条)")

    # 串行批次调 AI（每批 AI_CATEGORY_BATCH_SIZE 条，批间 sleep 限速）
    from gov_price_etl.classify.rules._core import classify_breed_ai

    breed_cats: dict = {}
    breed_sources: dict = {}
    t_stage3 = time.time()
    total_breeds = len(breeds)
    for i in range(0, len(breeds), AI_CATEGORY_BATCH_SIZE):
        chunk = breeds[i:i + AI_CATEGORY_BATCH_SIZE]
        for b in chunk:
            t0 = time.time()
            cat, src = classify_breed_ai(b, city)
            breed_cats[b] = cat
            breed_sources[b] = src
            print(f"    [STG3 AI] {i + chunk.index(b) + 1}/{total_breeds}: {b} → {cat} ({src}, {time.time()-t0:.1f}s)")
        if i + AI_CATEGORY_BATCH_SIZE < len(breeds):
            time.sleep(AI_CATEGORY_BATCH_SLEEP_S)
    print(f"  [STG3 AI] 阶段 3 AI 分类总耗时 {time.time()-t_stage3:.1f}s")

    # 回写 DWD（bulk update）
    update_body = ""
    for breed_clean, doc_id in ai_pending:
        cat = breed_cats.get(breed_clean, "其他")
        src = breed_sources.get(breed_clean, "ai_fallback")
        update_body += json.dumps({"update": {"_id": doc_id}}, ensure_ascii=False) + "\n"
        update_body += json.dumps({
            "doc": {
                "category": cat,
                "category_source": src,
            },
            "doc_as_upsert": True,
        }, ensure_ascii=False) + "\n"

    session = get_es_client(es_host)
    r = session.post(
        f"{es_host}/{dwd_idx}/_bulk",
        data=update_body.encode("utf-8"),
        headers={"Content-Type": "application/x-ndjson"},
    )
    result = r.json()
    errors = sum(1 for it in result.get("items", []) if "error" in it.get("update", {}))
    updated = len(ai_pending) - errors
    print(f"  [STG3 AI] 批量回写: 更新 {updated}/{len(ai_pending)} 条，错误 {errors}")
    if errors > 0:
        for it in result.get("items", [])[:3]:
            if "error" in it.get("update", {}):
                print(f"    错误: {it['update']['error']}")
    return updated


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
    """单城市 ODS → DWD 三段式 ETL。返回 (成功, 失败)。

    流程：
      1. ODS 滚动拉取（按 update_date 排序）
      2. 每条调 transform_doc() → 阶段 1+2 本地匹配（不调 AI）
      3. 阶段 3：未命中品种攒批，调 AI classify_breed_batch 串行分类 → 回写 DWD
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
    ai_pending: list = []  # [(breed_clean, doc_id), ...] 阶段 1+2 都未命中

    # ── 阶段 1+2: 本地规则库匹配（不调 AI） ─────────────────────────────
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

                # ── 阶段 1+2: 本地规则库匹配（覆盖 transform_doc 内的默认分类）──
                cat, src, stage = classify_breed_with_stages(
                    doc["breed_clean"], city=city, use_ai=False
                )
                if not cat:
                    cat = "其他"
                    src = ""
                    stage = ""
                doc["category"] = cat
                doc["category_source"] = src
                doc["category_stage"] = stage

                if dry_run:
                    print(f"    [dry-run] {doc['breed_clean']} → {doc['category']} ({src}/stage={stage})")
                    continue

                if stage == "" or src == "ai_fallback":
                    # 阶段 1+2 都未命中 → 走阶段 3 AI
                    ai_pending.append((doc["breed_clean"], h["_id"]))
                    # 先写入 DWD（不带 category，等 AI 更新时合并）
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

    # ── 阶段 3: AI classify_breed_batch 串行批次 ─────────────────────────
    ai_updated = 0
    if ai_pending and not dry_run:
        ai_updated = _ai_classify_pending(es_host, dwd_idx, ai_pending, city)

    print(
        f"  [ETL] {city} 完成: → {dwd_idx} | "
        f"etled={etled}, failed={failed}, ai_updated={ai_updated}"
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
    """跑全流程：每个城市先 ODS→DWD 三段式 ETL，再 DWD→DWS 三段式同步。"""
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