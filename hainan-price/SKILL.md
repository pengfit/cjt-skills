---
name: hainan-price
description: "海南工程造价材料信息采集,从 `https://zjt.hainan.gov.cn/szjt/dejgxx/dezlist.shtml` 抓取数据,按期期刊跟踪,同步至 Elasticsearch。覆盖 6 个期数。"
---

# 海南 · 工程造价材料信息采集

> 省份:海南 · 进度模式:`period` · 范围(6): 海南, 北部, 南部, 西部, 东部, 中部

## v0.8.4 (2026-08-03) — 5/6 月不使用 OCR 解析

道友要求：**海南 5月/6月期刊不调用 OCR 解析（rapidocr）**，直接跳过不入库。

**改动**（`commands/hainan_collector.py`）：
- `_process_one()` 在 `_is_image_pdf` 之后新增 period 判定：`month ∈ {5, 6}` → 返回 `(0, "skipped_ocr_disabled")`
- PDF 仍上传 minio 留底（步骤 3 在前），后续人工或更强 OCR 可补
- `import re` 已加（period regex 解析）
- 与 `skipped_image_pdf` 平行：纯扫描型（< 10 字符/页）走 `skipped_image_pdf`，5/6 月图片版式（~387 字符/页）走 `skipped_ocr_disabled`

**触发顺序**：minio 上传 → `_is_image_pdf`（纯扫描）→ period 判定（5/6 月）→ pdfplumber 解析

**与 v0.8.3 OCR fallback 关系**：parser.py 里的 `_parse_pdf_with_ocr` 暂保留，未删除。后续 7月+ 如果又回到图片版式，period 判定不命中（month ∉ {5, 6}），`_is_image_heavy_pdf` 仍会走 OCR。如未来所有图片版式都禁 OCR，可删除整个 OCR 分支。

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
