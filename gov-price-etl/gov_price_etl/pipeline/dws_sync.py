"""pipeline/dws_sync.py - DWD → DWS 三段式同步（明确节点）

新数据流（v0.3 重构）：
  ┌─────────────────────────────────────────────────────────────────────┐
  │ DWD source (attr 来自 ODS→DWD 阶段，可能为空)                        │
  │   │                                                                 │
  │   ├── 阶段 1：DWD attr 非空 → 直接同步 DWS                          │
  │   │     - 不调本地规则库、不调 AI                                     │
  │   │     - attr_source = 'etl'  （ODS→DWD 时已经解析过）              │
  │   │                                                                 │
  │   ├── 阶段 2：DWD attr 空 → 本地规则库 breed_spec_rules.db 解析     │
  │   │     - 调 BaseParseSpec.parse()（已重写为只查 vector_store）      │
  │   │     - 命中 → 回写 DWD attr + 同步 DWS                            │
  │   │     - attr_source = 'local_db'                                  │
  │   │                                                                 │
  │   └── 阶段 3：DWD attr 空 + 本地未命中 → AI batch_spec_parse 串行   │
  │         - 攒批（默认 20/批，串行调用，不并发）                        │
  │         - 命中 → 回写 DWD attr + 同步 DWS                            │
  │         - attr_source = 'ai' | 'ai_fallback'                        │
  └─────────────────────────────────────────────────────────────────────┘

每条 DWS 文档带 `attr_source` 字段，标识 attr 来源：
  'etl'         阶段 1 命中（DWD 已解析，ODS→DWD 阶段留下的）
  'local_db'    阶段 2 命中（本地 breed_spec_rules.db 解析）
  'ai'          阶段 3 AI 解析成功
  'ai_fallback' 阶段 3 AI 失败兜底（空 attr）

历史兼容：保留 sync_dws_plain / sync_dws_quick / sync_dws_with_ai 三个对外入口。
"""
import json
import re
import time
from collections import defaultdict
from typing import Callable, Optional, Tuple

import requests

from gov_price_etl.config import CITY_CONFIGS
from gov_price_etl.es_client import bulk_index, get_es_client
from gov_price_etl.indexer import ensure_indices
from gov_price_etl.parse_spec import get_parser
from gov_price_etl.transform import build_attr, flat_attr_to_nested


# AI 解析串行批次大小（道友要求"串行"，默认 20/批，逐批调用 AI）
AI_PARSE_BATCH_SIZE = 20
AI_PARSE_BATCH_SLEEP_S = 0.5  # 批间限速


def _is_price_valid(d: dict) -> bool:
    """价格有效性检查：price 和 tax_price 任一不为 None/0 才算有效。

    背景：甘孜州偏远区县 (sichuan) 、绿化苗木 (chongqing) 、造型树 (jinan) 等场景
    数据源未发布价格，被存为 0；这类文档写入 DWS 后会污染价格走势 / 排序 / 统计。
    返回 True 表示文档价格有效。
    """
    p = d.get("price")
    t = d.get("tax_price")
    p_valid = (p is not None) and (p != 0) and (p != 0.0)
    t_valid = (t is not None) and (t != 0) and (t != 0.0)
    return p_valid or t_valid


def _source_to_dws(d: dict) -> dict:
    """DWD source → DWS doc：转换 attr 字段，清理空值。"""
    dws_doc = dict(d)
    attr = build_attr(dws_doc)
    dws_doc["attr"] = flat_attr_to_nested(attr)
    # 删除原顶层 attr_* 字段（已迁移到 attr nested）
    for f in list(dws_doc.keys()):
        if f.startswith("attr_"):
            dws_doc.pop(f)
    # 过滤空 date 字段（空字符串无法解析为 date 类型）
    for f in ("date", "publish_time"):
        if not dws_doc.get(f):
            dws_doc.pop(f, None)
    return dws_doc


# ── 阶段 2: 本地规则库解析 ──────────────────────────────────────────────
def _parse_spec_local(spec: str, breed: str, category: str, city: str) -> dict:
    """阶段 2：本地规则库 breed_spec_rules.db 解析（不调 AI）。

    Returns:
        {attr_name: value, ...} 或 {}（未命中）
    """
    if not spec:
        return {}
    parser = get_parser(city)
    if not parser:
        return {}
    try:
        parsed = parser.parse(spec, breed, category)
        return {k: v for k, v in parsed.items() if v}
    except Exception:
        return {}


