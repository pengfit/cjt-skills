---
name: henan-price
description: "河南工程造价材料信息采集,从 `http://www.hncost.com/jcxx/004001/subpage2.html` 抓取数据,按期期刊跟踪,同步至 Elasticsearch。覆盖 18 个期数。"
---

# 河南 · 工程造价材料信息采集

> 省份:河南 · 进度模式:`period` · 范围(18): 郑州, 濮阳, 周口, 许昌, 新乡, 洛阳, 安阳, 焦作, 平顶山, 信阳, 漯河, 驻马店, 南阳, 鹤壁, 三门峡, 济源, 开封, 商丘

## 数据流

```
源站: http://www.hncost.com/jcxx/004001/subpage2.html
   ↓ (commands/sync.py)
ods_material_henan_price
   ↓ (<skills>/gov-price-etl cli/etl.py --city henan)
dwd_henan_price
   ↓ (cli/sync_dws.py --city henan --mode quick)
dws_henan_price
```

## 快速开始

```bash
cd <skills>/henan-price
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

- `--period` — 指定周期（如 2026.3月）
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
| `ods_material_henan_price` | 原始抓取数据(主数据) |
| `ods_material_henan_price_sync_progress` | 同步进度(按 run_id 分组) |
| `dwd_henan_price` | ETL 清洗层 |
| `dws_henan_price` | 看板查询层 |

## 配置(config.yml)

```yaml
es:
  host: http://localhost:59200
  index: ods_material_henan_price
  progress_index: ods_material_henan_price_sync_progress
site:
  base_url: http://www.hncost.com/jcxx/004001/subpage2.html
  counties/tabs:
  - 郑州
  - 濮阳
  - 周口
  - 许昌
  - 新乡
  - 洛阳
  - 安阳
  - 焦作
  - 平顶山
  - 信阳
  - 漯河
  - 驻马店
  - 南阳
  - 鹤壁
  - 三门峡
  - 济源
  - 开封
  - 商丘
sync:
  last_period: 
  last_publish_date: 
```

## 项目结构

```
henan-price/
├── run.sh
├── config.yml
└── commands/
    ├── check.py
    ├── henan_collector.py
    ├── preview.py
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
