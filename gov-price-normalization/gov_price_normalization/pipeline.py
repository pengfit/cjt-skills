"""pipeline.py — 把 L1/L2/L3/L4 组合成 normalize_doc()

v0.2（2026-07-22）：
- L1 fields 提前到 L2/L3 之前跑（attr 净化是上游）
- L1 包含：sanitize_attr() 删脏/修错位 + normalize_cable_type() 电缆重拆
- L1 失败降级，不阻断

设计原则：
- pipeline 不写业务逻辑，只组合 layers/
- 每层失败时不阻断整流程，降级为保留原值 + 在字段里记 status
- status: 'ok' / 'skipped' / 'error'
"""
from __future__ import annotations
import logging
from typing import Optional
from .layers import units as L_units
from .layers import periods as L_periods
from .layers import fields as L_fields

log = logging.getLogger(__name__)


def normalize_doc(doc: dict, city: str, *, l3_code: Optional[str] = None, strict: bool = False) -> dict:
    """对单条 DWS 原始文档做标准化。

    Args:
        doc: DWS 原始 doc，至少包含 breed / period_start / unit / price / spec / attr
        city: 城市 key
        l3_code: v3 三级分类码（如 '01.05.07'）。提供后会做价格归一。
        strict: True 时任一层失败抛异常；False（默认）降级 + 记 status

    Returns:
        新字典（不修改入参），含原字段 + 所有 *_norm 字段 + 各层 status

    处理顺序：
        L1 fields (sanitize_attr + cable_type)  → attr_norm
        L3 periods                              → canonical_period
        L2 units                                → unit_norm
        L2 price_normalize (需 l3_code)         → price_norm
    """
    out = dict(doc)
    out.setdefault("_norm", {})
    norm_status = {}
    out["_norm"]["dropped_attrs"] = []  # L1 留痕槽

    # ── L1: attr 净化（最前） ─────────────────────────────────────────────
    try:
        sanitize = L_fields.sanitize_attr(doc, l3_code=l3_code)
        attr_norm = list(sanitize["attr_norm"])

        # L1: cable 型号归一（仅当 breed 含 cable 关键词时跑）
        cable = L_fields.normalize_cable_type(doc)
        if cable.get("applied"):
            # 删原错 type（同时记入 dropped, 供审计追溯）
            for drop_k in cable.get("drop_keys", []):
                removed = [a for a in attr_norm if a.get("k") == drop_k]
                for r in removed:
                    out["_norm"]["dropped_attrs"].append((r.get("k"), r.get("v"), "cable_canonical_replaced"))
            attr_norm = [a for a in attr_norm if a.get("k") not in cable.get("drop_keys", [])]
            # 写入新字段（canonical_type / voltage / core_count / cross_section / fire_rating / armor_type）
            for k in ("canonical_type", "voltage", "core_count", "cross_section", "fire_rating", "armor_type"):
                v = cable.get(k)
                if v is not None and v != "":
                    attr_norm.append({"k": k, "v": v})
            out["_norm"]["cable_canonical"] = cable
            norm_status["L1_cable_canonical"] = "ok"

        out["attr_norm"] = attr_norm
        out["_norm"]["dropped_attrs"].extend(sanitize["dropped"])
        if sanitize.get("promoted"):
            out["_norm"]["promoted_attrs"] = sanitize["promoted"]
        if sanitize.get("empty"):
            norm_status["L1_attr_sanitize"] = "skipped_empty"
        else:
            norm_status["L1_attr_sanitize"] = "ok"
    except Exception as e:
        norm_status["L1_attr_sanitize"] = f"error: {e}"
        if strict:
            raise
        log.warning("[pipeline] L1 attr sanitize failed: doc=%s err=%s", doc.get("_id", "?"), e)
        out["attr_norm"] = doc.get("attr") or []

    # ── L3：业务期对齐 ─────────────────────────────────────────────────────
    try:
        ps = L_periods.normalize_period(doc.get("period_start"), city)
        out["period_norm"] = ps
        out["canonical_period"] = ps["canonical"]
        norm_status["L3_periods"] = "ok"
    except Exception as e:
        norm_status["L3_periods"] = f"error: {e}"
        if strict:
            raise
        log.warning("[pipeline] L3 periods failed: doc=%s err=%s", doc.get("_id", "?"), e)
        out["period_norm"] = None
        out["canonical_period"] = doc.get("period_start")

    # ── L2：单位解析 ───────────────────────────────────────────────────────
    try:
        unit_info = L_units.parse_unit(doc.get("unit"))
        out["unit_norm"] = unit_info
        norm_status["L2_units_parse"] = "ok"
    except Exception as e:
        norm_status["L2_units_parse"] = f"error: {e}"
        if strict:
            raise
        log.warning("[pipeline] L2 units parse failed: doc=%s err=%s", doc.get("_id", "?"), e)
        out["unit_norm"] = {
            "raw": doc.get("unit", ""),
            "dim": None,
            "to_base": 1.0,
            "base": "",
            "normalized": doc.get("unit", ""),
        }

    # ── L2：价格归一（仅在提供 l3_code 时做） ─────────────────────────────
    if l3_code:
        try:
            from_unit = doc.get("unit", "")
            price = doc.get("price")
            if price is not None and from_unit:
                pn = L_units.normalize_price_to_l3(price, from_unit, l3_code)
                out["price_norm"] = pn
                norm_status["L2_price_normalize"] = "ok" if pn["converted"] else "skipped"
            else:
                out["price_norm"] = None
                norm_status["L2_price_normalize"] = "skipped"
        except Exception as e:
            norm_status["L2_price_normalize"] = f"error: {e}"
            if strict:
                raise
            log.warning("[pipeline] L2 price normalize failed: doc=%s err=%s", doc.get("_id", "?"), e)
            out["price_norm"] = None

    # ── L4：Phase C 占位 ──────────────────────────────────────────────────
    norm_status["L4_cross_city"] = "phase_c_pending"

    out["_norm"]["status"] = norm_status
    out["_norm"]["city"] = city
    out["_norm"]["l3_code"] = l3_code
    out["_norm"]["version"] = "0.2.0"
    return out


def normalize_batch(docs: list[dict], city: str, *, l3_code: Optional[str] = None, strict: bool = False) -> list[dict]:
    """批量标准化，每条 doc 独立处理（无状态）。"""
    return [normalize_doc(d, city, l3_code=l3_code, strict=strict) for d in docs]