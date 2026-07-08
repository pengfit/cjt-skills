"""L4 跨城映射层（占位 / Phase C 扩展）

未来要做的：
- canonical_breed → [(city, raw_breed), ...] 反向索引
- canonical_spec_key → 跨城公共 attr_pair 配对

Phase A 暂返回空 dict 或 NotImplemented。
"""
from __future__ import annotations
from typing import Optional


def expand_to_cities(canonical_breed: str, cities: list[str]) -> dict:
    """[Phase C] 把 canonical_breed 展开到各城市的 raw_breed。

    Phase A 暂返回 {}。
    """
    raise NotImplementedError(
        "[L4 cross_city] expand_to_cities 将在 Phase C 实现，依赖 breed_canonical.json。"
    )


def align_spec_across_cities(spec_attrs: dict, cities: list[str]) -> dict:
    """[Phase C] 跨城 spec_key 对齐。

    Phase A 暂返回 {}。
    """
    raise NotImplementedError(
        "[L4 cross_city] align_spec_across_cities 将在 Phase C 实现。"
    )