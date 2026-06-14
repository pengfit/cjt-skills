"""classify - gov-price 品种分类引擎

breed → category 三级召回：
  1. Jaccard 相似度（精确包含 + 加权 + char-bigram，阈值 0.45）
  2. DB breed_category_rules 精确查表
  3. 未命中 → "其他"（由 etl.py 单独发起 AI 批量分类）

数据源：
  - data/breed_category_rules.db（SQLite，规则唯一来源）
  - data/category_in_system.json（分类体系 code/name 映射）
"""
from .rules._core import (
    # 兼容旧接口
    classify_breed,
    _fetch_ai_category_batch,
    _ai_cache,
    # 三段式显式 API
    classify_breed_db_exact,      # 阶段 1: DB 精确
    classify_breed_db_fuzzy,      # 阶段 2: DB 模糊 / Jaccard
    classify_breed_local,         # 阶段 1+2: 本地规则库
    classify_breed_ai,            # 阶段 3: AI 串行
    classify_breed_with_stages,   # 三段合并（pipeline 编排用）
)
from .rules.jaccard import (
    jaccard_breed_classify,
    insert_breed_rule,
    batch_insert_breed_rules,
)
from .system import (
    _get_category_system_maps,
    get_category_system_map,
    get_category_system_name_map,
)

# 兼容老代码的 import 路径
_get_category_system_map = get_category_system_map
_get_category_system_name_map = get_category_system_name_map

__all__ = [
    # 兼容旧接口
    "classify_breed",
    "_fetch_ai_category_batch",
    "_ai_cache",
    # 三段式显式 API
    "classify_breed_db_exact",
    "classify_breed_db_fuzzy",
    "classify_breed_local",
    "classify_breed_ai",
    "classify_breed_with_stages",
    # jaccard 召回引擎
    "jaccard_breed_classify",
    "insert_breed_rule",
    "batch_insert_breed_rules",
    # 分类体系映射
    "get_category_system_map",
    "get_category_system_name_map",
    "_get_category_system_maps",
    "_get_category_system_map",
    "_get_category_system_name_map",
]

if __name__ == "__main__":
    import sys
    breed = sys.argv[1] if len(sys.argv) > 1 else ""
    spec = sys.argv[2] if len(sys.argv) > 2 else ""
    city = sys.argv[3] if len(sys.argv) > 3 else "xian"
    print(f"品种: {breed} | 规格: {spec} → 分类: {classify_breed(breed, spec, city)}")
