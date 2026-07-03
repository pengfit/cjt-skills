---
name: qingdao-price
description: "青岛工程造价材料信息采集：从 sjw.qingdao.gov.cn 抓取每月《青岛市建设工程材料价格》PDF，存到 minio 并入库到 ods_material_qingdao_price，含 period_start/period_end/period_days 字段。"
---

# qingdao-price

青岛工程造价材料信息采集 Skill（v0.9, 2026-07-03）。从 `sjw.qingdao.gov.cn`（青岛市住房和城乡建设局）"建材价格信息" 栏目抓取每月发布的《青岛市建设工程材料价格》PDF，上传 MinIO，解析为长表（材料×规格×单位×价格），按月周期增量同步至本地 ES `ods_material_qingdao_price`。

> **v0.9 重构（2026-07-03）**：从「一站式 sync.py」改为 **SyncRunner 抽象基类化**（参考 chongqing v0.9），新增 `period_start / period_end / period_days` 三个字段。已在 2026-07-03 生产跑通 1 次（run_id=`qd_run_20260703_163551`，2026 年 1-5 月共 1167 条）。
>
> **v0.9 决策记录**：
> - chongqing v0.9 试点 SyncRunner 抽象基类化后，qingdao 跟改（参考 chongqing_collector.py 写法）
> - 旧 sync.py 逻辑保留在 `sync_legacy.py`，通过 `--legacy` 切换（逃生通道，不推荐）
> - 三个新字段映射到 `_ODS_BASE_FIELDS`（gov-price-etl v0.5 抽出），mapping 走标准 ODS 模板自动带

## 数据流

```
sjw.qingdao.gov.cn/cxjsj13/cxjs_95/cxjsj_zj5/ (列表，无分页)
       ↓ fetch
列表 (N 期) → 详情页 → PDF 链接
       ↓ download (需 Referer) + upload
MinIO: gov-price-data/qingdao-price/{period}/source.pdf
       ↓ pdfplumber.extract_tables
长表 (材料 × 规格 × 单位 × 含税价/不含税价)
       ↓ bulk_index
ods_material_qingdao_price
       (含 period_start/period_end/period_days)
```

## 快速启动

```bash
cd skills/qingdao-price

./run.sh preview                  # 预览（不写入 ES、不上传 minio）
./run.sh preview --period 2026.5  # 指定周期预览
./run.sh sync                     # 同步最新一期到 ES + minio
./run.sh sync --year 2026         # 同步 2026 年所有未入仓期
./run.sh sync --reset             # 重置进度，从头开始
./run.sh sync --dry-run           # 预览要入仓的 doc 数（不真写）
./run.sh sync --max-units 1       # 只跑前 1 个工作单元（验证用）
./run.sh status                   # 查看同步状态
```

## 数据源

- **列表页**：`https://sjw.qingdao.gov.cn/cxjsj13/cxjs_95/cxjsj_zj5/`
  - 一页内全部列表项，无分页
  - 列表项：`<li trs-attr="chip"><a target="_blank" href="...t{YYYYMMDD}_{ID}.html" title="2026年M月青岛市建设工程材料价格">`
- **详情页**：`http://sjw.qingdao.gov.cn/cxjsj13/cxjs_95/cxjsj_zj5/{YYYYMM}/t{YYYYMMDD}_{ID}.html`
- **PDF 链接**：
  - 详情页正文：`<a href="./P{YYYYMMDD}{ID}.pdf" download="2026年M月青岛市建设工程材料价格.pdf">`
  - 旧路径：`oldsrc="/protect/P{YYYYMMDD-prefixed-path}/P{YYYYMMDD}{ID}.pdf"`
  - **下载必须带 Referer 头**（指向详情页），否则 501 Not Implemented
- **PDF 内部月份**：`YYYY年M月青岛市建设工程材料价格` → 周期 `2026.M月`
- **PDF 结构**：
  - Page 1: 5月主要建材价格行情（文字分析）
  - Page 2: 主要建材价格走势图（图表）
  - Page 3-8: 材料价格表，每页一个分类（一/钢材、二/水泥、三/门窗、四/……）
  - 表头：`序号 | 名称 | 规格型号 | 单位 | 含税价(元)`
  - **全部为含税价** → 程序按 9% 增值税率反推 `price`（不含税价）
  - **单城市**：仅青岛市一个 city 标签

