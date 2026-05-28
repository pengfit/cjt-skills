"""classify.py - gov-price 品种分类引擎（rules/ 动态加载版）"""

try:
    from .rules._core import classify_breed
except ImportError:
    from classify.rules._core import classify_breed


if __name__ == "__main__":
    import sys
    breed = sys.argv[1] if len(sys.argv) > 1 else ""
    spec = sys.argv[2] if len(sys.argv) > 2 else ""
    print(f"品种: {breed} | 规格: {spec} → 分类: {classify_breed(breed, spec)}")