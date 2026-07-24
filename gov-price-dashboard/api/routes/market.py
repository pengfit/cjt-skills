"""市场行情公开 API（不需 JWT）· 数据源:norm_*_price 跨城归一索引

v2 (2026-07-21): 数据源从 DWS 切到 norm。
  - 涨跌幅按 (normalized_breed, city) 跨城归一品种,本期 vs 上期均价对比
  - 热门品类跨 norm 索引聚合
  - 热力图行=normalized_breed,列=city
  - 周期用 period_end (date 类型,跨索引一致) 做 date_histogram,规避 norm 中
    period_id 类型不一 (xian=date,guizhou/henan/heze=text) 的坑
"""
from fastapi import APIRouter, HTTPException, Query
from elasticsearch import Elasticsearch
import os
import sys
import time
import math
import random
from datetime import datetime
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from api.skill_registry import get_all as _registry_get_all

router = APIRouter(prefix="/api/market", tags=["market"])

# ── attr.k 中英映射（2026-07-22 从 trend.py 复用，给 /market 属性自由组合展示中文标签）
#   加载源：1) gov-price-etl/parse_spec/rules/_attrs.py  2) alias 兼容  3) DWS 实际数据补全
#   调用方：/attr-keys 返回中追加 label = _label_k(k)
def _load_attr_label_cn() -> dict:
    import re
    from pathlib import Path
    labels = {}
    try:
        skills_root = os.environ.get("SKILLS_ROOT")
        if skills_root:
            attrs_path = Path(skills_root) / "gov-price-etl" / "gov_price_etl" / "parse_spec" / "rules" / "_attrs.py"
        else:
            attrs_path = (
                Path(__file__).resolve().parent.parent.parent.parent
                / "gov-price-etl" / "gov_price_etl" / "parse_spec" / "rules" / "_attrs.py"
            )
        if attrs_path.exists():
            content = attrs_path.read_text(encoding="utf-8")
            arrow = chr(0x2192)
            for raw in content.split("\n"):
                line = raw.strip()
                if not line or line.startswith("#") or arrow not in line:
                    continue
                left, right = line.split(arrow, 1)
                keys = re.findall(r'"(\w+)"', left)
                cns = re.findall(r'"([^"]+)"', right)
                if keys and cns:
                    labels.setdefault(keys[0], cns[0])
    except Exception:
        pass

    aliases = {
        "core_count": "芯数",
        "cross_section_area": "截面面积",
        "pe_core_count": "PE 芯数",
        "pe_cross_section": "PE 截面",
        "sn_grade": "环刚度",
        "strength": "强度",
        "mix_grade": "强度等级",
        "grade": "强度/标号",
        "trunk_diameter": "干径",
        "crown_diameter": "冠径",
        "branch_height": "分枝高",
    }
    for k, v in aliases.items():
        labels.setdefault(k, v)

    hainan_extras = {
        "trunk_diameter_range": "干径范围",
        "crown_width_range": "冠幅范围",
        "branch_diameter_range": "分枝径范围",
        "palm_height": "株高",
        "glass_thickness": "玻璃厚度",
        "glass_thickness_left": "玻璃厚度(左)",
        "glass_thickness_right": "玻璃厚度(右)",
        "interlayer_thickness": "夹层厚度",
        "tempering": "钢化",
        "fabric_type": "织物类型",
        "thickness_range": "厚度范围",
        "width_range": "宽度范围",
        "diameter_range": "直径范围",
        "grade_range": "强度范围",
        "area_range": "面积范围",
        "depth_range": "深度范围",
        "wall_thickness_range": "壁厚范围",
        "container_size": "容器规格",
        "container_type": "容器类型",
        "surface": "表面处理",
        "reinforcement_content": "含筋量",
        "density": "密度",
        "usage": "用途",
        "quantity": "数量",
        "spacing": "间距",
        "feature": "特性",
        "type": "类型",
        "spec": "规格",
        "unit_weight": "单重",
        "natural": "天然",
        "packaging": "包装",
        "accessory": "配件",
        "breed": "品种",
        "unit": "单位",
    }
    for k, v in hainan_extras.items():
        labels.setdefault(k, v)

    dws_extras = {
        "outer_diameter": "外径",
        "inner_thickness": "内厚",
        "short_leg_width": "短边宽",
        "long_leg_width": "长边宽",
        "web_thickness": "腹板厚度",
        "flange_thickness": "翼缘厚度",
        "flange_type": "翼缘形式",
        "small_diameter": "小径",
        "volume": "体积",
        "distance": "距离",
        "angle": "角度",
        "cut_angle": "切口角度",
        "particle_size": "粒径",
        "particle_size_max": "最大粒径",
        "particle_size_min": "最小粒径",
        "particle_size_range": "粒径范围",
        "mesh_size": "筛孔尺寸",
        "mix_ratio": "配合比",
        "concentration": "浓度",
        "branch_diameter": "分枝径",
        "branch_diameter_max": "最大分枝径",
        "branch_diameter_min": "最小分枝径",
        "branch_count": "分枝数",
        "branch_count_range": "分枝数范围",
        "single_branch_length": "单枝长",
        "trunk_count": "主干数",
        "pot_diameter": "盆径",
        "crown_width": "冠幅",
        "growth_period": "生长周期",
        "bud_count": "芽数",
        "leaf_count": "叶数",
        "power": "功率",
        "power_range": "功率范围",
        "output_voltage": "输出电压",
        "frequency": "频率",
        "backup_time": "备用时间",
        "light_source": "光源",
        "voltage_range": "电压范围",
        "voltage_rating": "电压等级",
        "temperature_rating": "温度等级",
        "fire_resistance": "耐火极限",
        "surface_type": "表面类型",
        "coating": "涂层",
        "socket_type": "套接形式",
        "outlet_count": "出水口数",
        "sleeve_count": "套筒数",
        "layer_count": "层数",
        "flow_coefficient": "流量系数",
        "interlayer_material": "夹层材质",
        "glass_type": "玻璃类型",
        "model": "型号",
        "brand": "品牌",
        "standard": "标准",
        "code": "编号",
        "origin": "产地",
        "plant_spec": "苗木规格",
        "process": "工艺",
        "structure": "结构",
        "capacity": "容量",
        "air_volume": "风量",
        "humidity": "湿度",
        "duration_max": "最长时间",
        "duration_min": "最短时间",
        "base_type": "基层类型",
        "material_type": "材质类型",
        "pole_count": "杆数",
        "glass": "玻璃",
        "washing_method": "洗涤方式",
        "water_absorption": "吸水率",
        "water_repellency": "防水性",
        "softening_rate": "软化率",
        "price_range": "价格区间",
        "cross_section_range": "截面范围",
        "age": "树龄",
        "chest_diameter": "胸径",
        "ground_diameter": "地径",
        "ground_diameter_max": "最大地径",
        "ground_diameter_min": "最小地径",
        "alloy": "合金",
        "area": "面积",
        "depth": "深度",
        "diameter_max": "最大直径",
        "diameter_min": "最小直径",
        "height_max": "最大高度",
        "height_min": "最小高度",
        "thickness_max": "最大厚度",
        "weight": "重量",
        "air_flow": "风量",
        "aux_power": "辅助功率",
        "lifting_height": "起升高度",
        "pixel": "像素",
        "port_count": "端口数",
        "content_percent": "含量",
        "fire_rating": "防火等级",
        "package_type": "包装方式",
        "reinforcement_code": "含筋代号",
        "surface_material": "表面材质",
        "surface_treatment": "表面处理工艺",
        "temper": "调质",
        "duration": "持续时间",
        "modifier": "修饰词",
        "note": "备注",
        "price": "价格",
    }
    for k, v in dws_extras.items():
        labels.setdefault(k, v)
    return labels


