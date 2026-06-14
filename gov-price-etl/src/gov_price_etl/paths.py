"""paths.py - gov-price-etl 路径中心

所有文件路径都从这里出，避免散落在各模块的 os.path.join(__file__, ...) 拼凑。

布局：
    gov-price-etl/                        # PROJECT_ROOT
    ├── config.yml
    ├── data/
    │   ├── breed_spec_rules.db           # 规格解析规则
    │   ├── breed_category_rules.db       # 品种分类规则
    │   ├── category_in_system.json       # 分类体系映射
    │   └── ai_cache.db                   # AI 调用缓存
    └── src/gov_price_etl/                # PACKAGE_ROOT
        ├── paths.py                      # ← 本文件
        ├── ...
"""
from pathlib import Path

# src/gov_price_etl/paths.py → 上溯 2 层到 gov-price-etl/
PACKAGE_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_ROOT.parent.parent
DATA_DIR = PROJECT_ROOT / "data"
CONFIG_PATH = PROJECT_ROOT / "config.yml"

# 数据文件
SPEC_RULES_DB = DATA_DIR / "breed_spec_rules.db"
CATEGORY_RULES_DB = DATA_DIR / "breed_category_rules.db"
CATEGORY_IN_SYSTEM_JSON = DATA_DIR / "category_in_system.json"
AI_CACHE_DB = DATA_DIR / "ai_cache.db"

# 确保 data/ 存在（首次跑时 ai_cache.db 会在这里建）
DATA_DIR.mkdir(parents=True, exist_ok=True)
