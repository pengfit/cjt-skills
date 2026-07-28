#!/usr/bin/env python3
"""build_norm_index.py — Normalizer ETL worker

职责：
- 读 dws_{city}_price 索引
- 调 normalize_batch() 批量标准化
- 写 norm_{city}_price 索引（NormalizationLayer 自己拥有）

用法：
    # 单城全量重建
    python3 -m cli.build_norm_index --city xian

    # 多城全量重建
    python3 -m cli.build_norm_index --cities xian,hainan,chongqing

    # 所有 DWS 城市
    python3 -m cli.build_norm_index --all-cities

    # 增量：只重建某 period_start 之后的数据
    python3 -m cli.build_norm_index --city xian --since 2026-06-01

    # 干跑（不写，只统计会写多少条）
    python3 -m cli.build_norm_index --city xian --dry-run

依赖：elasticsearch Python client（>=7.x）
"""

from __future__ import annotations
import sys
import os
import json
import time
import argparse
from pathlib import Path
from datetime import datetime
from typing import Optional

_HERE = Path(__file__).resolve().parent
_PKG = _HERE.parent
if str(_PKG) not in sys.path:
    sys.path.insert(0, str(_PKG))

from gov_price_normalization.pipeline import normalize_batch  # noqa: E402
from gov_price_normalization.utils import data_loader  # noqa: E402
from gov_price_normalization.utils.errors import NormalizationError  # noqa: E402
from gov_price_normalization.data.breed_canonical import get_canonical, DB_PATH  # noqa: E402

# ES 配置（与 dashboard 一致；Phase D 可统一到 .env）
ES_HOST = os.environ.get("ES_HOST", "http://localhost:59200")
ES_AUTH = os.environ.get("ES_AUTH")  # 可选 "user:pass"

try:
    from elasticsearch import Elasticsearch
    from elasticsearch.helpers import scan, bulk
except ImportError:
    print("ERROR: 需要 elasticsearch 包。安装：pip install elasticsearch>=7", file=sys.stderr)
    sys.exit(1)

# 2026-07-25: Dify 客户端（--with-dify 时用，治理 raw_fallback）
try:
    import sqlite3 as _sqlite
    import sys as _sys
    # _HERE = .../skills/gov-price-normalization/cli/
    # .parent.parent = .../skills/
    _SKILLS = _HERE.parent.parent  # skills/
    _DIFY_PATH = str(_SKILLS / "gov-price-etl")
    if _DIFY_PATH not in _sys.path:
        _sys.path.insert(0, _DIFY_PATH)
    from gov_price_etl.ai.dify_client import call_workflow, KNOWN_APPS  # noqa: E402
    _DIFY_OK = True
except ImportError as e:
    _DIFY_OK = False
    _DIFY_ERR = str(e)


def _es():
    if ES_AUTH:
        return Elasticsearch(ES_HOST, basic_auth=tuple(ES_AUTH.split(":")), request_timeout=60)
    return Elasticsearch(ES_HOST, request_timeout=60)


def _dws_index(city: str) -> str:
    return f"dws_{city}_price"


def _norm_index(city: str) -> str:
    return f"norm_{city}_price"


def _ensure_norm_index(es, city: str) -> bool:
    """如果 norm_{city}_price 不存在则创建（按 data/norm_index_settings.json 模板）。"""
    idx = _norm_index(city)
    if es.indices.exists(index=idx):
        return False
    settings = data_loader.load_json("norm_index_settings.json")
    # ES 不接受顶层 _meta（去掉）；其余原样
    body = {
        "settings": settings["settings"],
        "mappings": settings["mappings"],
    }
    es.indices.create(index=idx, body=body)
    print(f"[create] {idx}")
    return True


def _scan_dws(es, city: str, since: Optional[str] = None, size: int = 1000):
    """扫描 dws_{city}_price，可选按 period_start 过滤。"""
    idx = _dws_index(city)
    query: dict = {}
    if since:
        query = {"range": {"period_start": {"gte": since}}}
    kwargs: dict = {"index": idx, "size": size, "preserve_order": True, "request_timeout": 120}
    if query:
        kwargs["query"] = query
    return scan(es, **kwargs)


