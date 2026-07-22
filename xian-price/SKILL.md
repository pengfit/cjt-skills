---
name: xian-price
description: "西安工程造价材料信息采集,从 `https://zjj.xa.gov.cn/zxcx/gczj/index.aspx` 抓取数据,按区县跟踪,同步至 Elasticsearch。覆盖 6 个区县。"
---

# 西安 · 工程造价材料信息采集

> 省份:陕西 · 进度模式:`county` · 范围(6): 阎良区, 临潼区, 高陵区, 鄠邑区, 蓝田县, 周至县

## 数据流

```
源站: https://zjj.xa.gov.cn/zxcx/gczj/index.aspx
   ↓ (commands/sync.py)
ods_material_xian_price
   ↓ ([gov-price-etl](../../gov-price-etl/) cli/etl.py --city xian)
dwd_xian_price
   ↓ (cli/sync_dws.py --city xian --mode quick)
dws_xian_price
   ↓ ([gov-price-normalization](../../gov-price-normalization/) · Normalizer worker)
norm_xian_price                          ← Dashboard 默认查 NORM，DWS 作 fallback
```

下游框架:
- ETL 三段式清洗 + attr 治本 L2 封堵 — [gov-price-etl](../../gov-price-etl/)
- NORM 标准化 + attr 治本 L1 净化 — [gov-price-normalization](../../gov-price-normalization/)
- 可视化(默认查 NORM) — [gov-price-dashboard](../../gov-price-dashboard/)

## 快速开始

```bash
cd <skills>/xian-price
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

- `--force` — _无说明_
- `--max-pages` — _无说明_
- `--counties` — _无说明_
- `--resume-from` — _无说明_
- `--reset` — _无说明_
- `--no-log` — _无说明_
- `--no-spot-check` — _无说明_
- `--period` — 指定周期，逗号分隔，如 2026-01,2026-02
- `--periods-year` — 指定整年的所有月份，如 2026
- `--periods-all` — 抓取所有有数据的年月（源站 2024 至今）
- `--list-periods` — 只列出可用周期，不抓取
- `--dry-run` — 预览模式（不写入 ES）
- `--periods` — 多周期，逗号分隔，如
- `--list-year` — --list-periods 时限定年份
- `--max-units` — 只跑前 N 个 unit（验证用）
- `--run-id` — 指定 run_id（默认自动生成）
- `--legacy` — v0.6 兼容：走原 main 流程。默认走 Collector。
- `--no-progress` — 不写 ES progress 索引

## ES 索引

| 索引 | 说明 |
|------|------|
| `ods_material_xian_price` | 原始抓取数据(主数据) |
| `ods_material_xian_price_sync_progress` | 同步进度(按 run_id 分组) |
| `dwd_xian_price` | ETL 清洗层 |
| `dws_xian_price` | 看板查询层 |

## 配置(config.yml)

```yaml
es:
  host: http://localhost:59200
  index: ods_material_xian_price
  progress_index: ods_material_xian_price_sync_progress
site:
  base_url: https://zjj.xa.gov.cn/zxcx/gczj/index.aspx
  counties/tabs:
  - 阎良区
  - 临潼区
  - 高陵区
  - 鄠邑区
  - 蓝田县
  - 周至县
sync:
  last_update_date: 2026-06-24
```

## 项目结构

```
xian-price/
├── run.sh
├── config.yml
└── commands/
    ├── check.py
    ├── preview.py
    ├── status.py
    ├── sync.py
    ├── sync_diff.py
    ├── test.py
    ├── utils.py
    ├── xian_collector.py
```

## 依赖

- Python 3
- requests / beautifulsoup4 / pyyaml / elasticsearch

## 相关

- <skills>/gov-price-dashboard — 看板(查 DWS 数据)
- <skills>/gov-price-etl — ETL 公共层
