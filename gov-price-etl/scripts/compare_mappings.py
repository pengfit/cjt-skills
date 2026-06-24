#!/usr/bin/env python3
"""对比 mappings.py 声明 vs 实际 ES 索引 mapping 的差异

输出三类差异：
1. 声明有但 ES 缺：mappings.py 定义了，但 ES 索引没这个字段
2. ES 有但声明没：ES 实际有，但 mappings.py 没声明（多半是 dynamic 推断的脏字段）
3. 类型不一致：两边都有，但 type 不一样

用法：
    python3 scripts/compare_mappings.py            # 全部 dwd_*/dws_*
    python3 scripts/compare_mappings.py dwd         # 只 dwd
    python3 scripts/compare_mappings.py dws         # 只 dws
    python3 scripts/compare_mappings.py dws --city xian   # 只看 xian
"""
import sys
import os
import json
import urllib.request
from collections import OrderedDict

# 让脚本能从仓库根目录 import mappings
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "gov_price_etl"))

from mappings import build_dwd_mapping, build_dws_mapping  # noqa: E402

ES_HOST = "http://localhost:59200"


def fetch_es_mapping(index: str) -> dict:
    """拉 ES 索引的 mapping，剥到 properties 层"""
    url = f"{ES_HOST}/{index}/_mapping"
    with urllib.request.urlopen(url) as r:
        data = json.load(r)
    if index not in data:
        return {}
    return data[index].get("mappings", {}).get("properties", {})


def list_indices(prefix: str) -> list:
    """列出所有 <prefix>_*_price 的活索引（去掉 _v*_bak 和 _test_*）"""
    url = f"{ES_HOST}/_cat/indices/{prefix}_*?h=index"
    with urllib.request.urlopen(url) as r:
        raw = r.read().decode()
    out = []
    for name in raw.strip().split("\n"):
        name = name.strip()
        if not name:
            continue
        if "_v" in name and "_bak" in name:
            continue
        if "_test_" in name:
            continue
        if name.endswith("_price") or name.endswith("_price_"):
            out.append(name)
    return sorted(set(out))


def flatten_type(field_def: dict) -> str:
    """把 ES 字段定义归一化成可比较的字符串

    - keyword: 'keyword'
    - text+keyword: 'text+fields:keyword(512)'
    - nested: 'nested{attr:...}'
    """
    t = field_def.get("type", "")
    if t == "text" and "fields" in field_def:
        sub = field_def["fields"]
        if "keyword" in sub:
            return f"text+fields:keyword({sub['keyword'].get('ignore_above', '?')})"
    if t == "nested" and "properties" in field_def:
        sub_keys = sorted(field_def["properties"].keys())
        return f"nested{{{','.join(sub_keys)}}}"
    if t == "date":
        fmt = field_def.get("format", "")
        return f"date({fmt})"
    return t


def compare(declared: dict, actual: dict) -> dict:
    """返回差异字典"""
    decl_keys = set(declared.keys())
    actual_keys = set(actual.keys())

    missing = []     # 声明有 ES 缺
    extra = []       # ES 有声明没
    mismatch = []    # 类型不一致

    for k in sorted(decl_keys - actual_keys):
        missing.append(k)

    for k in sorted(actual_keys - decl_keys):
        extra.append({"field": k, "es_type": flatten_type(actual[k])})

    for k in sorted(decl_keys & actual_keys):
        d_t = flatten_type(declared[k])
        a_t = flatten_type(actual[k])
        if d_t != a_t:
            mismatch.append({
                "field": k,
                "declared": d_t,
                "actual": a_t,
            })

    return {"missing": missing, "extra": extra, "mismatch": mismatch}


def main():
    args = [a.lower() for a in sys.argv[1:]]
    if not args or args[0] not in ("dwd", "dws"):
        args = ["dwd", "dws"]
    city_filter = None
    if "--city" in args:
        idx = args.index("--city")
        city_filter = args[idx + 1]
        args = args[:idx]

    dwd_decl = build_dwd_mapping()["mappings"]["properties"]
    dws_decl = build_dws_mapping()["mappings"]["properties"]

    summary = {"dwd": {}, "dws": {}}

    for layer in args:
        decl = dwd_decl if layer == "dwd" else dws_decl
        indices = list_indices(layer)
        if city_filter:
            indices = [i for i in indices if city_filter in i]
        print(f"\n{'='*72}\n  {layer.upper()} 声明字段数: {len(decl)}    实际索引: {len(indices)}\n{'='*72}")
        for idx in indices:
            actual = fetch_es_mapping(idx)
            diff = compare(decl, actual)
            n_mis = len(diff["missing"])
            n_extra = len(diff["extra"])
            n_type = len(diff["mismatch"])
            print(f"\n[{idx}]  missing={n_mis}  extra={n_extra}  type_mismatch={n_type}")
            if diff["missing"]:
                print(f"  ✗ 声明有 ES 缺: {diff['missing']}")
            if diff["extra"]:
                print(f"  ⚠ ES 多出字段（dynamic 推断）:")
                for e in diff["extra"]:
                    print(f"     - {e['field']:30s} es_type={e['es_type']}")
            if diff["mismatch"]:
                print(f"  ⚠ 类型不一致:")
                for m in diff["mismatch"]:
                    print(f"     - {m['field']:30s} 声明={m['declared']:30s} 实际={m['actual']}")
            summary[layer][idx] = {
                "missing": n_mis, "extra": n_extra, "type_mismatch": n_type
            }

    # 汇总
    print(f"\n{'='*72}\n  汇总\n{'='*72}")
    for layer, items in summary.items():
        if not items:
            continue
        total_missing = sum(v["missing"] for v in items.values())
        total_extra = sum(v["extra"] for v in items.values())
        total_type = sum(v["type_mismatch"] for v in items.values())
        print(f"{layer.upper()}: {len(items)} 索引  缺字段={total_missing}  多余={total_extra}  类型错={total_type}")


if __name__ == "__main__":
    main()
