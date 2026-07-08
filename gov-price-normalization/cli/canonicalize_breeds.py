#!/usr/bin/env python3
"""canonicalize_breeds.py — AI 规范化 CLI（breed_clean → normalized_breed）

职责：
  1. extract  - 抽 DWS 全部 distinct breed_clean，对比 DB 找 pending
  2. resolve  - 批量调 Dify etl-canonicalize-breed，回写 DB
  3. stats    - 汇总统计

数据流：
  DWS.breed_clean
    ↓ extract (扫 dws_*_price terms agg)
  tmp/pending_breeds.json
    ↓ resolve (batch 50/批 调 Dify)
  breed_canonical.db INSERT
    ↓ rebuild (build_norm_index.py)
  NORM 文档 normalized_breed

用法：
    # 1. 抽 pending（不调 AI）
    python3 -m cli.canonicalize_breeds extract --out tmp/pending_breeds.json

    # 2. 批量 AI 规范化并回写
    python3 -m cli.canonicalize_breeds resolve --in tmp/pending_breeds.json --batch-size 20

    # 3. 看统计
    python3 -m cli.canonicalize_breeds stats
"""
from __future__ import annotations

import sys
import os
import json
import time
import argparse
import sqlite3
from pathlib import Path
from collections import defaultdict
from typing import Optional, Iterable

_HERE = Path(__file__).resolve().parent
_PKG = _HERE.parent
if str(_PKG) not in sys.path:
    sys.path.insert(0, str(_PKG))

from gov_price_normalization.data.breed_canonical import DB_PATH, get_canonical_batch  # noqa: E402
from gov_price_normalization.utils import data_loader  # noqa: E402
from gov_price_normalization.data import breed_canonical as _bc  # noqa: E402

ES_HOST = os.environ.get("ES_HOST", "http://localhost:59200")

try:
    from elasticsearch import Elasticsearch
    from elasticsearch.helpers import scan
except ImportError:
    print("ERROR: 需要 elasticsearch 包", file=sys.stderr)
    sys.exit(1)

# Dify
try:
    sys.path.insert(0, str(_PKG.parent / "gov-price-etl"))
    from gov_price_etl.ai.dify_client import call_workflow, KNOWN_APPS
    _DIFY_OK = True
except ImportError as e:
    print(f"[warn] Dify client 不可用: {e}", file=sys.stderr)
    _DIFY_OK = False


# ── DB 写入（带 WAL） ──────────────────────────────────────────────────
def _connect_rw() -> sqlite3.Connection:
    """读写连接（canonicalize_breeds.py 写 DB 用）"""
    con = sqlite3.connect(str(DB_PATH), timeout=30)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA synchronous=NORMAL")
    con.row_factory = sqlite3.Row
    return con


def _upsert_mappings(rows: list, source: str) -> int:
    """rows: [{breed_clean, normalized_breed, confidence, note, l3_code?}, ...]
    Returns: new_count (实际新插入的条数)
    """
    if not rows:
        return 0
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    con = _connect_rw()
    new_count = 0
    try:
        for r in rows:
            cur = con.execute(
                "SELECT 1 FROM breed_canonical WHERE breed_clean = ?", (r["breed_clean"],)
            )
            existed = cur.fetchone() is not None
            con.execute(
                "INSERT OR REPLACE INTO breed_canonical "
                "(breed_clean, normalized_breed, l3_code, confidence, source, note, created_at, updated_at) "
                "VALUES (?,?,?,?,?,?,COALESCE((SELECT created_at FROM breed_canonical WHERE breed_clean=?),?),?)",
                (
                    r["breed_clean"],
                    r["normalized_breed"],
                    r.get("l3_code"),
                    float(r.get("confidence", 0.9)),
                    source,
                    (r.get("note") or "")[:200],
                    r["breed_clean"],
                    now,
                    now,
                ),
            )
            if not existed:
                new_count += 1
        con.commit()
    finally:
        con.close()
    return new_count


def _log_run(event: str, input_count: int, new_count: int, updated_count: int,
             failed_count: int, duration_sec: float, meta: Optional[dict] = None) -> None:
    con = _connect_rw()
    try:
        con.execute(
            "INSERT INTO canonical_run (event, input_count, new_count, updated_count, failed_count, duration_sec, meta, created_at) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (event, input_count, new_count, updated_count, failed_count, duration_sec,
             json.dumps(meta or {}, ensure_ascii=False),
             time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())),
        )
        con.commit()
    finally:
        con.close()


