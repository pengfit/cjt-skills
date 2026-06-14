"""pipeline/dws_sync.py - DWD → DWS 同步（合一）

历史上 3 处 DWS 同步入口（行为不一致）已合并为 1 个核心 + 3 个薄壳：
  - sync_dws()           核心循环（search_after 翻页 + bulk 写 DWS）
  - sync_dws_with_ai()   增量：缺 attr 的 doc 走 AI 补全，再写 DWS
  - sync_dws_plain()     全量：DWD 有 spec 即同步（不调 AI）
  - sync_dws_quick()     全量：DWD 有非空 attr 即同步（不调 AI）

统一语义：
  - DWD doc_id 即 DWS doc_id（upsert 语义）
  - 入 DWS 条件：source_filter(doc) 为真（各模式不同）
  - 字段映射：DWS = {**dwd 源, "attr": flat_attr_to_nested(build_attr(dwd))}，删除 attr_* 前缀
  - 死循环防护：search_after 连续两页 etl_time 相同则强制退出
"""
import json
import time
from typing import Callable, Optional, Tuple

import requests

from gov_price_etl.classify import (
    get_category_system_map,
    get_category_system_name_map,
)
from gov_price_etl.config import CITY_CONFIGS
from gov_price_etl.es_client import bulk_index, get_es_client
from gov_price_etl.indexer import ensure_indices
from gov_price_etl.parse_spec import get_parser
from gov_price_etl.transform import build_attr, flat_attr_to_nested, transform_doc


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


# ── 核心循环 ────────────────────────────────────────────────────────────
def sync_dws(
    es_host: str,
    city: str,
    cfg: dict,
    *,
    batch_size: int = 500,
    dry_run: bool = False,
    # 入 DWS 过滤：返回 True 的 doc 才同步
    source_filter: Callable[[dict, dict], bool] = None,
    # 可选后置处理：返回新的 attr dict（用于 AI 补全等场景）
    enrich_attr: Callable[[dict, dict], dict] = None,
) -> Tuple[int, int]:
    """
    DWD → DWS 同步核心循环。

    Args:
        es_host: ES 地址
        city:    城市 key
        cfg:     {"dwd": ..., "dws": ...}
        batch_size: search_after 翻页 size
        dry_run:    只统计不写入
        source_filter:  (dwd_source, hit) → bool，True 才同步
        enrich_attr:   (dwd_source, hit) → dict，注入 attr（覆盖 build_attr 结果）

    Returns:
        (synced, failed)
    """
    dwd_idx = cfg["dwd"]
    dws_idx = cfg["dws"]
    session = get_es_client(es_host)

    if not dry_run:
        ensure_indices(es_host, cfg)

    if source_filter is None:
        # 默认：spec 非空就同步
        def _default_filter(d, h):
            return bool(d.get("spec"))
        source_filter = _default_filter

    # 初次搜索
    body = {
        "query": {"match_all": {}},
        "size": batch_size,
        "sort": [{"etl_time": "asc"}, {"_id": "asc"}],
    }
    resp = session.post(f"{es_host}/{dwd_idx}/_search", json=body, timeout=60)
    if resp.status_code != 200:
        print(f"  [DWS] {city}: 查询 DWD 失败: {resp.text[:200]}")
        return 0, 0
    hits = resp.json()["hits"]["hits"]
    total_resp = session.post(f"{es_host}/{dwd_idx}/_count", json={"query": {"match_all": {}}}, timeout=30)
    total = total_resp.json().get("count", 0) if total_resp.status_code == 200 else 0

    if total == 0:
        print(f"  [DWS] {city}: 无待同步数据")
        return 0, 0
    print(f"  [DWS] {city}: {dwd_idx} → {dws_idx} ({total:,} 条 DWD)")

    synced = 0
    failed = 0
    skipped = 0
    pages = 0
    prev_etl_time = None
    start = time.time()

    while hits:
        pages += 1
        dws_docs = []
        dws_ids = []

        for h in hits:
            d = dict(h["_source"])
            if not source_filter(d, h):
                skipped += 1
                continue

            if enrich_attr is not None:
                new_attr = enrich_attr(d, h)
                if new_attr:
                    d["attr"] = flat_attr_to_nested(new_attr)
                # enrich_attr 返回空 → 走默认 build_attr
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

        if pages % 20 == 0:
            print(f"    pages={pages}, synced={synced}/{total}")

        # search_after 翻页
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
        # 死循环防护
        if pages > 1 and hits and last_etl_time == prev_etl_time:
            print(f"  [WARN] sync_dws search_after 可能死循环: etl_time={repr(last_etl_time)}, 强制退出", flush=True)
            break
        prev_etl_time = last_etl_time

    elapsed = time.time() - start
    print(f"  [DWS] {city} 完成: synced={synced}, skipped={skipped}, failed={failed}, 用时 {elapsed:.1f}s")
    return synced, failed


