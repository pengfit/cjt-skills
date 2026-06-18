"""paths.py - gov-price-etl 路径中心

所有文件路径都从这里出，避免散落在各模块的 os.path.join(__file__, ...) 拼凑。

布局：
    gov-price-etl/                        # PROJECT_ROOT
    ├── config.yml
    ├── data/
    │   ├── breed_spec_rules.db           # 规格解析规则
    │   ├── category_v2_rules.db          # 分类体系 v2（8 L1 / 30 L2 / 69 L3，已废弃保留）
    │   └── category_v3_rules.db          # 分类体系 v3（8 L1 / 42 L2 / 145 L3，按 GB 章节重建，当前主库）
    └── gov_price_etl/                    # PACKAGE_ROOT
        ├── paths.py                      # ← 本文件
        ├── ...
"""
from pathlib import Path

# gov_price_etl/paths.py → 上溯 1 层到 gov-price-etl/
PACKAGE_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_ROOT.parent
DATA_DIR = PROJECT_ROOT / "data"
CONFIG_PATH = PROJECT_ROOT / "config.yml"

# 数据文件
SPEC_RULES_DB = DATA_DIR / "breed_spec_rules.db"
CATEGORY_V2_RULES_DB = DATA_DIR / "category_v2_rules.db"   # 已废弃，保留供回滚
CATEGORY_V3_RULES_DB = DATA_DIR / "category_v3_rules.db"   # 当前主库

# AI Prompt 模板（可手动编辑 + 热重载）
PROMPTS_YML = PROJECT_ROOT / "prompts.yml"

# 确保 data/ 存在
DATA_DIR.mkdir(parents=True, exist_ok=True)
