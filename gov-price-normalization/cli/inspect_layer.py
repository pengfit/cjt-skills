#!/usr/bin/env python3
"""inspect_layer.py — 单独跑某一层的输出（用于调试）

用法：
    # L2 units parse
    python -m cli.inspect_layer units --unit "kg"
    python -m cli.inspect_layer units convert --from t --to kg --value 1

    # L2 price normalize
    python -m cli.inspect_layer units price-normalize --from t --to-l3 01.01.01 --value 3500

    # L3 periods normalize
    python -m cli.inspect_layer periods --city weihai --period-start "2026-Q1"
    python -m cli.inspect_layer periods --city qingdao --period-start "2026年02月"

    # 数据表元信息
    python -m cli.inspect_layer meta
"""
from __future__ import annotations
import sys
import json
import argparse
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_PKG = _HERE.parent
if str(_PKG) not in sys.path:
    sys.path.insert(0, str(_PKG))

from gov_price_normalization.layers import units, periods  # noqa: E402
from gov_price_normalization.utils import data_loader  # noqa: E402


def cmd_units_parse(args):
    info = units.parse_unit(args.unit)
    print(json.dumps(info, ensure_ascii=False, indent=2))


def cmd_units_convert(args):
    out = units.convert_value(args.value, args.frm, args.to)
    print(json.dumps({"from": args.frm, "to": args.to, "value": args.value, "result": out}, ensure_ascii=False, indent=2))


def cmd_units_price(args):
    out = units.normalize_price_to_l3(args.value, args.frm, args.l3)
    print(json.dumps({"l3": args.l3, "from_unit": args.frm, "value": args.value, **out}, ensure_ascii=False, indent=2))


def cmd_periods(args):
    out = periods.normalize_period(args.period_start, args.city)
    print(json.dumps(out, ensure_ascii=False, indent=2))


def cmd_meta(args):
    print("=== unit_conversion.json ===")
    print(json.dumps(data_loader.get_meta("unit_conversion.json"), ensure_ascii=False, indent=2))
    print("\n=== period_rules.json ===")
    print(json.dumps(data_loader.get_meta("period_rules.json"), ensure_ascii=False, indent=2))
    print("\n=== data_dir ===")
    print(str(data_loader.data_dir()))


def main():
    ap = argparse.ArgumentParser(description="单独跑某一层的输出")
    sub = ap.add_subparsers(dest="layer", required=True)

    # units
    u = sub.add_parser("units", help="L2 units 层")
    usub = u.add_subparsers(dest="action", required=True)
    p = usub.add_parser("parse", help="解析单位字符串")
    p.add_argument("--unit", required=True)
    p.set_defaults(func=cmd_units_parse)
    c = usub.add_parser("convert", help="数值换算")
    c.add_argument("--value", type=float, required=True)
    c.add_argument("--from", dest="frm", required=True)
    c.add_argument("--to", required=True)
    c.set_defaults(func=cmd_units_convert)
    pn = usub.add_parser("price-normalize", help="按 L3 default_unit 归一价格")
    pn.add_argument("--value", type=float, required=True)
    pn.add_argument("--from", dest="frm", required=True)
    pn.add_argument("--to-l3", dest="l3", required=True)
    pn.set_defaults(func=cmd_units_price)

    # periods
    pe = sub.add_parser("periods", help="L3 periods 层")
    pe.add_argument("--city", required=True)
    pe.add_argument("--period-start", required=True, dest="period_start")
    pe.set_defaults(func=cmd_periods)

    # meta
    m = sub.add_parser("meta", help="看数据表元信息")
    m.set_defaults(func=cmd_meta)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()