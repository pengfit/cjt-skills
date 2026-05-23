# classify/rules/_core.py - 核心分类函数（动态加载规则，不硬编码）
import os, re

try:
    from . import CLASSIFICATIONS, get_rules, RULES_DIR
except ImportError:
    from classify.rules import CLASSIFICATIONS, get_rules, RULES_DIR

# 缓存
_cache = {}


def _load_cache():
    if _cache:
        return
    _cache['breed_cat_map'] = {}   # breed片段 → 分类
    _cache['keyword_rules'] = []    # (关键词, 分类)
    _cache['spec_hint'] = []        # (规格关键词, 分类)

    for rule in get_rules():
        cat = rule['category']
        kw = rule['keyword']
        if rule['file'] == 'breed.py':
            _cache['breed_cat_map'][kw] = cat
        elif rule['file'] == 'keyword.py':
            _cache['keyword_rules'].append((kw, cat))
        elif rule['file'] == 'species.py':
            _cache['spec_hint'].append((kw, cat))


def classify_breed(breed: str, spec: str = "") -> str:
    """根据品种名和规格返回分类"""
    if not breed:
        return "其他"

    _load_cache()

    breed_val = breed.strip()

    # 1. BREED_CAT_MAP 精确匹配（部分匹配）
    for bm_breed, cat in _cache['breed_cat_map'].items():
        if bm_breed in breed_val or breed_val in bm_breed:
            return cat

    # 2. KEYWORD_RULES 关键词匹配
    for kw, cat in _cache['keyword_rules']:
        if kw in breed_val:
            return cat

    # 3. 短 breed 规格辅助推断 (breed ≤ 5 字符)
    if len(breed_val) <= 5 and spec:
        spec_lower = spec.lower()
        for hint_kw, cat in _cache['spec_hint']:
            if hint_kw in spec_lower:
                return cat

    return "其他"


def get_all_categories() -> list:
    return sorted(CLASSIFICATIONS)


CAT_ID_MAP = {name: idx + 1 for idx, name in enumerate(sorted(CLASSIFICATIONS))}


if __name__ == "__main__":
    import sys
    breed = sys.argv[1] if len(sys.argv) > 1 else ""
    spec = sys.argv[2] if len(sys.argv) > 2 else ""
    print(f"品种: {breed} | 规格: {spec} → 分类: {classify_breed(breed, spec)}")