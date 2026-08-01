"""L4 跨城映射层

v0.3（2026-08-01）首次完整实现，解锁 Phase C。核心：

  canonicalize(breed_clean, city=None)
    单文档主入口：breed_clean → {normalized_breed, l3_code, confidence, source}
    内部走 data/breed_canonical.get_canonical()。命中即返回，未命中 None。

  expand_to_cities(canonical_breed, cities=None)
    反向索引：canonical_breed → {breed_clean: row}
    用于跨城/跨期同义品种展开（dashboard 跨城行情标准用法）。
    city 过滤不在本层做——DB 不存 city 字段。返回的 breed_cleans 列表交给调用方
    去 NORM 索引按 (city, breed_clean) 查询。

  align_spec_across_cities(spec_attrs, cities)
    跨城 spec attr 对齐（v0.3 占位透传）。spec 命名差异（HPB300 ↔ Q235）属 v0.4+ 范围，
    本期 spec 维度靠 ES 多字段聚合处理。

设计：
  - 全程纯函数（除读 DB）
  - 失败降级不阻断（不抛异常，返回 None 或 {}）
  - city 字段为「上下文参数」（未来按城做归一策略时用），不影响 v0.3 行为
"""
from __future__ import annotations
import logging
from typing import Optional

from ..data.breed_canonical import (
    get_canonical,
    get_breeds_by_canonical,
    search_canonical as _search_canonical_raw,
)

log = logging.getLogger(__name__)


def canonicalize(breed_clean: str, city: Optional[str] = None) -> Optional[dict]:
    """L4 单文档主入口：breed_clean → canonical 元信息。

    Args:
        breed_clean: 清洗后品种名（如「热轧带肋钢筋」「HRB400」）。
        city: 城市 key（v0.3 仅作上下文记录，不影响查表）。

    Returns:
        None if breed_clean 不在 canonical.db
        dict 形如:
            {
                "breed_clean": str,
                "normalized_breed": str,
                "l3_code": str | None,
                "confidence": float,
                "source": str,        # etl_v3_sqlite / ai_dify / ...
            }

    用法：
        hit = canonicalize("HRB400")
        if hit:
            doc["normalized_breed"] = hit["normalized_breed"]
            doc["_canonical_source"] = hit["source"]
            doc["_l3_code"] = hit["l3_code"]
        else:
            doc["normalized_breed"] = breed_clean  # raw fallback
            doc["_canonical_source"] = "raw_fallback"

    失败降级：DB 读取异常返回 None（不抛异常），调用方按 raw_fallback 处理。
    """
    if not breed_clean:
        return None
    try:
        row = get_canonical(breed_clean)
    except Exception as e:
        log.warning("[L4 canonicalize] DB read failed breed_clean=%r city=%s err=%s",
                    breed_clean, city, e)
        return None
    if row is None:
        return None
    # 拼回 breed_clean 字段（业务上调用方常需要反查）
    return {
        "breed_clean": breed_clean,
        "normalized_breed": row["normalized_breed"],
        "l3_code": row.get("l3_code"),
        "confidence": float(row.get("confidence", 0.0) or 0.0),
        "source": row.get("source", ""),
    }


def expand_to_cities(
    canonical_breed: str,
    cities: Optional[list[str]] = None,
) -> dict:
    """反向索引：canonical_breed → 全部已知 breed_clean。

    Args:
        canonical_breed: 归一化品种名（如「热轧带肋钢筋」）。
        cities: 可选城市过滤。**注意：v0.3 不在 DB 层过滤**（DB 无 city 字段），
            仅作为元信息透传，调用方仍需对返回的 breed_cleans 去 NORM 索引
            按 (city, breed_clean) 查询价格。

    Returns:
        {
            "canonical_breed": str,
            "breed_cleans":   [str, ...],           # 全部 breed_clean 去重
            "by_breed":       {breed_clean: {l3_code, confidence, source, ...}},
            "cities_filter":  [city, ...] or None,  # 调用方传入的 cities（仅透传）
        }

    失败降级：DB 读取异常返回空 dict（保留 canonical_breed 字段）。
    """
    if not canonical_breed:
        return {"canonical_breed": "", "breed_cleans": [], "by_breed": {}, "cities_filter": cities}
    try:
        rows = get_breeds_by_canonical(canonical_breed)
    except Exception as e:
        log.warning("[L4 expand_to_cities] DB read failed canonical=%r err=%s",
                    canonical_breed, e)
        rows = {}
    breed_cleans = sorted(rows.keys())
    return {
        "canonical_breed": canonical_breed,
        "breed_cleans": breed_cleans,
        "by_breed": rows,
        "cities_filter": cities,
    }


def align_spec_across_cities(
    spec_attrs: dict,
    cities: Optional[list[str]] = None,
) -> dict:
    """跨城 spec attr 对齐（v0.3 占位透传）。

    v0.3 范围内：spec 维度的命名差异（HPB300 ↔ Q235）靠 ES 多字段聚合解决，
    本函数不做事。返回的 dict 给调用方一个稳定接口，未来 v0.4+ 在此接 L4 spec 层。

    Args:
        spec_attrs: 形如 {"grade": "HPB300", "diameter": "Φ10"} 的 attr dict。
        cities: 上下文（同 expand_to_cities，不影响行为）。

    Returns:
        原样返回 spec_attrs（占位透传，不修改）。
    """
    return spec_attrs


# ──────────────────────────────────────────────────────────────────────
# v0.3.1 (2026-08-01): search_canonical — casual 名 fallback
# ──────────────────────────────────────────────────────────────────────
def search_canonical(q: str, limit: int = 10) -> list:
    """模糊查：breed_clean OR normalized_breed LIKE %q%

    用于「casual 名 fallback」场景：直接 canonicalize() 查不到时
    （如用户搜「盘螺」「HRB400」这种带括号后缀前/后的 casual 名），
    退到这里 SQL LIKE 找候选。dashboard /api/market/breed-search 的 2-step fallback 用此函数。

    Args:
        q: 用户搜索词
        limit: 返回候选数上限（默认 10）

    Returns:
        list of row dict, 按 confidence DESC + breed_clean ASC 排序。
        空列表表示无候选（调用方走 wildcard 兜底）。

    与 canonicalize() 的关系：
      - canonicalize(q): 精确查，1 条命中即返回（v0.3 主路径）
      - search_canonical(q): 模糊查，返回多候选（v0.3.1 fallback 路径）
      - 典型用法：先 canonicalize()，miss 时再 search_canonical()，2-step fallback
    """
    return _search_canonical_raw(q, limit=limit)


__all__ = [
    "canonicalize",
    "expand_to_cities",
    "align_spec_across_cities",
    "search_canonical",
]
