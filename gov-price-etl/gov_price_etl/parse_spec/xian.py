"""parse_spec/xian.py - 西安专用规格解析

在 BaseParseSpec 基础上扩展西安特有的解析规则。
目前西安规则已在 base.py 通用规则中覆盖（H=0.36m、δ=、W*(H1+H2) 等），
如后续有西安特有的规格模式，在此添加。
"""
from .base import BaseParseSpec


class XianParseSpec(BaseParseSpec):
    """西安规格解析器"""

    def _city_rules(self, s: str, result: dict) -> dict:
        """西安特有规则（目前已移至 base.py 通用规则）"""
        return result