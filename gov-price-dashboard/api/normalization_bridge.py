"""api/normalization_bridge.py

把 gov-price-normalization 包路径加入 sys.path，绝不 import ETL 模块。

用法（在 dashboard api/ 任意模块顶部）：
    from api.normalization_bridge import normalize_doc, normalize_batch

特点：
- 不在包内硬编码路径（基于本文件路径反推）
- 路径解析失败时给明确错误，不静默 fallback
- 一次 sys.path 设置即可，无需重复
"""
from __future__ import annotations
import sys
import os
from pathlib import Path

# 路径优先走 SKILLS_ROOT 环境变量（与 api/paths.py 一致）
# 本地开发：~/.openclaw/workspace/cjt/skills
# 容器内：/app/skills
try:
    from api.paths import SKILLS_ROOT as _SKILLS_ROOT
except ImportError:
    # api.paths 加载失败时（如直接 import 本文件），从 __file__ 反推兜底
    _BRIDGE = Path(__file__).resolve()
    _DASHBOARD = _BRIDGE.parent.parent
    _SKILLS_ROOT = _DASHBOARD.parent

_NORM_PKG = Path(_SKILLS_ROOT) / "gov-price-normalization"

if not _NORM_PKG.exists():
    raise RuntimeError(
        f"[normalization_bridge] 找不到 NormalizationLayer 包：{_NORM_PKG}\n"
        f"确认 skills/gov-price-normalization/ 存在（与 gov-price-dashboard/ 平级）。"
    )

if str(_NORM_PKG) not in sys.path:
    sys.path.insert(0, str(_NORM_PKG))

# 重新导出主入口（不引入 ETL 依赖）
from gov_price_normalization import (  # noqa: E402
    normalize_doc,
    normalize_batch,
    layers,
    units,
    periods,
    fields,
    cross_city,
    data_loader,
    errors,
    __version__ as _NORM_VERSION,
)

# breed 格式归一（从 cli 模块拿，避免复制逻辑）
try:
    from gov_price_normalization.cli.normalize_breed_format import (  # noqa: E402
        normalize_breed_format,
    )
    normalize_breed_text = normalize_breed_format
except Exception:  # pragma: no cover
    def normalize_breed_text(s: str) -> str:
        return s or ""


def resolve_query_index(es_client, city: str, *, prefer: str = "norm") -> dict:
    """决定该查询走哪个索引：NORM 优先，缺失 fallback DWS。

    Args:
        es_client: 已连接好的 elasticsearch.Elasticsearch 实例
        city: 城市 key，如 'xian' / 'hainan'
        prefer: 'norm'（默认，NORM 优先）/ 'dws'（强制走 DWS）/ 'auto'（自动判断）

    Returns:
        {
          'index': str,            # 实际查询用的索引名
          'fallback': bool,         # 是否走了 fallback
          'reason': str,            # 选择原因（调试 / 上游 / 提示用）
          'has_norm': bool,         # NORM 索引是否存在
          'has_dws': bool,          # DWS 索引是否存在
        }
    """
    dws_idx = f"dws_{city}_price"
    norm_idx = f"norm_{city}_price"

    has_norm = False
    has_dws = False
    try:
        has_norm = bool(es_client.indices.exists(index=norm_idx))
    except Exception:
        pass
    try:
        has_dws = bool(es_client.indices.exists(index=dws_idx))
    except Exception:
        pass

    if prefer == "dws":
        if has_dws:
            return {"index": dws_idx, "fallback": False, "reason": "forced_dws", "has_norm": has_norm, "has_dws": has_dws}
        return {"index": None, "fallback": True, "reason": "dws_missing", "has_norm": has_norm, "has_dws": has_dws}

    # prefer == 'norm' or 'auto'
    if has_norm:
        return {"index": norm_idx, "fallback": False, "reason": "norm_preferred", "has_norm": has_norm, "has_dws": has_dws}
    if has_dws:
        return {"index": dws_idx, "fallback": True, "reason": "norm_missing_fallback_dws", "has_norm": has_norm, "has_dws": has_dws}
    return {"index": None, "fallback": True, "reason": "both_missing", "has_norm": has_norm, "has_dws": has_dws}


__all__ = [
    "normalize_doc",
    "normalize_batch",
    "layers",
    "units",
    "periods",
    "fields",
    "cross_city",
    "data_loader",
    "errors",
    "resolve_query_index",
    "normalize_breed_text",
    "_NORM_VERSION",
    "_NORM_PKG",
]