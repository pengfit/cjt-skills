"""classify.py - gov-price 品种分类引擎（rules/ 动态加载版）"""

from .rules._core import classify_breed, _fetch_ai_category_batch, _ai_cache

__all__ = ["classify_breed", "_fetch_ai_category_batch", "_ai_cache"]

if __name__ == "__main__":
    import sys
    breed = sys.argv[1] if len(sys.argv) > 1 else ""
    spec = sys.argv[2] if len(sys.argv) > 2 else ""
    cat, conf = classify_breed(breed, spec)
    print(f"品种: {breed} | 规格: {spec} → 分类: {cat} (置信度: {conf:.2f})")