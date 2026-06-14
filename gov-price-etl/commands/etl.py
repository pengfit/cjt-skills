#!/usr/bin/env python3
"""commands/etl.py - 向后兼容 shim

⚠️ 已废弃：此入口已迁移到 cli/etl。
原 etl.py (1107 行) 已拆分为 gov_price_etl 包。

迁移：
  python3 commands/etl.py ...  →  ./cli/etl ...
"""
import sys
import warnings
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

warnings.warn(
    "commands/etl.py 已废弃，请使用 cli/etl.py。",
    DeprecationWarning,
    stacklevel=2,
)

# 转发到 cli/etl
sys.argv[0] = str(PROJECT_ROOT / "cli" / "etl")
sys.path.insert(0, str(PROJECT_ROOT))  # 让 `import cli` 找得到
sys.path.insert(0, str(PROJECT_ROOT))  # 让 `import gov_price_etl` 找得到
from cli.etl import main  # noqa: E402
sys.exit(main())
