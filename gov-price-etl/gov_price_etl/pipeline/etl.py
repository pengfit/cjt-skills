"""pipeline/etl.py - ODS → DWD ETL（DB 二段式 + AI 在线缓存补全）

流程：
  1. 第一轮：DB 2 段式（breed_l3_map_v3 缓存，conf >= 0.9）
     - 命中 → transform_doc + bulk_index 写 DWD
     - 未命中 → 按 breed 去重攒批（存 breed_clean 列表）
  2. 第二轮：未命中 breed → Dify 分类（classify_v3_batch）
     - 结果写回 breed_l3_map_v3（conf ≥ 0.9）
  3. 第三轮：重新匹配 ODS 中未命中 breed 的文档 → 写 DWD

数据依赖：
  - gov_price_etl.classify.category_v3（2 段式，仅 breed_l3_map_v3 匹配）
  - gov_price_etl.ai.service.classify_v3_batch（Dify AI, 动态补缓存）
  - gov_price_etl.transform.transform_doc
"""
import time
from collections import Counter
from typing import Dict, List, Tuple

from gov_price_etl.ai.service import classify_v3_batch
from gov_price_etl.classify.category_v3 import classify_v3
from gov_price_etl.config import CITY_CONFIGS
from gov_price_etl.es_client import bulk_index, get_es_client
from gov_price_etl.indexer import ensure_indices
from gov_price_etl.transform import transform_doc
from gov_price_etl.transform.clean import clean_breed
from gov_price_etl.pipeline.dws_sync import sync_dws_with_ai

_LOCAL_HIT_SOURCES = frozenset(("db_exact_v3", "db_fuzzy_v3"))


def _count_ods(es_host: str, ods_idx: str) -> int:
    """ES 索引文档数。"""
    session = get_es_client(es_host)
    r = session.get(f"{es_host}/{ods_idx}/_count")
    return r.json()["count"] if r.status_code == 200 else 0


def _scroll_ods(
    es_host: str, ods_idx: str,
    total: int, batch_size: int,
    category: str, incremental: bool, since_date: str,
    sort_field: str = "update_date",
):
    """滚动 ODS 返回生成器 (doc_id, raw_source)。

    sort_field: 用于 scroll 排序 + 增量 range 的字段名（默认 update_date）。
    新疆 ODS 的 update_date 是 keyword，改用 _period（date 类型）做正确时间排序。
    """
    session = get_es_client(es_host)
    # v0.12+ (2026-07-18): 源头杜绝 — breed 为空跳过。
    # v0.15+ (2026-07-23): spec 为空不再过滤。
    #   背景：原 must_not spec.keyword="" 会让 PDF 合并列 / 人工成本等
    #   没有独立 spec 字段的源数据被整条丢弃；采集端为救活数据伪造 spec=name
    #   把 breed 回填到 spec，导致 ES 里出现 spec==breed 的脏数据。
    #   修法：query 层放空 spec，transform_doc 层对空 spec 标 attr_source='no_spec'，
    #   数据保留但不参与 attr 解析。
    _base_must = [
        {"exists": {"field": "breed"}},   # breed 字段必须存在（无 breed 必丢）
        {"exists": {"field": "spec"}},    # spec 字段可以为空（v0.15+）
    ]
    must_not = [
        {"terms": {"breed.keyword": ["", "/"]}},  # breed 不能是 '' 或 '/'
    ]
    if category and not (incremental and since_date):
        must = _base_must + [{"term": {"category": category}}]
    elif incremental and since_date:
        must = _base_must + [{"range": {sort_field: {"gte": since_date}}}]
    else:
        must = _base_must

    body = {
        "query": {"bool": {"must": must, "must_not": must_not}},
        "size": min(batch_size, total),
        "sort": [{sort_field: "asc"}],
    }
    resp = session.post(f"{es_host}/{ods_idx}/_search?scroll=2m", json=body)
    if resp.status_code != 200:
        return

    data = resp.json()
    scroll_id = data.get("_scroll_id", "")
    hits = data["hits"]["hits"]

    while hits:
        for h in hits:
            yield h["_id"], h["_source"]
        resp = session.post(f"{es_host}/_search/scroll?scroll=2m",
                            json={"scroll_id": scroll_id})
        if resp.status_code != 200:
            break
        data = resp.json()
        hits = data["hits"]["hits"]
        scroll_id = data.get("_scroll_id", "")

    if scroll_id:
        session.delete(f"{es_host}/_search/scroll", json={"scroll_id": scroll_id})


