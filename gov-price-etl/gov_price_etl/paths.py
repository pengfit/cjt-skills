"""paths.py - gov-price-etl 路径中心

所有文件路径都从这里出，避免散落在各模块的 os.path.join(__file__, ...) 拼凑。

布局：
    gov-price-etl/                        # PROJECT_ROOT
    ├── config.yml
    ├── data/
    │   ├── breed_spec_rules.db           # 规格解析规则
    │   ├── breed_category_rules.db       # 品种分类规则（v1）
    │   └── category_v2_rules.db          # 分类体系 v2（4 级 L1-L4 + breed→L3 映射）
    └── src/gov_price_etl/                # PACKAGE_ROOT
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
# CATEGORY_RULES_DB 已废 (2026-06-16)：
#   - v1 大分类 AI 入口（classify_breed_batch）已删除
#   - breed_category_rules.db 静态规则（616 条）已清除
#   - DWD.category 字段值改为 v2 L1 中文名（如"建筑工程"）
#   - spec 规则库已迁到 v2 L1 名（data/v1_to_v2_l1_name.json 记录映射）
CATEGORY_V2_RULES_DB = DATA_DIR / "category_v2_rules.db"

# AI Prompt 模板（可手动编辑 + 热重载）
PROMPTS_YML = PROJECT_ROOT / "prompts.yml"

# 确保 data/ 存在
DATA_DIR.mkdir(parents=True, exist_ok=True)
