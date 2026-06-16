"""pipeline/etl.py - ODS → DWD 二段式 ETL（v1+v2 并行）

新数据流（2026-06-16 简化，去掉 v1 阶段 3 AI）：
  ┌─────────────────────────────────────────────────────────────────────┐
  │ ODS source                                                          │
  │   │                                                                 │
  │   ├── v1 阶段 1+2：breed_category_rules.db 精确 + Jaccard 模糊       │
  │   │     - transform_doc 内置（纯 DB 查表，不调 AI）                 │
  │   │     - 命中 → DWD.category = v1 大类名                            │
  │   │     - 未命中 → DWD.category = '其他'                            │
  │   │     - category_source = 'db_exact' / 'db_fuzzy' / ''             │
  │   │                                                                 │
  │   └── v2 5 段式：category_v2_rules.db 精确 → Jaccard → 正则 → AI    │
  │         - db_exact_v2 / db_fuzzy_v2 / pattern_v2 / ai_v2 / unit_fallback │
  │         - DWD.category_l1/l2/l3/l4 + name_l1/l2/l3 + 7 个属性字段    │
  │         - 命中即写；AI 失败兜底 no_match_v2                          │
  └─────────────────────────────────────────────────────────────────────┘

v1/v2 协作模式：
  - v1 category 写到 DWD.category（v1 大类，如「钢材金属材料」），用于 spec 规则库过滤
  - v2 14 字段写到 DWD.category_l1/l2/l3/l4 + ... + material_code
  - v1 仅 DB 查表，**不再调 AI**（v1 AI 入口 classify_breed_batch 2026-06-16 删除）
  - 全部 AI 资源让位给 v2 4 层分类

数据依赖：
  - gov_price_etl.classify（v1 二段式：DB 精确 + Jaccard 模糊）
  - gov_price_etl.classify.category_v2（v2 5 段式，写 DWD 14 字段）
  - gov_price_etl.transform.transform_doc（ODS → DWD 单文档转换）

etl.py 主体瘦身：移除 v1 阶段 3 AI 攒批逻辑（_ai_classify_pending / ai_pending 累加）。
"""
import time
from typing import Tuple

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
    """单城市 ODS → DWD 二段式 ETL。返回 (成功, 失败)。

    流程（2026-06-16 简化）：
      1. ODS 滚动拉取（按 update_date 排序）
      2. 每条调 transform_doc() → v1 阶段 1+2（DB 查表，不调 AI） + v2 5 段式
      3. 直接 bulk_index 写 DWD，无 v1 AI 后处理

    v1 阶段 3 AI 已删除，category 未命中统一填 '其他'，v2 兜底 no_match_v2。
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

    # ── v1 DB 查表 + v2 5 段式：transform_doc 内部已调完，直接写 DWD ──
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

                # v1 阶段 1+2 已在 transform_doc 内调完（classify_breed → DB 查表）
                # category / category_source 已带在 doc 里
                # 2026-06-16 简化：v1 不再调 AI，未命中直接是 '其他'

                if dry_run:
                    print(f"    [dry-run] {doc['breed_clean']} → {doc.get('category', '其他')}")
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

    print(
        f"  [ETL] {city} 完成: → {dwd_idx} | "
        f"etled={etled}, failed={failed}"
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