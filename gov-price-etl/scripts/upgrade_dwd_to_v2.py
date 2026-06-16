#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
upgrade_dwd_to_v2.py - DWD 索引升级到 v2 mapping（阶段 2 接入）

操作：
  1. 推新 index template（gov_dwd 用新 mapping，包含 v2 字段）
  2. 删除 8 个 DWD 旧索引（v1 mapping）
  3. （可选）立刻重建 8 个 DWD 索引（空索引，套用新 template）

不做：
  - 不跑 ETL / 不回填数据
  - 不改 transform.py
  - 不动 DWS 索引
  - 不动 ODS 索引

用法：
    python3 scripts/upgrade_dwd_to_v2.py             # 升级 + 重建
    python3 scripts/upgrade_dwd_to_v2.py --no-create # 只升级 template + 删旧（不重建）
    python3 scripts/upgrade_dwd_to_v2.py --dry-run   # 只打印不执行
"""

import argparse
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
PROJECT_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(PROJECT_ROOT))

from gov_price_etl.es_client import get_es_client
from gov_price_etl.indexer import setup_index_templates


ES_HOST = "http://localhost:59200"

DWD_INDICES = [
    "dwd_xian_price", "dwd_sichuan_price", "dwd_chongqing_price",
    "dwd_jinan_price", "dwd_rizhao_price", "dwd_henan_price",
    "dwd_heze_price", "dwd_qingdao_price",
]


def main():
    parser = argparse.ArgumentParser(description="DWD 索引升级到 v2 mapping")
    parser.add_argument("--dry-run", action="store_true", help="只打印不执行")
    parser.add_argument("--no-create", action="store_true", help="不重建索引（让下次 ETL 自动套用新 template）")
    args = parser.parse_args()

    s = get_es_client(ES_HOST)

    def head(idx): return s.head(f"{ES_HOST}/{idx}")
    def count(idx): return s.get(f"{ES_HOST}/{idx}/_count").json().get("count", 0)
    def get_mapping(indices): return s.get(f"{ES_HOST}/{','.join(indices)}/_mapping").json()

    # ── 1. 推新 index template ──
    print("=== [1/3] 推新 index template（gov_dwd 用 v2 mapping）===")
    if args.dry_run:
        print(f"  [DRY-RUN] 调 setup_index_templates({ES_HOST})")
    else:
        setup_index_templates(ES_HOST)

    # ── 2. 删除 8 个 DWD 旧索引 ──
    print("\n=== [2/3] 删除 8 个 DWD 旧索引（v1 mapping）===")
    for idx in DWD_INDICES:
        if args.dry_run:
            r = head(idx)
            exists = (r.status_code == 200)
            cnt = count(idx) if exists else 0
            print(f"  [DRY-RUN] {idx:30s}  exists={exists}  docs={cnt}")
        else:
            r = head(idx)
            if r.status_code == 200:
                cnt = count(idx)
                s.delete(f"{ES_HOST}/{idx}")
                print(f"  ✓ 删 {idx:30s}  (清空 {cnt} 条文档)")
            else:
                print(f"  - 跳 {idx:30s}  (不存在)")

    # ── 3. 重建（套用新 template）──
    if not args.no_create:
        print("\n=== [3/3] 重建 8 个 DWD 索引（套用新 template）===")
        for idx in DWD_INDICES:
            if args.dry_run:
                print(f"  [DRY-RUN] 创建 {idx}")
            else:
                s.put(f"{ES_HOST}/{idx}", json={})
                print(f"  ✓ 创建 {idx}")

    # ── 验证 ──
    if not args.dry_run:
        print("\n=== 验证：DWD mapping 包含 v2 字段 ===")
        v2_fields = ["category_l1", "category_l2", "category_l3", "category_l4",
                     "eng_part", "eng_stage", "main_or_aux",
                     "gb_50500", "quota_ref", "ifc_class", "uniclass_ss",
                     "material_code", "category_v2_source", "category_v2_confidence"]
        m = get_mapping(DWD_INDICES)
        sample_idx = list(m.keys())[0]
        props = m[sample_idx]["mappings"]["properties"]
        for f in v2_fields:
            status = "✓" if f in props else "✗"
            ftype = props.get(f, {}).get("type", "MISSING")
            print(f"  {status} {sample_idx}.{f:25s}  type={ftype}")


if __name__ == "__main__":
    main()