# ── 三个对外入口（薄壳） ────────────────────────────────────────────────
def sync_dws_plain(es_host: str, city: str, cfg: dict, batch_size: int = 500,
                   category: str = "", dry_run: bool = False) -> Tuple[int, int]:
    """DWD spec 非空 → DWS（不调 AI，对应旧 flush_to_dws）。"""
    # category 过滤：旧 flush_to_dws 支持，这里透传到 source_filter
    if category:
        def _filter(d, h):
            return bool(d.get("spec")) and d.get("category") == category
        return sync_dws(es_host, city, cfg, batch_size=batch_size, dry_run=dry_run, source_filter=_filter)
    return sync_dws(es_host, city, cfg, batch_size=batch_size, dry_run=dry_run)


def sync_dws_quick(es_host: str, city: str, cfg: dict, batch_size: int = 1000,
                   dry_run: bool = False) -> Tuple[int, int, int]:
    """DWD attr 非空 → DWS（不调 AI，对应旧 sync_dws_quick.py）。"""
    def _filter(d, h):
        return bool(build_attr(d))
    s, f = sync_dws(es_host, city, cfg, batch_size=batch_size, dry_run=dry_run, source_filter=_filter)
    return s, 0, f  # 旧接口三返回 (synced, skipped, failed)，这里 skipped 由 sync_dws 内部计


def sync_dws_with_ai(es_host: str, city: str, cfg: dict, batch_size: int = 500,
                     ai_batch_size: int = 100, category: str = "",
                     dry_run: bool = False) -> Tuple[int, int]:
    """DWD → DWS，缺 attr 的 doc 走 AI 补全（对应旧 flush_to_dws_with_ai）。

    入 DWS 条件：spec 非空 + (已有 attr OR AI 补全到 attr)。
    """
    # 这部分逻辑比较复杂（旧 400 行），保留原行为
    # 简化思路：source_filter 接受 spec 非空；enrich_attr 走 AI 补全
    # 实际 AI 批处理逻辑在 sync_dws_with_ai_impl 里实现
    return _sync_dws_with_ai_impl(es_host, city, cfg, batch_size, ai_batch_size, category, dry_run)


