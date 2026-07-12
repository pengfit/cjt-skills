"""paths.py - gov-price-etl 路径中心

所有文件路径都从这里出，避免散落在各模块的 os.path.join(__file__, ...) 拼凑。

布局（v0.7 — 2026-07-12 集中迁移 monorepo data/）：

    skills/                              # MONOREPO_ROOT (= PACKAGE_ROOT.parents[1])
    ├── data/                            # 统一数据目录（集中）
    │   ├── breed_canonical.db           # 归一法骨架（dashboard CATEGORY_DB 单一来源）
    │   ├── breed_spec_rules.db          # 规格解析规则（v0.7 起挪入此处）
    │   ├── category_v2_rules.db         # 分类体系 v2（已废弃保留）
    │   └── category_v3_rules.db         # 分类体系 v3（8 L1 / 42 L2 / 145 L3，当前主库）
    └── gov-price-etl/                   # ETL_PROJECT_ROOT
        ├── config.yml
        ├── gov_price_etl/               # PACKAGE_ROOT
        │   ├── paths.py                 # ← 本文件
        │   └── ...
        └── data/                        # 旧位置（v0.7 后只读保留,不再生效）

为什么集中：
    dashboard / etl / 其他子项目都用同一份 .db，避免多个副本。
    env 可显式覆盖：GOV_PRICE_ETL_DATA_DIR=/custom/path/data
"""
import os
from pathlib import Path

# gov_price_etl/paths.py → 上溯到 gov-price-etl/（ETL_PROJECT_ROOT）
PACKAGE_ROOT = Path(__file__).resolve().parent
ETL_PROJECT_ROOT = PACKAGE_ROOT.parent
# 上溯 1 层到 monorepo 根（skills/），让 DATA_DIR 默认 = skills/data
MONOREPO_ROOT = PACKAGE_ROOT.parents[1]

# BACK COMPAT：旧 etl 内部代码仍 `from gov_price_etl.paths import PROJECT_ROOT`
# v0.7 起语义统一指向 ETL_PROJECT_ROOT（旧义）。
PROJECT_ROOT = ETL_PROJECT_ROOT

# data 目录：env > MONOREPO_ROOT/data > ETL_PROJECT_ROOT/data（兜底老路径，仅警告）
_DEFAULT_DATA = MONOREPO_ROOT / "data"
DATA_DIR = Path(os.environ.get("GOV_PRICE_ETL_DATA_DIR", str(_DEFAULT_DATA)))

# config.yml / prompts.yml 仍在 etl 项目根（属 ETL 私有）
CONFIG_PATH = ETL_PROJECT_ROOT / "config.yml"
PROMPTS_YML = ETL_PROJECT_ROOT / "prompts.yml"

# 数据文件（集中到 DATA_DIR）
SPEC_RULES_DB = DATA_DIR / "breed_spec_rules.db"
CATEGORY_V2_RULES_DB = DATA_DIR / "category_v2_rules.db"   # 已废弃，保留供回滚
CATEGORY_V3_RULES_DB = DATA_DIR / "category_v3_rules.db"   # 当前主库

# 确保 data/ 存在
DATA_DIR.mkdir(parents=True, exist_ok=True)