def _fetch_ods_by_breeds(
    es_host: str, ods_idx: str, breed_cleans: List[str],
    sort_field: str = "update_date",
) -> List[Tuple[str, dict]]:
    """按 breed_clean（ES 上即 breed.keyword）批量拉 ODS 文档。

    sort_field: 同 _scroll_ods，用于排序字段。
    """
    if not breed_cleans:
        return []
    session = get_es_client(es_host)
    results = []
    # 分小批查（ES terms 查询有 max_terms_count 限制）
    for i in range(0, len(breed_cleans), 100):
        chunk = breed_cleans[i:i + 100]
        body = {
            "query": {"bool": {"must": [
                {"terms": {"breed.keyword": chunk}},
            ], "must_not": [
                {"terms": {"breed.keyword": ["", "/"]}},
                # 2026-06-29：去除 spec="" 过滤，跟主滚动逻辑对齐
            ]}},
            "size": 1000,
            "sort": [{sort_field: "asc"}],
        }
        resp = session.post(f"{es_host}/{ods_idx}/_search?scroll=2m", json=body)
        if resp.status_code != 200:
            print(f"      [重捞] 查询失败: {resp.text[:100]}")
            continue
        data = resp.json()
        scroll_id = data.get("_scroll_id", "")
        hits = data["hits"]["hits"]
        while hits:
            for h in hits:
                results.append((h["_id"], h["_source"]))
            resp = session.post(f"{es_host}/_search/scroll?scroll=2m",
                                json={"scroll_id": scroll_id})
            if resp.status_code != 200:
                break
            data = resp.json()
            hits = data["hits"]["hits"]
            scroll_id = data.get("_scroll_id", "")
        if scroll_id:
            session.delete(f"{es_host}/_search/scroll", json={"scroll_id": scroll_id})
    return results