# ── 阶段 3: AI 串行解析 ─────────────────────────────────────────────────
def _ai_parse_specs_serial(items: list, city: str) -> dict:
    """阶段 3：AI batch_spec_parse 串行批次解析。

    Args:
        items: [{"spec", "breed", "category", "doc_id"}, ...]
        city:  城市 key（缓存分区用）

    Returns:
        {doc_id: (attrs_dict, source)}，source ∈ {'ai', 'ai_fallback'}
    """
    if not items:
        return {}

    from gov_price_etl.ai.service import parse_spec_batch

    # 按 (breed, spec) 去重，减少 AI 调用量
    groups: dict = defaultdict(list)
    for it in items:
        key = (it["breed"], it["spec"])
        groups[key].append(it)
    deduped = [v[0] for v in groups.values()]
    print(f"    [STG3 AI] 调用 batch_spec_parse: {len(items)} → {len(deduped)} (去重)")

    # 串行批次（每批 AI_PARSE_BATCH_SIZE 条）
    all_results: list = []
    total_batches = (len(deduped) + AI_PARSE_BATCH_SIZE - 1) // AI_PARSE_BATCH_SIZE
    t_stage3 = time.time()
    for i in range(0, len(deduped), AI_PARSE_BATCH_SIZE):
        batch_idx = i // AI_PARSE_BATCH_SIZE + 1
        chunk = deduped[i:i + AI_PARSE_BATCH_SIZE]
        chunk_items = [{"spec": it["spec"], "breed": it["breed"], "category": it["category"]}
                       for it in chunk]
        t0 = time.time()
        try:
            chunk_results = parse_spec_batch(chunk_items, write_rules=True)
            all_results.extend(chunk_results)
            print(f"    [STG3 AI] 批次 {batch_idx}/{total_batches}: {len(chunk)} 条，{time.time()-t0:.1f}s")
        except Exception as e:
            print(f"    [STG3 AI] 批次 {batch_idx}/{total_batches} 失败 ({time.time()-t0:.1f}s): {e}")
            # 失败：占位失败结果
            for it in chunk:
                all_results.append({
                    "spec": it["spec"],
                    "ok": False,
                    "suggestions": [],
                    "failed_reason": str(e),
                })
        if i + AI_PARSE_BATCH_SIZE < len(deduped):
            time.sleep(AI_PARSE_BATCH_SLEEP_S)
    print(f"    [STG3 AI] 阶段 3 AI 解析总耗时 {time.time()-t_stage3:.1f}s")

    # 把 AI 建议执行 code_block 提取 attr
    results_map: dict = {}  # spec → suggestions
    for r in all_results:
        results_map[r.get("spec", "")] = r.get("suggestions", [])

    out: dict = {}
    for it in items:
        suggestions = results_map.get(it["spec"], [])
        attrs = _execute_suggestions(suggestions, it["spec"])
        if attrs:
            out[it["doc_id"]] = (attrs, "ai")
        else:
            out[it["doc_id"]] = ({}, "ai_fallback")
    return out


def _execute_suggestions(suggestions: list, spec: str) -> dict:
    """执行 AI 返回的建议列表，提取 attr dict。"""
    attrs: dict = {}
    for s in suggestions:
        if not isinstance(s, dict):
            continue
        a = s.get("attr", "")
        c = s.get("code_block", "")
        if not a or not c:
            continue
        norm_a = a[5:] if a.startswith("attr_") else a
        try:
            exec_globals = {"result": {}, "re": re, "s": spec}
            code = c if isinstance(c, str) else "\n".join(c)
            # Python 3.12+ 对字符串中 \s 等非标注义序列产生 SyntaxWarning,
            # Dify 返回的 code_block 含 raw string (r'...') 语义，
            # compile 后 warnings.filterwarnings 静默处理
            import warnings
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", SyntaxWarning)
                exec(code, exec_globals)
            val = exec_globals.get("result", {}).get(norm_a, "")
            if not val:
                val = exec_globals.get("result", {}).get(a, "")
            if val:
                attrs[norm_a] = str(val)
        except Exception:
            pass
    return attrs


