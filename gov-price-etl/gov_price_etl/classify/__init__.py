"""classify - gov-price 品种分类引擎（v3 主，v2 备份）

v1 大分类（classify_breed / breed_category_rules.db）已废（2026-06-16）。
全部分类由 v3 4 层分类接管（2026-06-18 起，v2 保留向后兼容）：

  - classify_v3(breed, spec, unit, breed_clean)       单条 5 段式
  - classify_v3_batch(items, write_rules)              批量 AI 攒批入口
  - batch_insert_breed_l3_map / insert_breed_l3_map    写 v3 breed_l3_map_v3 表

数据源：
  - data/category_v3_rules.db（v3 主分类库）
    - category_v3 表（4 级分类节点 145 行，按 GB 50854/50856/50857/50858 章节）
    - breed_l3_map_v3 表（品种→L3 映射）
  - data/category_v2_rules.db（v2 备份，已废弃，保留回滚用）

文件结构：
  - category_v3.py  v3 主入口（5 段式 + 批量 AI）
  - category_v2.py  v2 旧实现（保留回滚）
"""
from .category_v3 import (
    classify_v3,
    classify_v3_batch,
    close_singleton,
)

__all__ = [
    # v3 唯一分类入口
    "classify_v3",
    "classify_v3_batch",
    "close_singleton",
]
