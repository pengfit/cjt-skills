#!/usr/bin/env python3
"""P1 (v0.7 工具函数统一) 全量验证脚本。

verify 11 个 es SDK 城市 commands/utils.py 的 7 个工具函数
（get_es_client / get_s3_client / ensure_bucket / upload_to_minio / minio_object_url
/ fetch_html / download_file）全部委托到 gov_price_etl.collectors.client。

load_config 不在 P1 抽取范围（路径推断不可靠）。
requests 城市（xian/sichuan/jinan/rizhao）无可抽工具。
chongqing 是 browser 自动化，跳过。

用法：python3 scripts/verify_p1.py
"""
import importlib.util
import sys
from pathlib import Path

SKILLS_ROOT = Path("/Users/pengfit/.openclaw/workspace/skills")

# 11 个 es SDK 城市
ES_SDK_CITIES = [
    "qingdao", "weihai", "huhehaote", "heze", "jiangxi",
    "ningxia", "qinghai", "shaanxi", "hainan", "henan", "xinjiang",
]

# P1 抽取的工具函数（应在 utils.py 里通过 import from etl 委托）
EXPECTED_DELEGATED = [
    "get_es_client", "get_s3_client", "ensure_bucket",
    "upload_to_minio", "minio_object_url",
    "fetch_html", "download_file",
]

ok = 0
fail = []
for city in ES_SDK_CITIES:
    fpath = SKILLS_ROOT / f"{city}-price" / "commands" / "utils.py"
    if not fpath.exists():
        fail.append(f"{city}: FILE NOT FOUND")
        continue
    try:
        spec = importlib.util.spec_from_file_location(f"t_{city}", str(fpath))
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        # 检查 7 个工具函数都从 etl 委托
        missing = []
        for fn in EXPECTED_DELEGATED:
            if not hasattr(mod, fn):
                missing.append(fn)
        if missing:
            fail.append(f"{city}: 缺 {missing}")
            continue

        # 验证 load_config 不委托（本地实现）
        if not hasattr(mod, "load_config"):
            fail.append(f"{city}: 缺 load_config（应本地实现）")
            continue

        # 验证 7 个工具函数都从 gov_price_etl.collectors 导入
        # 通过检查函数的 __module__ 属性
        not_delegated = []
        for fn in EXPECTED_DELEGATED:
            f = getattr(mod, fn)
            if not f.__module__.startswith("gov_price_etl"):
                not_delegated.append(f"{fn}({f.__module__})")
        if not_delegated:
            fail.append(f"{city}: 未委托 {not_delegated}")
            continue

        # 验证 load_config 来自 utils.py 本地（不是 etl）
        # 由于 importlib 加载，__module__ 是 't_<city>'，所以用 inspect.getsourcefile 判断文件路径
        import inspect
        load_cfg_src = inspect.getsourcefile(mod.load_config)
        if 'gov_price_etl' in load_cfg_src:
            fail.append(f"{city}: load_config 在 etl 中（应本地）")
            continue

        ok += 1
        print(f"  ✓ {city:<11} load_config 本地 + 7 个工具函数委托到 gov_price_etl.collectors")
    except Exception as e:
        fail.append(f"{city}: EXCEPTION {type(e).__name__}: {e}")

print(f"\n==== {ok} / {len(ES_SDK_CITIES)} es SDK 城市 P1 迁移通过 ====")
if fail:
    print("\n❌ 失败:")
    for f in fail:
        print(f"  - {f}")
    sys.exit(1)
else:
    print("✅ 全部通过")
    sys.exit(0)