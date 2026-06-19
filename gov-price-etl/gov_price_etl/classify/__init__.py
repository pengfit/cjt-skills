"""classify - gov-price 品种分类引擎（v3 主）

v1 大分类（classify_breed / breed_category_rules.db）已废（2026-06-16）。
全部分类由 v3 2 段式接管（2026-06-19 起）：

  - classify_v3(breed, spec, unit, breed_clean)       单条 2 段式（db_exact → db_fuzzy）

数据源：
  - data/category_v3_rules.db（v3 主分类库）
    - category_v3 表（4 级分类节点 161 行，按 GB 50854/50856/50857/50858 章节）
    - breed_l3_map_v3 表（品种→L3 映射，confidence >= 0.9 有效）
"""
from .category_v3 import (
    classify_v3,
    close_singleton,
)

__all__ = [
    # v3 唯一分类入口
    "classify_v3",
    "close_singleton",
]
