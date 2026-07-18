"""api/paths.py - dashboard 端所有路径的单一来源

设计原则：
- 只暴露 1 个 env var：SKILLS_ROOT
- 其他路径全部从 SKILLS_ROOT 推导
- 与 gov-price-etl/paths.py 风格一致，便于后期合并

环境变量：
- SKILLS_ROOT：dashboard 用的 skills 根目录
  - 本地默认：~/.openclaw/workspace/cjt/skills
  - 容器内：/app/skills（Dockerfile 已 COPY skills/ 整个目录）
"""
from __future__ import annotations

import os
from pathlib import Path

# 单一 env var：skills 根目录
SKILLS_ROOT: Path = Path(
    os.environ.get(
        "SKILLS_ROOT",
        "/Users/pengfit/.openclaw/workspace/cjt/skills",
    )
).expanduser().resolve()

# data 子目录（所有共享 db / json 都在这里）
DATA_DIR: Path = SKILLS_ROOT / "data"

# ============================ SQLite 数据库 ============================
# breed_canonical.db 同时含 breed_canonical 主表 + category_v3 分类骨架表
# 简称 CATEGORY_DB（dashboard 主要用来查分类），但文件实际名是 breed_canonical.db
CATEGORY_DB: Path = DATA_DIR / "breed_canonical.db"

# 规格解析规则库（前端 /api/stats/spec-quality 查这个）
BREED_SPEC_RULES_DB: Path = DATA_DIR / "breed_spec_rules.db"

# ============================ ETL 项目根 ============================
# provenance.py 需要从 ETL 源码 import 模块（paths.py / service.py 等）
GOV_PRICE_ETL_ROOT: Path = SKILLS_ROOT / "gov-price-etl"


__all__ = [
    "SKILLS_ROOT",
    "DATA_DIR",
    "CATEGORY_DB",
    "BREED_SPEC_RULES_DB",
    "GOV_PRICE_ETL_ROOT",
]