# ── extract：抽 DWS 全部 distinct breed_clean，对比 DB 找 pending ─────
def cmd_extract(args) -> int:
    es = Elasticsearch(args.es_host, request_timeout=120)

    # 1. 列所有 dws_*_price 索引
    if args.cities:
        cities = [c.strip() for c in args.cities.split(",") if c.strip()]
        indices = [f"dws_{c}_price" for c in cities]
    else:
        resp = es.indices.get(index="dws_*_price", ignore_unavailable=True)
        indices = sorted(resp.keys())
    print(f"[extract] 扫 {len(indices)} 个 DWS 索引")

    # 2. 跨索引聚合 distinct breed_clean
    all_breed_cleans = set()
    for idx in indices:
        try:
            r = es.search(
                index=idx,
                body={"size": 0, "aggs": {"b": {"terms": {"field": "breed_clean", "size": 10000}}}},
                ignore_unavailable=True,
            )
            buckets = r.get("aggregations", {}).get("b", {}).get("buckets", [])
            for b in buckets:
                k = (b["key"] or "").strip()
                if k:
                    all_breed_cleans.add(k)
        except Exception as e:
            print(f"  [warn] {idx} skip: {e}", file=sys.stderr)

    print(f"[extract] 跨 {len(indices)} 城 DWS distinct breed_clean = {len(all_breed_cleans):,}")

    # 3. 加载 DB 已收录的，清出 pending
    db_batch = get_canonical_batch(list(all_breed_cleans))
    db_set = {bc for bc, v in db_batch.items() if v is not None}
    pending = sorted(all_breed_cleans - db_set)
    print(f"[extract] DB 已收录 {len(db_set):,} / pending {len(pending):,}")

    # 4. 输出
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "scanned_cities": len(indices),
        "distinct_breed_clean": len(all_breed_cleans),
        "already_in_db": len(db_set),
        "pending_count": len(pending),
        "pending": pending,
    }
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[extract] → {out_path} ({out_path.stat().st_size:,} bytes)")
    return 0


# ── resolve：批量调 Dify，回写 DB ─────────────────────────────────────
def _try_parse_partial_json(s: str) -> Optional[dict]:
    """Dify 把截断 JSON 当字符串返时，尝试救回完整 key。

    策略：
      1) 先尝试 json.loads（完好 JSON 直接返）
      2) 失败：找到第一个 '{' 到最后一个 '},' 切，保留所有完整 dict
    """
    if not s:
        return None
    s = s.strip()
    # 1) 完整 JSON
    try:
        v = json.loads(s)
        return v if isinstance(v, dict) else None
    except Exception:
        pass
    # 2) 截断 JSON：截到最后一个 '},' 位置（含 }）
    if "{" not in s or "}" not in s:
        return None
    start = s.find("{")
    last_close = -1
    for i in range(len(s) - 1, -1, -1):
        if s[i] == "}":
            nxt = s[i + 1] if i + 1 < len(s) else ""
            if nxt in (",", "\n", " "):
                last_close = i + 1
                break
    if last_close <= 0:
        return None
    head = s[start:last_close]  # 含到 }
    candidate = head + "}"  # 补一个右括号让 json.loads 能解析
    try:
        v = json.loads(candidate)
        return v if isinstance(v, dict) else None
    except Exception:
        return None
