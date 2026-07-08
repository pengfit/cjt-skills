"""统一数据加载器：lazy load + 内存缓存 + 路径解析

所有层（units/periods/fields/cross_city）只通过本模块拿数据，
不直接读 JSON 或 SQLite，方便：
- 测试时 mock
- 数据更新（reload）
- 多源支持（JSON / SQLite / 远程）

数据存放约定：
- <pkg>/data/*.json         标准 JSON 数据
- 用户可在 <pkg>/data/override/ 放同名 JSON 覆盖（开发用）
"""
from __future__ import annotations
import json
from pathlib import Path
from threading import RLock
from typing import Any, Optional

# 包根目录（包含 data/ 的那个目录）
_PKG_ROOT = Path(__file__).resolve().parent.parent
_DATA_DIR = _PKG_ROOT / "data"
_OVERRIDE_DIR = _DATA_DIR / "override"

_cache: dict[str, Any] = {}
_lock = RLock()


def _read_json(name: str) -> Any:
    """读 JSON，override 目录优先于 data 目录。"""
    override_path = _OVERRIDE_DIR / name
    main_path = _DATA_DIR / name
    if override_path.exists():
        with open(override_path, "r", encoding="utf-8") as f:
            return json.load(f)
    if not main_path.exists():
        raise FileNotFoundError(f"data/{name} 不存在（_PKG_ROOT={_PKG_ROOT}）")
    with open(main_path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_json(name: str, *, force: bool = False) -> Any:
    """加载并缓存 JSON 文件。force=True 重新读盘（数据更新后用）。"""
    with _lock:
        if force or name not in _cache:
            _cache[name] = _read_json(name)
        return _cache[name]


def clear_cache() -> None:
    """清空所有缓存（测试用）。"""
    with _lock:
        _cache.clear()


def get_meta(name: str, *, default_version: str = "0.0.0") -> dict:
    """取 JSON 顶层的 _meta 块（version/updated/note），缺失时给默认值。"""
    data = load_json(name)
    return data.get("_meta", {"version": default_version, "updated": "unknown", "note": ""})


def data_dir() -> Path:
    """返回 data 目录路径（CLI/调试用）。"""
    return _DATA_DIR