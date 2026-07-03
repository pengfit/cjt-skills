---
name: henan-price
description: "河南工程造价材料信息采集：从 www.hncost.com 抓取全省 18 个地级市材料价格 PDF 表格，存到 minio 并入库到 ods_material_henan_price。"
---

# henan-price

河南工程造价材料信息采集 Skill。从 `www.hncost.com`（河南省工程造价信息网）抓取"材料价格查询"模块每期的 PDF 附件，上传 MinIO，解析为长表（材料×规格×单位×地市×价格），按月周期增量同步至本地 ES，写入 `ods_material_henan_price`。

> **v0.8 改造（2026-07-03）**：按重庆 v0.8 模式抽 SyncRunner 抽象基类化（henan_collector.py），CLI 默认走 Collector 路径，--legacy 走 v0.7。
> 同步 doc 新增 `period_start` / `period_end` / `period_days` 三个字段（从业务标题 "YYYY年M1-M2月" 推算的窗口）。

## 数据流

```
www.hncost.com (列表 4 页) 
       ↓ fetch
列表 (16 期) → 详情页 → PDF 链接
       ↓ download + upload
MinIO: gov-price-data/henan-price/{period}/source.pdf
       ↓ pdfplumber.extract_tables
长表 (材料 × 18 个地市价格)
       ↓ bulk_index
ods_material_henan_price
```

## 快速启动

```bash
cd skills/henan-price

./run.sh preview                  # 预览（不写入 ES、不上传 minio）
./run.sh preview --year 2026      # 仅预览 2026 年
./run.sh sync                     # 同步最新一期到 ES + minio
./run.sh sync --year 2026 --all   # 同步 2026 年所有未入仓的期
./run.sh sync --reset --year 2026 # 重置本地进度 + 重新同步 2026 年
./run.sh status                   # 查看同步状态
./run.sh check                    # 增量检测（页面月份 vs ES 最新）
./run.sh test                     # ES + minio + 源站连通性
```

## v0.8 同步入口（CLI）

```
python3 commands/sync.py [--year YYYY] [--period PERIOD] [--all] [--reset] [--latest] [--run-id ID] [--legacy] [--max-units N]
```

- 默认走 `HenanCollector`（v0.8 SyncRunner 化，commands/henan_collector.py）
- `--legacy` 走 v0.7 `cmd_legacy_sync`（逃生通道，不推荐）
- `--max-units N` 只跑前 N 个工作单元（验证用）

## 数据源

- **列表页**：`http://www.hncost.com/jcxx/004001/subpage2.html` (含分页 1-4)
- **详情页**：`/jcxx/004001/{YYYYMMDD}/{uuid}.html`
- **PDF 附件**：`/BigFileUpLoadStorage/temp/{YYYY-MM-DD}/{uuid}/{filename}.pdf`
- **标题格式**：`河南省YYYY年M1-M2月建设工程材料价格信息`（如"河南省2026年3-4月"，双月合刊）
- **PDF 内部月份**：`YYYY.M月`（如"2026.3月"，业务期 = 首月）
- **页数**：约 131 页（约 60 个"材料组"，每组 = 1 主表页 + 0~1 续表页）

## 18 个地市

郑州、濮阳、周口、许昌、新乡、洛阳、安阳、焦作、平顶山、信阳、漯河、驻马店、南阳、鹤壁、三门峡、济源、开封、商丘

## 数据字段（v0.8）

| 字段 | 说明 | 必填 |
|------|------|------|
| `breed` | 材料名称 | ✓ |
| `spec` | 规格型号 | ✓ |
| `unit` | 单位 | ✓ |
| `price` | 价格（不含税，含税时自动折算） | ✓ |
| `tax_price` | 含税价（仅含税表才有） |  |
| `period` | 周期（PDF 内部月份 `2026.3月`，首月标识） | ✓ |
| **`period_start`** | **期首日**（`YYYY-MM-DD`，如 `2026-03-01`） | ✓ |
| **`period_end`** | **期末日**（`YYYY-MM-DD`，如 `2026-04-30`，合刊末日） | ✓ |
| **`period_days`** | **期天数**（`M1 月天数 + M2 月天数`，如 3-4 月 = 31+30=61） | ✓ |
| `province` | 河南 | ✓ |
| `city` | 地市 | ✓ |
| `update_date` | 发布日期（列表上的 `YYYY-MM-DD`） | ✓ |
| `create_time` | 入库时间 | ✓ |
| `source_pdf` | MinIO 对象 key | ✓ |
| `source_url` | 源站 PDF URL | ✓ |

> period 窗口字段（period_start/end/days）从业务标题 `YYYY年M1-M2月` 推算：
> - period: `YYYY.M月`（首月标识，幂等 _id 用）
> - period_start: M1 月第一天
> - period_end: M2 月最后一天（合刊末日）
> - period_days: M1 月天数 + M2 月天数

## ES 索引

| 索引 | 说明 |
|------|------|
| `ods_material_henan_price` | 材料价格数据 |
| `ods_material_henan_price_sync_progress` | 同步进度记录 |

## 幂等写入

```
_id = MD5(period + breed + spec + city)
```

> 同一 (breed, spec, city) 在 PDF 中可能出现 2 次（主表页前 5 地市 + 续表页后 13 地市），
> 不含 price 的 _id 让后写覆盖前写，去重后约 4870 条 / 期（原始解析 ~6330 行）。
> PDF 中部分地市无数据的格子会被跳过（如商丘某期某材料）。

## 项目结构

```
henan-price/
├── SKILL.md
├── config.yml
├── run.sh
├── .henan_sync_progress.json
└── commands/
    ├── sync.py             # CLI 入口（默认 Collector，--legacy 走 v0.7 cmd_legacy_sync）
    ├── henan_collector.py  # v0.8 SyncRunner 化默认实现（参考 chongqing_collector.py）
    ├── preview.py          # 预览（不写入）
    ├── check.py            # 增量检测（页面月份 vs ES 最新）
    ├── status.py           # 进度查询
    ├── test.py             # ES + minio + 源站连通性
    └── utils.py            # 配置加载、minio 客户端、ES 客户端
```

## 依赖

- Python 3
- requests / beautifulsoup4 / pyyaml
- pdfplumber
- boto3 (MinIO S3 兼容)
- elasticsearch
- **gov-price-etl skill**（部署在 `~/.openclaw/workspace/skills/gov-price-etl`）— 强依赖：
  - `collectors.base.SyncRunner`（v0.8 抽象基类）
  - `collectors.{get_es_client, get_s3_client, fetch_html, download_file, upload_to_minio, ...}`
  - `mappings.{build_ods_mapping, build_progress_mapping}`（v0.5/v0.6 集中维护 mapping）
  - 部署缺失时 `utils.py` 顶部会 hard raise