def _call_dify_batch(breed_cleans: list, retries: int = 2) -> dict:
    """调一次 Dify workflow，返回 {breed_clean: {normalized_breed, confidence, note}} 或 {} on fail

    防御层：Dify 偶尔会把截断的 JSON 当字符串返回（`Output results is not an object`）。
    这里多一道：拿到字符串时尝试 json.loads，部分入库也接受，缺的进 reject。
    """
    if not _DIFY_OK:
        raise RuntimeError("Dify client 不可用")
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
                user="norm-canonicalize-batch",
                timeout_s=180,
            )
            if resp.ok and resp.outputs:
                out = resp.outputs.get("results")
                # 1) 正常情况：dict 直返
                if isinstance(out, dict):
                    return out
                # 2) 字符串：尝试 parse（截断 JSON 也救回一部分）
                if isinstance(out, str):
                    parsed = _try_parse_partial_json(out)
                    if parsed is not None:
                        print(f"    [warn] results 是字符串，截断救回 {len(parsed)}/{len(breed_cleans)}", file=sys.stderr)
                        return parsed
                # 3) 都不是：fallback
                last_err = resp.error or f"workflow_status={resp.workflow_status}, results_type={type(out).__name__}"
            else:
                last_err = resp.error or f"workflow_status={resp.workflow_status}"
        except Exception as e:
            last_err = str(e)
        if attempt < retries:
            wait = 2 ** attempt
            print(f"    [retry] attempt {attempt+1} failed ({last_err[:100]}); sleep {wait}s", file=sys.stderr)
            time.sleep(wait)
    raise RuntimeError(f"Dify batch failed after {retries+1} attempts: {last_err}")


def cmd_resolve(args) -> int:
    t0 = time.time()
    in_path = Path(args.in_)
    payload = json.loads(in_path.read_text(encoding="utf-8"))
    pending = payload.get("pending", [])
    print(f"[resolve] 输入 {len(pending):,} 条 pending breed")

    if args.limit:
        pending = pending[:args.limit]
        print(f"[resolve] --limit={args.limit}，实际处理 {len(pending):,} 条")

    if not pending:
        print("[resolve] 无 pending 待处理")
        return 0

    batch_size = args.batch_size
    print(f"[resolve] batch_size={batch_size}, total_batches={(len(pending) + batch_size - 1) // batch_size}")

    total_new = 0
    total_updated = 0
    total_failed = 0
    total_batches = 0
    rejected = []
    for i in range(0, len(pending), batch_size):
        batch = pending[i:i + batch_size]
        batch_no = i // batch_size + 1
        total_batches += 1
        print(f"  [batch {batch_no}/{total_batches}] {len(batch)} 条 → Dify", end=" ... ", flush=True)
        try:
            result = _call_dify_batch(batch)
        except Exception as e:
            print(f"FAIL ({e})")
            total_failed += len(batch)
            rejected.extend(batch)
            continue

        # 落 DB
        rows = []
        for bc in batch:
            r = result.get(bc)
            if not r:
                # Dify 没返回这条 → 标记 reject
                rejected.append(bc)
                total_failed += 1
                continue
            nb = (r.get("normalized_breed") or "").strip()
            if not nb:
                rejected.append(bc)
                total_failed += 1
                continue
            rows.append({
                "breed_clean": bc,
                "normalized_breed": nb,
                "confidence": float(r.get("confidence", 0.9)),
                "note": r.get("note", ""),
            })

        new_n = _upsert_mappings(rows, source="ai_dify")
        total_new += new_n
        total_updated += (len(rows) - new_n)
        distinct_norm_in_batch = len(set(r["normalized_breed"] for r in rows))
        print(f"OK (input={len(batch)} mapped={len(rows)} new={new_n} distinct_norm={distinct_norm_in_batch})")

    # 写黑名单（被 Dify 拒绝的）
    if rejected:
        con = _connect_rw()
        try:
            now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            for bc in rejected:
                con.execute(
                    "INSERT OR REPLACE INTO canonical_reject (breed_clean, reason, last_tried_at) VALUES (?,?,?)",
                    (bc, "ai_no_result", now),
                )
            con.commit()
        finally:
            con.close()
        print(f"[resolve] 黑名单 {len(rejected)} 条写入 canonical_reject")

    # 写 canonical_run
    duration = round(time.time() - t0, 2)
    _log_run(
        "batch_resolve",
        input_count=len(pending),
        new_count=total_new,
        updated_count=total_updated,
        failed_count=total_failed,
        duration_sec=duration,
        meta={"batch_size": batch_size, "total_batches": total_batches, "rejected": len(rejected)},
    )
    print()
    print(f"  [summary] input={len(pending)}  new={total_new}  updated={total_updated}  failed={total_failed}  duration={duration}s")
    # 清缓存，让后续 build_norm_index 重新拉
    _bc.clear_cache()
    print("  [cache]  breed_canonical cache cleared")
    return 0


