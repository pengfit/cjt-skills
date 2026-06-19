"""pipeline/etl.py - ODS → DWD ETL（v2-only，两轮：先 DB 后 AI）

新数据流（2026-06-17 重构，两轮 ETL）：
  ┌─────────────────────────────────────────────────────────────────────┐
  │ ODS source                                                          │
  │   │                                                                 │
  │   ├── 第一轮：DB-only 5 段式（category_v3_rules.db）              │
  │   │     - 阶段 1：breed_l3_map 精确匹配                              │
  │   │     - 阶段 2：Jaccard 模糊召回 (>= 0.6)                          │
  │   │     - 阶段 3：L4 pattern 正则                                    │
  │   │     - DB 命中（db_exact_v2 / db_fuzzy_v2 / pattern_v2）         │
  │   │         → 立即 transform_doc + bulk_index 写 DWD                │
  │   │     - DB 未命中 → 攒到 pending_ai_items                         │
  │   │                                                                 │
  │   └── 第二轮：攒批 AI（ai.service.classify_v3_batch）             │
  │         - DB 优先检查（避免重复调 AI）                              │
  │         - 未命中攒批送 AI，每批 V2_AI_BATCH_SIZE=20 条                │
  │         - AI 结果写回 breed_l3_map（DB 自我学习）                   │
  │         - AI 失败 → 标记 no_match_v2，跳过（fail-safe）              │
  │         - 重新构 doc + bulk_index 写 DWD                             │
  └─────────────────────────────────────────────────────────────────────┘

数据依赖：
  - gov_price_etl.classify.category_v3（v3 5 段式 + 批量 AI，按 GB 章节）
  - gov_price_etl.ai.service（classify_v3_batch 走 OpenClaw gateway）
  - gov_price_etl.transform.transform_doc（ODS → DWD 单文档转换）

历史（2026-06-17 已清干净）：
  - v1 大分类 DB（breed_category_rules.db）已删除
  - v1 AI 入口（classify_breed_batch）已删除
  - v1 阶段 1+2 流转为 v2 阶段 1+2（DB 查表逻辑复用）
  - DWD.category 字段保留兼容（值 = v2 L1 中文名，spec 规则库按此过滤）
"""
import time
from typing import List, Tuple

from gov_price_etl.ai.service import classify_v3_batch as ai_classify_v3_batch
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
    """单城市 ODS → DWD 二段式 ETL（先 DB 后 AI）。返回 (成功, 失败)。

    流程（2026-06-17 重构）：
      1. 第一轮：滚动 ODS 拉取
         - 每条调 classify_v3()（DB-only，阶段 4 占位）
         - DB 命中（db_exact_v2 / db_fuzzy_v2 / pattern_v2）→ 立即 transform_doc + bulk_index
         - DB 未命中 → 攒到 pending_ai_items
      2. 第二轮：所有 ODS 走完后，攒批调 ai_classify_v3_batch（写回 breed_l3_map + 返回 v2）
      3. 第三轮：用 AI 返回的 v2 结果对 pending 项构 doc + bulk_index

    优点：
      - DB 命中的项不需要 AI 调用（6成以上性能节省）
      - 未命中的攒批送 AI，减少 AI 调用次数
      - AI 结果自动写回 DB，下次 ETL 走阶段 1 命中（DB 自我学习）
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
    pending_ai_items: List[dict] = []   # 待 AI 的 items
    pending_ai_meta: List[tuple] = []    # (doc_id, raw) 对齐 items

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
                    # DB 未命中 → 攒到 pending_ai（等下一轮批量 AI）
                    pending_ai_items.append({
                        "breed": breed_raw,
                        "spec": raw.get("spec", ""),
                        "unit": raw.get("unit", ""),
                        "breed_clean": breed_clean,
                    })
                    pending_ai_meta.append((h["_id"], raw))

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
            print(f"    pages={pages}, etled={etled}/{total}, pending_ai={len(pending_ai_items)}")

        resp = session.post(f"{es_host}/_search/scroll?scroll=2m",
                            json={"scroll_id": scroll_id})
        if resp.status_code != 200:
            break
        result = resp.json()
        hits = result["hits"]["hits"]
        scroll_id = result.get("_scroll_id", "")

    # ── 第二轮：批量 AI（service.classify_v3_batch 内部 DB 优先 + 未命中调 AI + 写回 DB）──
    ai_hits = 0
    if pending_ai_items and not dry_run:
        print(f"    [AI] 攒批 {len(pending_ai_items)} 条送 AI 分类...")
        t0 = time.time()
        # write_rules=True → AI 结果写回 breed_l3_map，下次 ETL 走阶段 1 命中
        v2_results = ai_classify_v3_batch(
            pending_ai_items, city=city, write_rules=True,
        )
        elapsed = time.time() - t0
        print(f"    [AI] AI 调用耗时 {elapsed:.1f}s，返回 {len(v2_results)} 条结果")

        # ── 第三轮：用 AI 返回的 v2 构 doc + bulk_index ──
        ai_docs = []
        ai_ids = []
        for (doc_id, raw), item in zip(pending_ai_meta, pending_ai_items):
            v2 = v2_results.get(item["breed_clean"])
            if not v2 or not v2.get("l3"):
                # AI 也未判出 → 跳过（fail-safe，不写 DWD）
                failed += 1
                continue
            doc = transform_doc(raw, ods_idx, city, v2_override=v2)
            # transform_doc 内部已完成 spec='/' 规范化和空 spec 回填
            if not doc.get("breed"):
                continue
            ai_docs.append(doc)
            ai_ids.append(doc_id)
            ai_hits += 1

        if ai_docs:
            ok, fail = bulk_index(es_host, dwd_idx, ai_docs, ai_ids)
            etled += ok
            failed += fail

    if scroll_id:
        session.delete(f"{es_host}/_search/scroll", json={"scroll_id": scroll_id})

    print(
        f"  [ETL] {city} 完成: → {dwd_idx} | "
        f"etled={etled} (DB-hit={etled - ai_hits}, AI-hit={ai_hits}), "
        f"failed={failed}, pending_ai={len(pending_ai_items)}"
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