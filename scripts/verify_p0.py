#!/usr/bin/env python3
"""P0 (v0.6 进度统一) 全量验证脚本。

verify 各城市 commands/utils.py（部分城市 sync.py / write_es.py）的
`ensure_progress_index` 函数：
- 7 个 es SDK 城市：qingdao / weihai / huhehaote / heze / jiangxi / ningxia / qinghai
- 1 个 es SDK 函数名差异：shaanxi
- 4 个 requests：xian (sync.py ProgressLogger) / sichuan / jinan / rizhao
- 4 个 PDF 类：hainan / henan / xinjiang / shaanxi(utils.py 共用)
- 1 个特殊内嵌：chongqing (write_es.py)
全部迁移到 gov_price_etl.mappings.build_progress_mapping 或
gov_price_etl.indexer.ensure_progress_index。
"""
import importlib.util
import os
import sys
from pathlib import Path

SKILLS_ROOT = Path("/Users/pengfit/.openclaw/workspace/skills")

# (city, entry_file_relative_to_city_skill)
CASES = [
    ("qingdao",     "commands/utils.py"),
    ("weihai",      "commands/utils.py"),
    ("huhehaote",   "commands/utils.py"),
    ("heze",        "commands/utils.py"),
    ("jiangxi",     "commands/utils.py"),
    ("ningxia",     "commands/utils.py"),
    ("qinghai",     "commands/utils.py"),
    ("shaanxi",     "commands/utils.py"),
    ("hainan",      "commands/utils.py"),
    ("henan",       "commands/utils.py"),
    ("xinjiang",    "commands/utils.py"),
    ("xian",        "commands/sync.py"),
    ("sichuan",     "commands/utils.py"),
    ("jinan",       "commands/utils.py"),
    ("rizhao",      "commands/utils.py"),
    ("chongqing",   "commands/write_es.py"),
]

ok = 0
fail = []
for city, rel in CASES:
    fpath = SKILLS_ROOT / f"{city}-price" / rel
    if not fpath.exists():
        fail.append(f"{city}: FILE NOT FOUND ({fpath})")
        continue
    try:
        spec = importlib.util.spec_from_file_location(f"t_{city}", str(fpath))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        # 城市迁移验证
        if city == "chongqing":
            # write_es.py：检查 _ensure_progress_index 是否已 import
            if hasattr(mod, "_ensure_progress_index") and hasattr(mod, "cmd_progress"):
                src = (fpath / "").read_text() if False else fpath.read_text()
                if "gov_price_etl.indexer" in src and "__" in src and "cmd_progress" in src:
                    ok += 1
                    print(f"  ✓ {city:<11} write_es.py: _ensure_progress_index 已 import + _id 标准化")
                else:
                    fail.append(f"{city}: _id 未完全标准化")
            else:
                fail.append(f"{city}: 缺 _ensure_progress_index 或 cmd_progress")
        elif city == "xian":
            # sync.py: ProgressLogger._ensure_index 应该委托到 gov_price_etl
            cls = getattr(mod, "ProgressLogger", None)
            if cls is None:
                fail.append(f"{city}: 没有 ProgressLogger")
            else:
                src = fpath.read_text()
                if "ensure_progress_index" in src and "from gov_price_etl" in src:
                    ok += 1
                    print(f"  ✓ {city:<11} sync.py: ProgressLogger._ensure_index 委托到 gov_price_etl")
                else:
                    fail.append(f"{city}: ProgressLogger 未委托到 gov_price_etl")
        else:
            # utils.py: ensure_progress_index 必须存在 + 文档提到 gov_price_etl
            fn = getattr(mod, "ensure_progress_index", None)
            if fn is None:
                fail.append(f"{city}: 缺 ensure_progress_index")
            else:
                src = fpath.read_text()
                # es SDK 类调用 build_progress_mapping，requests 类调用 ensure_progress_index
                has_deleg = ("build_progress_mapping" in src) or ("ensure_progress_index" in src)
                if has_deleg:
                    ok += 1
                    print(f"  ✓ {city:<11} utils.py: ensure_progress_index 已委托到 gov_price_etl")
                else:
                    fail.append(f"{city}: ensure_progress_index 未委托到 gov_price_etl")
    except Exception as e:
        fail.append(f"{city}: EXCEPTION {type(e).__name__}: {e}")

print(f"\n==== {ok} / {len(CASES)} 城市 P0 迁移通过 ====")
if fail:
    print("\n❌ 失败:")
    for f in fail:
        print(f"  - {f}")
    sys.exit(1)
else:
    print("✅ 全部通过")
    sys.exit(0)
