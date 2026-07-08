#!/usr/bin/env python3
"""normalize_one.py — 单文档标准化命令行工具

用法：
    # 用 JSON 字面量
    python -m cli.normalize_one '{"breed":"散装水泥","unit":"t","price":350,"period_start":"2026-02-15"}' --city hainan --l3 01.05.07

    # 从 stdin 读 JSON（一行一个 doc）
    echo '{"breed":"钢筋","unit":"kg","price":4.2,"period_start":"2026-02"}' | python -m cli.normalize_one --city xian --l3 01.01.01
"""
from __future__ import annotations
import sys
import json
import argparse
from pathlib import Path

# 让脚本能 import gov_price_normalization（无论 cwd 在哪）
_HERE = Path(__file__).resolve().parent
_PKG = _HERE.parent
if str(_PKG) not in sys.path:
    sys.path.insert(0, str(_PKG))

from gov_price_normalization import normalize_doc  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description="单文档标准化（L2+L3 Phase A）")
    ap.add_argument("doc", nargs="?", help="JSON 文档字符串（缺省读 stdin）")
    ap.add_argument("--city", required=True, help="城市 key，如 hainan / xian / qingdao")
    ap.add_argument("--l3", default=None, help="v3 L3 码（提供则做价格归一）")
    ap.add_argument("--strict", action="store_true", help="任一层失败抛异常（默认降级）")
    args = ap.parse_args()

    if args.doc:
        doc = json.loads(args.doc)
    else:
        line = sys.stdin.readline().strip()
        if not line:
            print("ERROR: 空 stdin", file=sys.stderr)
            sys.exit(1)
        doc = json.loads(line)

    result = normalize_doc(doc, args.city, l3_code=args.l3, strict=args.strict)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()