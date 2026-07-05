---
name: rizhao-price
description: "日照工程造价材料信息采集,从 `http://58.59.43.227:81/EpointSDRZ` 抓取数据,按分类目录跟踪,同步至 Elasticsearch。覆盖 1 个分类。"
---

# 日照 · 工程造价材料信息采集

> 省份:山东 · 进度模式:`catalogue` · 范围(1): 日照市

## 数据流

```
源站: http://58.59.43.227:81/EpointSDRZ
   ↓ (commands/sync.py)
ods_material_rizhao_price
   ↓ (<skills>/gov-price-etl cli/etl.py --city rizhao)
dwd_rizhao_price
   ↓ (cli/sync_dws.py --city rizhao --mode quick)
dws_rizhao_price
```

## 快速开始

```bash
cd <skills>/rizhao-price
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
| `sync` | `commands/sync.py` | 同步到 ES（默认 Collector 路径，推荐） |
| `sync` | `commands/sync.py` | --periods 2026-01..2026-05  多期范围语法：5 期 × 3 tab = 15 units |
| `sync` | `commands/sync.py` | --periods 2026-01,2026-02   多期列表语法 |
| `sync` | `commands/sync.py` | --tabs 1                 只抓建设工程材料（1=建设, 2=苗木, 3=区县） |
| `sync` | `commands/sync.py` | --tabs 1,3               抓建设+区县，跳过苗木 |
| `sync` | `commands/sync.py` | --reset                  重置本地进度，重新开始 |
| `sync` | `commands/sync.py` | --max-units 1            验证模式：只跑前 1 个 unit |
| `sync` | `commands/sync.py` | --legacy                 走 v0 流式旧路径（逃生通道） |
| `preview` | `commands/preview.py` | 预览前 N 页数据（默认 2 页，兼容旧调用） |
| `status` | `commands/status.py` | 查看同步状态 |
| `check` | `commands/check.py` | 检查源站是否有新数据（兼容旧调用） |
| `test` | `commands/test.py` | 测试 ES 和源站连接 |
| `每个` | `commands/每个.py` | doc 必含 period_start / period_end / period_days（v1.0 新增） |
| `period` | `commands/period.py` | 格式：'YYYY-MM'（如 '2026-05'）→ 推算 start/end/days |
| `源站支持` | `commands/源站支持.py` | 2026-01 ~ 2026-05 历史期回溯 |
| `5` | `commands/5.py` | 期 × 3 tab = 15 units，约 80 秒（1 次浏览器启动 + 15 unit API） |

## sync 关键参数

- `--tabs` — tab 列表（逗号分隔），如
- `--period` — 指定单个周期（如
- `--periods` — 多周期（v1.1）：逗号分隔
- `--run-id` — 指定 run_id（默认自动生成）
- `--max-pages` — 最大页数（默认 2000，v1.1 已无实际作用）
- `--reset` — 重置本地进度，重新开始
- `--max-units` — Collector 路径：只跑前 N 个工作单元（验证用）
- `--legacy` — v0 兼容：走原流式同步（旧生产路径）。默认走 Collector
- `--dry-run` — 预览模式（仅 legacy 路径支持）
- `--force` — 强制全量同步（仅 legacy 路径支持）

## ES 索引

| 索引 | 说明 |
|------|------|
| `ods_material_rizhao_price` | 原始抓取数据(主数据) |
| `ods_rizhao_price_sync_progress` | 同步进度(按 run_id 分组) |
| `dwd_rizhao_price` | ETL 清洗层 |
| `dws_rizhao_price` | 看板查询层 |

## 配置(config.yml)

```yaml
es:
  host: http://localhost:59200
  index: ods_material_rizhao_price
  progress_index: ods_rizhao_price_sync_progress
site:
  base_url: http://58.59.43.227:81/EpointSDRZ
  counties/tabs:
  - 日照市
sync:
  last_period: 2026-05
  progress_file: .rizhao_sync_progress.json
```

## 项目结构

```
rizhao-price/
├── run.sh
├── config.yml
└── commands/
    ├── check.py
    ├── fetch_data.py
    ├── legacy_sync.py
    ├── preview.py
    ├── rizhao_collector.py
    ├── status.py
    ├── sync.py
    ├── test.py
    ├── utils.py
```

## 依赖

- Python 3
- requests / beautifulsoup4 / pyyaml / elasticsearch

## 相关

- <skills>/gov-price-dashboard — 看板(查 DWS 数据)
- <skills>/gov-price-etl — ETL 公共层
