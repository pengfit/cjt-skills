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
import requests
from datetime import datetime
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from api.skill_registry import get_all as _registry_get_all
from api.routes.norm_trend import norm_price_trend as _norm_price_trend_inner  # 2026-07-28: /market 双卡片复用 /trend 的 NORM 取数逻辑

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


# 2026-07-28: 省份 → skill keys 映射（给 random-breeds / breed-trend 的 province 参数用）
def _skill_keys_by_province(province: str) -> list:
    """返回某省份下所有 skill key（如 '山东' → ['qingdao','weihai','heze','jinan','rizhao']）"""
    if not province:
        return []
    return [s["key"] for s in _registry_get_all() if s.get("province") == province]


def _city_latest_two_periods(norm_index: str):
    """用 runtime_mappings 把 period_end 转为 keyword,terms agg 取最近 2 个 unique 值。
    适用于所有期刊节奏 (月刊/双月刊/季刊),不依赖 date_histogram 的 bucket 粒度。
    2026-07-24: 允许仅 1 期时也返回 (latest, None) — 单期也能跑 _period_norm_prices 拿 l3/l1,
    只是拿不到变化率。
    返回 (latest_period_end_ms, prev_period_end_ms | None) | None(总失败)
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
        if not buckets:
            return None
        # 2026-07-24: 改 — len 1 也允许(返回 latest + None)
        # 原来 len(buckets) < 2 直接 None,导致单期城市整个被跳过,meta 永远填不上
        if len(buckets) < 2:
            print(f"[market] _city_latest_two_periods({norm_index}) 仅 1 期,变化率将为 None", flush=True)
        # key 是 ISO 字符串 (如 "2026-06-30T00:00:00.000Z"),转 epoch ms
        result = []
        for b in buckets[:2]:
            try:
                pe_str = b["key"]
                # 2026-07-24: 兼容两种格式 — ES date 字段 toString() 返回 epoch ms 数字串("1774915200000"),
                # 旧版本可能是 ISO 日期串("2026-03-31T08:00:00.000Z")。isnumeric 优先走数字路径。
                try:
                    if pe_str.isdigit():
                        pe_ms = int(pe_str)
                    else:
                        pe_clean = pe_str.replace("Z", "+00:00")
                        pe_dt = datetime.fromisoformat(pe_clean)
                        pe_ms = int(pe_dt.timestamp() * 1000)
                    result.append(pe_ms)
                except Exception:
                    continue
            except Exception:
                continue
        if not result:
            return None
        # 2026-07-24: 只有 1 期时 prev 置 None(调用方需判断)
        if len(result) == 1:
            ret = (result[0], None)
        else:
            ret = (result[0], result[1])
        _city_period_cache[norm_index] = (now, ret)
        return ret
    except Exception:
        return None


def _city_latest_publish_date(norm_index: str):
    """最新 source_publish_date 聚合 (ms epoch) — 数据治理透明卡 / 整体新鲜度用

    区别于 _city_latest_two_periods(用 period_end):
    - period_end            = 数据覆盖期结束日(本期 vs 上期 涨跌幅对比有意义)
    - source_publish_date   = ODS 实际发布时间(数据新鲜度有意义)

    2026-07-26 修:之前 latest_end + age_days 都用 period_end 算,导致
      - jilin   period_end=2026-06-30  source_publish_date=2026-07-08  (6 月数据 7 月 8 号才发)
      - jiangxi period_end=2026-07-31  source_publish_date=2026-07-07  (7 月 7 号发,覆盖 7 月)
      - henan   period_end=2026-04-30  source_publish_date=2026-07-03  (4 月数据 7 月 3 号才发,差 64 天)

    2026-07-26 (2): 6 城(sichuan/xinjiang/rizhao/jinan/xian/chongqing)把 source_publish_date
    存成 text 类型(值 "YYYY-MM-DD HH:MM:SS" 空格分隔),不是 date(ISO 8601 'T' 分隔)。
    ES 直接 `max` 聚合在 text 字段上会报 "Fielddata is disabled" 错误(默认 text 字段不启 fielddata)。

    方案:`max` + `script` 参数,Painlessly 取 _source.source_publish_date 转 ISO 8601,再解析成 epoch ms。
      - date 类型源:_source 里是 ISO 8601 字符串("2026-07-08T18:01:34"),Instant.parse 直接成功
      - text  类型源:是空格分隔的 "2026-07-04 07:49:02",replace 空格为 T 后用 LocalDateTime.parse + UTC 兜底
    两种解析都失败时返 0,被外层 `if not max_ms: return None` 过滤掉(避免崩 500)。

    返回: ms(epoch) | None
    """
    now = time.time()
    cache_key = f"pub::{norm_index}"
    cached = _city_period_cache.get(cache_key)
    if cached and (now - cached[0]) < _CITY_PERIOD_TTL_S:
        return cached[1]
    try:
        body = {
            "size": 0,
            "aggs": {
                "max_pub": {
                    "max": {
                        "script": {
                            "lang": "painless",
                            "source": (
                                "if (params._source == null || !params._source.containsKey('source_publish_date') || params._source.source_publish_date == null) return null;"
                                "String s = params._source.source_publish_date.toString().replace(' ', 'T');"
                                "long ms = 0L;"
                                "try { ms = java.time.Instant.parse(s).toEpochMilli(); }"
                                "catch (Exception e) {"
                                "  try { ms = java.time.LocalDateTime.parse(s).atZone(java.time.ZoneOffset.UTC).toInstant().toEpochMilli(); }"
                                "  catch (Exception e2) { ms = 0L; }"
                                "}"
                                "return ms;"
                            ),
                        }
                    }
                }
            },
        }
        r = es.search(
            index=norm_index,
            body=body,
            ignore_unavailable=True,
            allow_no_indices=True,
        )
        max_ms = r.get("aggregations", {}).get("max_pub", {}).get("value", 0) or 0
        if not max_ms:
            return None
        _city_period_cache[cache_key] = (now, max_ms)
        return max_ms
    except Exception:
        return None


def _city_latest_update_date(ods_index: str):
    """最新 ODS update_date 聚合 (ms epoch) — 数据治理透明卡 / 数据新鲜度用

    区别于 _city_latest_publish_date (走 NORM source_publish_date):
    - update_date           = ODS 入库时间(数据治理透明卡的"新鲜度"更准 — 抓到我们系统的时间)
    - source_publish_date   = 政府发布时间(NORM 层规范化,部分城市抓得晚 → 时间远早于实际入库)

    部分 ODS 索引(如 heze)的 update_date 是 keyword 不是 date,直接 max 聚合会失败,
    用 max+script 取 _source.update_date。ODS update_date 三种常见格式都兜底:
      - "YYYY-MM-DDTHH:MM:SSZ"   → Instant.parse
      - "YYYY-MM-DD HH:MM:SS"    → LocalDateTime.parse (空格先替 T)
      - "YYYY-MM-DD"             → LocalDate.parse (纯日期,atStartOfDay(UTC))
    全失败时返 0,被外层过滤(避免崩 500)。

    返回: ms(epoch) | None
    """
    now = time.time()
    cache_key = f"upd::{ods_index}"
    cached = _city_period_cache.get(cache_key)
    if cached and (now - cached[0]) < _CITY_PERIOD_TTL_S:
        return cached[1]
    try:
        body = {
            "size": 0,
            "aggs": {
                "max_upd": {
                    "max": {
                        "script": {
                            "lang": "painless",
                            "source": (
                                "if (params._source == null || !params._source.containsKey('update_date') || params._source.update_date == null) return null;"
                                "String s = params._source.update_date.toString().replace(' ', 'T');"
                                "long ms = 0L;"
                                "try { ms = java.time.Instant.parse(s).toEpochMilli(); }"
                                "catch (Exception e) {"
                                "  try { ms = java.time.LocalDateTime.parse(s).atZone(java.time.ZoneOffset.UTC).toInstant().toEpochMilli(); }"
                                "  catch (Exception e2) {"
                                "    try { ms = java.time.LocalDate.parse(s).atStartOfDay(java.time.ZoneOffset.UTC).toInstant().toEpochMilli(); }"
                                "    catch (Exception e3) { ms = 0L; }"
                                "  }"
                                "}"
                                "return ms;"
                            ),
                        }
                    }
                }
            },
        }
        r = es.search(
            index=ods_index,
            body=body,
            ignore_unavailable=True,
            allow_no_indices=True,
        )
        max_ms = r.get("aggregations", {}).get("max_upd", {}).get("value", 0) or 0
        if not max_ms:
            return None
        _city_period_cache[cache_key] = (now, max_ms)
        return max_ms
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
    # 2026-07-26: 同步拿 publish_date — 新增字段,旧字段保留(驱动本期 vs 上期 均价对比)
    cities_active = 0
    cities_meta = []
    latest_end_global = 0
    prev_end_global = 0
    latest_publish_global = 0
    for idx in norm_list:
        periods = _city_latest_two_periods(idx)
        publish_ms = _city_latest_publish_date(idx) or 0
        cities_active += 1
        if periods:
            latest_end, prev_end = periods
        else:
            latest_end, prev_end = 0, 0
        latest_end_global = max(latest_end_global, latest_end)
        # 2026-07-24: prev_end 可能为 None(单期城市) — max 不支持 None,转为 0
        prev_end_global = max(prev_end_global, prev_end or 0)
        latest_publish_global = max(latest_publish_global, publish_ms)
        cities_meta.append({
            "key": idx.replace("norm_", "").replace("_price", ""),
            "label": _city_label(idx),
            # 2026-07-26 新增: ODS 实际发布时间(数据新鲜度口径)
            "latest_publish_date": _ms_to_date(publish_ms),
            # 保留: 覆盖期结束日(本期 vs 上期 涨跌幅口径)
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
        # 2026-07-24: prev_end 可能 None(单期城市) — 跳过 prev 计算
        if not prev_end:
            continue
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
        # 2026-07-26 新增: 全局最新发布时间(用于新鲜度口径)
        "latest_publish_date": _ms_to_date(latest_publish_global),
        # 保留: 驱动本期 vs 上期 均价对比
        "latest_period_end": _ms_to_date(latest_end_global),
        "prev_period_end": _ms_to_date(prev_end_global),
        "cities_meta": sorted(cities_meta, key=lambda c: c["label"]),
        "data_source": "norm_*_price",
    }


# 2026-07-25 P0: /sources — /market 页「数据来源」模块的入参来源
#   - 不鉴权：与 /overview /movers /hot-categories 等同走公开页（不需 JWT）
#   - 不查 ES：纯走 skill_registry（启动时一次扫盘 + 进程级缓存），零开销
#   - v0.2 (2026-07-25): 按道友反馈，去掉按省分组 — 改为平铺 sources 数组
#     全部 20 个源站一张 grid 展示，更直观
#   - 每个 skill 暴露：key / label / province / cities / site_url / skill_dir
@router.get("/sources")
def sources():
    """全量源网站清单（平铺）。给 /market 页「数据来源」模块使用。

    返回:
      {
        "total_skills": int,
        "total_cities": int,
        "sources": [
          {"key": "weihai", "label": "威海", "province": "山东",
           "cities": ["威海"], "site_url": "https://..."},
          ...
        ]
      }
    """
    items = []
    total_cities = 0
    for s in _registry_get_all():
        site_url = s.get("site_url") or ""
        if not site_url:
            # 没有 site_url 的 skill（老 yml 缺 config 推导）跳过，不在前端展示坏链
            continue
        cities = s.get("cities") or []
        if isinstance(cities, list):
            total_cities += len(cities)
        items.append({
            "key": s.get("key", ""),
            "label": s.get("label", s.get("key", "")),
            "province": s.get("province") or "",
            "cities": cities if isinstance(cities, list) else [],
            "site_url": site_url,
            "skill_dir": s.get("skill_dir", ""),
        })

    # 全局按 label 拼音排序（locale，无 locale 时退化为字典序）
    try:
        import locale as _locale
        _locale.setlocale(_locale.LC_ALL, "")
        items.sort(key=lambda x: _locale.strxfrm(x["label"]))
    except Exception:
        items.sort(key=lambda x: x["label"])

    return {
        "total_skills": len(items),
        "total_cities": total_cities,
        "sources": items,
    }


# 2026-07-28: 浏览器 GPS → 中国省份名 (给 /market 首屏定位用)
#   Nominatim reverse geocoding + 内存缓存(按 lat,lng 3 位小数键 ≈ 110m 精度)
#   同小区缓存命中(1 天 TTL),失败兜底返 province=None,前端降级"全国"
_geo_locate_cache: dict = {}
_GEO_LOCATE_TTL_S = 86400
NOMINATIM_URL = "https://nominatim.openstreetmap.org/reverse"
NOMINATIM_HEADERS = {"User-Agent": "ChinaJT-Market/1.0 (https://pengfit.cn; contact via github.com/pengfit/cjt-skills)"}

# 中国省份名归一化: Nominatim 中文返回可能带 "省/市/自治区/xxx族" 后缀,
#   NORM province 字段是简短名(山东、四川、新疆、内蒙古...),需要剥后缀
def _normalize_province(name: str) -> str:
    if not name:
        return ""
    n = name.strip()
    # 优先剥长后缀(顺序很重要:长 → 短)
    for suffix in ["维吾尔自治区", "壮族自治区", "回族自治区", "特别行政区", "自治区", "省", "市"]:
        if n.endswith(suffix):
            return n[:-len(suffix)].strip()
    return n


@router.get("/geo-locate")
def geo_locate(
    lat: float = Query(..., ge=-90, le=90, description="纬度(浏览器 GPS)"),
    lng: float = Query(..., ge=-180, le=180, description="经度(浏览器 GPS)"),
):
    """浏览器 GPS 坐标 → 中国省份名

    返回:
    {
      "province": "山东",       # 归一化省份名(对齐 NORM province 字段),None 表示不在中国或失败
      "province_full": "山东省", # Nominatim 原始返回
      "country": "中国",
      "source": "nominatim" | "cache" | "error",
      "cached": bool,
      "lat": float, "lng": float
    }
    """
    cache_key = f"{lat:.3f},{lng:.3f}"
    now = time.time()
    cached = _geo_locate_cache.get(cache_key)
    if cached and (now - cached[0]) < _GEO_LOCATE_TTL_S:
        return {**cached[1], "cached": True, "lat": lat, "lng": lng, "source": "cache"}
    try:
        r = requests.get(
            NOMINATIM_URL,
            params={"lat": lat, "lon": lng, "format": "json", "accept-language": "zh-CN", "zoom": 5},
            headers=NOMINATIM_HEADERS,
            timeout=5,
        )
        r.raise_for_status()
        data = r.json()
        addr = data.get("address", {})
        province_full = addr.get("province") or addr.get("state") or ""
        province = _normalize_province(province_full)
        country = addr.get("country", "")
        result = {
            "province": province or None,
            "province_full": province_full or None,
            "country": country or None,
        }
        _geo_locate_cache[cache_key] = (now, result)
        return {**result, "cached": False, "lat": lat, "lng": lng, "source": "nominatim"}
    except Exception as e:
        print(f"[geo-locate] Nominatim error: {e}", flush=True)
        return {
            "province": None, "province_full": None, "country": None,
            "cached": False, "lat": lat, "lng": lng, "source": "error", "error": str(e)
        }


# 2026-07-25 (B.1): 数据治理透明卡 — 给 /market 页面 hero 下方展示用
# 2026-07-26 (修): latest_end / age_days 改用 source_publish_date (ODS 真实发布时间)
#   之前用 period_end ("覆盖期结束日") 会导致 jiangxi=未来 5 天、henan=87 天等错误新鲜度
# 2026-07-27 (修): fresh_ms 优先 ODS update_date (入库时间,8 城 ODS 有索引),
#   缺 ODS 的城回退 NORM source_publish_date (政府发布时间,2026-07-26 引入)
@router.get("/data-quality")
def market_data_quality():
    """每城数据健康度 + attr_norm 净化率,Dashboard 公开页可匿名访问。"""
    norm_list = _norm_indices()
    import time as _time
    now_ms = int(_time.time() * 1000)
    idx2info = {s.get("key"): s for s in _registry_get_all()}
    cities = []
    for norm_idx in norm_list:
        key = norm_idx.replace("norm_", "").replace("_price", "")
        info = idx2info.get(key, {})
        # 2026-07-27: 优先 ODS update_date (入库时间),缺 ODS 的城回退 NORM source_publish_date
        ods_idx = f"ods_material_{key}_price"
        fresh_ms = _city_latest_update_date(ods_idx)
        fresh_source = "ods_update" if fresh_ms else None
        if not fresh_ms:
            fresh_ms = _city_latest_publish_date(norm_idx)
            fresh_source = "norm_publish" if fresh_ms else None
        periods = _city_latest_two_periods(norm_idx)
        period_end_ms = periods[0] if periods else 0

        if fresh_ms:
            age_days = max(0, (now_ms - fresh_ms) // 86400000)
        else:
            age_days = -1
        if age_days < 0:
            status, tone = "unknown", "alert"; emoji = "⚫"
        elif age_days < 90:    # 0-90 天 = 新鲜
            status, tone = "fresh",  "ok";    emoji = "🟢"
        elif age_days < 180:   # 90-180 天 = 警告
            status, tone = "warm",   "warn";  emoji = "🟡"
        else:                  # >=180 天 = 停更
            status, tone = "stale",  "alert"; emoji = "🔴"
        cities.append({
            "key": key,
            "label": _city_label(norm_idx),
            "province": info.get("province", ""),
            # fresh_ms 优先 ODS update_date (2026-07-27),回退到 NORM source_publish_date
            "latest_end": _ms_to_date(fresh_ms),
            # 新增: 保留 period_end 供查看覆盖期
            "period_end": _ms_to_date(period_end_ms),
            # 新增: 数据来源标记,前端/调试用 — ods_update / norm_publish / None
            "fresh_source": fresh_source,
            "age_days": age_days,
            "status": status,
            "tone": tone,
            "emoji": emoji,
            "docs": _safe_count(norm_idx),
        })
    return {"cities": sorted(cities, key=lambda c: (c["tone"] != "alert", c["label"]))}

@router.get("/sparkline")
def sparkline(
    breeds: Optional[str] = Query(None, description="品种列表(逗号分隔)"),
    periods: int = Query(6, ge=2, le=24, description="返回 N 期的折线数据"),
):
    """2026-07-25 (A.2) — 给 /market 页热力图行标签下的 sparkline 提供数据。

    每城每品种最近 N 期的均价折线(period_end 升序)。
    用 ES date_histogram 聚合,每城 1 个 query 拿所有品种。
    数据从 norm_*_price 索引读,NORM 索引无数据时降级 DWS。
    """
    breed_list = [b.strip() for b in (breeds or "").split(",") if b.strip()]
    if not breed_list:
        return {"timelines": {}}

    norm_list = _norm_indices()
    if not norm_list:
        return {"timelines": {}}

    timelines: dict = {}
    for s_city, info in [(idx.replace("norm_", "").replace("_price", ""), idx) for idx in norm_list]:
        norm_idx = info
        body = {
            "size": 0,
            "query": {
                "bool": {
                    "filter": [
                        {"terms": {"normalized_breed.keyword": breed_list}},
                        {"range": {"period_end": {"gte": "now-12m/m"}}},
                    ]
                }
            },
            "aggs": {
                "by_breed": {
                    "terms": {"field": "normalized_breed.keyword", "size": len(breed_list) * 2},
                    "aggs": {
                        "by_period": {
                            "date_histogram": {
                                "field": "period_end",
                                "calendar_interval": "month",
                                "min_doc_count": 1,
                                "order": {"_key": "asc"},  # 升序 — 左旧右新
                            },
                            "aggs": {
                                "avg_price": {"avg": {"field": "price"}}
                            }
                        }
                    }
                }
            }
        }
        try:
            r = es.search(
                index=norm_idx,
                body=body,
                ignore_unavailable=True,
                allow_no_indices=True,
            )
        except Exception:
            continue

        for breed_bucket in r.get("aggregations", {}).get("by_breed", {}).get("buckets", []):
            breed_name = breed_bucket["key"]
            period_buckets = (
                breed_bucket.get("by_period", {}).get("buckets", [])
            )
            points = []
            for p in period_buckets:
                avg = p["avg_price"]["value"]
                if avg is None or avg <= 0:
                    continue
                points.append({
                    "period_end": p["key"],   # ms
                    "avg_price": round(float(avg), 4),
                })
            if not points:
                continue
            timelines.setdefault(breed_name, {})[s_city] = points

    return {"timelines": timelines, "periods": periods}


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
    # 2026-07-25 P0-fix (A.1): 返回每格绝对价格 + 单位,前端做 mini bar
    prices_grid = [[None] * len(cities) for _ in row_keys]
    units_grid  = [[None] * len(cities) for _ in row_keys]

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
                # 2026-07-24: prev_end 可能为 None(单期城市),跳过 prev 查询
                prev = _period_norm_prices_by_attr(norm_idx, prev_end, breed_key, breed_filters_to_use) if prev_end else {}
                # 2026-07-24: 只要 latest 有数据就 enrich 元数据(l3/l1/unit) — 不再依赖 prev 也有
                if breed_key in latest:
                    _enrich_breed_meta(breeds[bi], latest[breed_key])
                    # 2026-07-25 A.1: 跨城绝对价
                    prices_grid[bi][ci] = latest[breed_key]["price"]
                    units_grid[bi][ci] = latest[breed_key].get("unit", "")
                if breed_key in latest and breed_key in prev:
                    curr_p = latest[breed_key]["price"]
                    prev_p = prev[breed_key]["price"]
                    if prev_p > 0:
                        matrix[bi][ci] = round((curr_p - prev_p) / prev_p * 100, 2)
        else:
            # 多 breed 模式(混合,无规格对齐)
            latest = _period_norm_prices(norm_idx, latest_end, breed_size=1500)
            # 2026-07-24: prev_end 可能为 None(单期城市),跳过 prev 查询
            prev = _period_norm_prices(norm_idx, prev_end, breed_size=1500) if prev_end else {}
            for bi, breed_key in enumerate(row_keys):
                # 2026-07-24: 只要 latest 有数据就 enrich 元数据(l3/l1/unit) — 不再依赖 prev 也有
                if breed_key in latest:
                    _enrich_breed_meta(breeds[bi], latest[breed_key])
                    # 2026-07-25 A.1: 跨城绝对价
                    prices_grid[bi][ci] = latest[breed_key]["price"]
                    units_grid[bi][ci] = latest[breed_key].get("unit", "")
                if breed_key in latest and breed_key in prev:
                    curr_p = latest[breed_key]["price"]
                    prev_p = prev[breed_key]["price"]
                    if prev_p > 0:
                        matrix[bi][ci] = round((curr_p - prev_p) / prev_p * 100, 2)

    # 2026-07-25 (A.1): 算全表价格区间,前端 mini bar 颜色映射需要
    _all_prices = [p for row in prices_grid for p in row if p is not None and p > 0]
    _price_min = min(_all_prices) if _all_prices else 0
    _price_max = max(_all_prices) if _all_prices else 0

    return {
        "breeds": breeds,
        "cities": cities,
        "matrix": matrix,
        "prices_grid": prices_grid,    # 2026-07-25 (A.1): 跨城绝对价 mini bar 数据
        "units_grid":  units_grid,     # 2026-07-25 (A.1): 对应单位
        "price_min":   _price_min,     # 2026-07-25 (A.1): mini bar 色阶下限
        "price_max":   _price_max,     # 2026-07-25 (A.1): mini bar 色阶上限
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
    province: Optional[str] = Query(None, description="2026-07-28: 省份过滤(中文,如 '山东'),只在该省 NORM 数据池里搜;空=全池"),
):
    norm_list = _norm_indices()
    if not norm_list:
        return {"results": [], "total_breeds": 0, "matched_docs": 0, "query": q, "province": province or ""}
    # 2026-07-28: province 过滤 — 限定到该省份的 NORM 数据池(避免山东用户搜出黑龙江品种)
    if province:
        prov_keys = set(_skill_keys_by_province(province))
        norm_list = [idx for idx in norm_list
                     if idx.replace("norm_", "").replace("_price", "") in prov_keys]
        if not norm_list:
            return {"results": [], "total_breeds": 0, "matched_docs": 0, "query": q, "province": province}

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
            "province": province or "",
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
def random_breeds(
    province: Optional[str] = Query(None, description="省份过滤(中文,如 '山东'),只从该省 NORM 池子抽"),
    count: int = Query(10, ge=1, le=50, description="返回品种数,默认 10"),
):
    """2026-07-28 v0.5: 加 province 参数 — 指定省份时只从该省 NORM 池子抽。

    历史:
      v1: 全池 size=200 → 小城长尾进不去
      v2: 每城 size=8 → 池子太浅
      v3 (v0.35, 2026-07-26): 每城 size=120 + Phase 1 不 dedup,每城强取 #1
          保证小城品种进热力图,但商品混凝土/钢筋等大宗主材在 15+ 城都出现,
          列表严重重复
      v4 (2026-07-28 配合 build_norm_index.py 全 20 城重建):
          - dedup by normalized_breed:同一品种只出现一次
          - records = Σ该 breed 在所有 NORM 索引中的 doc_count(跨 index 求和)
          - city_index 改为 list[str]:列出该 breed 出现的所有 NORM 索引
          - 长尾品种仍能进(每城 pool=120,dedup 后总池数百个 breed,
            random.sample 覆盖长尾;小城品种排在 100+ 也能被 random 到)
      v5 (当前, 2026-07-28): 加 province 参数 — /market 首屏 GPS 定位后
          只从该省数据池里抽,避免随机出黑龙江的"白桦原木"给广东用户
    """
    norm_list = _norm_indices()
    if not norm_list:
        return {"results": [], "total": 0, "count": count, "province": province}
    # province 过滤:把 norm_list 限定到该省份的 skill key 列表
    if province:
        prov_keys = set(_skill_keys_by_province(province))
        norm_list = [idx for idx in norm_list
                     if idx.replace("norm_", "").replace("_price", "") in prov_keys]
        if not norm_list:
            # 该省份暂无任何 NORM 数据 → 返空,前端降级"全国"提示
            return {"results": [], "total": 0, "count": count, "province": province}
    # 大池 size:小城品种总数常 < 200,120 已能覆盖长尾品种
    # 大城(重庆 4000+)120 只取前 1.5%,random 在这 120 内仍能拿到冷门品类
    pool_size = 120

    def _fetch_one(idx):
        """单索引 terms agg,带 l3 + 规格"""
        body = {
            "size": 0,
            "aggs": {
                "breeds": {
                    "terms": {"field": "normalized_breed.keyword", "size": pool_size},
                    "aggs": {
                        "l3": {"terms": {"field": "category_name_l3.keyword", "size": 1}},
                        "all_specs": {
                            "nested": {"path": "attr_norm"},
                            "aggs": {
                                "by_k": {"terms": {"field": "attr_norm.k", "size": 10},
                                    "aggs": {"values": {"terms": {"field": "attr_norm.v", "size": 30}}}
                                }
                            }
                        }
                    }
                }
            }
        }
        try:
            r = es.search(index=idx, body=body, ignore_unavailable=True, allow_no_indices=True)
            return r.get("aggregations", {}).get("breeds", {}).get("buckets", [])
        except Exception:
            return []

    def _to_result(b, cities, records_sum):
        """组装单条结果;cities/records_sum 由 dedup 阶段聚合后传入"""
        breed = b["key"]
        l3 = b["l3"]["buckets"][0]["key"] if b["l3"]["buckets"] else ""
        spec_attrs = {}
        for k_bucket in b.get("all_specs", {}).get("by_k", {}).get("buckets", []):
            spec_attrs[k_bucket["key"]] = [v["key"] for v in k_bucket["values"]["buckets"]]
        return {
            "breed": breed,
            "category_name_l3": l3,
            "spec_attrs": spec_attrs,
            "spec_summary": _summarize_specs(spec_attrs),
            "records": records_sum,           # 跨城 NORM 求和
            "city_index": cities,             # list[str]: 该 breed 出现的所有 NORM 索引
        }

    # 2026-07-28 v0.4: dedup by normalized_breed + 跨 index 聚合
    # 收集每城 pool_size buckets,聚合到 breed_pool(同一 breed 跨城汇总)
    breed_pool = {}  # breed_name -> {first_bucket, records_sum, cities}
    for norm_idx in random.sample(norm_list, len(norm_list)):
        buckets = _fetch_one(norm_idx)
        for b in buckets:
            breed_name = b["key"]
            if breed_name not in breed_pool:
                breed_pool[breed_name] = {
                    "first_bucket": b,
                    "records": 0,
                    "cities": [],
                }
            entry = breed_pool[breed_name]
            entry["records"] += b["doc_count"]
            if norm_idx not in entry["cities"]:
                entry["cities"].append(norm_idx)

    # dedup 后 random.sample 取 count 个,覆盖长尾品种
    if not breed_pool:
        return {"results": [], "total": 0, "count": count}
    selected_names = random.sample(list(breed_pool.keys()), min(count, len(breed_pool)))

    results = []
    for breed_name in selected_names:
        entry = breed_pool[breed_name]
        results.append(_to_result(entry["first_bucket"], entry["cities"], entry["records"]))

    random.shuffle(results)
    return {"results": results, "total": len(results), "count": count}


# 2026-07-27 新增 — /market 趋势卡专用端点
#   实现思路参考 /api/norm/price-trend:date_histogram(month) + terms(city)
#   区别:不分 spec(每个 (city, period) 一个桶);不用 avg,用 top_hits 取原始价格数组
#   给前端做 median / min-max band / scatter 都有空间 — 避开 double-averaging 失真
@router.get("/breed-trend")
def breed_trend(
    breed: str = Query(..., min_length=1, max_length=100, description="归一品种名(精确匹配 normalized_breed)"),
    cities: Optional[str] = Query(None, description="城市过滤,逗号分隔;空=全部 NORM 城市"),
    province: Optional[str] = Query(None, description="省份过滤(中文,如 '山东'),自动转成该省 skill key 列表"),
    months: int = Query(6, ge=1, le=24, description="往前几个月"),
):
    """单品种按城半年价趋势
    输出:
    {
      "breed": "闸阀",
      "periods": [{"start": ms, "end": ms, "label": "YYYY-MM"}, ...],
      "cities": [
        {"city": "jiangxi", "points": [{"period_idx": 0, "prices": [134.5, 135.0, ...]}, ...]},
        ...
      ]
    }

    2026-07-28 v0.3: 加 province 参数 — GPS 定位后只取所在省的城市,避免山东用户看全国折线
    """
    norm_list = _norm_indices()
    if not norm_list:
        return {"breed": breed, "periods": [], "cities": []}

    city_filter = [c.strip() for c in (cities or "").split(",") if c.strip()]
    # province 参数自动转成城市列表（仅在 cities 未指定时生效,给前端一个高层级 API）
    if province and not city_filter:
        city_filter = _skill_keys_by_province(province)
    # months 参数在 date_histogram 的 min_doc_count + 取最后 N 个月逻辑里用,不在 ES 端 filter
    body = {
        "size": 0,
        "query": {
            "bool": {
                "filter": [
                    {"term": {"normalized_breed.keyword": breed}},
                    # 2026-07-27:不用 now-6m(ES 服务器时钟可能不对),硬编码宽范围
                    #   NORM 数据目前都在 2025-2030 内,够用;月 bucket 数量由 date_histogram 自动归
                    {"range": {"period_end": {"gte": "2025-01-01", "lte": "2030-12-31"}}},
                ]
            }
        },
        "aggs": {
            "by_period": {
                "date_histogram": {
                    "field": "period_end",
                    "calendar_interval": "month",
                    "min_doc_count": 1,
                    "order": {"_key": "asc"},   # 2026-07-27:改正序 — 横坐标左旧右新符合时间轴直觉
                    "extended_bounds": {"min": "2025-01-01", "max": "2030-12-31"},
                },
                "aggs": {
                    "by_city": {
                        "terms": {"field": "city", "size": 30},
                        "aggs": {
                            "prices": {
                                "top_hits": {
                                    "size": 80,  # 每月每城最多取 80 条原始价样本
                                    "_source": ["price"],
                                    "sort": [{"period_end": {"order": "desc"}}]
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
        buckets = r.get("aggregations", {}).get("by_period", {}).get("buckets", [])

        # period 元数据 — buckets 现在 asc,取最后 months 个 = 最近 N 月
        # (固定 size: months 避免 ES 返太多空 bucket)
        last_n = buckets[-months:] if len(buckets) > months else buckets
        periods = []
        for b in last_n:
            ms = b["key"]
            dt = datetime.fromtimestamp(ms / 1000)
            label = f"{dt.year}-{str(dt.month).zfill(2)}"
            periods.append({"start": ms, "end": ms, "label": label})

        # 按城按期聚合(用 last_n,与 periods 同序)
        city_points: dict = {}
        for period_idx, b in enumerate(last_n):
            for city_bucket in b["by_city"]["buckets"]:
                city = city_bucket["key"]
                if city_filter and city not in city_filter:
                    continue
                prices = []
                for hit in city_bucket["prices"]["hits"]["hits"]:
                    p = hit["_source"].get("price")
                    if p and p > 0:
                        prices.append(p)
                if city not in city_points:
                    city_points[city] = []
                city_points[city].append({"period_idx": period_idx, "prices": prices})

        city_series = [{"city": c, "points": data} for c, data in city_points.items()]
        return {"breed": breed, "periods": periods, "cities": city_series}
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


# 2026-07-28: /market GPS 定位后展示用 — 单省份多品种 × 月度均价趋势(一次 ES query)
#   vs /breed-trend:后者是单品种 × 多城市(每城一条线);本端点是多品种 × 单省(每品种一条均价线)
@router.get("/province-trend")
def province_trend(
    province: Optional[str] = Query(None, description="省份(中文,如 '山东');空=全国"),
    months: int = Query(6, ge=1, le=24, description="往前几个月"),
    limit: int = Query(10, ge=1, le=30, description="随机品种数(breeds 未指定时生效)"),
    breeds: Optional[str] = Query(None, description="2026-07-28: 指定品种列表(逗号分隔),按用户顺序返回(不随机);空=随机 limit 个"),
):
    """单省份多品种半年价趋势(给 /market GPS 定位后展示)

    返回:
    {
      "province": "山东",
      "periods": [{"start": ms, "label": "YYYY-MM"}, ...],
      "breeds": [
        {"breed": "商品混凝土", "points": [{"period_idx": 0, "avg_price": 425.5}, ...]},
        ...
      ]
    }

    实现思路:
      1) province 空 → 走全池;非空 → 限定到该省份的 skill key 列表
      2) 一次 ES query(date_histogram 月 + terms breed),拿全月全品种均值
      3) 按品种随机抽 limit 个(优先选覆盖度高的, 保证随机性)
    """
    norm_list = _norm_indices()
    if not norm_list:
        return {"province": province or "", "periods": [], "breeds": []}
    if province:
        prov_keys = set(_skill_keys_by_province(province))
        norm_list = [idx for idx in norm_list
                     if idx.replace("norm_", "").replace("_price", "") in prov_keys]
        if not norm_list:
            return {"province": province, "periods": [], "breeds": []}

    # 一次 query 拿全月全品种均值(跨索引)
    body = {
        "size": 0,
        "query": {"range": {"period_end": {"gte": "2025-01-01", "lte": "2030-12-31"}}},
        "aggs": {
            "by_period": {
                "date_histogram": {
                    "field": "period_end",
                    "calendar_interval": "month",
                    "min_doc_count": 1,
                    "order": {"_key": "asc"},
                    "extended_bounds": {"min": "2025-01-01", "max": "2030-12-31"},
                },
                "aggs": {
                    "by_breed": {
                        "terms": {"field": "normalized_breed.keyword", "size": 300},
                        "aggs": {
                            "avg_price": {"avg": {"field": "price"}}
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
        buckets = r.get("aggregations", {}).get("by_period", {}).get("buckets", [])
        # 取最近 months 个月
        last_n = buckets[-months:] if len(buckets) > months else buckets
        periods = []
        for b in last_n:
            ms = b["key"]
            dt = datetime.fromtimestamp(ms / 1000)
            label = f"{dt.year}-{str(dt.month).zfill(2)}"
            periods.append({"start": ms, "end": ms, "label": label})

        # 按 breed 聚合:每个 breed 在所有月里的均价
        breed_data: dict = {}  # breed_name -> {period_idx: avg_price}
        for period_idx, b in enumerate(last_n):
            for breed_bucket in b["by_breed"]["buckets"]:
                breed_name = breed_bucket["key"]
                avg = breed_bucket["avg_price"]["value"]
                if avg is None or avg <= 0:
                    continue
                breed_data.setdefault(breed_name, {})[period_idx] = round(float(avg), 4)

        # 2026-07-28: breeds 参数 — 用户指定品种时按用户顺序返回(不随机,不截断),否则保持原 random 逻辑
        missing_breeds = []
        if breeds:
            target = [b.strip() for b in breeds.split(",") if b.strip()]
            # 不 [:limit] 截断:用户传 11 个就返 11 个(空品种会被 missing 报告)
            # 但保险起见设个硬上限 100,避免恶意请求拖垮 ES
            if len(target) > 100:
                target = target[:100]
            # 记录无数据品种,告诉前端(避免静默丢品种 — 13:15 道友报)
            selected_names = []
            for b in target:
                if b in breed_data:
                    selected_names.append(b)
                else:
                    missing_breeds.append(b)
        else:
            # 按覆盖度(多少个月有数据)排序,再 random.sample 取 limit 个保多样性
            candidates = sorted(
                [(b, len(pts)) for b, pts in breed_data.items()],
                key=lambda x: x[1],
                reverse=True,
            )
            # 优先覆盖度 ≥1 的所有品种,random.sample 出 limit 个
            candidate_names = [b for b, c in candidates if c >= 1]
            if len(candidate_names) > limit:
                selected_names = random.sample(candidate_names, limit)
            else:
                selected_names = candidate_names

        breeds_out = []
        for breed_name in selected_names:
            pts = breed_data[breed_name]
            points = [{"period_idx": pidx, "avg_price": pts[pidx]} for pidx in sorted(pts.keys())]
            breeds_out.append({"breed": breed_name, "points": points})

        # 用户指定品种时保持顺序(便于视觉追踪),随机时打乱
        if not breeds:
            random.shuffle(breeds_out)
        return {
            "province": province or "",
            "periods": periods,
            "breeds": breeds_out,
            "missing": missing_breeds,  # 用户指定的品种中无数据的(帮前端告警)
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


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

# ── 价格走势 + 时序数据表 双卡片接口(2026-07-28 v3 — /market 公开页专用) ──────────
#   与 /trend 页同源 NORM 数据, 复用 norm_trend.norm_price_trend 内部函数
#   公开, 不需 JWT(_PUBLIC_PATHS 通过 /api/market/* 前缀默认放行)
#   参数比 /api/norm/price-trend 更严: 公开页防止被滥用
@router.get("/price-trend")
def market_price_trend(
    city: str = Query("qingdao", description="城市 key (公开页默认 qingdao — NORM 索引已 ETL)"),
    periods: int = Query(12, ge=1, le=12, description="期数, 公开页限制最多 12"),
    top_specs: int = Query(3, ge=1, le=5, description="每品种规格数, 公开页限制最多 5"),
    max_breeds: int = Query(8, ge=1, le=10, description="品种数, 公开页限制最多 10"),
):
    """公开页价格走势 chart 数据(简化版 /api/norm/price-trend)

    返回结构与 /api/norm/price-trend 同形: {periods, series, total_docs, ...}
    /market 价格走势卡片直接吃这个 shape。

    设计:
      - city 默认 qingdao (与 norm_trend hardcoded 一致, 已 ETL)
      - 参数上限收紧, 防公开页被滥用拉全量
      - materials='*' (走 top N 品种路径)
      - date_from/to 空 (走 periods 路径)
      - attr_keys 空 (不过滤)
    """
    return _norm_price_trend_inner(
        city=city,
        materials='*',
        periods=periods,
        date_from='',
        date_to='',
        top_specs=top_specs,
        max_breeds=max_breeds,
        attr_keys='',
    )


@router.get("/trend-table")
def market_trend_table(
    city: str = Query("qingdao", description="城市 key (公开页默认 qingdao)"),
    periods: int = Query(12, ge=1, le=12, description="期数, 公开页限制最多 12"),
    top_specs: int = Query(3, ge=1, le=5, description="每品种规格数, 公开页限制最多 5"),
    max_breeds: int = Query(8, ge=1, le=10, description="品种数, 公开页限制最多 10"),
):
    """公开页时序数据表(扁平行, 每行 = 一品种 × 一规格)

    返回结构:
      {
        ok: true,
        city, label,
        periods: [{start, end, label}],
        rows: [{material, spec, unit, prices: {period_start: avg}, prices_n: {...},
                trend_pct, trend_abs}],
        total_docs
      }

    /market 时序数据表卡片直接吃这个 shape, 无需前端二次 transform。

    设计:
      - 内部复用 _norm_price_trend_inner (避免与 price-trend 重复 ES 查询逻辑)
      - 同样的参数上限, 与 price-trend 同源数据
      - 趋势%与绝对额在服务端算好(首末两期), 前端只渲染
    """
    data = _norm_price_trend_inner(
        city=city,
        materials='*',
        periods=periods,
        date_from='',
        date_to='',
        top_specs=top_specs,
        max_breeds=max_breeds,
        attr_keys='',
    )
    if not data.get('ok'):
        return data

    rows = []
    for s in (data.get('series') or []):
        for sp in (s.get('specs') or []):
            prices = {}
            prices_n = {}
            for p in (sp.get('points') or []):
                prices[p['period_start']] = p['avg']
                prices_n[p['period_start']] = p['n']
            pts = sp.get('points') or []
            trend_pct = None
            trend_abs = None
            if len(pts) >= 2 and pts[0].get('avg', 0) > 0:
                first = pts[0]['avg']
                last = pts[-1]['avg']
                trend_pct = ((last - first) / first) * 100
                trend_abs = last - first
            rows.append({
                'material': s.get('normalized_breed', ''),
                'spec': sp.get('spec', ''),
                'unit': sp.get('unit') or s.get('unit') or '',
                'prices': prices,
                'prices_n': prices_n,
                'trend_pct': trend_pct,
                'trend_abs': trend_abs,
            })

    return {
        'ok': True,
        'city': data.get('city', city),
        'label': data.get('label', ''),
        'periods': data.get('periods', []),
        'rows': rows,
        'total_docs': data.get('total_docs', 0),
    }


# ── 城市列表(2026-07-28 v3.1 — /market 双卡片 toolbar 下拉用) ────────────────────────────
#   公开,只返 NORM 已 ETL 的城市(key + 标签),无敏感数据
#   数据源: 扫 _registry_get_all() 的所有 skill, 过滤 NORM 索引真实存在的
# 2026-07-28 v3.2: 接受 province 参数,只返该省的 NORM 城市
#   - province 为空 / '全国' → 返全国 (与旧行为一致)
#   - province 为省名(如 '山东') → 只返 _skill_keys_by_province(province) 里的城市
@router.get("/cities")
def market_cities(
    province: str = Query("", description="省份名, 空或'全国'= 全国 NORM 城市, 如'山东'仅返山东 NORM 城市"),
):
    """公开页 /market 工具栏下拉(城市选择)用 — 列出 NORM 已 ETL 的城市

    返回: {ok, cities: [{key, label, docs_count}], province}
      - docs_count: 该城市 NORM 索引文档总数 (totals 聚合, 1 次轻量 ES 查询)
      - 按 docs_count 倒序, 数据多的城市排前面
      - province 非空时仅返该省内的城市(配合前端 GPS 定位)
    """
    from api.dependencies import es
    # v3.2: 省份过滤 — 空 / '全国' 走全国路径,否则只过该省的 skill keys
    province_keys = None
    if province and province != '全国':
        try:
            province_keys = set(_skill_keys_by_province(province))
        except Exception:
            province_keys = set()
    cities = []
    for skill in _registry_get_all() or []:
        key = skill.get('key')
        label = skill.get('label', key)
        if not key:
            continue
        # v3.2: 省份过滤
        if province_keys is not None and key not in province_keys:
            continue
        norm_idx = f"norm_{key}_price"
        # 校验 NORM 索引真实存在(轻量 head 请求)
        try:
            if not es.indices.exists(index=norm_idx, ignore_unavailable=True):
                continue
            # 一次轻量聚合拿文档数
            r = es.count(index=norm_idx, ignore_unavailable=True, allow_no_indices=True)
            docs = r.get('count', 0)
        except Exception:
            continue
        if docs == 0:
            continue
        cities.append({'key': key, 'label': label, 'docs_count': docs})
    cities.sort(key=lambda x: x['docs_count'], reverse=True)
    return {'ok': True, 'cities': cities, 'province': province or '全国'}
