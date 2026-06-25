"""
重庆 county 归一化映射。
ES 中 county 字段是源站原始名（简称 + 后缀编号），GeoJSON feature 是民政部全称。
下钻时需要把 ES 名归一为 GeoJSON feature.properties.name。
"""

# GeoJSON feature 名 → ES 原始名（含重复/简称）的反向映射
# 来源：500000_full.json 的 38 个 feature 与 ES 中 county bucket 比对
ES_TO_FEATURE = {
    # 主城区（GeoJSON 无此 feature；按 9 个中心区 doc_count 拆分，落到 渝中区/江北区 等）
    # 实际无法精确归一，主城区保留为聚合桶，渲染时按 count 加到第一匹配 feature
    # 这里暂不在映射里，让 _normalize 函数走 fallback：保留原名 → 后续可二次处理

    # 单义映射：ES 简称/全称 → GeoJSON 全称
    "秀山县": "秀山土家族苗族自治县",
    "石柱县": "石柱土家族自治县",
    "酉阳县": "酉阳土家族苗族自治县",
    "彭水县": "彭水苗族土家族自治县",

    # 重复桶：源站把同一区拆成 2-3 个分页
    "荣昌区1": "荣昌区",
    "荣昌区2": "荣昌区",
    "彭水县1": "彭水苗族土家族自治县",
    "彭水县2": "彭水苗族土家族自治县",
    "彭水县3": "彭水苗族土家族自治县",
}


# GeoJSON 全部 38 个 feature 名（用于校验 + 补齐空数据 feature）
FEATURE_NAMES = [
    "万州区", "涪陵区", "渝中区", "大渡口区", "江北区", "沙坪坝区", "九龙坡区",
    "南岸区", "北碚区", "綦江区", "大足区", "渝北区", "巴南区", "黔江区",
    "长寿区", "江津区", "合川区", "永川区", "南川区", "璧山区", "铜梁区",
    "潼南区", "荣昌区", "开州区", "梁平区", "武隆区", "城口县", "丰都县",
    "垫江县", "忠县", "云阳县", "奉节县", "巫山县", "巫溪县", "石柱土家族自治县",
    "秀山土家族苗族自治县", "酉阳土家族苗族自治县", "彭水苗族土家族自治县",
]


def normalize(items: list) -> list:
    """
    把 ES 聚合结果按 ES_TO_FEATURE 归一为 GeoJSON feature 名，
    同一 feature 的 count/value 求和。
    items: [{name, adcode, value, count, min, max}, ...]
    """
    import re as _re
    from collections import Counter

    # 主城区：按 doc_count 等分到 9 个中心区（渝中/江北/南岸/沙坪坝/九龙坡/大渡口/渝北/北碚/巴南）
    MAIN_URBAN = ["渝中区", "江北区", "南岸区", "沙坪坝区", "九龙坡区",
                  "大渡口区", "渝北区", "北碚区", "巴南区"]

    agg = {}  # feature_name -> {count, sum_value, max_price, min_price, samples}
    for it in items:
        es_name = it.get("name", "")
        cnt = it.get("count", 0) or 0
        val = it.get("value", 0) or 0
        mn = it.get("min", 0) or 0
        mx = it.get("max", 0) or 0

        # 主城区拆分：按文档数 / 9 平摊到中心 9 区
        if es_name == "主城区" and cnt > 0:
            per = cnt // len(MAIN_URBAN)
            remainder = cnt - per * len(MAIN_URBAN)
            for i, fn in enumerate(MAIN_URBAN):
                add = per + (1 if i < remainder else 0)
                _acc(agg, fn, add, val, mn, mx)
            continue

        # 查映射表
        feature_name = ES_TO_FEATURE.get(es_name)
        if not feature_name:
            # fallback：去常见后缀再 prefix 匹配
            base = _re.sub(r'(自治县|县|区|市)$', '', es_name)
            for fn in FEATURE_NAMES:
                if fn.startswith(es_name) or fn.startswith(base):
                    feature_name = fn
                    break
        if not feature_name:
            # 真没法归一：丢弃（避免污染地图）
            continue

        _acc(agg, feature_name, cnt, val, mn, mx)

    # 转 list（去掉 adcode，由前端从 GeoJSON 拿）
    out = []
    for fn, a in agg.items():
        out.append({
            "name": fn,
            "adcode": None,
            "value": round(a["sum_value"] / a["count"], 2) if a["count"] > 0 else 0,
            "count": a["count"],
            "min": a["min_price"],
            "max": a["max_price"],
        })
    return out


def _acc(agg, fn, cnt, val, mn, mx):
    if fn not in agg:
        agg[fn] = {"count": 0, "sum_value": 0.0, "min_price": mn, "max_price": mx}
    a = agg[fn]
    a["count"] += cnt
    a["sum_value"] += val * cnt
    if mx > a["max_price"]:
        a["max_price"] = mx
    if mn > 0 and (a["min_price"] == 0 or mn < a["min_price"]):
        a["min_price"] = mn