# ── 阶段 1+2+3 合并: DWD → DWS 三段式 ────────────────────────────────────
def _dwd_to_dws_three_stages(
    es_host: str,
    city: str,
    cfg: dict,
    *,
    batch_size: int = 500,
    category: str = "",
    dry_run: bool = False,
) -> Tuple[int, int, int, int]:
    """DWD → DWS 显式三段式。

    Returns:
        (stage1_synced, stage2_synced, stage3_synced, failed)
        - stage1_synced: DWD attr 非空直接同步
        - stage2_synced: 本地规则库命中同步
        - stage3_synced: AI 串行命中同步
    """
    dwd_idx = cfg["dwd"]
    dws_idx = cfg["dws"]
    session = get_es_client(es_host)

    # 防御：DWS == DWD 时（部分城市暂用同索引，如 henan），
    # 写入 DWS 会同时改 DWD 的 etl_time，导致 search_after 死循环。
    # 数据本就在同一个索引里，不需要再同步。
    if dwd_idx == dws_idx:
        cnt = 0
        try:
            cnt = session.post(
                f"{es_host}/{dwd_idx}/_count",
                json={"query": {"match_all": {}}},
                timeout=30,
            ).json().get("count", 0)
        except Exception:
            pass
        print(f"  [DWS+AI] {city}: DWD == DWS（{dwd_idx}），无需同步（{cnt} 条已是最终态）")
        return 0, 0, 0, 0

    if not dry_run:
        ensure_indices(es_host, cfg)

    # 启用 _id 字段排序支持
    try:
        requests.put(
            f"{es_host}/_cluster/settings",
            json={"persistent": {"indices.id_field_data.enabled": "true"}},
        )
    except Exception:
        pass

    # 查询条件：DWD spec 非空 + 可选 category 过滤
    must_clauses = [{"exists": {"field": "spec"}}]
    if category:
        must_clauses.append({"term": {"category": category}})

    # 统计总数
    cnt = session.post(f"{es_host}/{dwd_idx}/_count",
                       json={"query": {"bool": {"must": must_clauses}}}, timeout=30)
    total = cnt.json().get("count", 0) if cnt.status_code == 200 else 0
    if total == 0:
        print(f"  [DWS+AI] {city}: 无待同步数据")
        return 0, 0, 0, 0
    print(f"  [DWS+AI] {city}: {dwd_idx} → {dws_idx} ({total:,} 条)")

    stage1_synced = stage2_synced = stage3_synced = failed = pages = 0

    # 初次搜索
    body = {
        "query": {"bool": {"must": must_clauses}},
        "size": batch_size,
        "sort": [{"etl_time": "asc"}, {"_id": "asc"}],
    }
    resp = session.post(f"{es_host}/{dwd_idx}/_search", json=body, timeout=60)
    if resp.status_code != 200:
        print(f"  [DWS+AI] 查询 DWD 失败: {resp.text[:200]}")
        return 0, 0, 0, 0
    hits = resp.json()["hits"]["hits"]

    # 攒批容器
    ai_batch: list = []        # 阶段 3 待 AI 解析的 doc
    hits_by_id: dict = {}      # doc_id → hit（用于 AI 回写时找源文档）

    prev_etl_time = None

    while hits:
        pages += 1

        # 本轮攒批：阶段 1 同步 + 阶段 2 解析回写 + 阶段 3 攒批
        dws_docs_s1: list = []   # 阶段 1 同步
        dws_ids_s1: list = []
        dws_docs_s2: list = []   # 阶段 2 同步（已写回 DWD）
        dws_ids_s2: list = []
        dwd_update_s2: list = [] # 阶段 2 回写 DWD attr
        dwd_update_docs_s2: list = []

        for h in hits:
            doc_id = h["_id"]
            d = dict(h["_source"])
            hits_by_id[doc_id] = h
            # 价格过滤：price 和 tax_price 都为空/0 → 跳过（2026-06-24 道友需求）
            if not _is_price_valid(d):
                continue
            spec = d.get("spec", "")
            breed = d.get("breed", "")
            cat = d.get("category", "")

            existing_attr = build_attr(d)
            if existing_attr:
                # ── 阶段 1: DWD attr 非空 → 直接同步 ────────────────────
                dws_doc = _source_to_dws(d)
                dws_doc["attr_source"] = "etl"
                dws_docs_s1.append(dws_doc)
                dws_ids_s1.append(doc_id)
                continue

            # ── 阶段 2: 本地规则库 breed_spec_rules.db 解析 ─────────────
            local_attrs = _parse_spec_local(spec, breed, cat, city)
            if local_attrs:
                nested = flat_attr_to_nested(local_attrs)
                dwd_update_s2.append(json.dumps({"update": {"_id": doc_id}}, ensure_ascii=False) + "\n" +
                                     json.dumps({"doc": {"attr": nested}}, ensure_ascii=False) + "\n")
                dwd_update_docs_s2.append(doc_id)
                dws_doc = _source_to_dws(d)
                dws_doc["attr"] = nested
                dws_doc["attr_source"] = "local_db"
                dws_docs_s2.append(dws_doc)
                dws_ids_s2.append(doc_id)
                continue

            # ── 阶段 3: 攒批送 AI 串行解析 ──────────────────────────────
            ai_batch.append({
                "doc_id": doc_id, "spec": spec,
                "breed": breed, "category": cat,
            })

        # ── 批量写入 ─────────────────────────────────────────────────
        if dws_docs_s1:
            if dry_run:
                stage1_synced += len(set(dws_ids_s1))  # unique doc 数
            else:
                ok, err = bulk_index(es_host, dws_idx, dws_docs_s1, dws_ids_s1)
                stage1_synced += len(set(dws_ids_s1))  # unique doc 数
                failed += err

        if dws_docs_s2:
            if not dry_run and dwd_update_s2:
                # 写回 DWD attr
                update_body = "".join(dwd_update_s2)
                session.post(
                    f"{es_host}/{dwd_idx}/_bulk",
                    data=update_body.encode("utf-8"),
                    headers={"Content-Type": "application/x-ndjson"},
                    timeout=60,
                )
            if dry_run:
                stage2_synced += len(set(dws_ids_s2))  # unique doc 数
            else:
                ok, err = bulk_index(es_host, dws_idx, dws_docs_s2, dws_ids_s2)
                stage2_synced += len(set(dws_ids_s2))  # unique doc 数
                failed += err

        # AI batch 满了则触发串行解析 + 回写
        if len(ai_batch) >= AI_PARSE_BATCH_SIZE * 5:  # 攒够 5 批就触发，避免攒太多
            stage3_synced += _flush_ai_batch_to_dws(
                es_host, city, dwd_idx, dws_idx,
                ai_batch, hits_by_id, dry_run
            )

        if pages % 20 == 0:
            print(f"    pages={pages}, s1={stage1_synced}, s2={stage2_synced}, s3={stage3_synced}/{total}")

        # search_after 翻页
        last_hit = hits[-1]
        last_etl_time = last_hit["_source"].get("etl_time", "") or ""
        body_page = {
            "query": {"bool": {"must": must_clauses}},
            "size": batch_size,
            "search_after": [last_etl_time, last_hit["_id"]],
            "sort": [{"etl_time": "asc"}, {"_id": "asc"}],
        }
        try:
            resp_page = session.post(f"{es_host}/{dwd_idx}/_search", json=body_page, timeout=60)
        except Exception:
            break
        if resp_page.status_code != 200:
            break
        hits = resp_page.json()["hits"]["hits"]
        for h in hits:
            hits_by_id[h["_id"]] = h
        if pages > 1 and hits and last_etl_time == prev_etl_time:
            print(f"  [WARN] search_after 可能死循环: etl_time={repr(last_etl_time)}, 强制退出", flush=True)
            break
        prev_etl_time = last_etl_time

    # 剩余 AI batch
    if ai_batch:
        stage3_synced += _flush_ai_batch_to_dws(
            es_host, city, dwd_idx, dws_idx,
            ai_batch, hits_by_id, dry_run
        )

    print(
        f"  [DWS+AI] {city} 完成: "
        f"s1(etl)={stage1_synced}, s2(local_db)={stage2_synced}, s3(ai)={stage3_synced}, "
        f"failed={failed}"
    )
    return stage1_synced, stage2_synced, stage3_synced, failed


