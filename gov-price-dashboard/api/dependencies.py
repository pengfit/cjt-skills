"""API 共享依赖：ES client + 索引集常量。

集中所有路由模块需要的底层依赖：
- `es`：ES client 单例（按 ES_HOST 环境变量）
- `ES_HOST` / `ES_INDEX`：环境变量配置
- `ALL_INDICES`：默认 NORM（业务层），env var `DASHBOARD_DATA_LAYER=dws` 可回退 DWS
- `LIST_INDICES`：DWS 索引集，专供 `/api/search`（/list 页）
- `ALL_DWD_INDICES`：DWD 索引集，供审计/分类校对
- `ALL_ODS_INDICES`：ODS 索引集，供数据健康/同步进度
- `NORM_INDICES`：运行时扫 ES 的 norm_*_price 列表，供分类接口

任何路由模块 `from api.dependencies import es, ALL_INDICES, ...` 即可。

启动时自动执行 skill registry reload + 索引过滤，失败有 fallback。
"""
from __future__ import annotations
import os
import logging
from typing import Tuple

from elasticsearch import Elasticsearch

# 集中引用 skill registry（见 api/skill_registry.py）
# 新增/修改 skill 只需编辑 skills/<name>/skill.yml，重启后自动生效
from api.skill_registry import (
    reload as _registry_reload,
    dws_indices_csv as _registry_dws_csv,
    ods_indices_csv as _registry_ods_csv,
    dwd_indices_csv as _registry_dwd_csv,
    norm_indices_csv as _registry_norm_csv,
)
from api.helpers import filter_existing_indices

log = logging.getLogger("dependencies")

# ── ES client ───────────────────────────────────────────────────────────
ES_HOST = os.environ.get("ES_HOST", "http://localhost:59200")
ES_INDEX = os.environ.get("ES_INDEX", "dwd_xian_price")

es = Elasticsearch([ES_HOST], request_timeout=30)

# ── Fallback 索引集（registry 失败 / 无 skill 时使用）────────────────────
_DWS_FALLBACK = (
    "dws_xian_price,dws_sichuan_price,dws_chongqing_price,dws_jinan_price,"
    "dws_rizhao_price,dws_heze_price,dws_henan_price,dws_qingdao_price"
)
_ODS_FALLBACK = (
    "ods_material_xian_price,ods_material_sichuan_price,ods_material_chongqing_price,"
    "ods_material_jinan_price,ods_material_rizhao_price,ods_material_heze_price,"
    "ods_material_henan_price,ods_material_qingdao_price"
)
_DWD_FALLBACK = (
    "dwd_xian_price,dwd_sichuan_price,dwd_chongqing_price,dwd_jinan_price,"
    "dwd_rizhao_price,dwd_heze_price,dwd_henan_price,dwd_qingdao_price"
)


# ── 工具函数 ────────────────────────────────────────────────────────────
def _csv_with_fallback(csv_fn, fallback: str, label: str) -> Tuple[str, bool]:
    """调 csv_fn()，失败或空时用 fallback。

    Returns:
        (csv, fallback_used) — fallback_used=True 表示走了 fallback
    """
    try:
        v = csv_fn()
        if not v:
            log.warning("[%s] 扫到空 csv，使用 fallback", label)
            return fallback, True
        return v, False
    except Exception as e:
        log.warning("[%s] csv 扫描失败: %s，使用 fallback", label, e)
        return fallback, True


def _scan_norm_indices() -> str:
    """运行时扫 ES 的 norm_*_price 索引（不依赖 skill registry）。

    NORM_INDICES 是动态的（每次 ETL 重建 NORM 后可能增减），
    所以启动时直接 cat ES，不读 registry。
    """
    try:
        cat = es.cat.indices(index="norm_*_price", format="json")
        out = [r["index"] for r in cat if r.get("index")]
        return ",".join(sorted(out))
    except Exception as ex:
        log.warning("_scan_norm_indices 失败: %s", ex)
        return ""


# ── 启动时初始化（导入即生效）─────────────────────────────────────────
try:
    _registry_reload()
except Exception as _e:
    log.warning("skill_registry reload 失败: %s", _e)

# ALL_INDICES：默认 NORM（业务层）；env var `DASHBOARD_DATA_LAYER=dws` 回退 DWS
_DATA_LAYER = os.environ.get("DASHBOARD_DATA_LAYER", "norm").lower().strip()
if _DATA_LAYER == "norm":
    _all_csv, _fb1 = _csv_with_fallback(_registry_norm_csv, _DWS_FALLBACK, "ALL_INDICES")
else:
    _all_csv, _fb1 = _csv_with_fallback(_registry_dws_csv, _DWS_FALLBACK, "ALL_INDICES")
ALL_INDICES = filter_existing_indices(es, _all_csv, log_label="ALL_INDICES")
print(f"[info] ALL_INDICES data layer={_DATA_LAYER or 'dws'} fallback={_fb1} count={len(ALL_INDICES.split(',')) if ALL_INDICES else 0}")

# LIST_INDICES：/list 页（/api/search）单独走 DWS，其他页面走 NORM
_list_csv, _ = _csv_with_fallback(_registry_dws_csv, _DWS_FALLBACK, "LIST_INDICES")
LIST_INDICES = filter_existing_indices(es, _list_csv, log_label="LIST_INDICES")
print(f"[info] LIST_INDICES (for /api/search) count={len(LIST_INDICES.split(',')) if LIST_INDICES else 0}")

# ALL_DWD_INDICES：审计/分类校对用
ALL_DWD_INDICES, _ = _csv_with_fallback(_registry_dwd_csv, _DWD_FALLBACK, "ALL_DWD_INDICES")

# ALL_ODS_INDICES：数据健康/同步进度用
ALL_ODS_INDICES, _ = _csv_with_fallback(_registry_ods_csv, _ODS_FALLBACK, "ALL_ODS_INDICES")

# NORM_INDICES：运行时扫 ES（不依赖 registry，因为 ETL 会重建）
NORM_INDICES = _scan_norm_indices()
if not NORM_INDICES:
    print("[warn] NORM_INDICES 为空，未扫到任何 norm_*_price，类别接口将不提供数据")
else:
    head = NORM_INDICES[:200]
    more = "..." if len(NORM_INDICES) > 200 else ""
    print(f"[info] NORM_INDICES = {head}{more}")