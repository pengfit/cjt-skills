"""indexer.py - 索引创建 / 模板管理

幂等创建/更新 gov_ods / gov_dwd / gov_dws 三个 index template，并确保指定索引存在。

v0.5 (2026-07-02) 新增 ODS 模板管理：
  - 之前 17 个城市 skill 各自写一份 mapping，重复且不一致
  - 抽出后所有 ods_material_<city>_price 套用同一个 gov_ods 模板
  - 城市特化字段透参：setup_ods_index_templates(es_host, city_extensions={...})
"""
from .es_client import get_es_client
from .mappings import build_dwd_mapping, build_dws_mapping, build_ods_mapping


def setup_ods_index_templates(es_host: str, city_extensions: dict = None) -> None:
    """幂等创建/更新 gov_ods index template（适用所有 ods_material_*_price 索引）。

    Args:
        es_host: ES 地址
        city_extensions: {city_key: {field: mapping}} 城市特化字段。
            例如：
                city_extensions = {
                    "xinjiang": {"areaid": {"type": "integer"}, "area_name": {"type": "keyword"}},
                    "hainan":   {"remark": {"type": "text", ...}},  # 覆盖默认
                }
            不传则全城市用同一份标准模板。

    动态策略：dynamic=strict。未声明字段写入会被 ES 拒绝，迫使采集器更新 mapping。
    """
    s = get_es_client(es_host)

    # 1) 先创建 / 更新默认模板（不设城市特化）
    default = build_ods_mapping()
    r = s.put(
        f"{es_host}/_index_template/gov_ods",
        json={
            "index_patterns": ["ods_material_*_price"],
            "template": {"settings": default["settings"], "mappings": default["mappings"]},
            "priority": 100,
        },
    )
    tag = "OK" if r.status_code in (200, 201) else f"FAIL {r.status_code}"
    print(f"  [template] gov_ods → ods_material_*_price {tag}")

    # 2) 每个城市创建 / 更新一个高优先级特化模板
    if city_extensions:
        for city, ext in city_extensions.items():
            tpl = build_ods_mapping(city_extension=ext)
            r = s.put(
                f"{es_host}/_index_template/gov_ods_{city}",
                json={
                    "index_patterns": [f"ods_material_{city}_price"],
                    "template": {"settings": tpl["settings"], "mappings": tpl["mappings"]},
                    "priority": 200,  # 高于默认，足够多个模板匹配时优先取特化
                },
            )
            tag = "OK" if r.status_code in (200, 201) else f"FAIL {r.status_code}"
            print(f"  [template] gov_ods_{city} → ods_material_{city}_price {tag}")


def setup_dwd_dws_index_templates(es_host: str) -> None:
    """幂等创建/更新 gov_dwd / gov_dws 两个 index template。"""
    s = get_es_client(es_host)
    for name, pattern, mapping in [
        ("gov_dwd", "dwd_*", build_dwd_mapping()),
        ("gov_dws", "dws_*", build_dws_mapping()),
    ]:
        r = s.put(
            f"{es_host}/_index_template/{name}",
            json={
                "index_patterns": [pattern],
                "template": {"settings": mapping["settings"], "mappings": mapping["mappings"]},
                "priority": 100,
            },
        )
        tag = "OK" if r.status_code in (200, 201) else f"FAIL {r.status_code}"
        print(f"  [template] {name} → {pattern} {tag}")


# 向后兼容别名（历史代码调用 setup_index_templates）
setup_index_templates = setup_dwd_dws_index_templates


def ensure_indices(es_host: str, cfg: dict) -> None:
    """统一入口：确保 dwd/dws 索引存在，新建时自动套用 index template。"""
    setup_dwd_dws_index_templates(es_host)
    dwd_idx, dws_idx = cfg["dwd"], cfg["dws"]
    s = get_es_client(es_host)
    for idx in (dwd_idx, dws_idx):
        r = s.head(f"{es_host}/{idx}")
        if r.status_code == 404:
            print(f"  [idx] 创建索引 {idx} ...")
            s.put(f"{es_host}/{idx}", json={})  # template 自动套用
            print(f"  [idx] {idx} 创建完成（套用 template）")


def ensure_ods_index(es_host: str, ods_index: str, city_extension: dict = None) -> bool:
    """确保 ODS 索引存在。不存在则创建并套用标准 mapping。

    Args:
        es_host: ES 地址
        ods_index: 索引名（如 'ods_material_xinjiang_price'）
        city_extension: 城市特化字段，同 setup_ods_index_templates

    Returns:
        True 表示索引已存在或新建成功；False 表示新建失败。
    """
    s = get_es_client(es_host)
    r = s.head(f"{es_host}/{ods_index}")
    if r.status_code == 200:
        return True

    # 先创建 / 更新模板（幂等）
    setup_ods_index_templates(es_host, city_extensions={ods_index.rsplit("_", 1)[0].split("ods_material_")[-1]: city_extension} if city_extension else None)

    # 创建索引（不传 body，模板会自动套用）
    r = s.put(f"{es_host}/{ods_index}", json={})
    if r.status_code in (200, 201):
        print(f"  [idx] 创建 ODS {ods_index} 成功（套用 gov_ods 模板）")
        return True
    print(f"  [idx] 创建 ODS {ods_index} 失败: {r.status_code} {r.text[:200]}")
    return False


# ── backward compat stubs ──────────────────────────────────────────────
def ensure_dwd(es_host: str, dwd_index: str):
    pass  # now handled by ensure_indices


def ensure_dws(es_host: str, dws_index: str):
    pass  # now handled by ensure_indices