# ── stats：汇总统计 ──────────────────────────────────────────────────
def cmd_stats(args) -> int:
    s = _bc.get_stats()
    print(json.dumps(s, ensure_ascii=False, indent=2))
    return 0


# ── bootstrap：从 breed_l3_map_v3 seed 导入（带 l3_code 校验） ──────
def cmd_bootstrap(args) -> int:
    """从 gov-price-etl/data/category_v3_rules.db 的 breed_l3_map_v3 表
    拉 breed_clean → (normalized_breed=l3_name, l3_code, source=etl_v3_sqlite)
    写入 breed_canonical。

    审计：每个 l3_code 必须在 category_v3 字典里（防硬编码错值，如 jilin 翻车的
    "01.01.01 挖一般土方"）。

    选项：
      --dry-run          只统计不写
      --replace          覆盖现有 etl_v3_sqlite 来源的记录（默认跳过冲突）
      --min-confidence   只导 conf >= 此值的（默认 0.9）
    """
    t0 = time.time()

    # 1. 拉 v3 rules DB
    from gov_price_etl.paths import PROJECT_ROOT
    v3_db = PROJECT_ROOT / "data" / "category_v3_rules.db"
    if not v3_db.exists():
        print(f"[bootstrap] v3 rules DB 不存在: {v3_db}", file=sys.stderr)
        return 1
    print(f"[bootstrap] 源: {v3_db}")

    conn = sqlite3.connect(f"file:{v3_db}?mode=ro", uri=True)
    try:
        cur = conn.execute(
            "SELECT breed_clean, l3, source, confidence FROM breed_l3_map_v3 "
            "WHERE confidence >= ?",
            (args.min_confidence,),
        )
        v3_rows = cur.fetchall()
    finally:
        conn.close()
    print(f"[bootstrap] v3.breed_l3_map_v3 拉取 {len(v3_rows)} 条 (conf >= {args.min_confidence})")

    # 2. 反查 l3 中文名（来自 category_v3 表）
    conn = sqlite3.connect(f"file:{v3_db}?mode=ro", uri=True)
    try:
        l3_name_map = dict(conn.execute(
            "SELECT l3, name_l3 FROM category_v3 WHERE l3 IS NOT NULL"
        ).fetchall())
    finally:
        conn.close()
    print(f"[bootstrap] v3.category_v3 字典 {len(l3_name_map)} 个 L3")

    # 3. 审计：l3 必须在字典里（防硬编码错值）
    valid_rows = []
    invalid_samples = []
    invalid_count = 0
    for breed_clean, l3, source, confidence in v3_rows:
        if not l3 or l3 == "UNCLASSIFIED":
            invalid_count += 1
            if len(invalid_samples) < 5:
                invalid_samples.append((breed_clean, l3, "l3空或UNCLASSIFIED"))
            continue
        if l3 not in l3_name_map:
            invalid_count += 1
            if len(invalid_samples) < 5:
                invalid_samples.append((breed_clean, l3, "l3不在v3字典里"))
            continue
        # normalized_breed 用 l3 中文名（与之前 bootstrap 保持一致）
        normalized = l3_name_map[l3]
        valid_rows.append({
            "breed_clean": breed_clean,
            "normalized_breed": normalized,
            "l3_code": l3,
            "confidence": float(confidence),
            "source": "etl_v3_sqlite",
            "note": (source or "")[:200],
        })

    print(f"[bootstrap] 有效: {len(valid_rows)} / 无效: {invalid_count}")
    if invalid_count:
        print(f"[bootstrap] 无效样本（前5）:")
        for bc, l3, reason in invalid_samples:
            print(f"    - {bc!r} → {l3!r} ({reason})")

    if args.dry_run:
        print(f"[bootstrap] --dry-run，不写 DB")
        return 0

    if not valid_rows:
        print(f"[bootstrap] 无有效记录可写")
        return 0

    # 4. 写 DB（带 replace 选项）
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    con = _connect_rw()
    new_count = 0
    updated_count = 0
    skipped_count = 0
    try:
        for r in valid_rows:
            cur = con.execute(
                "SELECT source FROM breed_canonical WHERE breed_clean = ?", (r["breed_clean"],)
            )
            existing = cur.fetchone()
            if existing:
                if not args.replace:
                    skipped_count += 1
                    continue
                # replace 模式：只覆盖 etl_v3_sqlite 来源（避免覆盖 ai_dify 的归一结果）
                if existing[0] not in ("etl_v3_sqlite", "bootstrap"):
                    skipped_count += 1
                    continue
                con.execute(
                    "UPDATE breed_canonical SET normalized_breed=?, l3_code=?, confidence=?, "
                    "source=?, note=?, updated_at=? WHERE breed_clean=?",
                    (r["normalized_breed"], r["l3_code"], r["confidence"],
                     r["source"], r["note"], now, r["breed_clean"]),
                )
                updated_count += 1
            else:
                con.execute(
                    "INSERT INTO breed_canonical "
                    "(breed_clean, normalized_breed, l3_code, confidence, source, note, created_at, updated_at) "
                    "VALUES (?,?,?,?,?,?,?,?)",
                    (r["breed_clean"], r["normalized_breed"], r["l3_code"],
                     r["confidence"], r["source"], r["note"], now, now),
                )
                new_count += 1
        con.commit()
    finally:
        con.close()

    # 5. 写 canonical_run
    duration = round(time.time() - t0, 2)
    _log_run(
        "bootstrap",
        input_count=len(v3_rows),
        new_count=new_count,
        updated_count=updated_count,
        failed_count=invalid_count,
        duration_sec=duration,
        meta={
            "source_table": "breed_l3_map_v3",
            "min_confidence": args.min_confidence,
            "replace": args.replace,
            "invalid_l3_count": invalid_count,
            "invalid_samples": invalid_samples,
            "skipped_existing": skipped_count,
        },
    )

    # 清缓存
    _bc.clear_cache()

    print()
    print(f"  [summary] source_rows={len(v3_rows)} valid={len(valid_rows)} invalid_l3={invalid_count} "
          f"new={new_count} updated={updated_count} skipped={skipped_count} duration={duration}s")
    return 0


