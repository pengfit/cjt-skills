# chongqing-price

重庆工程造价材料信息采集。从 `www.cqsgczjxx.org` 抓取重庆市区县材料价格数据，通过 openclaw browser 自动化同步至本地 ES，写入 `ods_material_chongqing_price`。

## 快速启动

```bash
cd skills/chongqing-price

# 前提：openclaw browser 已打开目标页面
openclaw browser open "http://www.cqsgczjxx.org/Pages/CQZJW/priceInformation.aspx"

# 同步
python3 commands/sync.py --tab-id <tab-id>

# 重置进度，重新开始
python3 commands/sync.py --tab-id <tab-id> --reset

# 查看状态
python3 commands/status.py
```

## 数据流

```
www.cqsgczjxx.org → openclaw browser → ods_material_chongqing_price
                                                  ↓
                                        gov-price-etl (etl.py)
                                                  ↓
                                        dwd_chongqing_price
                                                  ↓
                                        sync_dws.py
                                                  ↓
                                        dws_chongqing_price
```

## 支持区县（35 个）

主城区、万州区、涪陵区、黔江区、长寿区、江津区、合川区、永川区、南川区、梁平区、城口县、丰都县、垫江县、忠县、开州区、云阳县、奉节县、巫山县、巫溪县、石柱县、秀山县、酉阳县、大足区、綦江区、万盛经开区、双桥经开区、铜梁区、璧山区、彭水县、荣昌区、潼南区、武隆区 等

## 数据字段

| 字段 | 说明 |
|------|------|
| `breed` | 材料名称 |
| `spec` | 规格型号 |
| `unit` | 单位 |
| `price` | 不含税价格 |
| `tax_price` | 含税价格 |
| `is_tax` | 含税/不含税 |
| `period` | 周期名称 |
| `province` | 重庆 |
| `city` / `county` | 区县 |
| `update_date` | 更新日期 |
| `create_time` | 入库时间 |

## ES 索引

| 索引 | 说明 |
|------|------|
| `ods_material_chongqing_price` | 材料价格数据 |
| `ods_chongqing_price_progress` | 同步进度记录 |

## 幂等写入

```
_id = MD5(breed + spec + period + price + tax_price + county)
```

## 断点续传

进度保存在 `.chongqing_sync_progress.json`，中断后 `./run.sh sync` 自动续传。

## 项目结构

```
chongqing-price/
├── config.yml
├── .chongqing_sync_progress.json
└── commands/
    ├── sync.py      # 同步入口
    ├── write_es.py # ES 写入 + 浏览器自动化
    ├── status.py
    ├── test.py
    └── utils.py
```

## 依赖

- Python 3
- openclaw browser（已打开目标页面）
- requests / pyyaml
- elasticsearch