---
name: ningxia-price
description: "宁夏工程造价材料信息采集,从 `https://jst.nx.gov.cn/ztzl/gczj/zjtt/index.html` 抓取数据,按期期刊跟踪,同步至 Elasticsearch。覆盖 5 个期数。"
---

# 宁夏 · 工程造价材料信息采集

> 省份:宁夏 · 进度模式:`period` · 范围(5): 银川市, 石嘴山市, 吴忠市, 固原市, 中卫市

## 数据流

```
源站: https://jst.nx.gov.cn/ztzl/gczj/zjtt/index.html
   ↓ (commands/sync.py)
ods_material_ningxia_price
   ↓ ([gov-price-etl](../../gov-price-etl/) cli/etl.py --city ningxia)
dwd_ningxia_price
   ↓ (cli/sync_dws.py --city ningxia --mode quick)
dws_ningxia_price
   ↓ ([gov-price-normalization](../../gov-price-normalization/) · Normalizer worker)
norm_ningxia_price                          ← Dashboard 默认查 NORM，DWS 作 fallback
```

下游框架:
- ETL 三段式清洗 + attr 治本 L2 封堵 — [gov-price-etl](../../gov-price-etl/)
- NORM 标准化 + attr 治本 L1 净化 — [gov-price-normalization](../../gov-price-normalization/)
- 可视化(默认查 NORM) — [gov-price-dashboard](../../gov-price-dashboard/)

## 快速开始

```bash
cd <skills>/ningxia-price
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
| `check` | `commands/check.py` | 增量检测（不写入） |
| `test` | `commands/test.py` | 测试连通性 |

## sync 关键参数

- `--year` — 同步年份（默认 2026）
- `--period` — 限定周期（标题含此串），如
- `--exclude-period` — 排除周期
- `--all` — 同步所有未入仓的期（不限于指定年份）
- `--reset` — 重置本地进度
- `--dry-run` — 只解析不入库
- `--latest` — 只同步最新一期
- `--max-units` — 最多处理多少期（测试用，0=全部）
- `--legacy` — 走 v3 旧路径（逃生通道）
- `--run-id` — 本次运行标识（默认自动生成）

## ES 索引

| 索引 | 说明 |
|------|------|
| `ods_material_ningxia_price` | 原始抓取数据(主数据) |
| `ods_material_ningxia_price_sync_progress` | 同步进度(按 run_id 分组) |
| `dwd_ningxia_price` | ETL 清洗层 |
| `dws_ningxia_price` | 看板查询层 |

## 配置(config.yml)

```yaml
es:
  host: http://localhost:59200
  index: ods_material_ningxia_price
  progress_index: ods_material_ningxia_price_sync_progress
site:
  base_url: https://jst.nx.gov.cn/ztzl/gczj/zjtt/index.html
  counties/tabs:
  - 银川市
  - 石嘴山市
  - 吴忠市
  - 固原市
  - 中卫市
sync:
  last_period: 
  last_publish_date: 
```

## 项目结构

```
ningxia-price/
├── run.sh
├── config.yml
└── commands/
    ├── check.py
    ├── ningxia_collector.py
    ├── preview.py
    ├── status.py
    ├── sync.py
    ├── sync_legacy.py
    ├── sync_v3_legacy.py
    ├── utils.py
```

## 依赖

- Python 3
- requests / beautifulsoup4 / pyyaml / elasticsearch

## 相关

- <skills>/gov-price-dashboard — 看板(查 DWS 数据)
- <skills>/gov-price-etl — ETL 公共层
