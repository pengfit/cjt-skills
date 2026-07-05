#!/usr/bin/env python3
"""P1 抽取脚本 - 把 11 个 es SDK 城市的 utils.py 工具函数委托到 gov_price_etl.collectors

目标函数（11 城都重复）：
  load_config / get_es_client / get_s3_client / ensure_bucket /
  fetch_html / download_file / upload_to_minio / minio_object_url

保留（业务特定）：
  ensure_ods_index / ensure_progress_index（P0 已委托，不动）/
  parse_list_page / parse_detail_page / extract_period / extract_city
  等业务函数

用法：
  python3 scripts/migrate_p1_es_sdk.py [--dry-run]
"""
def _resolve_etl_root():
    """解析 gov-price-etl 项目根路径。

    优先级：
      1) 环境变量 GOV_PRICE_ETL_ROOT（部署/调试可显式覆盖）
      2) 自动反推：从本文件路径向上找 'gov-price-etl' 同级目录，
         不依赖硬编码的 workspace 名 / 目录深度。
      3) 兜底 fallback（cjt 子目录布局），让上层 log warning，不抛异常。
    """
    import os
    from pathlib import Path
    env = os.environ.get("GOV_PRICE_ETL_ROOT")
    if env and os.path.isdir(env):
        return env
    p = Path(__file__).resolve().parent
    for _ in range(6):
        candidate = p / "gov-price-etl"
        if candidate.is_dir():
            return str(candidate)
        p = p.parent
    return str(Path.home() / ".openclaw" / "workspace" / "cjt" / "skills" / "gov-price-etl")


import os
import re
import sys
from pathlib import Path

SKILLS_ROOT = Path("/Users/pengfit/.openclaw/workspace/skills")

# 11 个 es SDK 城市
ES_SDK_CITIES = [
    "qingdao", "weihai", "huhehaote", "heze", "jiangxi",
    "ningxia", "qinghai", "shaanxi", "hainan", "henan", "xinjiang",
]

# 工具函数名（要被替换为委托）
TOOL_FUNCTIONS = [
    "load_config", "get_es_client", "get_s3_client", "ensure_bucket",
    "fetch_html", "download_file", "upload_to_minio", "minio_object_url",
]

# 新文件头模板（替换原 import 区 + 工具函数定义）
NEW_HEADER = '''"""{}"""
import os
import sys

# v0.7 (2026-07-02) P1 抽取：工具函数委托到 gov_price_etl.collectors
_etl_root = _resolve_etl_root()
if os.path.isdir(_etl_root) and _etl_root not in sys.path:
    sys.path.insert(0, _etl_root)
from gov_price_etl.collectors import (
    load_config, get_es_client, get_s3_client, ensure_bucket,
    upload_to_minio, minio_object_url, fetch_html, download_file,
)


'''


def extract_docstring(text, fn_name):
    """提取函数 docstring 的第一行（用作新文件头注释）。"""
    # 支持单行 """xxx""" 和多行 """\nxxx\n"""
    m = re.search(r'^"""([^"\n]+?)"""', text, re.MULTILINE)
    if m:
        return m.group(1).strip()
    m = re.search(r'^"""\s*\n(.+?)\n', text, re.MULTILINE)
    if m:
        return m.group(1).strip()
    return f"{fn_name} 工具函数"


def migrate_city(city: str, dry_run: bool = False) -> tuple[bool, int]:
    """迁移单个城市的 utils.py。

    Returns:
        (changed, lines_saved)
    """
    fpath = SKILLS_ROOT / f"{city}-price" / "commands" / "utils.py"
    if not fpath.exists():
        print(f"  ❌ {city}: 文件不存在")
        return False, 0

    original = fpath.read_text()
    lines_original = original.count("\n")

    # 1. 删除所有工具函数（保留 ensure_ods_index / ensure_progress_index / 业务函数）
    # 策略：找到所有 def <TOOL_FN>(...) 块，连同前后空行一起删
    new_text = original
    for fn in TOOL_FUNCTIONS:
        # 匹配 def fn(...): ... 后面到下一个 def 或文件结尾
        pattern = rf'\n*def {fn}\([^)]*\).*?(?=\n\ndef |\nclass |\Z)'
        new_text = re.sub(pattern, '', new_text, count=1, flags=re.DOTALL)

    # 2. 替换文件头（import 区域）
    docstring = extract_docstring(original, city)
    new_header = NEW_HEADER.format(docstring)
    # 找到原文件头结束位置（第一个 def 之前）
    first_def_match = re.search(r'\ndef ', new_text)
    if first_def_match:
        new_text = new_header + new_text[first_def_match.start()+1:]
    else:
        new_text = new_header + new_text

    # 3. 清理多余的连续空行
    new_text = re.sub(r'\n{3,}', '\n\n', new_text)

    lines_new = new_text.count("\n")
    lines_saved = lines_original - lines_new

    if dry_run:
        print(f"  🔍 {city}: {lines_original} → {lines_new} 行 (净 - {lines_saved})")
        # print 头 30 行
        print("    " + new_text[:500].replace("\n", "\n    "))
        print()
        return False, lines_saved

    # 写文件
    fpath.write_text(new_text)
    print(f"  ✓ {city}: {lines_original} → {lines_new} 行 (净 - {lines_saved})")
    return True, lines_saved


def main():
    dry_run = "--dry-run" in sys.argv

    print(f"{'🔍 DRY-RUN' if dry_run else '✏️  MIGRATE'} 11 个 es SDK 城市 utils.py\n")

    total_saved = 0
    changed_count = 0
    for city in ES_SDK_CITIES:
        changed, saved = migrate_city(city, dry_run=dry_run)
        if changed:
            changed_count += 1
        total_saved += saved

    print(f"\n==== {'总览' if dry_run else '迁移'} ====")
    print(f"城市数: {changed_count if not dry_run else 0} / {len(ES_SDK_CITIES)} 已{'迁移' if not dry_run else '检查'}")
    print(f"净删除: {total_saved} 行")


if __name__ == "__main__":
    main()