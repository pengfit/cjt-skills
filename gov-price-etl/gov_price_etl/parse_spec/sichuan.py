"""parse_spec/sichuan.py - 四川专用规格解析"""
from .base import BaseParseSpec


class SichuanParseSpec(BaseParseSpec):
    """四川规格解析器"""

    def _city_rules(self, s: str, result: dict) -> dict:
        """四川特有规则（暂无）"""
        return result