def _normalize_doc(dws_doc: dict, city: str) -> dict:
    """包装 normalize_doc：把标准化结果 + 原 DWS doc 合并成 NORM doc。"""
    src = dws_doc.get("_source", {})
    # normalized_breed：跨城 join 用的归一化名（dashboard trend/compare 的 should OR 优先匹配这个字段）
    #   查表顺序：breed_clean → breed
    #     命中 → 拿表里的 normalized_breed（可能与原始不同，多对一合并）+ 写 _canonical_source
    #     未命中 → 野生品种：normalized_breed = raw breed，_canonical_source=raw_fallback
    #   后续 AI 规范化累积进 breed_canonical.db 后会自动覆盖 raw_fallback（增量）
    _key = (src.get("breed_clean") or src.get("breed") or "").strip()
    _hit = get_canonical(_key) if _key else None
    if _hit:
        normed = normalize_batch([src], city, l3_code=_hit.get("l3_code"))[0]
        normed["normalized_breed"] = _hit["normalized_breed"]
        normed["_l3_code"] = _hit.get("l3_code")
        normed["_canonical_source"] = _hit["source"]
        normed["_canonical_confidence"] = _hit.get("confidence", 0.0)
    else:
        # 野生品种：l3_code=None → L1 走 hard_reject 兑底, 不走 L3 白名单
        normed = normalize_batch([src], city, l3_code=None)[0]
        normed["normalized_breed"] = _key
        normed["_l3_code"] = None
        normed["_canonical_source"] = "raw_fallback"
        normed["_canonical_confidence"] = 0.0
    # 把 _id 保留下来作 _dws_id 追溯
    normed["_dws_id"] = dws_doc.get("_id")
    # 加 build 元信息
    normed.setdefault("_norm", {})
    normed["_norm"]["built_at"] = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    # 顶层冗余字段（便于 dashboard 直接 filter）
    normed["canonical_period"] = normed.get("canonical_period")
    normed["canonical_unit"] = (normed.get("unit_norm") or {}).get("normalized")
    # 注意：l3_code 现在从 breed_canonical 查到了 → L1 attr 净化会走 L3 白名单收紧
    return normed


def _bulk_actions(actions):
    """包装 elasticsearch.helpers.bulk，统一 success/failure 计数。"""
    success, failed = bulk(_es(), actions, raise_on_error=False, request_timeout=120)
    return success, failed


def build_city(es, city: str, since: Optional[str] = None, dry_run: bool = False, batch_size: int = 500, with_dify: bool = False) -> dict:
    """重建/增量单个城市的 NORM 索引。返回统计。

    2026-07-25: with_dify=True 时，rebuild 完成后调 Dify 补 raw_fallback
    """
    started = time.time()
    dws_idx = _dws_index(city)
    norm_idx = _norm_index(city)

    # 0. 检查 DWS 索引存在
    if not es.indices.exists(index=dws_idx):
        return {"city": city, "ok": False, "error": f"DWS 索引不存在：{dws_idx}"}

    # 1. 准备 NORM 索引（全量时强制重建；增量时不重建）
    created = False
    if not dry_run:
        if not since:
            if es.indices.exists(index=norm_idx):
                print(f"[rebuild] {norm_idx} → delete + recreate")
                es.indices.delete(index=norm_idx)
            created = _ensure_norm_index(es, city)
        else:
            created = _ensure_norm_index(es, city)

    # 2. scan DWS
    print(f"[scan] {dws_idx} (since={since or 'all'})")
    scanned = 0
    written = 0
    failed = 0
    skipped = 0
    err_samples = []
    actions = []
    for hit in _scan_dws(es, city, since=since):
        scanned += 1
        try:
            normed = _normalize_doc(hit, city)
        except Exception as e:
            failed += 1
            if len(err_samples) < 3:
                err_samples.append(f"normalize: {e}")
            continue

        # 2026-07-25 (P0-fix): 防止 None/0 价格污染跨城均价
        # 修复 bug:之前 DWS->NORM 允许 price 为 None 或 0 的数据落入 NORM,
        # 污染跨城归一均价、热力图涨跌幅、attr_norm 计算。
        # 2026-07-26 (P1-fix): OR → AND
        # 旧逻辑 OR 过于激进——6 城 DWS 无 tax_price 字段（默认 0）被 100% skip，
        # 但 price 字段值正常。改为双 0 才 skip（AND），单 0 视为「未含税」放行。
        _price_v = normed.get("price")
        _tax_v = normed.get("tax_price")
        if (
            (_price_v is None or not isinstance(_price_v, (int, float)) or _price_v <= 0)
            and (_tax_v is None or not isinstance(_tax_v, (int, float)) or _tax_v <= 0)
        ):
            skipped += 1
            continue

        if dry_run:
            if scanned <= 2:
                print(f"[dry-run sample] _id={hit.get('_id')[:20]}... canonical_period={normed.get('canonical_period')}")
            continue

        actions.append({
            "_op_type": "index",
            "_index": norm_idx,
            "_source": normed,
        })

        if len(actions) >= batch_size:
            s, f = bulk(es, actions, raise_on_error=False, stats_only=True, request_timeout=120)
            written += s
            failed += f
            actions = []
            if scanned % (batch_size * 5) == 0:
                print(f"[progress] scanned={scanned} written={written} failed={failed}")

    if actions and not dry_run:
        s, f = bulk(es, actions, raise_on_error=False, stats_only=True, request_timeout=120)
        written += s
        failed += f

    # 3. 强制 refresh（方便 dashboard 立刻读到）
    if not dry_run and written > 0:
        try:
            es.indices.refresh(index=norm_idx)
        except Exception as e:
            print(f"[warn] refresh failed: {e}")

    elapsed = time.time() - started
    summary = {
        "city": city,
        "ok": True,
        "dws_index": dws_idx,
        "norm_index": norm_idx,
        "norm_created": created,
        "dry_run": dry_run,
        "scanned": scanned,
        "written": written,
        "failed": failed,
        "skipped": skipped,
        "elapsed_sec": round(elapsed, 2),
        "rate": round(scanned / elapsed, 1) if elapsed > 0 else 0,
        "err_samples": err_samples,
    }
    print(f"\n[summary] {json.dumps(summary, ensure_ascii=False)}")

    # 2026-07-25: --with-dify Phase 2（仅全量重建 + 启用 flag）
    if with_dify and not dry_run and not since:
        dify_result = _run_dify_phase(es, norm_idx, city)
        summary["dify_phase"] = dify_result

    return summary


