---
name: jinan-price
description: "济南工程造价材料信息采集,从 `http://jnxxj.jngczjxh.com:5020/cj/api/build` 抓取数据,按分类目录跟踪,同步至 Elasticsearch。覆盖 1 个分类。"
---

# 济南 · 工程造价材料信息采集

> 省份:山东 · 进度模式:`catalogue` · 范围(1): 济南市

## 数据流

```
源站: http://jnxxj.jngczjxh.com:5020/cj/api/build
   ↓ (commands/sync.py)
ods_material_jinan_price
   ↓ (<skills>/gov-price-etl cli/etl.py --city jinan)
dwd_jinan_price
   ↓ (cli/sync_dws.py --city jinan --mode quick)
dws_jinan_price
```

## 快速开始

```bash
cd <skills>/jinan-price
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
- `--legacy` — v0 兼容：走原 sync 主流程（不推荐）
- `--periods` — 多周期，逗号分隔（精确匹配 periodName），如
- `--year` — 按年份过滤（0=用 config.sync.year）
- `--run-id` — 自定义 run_id
- `--dry-run` — 预览模式，不写入 ES
- `--max-units` — 只跑前 N 个工作单元（验证用）

## ES 索引

| 索引 | 说明 |
|------|------|
| `ods_material_jinan_price` | 原始抓取数据(主数据) |
| `material_jinan_price_sync_progress` | 同步进度(按 run_id 分组) |
| `dwd_jinan_price` | ETL 清洗层 |
| `dws_jinan_price` | 看板查询层 |

## 配置(config.yml)

```yaml
es:
  host: http://localhost:59200
  index: ods_material_jinan_price
  progress_index: material_jinan_price_sync_progress
site:
  base_url: http://jnxxj.jngczjxh.com:5020/cj/api/build
  counties/tabs:
  - 济南市
sync:
  last_period: 2026年05月材料价格信息
  last_period_id: 811589252355269
  last_run_at: 2026-07-03 15:42:31
  last_run_id: jn_run_20260703_153817
  size_per_page: 100
  year: 2026
```

## 项目结构

```
jinan-price/
├── run.sh
├── config.yml
└── commands/
    ├── check.py
    ├── jinan_collector.py
    ├── preview.py
    ├── status.py
    ├── sync.py
    ├── test.py
    ├── utils.py
    ├── write_es.py
```

## 依赖

- Python 3
- requests / beautifulsoup4 / pyyaml / elasticsearch

## 相关

- <skills>/gov-price-dashboard — 看板(查 DWS 数据)
- <skills>/gov-price-etl — ETL 公共层
