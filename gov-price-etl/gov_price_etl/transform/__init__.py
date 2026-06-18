"""transform - 数据清洗与归一化

子模块：
  - clean.py        品种/规格/单位/价格清洗
  - doc.py          transform_doc() 单文档 ODS → DWD
  - attr_utils.py   attr 字段提取 / 扁平↔nested 转换

公开 API：
  from gov_price_etl.transform import (
      transform_doc,
      clean_breed, clean_unit, clean_price,
      build_attr, flat_attr_to_nested,
  )
"""
from .clean import clean_breed, clean_unit, clean_price
from .doc import transform_doc
from .attr_utils import build_attr, flat_attr_to_nested

__all__ = [
    "transform_doc",
    "clean_breed", "clean_unit", "clean_price",
    "build_attr", "flat_attr_to_nested",
]
