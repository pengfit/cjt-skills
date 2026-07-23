"""Phase 4 抽取: /api/stats/geo-distribution + /api/stats/geo-regions (原 main.py 内联实现)"""
from fastapi import APIRouter, Query, HTTPException
from typing import Optional

from api.helpers import _build_bool_query, safe_search
from api.dependencies import es, ALL_INDICES

# 中国省份名 → adcode 映射（DataV.GeoAtlas 用 adcode 标识省份）
_PROVINCE_ADCODE = {
    "北京": 110000, "天津": 120000, "河北": 130000, "山西": 140000,
    "内蒙古": 150000, "辽宁": 210000, "吉林": 220000, "黑龙江": 230000,
    "上海": 310000, "江苏": 320000, "浙江": 330000, "安徽": 340000,
    "福建": 350000, "江西": 360000, "山东": 370000, "河南": 410000,
    "湖北": 420000, "湖南": 430000, "广东": 440000, "广西": 450000,
    "海南": 460000, "重庆": 500000, "四川": 510000, "贵州": 520000,
    "云南": 530000, "西藏": 540000, "陕西": 610000, "甘肃": 620000,
    "青海": 630000, "宁夏": 640000, "新疆": 650000, "台湾": 710000,
}

router = APIRouter()

@router.get("/api/stats/geo-distribution")
def geo_distribution(
    level: str = Query("province", pattern="^(province|city|county)$"),
    parent: Optional[str] = Query(None, description="level=city 时传 province；level=county 时传 city"),
    parent2: Optional[str] = Query(None, description="level=county 时传 province"),
    category: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None, description="YYYY-MM-DD"),
    date_to: Optional[str] = Query(None, description="YYYY-MM-DD"),
    breed: Optional[str] = Query(None, description="产品名关键词"),
):
    """
    地理分布聚合（地图着色用）
    - level=province: 全省聚合
    - level=city:     parent=省份，下钻到地市
    - level=county:   parent=省份，parent2=地市，下钻到区县
    返回：[{name, adcode, value(均价), count, min, max}]
    """
    # 1. 过滤条件
    filter_clauses = []
    if level == "city" and parent:
        filter_clauses.append({"term": {"province": parent}})
    if level == "county":
        if parent2:
            filter_clauses.append({"term": {"province": parent2}})
        if parent:
            filter_clauses.append({"term": {"city": parent}})
    if category:
        filter_clauses.append({"term": {"category": category}})
    if breed:
        filter_clauses.append({"match": {"breed": breed}})
    if date_from or date_to:
        date_range = {}
        if date_from:
            date_range["gte"] = date_from
        if date_to:
            date_range["lte"] = date_to
        filter_clauses.append({"range": {"update_date": date_range}})

    # 2. 聚合字段
    field_map = {"province": "province", "city": "city", "county": "county"}
    agg_field = field_map[level]
    size_map = {"province": 40, "city": 50, "county": 100}
    agg_size = size_map[level]
    # 四川省下钻时 ES 中 city 字段实际存的是区/县级粒度（未归一），
    # 同地市不同区/县值不同，需要放大 size 拿到所有桶再归一
    if level == "city" and parent == "四川":
        agg_size = 300

    body = {
        "size": 0,
        "query": _build_bool_query([], filter_clauses),
        "aggs": {
            "by_region": {
                "terms": {"field": agg_field, "size": agg_size, "missing": "[未知]"},
                "aggs": {
                    "avg_price": {"avg": {"field": "price"}},
                    "min_price": {"min": {"field": "price"}},
                    "max_price": {"max": {"field": "price"}},
                    "count": {"value_count": {"field": "price"}},
                },
            }
        },
    }
    try:
        result = safe_search(es, ALL_INDICES, body)
        buckets = result.get("aggregations", {}).get("by_region", {}).get("buckets", [])
        items = []
        for b in buckets:
            name = b["key"]
            # 给省级数据加 adcode（便于 ECharts 地图匹配）
            adcode = _PROVINCE_ADCODE.get(name) if level == "province" else None
            items.append({
                "name": name,
                "adcode": adcode,
                "value": round(b["avg_price"]["value"], 2) if b["avg_price"]["value"] else 0,
                "count": int(b["count"]["value"] or 0),
                "min": round(b["min_price"]["value"], 2) if b["min_price"]["value"] else 0,
                "max": round(b["max_price"]["value"], 2) if b["max_price"]["value"] else 0,
            })
        # 四川省下钻特殊处理：ES 中 city/county 字段存的是区/县级粒度（未归一），
        # 需要按 doc_count 分桶去重 + 映射到 21 个地市名/区/县全称，与地图 features 对齐。
        # level=city: parent 是省份「四川」；level=county: parent2 是省份「四川」
        is_sichuan = (level == "city" and parent == "四川") or (level == "county" and parent2 == "四川")
        if is_sichuan and items:
            from api.sichuan_city_mapping import SICHUAN_CITY_MAPPING
            if level == "city":
                items = _normalize_sichuan_cities(items, SICHUAN_CITY_MAPPING)
            elif level == "county":
                # parent 是地市名（如「乐山市」）
                items = _normalize_sichuan_counties(items, SICHUAN_CITY_MAPPING, parent)

        # 直辖市下钻特殊处理：重庆 ES 中 city=「重庆」本身（1 个聚合桶），实际区/县在 county 字段。
        # 下钻时按 county 聚合 + 归一匹配 GeoJSON 38 个 feature。
        # 仅对当前有数据的重庆生效；北京/上海/天津 如未来入库，可扩展相同逻辑。
        is_chongqing_city_drill = level == "city" and parent == "重庆"
        if is_chongqing_city_drill and items:
            # 重新按 county 聚合一次，替换 items
            cq_query = _build_bool_query([], [{"term": {"province": "重庆"}}] + filter_clauses[1:])
            cq_body = {
                "size": 0,
                "query": cq_query,
                "aggs": {
                    "by_region": {
                        "terms": {"field": "county", "size": 100, "missing": "[未知]"},
                        "aggs": {
                            "avg_price": {"avg": {"field": "price"}},
                            "min_price": {"min": {"field": "price"}},
                            "max_price": {"max": {"field": "price"}},
                            "count": {"value_count": {"field": "price"}},
                        },
                    }
                },
            }
            try:
                cq_result = es.search(index=ALL_INDICES, body=cq_body)
                cq_buckets = cq_result.get("aggregations", {}).get("by_region", {}).get("buckets", [])
                raw_items = [{
                    "name": b["key"], "adcode": None,
                    "value": round(b["avg_price"]["value"], 2) if b["avg_price"]["value"] else 0,
                    "count": int(b["count"]["value"] or 0),
                    "min": round(b["min_price"]["value"], 2) if b["min_price"]["value"] else 0,
                    "max": round(b["max_price"]["value"], 2) if b["max_price"]["value"] else 0,
                } for b in cq_buckets]
                from api.chongqing_county_mapping import normalize as _normalize_cq
                items = _normalize_cq(raw_items)
            except Exception as _cq_e:
                # 归一失败不要阻断整体响应，回退到原 items
                print(f"[chongqing drill] normalize failed: {_cq_e}")

        # 河南全省指导价：河南 sync.py 把省级单列价格记为 city=「河南」（与 province 同名），
        # 业务上不归属任何地市，地图上不应误着色为某个地市。拆出到 province_wide。
        province_wide = None
        if level == "city" and parent and items:
            wide_idx = next((i for i, it in enumerate(items) if it.get("name") == parent), None)
            if wide_idx is not None:
                w = items.pop(wide_idx)
                province_wide = {
                    "name": parent,
                    "label": f"{parent}省本级指导价",
                    "count": w["count"],
                    "value": w["value"],
                    "min": w["min"],
                    "max": w["max"],
                }

        # 海南特殊处理：海南住建厅发布的 PDF 按「方位」（北部/东部/中部/南部/西部/全省）划分，
        # 不按市县。ES city 字段统一是「海南」，city level 聚合后只有 1 个桶 + 无任何市县项。
        # 改为按 region 字段重新聚合，返回「方位」分布明细，让前端可以展示省级指导价结构。
        if level == "city" and parent == "海南" and not items:
            hn_query = _build_bool_query([], [{"term": {"province": "海南"}}] + filter_clauses[1:])
            hn_body = {
                "size": 0,
                "query": hn_query,
                "aggs": {
                    "by_region": {
                        "terms": {"field": "region.keyword", "size": 30, "missing": "[未知]"},
                        "aggs": {
                            "avg_price": {"avg": {"field": "price"}},
                            "min_price": {"min": {"field": "price"}},
                            "max_price": {"max": {"field": "price"}},
                            "count": {"value_count": {"field": "price"}},
                        },
                    }
                },
            }
            try:
                hn_result = es.search(index=ALL_INDICES, body=hn_body)
                hn_buckets = hn_result.get("aggregations", {}).get("by_region", {}).get("buckets", [])
                # 方位列表（名称加「海南省·方位」以避免与海南地图市县 feature 重名）
                region_items = [{
                    "name": b["key"],
                    "adcode": None,
                    "value": round(b["avg_price"]["value"], 2) if b["avg_price"]["value"] else 0,
                    "count": int(b["count"]["value"] or 0),
                    "min": round(b["min_price"]["value"], 2) if b["min_price"]["value"] else 0,
                    "max": round(b["max_price"]["value"], 2) if b["max_price"]["value"] else 0,
                } for b in hn_buckets]
                total_cnt = sum(it["count"] for it in region_items)
                if total_cnt > 0:
                    avg_val = sum(it["value"] * it["count"] for it in region_items) / total_cnt
                    province_wide = {
                        "name": "海南",
                        "label": "海南省本级指导价（按方位划分）",
                        "count": total_cnt,
                        "value": round(avg_val, 2),
                        "min": min((it["min"] for it in region_items if it["count"] > 0), default=0),
                        "max": max((it["max"] for it in region_items if it["count"] > 0), default=0),
                        "items": region_items,   # 方位列表，供前端展示
                    }
            except Exception as _hn_e:
                print(f"[hainan drill] by-region failed: {_hn_e}")
        return {
            "level": level,
            "parent": parent,
            "parent2": parent2,
            "total": len(items),
            "items": items,
            "province_wide": province_wide,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def _normalize_sichuan_cities(items: list, mapping: dict) -> list:
    """
    四川省 city 归一化：ES 中 city 字段实际存的是区/县级粒度（如「五通」= 乐山市五通桥区），
    同一地市下的不同区/县 doc_count 相同（数据冗余）。按 count 分桶去重，再用 mapping 表把
    代表名归一为地市级（如「乐山市」）。
    """
    import re as _re
    from collections import Counter
    city_set = set(mapping.values())
    city_set |= {"阿坝州", "甘孜州", "凉山州"}

    def _normalize(name: str):
        if name in city_set:
            return name
        if name in mapping:
            return mapping[name]
        m = _re.match(r"^(.+)市区$", name)
        if m and (m.group(1) + "市") in city_set:
            return m.group(1) + "市"
        m = _re.match(r"^(.+?)(北部|南部|东部|西部|其他.+|市区)$", name)
        if m:
            x = m.group(1)
            for k in mapping:
                if k.startswith(x) or x in k:
                    return mapping[k]
            if (x + "市") in city_set:
                return x + "市"
        return None

    # 按 count 分桶（同一地市下不同区/县 doc_count 相同）
    buckets: dict = {}
    for it in items:
        buckets.setdefault(it["count"], []).append(it)

    normalized = []
    for cnt, grp in buckets.items():
        # 找桶里能归一到地市的项
        candidates = []
        for it in grp:
            norm = _normalize(it["name"])
            if norm:
                candidates.append((it, norm))
        if not candidates:
            # 整桶无法归一，跳过（理论上不应该发生）
            continue
        # 选出现次数最多的归一值作为代表
        norm_counter = Counter(n for _, n in candidates)
        rep_name, _ = norm_counter.most_common(1)[0]
        # 聚合桶内统计：avg/min/max 用桶里任一项（值相同），count 用一份（避免重复累加）
        sample = candidates[0][0]
        normalized.append({
            **sample,
            "name": rep_name,
        })
    # 按 count 降序
    normalized.sort(key=lambda x: -x["count"])
    return normalized


def _normalize_sichuan_counties(items: list, mapping: dict, parent_city: str) -> list:
    """
    四川省 county 归一化：ES 中 county 字段存的是区/县简称（如「五通」= 五通桥区），
    与地图 features 全称不匹配。在 parent_city 名下，按 prefix/substring 匹配把简称归一为
    mapping 表里的全称（如「五通桥区」）。
    """
    import re as _re
    from collections import Counter

    # 取该地市下所有 mapping key
    city_counties = [k for k, v in mapping.items() if v == parent_city]
    if not city_counties:
        return items  # 没数据,原样返回

    # 各城市「市区」简称 → 多个中心区（同一 doc_count 重复展开）
    CITY_CENTRAL_DISTRICTS = {
        '成都市': ['锦江区', '金牛区', '武侯区', '成华区', '青羊区'],
        '自贡市': ['自流井区', '贡井区', '大安区', '沿滩区'],
        '攀枝花市': ['东区', '西区', '仁和区'],
        '泸州市': ['江阳区', '纳溪区', '龙马潭区'],
        '德阳市': ['旌阳区'],
        '绵阳市': ['涪城区', '游仙区'],
        '广元市': ['利州区'],
        '遂宁市': ['船山区', '安居区'],
        '内江市': ['市中区'],
        '乐山市': ['市中区'],
        '南充市': ['顺庆区', '高坪区', '嘉陵区'],
        '眉山市': ['东坡区'],
        '宜宾市': ['翠屏区', '南溪区', '叙州区'],
        '广安市': ['广安区', '前锋区'],
        '达州市': ['通川区'],
        '雅安市': ['雨城区'],
        '巴中市': ['巴州区', '恩阳区'],
        '资阳市': ['雁江区'],
    }

    def _expand_one(name: str) -> list:
        """把 county 名归一为全称,特殊处理「X市区」展开为多个中心区。
        返回 1+ 个最终 county 名。
        """
        if not name:
            return [name]
        # 「X市区」模式：展开为该地市多个中心区
        m = _re.match(r"^(.+)市区$", name)
        if m:
            x = m.group(1)  # 如 "成都"
            # dict key 是「X市」形式 ("成都市")，用 x + "市" 查
            central = CITY_CENTRAL_DISTRICTS.get(x + "市", CITY_CENTRAL_DISTRICTS.get(x, []))
            matched = [c for c in central if c in city_counties]
            if matched:
                return matched
            # fallback: 最短的区
            districts = [k for k in city_counties if k.endswith("区")]
            if districts:
                return [min(districts, key=len)]
            return [name]
        if name in city_counties:
            return [name]
        # 「X其他乡镇」模式（如「屏山其他乡镇」→ 屏山县）
        m = _re.match(r"^(.+?)其他乡镇$", name)
        if m:
            x = m.group(1)
            for k in city_counties:
                if k == x + "县" or k == x + "市" or k == x + "区" or k.startswith(x):
                    return [k]
        # 「X北部/南部」模式
        m = _re.match(r"^(.+?)(北部|南部|东部|西部)$", name)
        if m:
            x = m.group(1)
            for k in city_counties:
                if k.startswith(x):
                    return [k]
        # 去后缀(县/区/市)再 prefix 匹配
        base = _re.sub(r'(县|区|市)$', '', name)
        for k in city_counties:
            if k.startswith(name) or (base and k.startswith(base)):
                return [k]
        # 特殊情况: county == parent_city（主城「乐山市」=「市中区」）
        if name == parent_city:
            for k in city_counties:
                if k == "市中区":
                    return [k]
            districts = [k for k in city_counties if k.endswith("区")]
            if districts:
                return [min(districts, key=len)]
        # substring 匹配
        for k in city_counties:
            if name in k or base in k:
                return [k]
        return [name]

    # 按 count 分桶（同地市下不同区/县 doc_count 相同）
    buckets: dict = {}
    for it in items:
        buckets.setdefault(it["count"], []).append(it)

    normalized = []
    for cnt, grp in buckets.items():
        expanded = []
        for it in grp:
            for new_name in _expand_one(it["name"]):
                expanded.append({**it, "name": new_name})
        # 去重
        seen = set()
        deduped = []
        for it in expanded:
            if it["name"] not in seen:
                seen.add(it["name"])
                deduped.append(it)
        normalized.extend(deduped)

    # 按 count 降序
    normalized.sort(key=lambda x: -x["count"])
    return normalized


@router.get("/api/stats/geo-regions")
def geo_regions():
    """
    返回所有有数据的省份/城市/区县列表（地图下钻决策用）
    让前端知道哪些省份/城市有数据，避免空白下钻
    """
    try:
        body = {
            "size": 0,
            "aggs": {
                "provinces": {
                    "terms": {"field": "province", "size": 50},
                    "aggs": {
                        "cities": {
                            "terms": {"field": "city", "size": 50},
                            "aggs": {
                                "counties": {
                                    "terms": {"field": "county", "size": 50}
                                }
                            }
                        }
                    }
                }
            }
        }
        result = safe_search(es, ALL_INDICES, body)
        prov_buckets = result.get("aggregations", {}).get("provinces", {}).get("buckets", [])
        provinces = []
        for pb in prov_buckets:
            cities = []
            for cb in pb["cities"]["buckets"]:
                counties = [c["key"] for c in cb["counties"]["buckets"] if c["key"] and c["key"] != "[未知]"]
                cities.append({
                    "name": cb["key"],
                    "count": int(cb["doc_count"]),
                    "counties": counties,
                })
            provinces.append({
                "name": pb["key"],
                "adcode": _PROVINCE_ADCODE.get(pb["key"]),
                "count": int(pb["doc_count"]),
                "cities": cities,
            })
        return {"provinces": provinces}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
