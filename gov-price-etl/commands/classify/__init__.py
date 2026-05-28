"""classify.py - gov-price 品种分类引擎（rules/ 动态加载版）"""

from .rules._core import classify_breed, get_all_categories, CAT_ID_MAP, CLASSIFICATIONS, _fetch_ai_category_batch, _query_breed_rules_db

__all__ = ["classify_breed", "get_all_categories", "CAT_ID_MAP", "CLASSIFICATIONS", "_fetch_ai_category_batch", "_query_breed_rules_db"]

if __name__ == "__main__":
    import sys
    breed = sys.argv[1] if len(sys.argv) > 1 else ""
    spec = sys.argv[2] if len(sys.argv) > 2 else ""
    print(f"品种: {breed} | 规格: {spec} → 分类: {classify_breed(breed, spec)}")