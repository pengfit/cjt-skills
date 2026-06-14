"""parse_spec/henan.py - 河南专用规格解析

河南 PDF 规格模式大部分与通用 base.py 规则一致，
如后续出现河南特有规格（地市简称编码、双计量单位等），在此扩展。
"""
from .base import BaseParseSpec


class HenanParseSpec(BaseParseSpec):
    """河南规格解析器"""

    def _city_rules(self, s: str, result: dict) -> dict:
        """河南特有规则（暂走通用规则）"""
        return result
