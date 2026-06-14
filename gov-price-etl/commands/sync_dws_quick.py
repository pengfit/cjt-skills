#!/usr/bin/env python3
"""commands/sync_dws_quick.py - 向后兼容 shim

⚠️ 已废弃：此入口已迁移到 cli/sync_dws。
旧 sync_dws_quick.py 行为对应 cli/sync_dws --mode quick。

迁移：
  python3 commands/sync_dws_quick.py ...  →  ./cli/sync_dws --mode quick ...
"""
import sys
import warnings
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

warnings.warn(
    "commands/sync_dws_quick.py 已废弃，请使用 cli/sync_dws --mode quick。",
    DeprecationWarning,
    stacklevel=2,
)

# 强制 mode=quick
sys.argv = [sys.argv[0]] + ["--mode", "quick"] + [a for a in sys.argv[1:] if a not in ("--mode", "quick")]
sys.path.insert(0, str(PROJECT_ROOT))  # 让 `import cli` 找得到
sys.path.insert(0, str(PROJECT_ROOT))  # 让 `import gov_price_etl` 找得到
from cli.sync_dws import main  # noqa: E402
sys.exit(main())