# ─── 2026-07-25: --with-dify 补缓存 Phase（raw_fallback 治理）───────────────
def _scan_with_body(es, index: str, body: dict, page_size: int = 500) -> "generator":
    """2026-07-25: 手写 scroll 迭代，避免 scan() 在 ES 8.x 下 query/term 解包 bug

    body 必须包含 "query" 键。可选 "_source" 限制返回字段
    """
    full_body = {**body, "size": page_size}
    resp = es.search(index=index, body=full_body, scroll="5m", request_timeout=120)
    scroll_id = resp.get("_scroll_id")
    hits = resp["hits"]["hits"]
    while hits:
        for h in hits:
            yield h
        resp = es.scroll(scroll_id=scroll_id, scroll="5m", request_timeout=120)
        scroll_id = resp.get("_scroll_id")
        hits = resp["hits"]["hits"]
    if scroll_id:
        try:
            es.clear_scroll(scroll_id=scroll_id)
        except Exception:
            pass


def _collect_raw_fallback_breeds(es, norm_idx: str) -> list:
    """从刚建好的 NORM 索引收集所有 raw_fallback 的 distinct breed_clean

    返回 list[str]（去重），作为 Dify 调用的输入
    """
    pending = set()
    body = {
        "query": {"term": {"_canonical_source.keyword": "raw_fallback"}},
        "_source": ["breed_clean", "breed"],
    }
    for hit in _scan_with_body(es, norm_idx, body):
        src = hit.get("_source", {})
        bc = (src.get("breed_clean") or src.get("breed") or "").strip()
        if bc:
            pending.add(bc)
    return list(pending)


def _dify_call_batch(breed_cleans: list, retries: int = 2) -> dict:
    """调一次 Dify etl-canonicalize-breed workflow

    返回 {breed_clean: {normalized_breed, l3_code, confidence, note}}
    失败抛 RuntimeError
    """
    if not _DIFY_OK:
        raise RuntimeError(f"Dify client 不可用: {_DIFY_ERR}")
    app_id = KNOWN_APPS["etl-canonicalize-breed"]["app_id"]
    last_err = None
    for attempt in range(retries + 1):
        try:
            resp = call_workflow(
                app_id,
                inputs={
                    "breeds_json": json.dumps(breed_cleans, ensure_ascii=False),
                    "n": len(breed_cleans),
                },
                user=f"norm-build-with-dify-{int(time.time()*1000)}",
                timeout_s=180,
            )
            if resp.ok and resp.outputs:
                out = resp.outputs.get("results")
                if isinstance(out, dict):
                    return out
                last_err = resp.error or f"workflow_status={resp.workflow_status}, results_type={type(out).__name__}"
            else:
                last_err = resp.error or f"workflow_status={resp.workflow_status}"
        except Exception as e:
            last_err = str(e)
        if attempt < retries:
            wait = 2 ** attempt
            print(f"    [retry] attempt {attempt+1} failed ({str(last_err)[:100]}); sleep {wait}s")
            time.sleep(wait)
    raise RuntimeError(f"Dify batch failed after {retries+1} attempts: {last_err}")


