---
name: weihai-price
description: "威海工程造价材料信息采集,从 `https://zjj.weihai.gov.cn/col/col28584/index.html` 抓取数据,按期期刊跟踪,同步至 Elasticsearch。覆盖 1 个期数。"
---

# 威海 · 工程造价材料信息采集

> 省份:山东 · 进度模式:`period` · 范围(1): 威海

## 数据流

```
源站: https://zjj.weihai.gov.cn/col/col28584/index.html
   ↓ (commands/sync.py)
ods_material_weihai_price
   ↓ ([gov-price-etl](../../gov-price-etl/) cli/etl.py --city weihai)
dwd_weihai_price
   ↓ (cli/sync_dws.py --city weihai --mode quick)
dws_weihai_price
   ↓ ([gov-price-normalization](../../gov-price-normalization/) · Normalizer worker)
norm_weihai_price                          ← Dashboard 默认查 NORM，DWS 作 fallback
```

下游框架:
- ETL 三段式清洗 + attr 治本 L2 封堵 — [gov-price-etl](../../gov-price-etl/)
- NORM 标准化 + attr 治本 L1 净化 — [gov-price-normalization](../../gov-price-normalization/)
- 可视化(默认查 NORM) — [gov-price-dashboard](../../gov-price-dashboard/)

## 快速开始

```bash
cd <skills>/weihai-price
./run.sh preview          # 预览数据(不写 ES)
./run.sh sync             # 增量同步(自动断点续传)
./run.sh sync --force     # 强制全量同步
./run.sh status           # 查看同步状态
./run.sh check            # 增量检测
./run.sh test             # 测试 ES / 源站连通性
```

## 命令清单

| 命令 | 脚本 | 说明 |
|------|------|------|
| `preview` | `commands/preview.py` | 预览数据 |
| `sync` | `commands/sync.py` | 同步到 ES |
| `status` | `commands/status.py` | 查看状态 |
| `test` | `commands/test.py` | 测试连通性 |
| `check` | `commands/check.py` | 增量检测（不写入） |

## sync 关键参数

- `--reset` — 重置本地进度，重新开始
- `--year` — 只入库指定年份（默认走 config.yml 的 default_year，0=不限制）
- `--period` — 指定 period（如 2026.1-3月）
- `--latest` — 只同步最新一期
- `--run-id` — 指定 run_id（默认 weihai_YYYYMMDD_HHMMSS）
- `--legacy` — 走 sync_legacy.py 主函数路径（逃生通道，不推荐）

## ES 索引

| 索引 | 说明 |
|------|------|
| `ods_material_weihai_price` | 原始抓取数据(主数据) |
| `ods_material_weihai_price_sync_progress` | 同步进度(按 run_id 分组) |
| `dwd_weihai-price_price` | ETL 清洗层 |
| `dws_weihai_price` | 看板查询层 |

## 配置(config.yml)

```yaml
es:
  host: http://localhost:59200
  index: ods_material_weihai_price
  progress_index: ods_material_weihai_price_sync_progress
site:
  base_url: https://zjj.weihai.gov.cn/col/col28584/index.html
  counties/tabs:
  - 威海
sync:
  last_period: 
  last_publish_date: 
  default_year: 2026
```

## 项目结构

```
weihai-price/
├── run.sh
├── config.yml
└── commands/
    ├── check.py
    ├── preview.py
    ├── status.py
    ├── sync.py
    ├── sync_legacy.py
    ├── test.py
    ├── utils.py
    ├── weihai_collector.py
```

## 依赖

- Python 3
- requests / beautifulsoup4 / pyyaml / elasticsearch

## 相关

- <skills>/gov-price-dashboard — 看板(查 DWS 数据)
- <skills>/gov-price-etl — ETL 公共层
