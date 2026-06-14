#!/usr/bin/env python3
"""cli/reload_prompts - 重读 prompts.yml

用途：
  - 调试：调完 prompt 后想让 ETL 立即生效（不需要重启）
  - 验证 yml 语法是否正确

用法：
  ./cli/reload_prompts.py
  ./cli/reload_prompts.py --show  # 顺手显示当前加载的所有 prompt
"""
import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from gov_price_etl.ai.prompts import (  # noqa: E402
    get_prompt,
    get_prompts,
    reload_prompts,
)
from gov_price_etl.paths import PROMPTS_YML  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="重读 prompts.yml")
    parser.add_argument("--show", action="store_true", help="顺手显示当前所有 prompt 概览")
    args = parser.parse_args()

    print(f"[prompts] 文件: {PROMPTS_YML}")
    print(f"[prompts] 重读中...")
    data = reload_prompts()
    keys = list(data.keys())
    print(f"[prompts] ✓ 已加载 {len(keys)} 个 prompt: {', '.join(keys) if keys else '(无)'}")

    if args.show:
        print()
        for k, v in data.items():
            sys_msg = v.get("system", "")
            tmpl = v.get("template", "")
            print(f"─── {k} ───")
            print(f"  system   ({len(sys_msg)} chars): {sys_msg[:80]}{'...' if len(sys_msg) > 80 else ''}")
            print(f"  template ({len(tmpl)} chars): {tmpl[:80]}{'...' if len(tmpl) > 80 else ''}")
            print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
