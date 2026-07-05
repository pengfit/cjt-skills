---
name: heze-price
description: "菏泽工程造价材料信息采集,从 `http://hzszjj.heze.gov.cn` 抓取数据,按期期刊跟踪,同步至 Elasticsearch。覆盖 1 个期数。"
---

# 菏泽 · 工程造价材料信息采集

> 省份:山东 · 进度模式:`period` · 范围(1): 菏泽

## 数据流

```
源站: http://hzszjj.heze.gov.cn
   ↓ (commands/sync.py)
ods_material_heze_price
   ↓ (<skills>/gov-price-etl cli/etl.py --city heze)
dwd_heze_price
   ↓ (cli/sync_dws.py --city heze --mode quick)
dws_heze_price
```

## 快速开始

```bash
cd <skills>/heze-price
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
| `sync` | `commands/sync.py` | 同步到 ES（v0.8 默认走 HezeCollector，加 --legacy 走 v0.7） |
| `status` | `commands/status.py` | 查看状态 |
| `check` | `commands/check.py` | 增量检测（不写入） |
| `sync` | `commands/sync.py` | 常用参数: |
| `--year` | `commands/--year.py` | 2026          只入库指定年份（默认本年，0=不限制） |
| `--period` | `commands/--period.py` | 2026.1期    指定单期 |
| `--latest` | `commands/--latest.py` | 只同步最新一期 |
| `--reset` | `commands/--reset.py` | 重置本地进度 |
| `--legacy` | `commands/--legacy.py` | 走 v0.7 cmd_legacy_sync（逃生通道） |
| `--dry-run` | `commands/--dry-run.py` | 预览不写入（仅 legacy 支持） |
| `--max-units` | `commands/--max-units.py` | N        Collector 路径：只跑前 N 个工作单元（验证用） |

## sync 关键参数

- `--period` — 指定周期（如 2026.1期）
- `--year` — _无说明_
- `--all` — 同步所有未入仓的期
- `--reset` — 重置进度
- `--dry-run` — 预览，不写入（仅 legacy 支持）
- `--latest` — 只同步最新一期
- `--run-id` — 指定 run_id（默认自动生成）
- `--legacy` — v0.7 兼容：走原 main 流程。默认走 Collector（推荐）。
- `--max-units` — Collector 路径：只跑前 N 个工作单元（验证用）

## ES 索引

| 索引 | 说明 |
|------|------|
| `ods_material_heze_price` | 原始抓取数据(主数据) |
| `ods_material_heze_price_sync_progress` | 同步进度(按 run_id 分组) |
| `dwd_heze_price` | ETL 清洗层 |
| `dws_heze_price` | 看板查询层 |

## 配置(config.yml)

```yaml
es:
  host: http://localhost:59200
  index: ods_material_heze_price
  progress_index: ods_material_heze_price_sync_progress
site:
  base_url: http://hzszjj.heze.gov.cn
  counties/tabs:
  - 菏泽
sync:
  last_period: 
  last_publish_date: 
```

## 项目结构

```
heze-price/
├── run.sh
├── config.yml
└── commands/
    ├── check.py
    ├── heze_collector.py
    ├── preview.py
    ├── status.py
    ├── sync.py
    ├── utils.py
```

## 依赖

- Python 3
- requests / beautifulsoup4 / pyyaml / elasticsearch

## 相关

- <skills>/gov-price-dashboard — 看板(查 DWS 数据)
- <skills>/gov-price-etl — ETL 公共层