def _upsert_dify_results(results: dict) -> int:
    """把 Dify 结果写入 breed_canonical.db（source='ai_dify'），返回写入条数

    INSERT OR REPLACE：如果该 breed_clean 已有 ai_dify entry，覆盖；其他 source 不动

    2026-07-25: Dify etl-canonicalize-breed 只返回 normalized_breed/confidence/note
    （l3_code 不返回，Dify workflow 只返 normalized_breed/confidence/note）— 允许 l3_code=None
    """
    if not results:
        return 0
    con = _sqlite.connect(str(DB_PATH), timeout=30)
    try:
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA synchronous=NORMAL")
        rows = []
        for bc, r in results.items():
            nb = r.get("normalized_breed") or bc
            l3 = r.get("l3_code") or r.get("l3")  # Dify 不返回 → None
            conf = float(r.get("confidence", 0.0)) if r.get("confidence") is not None else 0.0
            note = r.get("note", "") or ""
            rows.append((bc, nb, l3, conf, "ai_dify", note))
        if not rows:
            return 0
        cur = con.executemany(
            "INSERT OR REPLACE INTO breed_canonical "
            "(breed_clean, normalized_breed, l3_code, confidence, source, note, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, COALESCE((SELECT created_at FROM breed_canonical WHERE breed_clean=?), datetime('now')), datetime('now'))",
            [(bc, nb, l3, conf, "ai_dify", note[:200], bc) for (bc, nb, l3, conf, _src, note) in rows],
        )
        con.commit()
        return cur.rowcount
    finally:
        con.close()


def _update_norm_docs(es, norm_idx: str, dify_results: dict, city: str) -> int:
    """把 raw_fallback 文档用 Dify 结果就地 update（不重建全索引，省 IO）

    只更新受影响文档：breed_clean in dify_results 且 _canonical_source='raw_fallback'
    返回更新条数
    """
    if not dify_results:
        return 0
    affected_breeds = list(dify_results.keys())
    body = {
        "query": {"bool": {
            "must": [{"term": {"_canonical_source.keyword": "raw_fallback"}}],
            "filter": [{"terms": {"breed_clean": affected_breeds}}],
        }},
        "_source": ["breed", "breed_clean", "city", "canonical_period", "canonical_unit", "_dws_id"],
    }
    actions = []
    updated = 0
    for hit in _scan_with_body(es, norm_idx, body):
        src = hit["_source"]
        bc = (src.get("breed_clean") or src.get("breed") or "").strip()
        r = dify_results.get(bc)
        if not r:
            continue
        nb = r.get("normalized_breed") or bc
        l3 = r.get("l3_code") or r.get("l3")
        src_copy = dict(src)
        src_copy["normalized_breed"] = nb
        # 重新跑 normalize_batch 让 l3_name 等字段同步更新
        enriched = normalize_batch([src_copy], city, l3_code=l3)[0]
        enriched["normalized_breed"] = nb
        enriched["_l3_code"] = l3
        enriched["_canonical_source"] = "ai_dify"
        enriched["_canonical_confidence"] = float(r.get("confidence", 0.0))
        # 保留 build 元信息
        enriched["_dws_id"] = src.get("_dws_id")
        enriched["canonical_period"] = enriched.get("canonical_period") or src.get("canonical_period")
        enriched["canonical_unit"] = enriched.get("canonical_unit") or src.get("canonical_unit")
        actions.append({
            "_op_type": "index",
            "_index": norm_idx,
            "_id": hit["_id"],
            "_source": enriched,
        })
        if len(actions) >= 200:
            s, _ = bulk(es, actions, raise_on_error=False, stats_only=True, request_timeout=60)
            updated += s
            actions = []
    if actions:
        s, _ = bulk(es, actions, raise_on_error=False, stats_only=True, request_timeout=60)
        updated += s
    return updated


