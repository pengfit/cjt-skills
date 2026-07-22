---
name: chongqing-price
description: "重庆工程造价材料信息采集,从 `http://www.cqsgczjxx.org/Pages/CQZJW/priceInformation.aspx` 抓取数据,按区县跟踪,同步至 Elasticsearch。覆盖 35 个区县。"
---

# 重庆 · 工程造价材料信息采集

> 省份:重庆 · 进度模式:`county` · 范围:35 项

## 数据流

```
源站: http://www.cqsgczjxx.org/Pages/CQZJW/priceInformation.aspx
   ↓ (commands/sync.py)
ods_material_chongqing_price
   ↓ ([gov-price-etl](../../gov-price-etl/) cli/etl.py --city chongqing)
dwd_chongqing_price
   ↓ (cli/sync_dws.py --city chongqing --mode quick)
dws_chongqing_price
   ↓ ([gov-price-normalization](../../gov-price-normalization/) · Normalizer worker)
norm_chongqing_price                          ← Dashboard 默认查 NORM，DWS 作 fallback
```

下游框架:
- ETL 三段式清洗 + attr 治本 L2 封堵 — [gov-price-etl](../../gov-price-etl/)
- NORM 标准化 + attr 治本 L1 净化 — [gov-price-normalization](../../gov-price-normalization/)
- 可视化(默认查 NORM) — [gov-price-dashboard](../../gov-price-dashboard/)

## 快速开始

```bash
cd <skills>/chongqing-price
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

- `--reset` — 重置进度，重新开始
- `--period` — 目标周期（兼容旧参数，等价 --periods 单值）
- `--periods` — 多周期，逗号分隔，如
- `--run-id` — 指定 run_id
- `--tab-id` — 浏览器标签页 ID（必填）
- `--source` — 数据来源: district / mortar / citywide / all
- `--legacy` — v3 兼容：走原 cmd_sync（旧生产路径）。**默认走 Collector**。仅在 Collector 异常时备用。
- `--max-units` — Collector 路径：只跑前 N 个工作单元（验证用），不传则跑全部

## ES 索引

| 索引 | 说明 |
|------|------|
| `ods_material_chongqing_price` | 原始抓取数据(主数据) |
| `material_chongqing_price_sync_progress` | 同步进度(按 run_id 分组) |
| `dwd_chongqing_price` | ETL 清洗层 |
| `dws_chongqing_price` | 看板查询层 |

## 配置(config.yml)

```yaml
es:
  host: http://localhost:59200
  index: ods_material_chongqing_price
  progress_index: material_chongqing_price_sync_progress
site:
  base_url: http://www.cqsgczjxx.org/Pages/CQZJW/priceInformation.aspx
  counties/tabs:
  - 主城区
  - 万州区
  - 涪陵区
  - 黔江区
  - 长寿区
  - 江津区
  - 合川区
  - 永川区
  - 南川区
  - 梁平区
  - 城口县
  - 丰都县
  - 垫江县
  - 忠县
  - 开州区
  - 云阳县
  - 奉节县
  - 巫山县
  - 巫溪县
  - 石柱县
  - 秀山县
  - 酉阳县
  - 大足区
  - 綦江区
  - 万盛经开区
  - 双桥经开区
  - 铜梁区
  - 璧山区
  - 彭水县1
  - 彭水县2
  - 彭水县3
  - 荣昌区1
  - 荣昌区2
  - 潼南区
  - 武隆区
sync:
  last_period: 2026
```

## 项目结构

```
chongqing-price/
├── run.sh
├── config.yml
└── commands/
    ├── check.py
    ├── chongqing_collector.py
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