def _flush_ai_batch_to_dws(
    es_host: str, city: str, dwd_idx: str, dws_idx: str,
    ai_batch: list, hits_by_id: dict, dry_run: bool,
) -> int:
    """阶段 3 攒批触发：调 AI 串行解析 → 回写 DWD + 同步 DWS。"""
    if not ai_batch:
        return 0
    session = get_es_client(es_host)

    # 调 AI 串行批次解析
    ai_results = _ai_parse_specs_serial(ai_batch, city)

    dws_docs: list = []
    dws_ids: list = []
    dwd_update_body = ""
    for it in ai_batch:
        doc_id = it["doc_id"]
        attrs, src = ai_results.get(doc_id, ({}, "ai_fallback"))
        h = hits_by_id.get(doc_id)
        if not h:
            continue
        # 价格过滤：price 和 tax_price 都为空/0 → 跳过（2026-06-24 道友需求）
        if not _is_price_valid(dict(h["_source"])):
            continue
        src_doc = dict(h["_source"])
        # 合并 src nested attr（如已有顶层 attr_*）
        if not attrs:
            attrs = build_attr(src_doc)
        else:
            src_attr = src_doc.get("attr")
            if isinstance(src_attr, dict):
                for ak, av in src_attr.items():
                    if ak not in attrs:
                        attrs[ak] = av
            elif isinstance(src_attr, list):
                for item in src_attr:
                    if isinstance(item, dict):
                        ak = item.get("k", "")
                        av = item.get("v", "")
                        if ak and ak not in attrs:
                            attrs[ak] = str(av)

        nested = flat_attr_to_nested(attrs)
        # 回写 DWD
        if attrs and not dry_run:
            dwd_update_body += (
                json.dumps({"update": {"_id": doc_id}}, ensure_ascii=False) + "\n" +
                json.dumps({"doc": {"attr": attrs}}, ensure_ascii=False) + "\n"
            )

        # 同步 DWS - 阶段 3 必须在 attrs 非空时才入 DWS
        # 背景：AI 未命中时 attrs 是空 dict；如果不挡，attr=[] 文档会进 DWS 制造孤儿
        # （菏泽 2026-06-15 发现 87 条 DWS > DWD 的 _id 都是 attr=[]）
        # 阶段 1/2 不会到这里（line 280/294 已有 if existing_attr/if local_attrs 短路）
        if not attrs:
            # AI 未命中且 DWD 也没 attr → 不进 DWS
            continue
        src_doc["attr"] = nested
        src_doc["attr_source"] = src
        for f in ("date", "publish_time"):
            if not src_doc.get(f):
                src_doc.pop(f, None)
        dws_docs.append(src_doc)
        dws_ids.append(doc_id)

    if not dry_run and dwd_update_body:
        session.post(
            f"{es_host}/{dwd_idx}/_bulk",
            data=dwd_update_body.encode("utf-8"),
            headers={"Content-Type": "application/x-ndjson"},
            timeout=60,
        )

    if dws_docs:
        if dry_run:
            ai_batch.clear()  # 清空攒批容器（避免重复送 AI）
            return len(set(dws_ids))  # unique doc 数
        ok, err = bulk_index(es_host, dws_idx, dws_docs, dws_ids)
        ai_batch.clear()  # 清空攒批容器（避免重复送 AI 和重复累加 s3）
        return len(set(dws_ids))  # unique doc 数
    ai_batch.clear()  # 即使 dws_docs 为空也要清空
    return 0


