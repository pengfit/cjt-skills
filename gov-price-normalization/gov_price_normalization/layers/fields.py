"""L1 字段标准化层（占位 / Phase B 扩展）

未来要做的：
- breed → canonical_breed + l3_code（依赖 breed_category_rules + v3 taxonomy）
- attr.k → canonical_attr_key（依赖 attr_canonical.json）
- attr.v → 归一（DN50 / DN 50 / Φ50 → DN-50）

Phase A（当前版本）：仅提供接口签名 + NotImplementedError。
这样 pipeline.py 能保持稳定的 normalize_doc() 形状，Phase B 实现时直接替换。
"""
from __future__ import annotations
from typing import Optional


def normalize_breed(raw: str, city: str) -> dict:
    """[Phase B] 品种名 → canonical + l3_code。

    Phase A 暂返回 raw 原值，便于上层先跑通流程。

    Returns:
        {'raw': str, 'canonical': str, 'l3_code': Optional[str], 'l3_name': Optional[str],
         'confidence': float, 'source': str}
    """
    raise NotImplementedError(
        "[L1 fields] normalize_breed 将在 Phase B 实现，依赖 v3 taxonomy + breed_category_rules。"
        "Phase A 直接用原始 breed 字段。"
    )


def normalize_attr_k(k: str) -> str:
    """[Phase B] attr.k → canonical_attr_key（如 DN → nominal_diameter）。

    Phase A 暂返回原值。
    """
    raise NotImplementedError(
        "[L1 fields] normalize_attr_k 将在 Phase B 实现，依赖 attr_canonical.json。"
    )


def normalize_attr_v(k_canonical: str, v: str) -> str:
    """[Phase B] attr.v 归一（如 DN50 / DN 50 / Φ50 → DN-50）。"""
    raise NotImplementedError(
        "[L1 fields] normalize_attr_v 将在 Phase B 实现。"
    )