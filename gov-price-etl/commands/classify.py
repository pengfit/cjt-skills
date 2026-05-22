"""classify.py - gov-price 数据品种分类引擎

规则优先级:
1. BREED_CAT_MAP (品种→分类精确映射)
2. KEYWORD_RULES (关键词→分类)
3. SPEC_HINT_RULES (规格模式→分类辅助, breed≤5时触发)
4. 兜底 → 其他
"""

try:
    from .rules import (
        BREED_CAT_MAP, KEYWORD_RULES, SPEC_HINT_RULES, CLASSIFICATIONS,
    )
except ImportError:
    from rules import (
        BREED_CAT_MAP, KEYWORD_RULES, SPEC_HINT_RULES, CLASSIFICATIONS,
    )


def classify_breed(breed: str, spec: str = "") -> str:
    """根据品种名和规格返回分类"""
    if not breed:
        return "其他"

    # 1. BREED_CAT_MAP 精确匹配（部分匹配）
    breed_val = breed.strip()
    for bm_breed, cat in BREED_CAT_MAP.items():
        if bm_breed in breed_val or breed_val in bm_breed:
            return cat

    # 2. KEYWORD_RULES 关键词匹配
    for kw, cat in KEYWORD_RULES:
        if kw in breed_val:
            return cat

    # 3. 短 breed 规格辅助推断 (breed ≤ 5 字符)
    if len(breed_val) <= 5 and spec:
        spec_lower = spec.lower()
        for hint_kw, cat in SPEC_HINT_RULES:
            if hint_kw in spec_lower:
                return cat

    # 4. 兜底
    return "其他"


def get_all_categories() -> list:
    return sorted(CLASSIFICATIONS)


# ─── 分类 ID 常量 (供 ETL 输出用) ────────────────────────────────────────────────
CAT_ID_MAP = {name: idx + 1 for idx, name in enumerate(sorted(CLASSIFICATIONS))}


if __name__ == "__main__":
    import sys
    breed = sys.argv[1] if len(sys.argv) > 1 else ""
    spec = sys.argv[2] if len(sys.argv) > 2 else ""
    print(f"品种: {breed} | 规格: {spec} → 分类: {classify_breed(breed, spec)}")