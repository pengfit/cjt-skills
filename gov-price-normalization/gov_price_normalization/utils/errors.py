"""自定义异常族——所有 NormalizationLayer 抛错都从这里出。

设计原则：
- 不同错误类型对应不同的"是否可降级"语义（见 handle_or_warn 装饰器）
- 异常带 city / field / raw 三元组，方便上层日志定位
"""

from __future__ import annotations
from typing import Optional, Any


class NormalizationError(Exception):
    """所有 NormalizationLayer 异常的基类"""
    layer: str = "unknown"

    def __init__(self, message: str, *, raw: Any = None, city: Optional[str] = None, field: Optional[str] = None):
        super().__init__(message)
        self.raw = raw
        self.city = city
        self.field = field

    def __str__(self):
        bits = [super().__str__()]
        if self.city:
            bits.append(f"city={self.city}")
        if self.field:
            bits.append(f"field={self.field}")
        if self.raw is not None:
            bits.append(f"raw={self.raw!r}")
        return " | ".join(bits)


class UnknownUnitError(NormalizationError):
    """未知单位——units.py 抛出"""
    layer = "units"


class DimensionMismatchError(NormalizationError):
    """量纲不匹配——尝试 kg → m 之类"""
    layer = "units"


class UnknownCityError(NormalizationError):
    """未知城市——period_rules 没登记"""
    layer = "periods"


class UnparseablePeriodError(NormalizationError):
    """period_start 字符串无法解析"""
    layer = "periods"


class UnknownBreedError(NormalizationError):
    """品种无法归一到 canonical——L1 抛"""
    layer = "fields"


class UnknownAttrKeyError(NormalizationError):
    """attr_key 无法归一到 canonical"""
    layer = "fields"