K_LABEL_CN = _load_attr_label_cn()

_ATTR_KEY_SPECIAL = {
    "__spec__": "原文规格",
    "__general__": "通用规格",
}


def _label_k(k: str) -> str:
    """取 attr.k 的中文标签，未识别返回原文 key。"""
    if k in _ATTR_KEY_SPECIAL:
        return _ATTR_KEY_SPECIAL[k]
    return K_LABEL_CN.get(k, k)

ES_HOST = os.environ.get("ES_HOST", "http://localhost:59200")
es = Elasticsearch([ES_HOST], request_timeout=30)

# ── 缓存(60s)─────────────────────────────────────────────────
_city_period_cache: dict = {}
_CITY_PERIOD_TTL_S = 60


def _ms_to_date(ms) -> str:
    if not ms:
        return ""
    try:
        return datetime.utcfromtimestamp(int(ms) / 1000).strftime("%Y-%m-%d")
    except Exception:
        return ""


def _norm_indices() -> list:
    """运行时扫所有 norm_*_price 索引"""
    try:
        cat = es.cat.indices(index="norm_*_price", format="json")
        return [r["index"] for r in cat if r.get("index")]
    except Exception:
        return []


def _city_label(norm_index: str) -> str:
    """从 norm_xian_price 反查 '西安'"""
    for s in _registry_get_all():
        if s.get("dws_index"):
            # registry 用 dws_index / ods_index 反查,但 norm 跟 dws 同名(dws_xian_price → norm_xian_price)
            # 直接从 index 名推 key
            pass
        # 简化:从 index 名直接匹配,避免依赖 registry 不同字段名
        expected_norm = s.get("dws_index", "").replace("dws_", "norm_") if s.get("dws_index") else ""
        if expected_norm == norm_index:
            return s.get("label", s.get("key", ""))
        # 兜底:从 ods_index 反推(如果 dws_index 没配)
        expected_norm2 = s.get("ods_index", "").replace("ods_material_", "norm_").replace("_price", "_price")
        if expected_norm2 == norm_index:
            return s.get("label", s.get("key", ""))
    # 兜底兜底:把 index 名转换成可读 key
    return norm_index.replace("norm_", "").replace("_price", "")


def _city_latest_two_periods(norm_index: str):
    """用 runtime_mappings 把 period_end 转为 keyword,terms agg 取最近 2 个 unique 值。
    适用于所有期刊节奏 (月刊/双月刊/季刊),不依赖 date_histogram 的 bucket 粒度。
    返回 (latest_period_end_ms, prev_period_end_ms) | None
    """
    now = time.time()
    cached = _city_period_cache.get(norm_index)
    if cached and (now - cached[0]) < _CITY_PERIOD_TTL_S:
        return cached[1]
    try:
        r = es.search(
            index=norm_index,
            body={
                "size": 0,
                "runtime_mappings": {
                    "period_end_kw": {
                        "type": "keyword",
                        "script": {
                            "lang": "painless",
                            "source": "if (doc['period_end'].size() > 0) { emit(doc['period_end'].value.toString()); }",
                        },
                    }
                },
                "aggs": {
                    "by_period": {
                        "terms": {
                            "field": "period_end_kw",
                            "size": 10,
                            "order": {"_key": "desc"},
                        }
                    }
                },
            },
            ignore_unavailable=True,
            allow_no_indices=True,
        )
        buckets = r.get("aggregations", {}).get("by_period", {}).get("buckets", [])
        if len(buckets) < 2:
            return None
        # key 是 ISO 字符串 (如 "2026-06-30T00:00:00.000Z"),转 epoch ms
        result = []
        for b in buckets[:2]:
            try:
                pe_clean = b["key"].replace("Z", "+00:00")
                pe_dt = datetime.fromisoformat(pe_clean)
                result.append(int(pe_dt.timestamp() * 1000))
            except Exception:
                continue
        if len(result) < 2:
            return None
        ret = (result[0], result[1])
        _city_period_cache[norm_index] = (now, ret)
        return ret
    except Exception:
        return None


def _period_norm_prices(norm_index: str, period_end_ms: int, breed_size: int = 800,
                         spec_fingerprint: Optional[str] = None):
    """聚合给定 period_end(±3 天)内的 normalized_breed → avg_price + 元数据

    如果传 spec_fingerprint,会在 query 里加 filter + runtime_mappings 生成 spec_fingerprint 字段
    返回: {normalized_breed: {"price": float, "unit": str, "l3_name": str, "l1_name": str}}
    """
    range_query = {
        "range": {
            "period_end": {
                "gte": period_end_ms - 3 * 86400000,
                "lte": period_end_ms + 3 * 86400000,
            }
        }
    }
    if spec_fingerprint:
        query = {
            "bool": {
                "must": [range_query],
                "filter": [{"term": {"spec_fingerprint": spec_fingerprint}}],
            }
        }
    else:
        query = range_query

    body = {
        "size": 0,
        "query": query,
        "aggs": {
            "by_norm": {
                "terms": {"field": "normalized_breed.keyword", "size": breed_size},
                "aggs": {
                    "avg_price": {"avg": {"field": "price"}},
                    "unit": {"terms": {"field": "unit", "size": 1}},
                    "l3_name": {"terms": {"field": "category_name_l3.keyword", "size": 1}},
                    "l1_name": {"terms": {"field": "category_name_l1.keyword", "size": 1}},
                },
            }
        },
    }
    if spec_fingerprint:
        body.update(_spec_fingerprint_mapping())

    try:
        r = es.search(
            index=norm_index,
            body=body,
            ignore_unavailable=True,
            allow_no_indices=True,
        )
        result = {}
        for b in r.get("aggregations", {}).get("by_norm", {}).get("buckets", []):
            avg = b["avg_price"]["value"]
            if not avg or avg <= 0:
                continue
            result[b["key"]] = {
                "price": float(avg),
                "unit": b["unit"]["buckets"][0]["key"] if b["unit"]["buckets"] else "",
                "l3_name": b["l3_name"]["buckets"][0]["key"] if b["l3_name"]["buckets"] else "",
                "l1_name": b["l1_name"]["buckets"][0]["key"] if b["l1_name"]["buckets"] else "",
            }
        return result
    except Exception:
        return {}