# ── classify：补 UNCLASSIFIED 的 l3_code ─────────────────────────────
# v3 字典查询（独立函数，不依赖 cache 单例的全局副作用）
_V3_L3_CACHE: set = set()


def _validate_l3_v3_dict(l3: str) -> bool:
    """校验 l3 是否在 category_v3 字典里（防 AI 编造）。"""
    if not l3 or l3 == "UNCLASSIFIED":
        return False
    if l3 in _V3_L3_CACHE:
        return True
    try:
        import sqlite3 as _sq
        from gov_price_etl.paths import PROJECT_ROOT
        v3_db = PROJECT_ROOT / "data" / "category_v3_rules.db"
        if not v3_db.exists():
            return False
        conn = _sq.connect(f"file:{v3_db}?mode=ro", uri=True)
        row = conn.execute(
            "SELECT 1 FROM category_v3 WHERE l3 = ? LIMIT 1", (l3,)
        ).fetchone()
        conn.close()
        if row:
            _V3_L3_CACHE.add(l3)
            return True
    except Exception:
        pass
    return False


def _call_dify_classify_batch(breed_cleans: list, retries: int = 2) -> list:
    """调 etl-classify-category，返回 list[{breed_clean, l1, l2, l3, name_l3, confidence, ...}]

    防御层：
      - Dify 偶尔返回 dict 包裹 {results: [...]} → 解包
      - Dify 偶尔返回 str（截断/解析失败）→ 救回（json.loads）
    """
    if not _DIFY_OK:
        raise RuntimeError("Dify client 不可用")
    app_id = KNOWN_APPS["etl-classify-category"]["app_id"]
    # 格式化 breed_list（与 prompts.yml 期望一致）
    breed_list_str = "\n".join(
        f"{j+1}. breed={bc} | spec= | unit= | current_l3=" for j, bc in enumerate(breed_cleans)
    )
    last_err = None
    for attempt in range(retries + 1):
        try:
            resp = call_workflow(
                app_id,
                inputs={"breed_list": breed_list_str, "batch_n": len(breed_cleans)},
                user="norm-classify-batch",
                timeout_s=180,
            )
            if resp.ok and resp.outputs:
                out = resp.outputs.get("results")
                # 1) list 直返
                if isinstance(out, list):
                    return out
                # 2) dict 包裹 {"results": [...]}
                if isinstance(out, dict):
                    inner = out.get("results", [])
                    if isinstance(inner, list):
                        return inner
                # 3) 字符串（截断 JSON 救回）
                if isinstance(out, str):
                    parsed = _try_parse_partial_json(out)
                    if isinstance(parsed, list):
                        print(f"    [warn] results 是字符串，截断救回 {len(parsed)}/{len(breed_cleans)}", file=sys.stderr)
                        return parsed
                    if isinstance(parsed, dict):
                        inner = parsed.get("results", [])
                        if isinstance(inner, list):
                            return inner
                last_err = resp.error or f"workflow_status={resp.workflow_status}, results_type={type(out).__name__}"
            else:
                last_err = resp.error or f"workflow_status={resp.workflow_status}"
        except Exception as e:
            last_err = str(e)
        if attempt < retries:
            wait = 2 ** attempt
            print(f"    [retry] attempt {attempt+1} failed ({last_err[:100]}); sleep {wait}s", file=sys.stderr)
            time.sleep(wait)
    raise RuntimeError(f"Dify classify batch failed after {retries+1} attempts: {last_err}")