def _write_dwd_batch(
    es_host: str, dwd_idx: str, docs: List[dict], doc_ids: List[str], stats: dict,
):
    """写 DWD 并更新 etled/failed。"""
    ok, fail = bulk_index(es_host, dwd_idx, docs, doc_ids)
    stats["etled"] += ok
    stats["failed"] += fail
    docs.clear()
    doc_ids.clear()


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
    sort_field = cfg.get("sort_field", "update_date")  # 默认 update_date；新疆 _period 是 date 类型，原 mapping 是 keyword
    ensure_indices(es_host, cfg)
    total = _count_ods(es_host, ods_idx)
    if total == 0:
        print(f"  [ETL] {city}: {ods_idx} 为空，跳过")
        return 0, 0

    print(f"  [ETL] {city}: {ods_idx} ({total:,} 条) → {dwd_idx}")
    stats = {"etled": 0, "failed": 0}

    # ── 第一轮：DB 2 段式，命中写 DWD，未命中记录 breed ──
    uncategorized_breeds = {}  # breed_clean -> {"breed": raw_breed, "spec": ..., "unit": ...}
    docs = []
    doc_ids = []

    pages = 0
    for doc_id, raw in _scroll_ods(es_host, ods_idx, total, batch_size,
                                    category, incremental, since_date, sort_field):
        pages += 1
        try:
            breed_raw = raw.get("breed", "")
            spec_raw = raw.get("spec", "")
            # v0.12+ (2026-07-18): 源头杜绝 — breed/spec 任一为空都跳过（query 层已过滤，此处兑底）
            if not breed_raw.strip() or not spec_raw.strip():
                stats["failed"] += 1
                stats["skipped_empty_breed_or_spec"] = stats.get("skipped_empty_breed_or_spec", 0) + 1
                continue
            # 2026-06-29 新疆 ETL 优化 A：双 key 查询
            #   1. raw_breed 直接（ODS 文档的 breed 字段，含规格的完整名）
            #   2. ODS 索引的 breed_clean（xinjiang-price 的 split_breed_spec 算，去掉规格的核心名）
            # 任一命中即视为 DB 命中
            breed_clean_v1 = breed_raw  # 直接用 raw_breed
            breed_clean_v2 = raw.get("breed_clean", "")  # ODS 索引的 breed_clean
            # 用于写 DWD 的 breed_clean 字段（兼容历史 DWD）：用 clean_breed 算
            breed_clean = clean_breed(breed_raw)
            if not breed_clean:
                continue

            # 先用 v1（raw_breed）查 DB
            v2 = classify_v3(breed_raw, raw.get("spec", ""), raw.get("unit", ""), breed_clean_v1)
            source = v2.get("category_v2_source", "")
            # v1 未命中 → 试 v2（ODS 索引的 breed_clean）
            if source not in _LOCAL_HIT_SOURCES:
                v2 = classify_v3(breed_raw, raw.get("spec", ""), raw.get("unit", ""), breed_clean_v2)
                source = v2.get("category_v2_source", "")
            # v0.19+ (2026-07-24) 贵州 ETL 复盘: 加 v3 = clean_breed(raw_breed)
            #   v1=raw/v2=ODS breed_clean 都不含括号/规格后缀剥离,但 DB 存的是核心名,
            #   导致 "镀锌钢管 (Q215-235)" 这种 ODS 数据 miss DB "镀锌钢管" 入口。
            #   clean_breed() 循环剥后缀括号,让 ODS 标准化形式与 DB 对齐。
            #   73 个 breed / 1704 条 doc 在贵州重新命中。
            if source not in _LOCAL_HIT_SOURCES and breed_clean and breed_clean != breed_clean_v2:
                v2 = classify_v3(breed_raw, raw.get("spec", ""), raw.get("unit", ""), breed_clean)
                source = v2.get("category_v2_source", "")
            source = v2.get("category_v2_source", "")

            if source in _LOCAL_HIT_SOURCES:
                doc = transform_doc(raw, ods_idx, city, v2_override=v2)
                if not doc.get("breed"):
                    continue
                if not dry_run:
                    docs.append(doc)
                    doc_ids.append(doc_id)
                    if len(docs) >= batch_size:
                        _write_dwd_batch(es_host, dwd_idx, docs, doc_ids, stats)
            else:
                stats["failed"] += 1
                # 记录 breed 去重（用于后续 AI 补缓存）
                if breed_clean not in uncategorized_breeds:
                    uncategorized_breeds[breed_clean] = {
                        "breed": breed_raw, "spec": "", "unit": "", "breed_clean": breed_clean,
                    }

            if pages % 500 == 0:
                hit_count = stats["etled"]
                print(f"    {pages}/{total}, hit={hit_count}, uncat_breeds={len(uncategorized_breeds)}")

        except Exception as e:
            stats["failed"] += 1
            if stats["failed"] <= 3:
                print(f"    转换失败: {e}")

    # flush 最后一批
    if not dry_run and docs:
        _write_dwd_batch(es_host, dwd_idx, docs, doc_ids, stats)

    round1_etled = stats["etled"]
    round1_failed = stats["failed"]

    # ── 第二轮：未命中 breed → AI 补缓存 ──
    if uncategorized_breeds and not dry_run:
        # 2026-06-30：不再 DELETE 旧缓存。
        # 原逻辑要 DELETE 是为了防止 INSERT OR IGNORE 跳过新数据，
        # 但 DB 预查会在 service.py 里跳过已存在的项——所以手工/手动写的记录不要删。
        # 错删会导致：ODS 全角 vs DB 半角等样式差异场景，DB 里正确的记录被删后，
        # AI 重新分类又返回 fallback → 第三轮永远 miss。
        import sqlite3 as _sqlite
        from gov_price_etl.paths import CATEGORY_V3_RULES_DB as _db_path

        unique_breeds = list(uncategorized_breeds.values())
        print(f"    [AI 补缓存] {len(unique_breeds)} 个 breed 送 Dify...")
        t0 = time.time()
        ai_results = classify_v3_batch(unique_breeds, city=city, write_rules=True)
        elapsed = time.time() - t0
        ai_ok = sum(1 for v in ai_results.values()
                     if v.get("category_v2_source") == "ai_v3")
        print(f"    [AI 补缓存] {ai_ok}/{len(unique_breeds)} 成功, {elapsed:.1f}s")

        # 提置信度：AI 成功分类（有有效 L3）的 entry，强制 conf=0.95 确保 stage 1 命中
        try:
            _conn2 = _sqlite.connect(str(_db_path))
            for bc, v in ai_results.items():
                if v.get("category_v2_source") == "ai_v3" and v.get("l3"):
                    _conn2.execute(
                        "UPDATE breed_l3_map_v3 SET confidence=0.95, updated_at=datetime('now','localtime') WHERE breed_clean=?",
                        (bc,),
                    )
            _conn2.commit()
            _conn2.close()
        except Exception as _e2:
            print(f"    [AI 补缓存] 提置信度失败: {_e2}")

        # ── 第三轮：从 ODS 拉回这组 breed 的文档，重新匹配写 DWD ──
        # 注意：uncategorized_breeds 的 key 是 breed_clean（规范化后），但 _fetch_ods_by_breeds 查的是 breed.keyword（原始）
        # 必须从 value 里拿 raw breed 才能捞到文档（2026-06-24 bug fix）
        raw_breeds = [v["breed"] for v in uncategorized_breeds.values() if v.get("breed")]
        print(f"    [AI 重捞] 捞 {len(raw_breeds)} 个 raw breed...")
        fetched = _fetch_ods_by_breeds(es_host, ods_idx, raw_breeds, sort_field)

        docs.clear()
        doc_ids.clear()
        round2_hits = 0
        for doc_id, raw in fetched:
            breed_raw = raw.get("breed", "")
            spec_raw = raw.get("spec", "")
            # v0.12+ (2026-07-18): 第二轮重携同样需要兑底（防 query 层覆盖丢失）
            if not breed_raw.strip() or not spec_raw.strip():
                continue
            breed_clean = clean_breed(breed_raw)
            if not breed_clean:
                continue
            v2 = classify_v3(breed_raw, raw.get("spec", ""), raw.get("unit", ""), breed_clean)
            source = v2.get("category_v2_source", "")
            if source in _LOCAL_HIT_SOURCES:
                doc = transform_doc(raw, ods_idx, city, v2_override=v2)
                if doc.get("breed"):
                    docs.append(doc)
                    doc_ids.append(doc_id)
                    round2_hits += 1
                    if len(docs) >= batch_size:
                        _write_dwd_batch(es_host, dwd_idx, docs, doc_ids, stats)
            else:
                stats["failed"] += 1

        if docs:
            _write_dwd_batch(es_host, dwd_idx, docs, doc_ids, stats)

        print(f"    [AI 重捞] {round2_hits}/{len(fetched)} 命中写 DWD")

    round2_ai_breeds = len(uncategorized_breeds)
    print(
        f"  [ETL] {city} 完成: → {dwd_idx} | "
        f"第一轮 | hit={round1_etled}, miss_breeds={round2_ai_breeds}, "
        f"第二轮(ai+重捞) | total_etled={stats['etled']}, "
        f"total_failed={stats['failed']}"
    )
    return stats["etled"], stats["failed"]


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
    """全流程：ODS→DWD（DB 2 段 + AI 补缓存），再 DWD→DWS。"""
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
