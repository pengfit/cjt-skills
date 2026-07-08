"""gov_price_normalization — 政府材料价格数据标准化层

定位：
- 不依赖 ETL、不依赖 ES、不依赖 dashboard
- 提供 L1 (fields) / L2 (units) / L3 (periods) / L4 (cross_city) 四层纯函数
- 各层可独立调用，也可通过 pipeline.normalize_doc() 组合

入口：
- normalize_doc(doc, city, l3_code=None) → 标准化单条 DWS 文档
- normalize_batch(docs, city, l3_code=None) → 批量
- layers.units / layers.periods / layers.fields / layers.cross_city 单独 import

版本：
- v0.1.0 (2026-07-08, Phase A)
  - L2 units: 完整（kg/t, mm/m, m², m³, piece 类）
  - L3 periods: 完整（monthly / quarterly / bimonthly / irregular）
  - L1 fields: 占位（Phase B）
  - L4 cross_city: 占位（Phase C）
"""
from .pipeline import normalize_doc, normalize_batch
from . import layers
from .layers import units, periods, fields, cross_city
from .utils import data_loader, errors

__all__ = [
    "normalize_doc",
    "normalize_batch",
    "layers",
    "units",
    "periods",
    "fields",
    "cross_city",
    "data_loader",
    "errors",
]

__version__ = "0.1.0"