def cmd_classify(args) -> int:
    """批量调 etl-classify-category 给 UNCLASSIFIED 补 l3_code，写回 breed_canonical.l3_code。

    流程：
      1. 读 DB 拿所有 l3_code IS NULL 的 breed_clean
      2. batch=10 调 Dify（DeepSeek 版 workflow，内置 L3 知识库）
      3. 校验返回的 l3 是否在 v3 字典里（防 AI 编造）
      4. confidence < min_confidence 的拒绝（默认 0.7）
      5. 写回 DB：breed_canonical.l3_code
      6. 写 canonical_run 审计
    """
    t0 = time.time()

    # 1. 读 DB
    con = _connect_rw()
    cur = con.execute(
        "SELECT breed_clean FROM breed_canonical "
        "WHERE l3_code IS NULL ORDER BY breed_clean"
    )
    unclass_bcs = [row[0] for row in cur.fetchall()]
    con.close()
    print(f"[classify] UNCLASSIFIED 共 {len(unclass_bcs)} 条")

    if args.limit:
        unclass_bcs = unclass_bcs[:args.limit]
        print(f"[classify] --limit={args.limit}，实际处理 {len(unclass_bcs)} 条")

    if not unclass_bcs:
        print("[classify] 无 UNCLASSIFIED 待处理")
        return 0

    batch_size = args.batch_size
    total_batches = (len(unclass_bcs) + batch_size - 1) // batch_size
    print(f"[classify] batch_size={batch_size}, total_batches={total_batches}, min_confidence={args.min_confidence}")

    total_updated = 0
    total_low_conf = 0
    total_invalid_l3 = 0
    total_missing = 0
    total_failed = 0
    for i in range(0, len(unclass_bcs), batch_size):
        batch = unclass_bcs[i:i + batch_size]
        batch_no = i // batch_size + 1
        print(f"  [batch {batch_no}/{total_batches}] {len(batch)} 条 → Dify", end=" ... ", flush=True)
        try:
            results = _call_dify_classify_batch(batch)
        except Exception as e:
            print(f"FAIL ({e})")
            total_failed += len(batch)
            continue

        # 建 breed_clean → result 索引（智能引号容错：norm 归一化兜底）
        from gov_price_etl.classify.utils import norm_bc
        results_dict = {r.get("breed_clean"): r for r in results if isinstance(r, dict) and r.get("breed_clean")}
        results_dict_norm = {norm_bc(k): v for k, v in results_dict.items()}

        # 落 DB
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        con = _connect_rw()
        updated_in_batch = 0
        low_conf_in_batch = 0
        invalid_l3_in_batch = 0
        missing_in_batch = 0
        try:
            for bc in batch:
                r = results_dict.get(bc) or results_dict_norm.get(norm_bc(bc))
                if not r:
                    missing_in_batch += 1
                    continue
                conf = float(r.get("confidence", 0.7) or 0.7)
                l3 = (r.get("l3") or "").strip()
                name_l3 = (r.get("name_l3") or "").strip()
                # 低置信度不写
                if conf < args.min_confidence:
                    low_conf_in_batch += 1
                    continue
                if not l3:
                    invalid_l3_in_batch += 1
                    continue
                # 校验 l3 在 v3 字典里（防 AI 编造）
                if not _validate_l3_v3_dict(l3):
                    invalid_l3_in_batch += 1
                    continue
                # 写 l3_code
                con.execute(
                    "UPDATE breed_canonical SET l3_code=?, updated_at=? WHERE breed_clean=?",
                    (l3, now, bc),
                )
                updated_in_batch += 1
            con.commit()
        finally:
            con.close()

        total_updated += updated_in_batch
        total_low_conf += low_conf_in_batch
        total_invalid_l3 += invalid_l3_in_batch
        total_missing += missing_in_batch
        print(f"OK (mapped={updated_in_batch} low_conf={low_conf_in_batch} invalid_l3={invalid_l3_in_batch} missing={missing_in_batch})")

    duration = round(time.time() - t0, 2)
    _log_run(
        "batch_classify",
        input_count=len(unclass_bcs),
        new_count=total_updated,
        updated_count=0,
        failed_count=total_low_conf + total_invalid_l3 + total_missing + total_failed,
        duration_sec=duration,
        meta={
            "batch_size": batch_size,
            "total_batches": total_batches,
            "min_confidence": args.min_confidence,
            "low_conf": total_low_conf,
            "invalid_l3": total_invalid_l3,
            "missing": total_missing,
            "failed": total_failed,
        },
    )

    # 清缓存
    _bc.clear_cache()

    print()
    print(f"  [summary] input={len(unclass_bcs)}  updated={total_updated}  "
          f"low_conf={total_low_conf}  invalid_l3={total_invalid_l3}  "
          f"missing={total_missing}  failed={total_failed}  duration={duration}s")
    return 0