## 数据字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `breed` | text+keyword | 材料名称 |
| `spec` | text+keyword | 规格型号 |
| `unit` | keyword | 单位 |
| `price` | float | 不含税价（按 9% 增值税反推） |
| `tax_price` | float | 含税价（PDF 原始价格） |
| `period` | keyword | 周期（`2026.5月`） |
| `period_start` | date (yyyy-MM-dd) | **v0.9 新增** — 周期第一天（`2026-05-01`） |
| `period_end` | date (yyyy-MM-dd) | **v0.9 新增** — 周期最后一天（`2026-05-31`） |
| `period_days` | integer | **v0.9 新增** — 周期天数（`31`） |
| `province` | keyword | 山东 |
| `city` | keyword | 青岛 |
| `update_date` | date (yyyy-MM-dd) | 发布日期（列表上的 `YYYY-MM-DD`） |
| `create_time` | date | 入库时间 |
| `source_pdf` | keyword | MinIO PDF 路径 |
| `source_url` | keyword | PDF 原始 URL |
| `run_id` | keyword | **v0.9 新增** — 本次采集 run 标识 |

`period_start/period_end/period_days` 由 `compute_period_dates(period)` 推算（`commands/qingdao_collector.py`）。

## 幂等写入

```
_id = MD5(period + breed + spec + unit + price)
```

## 断点续传

本地进度保存至 `.qingdao_sync_progress.json`，记录 `detail_url`、`period`、`publish_date`、`docs_written`、`status`、`run_id`。中断后 `./run.sh sync` 自动从断点恢复。

进度键：`_compute_unit_key(unit) = unit['detail_url']`，与 chongqing 的 `done_<source>_<period>__<item>` 略有差异（qingdao 工作单元是 dict，按 detail_url 区分）。

## 项目结构

```
qingdao-price/
├── run.sh
├── config.yml
├── .qingdao_sync_progress.json    # 本地进度（自动生成）
└── commands/
    ├── sync.py              # 同步入口（默认走 collector，--legacy 走 v0.8）
    ├── qingdao_collector.py # v0.9 默认：SyncRunner 抽象基类化（参考 chongqing_collector）
    ├── sync_legacy.py       # v0.8 旧版（逃生通道，--legacy 调用）
    ├── preview.py           # 预览（不写入）
    ├── status.py            # 进度查看
    ├── test.py              # 连接测试
    └── utils.py             # 配置加载、ES、MinIO、HTTP 工具
```

## v0.8 → v0.9 迁移要点

| 维度 | v0.8（一站式） | v0.9（SyncRunner） |
|------|----------------|--------------------|
| 主流程位置 | `sync.py` 单文件 ~280 行 | `qingdao_collector.py` 类 ~330 行 |
| 进度管理 | 自写 `load_progress` / `save_progress` | 复用 `LocalProgressStore` |
| 中断处理 | 无（Ctrl+C 不保存） | 复用 `SignalHandler`（基类内置） |
| 进度上报 | 每期手写 ES.index | `_on_unit_done` 钩子里统一写 |
| 主循环 | `for item in todo: ...` | `collector.run(reset=..., max_units=...)` |
| 新字段 | 仅业务字段 | `period_start/end/days` 自动计算填充 |

## 依赖

- Python 3
- `requests` / `beautifulsoup4` / `pyyaml`
- `pdfplumber`（PDF 表格抽取）
- `boto3`（MinIO S3 客户端）
- `elasticsearch`（ES 客户端）
- **`gov-price-etl` skill**（部署在 `~/.openclaw/workspace/skills/gov-price-etl`）— 强依赖：
  - `collectors.base.SyncRunner` / `LocalProgressStore` / `SignalHandler`
  - `collectors.get_es_client` / `get_s3_client` / `ensure_bucket` / `upload_to_minio` / `fetch_html` / `download_file`
  - `mappings.build_ods_mapping`（动态 mapping 标准模板）
- Elasticsearch（`http://localhost:59200`）
- MinIO（`http://localhost:9000`，bucket `gov-price-data`）

安装依赖：
```bash
pip3 install requests beautifulsoup4 pyyaml pdfplumber boto3 elasticsearch
```
