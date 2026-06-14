"""classify/system.py - 分类体系（category → code → name）映射

从 data/category_in_system.json 加载懒加载映射：
  - _CATEGORY_CODE_MAP: name → code
  - _CATEGORY_NAME_MAP: code → name

调用方：
  - transform.doc.transform_doc()  写 category_system / category_system_name
  - pipeline.etl.etl_city()  AI 分类后回写
"""
import json
from typing import Tuple

from gov_price_etl.paths import CATEGORY_IN_SYSTEM_JSON

_CATEGORY_CODE_MAP: dict = {}
_CATEGORY_NAME_MAP: dict = {}


def _load_category_system_map() -> Tuple[dict, dict]:
    """从 category_in_system.json 构建 category name → code 和 name 映射。"""
    code_map: dict = {}
    name_map: dict = {}
    if CATEGORY_IN_SYSTEM_JSON.exists():
        with open(CATEGORY_IN_SYSTEM_JSON) as f:
            data = json.load(f)
        for group in data.get("categories", []):
            for child in group.get("children", []):
                code_map[child["name"]] = child["code"]
                name_map[child["code"]] = child["name"]
    return code_map, name_map


def _get_category_system_maps() -> Tuple[dict, dict]:
    global _CATEGORY_CODE_MAP, _CATEGORY_NAME_MAP
    if not _CATEGORY_CODE_MAP:
        _CATEGORY_CODE_MAP, _CATEGORY_NAME_MAP = _load_category_system_map()
    return _CATEGORY_CODE_MAP, _CATEGORY_NAME_MAP


def get_category_system_map() -> dict:
    """name → code"""
    code_map, _ = _get_category_system_maps()
    return code_map


def get_category_system_name_map() -> dict:
    """code → name"""
    _, name_map = _get_category_system_maps()
    return name_map