# ── 三个对外入口（薄壳，向后兼容） ─────────────────────────────────────
def sync_dws(es_host: str, city: str, cfg: dict, *,
             batch_size: int = 500, dry_run: bool = False,
             source_filter: Callable = None,
             enrich_attr: Callable = None) -> Tuple[int, int]:
    """DWD → DWS 同步核心循环（兼容旧 source_filter/enrich_attr 接口）。

    新代码推荐用 sync_dws_with_ai()，内部走三段式。
    """
    dwd_idx = cfg["dwd"]
    dws_idx = cfg["dws"]

    # 防御：DWS == DWD 时跳过（见 _dwd_to_dws_three_stages 注释）
    if dwd_idx == dws_idx:
        print(f"  [DWS] {city}: DWD == DWS（{dwd_idx}），无需同步")
        return 0, 0

    session = get_es_client(es_host)

    if not dry_run:
        ensure_indices(es_host, cfg)

    if source_filter is None:
        source_filter = lambda d, h: bool(d.get("spec"))

    body = {
        "query": {"match_all": {}},
        "size": batch_size,
        "sort": [{"etl_time": "asc"}, {"_id": "asc"}],
    }
    resp = session.post(f"{es_host}/{dwd_idx}/_search", json=body, timeout=60)
    if resp.status_code != 200:
        return 0, 0
    hits = resp.json()["hits"]["hits"]
    total_resp = session.post(f"{es_host}/{dwd_idx}/_count", json={"query": {"match_all": {}}}, timeout=30)
    total = total_resp.json().get("count", 0) if total_resp.status_code == 200 else 0
    if total == 0:
        return 0, 0

    synced = failed = skipped = pages = 0
    prev_etl_time = None
    while hits:
        pages += 1
        dws_docs, dws_ids = [], []
        for h in hits:
            d = dict(h["_source"])
            if not source_filter(d, h):
                skipped += 1
                continue
            # 价格过滤：price 和 tax_price 都为空/0 → 跳过（2026-06-24 道友需求）
            if not _is_price_valid(d):
                skipped += 1
                continue
            if enrich_attr is not None:
                new_attr = enrich_attr(d, h)
                if new_attr:
                    d["attr"] = flat_attr_to_nested(new_attr)
                elif not d.get("attr"):
                    d["attr"] = flat_attr_to_nested(build_attr(d))
            else:
                d = _source_to_dws(d)
            dws_docs.append(d)
            dws_ids.append(h["_id"])
        if dws_docs:
            if dry_run:
                synced += len(dws_docs)
            else:
                ok, err = bulk_index(es_host, dws_idx, dws_docs, dws_ids)
                synced += ok
                failed += err

        last_hit = hits[-1]
        last_etl_time = last_hit["_source"].get("etl_time", "") or ""
        body = {
            "query": {"match_all": {}},
            "size": batch_size,
            "sort": [{"etl_time": "asc"}, {"_id": "asc"}],
            "search_after": [last_etl_time, last_hit["_id"]],
        }
        try:
            resp = session.post(f"{es_host}/{dwd_idx}/_search", json=body, timeout=60)
        except Exception:
            break
        if resp.status_code != 200:
            break
        hits = resp.json()["hits"]["hits"]
        if pages > 1 and hits and last_etl_time == prev_etl_time:
            break
        prev_etl_time = last_etl_time

    return synced, failed


