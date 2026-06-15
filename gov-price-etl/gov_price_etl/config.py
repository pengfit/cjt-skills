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
}


def load_config() -> dict:
    """从项目根的 config.yml 读 ES 配置。"""
    import yaml
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)


def get_es_host() -> str:
    return load_config()["es"]["host"]
