"""pipeline.py — 把 L1/L2/L3/L4 组合成 normalize_doc()

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
# L1 / L4 Phase B/C 才实现，先不 import（避免触发 NotImplementedError）

log = logging.getLogger(__name__)


def normalize_doc(doc: dict, city: str, *, l3_code: Optional[str] = None, strict: bool = False) -> dict:
    """对单条 DWS 原始文档做标准化。

    Args:
        doc: DWS 原始 doc，至少包含 breed / period_start / unit / price，可选 attr
        city: 城市 key
        l3_code: v3 三级分类码（如 '01.05.07'）。提供后会做价格归一。
                不提供 → 仅做单位解析，不归一
        strict: True 时任一层失败抛异常；False（默认）降级 + 记 status

    Returns:
        新字典（不修改入参），含原字段 + 所有 *_norm 字段 + 各层 status
    """
    out = dict(doc)
    out.setdefault("_norm", {})
    norm_status = {}

    # ── L3：业务期对齐 ──
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
        out["canonical_period"] = doc.get("period_start")  # 降级用原值

    # ── L2：单位解析 ──
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

    # ── L2：价格归一（仅在提供 l3_code 时做） ──
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

    # ── L1 / L4：Phase B/C 实现后再加 ──
    norm_status["L1_fields"] = "phase_b_pending"
    norm_status["L4_cross_city"] = "phase_c_pending"

    out["_norm"]["status"] = norm_status
    out["_norm"]["city"] = city
    out["_norm"]["l3_code"] = l3_code
    out["_norm"]["version"] = "0.1.0"
    return out


def normalize_batch(docs: list[dict], city: str, *, l3_code: Optional[str] = None, strict: bool = False) -> list[dict]:
    """批量标准化，每条 doc 独立处理（无状态）。"""
    return [normalize_doc(d, city, l3_code=l3_code, strict=strict) for d in docs]