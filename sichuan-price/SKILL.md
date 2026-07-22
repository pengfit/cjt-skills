---
name: sichuan-price
description: "四川工程造价材料信息采集,从 `http://202.61.90.35:8032/pubpages/pricelist.aspx` 抓取数据,按分类目录跟踪,同步至 Elasticsearch。覆盖 21 个分类。"
---

# 四川 · 工程造价材料信息采集

> 省份:四川 · 进度模式:`catalogue` · 范围:21 项

## 数据流

```
源站: http://202.61.90.35:8032/pubpages/pricelist.aspx
   ↓ (commands/sync.py)
ods_material_sichuan_price
   ↓ ([gov-price-etl](../../gov-price-etl/) cli/etl.py --city sichuan)
dwd_sichuan_price
   ↓ (cli/sync_dws.py --city sichuan --mode quick)
dws_sichuan_price
   ↓ ([gov-price-normalization](../../gov-price-normalization/) · Normalizer worker)
norm_sichuan_price                          ← Dashboard 默认查 NORM，DWS 作 fallback
```

下游框架:
- ETL 三段式清洗 + attr 治本 L2 封堵 — [gov-price-etl](../../gov-price-etl/)
- NORM 标准化 + attr 治本 L1 净化 — [gov-price-normalization](../../gov-price-normalization/)
- 可视化(默认查 NORM) — [gov-price-dashboard](../../gov-price-dashboard/)

## 快速开始

```bash
cd <skills>/sichuan-price
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
| `preview` | `commands/preview.py` | 预览数据（不写入 ES） |
| `preview` | `commands/preview.py` | --pages N    预览前 N 页 |
| `sync` | `commands/sync.py` | 同步到 ES（有增量检测） |
| `sync` | `commands/sync.py` | --dry-run       预览同步（不写入） |
| `sync` | `commands/sync.py` | --force         强制全量同步（跳过增量检测） |
| `sync` | `commands/sync.py` | --reset         重置进度，重新开始 |
| `sync` | `commands/sync.py` | --period \"2026年03月\"  指定周期 |
| `status` | `commands/status.py` | 查看同步状态 |
| `test` | `commands/test.py` | 测试 ES 连接 |
| `check` | `commands/check.py` | 检查源站是否有新数据 |
| `增量逻辑：按时间周期判断。同步完成后自动更新` | `commands/增量逻辑：按时间周期判断。同步完成后自动更新.py` | last_period。 |
| `定时任务建议：crontab` | `commands/定时任务建议：crontab.py` | 设置 ./run.sh check，有更新时自动 sync |
| `支持翻页：ASP.NET` | `commands/支持翻页：ASP.NET.py` | POST 翻页，rptPager_input |

## sync 关键参数

- `--reset` — 重置进度，重新开始
- `--dry-run` — 预览模式，不写入 ES
- `--force` — 强制全量同步
- `--period` — 指定周期（如 2026年03月），默认自动获取最新）
- `--periods` — 批量周期（逗号分隔，如
- `--year` — 按年份批量抓取（如 2026 → 该年所有 State=1 周期）
- `--max-pages` — 最大页数
- `--no-check` — 跳过增量检测，直接同步

## ES 索引

| 索引 | 说明 |
|------|------|
| `ods_material_sichuan_price` | 原始抓取数据(主数据) |
| `ods_material_sichuan_price_sync_progress` | 同步进度(按 run_id 分组) |
| `dwd_sichuan_price` | ETL 清洗层 |
| `dws_sichuan_price` | 看板查询层 |

## 配置(config.yml)

```yaml
es:
  host: http://localhost:59200
  index: ods_material_sichuan_price
  progress_index: ods_material_sichuan_price_sync_progress
site:
  base_url: http://202.61.90.35:8032/pubpages/pricelist.aspx
  counties/tabs:
  - 成都市
  - 绵阳市
  - 自贡市
  - 攀枝花市
  - 泸州市
  - 德阳市
  - 广元市
  - 遂宁市
  - 内江市
  - 乐山市
  - 资阳市
  - 宜宾市
  - 南充市
  - 达州市
  - 雅安市
  - 阿坝州
  - 甘孜州
  - 凉山州
  - 广安市
  - 巴中市
  - 眉山市
sync:
  last_period: 2026年05月
```

## 项目结构

```
sichuan-price/
├── run.sh
├── config.yml
└── commands/
    ├── check.py
    ├── preview.py
    ├── repair_progress.py
    ├── sichuan_city_mapping.py
    ├── status.py
    ├── sync.py
    ├── test.py
    ├── test_pages.py
    ├── test_types.py
    ├── utils.py
```

## 依赖

- Python 3
- requests / beautifulsoup4 / pyyaml / elasticsearch

## 相关

- <skills>/gov-price-dashboard — 看板(查 DWS 数据)
- <skills>/gov-price-etl — ETL 公共层