def sync_dws_plain(es_host: str, city: str, cfg: dict, batch_size: int = 500,
                   category: str = "", dry_run: bool = False) -> Tuple[int, int]:
    """DWD spec 非空 → DWS（不调 AI，对应旧 flush_to_dws）。"""
    # category 过滤：旧 flush_to_dws 支持，这里走 source_filter 透传
    if category:
        def _filter(d, h):
            return bool(d.get("spec")) and d.get("category") == category
        return sync_dws(es_host, city, cfg, batch_size=batch_size, dry_run=dry_run, source_filter=_filter)
    return sync_dws(es_host, city, cfg, batch_size=batch_size, dry_run=dry_run)


def sync_dws_quick(es_host: str, city: str, cfg: dict, batch_size: int = 1000,
                   dry_run: bool = False) -> Tuple[int, int, int]:
    """DWD attr 非空 → DWS（不调 AI，对应旧 sync_dws_quick.py）。

    注：本接口等价于 sync_dws_with_ai 的"阶段 1"——只同步 attr 已有的。
    """
    def _filter(d, h):
        return bool(build_attr(d))
    s, f = sync_dws(es_host, city, cfg, batch_size=batch_size, dry_run=dry_run, source_filter=_filter)
    return s, 0, f


def sync_dws_with_ai(es_host: str, city: str, cfg: dict, batch_size: int = 500,
                     ai_batch_size: int = 100, category: str = "",
                     dry_run: bool = False) -> Tuple[int, int]:
    """DWD → DWS 三段式（对应旧 flush_to_dws_with_ai）。"""
    s1, s2, s3, f = _dwd_to_dws_three_stages(
        es_host, city, cfg,
        batch_size=batch_size, category=category, dry_run=dry_run,
    )
    return (s1 + s2 + s3), f