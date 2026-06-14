"""gov_price_etl - 政府材料价格数据入仓 ETL

将各城市 ODS 层原始数据（`ods_material_{city}_price`）清洗为结构化层（DWD）`dwd_{city}_price`，
再聚合同步到展示层（DWS）`dws_{city}_price`。

支持城市见 `config.CITY_CONFIGS`。
"""
__version__ = "0.2.0"