def _enrich_breed_meta(breed_meta: dict, latest_row: dict):
    """v0.31: 把 _period_norm_prices* 返回的最新行里 l3_name / l1_name / unit 首次填进 breed_meta,
    + 累加 records(有数据的城市数)。

    只填当前为空的字段(首次非空胜出),不覆盖已有 filter_label 等 user-input 字段。
    """
    if not latest_row:
        return
    if not breed_meta.get("category_name_l3") and latest_row.get("l3_name"):
        breed_meta["category_name_l3"] = latest_row["l3_name"]
    if not breed_meta.get("category_name_l1") and latest_row.get("l1_name"):
        breed_meta["category_name_l1"] = latest_row["l1_name"]
    if not breed_meta.get("unit") and latest_row.get("unit"):
        breed_meta["unit"] = latest_row["unit"]
    breed_meta["records"] = (breed_meta.get("records") or 0) + 1


def _spec_fingerprint_mapping() -> dict:
    """runtime_mappings 内层:attr (nested k/v) 拼成 canonical spec_fingerprint
    跨城同 (breed, fingerprint) 即"同规格",可比性大幅提升
    返回的 dict 用 ** 解包进 body
    """
    return {
        "runtime_mappings": {
            "spec_fingerprint": {
                "type": "keyword",
                "script": {
                    "lang": "painless",
                    "source": (
                        "def parts = new ArrayList();"
                        "if (params._source.attr_norm != null) {"
                        "  for (def a : params._source.attr_norm) {"
                        "    if (a.k != null && a.v != null) { parts.add(a.k + '=' + a.v); }"
                        "  }"
                        "}"
                        "if (parts.isEmpty()) {"
                        "  if (params._source.spec != null) { parts.add(params._source.spec); }"
                        "  else { parts.add('(none)'); }"
                        "}"
                        "Collections.sort(parts);"
                        "emit(String.join('|', parts));"
                    )
                }
            }
        }
    }


def _period_norm_prices_by_attr(
    norm_index: str, period_end_ms: int, breed: str, filters: list,
):
    """按 (k, v) 嵌套 attr 过滤后聚合
    filters: [{"key": "thickness", "values": ["3mm", "5mm"]}, {"key": "material", "values": ["Q235"]}]
    返回: {breed: {"price": float, "unit": str, ...}}
    """
    range_query = {
        "range": {
            "period_end": {
                "gte": period_end_ms - 3 * 86400000,
                "lte": period_end_ms + 3 * 86400000,
            }
        }
    }
    nested_clauses = []
    for f in filters:
        # attr 不是 nested,需在 _source 上手动配对。虚拟字段 attr_kv = "k||v"，
        # terms filter 配合 bool/should + minimum_should_match: 1 实现每 key 至少一匹配
        kv_should = [{"term": {"attr_kv": f"{f['key']}||{v}"}} for v in f["values"]]
        nested_clauses.append({
            "bool": {
                "should": kv_should,
                "minimum_should_match": 1,
            }
        })
    bool_query = {
        "bool": {
            "must": [range_query, {"term": {"normalized_breed.keyword": breed}}] + nested_clauses
        }
    }
    body = {
        "size": 0,
        "query": bool_query,
        "runtime_mappings": {
            "attr_kv": {
                "type": "keyword",
                "script": {
                    "lang": "painless",
                    "source": "if (params._source.attr_norm != null) { for (def a : params._source.attr_norm) { if (a.k != null && a.v != null) { emit(a.k + '||' + a.v); } } }",
                }
            }
        },
        "aggs": {
            "by_norm": {
                "terms": {"field": "normalized_breed.keyword", "size": 5},
                "aggs": {
                    "avg_price": {"avg": {"field": "price"}},
                    "unit": {"terms": {"field": "unit", "size": 1}},
                    "l3_name": {"terms": {"field": "category_name_l3.keyword", "size": 1}},
                    "l1_name": {"terms": {"field": "category_name_l1.keyword", "size": 1}},
                },
            }
        },
    }
    try:
        r = es.search(
            index=norm_index,
            body=body,
            ignore_unavailable=True,
            allow_no_indices=True,
        )
        result = {}
        for b in r.get("aggregations", {}).get("by_norm", {}).get("buckets", []):
            avg = b["avg_price"]["value"]
            if not avg or avg <= 0:
                continue
            result[b["key"]] = {
                "price": float(avg),
                "unit": b["unit"]["buckets"][0]["key"] if b["unit"]["buckets"] else "",
                "l3_name": b["l3_name"]["buckets"][0]["key"] if b["l3_name"]["buckets"] else "",
                "l1_name": b["l1_name"]["buckets"][0]["key"] if b["l1_name"]["buckets"] else "",
            }
        return result
    except Exception:
        return {}


def _period_norm_prices_multi_specs(
    norm_index: str, period_end_ms: int, breed: str, spec_fingerprints: list,
):
    """多规格聚合: 一次 query 返回该 breed 下所有 spec_fingerprints 的均价
    返回: {spec_fingerprint: {"price": float, "unit": str, "l3_name": str, "l1_name": str}}
    """
    range_query = {
        "range": {
            "period_end": {
                "gte": period_end_ms - 3 * 86400000,
                "lte": period_end_ms + 3 * 86400000,
            }
        }
    }
    bool_query = {
        "bool": {
            "must": [
                range_query,
                {"term": {"normalized_breed.keyword": breed}},
            ],
            "filter": [{"terms": {"spec_fingerprint": spec_fingerprints}}],
        }
    }
    body = {
        "size": 0,
        "query": bool_query,
        "aggs": {
            "by_spec": {
                "terms": {"field": "spec_fingerprint", "size": len(spec_fingerprints) * 2},
                "aggs": {
                    "avg_price": {"avg": {"field": "price"}},
                    "unit": {"terms": {"field": "unit", "size": 1}},
                    "l3_name": {"terms": {"field": "category_name_l3.keyword", "size": 1}},
                    "l1_name": {"terms": {"field": "category_name_l1.keyword", "size": 1}},
                },
            }
        },
    }
    body.update(_spec_fingerprint_mapping())
    try:
        r = es.search(
            index=norm_index,
            body=body,
            ignore_unavailable=True,
            allow_no_indices=True,
        )
        result = {}
        for b in r.get("aggregations", {}).get("by_spec", {}).get("buckets", []):
            avg = b["avg_price"]["value"]
            if not avg or avg <= 0:
                continue
            result[b["key"]] = {
                "price": float(avg),
                "unit": b["unit"]["buckets"][0]["key"] if b["unit"]["buckets"] else "",
                "l3_name": b["l3_name"]["buckets"][0]["key"] if b["l3_name"]["buckets"] else "",
                "l1_name": b["l1_name"]["buckets"][0]["key"] if b["l1_name"]["buckets"] else "",
            }
        return result
    except Exception:
        return {}