def _run_dify_phase(es, norm_idx: str, city: str, batch_size: int = 20) -> dict:
    """Dify 补缓存全流程（--with-dify 启用时调用）

    1. 收集 raw_fallback breeds
    2. 批量调 Dify
    3. 写 DB
    4. 清进程内缓存
    5. 就地 update 受影响 NORM 文档（不全量重建，省 IO）
    """
    started = time.time()
    print(f"\n[dify] === Phase 2: Dify 补缓存 (--with-dify) ===")
    if not _DIFY_OK:
        print(f"[dify] Dify client 不可用 ({_DIFY_ERR})，跳过")
        return {"phase": "dify", "ok": False, "error": _DIFY_ERR}

    pending = _collect_raw_fallback_breeds(es, norm_idx)
    if not pending:
        print(f"[dify] 无 raw_fallback，无需调 Dify")
        return {"phase": "dify", "ok": True, "pending": 0, "dify_returned": 0, "db_written": 0, "norm_updated": 0, "elapsed_sec": 0}
    print(f"[dify] 收集到 {len(pending)} 个 distinct raw_fallback breed")

    all_results = {}
    total_batches = (len(pending) + batch_size - 1) // batch_size
    failed_batches = 0
    for i in range(0, len(pending), batch_size):
        batch = pending[i:i + batch_size]
        bno = i // batch_size + 1
        print(f"  [dify batch {bno}/{total_batches}] {len(batch)} 条 → Dify ... ", end="", flush=True)
        try:
            r = _dify_call_batch(batch)
            all_results.update(r)
            print(f"OK (got {len(r)} results)")
        except Exception as e:
            print(f"FAIL ({str(e)[:100]})")
            failed_batches += 1
    print(f"[dify] Dify 返回 {len(all_results)} 条 (失败 batch={failed_batches})")

    db_written = _upsert_dify_results(all_results)
    print(f"[dify] DB 写入 {db_written} 条 (source=ai_dify)")

    # 清进程内缓存，让后续 DB 读拿到新数据
    from gov_price_normalization.data import breed_canonical as _bc
    _bc.clear_cache()

    # 就地 update 受影响文档（不全量重建）
    norm_updated = _update_norm_docs(es, norm_idx, all_results, city)
    print(f"[dify] NORM 就地 update {norm_updated} 条")

    try:
        es.indices.refresh(index=norm_idx)
    except Exception:
        pass

    elapsed = time.time() - started
    return {
        "phase": "dify",
        "ok": True,
        "pending": len(pending),
        "dify_returned": len(all_results),
        "db_written": db_written,
        "norm_updated": norm_updated,
        "failed_batches": failed_batches,
        "elapsed_sec": round(elapsed, 2),
    }


def main():
    ap = argparse.ArgumentParser(description="Normalizer ETL worker（DWS → NORM）")
    ap.add_argument("--city", help="单城市，如 xian")
    ap.add_argument("--cities", help="逗号分隔多城市，如 xian,hainan,chongqing")
    ap.add_argument("--all-cities", action="store_true", help="扫所有 dws_*_price 索引")
    ap.add_argument("--since", help="增量重建：period_start >= 此值 (YYYY-MM-DD)")
    ap.add_argument("--dry-run", action="store_true", help="干跑：不写 NORM，只扫描统计")
    ap.add_argument("--batch-size", type=int, default=500)
    ap.add_argument("--with-dify", action="store_true", help="2026-07-25: rebuild 后调 Dify 补 raw_fallback breeds（治理野生品种）")
    ap.add_argument("--es-host", default=ES_HOST, help="ES 地址")
    args = ap.parse_args()

    if not any([args.city, args.cities, args.all_cities]):
        ap.error("必须传 --city / --cities / --all-cities 之一")

    cities = []
    if args.city:
        cities = [args.city]
    elif args.cities:
        cities = [c.strip() for c in args.cities.split(",") if c.strip()]
    elif args.all_cities:
        es = _es()
        # 扫所有 dws_*_price
        resp = es.indices.get(index="dws_*_price", ignore_unavailable=True)
        for idx in resp.keys():
            # dws_xian_price → xian
            slug = idx.replace("dws_", "").replace("_price", "")
            if slug:
                cities.append(slug)

    print(f"[plan] cities={cities} since={args.since} dry_run={args.dry_run}")

    es = _es()
    results = []
    for city in cities:
        try:
            r = build_city(es, city, since=args.since, dry_run=args.dry_run, batch_size=args.batch_size, with_dify=args.with_dify)
        except Exception as e:
            r = {"city": city, "ok": False, "error": str(e)}
            print(f"[ERROR] {city}: {e}")
        results.append(r)

    print("\n========= FINAL =========")
    print(json.dumps(results, ensure_ascii=False, indent=2))

    # exit code：有失败则 1
    if any(not r.get("ok") or r.get("failed", 0) > 0 for r in results):
        sys.exit(1)


if __name__ == "__main__":
    main()