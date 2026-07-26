---
name: huhehaote-price
description: "呼和浩特工程造价材料信息采集,从 `http://zfcxjsj.huhhot.gov.cn/bsfw_91/xzzx/zjxx/index.html` 抓取数据,按期期刊跟踪,同步至 Elasticsearch。覆盖 6 个期数。"
---

# 呼和浩特 · 工程造价材料信息采集

> 省份:内蒙古 · 进度模式:`period` · 范围(6): 呼和浩特, 土默特左旗, 托克托县, 和林格尔县, 武川县, 清水河县

## 数据流

```
源站: http://zfcxjsj.huhhot.gov.cn/bsfw_91/xzzx/zjxx/index.html
   ↓ (commands/sync.py)
ods_material_huhehaote_price
   ↓ ([gov-price-etl](../../gov-price-etl/) cli/etl.py --city huhehaote)
dwd_huhehaote_price
   ↓ (cli/sync_dws.py --city huhehaote --mode quick)
dws_huhehaote_price
   ↓ ([gov-price-normalization](../../gov-price-normalization/) · Normalizer worker)
norm_huhehaote_price                          ← Dashboard 默认查 NORM，DWS 作 fallback
```

下游框架:
- ETL 三段式清洗 + attr 治本 L2 封堵 — [gov-price-etl](../../gov-price-etl/)
- NORM 标准化 + attr 治本 L1 净化 — [gov-price-normalization](../../gov-price-normalization/)
- 可视化(默认查 NORM) — [gov-price-dashboard](../../gov-price-dashboard/)

## 快速开始

```bash
cd <skills>/huhehaote-price
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

- `--period` — 指定周期（如
- `--year` — _无说明_
- `--exclude-period` — 排除指定周期
- `--all` — 同步所有未入仓的期
- `--reset` — 重置进度
- `--dry-run` — 预览，不写入（仅 legacy 支持）
- `--latest` — 只同步最新一期
- `--run-id` — 指定 run_id（默认自动生成）
- `--legacy` — v0.x 兼容：走原 main 流程。默认走 Collector（推荐）。
- `--max-units` — Collector 路径：只跑前 N 个工作单元（验证用）

## ES 索引

| 索引 | 说明 |
|------|------|
| `ods_material_huhehaote_price` | 原始抓取数据(主数据) |
| `ods_material_huhehaote_price_sync_progress` | 同步进度(按 run_id 分组) |
| `dwd_huhehaote_price` | ETL 清洗层 |
| `dws_huhehaote_price` | 看板查询层 |

## 配置(config.yml)

```yaml
es:
  host: http://localhost:59200
  index: ods_material_huhehaote_price
  progress_index: ods_material_huhehaote_price_sync_progress
site:
  base_url: http://zfcxjsj.huhhot.gov.cn/bsfw_91/xzzx/zjxx/index.html
  counties/tabs:
  - 呼和浩特
  - 土默特左旗
  - 托克托县
  - 和林格尔县
  - 武川县
  - 清水河县
sync:
  last_period: 
  last_publish_date: 
```

## 项目结构

```
huhehaote-price/
├── run.sh
├── config.yml
└── commands/
    ├── check.py
    ├── huhehaote_collector.py
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

## sync-gczj（建设工程造价信息 双月刊增量流，v0.1, 2026-07-26）

源站 8 期里 6 期是「建设工程造价信息」双月刊主刊，2 期是「信息价1期」等散刊。
原 sync 用 `journal_keyword="信息价"` 一次性抓所有，但只能命中 1 期散刊。
新 `sync-gczj` 专门抓建设工程造价信息系列，独立 progress 文件，独立 run。

```bash
cd <skills>/huhehaote-price
./run.sh sync-gczj                  # 增量同步（默认，跳过已 done 的期）
./run.sh sync-gczj --reset           # 重置进度，重抓全量
./run.sh sync-gczj --dry-run         # 只看不写
./run.sh sync-gczj --latest          # 只同步最新一期
```

复用 sync.py 的 fetch/parse 工具（parse_list_page / fetch_all_periods / fetch_detail_pdf / parse_pdf）。
源站过滤器：标题含「建设工程造价信息」且不含「信息价」散刊关键字。

## smart_split_breed_spec（v0.9, 2026-07-26）

源 PDF 表格里很多「核心名 + 规格」是一次连写的（如「钢筋HPB300(高线)Φ6」），
原 spec 列为空，ETL 会跳过（v0.12+ 源头杜绝设计）。需要提前拆开。

utils.py::smart_split_breed_spec(breed, spec) 优先级：
  1. 空格拆分
  2. 通用正则抽规格（Φ/φ/DN/De/Mpa/mm/m³/t/×mm）
  3. 领域特例：玻璃厚度（5+12A+5mm）、混凝土标号+石料（C30 碎石）

下游用法：
- sync.py collector 路径：自动调用
- sync_gczj_zjxx.py：自动调用
- 直接 API：`from utils import apply_smart_split; apply_smart_split(doc)`

## period_rules 补登（v0.2, 2026-07-26）

源站 bimonthly 但 period_rules 漏登记 guizhou/shanxi，导致 ETL 第一轮 报 UnknownCityError。
补登两条：
- guizhou: bimonthly, anchor_month [2,4,6,8,10,12]
- shanxi: bimonthly, anchor_month [1,3,5,7,9,11]
