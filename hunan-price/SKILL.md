---
name: hunan-price
description: "湖南工程造价材料信息采集,从 `https://zjt.hunan.gov.cn/zjt/hnweb/xzzx/zlxx/index.html` 抓取数据,按期期刊跟踪,同步至 Elasticsearch。覆盖 14 个期数。"
---

# 湖南 · 工程造价材料信息采集

> 省份:湖南 · 进度模式:`period` · 范围(14): 长沙市, 株洲市, 湘潭市, 岳阳市, 永州市, 益阳市, 怀化市, 张家界市, 常德市, 湘西自治州, 衡阳市, 娄底市, 郴州市, 邵阳市

## 数据流

```
源站: https://zjt.hunan.gov.cn/zjt/hnweb/xzzx/zlxx/index.html
   ↓ (commands/sync.py)
ods_material_hunan_price
   ↓ ([gov-price-etl](../../gov-price-etl/) cli/etl.py --city hunan)
dwd_hunan_price
   ↓ (cli/sync_dws.py --city hunan --mode quick)
dws_hunan_price
   ↓ ([gov-price-normalization](../../gov-price-normalization/) · Normalizer worker)
norm_hunan_price                          ← Dashboard 默认查 NORM，DWS 作 fallback
```

下游框架:
- ETL 三段式清洗 + attr 治本 L2 封堵 — [gov-price-etl](../../gov-price-etl/)
- NORM 标准化 + attr 治本 L1 净化 — [gov-price-normalization](../../gov-price-normalization/)
- 可视化(默认查 NORM) — [gov-price-dashboard](../../gov-price-dashboard/)

## 快速开始

```bash
cd <skills>/hunan-price
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

- `--period` — 指定周期（兼容旧参数；Collector 走 --year）
- `--year` — 只入库指定年份（默认走 config.year）
- `--exclude-period` — 排除指定周期（仅 legacy 路径生效）
- `--all` — 同步所有未入仓的期（仅 legacy 路径生效）
- `--reset` — 重置本地进度，重新开始
- `--dry-run` — 预览，不写入（仅 legacy 路径生效）
- `--latest` — 只同步最新一期（仅 legacy 路径生效）
- `--legacy` — v0.x 兼容：走原 cmd_legacy_sync（旧主流程）。**默认走 Collector**。仅在 Collector 异常时备用。
- `--kinds` — Collector 限定 kind（逗号分隔），默认两种都跑
- `--max-units` — Collector 路径：只跑前 N 个工作单元（验证用），不传则跑全部
- `--run-id` — 指定 run_id（默认自动生成 v08_YYYYMMDD_HHMMSS）

## ES 索引

| 索引 | 说明 |
|------|------|
| `ods_material_hunan_price` | 原始抓取数据(主数据) |
| `ods_material_hunan_price_sync_progress` | 同步进度(按 run_id 分组) |
| `dwd_hunan_price` | ETL 清洗层 |
| `dws_hunan_price` | 看板查询层 |

## 配置(config.yml)

```yaml
es:
  host: http://localhost:59200
  index: ods_material_hunan_price
  progress_index: ods_material_hunan_price_sync_progress
site:
  base_url: https://zjt.hunan.gov.cn/zjt/hnweb/xzzx/zlxx/index.html
  counties/tabs:
  - 长沙市
  - 株洲市
  - 湘潭市
  - 岳阳市
  - 永州市
  - 益阳市
  - 怀化市
  - 张家界市
  - 常德市
  - 湘西自治州
  - 衡阳市
  - 娄底市
  - 郴州市
  - 邵阳市
sync:
  last_period: 
  last_publish_date: 
```

## 项目结构

```
hunan-price/
├── run.sh
├── config.yml
└── commands/
    ├── check.py
    ├── hunan_collector.py
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
