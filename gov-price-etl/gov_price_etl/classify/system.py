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
    """name → code

    兑底：未在 category_in_system.json 里的分类名称（典型的如 "其他"），
    返回占位 code "OTHER"，避免下游字段为空。
    """
    code_map, _ = _get_category_system_maps()
    # 兑底：未知分类名给一个占位 code，让字段永不为空
    code_map.setdefault("其他", "OTHER")
    code_map.setdefault("", "OTHER")
    return code_map


def get_category_system_name_map() -> dict:
    """code → name

    兑底：未在 category_in_system.json 里的 code（如 "OTHER"），名称给 "其他"。
    """
    _, name_map = _get_category_system_maps()
    # 兑底：未知 code 给 "其他" 作为展示名
    name_map.setdefault("OTHER", "其他")
    return name_map
