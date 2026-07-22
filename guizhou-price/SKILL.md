---
name: guizhou-price
description: "贵州工程造价材料信息采集,从 `http://www.gzszj.com/Home/Policies/c2a45b5e-fb3e-43c6-a77c-000000000046` 的\"工程造价信息\"子 tab 抓取月刊,按期期刊跟踪,同步至 Elasticsearch。时间方法:2026 年(道友要求,默认仅入库 2026 年期)。"
---

# 贵州 · 工程造价材料信息采集

> 省份:贵州 · 进度模式:`period` · 时间方法:2026 年起 · 12 期/年(月刊)

## 数据流

```
源站: http://www.gzszj.com/Home/Policies/c2a45b5e-fb3e-43c6-a77c-000000000046
   ↑ sub-tab "工程造价信息" guid: ...000000004601
   ↓ (commands/sync.py, POST /Home/GetPoliciesListBy form-encoded AJAX 翻页)
ods_material_guizhou_price
   ↓ ([gov-price-etl](../../gov-price-etl/) cli/etl.py --city guizhou)
dwd_guizhou_price
   ↓ (cli/sync_dws.py --city guizhou --mode quick)
dws_guizhou_price
   ↓ ([gov-price-normalization](../../gov-price-normalization/) · Normalizer worker)
norm_guizhou_price                          ← Dashboard 默认查 NORM，DWS 作 fallback
```

下游框架:
- ETL 三段式清洗 + attr 治本 L2 封堵 — [gov-price-etl](../../gov-price-etl/)
- NORM 标准化 + attr 治本 L1 净化 — [gov-price-normalization](../../gov-price-normalization/)
- 可视化(默认查 NORM) — [gov-price-dashboard](../../gov-price-dashboard/)

## 快速开始

```bash
cd <skills>/guizhou-price
./run.sh preview          # 预览数据(不写 ES / MinIO)
./run.sh sync             # 增量同步(自动断点续传, 默认仅 2026 年)
./run.sh sync --all       # 同步所有未入仓的期(不限年份)
./run.sh sync --legacy    # v0.7 兼容路径(逃生通道)
./run.sh sync --year=2025 # 显式指定年份
./run.sh status           # 查看状态
./run.sh check            # 增量检测(不写入)
./run.sh test             # 测试 ES / MinIO / 源站连通性
```

## 命令清单

| 命令 | 脚本 | 说明 |
|------|------|------|
| `preview` | `commands/preview.py` | 预览数据(下载 PDF 试解析) |
| `sync` | `commands/sync.py` | 同步到 ES + MinIO |
| `status` | `commands/status.py` | 查看 ES / MinIO 状态 |
| `test` | `commands/test.py` | ES + MinIO + 源站连通性 |
| `check` | `commands/check.py` | 增量检测(对比 ES vs 源站最新日期) |

## sync 关键参数

- `--period` — 指定周期(如 `2026.6期`)
- `--year` — 默认 `config.sync.default_year=2026`(道友要求"时间方法 2026 年");传 `0` 表示不限
- `--all` — 同步所有未入仓的期,忽略 `--year` 过滤
- `--reset` — 重置本地进度(ES progress 保留)
- `--dry-run` — 预览,不写入(仅 `--legacy` 路径支持)
- `--latest` — 只同步最新一期(从源站首页第 1 条)
- `--run-id` — 指定 run_id(默认自动生成 `gz_run_YYYYMMDD_HHMMSS`)
- `--legacy` — v0.7 兼容:走原 `cmd_legacy_sync`。默认走 Collector(SyncRunner 化)
- `--max-units` — Collector 路径:只跑前 N 个工作单元(验证用)

## ES 索引

| 索引 | 说明 |
|------|------|
| `ods_material_guizhou_price` | 原始抓取数据(主数据) |
| `ods_material_guizhou_price_sync_progress` | 同步进度(每期一条) |
| `dwd_guizhou_price` | ETL 清洗层 |
| `dws_guizhou_price` | 看板查询层 |

## 周期命名(道友指定)

源站期号格式: `YYYY年第N期`(12 期/年 = 月刊)。

进度模式 `period` 用 `YYYY.N期`(如 `2026.6期`)作为业务标识:

  - `period`:        `2026.6期`
  - `period_start`:  `2026-06-01`(issue N → 月 N 第 1 天)
  - `period_end`:    `2026-06-30`(issue N → 月 N 最后一天)
  - `period_days`:   `30`(当月天数)

## 数据获取细节

不同于 henan 的 HTML 列表页,gzszj.com 是 .NET CMS,列表数据通过 AJAX POST 获取:

- **端点**: `POST /Home/GetPoliciesListBy`
- **Content-Type**: `application/x-www-form-urlencoded; charset=UTF-8`
- **Body**: `guid={sub_tab_guid}&page={N}&pagesize=20`
- **响应**: JSON, `{"Rows":[{ID, Name, EntryDate, PoliciesAttachmentDTOS:[{FileUrl}]}], "Total":N}`

PDF 直链: `base_url + /Upload/File/ + URL-encoded(FileUrl)`(中文文件名需 `urllib.parse.quote(safe='/')`)。

## 配置(config.yml)

```yaml
es:
  host: http://localhost:59200
  ods_index: ods_material_guizhou_price
  progress_index: ods_material_guizhou_price_sync_progress

minio:
  endpoint: http://localhost:9000
  bucket: gov-price-data
  prefix: guizhou-price

site:
  base_url: http://www.gzszj.com
  list_path: /Home/Policies/c2a45b5e-fb3e-43c6-a77c-000000000046
  ajax_path: /Home/GetPoliciesListBy
  sub_tab_guid: c2a45b5e-fb3e-43c6-a77c-000000004601  # 工程造价信息
  page_size: 20

sync:
  default_year: 2026
```

## PDF 解析(best-effort)

贵州 PDF 单期一份省级文件(`city='贵州'`)。当前采用通用 table 提取:

- pdfplumber `extract_tables()` 全表扫
- 表头关键字分类列:材料名称 / 规格型号 / 单位 / 单价(含税价/不含税价/信息价 等)
- 无表头行:启发式 — 最右数字格当 price,其余按顺序填 breed/spec/unit
- 解析失败:仍插 1 条 `parse_status='unparsed'` 的 placeholder(标识已归档)

> 提示:首次跑后看 `commands/preview.py` 输出,若 PDF 版式与默认解析不匹配,需在 `commands/sync.py` 的 `parse_pdf_tables` / `_classify_cols` 调整关键字或行结构。

## 项目结构

```
guizhou-price/
├── run.sh
├── config.yml
├── skill.yml
├── SKILL.md
├── README.md
└── commands/
    ├── check.py
    ├── guizhou_collector.py     # SyncRunner 化(默认)
    ├── preview.py
    ├── status.py
    ├── sync.py                  # 含 --legacy 逃生通道
    ├── test.py
    └── utils.py
```

## 依赖

- Python 3
- requests / beautifulsoup4 / pyyaml / elasticsearch
- pdfplumber
- gov_price_etl (本 workspace 内,公共 ETL 层)

## 相关

- `<skills>/gov-price-dashboard` — 看板(查 DWS 数据)
- `<skills>/gov-price-etl` — ETL 公共层
- `<skills>/henan-price` — 参考模板(同 v0.8 SyncRunner 结构)
