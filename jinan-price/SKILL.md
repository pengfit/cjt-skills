# jinan-price

济南工程造价材料信息采集。从 `jnxxj.jngczjxh.com:5020` 抓取材料价格数据，支持多分类、多周期、断点续传、增量自动检测。写入 `ods_material_jinan_price`。

## 快速启动

```bash
cd skills/jinan-price

./run.sh sync              # 增量同步（首次全量，后续只同步增量）
./run.sh sync --force      # 强制全量同步
./run.sh sync --dry-run    # 预览模式，不写入 ES
./run.sh sync --reset      # 重置进度，从头开始
./run.sh preview           # 预览数据
./run.sh status            # 查看同步进度
./run.sh check             # 手动触发增量检测
```

## 数据流

```
jnxxj.jngczjxh.com:5020 → sync.py → ods_material_jinan_price
                                          ↓
                                gov-price-etl (etl.py)
                                          ↓
                                dwd_jinan_price
                                          ↓
                                sync_dws.py
                                          ↓
                                dws_jinan_price
```

## 增量机制

- **周期维度**：网站 API 返回最新周期 ID，与 config 对比，不同则触发全量同步
- **分类记录数维度**：同周期内逐分类对比网站 total vs ES doc_count，差值为正则触发增量

## 数据字段

| 字段 | 说明 |
|------|------|
| `breed` | 材料名称 |
| `spec` | 规格型号 |
| `unit` | 单位 |
| `price` | 含税价格 |
| `period` / `period_id` | 周期名称/ID |
| `province` | 山东 |
| `city` | 济南 |
| `catalogue_name` | 分类目录名称 |
| `code` | 材料编码 |
| `update_date` | 更新日期 |
| `publish_time` | 发布时间 |

## ES 索引

| 索引 | 说明 |
|------|------|
| `ods_material_jinan_price` | 材料价格数据 |
| `ods_material_jinan_price_catalogue` | 分类目录（42 条）|
| `ods_material_jinan_price_sync_progress` | 同步进度记录 |

## 幂等写入

```
_id = MD5(breed + spec + period + period_id + catalogue_id + price)
```

## 断点续传

进度保存到 `.jinan_sync_progress.json`，中断后 `./run.sh sync` 自动续传。

## 项目结构

```
jinan-price/
├── run.sh
├── config.yml
├── .jinan_sync_progress.json
└── commands/
    ├── sync.py     # 同步主程序
    ├── preview.py
    ├── status.py
    ├── test.py
    ├── check.py    # 增量检测（定时触发）
    └── utils.py
```

## 依赖

- Python 3
- requests / beautifulsoup4 / pyyaml
- elasticsearch