def _safe_count(pattern: str) -> int:
    try:
        return int(es.count(index=pattern, ignore_unavailable=True, allow_no_indices=True).get("count", 0) or 0)
    except Exception:
        return 0


def _short_fp(fp: str) -> str:
    """把 'diameter=20|grade=HRB400' 简化显示用(给 API row label)"""
    if not fp:
        return ""
    return fp.split("|")[:3]  # 取前 3 段,过长会被 UI 截断


# ── 端点 ──────────────────────────────────────────────────

@router.get("/overview")
def overview():
    """KPI 概览: 数据规模 / 最新期 / 整体均价变动(跨城归一后口径)"""
    norm_list = _norm_indices()
    if not norm_list:
        return {"empty": True, "message": "无 norm 数据,请先跑 ETL 归一化"}

    # 总条数
    total_records = sum(_safe_count(idx) for idx in norm_list)

    # 跨城归一品种数
    breeds_count = 0
    try:
        r = es.search(
            index=",".join(norm_list),
            body={"size": 0, "aggs": {"breeds": {"cardinality": {"field": "normalized_breed.keyword"}}}},
            ignore_unavailable=True,
            allow_no_indices=True,
        )
        breeds_count = int(r.get("aggregations", {}).get("breeds", {}).get("value", 0) or 0)
    except Exception:
        pass

    # 每城最新两期（2026-07-23 修：0/1/2 期都计入，不再要求必须两期
    # 只要有 NORM 数据的城都进 cities_meta；不足两期时 prev_period_end
    # 走 0，_ms_to_date(0) 返 "",不会出 1970）
    cities_active = 0
    cities_meta = []
    latest_end_global = 0
    prev_end_global = 0
    for idx in norm_list:
        periods = _city_latest_two_periods(idx)
        cities_active += 1
        if periods:
            latest_end, prev_end = periods
        else:
            latest_end, prev_end = 0, 0
        latest_end_global = max(latest_end_global, latest_end)
        prev_end_global = max(prev_end_global, prev_end)
        cities_meta.append({
            "key": idx.replace("norm_", "").replace("_price", ""),
            "label": _city_label(idx),
            "latest_period_end": _ms_to_date(latest_end),
            "prev_period_end": _ms_to_date(prev_end),
        })

    # 整体均价变动:每城各自算本期/上期均价再取加权平均(按 common normalized_breed 数加权)
    overall_change_pct = 0.0
    weighted_sum = 0.0
    weight_total = 0
    for idx in norm_list:
        periods = _city_latest_two_periods(idx)
        if not periods:
            continue
        latest_end, prev_end = periods
        latest = _period_norm_prices(idx, latest_end, breed_size=2000)
        prev = _period_norm_prices(idx, prev_end, breed_size=2000)
        common = set(latest) & set(prev)
        if not common:
            continue
        curr_avg = sum(latest[k]["price"] for k in common) / len(common)
        prev_avg = sum(prev[k]["price"] for k in common) / len(common)
        if prev_avg > 0:
            change = (curr_avg - prev_avg) / prev_avg * 100
            weighted_sum += change * len(common)
            weight_total += len(common)
    if weight_total > 0:
        overall_change_pct = round(weighted_sum / weight_total, 2)

    return {
        "cities_count": cities_active,
        "total_records": total_records,
        "breeds_count": breeds_count,
        "overall_change_pct": overall_change_pct,
        "latest_period_end": _ms_to_date(latest_end_global),
        "prev_period_end": _ms_to_date(prev_end_global),
        "cities_meta": sorted(cities_meta, key=lambda c: c["label"]),
        "data_source": "norm_*_price",
    }


@router.get("/movers")
def movers(
    type: str = Query("up", pattern="^(up|down)$"),
    limit: int = Query(10, ge=1, le=50),
    city: Optional[str] = Query(None, description="可选:仅看某城 norm key (如 'xian')"),
):
    """涨幅榜 / 跌幅榜:每城各自取本期 vs 上期,normalized_breed 维度"""
    norm_list = _norm_indices()
    if city:
        norm_list = [f"norm_{city}_price"]

    candidates = []
    for norm_idx in norm_list:
        periods = _city_latest_two_periods(norm_idx)
        if not periods:
            continue
        latest_end, prev_end = periods

        latest_prices = _period_norm_prices(norm_idx, latest_end, breed_size=400)
        prev_prices = _period_norm_prices(norm_idx, prev_end, breed_size=400)

        city_label = _city_label(norm_idx)
        city_key = norm_idx.replace("norm_", "").replace("_price", "")

        common = set(latest_prices) & set(prev_prices)
        for breed in common:
            curr = latest_prices[breed]
            prev = prev_prices[breed]
            if prev["price"] <= 0 or curr["price"] <= 0:
                continue
            change_pct = (curr["price"] - prev["price"]) / prev["price"] * 100
            if abs(change_pct) < 0.5 or abs(change_pct) > 200:
                continue
            candidates.append({
                "breed": breed,
                "spec": "",
                "unit": curr["unit"] or prev["unit"],
                "city": city_key,
                "city_label": city_label,
                "prev_price": round(prev["price"], 2),
                "curr_price": round(curr["price"], 2),
                "change_abs": round(curr["price"] - prev["price"], 2),
                "change_pct": round(change_pct, 2),
            })

    reverse = (type == "up")
    candidates.sort(key=lambda x: x["change_pct"], reverse=reverse)
    return {"type": type, "total": len(candidates), "data": candidates[:limit]}


