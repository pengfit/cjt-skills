"""classify - gov-price 品种分类引擎

v1 仅保留 DB 查表路径（无 AI）；大分类任务全部交给 v2 4 层分类。

  v1: classify_breed_local(breed) → (category, source)
      - 阶段 1: DB 精确查表
      - 阶段 2: Jaccard 模糊召回
      - 未命中 → "其他"

  v2: classify/category_v2.py → classify_v2_batch(items)
      - 5 段式: db_exact_v2 → db_fuzzy_v2 → pattern_v2 → ai_v2 → unit_fallback
      - 输出 14 字段（l1/l2/l3/l4 + 标准码 + 工程属性 + 物料码）

数据源：
  - data/breed_category_rules.db（v1 静态查表，保留 spec 规则库兼容性）
  - data/category_v2_rules.db（v2 主分类库）
"""
from .rules._core import (
    # v1 兼容接口
    classify_breed,
    # v1 显式 API
    classify_breed_db_exact,      # 阶段 1: DB 精确
    classify_breed_db_fuzzy,      # 阶段 2: DB 模糊 / Jaccard
    classify_breed_local,         # 阶段 1+2: 本地规则库
)
from .rules.jaccard import (
    jaccard_breed_classify,
    insert_breed_rule,
    batch_insert_breed_rules,
)

__all__ = [
    # v1 兼容接口
    "classify_breed",
    # v1 显式 API
    "classify_breed_db_exact",
    "classify_breed_db_fuzzy",
    "classify_breed_local",
    # jaccard 召回引擎
    "jaccard_breed_classify",
    "insert_breed_rule",
    "batch_insert_breed_rules",
]

if __name__ == "__main__":
    import sys
    breed = sys.argv[1] if len(sys.argv) > 1 else ""
    spec = sys.argv[2] if len(sys.argv) > 2 else ""
    city = sys.argv[3] if len(sys.argv) > 3 else "xian"
    print(f"品种: {breed} | 规格: {spec} → 分类: {classify_breed(breed, spec, city)}")
