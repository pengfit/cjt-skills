---
name: shaanxi-price
description: "陕西工程造价材料信息采集,从 `https://js.shaanxi.gov.cn/sy/yw/zjglfw/zjxx/index.html` 抓取数据,按期期刊跟踪,同步至 Elasticsearch。覆盖 11 个期数。"
---

# 陕西 · 工程造价材料信息采集

> 省份:陕西 · 进度模式:`period` · 范围(11): 陕西, 安康, 汉中, 咸阳, 铜川, 渭南, 延安, 榆林, 商洛, 宝鸡, 西安

## 数据流

```
源站: https://js.shaanxi.gov.cn/sy/yw/zjglfw/zjxx/index.html
   ↓ (commands/sync.py)
ods_material_shaanxi_price
   ↓ ([gov-price-etl](../../gov-price-etl/) cli/etl.py --city shaanxi)
dwd_shaanxi_price
   ↓ (cli/sync_dws.py --city shaanxi --mode quick)
dws_shaanxi_price
   ↓ ([gov-price-normalization](../../gov-price-normalization/) · Normalizer worker)
norm_shaanxi_price                          ← Dashboard 默认查 NORM，DWS 作 fallback
```

下游框架:
- ETL 三段式清洗 + attr 治本 L2 封堵 — [gov-price-etl](../../gov-price-etl/)
- NORM 标准化 + attr 治本 L1 净化 — [gov-price-normalization](../../gov-price-normalization/)
- 可视化(默认查 NORM) — [gov-price-dashboard](../../gov-price-dashboard/)

## 快速开始

```bash
cd <skills>/shaanxi-price
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
| `preview` | `commands/preview.py` | 预览数据（不写 ES、不传 MinIO） |
| `sync` | `commands/sync.py` | 同步到 ES + MinIO |
| `status` | `commands/status.py` | 查看同步状态 |
| `test` | `commands/test.py` | 测试连通性（ES + MinIO + 源站） |
| `check` | `commands/check.py` | 增量检测（不写入） |
| `sync` | `commands/sync.py` | 选项: |
| `--period` | `commands/--period.py` | 2026.5月        指定 period（如 '2026.5月'、'2026.5期'） |
| `--year` | `commands/--year.py` | 2026             只入指定年份（默认配置中的 target_year=2026） |
| `--latest` | `commands/--latest.py` | 只同步最新一期 |
| `--reset` | `commands/--reset.py` | 重置本地进度 |
| `--all` | `commands/--all.py` | 同步所有未入仓的期 |
| `--dry-run` | `commands/--dry-run.py` | 预览，不写入 |

## sync 关键参数

- `--period` — 指定 period（如
- `--year` — 只入库指定年份（默认 cfg.sync.target_year=2026）
- `--all` — 同步所有未入仓的期（v0.5 兼容）
- `--reset` — 重置本地进度，从头开始
- `--dry-run` — 预览，不写入 ES / MinIO
- `--latest` — 只同步最新一期
- `--limit` — 最多同步 N 期（0=全部，兼容 v0.5）
- `--run-id` — 指定 run_id（默认 sn_run_YYYYMMDD_HHMMSS）
- `--max-units` — Collector 路径：只跑前 N 个工作单元（验证用）
- `--legacy` — v0.5 兼容：走 sync_legacy.py（旧生产路径）。**默认走 Collector**。

## ES 索引

| 索引 | 说明 |
|------|------|
| `ods_material_shaanxi_price` | 原始抓取数据(主数据) |
| `ods_material_shaanxi_price_sync_progress` | 同步进度(按 run_id 分组) |
| `dwd_shaanxi_price` | ETL 清洗层 |
| `dws_shaanxi_price` | 看板查询层 |

## 配置(config.yml)

```yaml
es:
  host: http://localhost:59200
  index: ods_material_shaanxi_price
  progress_index: ods_material_shaanxi_price_sync_progress
site:
  base_url: https://js.shaanxi.gov.cn/sy/yw/zjglfw/zjxx/index.html
  counties/tabs:
  - 陕西
  - 安康
  - 汉中
  - 咸阳
  - 铜川
  - 渭南
  - 延安
  - 榆林
  - 商洛
  - 宝鸡
  - 西安
sync:
  target_year: 2026
  last_period: 
  last_publish_date: 
```

## 项目结构

```
shaanxi-price/
├── run.sh
├── config.yml
└── commands/
    ├── check.py
    ├── city_parsers.py
    ├── pdf_parser.py
    ├── preview.py
    ├── shaanxi_collector.py
    ├── status.py
    ├── sync.py
    ├── sync_legacy.py
    ├── test.py
    ├── utils.py
```

## 依赖

- Python 3
- requests / beautifulsoup4 / pyyaml / elasticsearch

## 相关

- <skills>/gov-price-dashboard — 看板(查 DWS 数据)
- <skills>/gov-price-etl — ETL 公共层
