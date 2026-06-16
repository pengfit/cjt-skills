"""classify - gov-price 品种分类引擎（v2 唯一）

v1 大分类（classify_breed / breed_category_rules.db）已废（2026-06-16）。
全部分类由 v2 4 层分类接管：

  - classify_v2(breed, spec, unit, breed_clean)       单条 5 段式
  - classify_v2_batch(items, write_rules)              批量 AI 攒批入口
  - batch_insert_breed_l3_map / insert_breed_l3_map    写 v2 breed_l3_map 表

数据源：
  - data/category_v2_rules.db（v2 主分类库）
    - category_v2 表（4 级分类节点 64 行）
    - breed_l3_map 表（品种→L3 映射 4073 行）

文件结构：
  - category_v2.py  主入口（5 段式 + 批量 AI）
"""
from .category_v2 import (
    classify_v2,
    classify_v2_batch,
    close_singleton,
)

__all__ = [
    # v2 唯一分类入口
    "classify_v2",
    "classify_v2_batch",
    "close_singleton",
]

if __name__ == "__main__":
    # v1 兼容接口已删除
    import sys
    print("classify v1 已废弃（2026-06-16）。请使用 classify_v2 / classify_v2_batch。", file=sys.stderr)
    sys.exit(1)
