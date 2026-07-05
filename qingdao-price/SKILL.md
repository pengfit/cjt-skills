---
name: qingdao-price
description: "青岛工程造价材料信息采集,从 `https://sjw.qingdao.gov.cn/cxjsj13/cxjs_95/cxjsj_zj5/` 抓取数据,按期期刊跟踪,同步至 Elasticsearch。覆盖 1 个期数。"
---

# 青岛 · 工程造价材料信息采集

> 省份:山东 · 进度模式:`period` · 范围(1): 青岛

## 数据流

```
源站: https://sjw.qingdao.gov.cn/cxjsj13/cxjs_95/cxjsj_zj5/
   ↓ (commands/sync.py)
ods_material_qingdao_price
   ↓ (<skills>/gov-price-etl cli/etl.py --city qingdao)
dwd_qingdao-price_price
   ↓ (cli/sync_dws.py --city qingdao --mode quick)
dws_qingdao_price
```

## 快速开始

```bash
cd <skills>/qingdao-price
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

- `--period` — 指定周期（兼容 v0.8 单周期过滤）
- `--year` — 只入库指定年份（默认走 config.yml 的 default_year，0=不限制）
- `--all` — 同步所有未入仓的期（v0.8 兼容）
- `--reset` — 重置本地进度，从头开始
- `--dry-run` — 预览，不写入 ES / MinIO
- `--latest` — 只同步最新一期
- `--run-id` — 指定 run_id
- `--max-units` — Collector 路径：只跑前 N 个工作单元（验证用）
- `--legacy` — v0.8 兼容：走旧 sync.py（仅在 Collector 异常时备用）

## ES 索引

| 索引 | 说明 |
|------|------|
| `ods_material_qingdao_price` | 原始抓取数据(主数据) |
| `ods_material_qingdao_price_sync_progress` | 同步进度(按 run_id 分组) |
| `dwd_qingdao-price_price` | ETL 清洗层 |
| `dws_qingdao_price` | 看板查询层 |

## 配置(config.yml)

```yaml
es:
  host: http://localhost:59200
  index: ods_material_qingdao_price
  progress_index: ods_material_qingdao_price_sync_progress
site:
  base_url: https://sjw.qingdao.gov.cn/cxjsj13/cxjs_95/cxjsj_zj5/
  counties/tabs:
  - 青岛
sync:
  last_period: 
  last_publish_date: 
  default_year: 2026
```

## 项目结构

```
qingdao-price/
├── run.sh
├── config.yml
└── commands/
    ├── check.py
    ├── preview.py
    ├── qingdao_collector.py
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