# ── CLI 入口 ──────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser(description="breed_canonical DB 维护 CLI")
    sub = ap.add_subparsers(dest="cmd", required=True)

    # extract
    p_ext = sub.add_parser("extract", help="抽 DWS distinct breed_clean，找 pending")
    p_ext.add_argument("--es-host", default=ES_HOST)
    p_ext.add_argument("--cities", help="逗号分隔城市列表（默认全量）")
    p_ext.add_argument("--out", default="tmp/pending_breeds.json")
    p_ext.set_defaults(func=cmd_extract)

    # resolve
    p_res = sub.add_parser("resolve", help="批量调 Dify AI 规范化，回写 DB")
    p_res.add_argument("--in", required=True, dest="in_", help="extract 输出的 JSON")
    p_res.add_argument("--batch-size", type=int, default=20, help="Dify 单次 batch 大小（默认 20，防 LLM 输出截断）")
    p_res.add_argument("--limit", type=int, help="最多处理多少条（调试用）")
    p_res.set_defaults(func=cmd_resolve)

    # stats
    p_stats = sub.add_parser("stats", help="汇总统计")
    p_stats.set_defaults(func=cmd_stats)

    # classify（补 UNCLASSIFIED 的 l3_code）
    p_cls = sub.add_parser("classify", help="批量调 etl-classify-category 给 UNCLASSIFIED 补 l3_code")
    p_cls.add_argument("--batch-size", type=int, default=10, help="Dify 单次 batch 大小（默认 10，与 prompts.yml 一致）")
    p_cls.add_argument("--limit", type=int, help="最多处理多少条（调试用）")
    p_cls.add_argument("--min-confidence", type=float, default=0.7, help="最小置信度阈值（默认 0.7，低于此值不写 l3_code）")
    p_cls.set_defaults(func=cmd_classify)

    # bootstrap（从 breed_l3_map_v3 seed 导入，带 l3_code 校验）
    p_boot = sub.add_parser("bootstrap", help="从 v3 rules DB 的 breed_l3_map_v3 seed 导入到 breed_canonical，带 l3 校验")
    p_boot.add_argument("--dry-run", action="store_true", help="只审计不写 DB")
    p_boot.add_argument("--replace", action="store_true", help="覆盖现有 etl_v3_sqlite 来源的记录（默认跳过冲突，避免覆盖 ai_dify）")
    p_boot.add_argument("--min-confidence", type=float, default=0.9, help="v3 规则库的最小 confidence（默认 0.9）")
    p_boot.set_defaults(func=cmd_bootstrap)

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
