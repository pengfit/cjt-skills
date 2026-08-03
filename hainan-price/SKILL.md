---
name: hainan-price
description: "海南工程造价材料信息采集,从 `https://zjt.hainan.gov.cn/szjt/dejgxx/dezlist.shtml` 抓取数据,按期期刊跟踪,同步至 Elasticsearch。覆盖 6 个期数。"
---

# 海南 · 工程造价材料信息采集

> 省份:海南 · 进度模式:`period` · 范围(6): 海南, 北部, 南部, 西部, 东部, 中部

## v0.8.6 (2026-08-03) — 撤回 v0.8.5，5/6 月回 OCR 路径

**v0.8.5 决策错误，撤回**。v0.8.5 让 5/6 月跳过 OCR 走 pdfplumber text，结果只抽到 139 行污染（编制说明/目录页的 price 单字段），而 ES 已有 6月 1154 条真数据（OCR 之前入库的热轧带肋钢筋等真规格真价格）。如果按 v0.8.5 继续 sync，139 行污染会按 `_doc_id` 哈希**覆盖掉 6月 1154 条真数据**。

**改回**（`commands/parser.py` + `commands/hainan_collector.py`）：
- `parse_pdf(pdf_path)` 撤掉 period 参数，回 v0.8.3 签名
- OCR fallback 逻辑恢复：`_is_image_heavy_pdf` 触发 → 无条件走 `_parse_pdf_with_ocr (rapidocr)`
- collect 调用方回 `rows = _h.parse_pdf(local_pdf)`，不再传 period
- v0.8.4 的 `skipped_ocr_disabled` 跳过逻辑也保持废弃（v0.8.5 撤了它，本次不恢复）

**验证**：
- ES 6月 1154 条真数据保留（未删、未覆盖）
- 后续 sync 5/6 月仍走 OCR，能持续补/刷真数据
- 5月 ES 当前 0 条，靠 OCR 补（v0.8.3 OCR 路径已就位）

**经验教训**：
- 改 sync 路径前**必须先查 ES 真实状态**（不是只看 dry-run stdout）
- v0.8.5 是基于"139 行都是污染"假设，忽略了 OCR 已经成功入库的事实
- 任何覆盖式同步（_doc_id upsert）前先确认旧数据是垃圾，否则会丢真数据

## v0.8.4 (2026-08-03) — 5/6 月不使用 OCR 解析（已废）

**已被 v0.8.5 撤掉**。v0.8.4 加了 `skipped_ocr_disabled` 让 5/6 月跳过入库（不解析），v0.8.5 让 5/6 月改走 pdfplumber text 路径（解析但 0 行），v0.8.6 把这两个都撤了，5/6 月回 OCR 路径。

本节保留作变更历史。

## 数据流

```
源站: https://zjt.hainan.gov.cn/szjt/dejgxx/dezlist.shtml
   ↓ (commands/sync.py)
ods_material_hainan_price
   ↓ ([gov-price-etl](../../gov-price-etl/) cli/etl.py --city hainan)
dwd_hainan_price
   ↓ (cli/sync_dws.py --city hainan --mode quick)
dws_hainan_price
   ↓ ([gov-price-normalization](../../gov-price-normalization/) · Normalizer worker)
norm_hainan_price                          ← Dashboard 默认查 NORM，DWS 作 fallback
```

下游框架:
- ETL 三段式清洗 + attr 治本 L2 封堵 — [gov-price-etl](../../gov-price-etl/)
- NORM 标准化 + attr 治本 L1 净化 — [gov-price-normalization](../../gov-price-normalization/)
- 可视化(默认查 NORM) — [gov-price-dashboard](../../gov-price-dashboard/)

## 快速开始

```bash
cd <skills>/hainan-price
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

- `--period` — 指定周期（substring 匹配 title）
- `--year` — 只入库指定年份的期（默认 0=不限制）
- `--exclude-period` — 排除指定周期（substring 匹配）
- `--all` — 同步所有未入仓的期
- `--latest` — 只同步最新一期
- `--reset` — 重置本地进度，重新开始
- `--dry-run` — 预览，不写入 ES/minio（解析 PDF 仍跑）
- `--max-units` — Collector 路径：只跑前 N 个工作单元（验证用）

## ES 索引

| 索引 | 说明 |
|------|------|
| `ods_material_hainan_price` | 原始抓取数据(主数据) |
| `ods_material_hainan_price_sync_progress` | 同步进度(按 run_id 分组) |
| `dwd_hainan_price` | ETL 清洗层 |
| `dws_hainan_price` | 看板查询层 |

## 配置(config.yml)

```yaml
es:
  host: http://localhost:59200
  index: ods_material_hainan_price
  progress_index: ods_material_hainan_price_sync_progress
site:
  base_url: https://zjt.hainan.gov.cn/szjt/dejgxx/dezlist.shtml
  counties/tabs:
  - 海南
  - 北部
  - 南部
  - 西部
  - 东部
  - 中部
sync:
  last_period: 
  last_publish_date: 
```

## 项目结构

```
hainan-price/
├── run.sh
├── config.yml
└── commands/
    ├── check.py
    ├── hainan_collector.py
    ├── parser.py
    ├── preview.py
    ├── resync_from_minio.py
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