@router.get("/hot-categories")
def hot_categories(limit: int = Query(20, ge=1, le=50)):
    """热门品类(复合打分):跨城覆盖 × 数据密度 × 品种丰富度 × 时效"""
    norm_list = _norm_indices()
    if not norm_list:
        return {"data": []}
    try:
        # norm 的 update_date 是 date 类型(跨索引一致),无需 runtime_mappings
        r = es.search(
            index=",".join(norm_list),
            body={
                "size": 0,
                "aggs": {
                    "by_l3": {
                        "terms": {"field": "category_l3.keyword", "size": 200},
                        "aggs": {
                            "l3_name": {"terms": {"field": "category_name_l3.keyword", "size": 1}},
                            "l1_name": {"terms": {"field": "category_name_l1.keyword", "size": 1}},
                            "breeds": {"cardinality": {"field": "normalized_breed.keyword"}},
                            "cities": {"cardinality": {"field": "city"}},
                            "max_update": {"max": {"field": "update_date"}},
                            "avg_price": {"avg": {"field": "price"}},
                        },
                    }
                },
            },
            ignore_unavailable=True,
            allow_no_indices=True,
        )
        buckets = r.get("aggregations", {}).get("by_l3", {}).get("buckets", [])
        now_ms = int(datetime.now().timestamp() * 1000)

        results = []
        for b in buckets:
            l3 = b["key"]
            if not l3:
                continue
            breeds_n = int(b["breeds"]["value"])
            cities_n = int(b["cities"]["value"])
            records_n = b["doc_count"]
            latest_update = int(b["max_update"]["value"]) if b["max_update"]["value"] else 0
            days_old = max(0, (now_ms - latest_update) / 86400000) if latest_update else 365
            l3_name = b["l3_name"]["buckets"][0]["key"] if b["l3_name"]["buckets"] else l3
            l1_name = b["l1_name"]["buckets"][0]["key"] if b["l1_name"]["buckets"] else ""

            # 复合打分(归一到 0-100):
            # - 跨城覆盖 cities_n / 20 → 30 分
            # - 数据密度 log10(records_n)/6 → 20 分
            # - 品种丰富度 log10(breeds_n)/3 → 20 分
            # - 时效 1/(1+days_old/30) → 30 分
            score = (
                min(cities_n / 20, 1) * 30 +
                min(math.log10(records_n + 1) / 6, 1) * 20 +
                min(math.log10(breeds_n + 1) / 3, 1) * 20 +
                (1 / (1 + days_old / 30)) * 30
            )
            results.append({
                "category_l3": l3,
                "category_name_l3": l3_name,
                "category_name_l1": l1_name,
                "breeds_count": breeds_n,
                "cities_count": cities_n,
                "records_count": records_n,
                "days_old": round(days_old, 1),
                "score": round(score, 2),
            })

        results.sort(key=lambda x: x["score"], reverse=True)
        return {"data": results[:limit]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/change-heatmap")
def change_heatmap(
    breeds: Optional[str] = Query(None, description="品种列表(逗号分隔,v0.28 支持多选热力图)"),
    breed: Optional[str] = Query(None, description="(deprecated)单品种,兼容用,优先用 breeds"),
    attr_filters: Optional[str] = Query(None, description="共用筛选 'k1:v1,v2;k2:v3'(AND,所有品种都用)"),
    breed_filters: Optional[str] = Query(None, description="v0.37 per-breed 独立筛选 'breed1=k:v;k:v||breed2=k:v'(每个品种各自配置,优先于 attr_filters)"),
):
    """品类 × 城市 热力图。模式:
    1) 无 breeds: 返回空(产品搜索走 /breed-search,选中后跳到模式 2/3)
    2) ?breeds=A,B,C: 多品种 × 城市(每行一个品种,跨品种可比)
    3) ?breeds=A,B&attr_filters=k:v,k:v: 共用筛选,所有品种都套同一组 attr filters
    4) ?breeds=A,B&breed_filters=A=k:v;k:v||B=k:v: per-breed 独立筛选(v0.37,每个品种各自的 attr 配置)
    """
    _ = random  # noqa: F401  # 预留 import 后续可能用(以前随机抽样)
    # v0.28: 解析 breeds 列表(支持多选热力图);breed 单数兼容老调用
    breed_list = []
    if breeds:
        breed_list = [b.strip() for b in breeds.split(",") if b.strip()]
    elif breed:
        breed_list = [breed]
    norm_list = _norm_indices()
    if not norm_list:
        return {"breeds": [], "cities": [], "matrix": []}

    # 解析共用 attr_filters(v0.37 兼容,作为 per-breed 的 fallback)
    filters = []
    if attr_filters:
        for kv in attr_filters.split(";"):
            if ":" not in kv:
                continue
            k, vs = kv.split(":", 1)
            values = [v for v in vs.split(",") if v]
            if k and values:
                filters.append({"key": k, "values": values})

    # v0.37: 解析 per-breed 独立筛选 'breed1=k:v;k:v||breed2=k:v'
    # 格式:多个 breed 之间用 '||' 分隔(避免和 breed 名里可能的逗号冲突)
    #       breed 名后 '=' 接 filters
    #       filters 之间 ';' 分隔 k:v 单元(同 attr_filters 内部格式)
    per_breed_filters = {}  # dict[breed, list[filter]]
    if breed_filters:
        for segment in breed_filters.split("||"):
            if "=" not in segment:
                continue
            breed_part, filters_part = segment.split("=", 1)
            breed_key = breed_part.strip()
            breed_filter_list = []
            for kv in filters_part.split(";"):
                if ":" not in kv:
                    continue
                k, vs = kv.split(":", 1)
                values = [v for v in vs.split(",") if v]
                if k and values:
                    breed_filter_list.append({"key": k, "values": values})
            if breed_key and breed_filter_list:
                per_breed_filters[breed_key] = breed_filter_list

    # 1) 选行
    # v0.23 (2026-07-23): 删 top 15 随机模式(原 v0.21/v0.22 逻辑) — 改由 /breed-search
    # 端点返回候选品种 + 规格信息,用户选中后才进热力图。未选品种时直接返空。
    # v0.28: 多选 — breeds 列表生成 N 行
    if not breed_list:
        return {"breeds": [], "cities": [], "matrix": []}
    if filters and breed_list:
        # 过滤模式:N 行(filter 表达式作为标签,所有品种共用)
        # v0.2 (2026-07-22): attr key 翻译为中文,跟 /trend 拆分维度字段一致
        filter_label = " + ".join(
            f"{_label_k(f['key'])}={'/'.join(f['values'])}" for f in filters
        )
        breeds = []
        row_keys = []
        for b in breed_list:
            breeds.append({
                "breed": b,
                "category_name_l3": "",
                "category_name_l1": "",
                "unit": "",
                "records": 0,
                "filter_label": filter_label,
            })
            row_keys.append(b)
    else:
        breeds = []
        row_keys = []
        for b in breed_list:
            breeds.append({
                "breed": b,
                "category_name_l3": "",
                "category_name_l1": "",
                "unit": "",
                "records": 0,
            })
            row_keys.append(b)

    # 2) 城市列表
    cities = []
    idx_set = set(norm_list)
    for s in _registry_get_all():
        dws = s.get("dws_index")
        if dws:
            norm_equiv = dws.replace("dws_", "norm_")
            if norm_equiv in idx_set:
                cities.append({"key": s["key"], "label": s.get("label", s["key"])})
    cities.sort(key=lambda c: c["label"])

    # 3) 每城查最新两期,构建矩阵
    matrix = [[None] * len(cities) for _ in row_keys]

    for ci, city_info in enumerate(cities):
        norm_idx = next(
            (idx for idx in norm_list if idx.replace("norm_", "").replace("_price", "") == city_info["key"]),
            None,
        )
        if not norm_idx:
            continue
        periods = _city_latest_two_periods(norm_idx)
        if not periods:
            continue
        latest_end, prev_end = periods

        if filters or per_breed_filters:
            # v0.28 + v0.37: 共用筛选 OR per-breed 独立筛选 — per-breed 优先
            for bi, breed_key in enumerate(row_keys):
                # v0.37: per-breed 独立筛选优先,fallback 到共用 attr_filters
                breed_filters_to_use = per_breed_filters.get(breed_key, filters)
                if not breed_filters_to_use:
                    # 无任何筛选 → 跳过(没意义调 _period_norm_prices_by_attr)
                    continue
                latest = _period_norm_prices_by_attr(norm_idx, latest_end, breed_key, breed_filters_to_use)
                prev = _period_norm_prices_by_attr(norm_idx, prev_end, breed_key, breed_filters_to_use)
                if breed_key in latest and breed_key in prev:
                    curr_p = latest[breed_key]["price"]
                    prev_p = prev[breed_key]["price"]
                    if prev_p > 0:
                        matrix[bi][ci] = round((curr_p - prev_p) / prev_p * 100, 2)
                    # v0.31: 从 latest 首次填 breeds[bi] 元数据(不覆盖已有)
                    _enrich_breed_meta(breeds[bi], latest[breed_key])
        else:
            # 多 breed 模式(混合,无规格对齐)
            latest = _period_norm_prices(norm_idx, latest_end, breed_size=1500)
            prev = _period_norm_prices(norm_idx, prev_end, breed_size=1500)
            for bi, breed_key in enumerate(row_keys):
                if breed_key in latest and breed_key in prev:
                    curr_p = latest[breed_key]["price"]
                    prev_p = prev[breed_key]["price"]
                    if prev_p > 0:
                        matrix[bi][ci] = round((curr_p - prev_p) / prev_p * 100, 2)
                    # v0.31: 同上 — 首次填元数据,累加 records
                    _enrich_breed_meta(breeds[bi], latest[breed_key])

    return {
        "breeds": breeds,
        "cities": cities,
        "matrix": matrix,
        "attr_filters": filters,
        # v0.2 (2026-07-22): 输出 spec_label alias = filter_label (兼容前端 spec_label 字段名)
        "spec_label": next((b.get("filter_label", "") for b in breeds if b.get("filter_label")), ""),
    }


# 2026-07-23 v0.23: 产品名搜索端点 — /market 页面删 top 15 下拉后,
# 搜索成为主入口。需要返回品种 + 规格信息让用户综合选择。
#
# ES nested agg 一次拿:
#   filter(wildcard) > terms(normalized_breed) > nested(attr_norm) > terms(k) > terms(v)
#
# 例: 搜 "给水管" → results[i]:
#   {breed: "PP-R给水管", category_name_l3: "塑料给水管",
#    spec_attrs: {diameter: ["20mm","25mm","40mm"], thickness: ["2.8mm","3.7mm"]},
#    spec_summary: "diameter: 20/25/40 · thickness: 2.8/3.7",
#    records: 12}
#
# 设计决策:
#   - wildcard on normalized_breed.keyword(同 v0.22 change-heatmap 的搜索方案)
#   - attr_norm 是 nested 类型,直接对 k/v 聚合会污染,必须用 nested agg 包一层
#   - 不需要装 IK/jieba(同 v0.22 论述)
#   - 大小写敏感(ES 8.17 terms agg 不支持 case_insensitive)
@router.get("/breed-search")
def breed_search(
    q: str = Query(..., min_length=1, max_length=50, description="产品名搜索词,wildcard 匹配 normalized_breed"),
    limit: int = Query(30, ge=1, le=100, description="返回品种数上限"),
):
    norm_list = _norm_indices()
    if not norm_list:
        return {"results": [], "total_breeds": 0, "matched_docs": 0, "query": q}

    import re
    body = {
        "size": 0,
        "aggs": {
            "matched_breeds": {
                "filter": {
                    "wildcard": {
                        # ES wildcard query 语法是 *  (regexp query 才是 .*)
                        # 实测: *PP-R* 返 34 命中, .*PP-R.* 返 0
                        # 用 *q* + re.escape 防用户输入的正则元字符被当通配符
                        "normalized_breed.keyword": f"*{re.escape(q)}*"
                    }
                },
                "aggs": {
                    "breeds": {
                        "terms": {"field": "normalized_breed.keyword", "size": limit},
                        "aggs": {
                            "l3": {"terms": {"field": "category_name_l3.keyword", "size": 1}},
                            "all_specs": {
                                "nested": {"path": "attr_norm"},
                                "aggs": {
                                    "by_k": {
                                        # attr_norm.k / .v 是 text 字段,不是 .keyword
                                        # (mapping 里 nested attr_norm: ['k', 'v'] 无 keyword 子字段)
                                        # text 字段 terms agg 需 fielddata,本地 ES 8.17 默认开(已验返 1140 buckets)
                                        "terms": {"field": "attr_norm.k", "size": 10},
                                        "aggs": {
                                            "values": {
                                                "terms": {"field": "attr_norm.v", "size": 30}
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    }
    try:
        r = es.search(
            index=",".join(norm_list),
            body=body,
            ignore_unavailable=True,
            allow_no_indices=True,
        )
        matched = r["aggregations"]["matched_breeds"]
        results = []
        for breed_bucket in matched["breeds"]["buckets"]:
            breed = breed_bucket["key"]
            l3 = breed_bucket["l3"]["buckets"][0]["key"] if breed_bucket["l3"]["buckets"] else ""
            spec_attrs = {}
            for k_bucket in breed_bucket["all_specs"]["by_k"]["buckets"]:
                spec_attrs[k_bucket["key"]] = [v["key"] for v in k_bucket["values"]["buckets"]]
            spec_summary = _summarize_specs(spec_attrs)
            results.append({
                "breed": breed,
                "category_name_l3": l3,
                "spec_attrs": spec_attrs,
                "spec_summary": spec_summary,
                "records": breed_bucket["doc_count"],
            })
        return {
            "results": results,
            "total_breeds": len(results),
            "matched_docs": matched["doc_count"],
            "query": q,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def _summarize_specs(spec_attrs: dict, max_keys: int = 3, max_values_per_key: int = 3) -> str:
    """spec_attrs 拼成简短可读摘要
    {'diameter': ['20mm','25mm','40mm'], 'thickness': ['2.8mm','3.7mm']}
    → 'diameter: 20/25/40 · thickness: 2.8/3.7'
    """
    if not spec_attrs:
        return ""
    parts = []
    for k, vs in list(spec_attrs.items())[:max_keys]:
        v_str = "/".join(vs[:max_values_per_key])
        if len(vs) > max_values_per_key:
            v_str += f"/+{len(vs) - max_values_per_key}"
        parts.append(f"{k}: {v_str}")
    return " · ".join(parts)


# 2026-07-23 v0.25: /market 页面默认随机展示 — 让首屏有内容
# 2026-07-23 v0.26: HARDCODE count=12, 不接参数 — 防滥用 + 池大小也固化
# 复用 nested agg 拿规格信息(同 /breed-search),样本来源是 terms agg 大桶 + random.sample
RANDOM_BREEDS_COUNT = 12  # 前端调 /api/market/random-breeds 不带参,服务端固定 12
RANDOM_BREEDS_POOL_SIZE = max(RANDOM_BREEDS_COUNT * 20, 200)  # 池子大点保多样性

RELATED_BREEDS_DEFAULT_LIMIT = 12  # v0.33: /related-breeds 默认返回数
RELATED_BREEDS_POOL_SIZE = 60     # ES terms agg 取的多一些(60),Python 端排序后截 limit

@router.get("/related-breeds")
def related_breeds(
    q: Optional[str] = Query(None, max_length=50, description="搜索词(可选),wildcard 匹配 normalized_breed"),
    breeds: Optional[str] = Query(None, description="已选品种(逗号分隔,可选),作为相邻参考 — 抽它们的 l1/l2/l3"),
    limit: int = Query(RELATED_BREEDS_DEFAULT_LIMIT, ge=1, le=50, description="返回品种数上限"),
):
    """v0.33: 推荐相邻品种 — 搜索词 + 已选品种的"同 l3 不同规格 / 同 l2 不同 l3"排序。

    三种 mode 互斥:
      1. breeds 非空 → 抽已选品种的 l1/l2/l3,排除已选,返回同 l3/l2/l1 的其他品种
      2. q 非空 + breeds 空 → 全池里 wildcard 匹配 q,按 records 排
      3. 都没 → fallback:全池 records 最高的(同 random-breeds 但更稳定)

    Python 端打分:同 l3 +100,同 l2 +50,同 l1 +20,名称含 q +30,records 加权 0.5×
    """
    import re  # wildcard 字符 escape
    norm_list = _norm_indices()
    if not norm_list:
        return {"results": [], "mode": "empty", "q": q or "", "selected": breeds or "", "total_matched": 0}

    selected = []
    if breeds:
        selected = [b.strip() for b in breeds.split(",") if b.strip()]

    # 1. 拿已选 breeds 的 l1/l2/l3 分布
    l3_set: list = []
    l2_set: list = []
    l1_set: list = []
    if selected:
        try:
            r_meta = es.search(
                index=",".join(norm_list),
                body={
                    "size": 0,
                    "query": {"terms": {"normalized_breed.keyword": selected}},
                    "aggs": {
                        "by_l3": {"terms": {"field": "category_name_l3.keyword", "size": 30}},
                        "by_l2": {"terms": {"field": "category_name_l2.keyword", "size": 30}},
                        "by_l1": {"terms": {"field": "category_name_l1.keyword", "size": 10}},
                    },
                },
                ignore_unavailable=True, allow_no_indices=True,
            )
            l3_set = [b["key"] for b in r_meta["aggregations"]["by_l3"]["buckets"] if b["key"]]
            l2_set = [b["key"] for b in r_meta["aggregations"]["by_l2"]["buckets"] if b["key"]]
            l1_set = [b["key"] for b in r_meta["aggregations"]["by_l1"]["buckets"] if b["key"]]
        except Exception as e:
            print(f"[related-breeds] meta agg error: {e}", flush=True)

    # 2. 构建 bool query
    should_filters: list = []
    if l3_set:
        should_filters.append({"terms": {"category_name_l3.keyword": l3_set}})
    if l2_set:
        should_filters.append({"terms": {"category_name_l2.keyword": l2_set}})
    if l1_set:
        should_filters.append({"terms": {"category_name_l1.keyword": l1_set}})

    must_not_filters: list = []
    if selected:
        must_not_filters.append({"terms": {"normalized_breed.keyword": selected}})

    bool_q: dict = {"bool": {}}
    if should_filters:
        bool_q["bool"]["should"] = should_filters
        bool_q["bool"]["minimum_should_match"] = 1
    if must_not_filters:
        bool_q["bool"]["must_not"] = must_not_filters
    if q:
        bool_q["bool"]["must"] = [{"wildcard": {"normalized_breed.keyword": f"*{re.escape(q)}*"}}]

    # 3. 决定 mode + query
    if not should_filters and not q:
        query = {"match_all": {}}
        mode = "popular"          # 全池 records 最高的(冷启动兜底)
    elif not should_filters and q:
        query = bool_q
        mode = "search-only"      # 无已选,纯搜索词匹配
    else:
        query = bool_q
        mode = "related-to-selected"  # 主要场景:基于已选找相邻

    pool_size = RELATED_BREEDS_POOL_SIZE
    body = {
        "size": 0,
        "query": query,
        "aggs": {
            "by_norm": {
                "terms": {"field": "normalized_breed.keyword", "size": pool_size},
                "aggs": {
                    "l3": {"terms": {"field": "category_name_l3.keyword", "size": 1}},
                    "l2": {"terms": {"field": "category_name_l2.keyword", "size": 1}},
                    "l1": {"terms": {"field": "category_name_l1.keyword", "size": 1}},
                    "all_specs": {
                        "nested": {"path": "attr_norm"},
                        "aggs": {
                            "by_k": {
                                "terms": {"field": "attr_norm.k", "size": 10},
                                "aggs": {
                                    "values": {
                                        "terms": {"field": "attr_norm.v", "size": 30}
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    }
    try:
        r = es.search(
            index=",".join(norm_list),
            body=body,
            ignore_unavailable=True, allow_no_indices=True,
        )
        results = []
        for b in r["aggregations"]["by_norm"]["buckets"]:
            breed = b["key"]
            l3 = b["l3"]["buckets"][0]["key"] if b["l3"]["buckets"] else ""
            l2 = b["l2"]["buckets"][0]["key"] if b["l2"]["buckets"] else ""
            l1 = b["l1"]["buckets"][0]["key"] if b["l1"]["buckets"] else ""

            # v0.33: Python 端打分(l3 优先 > records 加权)
            score = 0
            if l3_set and l3 in l3_set:
                score += 100
            if l2_set and l2 in l2_set:
                score += 50
            if l1_set and l1 in l1_set:
                score += 20
            if q and q.lower() in breed.lower():
                score += 30
            score += b["doc_count"] * 0.5

            spec_attrs = {}
            for k_bucket in b["all_specs"]["by_k"]["buckets"]:
                spec_attrs[k_bucket["key"]] = [v["key"] for v in k_bucket["values"]["buckets"]]
            spec_summary = _summarize_specs(spec_attrs)
            results.append({
                "breed": breed,
                "category_name_l3": l3,
                "spec_attrs": spec_attrs,
                "spec_summary": spec_summary,
                "records": b["doc_count"],
                "relevance": round(score, 1),
            })
        results.sort(key=lambda x: x["relevance"], reverse=True)
        return {
            "results": results[:limit],
            "mode": mode,
            "q": q or "",
            "selected": breeds or "",
            "total_matched": len(results),
        }
    except Exception as e:
        print(f"[related-breeds] search error: {e}", flush=True)
        return {"results": [], "mode": "error", "q": q or "", "selected": breeds or "", "error": str(e)}


@router.get("/random-breeds")
def random_breeds():
    """默认随机 12 个产品。count 硬编码防滥用 — 不接受参数。"""
    count = RANDOM_BREEDS_COUNT
    norm_list = _norm_indices()
    if not norm_list:
        return {"results": [], "total": 0, "count": count}

    pool_size = RANDOM_BREEDS_POOL_SIZE
    body = {
        "size": 0,
        "aggs": {
            "all_breeds": {
                "terms": {"field": "normalized_breed.keyword", "size": pool_size},
                "aggs": {
                    "l3": {"terms": {"field": "category_name_l3.keyword", "size": 1}},
                    "all_specs": {
                        "nested": {"path": "attr_norm"},
                        "aggs": {
                            "by_k": {
                                "terms": {"field": "attr_norm.k", "size": 10},
                                "aggs": {
                                    "values": {
                                        "terms": {"field": "attr_norm.v", "size": 30}
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    }
    try:
        r = es.search(
            index=",".join(norm_list),
            body=body,
            ignore_unavailable=True,
            allow_no_indices=True,
        )
        all_buckets = r["aggregations"]["all_breeds"]["buckets"]
        n_pick = min(len(all_buckets), count)
        sampled = random.sample(all_buckets, n_pick) if n_pick > 0 else []
        sampled.sort(key=lambda b: b["doc_count"], reverse=True)
        results = []
        for breed_bucket in sampled:
            breed = breed_bucket["key"]
            l3 = breed_bucket["l3"]["buckets"][0]["key"] if breed_bucket["l3"]["buckets"] else ""
            spec_attrs = {}
            for k_bucket in breed_bucket["all_specs"]["by_k"]["buckets"]:
                spec_attrs[k_bucket["key"]] = [v["key"] for v in k_bucket["values"]["buckets"]]
            spec_summary = _summarize_specs(spec_attrs)
            results.append({
                "breed": breed,
                "category_name_l3": l3,
                "spec_attrs": spec_attrs,
                "spec_summary": spec_summary,
                "records": breed_bucket["doc_count"],
            })
        return {"results": results, "total": len(results), "count": count}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/attr-keys")
def attr_keys(
    breed: str = Query(None, description="单品种名(向后兼容,优先 breeds)"),
    breeds: str = Query(None, description="多品种名,逗号分隔(2026-07-24: 12 个默认品种属性不能遗漏)"),
    limit_per_value: int = Query(30, ge=1, le=100),
):
    """列出某归一种下所有 (k, [v1, v2, ...]) 组合 + 文档数
    用于前端 k=v 自由组合选择。attr 在 norm 索引中不是 nested,是普通 object 配 k/v 平行数组。
    用 runtime_mappings 虚拟字段 attr_kv = 'k||v' 做聚合。
    2026-07-24: 支持 breeds=A,B,C 逗号分隔 — /market 默认 12 个品种不漏属性
    """
    from collections import defaultdict
    norm_list = _norm_indices()
    if not norm_list:
        return {"data": []}

    # 解析品种列表(优先 breeds,其次单 breed)
    breed_list = []
    if breeds:
        breed_list = [b.strip() for b in breeds.split(",") if b.strip()]
    elif breed:
        breed_list = [breed.strip()]
    if not breed_list:
        return {"data": []}

    # 跨索引聚合(runtime_mappings 解决了 mapping 不一致问题)
    # 单品种 → term; 多品种 → terms (任一匹配)
    if len(breed_list) == 1:
        breed_query = {"term": {"normalized_breed.keyword": breed_list[0]}}
    else:
        breed_query = {"terms": {"normalized_breed.keyword": breed_list}}

    body = {
        "size": 0,
        "query": breed_query,
        "runtime_mappings": {
            "attr_kv": {
                "type": "keyword",
                "script": {
                    "lang": "painless",
                    "source": "if (params._source.attr_norm != null) { for (def a : params._source.attr_norm) { if (a.k != null && a.v != null) { emit(a.k + '||' + a.v); } } }",
                },
            }
        },
        "aggs": {
            "kv_pairs": {
                "terms": {"field": "attr_kv", "size": limit_per_value * 5},
            }
        },
    }
    try:
        r = es.search(
            index=",".join(norm_list),
            body=body,
            ignore_unavailable=True,
            allow_no_indices=True,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    # 拼装:{k: {v: docs}}
    key_agg: dict = defaultdict(lambda: defaultdict(int))
    for b in r.get("aggregations", {}).get("kv_pairs", {}).get("buckets", []):
        kv = b["key"]
        if "||" not in kv:
            continue
        k, v = kv.split("||", 1)
        key_agg[k][v] += b["doc_count"]

    result = []
    for k, vs in key_agg.items():
        values = [{"value": v, "docs": docs} for v, docs in sorted(vs.items(), key=lambda x: x[1], reverse=True)]
        total = sum(vs.values())
        # v0.2 (2026-07-22): 加 label 中文字段（与 trend 页 /拆分维度 保持一致）
        result.append({"key": k, "label": _label_k(k), "values": values, "total_docs": total})
    result.sort(key=lambda x: x["total_docs"], reverse=True)
    return {"data": result}


@router.get("/spec-fingerprints")
def spec_fingerprints(
    breed: str = Query(..., description="归一品种名 (normalized_breed)"),
    min_cities: int = Query(2, ge=1, le=20, description="最小城市覆盖数(过滤稀疏)"),
    limit: int = Query(20, ge=1, le=50),
):
    """列出某归一种下所有跨城共现的规格指纹,按城市覆盖数倒序
    用法: GET /api/market/spec-fingerprints?breed=热轧等边角钢
    返回: {"data": [{"fingerprint": "..."", "cities_count": N, "records": M, "sample_spec": "..."}]}
    """
    norm_list = _norm_indices()
    if not norm_list:
        return {"data": []}
    try:
        body = {
            "size": 0,
            "query": {"term": {"normalized_breed.keyword": breed}},
            "aggs": {
                "by_fp": {
                    "terms": {"field": "spec_fingerprint", "size": 200},
                    "aggs": {
                        "cities": {"cardinality": {"field": "city"}},
                        "sample": {"top_hits": {"size": 1, "_source": ["spec"]}},
                    },
                }
            },
        }
        body.update(_spec_fingerprint_mapping())
        r = es.search(
            index=",".join(norm_list),
            body=body,
            ignore_unavailable=True,
            allow_no_indices=True,
        )
        buckets = r.get("aggregations", {}).get("by_fp", {}).get("buckets", [])
        results = []
        for b in buckets:
            cities_n = int(b["cities"]["value"])
            if cities_n < min_cities:
                continue
            hits = b.get("sample", {}).get("hits", {}).get("hits", [])
            sample_spec = hits[0].get("_source", {}).get("spec", "") if hits else ""
            results.append({
                "fingerprint": b["key"],
                "cities_count": cities_n,
                "records": b["doc_count"],
                "sample_spec": sample_spec,
            })
        results.sort(key=lambda x: (x["cities_count"], x["records"]), reverse=True)
        return {"data": results[:limit]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))