---
name: "heze-price"
description: "菏泽工程造价材料价格采集：hzszjj.heze.gov.cn《工程造价信息》期刊，API 列表+HTML 抓 PDF，ods_material_heze_price。"
---

# heze-price

菏泽市住房和城乡建设局工程造价材料信息采集。从 `hzszjj.heze.gov.cn` 抓取《工程造价信息》期刊，PDF 解析为长表，按月周期增量同步至 ES，写入 `ods_material_heze_price`。

> **v0.8 改造（2026-07-03）**：按重庆 v0.8 模式抽 SyncRunner 抽象基类化（heze_collector.py），CLI 默认走 Collector 路径，`--legacy` 走 v0.7。
> doc / progress 新增 `period_start` / `period_end` / `period_days` 三个字段（业务期是单月自然月，按当月第 1 天 / 最后 1 天 / 总天数推算）。

## 数据流

```
hzszjj.heze.gov.cn (列表 API)
       ↓ POST /els-service/article/{page}/{size}
列表 (每期: xxid, subject, fwdate) → 详情页 HTML
       ↓ download
详情页: /{dwid}/{xxid}.html  →  提取 <a class="media" href="/upload-service/.../WY{fileid}.pdf">
       ↓ download + upload
MinIO: gov-price-data/heze-price/{period}/source.pdf
       ↓ pdfplumber.extract_tables
长表 (材料 × N 个地市/规格价格)
       ↓ bulk_index
ods_material_heze_price
```

## API 端点

- **列表**：`POST http://hzszjj.heze.gov.cn/els-service/article/{page}/{size}`
  - Body: `{"dw":["2c908088819842f701819a1a962f0005"], "catas":["1584708004996059136"], "fwzt":"3", "order":"fwdate", "type":[1]}`
  - dwid: 站点标识（菏泽住建局 = 2c908088819842f701819a1a962f0005）
  - catas: 栏目 ID（"材料价格" = 1584708004996059136）
  - 响应: `data.contents[i].{xxid, subject, fwdate}`
- **详情页**：`GET http://hzszjj.heze.gov.cn/{dwid}/{xxid}.html`
  - 提取: `<a class="media" href="/upload-service/.../WY{fileid}.pdf">` 或 `<div class="pdf-box"><a ...>`
  - PDF URL: `http://hzszjj.heze.gov.cn/upload-service/{dq}/{dwid}/WY{fileid}.pdf`
- **PDF**：直接下载上面提取的 URL

## 快速启动

```bash
cd skills/heze-price

# v0.8 默认走 HezeCollector（SyncRunner 抽象基类化）
./run.sh sync --year 2026          # 同步 2026 年所有未入仓的期
./run.sh sync --year 2026 --latest # 只同步最新一期
./run.sh sync --period 2026.1期    # 指定单期
./run.sh sync --reset --year 2026  # 重置本地进度 + 重新同步 2026 年

# v0.7 兼容路径
./run.sh sync --legacy --year 2026
./run.sh sync --legacy --period 2026.1期 --dry-run

# 其他命令
./run.sh preview                  # 预览（不写入 ES、不上传 minio）
./run.sh preview --period 2026.1  # 指定周期预览
./run.sh status                   # 查看同步状态
./run.sh check                    # 增量检测（页面月份 vs ES 最新）
./run.sh test                     # ES + minio + 源站连通性
```

## 数据源

- **API 基础**：`http://hzszjj.heze.gov.cn/els-service/article/{page}/{size}`
- **栏目 ID**：`1584708004996059136`（工程造价信息/材料价格）
- **subsite**：`2c908088819842f701819a1a962f0005`
- **标题格式**：《工程造价信息》YYYY 年第 N 期
- **发布日期**：列表 `fwdate` 字段

## 数据字段

| 字段 | 说明 |
|------|------|
| `breed` | 材料名称 |
| `spec` | 规格型号 |
| `unit` | 单位 |
| `price` | 价格 |
| `period` | 周期（`2026.1期`，首月标识） |
| **`period_start`** | **业务期窗口起始日**（如 `2026-01-01`，v0.8 新增） |
| **`period_end`** | **业务期窗口结束日**（如 `2026-01-31`，v0.8 新增） |
| **`period_days`** | **业务期总天数**（如 `31`，v0.8 新增） |
| `province` | 山东 |
| `city` | 菏泽 |
| `update_date` | 发布日期（`fwdate`） |
| `create_time` | 入库时间 |
| `source_pdf` | MinIO 对象 key |

## ES 索引

| 索引 | 说明 |
|------|------|
| `ods_material_heze_price` | 材料价格数据 |
| `ods_material_heze_price_sync_progress` | 同步进度记录 |

## 幂等写入

```
_id = MD5(period + breed + spec + city)
```

## 项目结构

```
heze-price/
├── SKILL.md
├── config.yml
├── run.sh
├── skill.yml                    # dashboard registry（v0.8 新增）
├── .heze_sync_progress.json
└── commands/
    ├── sync.py                  # v0.8 CLI 入口：默认走 Collector，--legacy 走 v0.7
    ├── heze_collector.py        # v0.8 默认路径：HezeCollector(SyncRunner)
    ├── preview.py               # 预览（不写入）
    ├── status.py                # 进度查询
    ├── check.py                 # 增量检测（页面月份 vs ES 最新）
    └── utils.py                 # 配置加载 + 委托到 gov_price_etl.collectors
```

## 依赖

- Python 3
- requests / beautifulsoup4 / pyyaml
- pdfplumber
- boto3 (MinIO S3 兼容)
- elasticsearch
- **gov-price-etl skill**（部署在 `~/.openclaw/workspace/skills/gov-price-etl`）—— 强依赖：
  - `collectors.base.SyncRunner` / `LocalProgressStore`
  - `mappings.build_ods_mapping` / `build_progress_mapping`（v0.8 走新 mapping）
  - `collectors.fetch_html` / `download_file` / `upload_to_minio` / `get_es_client` / `get_s3_client`
