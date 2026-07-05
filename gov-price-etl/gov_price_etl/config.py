"""config.py - 配置与城市注册表

从 config.yml 读 ES 连接参数；从本模块的 CITY_CONFIGS 查各城市的 ods/dwd/dws 索引名。
"""
from typing import Dict

from .paths import CONFIG_PATH


CITY_CONFIGS: Dict[str, Dict[str, str]] = {
    "xian": {
        "ods": "ods_material_xian_price",
        "dwd": "dwd_xian_price",
        "dws": "dws_xian_price",
        "city_label": "西安",
    },
    "sichuan": {
        "ods": "ods_material_sichuan_price",
        "dwd": "dwd_sichuan_price",
        "dws": "dws_sichuan_price",
        "city_label": "四川",
    },
    "chongqing": {
        "ods": "ods_material_chongqing_price",
        "dwd": "dwd_chongqing_price",
        "dws": "dws_chongqing_price",
        "city_label": "重庆",
    },
    "jinan": {
        "ods": "ods_material_jinan_price",
        "dwd": "dwd_jinan_price",
        "dws": "dws_jinan_price",  # 独立 dws 索引（2026-06-15 从 dwd_jinan_price 拆分）
        "city_label": "济南",
    },
    "rizhao": {
        "ods": "ods_material_rizhao_price",
        "dwd": "dwd_rizhao_price",
        "dws": "dws_rizhao_price",
        "city_label": "日照",
    },
    "henan": {
        "ods": "ods_material_henan_price",
        "dwd": "dwd_henan_price",
        "dws": "dws_henan_price",
        "city_label": "河南",
    },
    "heze": {
        "ods": "ods_material_heze_price",
        "dwd": "dwd_heze_price",
        "dws": "dws_heze_price",
        "city_label": "菏泽",
    },
    "qingdao": {
        "ods": "ods_material_qingdao_price",
        "dwd": "dwd_qingdao_price",
        "dws": "dws_qingdao_price",
        "city_label": "青岛",
    },
    "weihai": {
        "ods": "ods_material_weihai_price",
        "dwd": "dwd_weihai_price",
        "dws": "dws_weihai_price",
        "city_label": "威海",
    },
    "hainan": {
        "ods": "ods_material_hainan_price",
        "dwd": "dwd_hainan_price",
        "dws": "dws_hainan_price",
        "city_label": "海南",
    },
    "huhehaote": {
        "ods": "ods_material_huhehaote_price",
        "dwd": "dwd_huhehaote_price",
        "dws": "dws_huhehaote_price",
        "city_label": "呼和浩特",
    },
    "hunan": {
        "ods": "ods_material_hunan_price",
        "dwd": "dwd_hunan_price",
        "dws": "dws_hunan_price",
        "city_label": "湖南",
    },
    "jiangxi": {
        "ods": "ods_material_jiangxi_price",
        "dwd": "dwd_jiangxi_price",
        "dws": "dws_jiangxi_price",
        "city_label": "江西",
    },
    "ningxia": {
        "ods": "ods_material_ningxia_price",
        "dwd": "dwd_ningxia_price",
        "dws": "dws_ningxia_price",
        "city_label": "宁夏",
    },
    "qinghai": {
        "ods": "ods_material_qinghai_price",
        "dwd": "dwd_qinghai_price",
        "dws": "dws_qinghai_price",
        "city_label": "青海",
    },
    "shaanxi": {
        "ods": "ods_material_shaanxi_price",
        "dwd": "dwd_shaanxi_price",
        "dws": "dws_shaanxi_price",
        "city_label": "陕西",
    },
    "xinjiang": {
        "ods": "ods_material_xinjiang_price",
        "dwd": "dwd_xinjiang_price",
        "dws": "dws_xinjiang_price",
        "city_label": "新疆",
        # 2026-07-05 修：原 sort_field=_period，但 ODS mapping 实际有 update_date(date) 且无 _period，
        # 导致 _scroll_ods 返回 0 条（sort 字段不存在会静默失败）。
        # 当前 mapping update_date 已是 date 类型，直接用 update_date 即可。
        "sort_field": "update_date",
    },
}


def load_config() -> dict:
    """从项目根的 config.yml 读 ES 配置。"""
    import yaml
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)


def get_es_host() -> str:
    return load_config()["es"]["host"]