def _sync_dws_with_ai_impl(
    es_host: str, city: str, cfg: dict,
    batch_size: int, ai_batch_size: int, category: str, dry_run: bool
) -> Tuple[int, int]:
    """旧 flush_to_dws_with_ai 的实现细节（AI 批量补全 attr）。"""
    import re

    dwd_idx = cfg["dwd"]
    dws_idx = cfg["dws"]
    session = get_es_client(es_host)

    # 启用 _id 字段排序支持（search_after 需要 etl_time+_id 联合排序打破 tie）
    try:
        requests.put(
            f"{es_host}/_cluster/settings",
            json={"persistent": {"indices.id_field_data.enabled": "true"}},
        )
    except Exception:
        pass

    must_clauses = [{"exists": {"field": "spec"}}]
    if category:
        must_clauses.append({"term": {"category": category}})

    ensure_indices(es_host, cfg)

    # 统计总数
    cnt = session.post(f"{es_host}/{dwd_idx}/_count",
                       json={"query": {"bool": {"must": must_clauses}}}, timeout=30)
    total = cnt.json().get("count", 0) if cnt.status_code == 200 else 0
    if total == 0:
        print(f"  [DWS+AI] {city}: 无待同步数据")
        return 0, 0
    print(f"  [DWS+AI] {city}: {dwd_idx} → {dws_idx} ({total:,} 条)")

    parser = get_parser(city)
    synced = failed = local_parsed = local_failed = 0
    pages = 0

    body = {
        "query": {"bool": {"must": must_clauses}},
        "size": batch_size,
        "sort": [{"etl_time": "asc"}, {"_id": "asc"}],
    }
    resp = session.post(f"{es_host}/{dwd_idx}/_search", json=body, timeout=60)
    if resp.status_code != 200:
        print(f"  [DWS+AI] 查询 DWD 失败: {resp.text[:200]}")
        return 0, 0
    hits = resp.json()["hits"]["hits"]

    # 待 AI 解析的批次
    ai_batch: list = []
    seen_doc_ids: set = set()
    hits_by_id: dict = {h["_id"]: h for h in hits}

    def _flush_ai_batch():
        """调 AI 解析攒批，返回 [(doc_id, suggestions), ...]。"""
        nonlocal ai_batch
        if not ai_batch:
            return []
        from collections import defaultdict
        # 按 (breed, spec) 去重
        groups: dict = defaultdict(list)
        for b in ai_batch:
            key = (b["breed"], b["spec"])
            groups[key].append(b)
        deduped = [v[0] for v in groups.values()]
        if len(ai_batch) > len(deduped):
            print(f"    [AI] 去重: {len(ai_batch)} → {len(deduped)} (breed+spec)")

        items = [{"spec": b["spec"], "breed": b["breed"], "category": b["category"]} for b in deduped]
        try:
            from gov_price_etl.ai import parse_spec_batch
            before = parse_spec_batch.__module__  # just to test import works
            from gov_price_etl.ai.service import parse_spec_batch as _psb
            print(f"    [AI] 调用 ai_service.parse_spec_batch ({len(items)} 条，去重后)...", flush=True)
            ai_list = _psb(items, write_rules=True)
        except Exception as e:
            print(f"    [AI] ai_service 初始化失败: {e}，回退为空结果", flush=True)
            ai_list = []

        results_map = {}
        for r in ai_list:
            results_map[r.get("spec", "")] = r.get("suggestions", [])

        out = []
        for b in ai_batch:
            suggestions = results_map.get(b["spec"], [])
            out.append((b["doc_id"], suggestions))
        ai_batch.clear()
        return out

    prev_etl_time = None
    while hits:
        pages += 1

        for h in hits:
            doc_id = h["_id"]
            if doc_id in seen_doc_ids:
                continue
            seen_doc_ids.add(doc_id)
            d = dict(h["_source"])
            spec = d.get("spec", "")
            breed = d.get("breed", "")
            cat = d.get("category", "")
            hits_by_id[doc_id] = h

            # 1. DWD 已有 attr → 直接 sync
            existing_attr = build_attr(d)
            if existing_attr:
                dws_doc = _source_to_dws(d)
                ok, err = bulk_index(es_host, dws_idx, [dws_doc], [doc_id])
                synced += ok
                failed += err
                local_parsed += 1
                continue

            # 2. 本地规则库尝试解析
            local_attrs: dict = {}
            if parser and spec:
                try:
                    parsed = parser.parse(spec, breed, cat)
                    if parsed:
                        local_attrs = {k: v for k, v in parsed.items() if v}
                except Exception:
                    pass

            if local_attrs:
                # 规则库命中：写回 DWD attr，sync 到 DWS
                nested = flat_attr_to_nested(local_attrs)
                upd_body = (
                    json.dumps({"update": {"_id": doc_id}}, ensure_ascii=False) + "\n" +
                    json.dumps({"doc": {"attr": nested}}, ensure_ascii=False) + "\n"
                )
                session.post(
                    f"{es_host}/{dwd_idx}/_bulk",
                    data=upd_body.encode("utf-8"),
                    headers={"Content-Type": "application/x-ndjson"},
                    timeout=60,
                )
                dws_doc = _source_to_dws(d)
                dws_doc["attr"] = nested
                ok, err = bulk_index(es_host, dws_idx, [dws_doc], [doc_id])
                synced += ok
                failed += err
                local_parsed += 1
            else:
                # 3. 规则库未命中 → 送 AI
                local_failed += 1
                ai_batch.append({"doc_id": doc_id, "spec": spec, "breed": breed, "category": cat})

        # AI batch 满了则触发解析并回写
        if len(ai_batch) >= ai_batch_size:
            results = _flush_ai_batch()
            dws_docs, dws_ids = [], []
            for did, suggestions in results:
                if not suggestions:
                    continue
                # 执行 code_block 提取 attr 值
                attrs = {}
                for s in suggestions:
                    a = s.get("attr", "")
                    c = s.get("code_block", "")
                    if not a or not c:
                        continue
                    norm_a = a[5:] if a.startswith("attr_") else a
                    try:
                        exec_globals = {"result": {}, "re": re, "s": ""}
                        # spec 从 hit 取
                        h = hits_by_id.get(did)
                        exec_globals["s"] = h["_source"].get("spec", "") if h else ""
                        code = c if isinstance(c, str) else "\n".join(c)
                        exec(code, exec_globals)
                        val = exec_globals.get("result", {}).get(norm_a, "")
                        if not val:
                            val = exec_globals.get("result", {}).get(a, "")
                        if val:
                            attrs[norm_a] = str(val)
                    except Exception:
                        pass
                # 从 hits_by_id 找源文档
                h = hits_by_id.get(did)
                if not h:
                    continue
                src = dict(h["_source"])
                if not attrs:
                    attrs = build_attr(src)
                # 合并 src nested attr
                src_attr = src.get("attr")
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
                src["attr"] = flat_attr_to_nested(attrs)
                for f in ("date", "publish_time"):
                    if not src.get(f):
                        src.pop(f, None)
                dws_docs.append(src)
                dws_ids.append(did)
            if dws_docs and not dry_run:
                ok, err = bulk_index(es_host, dws_idx, dws_docs, dws_ids)
                synced += ok
                failed += err

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
        results = _flush_ai_batch()
        dws_docs, dws_ids = [], []
        for did, suggestions in results:
            if not suggestions:
                continue
            h = hits_by_id.get(did)
            if not h:
                continue
            src = dict(h["_source"])
            spec_text = src.get("spec", "")
            attrs = {}
            for s in suggestions:
                a = s.get("attr", "")
                c = s.get("code_block", "")
                if not a or not c:
                    continue
                norm_a = a[5:] if a.startswith("attr_") else a
                try:
                    exec_globals = {"result": {}, "re": re, "s": spec_text}
                    code = c if isinstance(c, str) else "\n".join(c)
                    exec(code, exec_globals)
                    val = exec_globals.get("result", {}).get(norm_a, "")
                    if not val:
                        val = exec_globals.get("result", {}).get(a, "")
                    if val:
                        attrs[norm_a] = str(val)
                except Exception:
                    pass
            # 回写 DWD
            if attrs and not dry_run:
                upd_body = (
                    json.dumps({"update": {"_id": did}}, ensure_ascii=False) + "\n" +
                    json.dumps({"doc": attrs}, ensure_ascii=False) + "\n"
                )
                session.post(
                    f"{es_host}/{dwd_idx}/_bulk",
                    data=upd_body.encode("utf-8"),
                    headers={"Content-Type": "application/x-ndjson"},
                    timeout=60,
                )
            if not attrs:
                attrs = build_attr(src)
            src["attr"] = flat_attr_to_nested(attrs)
            for f in ("date", "publish_time"):
                if not src.get(f):
                    src.pop(f, None)
            dws_docs.append(src)
            dws_ids.append(did)
        if dws_docs and not dry_run:
            ok, err = bulk_index(es_host, dws_idx, dws_docs, dws_ids)
            synced += ok
            failed += err

    print(f"  [DWS+AI] {city} 完成: synced={synced}, failed={failed}, local_parsed={local_parsed}, local_failed={local_failed}")
    return synced, failed
