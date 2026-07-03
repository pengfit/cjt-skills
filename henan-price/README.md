# henan-price

河南省工程造价材料价格数据采集。

> 📘 详细 Skill 描述见 [SKILL.md](./SKILL.md)
> 🆕 **v0.8（2026-07-03）**：SyncRunner 抽象基类化 + 新增 period_start/period_end/period_days 字段

## 简介

从 [河南省工程造价信息网](http://www.hncost.com) 抓取"材料价格查询"模块每期发布的 PDF 附件，下载、上传 MinIO，解析为长表（材料 × 18 个地市价格），写入 ES `ods_material_henan_price`。

## 快速开始

```bash
cd skills/henan-price

# 1. 测试连通性（ES + MinIO + 源站）
./run.sh test

# 2. 预览 2026 年所有期（不写入）
./run.sh preview --year 2026

# 3. 同步 2026 年所有期
./run.sh sync --year 2026 --all

# 4. 重置本地进度 + 重建 ES 后重跑
./run.sh sync --year 2026 --all --reset

# 5. 查看同步状态
./run.sh status
```

## v0.8 改造要点

### 1. SyncRunner 抽象基类化（参考 chongqing v0.8 试点）
- 抽 `commands/henan_collector.py`：`HenanCollector` 继承 `gov_price_etl.collectors.base.SyncRunner`
- 通用基础设施（SIGINT / 本地进度 / 进度汇总）由基类提供，henan 只保留站点特化逻辑（PDF 解析）
- `commands/sync.py` 改为 CLI 入口：默认走 Collector，--legacy 走 v0.7 `cmd_legacy_sync`（逃生通道）

### 2. 字段扩展：period 窗口（道友要求）
- `period`：业务期号（"2026.3月"，双月合刊取首月）
- **`period_start`**：期首日（"2026-03-01"）
- **`period_end`**：期末日（"2026-04-30"，合刊末日）
- **`period_days`**：期天数（M1 月 + M2 月 = 31 + 30 = 61）

业务标题 `"河南省2026年3-4月建设工程材料价格信息"` → period 窗口解析：

| period | period_start | period_end | period_days | months |
|---|---|---|---|---|
| 2026.1月 | 2026-01-01 | 2026-02-28 | 59 | [1, 2] |
| 2026.3月 | 2026-03-01 | 2026-04-30 | 61 | [3, 4] |

### 3. 标准 mapping 同步
- 之前 henan 自维护 mapping 字符串（v0.6 起委托到 `gov_price_etl.mappings.build_ods_mapping`）
- v0.8 期间扩展了 `build_progress_mapping` 的 `_PROGRESS_BASE_FIELDS`，加 `period_start/end/days` 三个字段（dynamic=strict）

## 目录结构

```
henan-price/
├── SKILL.md                   # Skill 描述（接口契约）
├── README.md                  # 本文件（开发与使用）
├── config.yml                 # ES / MinIO / 源站 / 18 地市配置
├── run.sh                     # 入口脚本
├── .henan_sync_progress.json  # 本地进度（每期 OK/FAILED）
└── commands/
    ├── sync.py                # CLI 入口（默认 Collector，--legacy 走 v0.7 cmd_legacy_sync）
    ├── henan_collector.py     # v0.8 SyncRunner 化默认实现（参考 chongqing_collector.py）
    ├── preview.py             # 预览（不写入 ES / MinIO）
    ├── status.py              # 进度查询（本地 + ES + MinIO）
    ├── test.py                # ES / MinIO / 源站连通性
    ├── check.py               # 增量检测
    └── utils.py               # 配置加载、MinIO 客户端、ES 客户端、HTTP 工具
```

## 数据流

```
hncost.com 列表 4 页（~49 期）
   ↓ fetch
详情页 + PDF 链接
   ↓ download
本地临时 PDF (~4.5MB / 131 页)
   ↓ upload
MinIO: gov-price-data/henan-price/{period}/source.pdf
   ↓ pdfplumber.extract_tables
长表 (材料 × 18 地市价格，~6330 行/期)
   ↓ bulk_index（_id 幂等去重）
ods_material_henan_price (~4870 条/期)
   每个 doc 含 period_start / period_end / period_days
```

## 关键设计

### 跨页续表拼接
PDF 跨页设计：每"材料组" = 1 主表页（前 5 地市）+ 0~1 续表页（后 13 地市）。
`_parse_one_table()` 识别主表/续表，主表填入 (breed, spec, unit) 列表 + 5 地市，续表按行序补全 13 地市。

### 幂等 _id
```python
_id = MD5(period + breed + spec + city)
```
不含 price：同 (breed, spec, city) 在 PDF 中可能跨组出现多次，后写覆盖前写。

### 分类标题行跳过
PDF 中"1 水泥"、"2 砂浆"等分类标题被识别为 `breed=水泥, spec='', unit='', prices=[None, ...]`，通过 `if not breed and not spec and not unit: continue` 跳过。

## SyncRunner 钩子实现（henan_collector.py）

| 钩子 | 行为 |
|---|---|
| `_list_work_units()` | 抓列表 4 页 → 过滤 year/period → 排除本地已 done → 返回 list[dict]（含 period 窗口字段） |
| `_process_one(unit)` | 抓详情 → 下载 PDF → MinIO → pdfplumber 解析 → bulk_index（含 period 窗口字段）→ 返回 (n, status) |
| `_on_unit_done(unit, n, status)` | 写 ES progress（含 period 窗口字段）+ 保存本地进度 + print 完成标记 |
| `_compute_unit_key(unit)` | `unit['detail_url']`（一期 = 一个 detail_url） |

## 配置

`config.yml` 主要字段：
- `es.host` / `es.ods_index` / `es.progress_index`
- `minio.endpoint` / `minio.bucket` / `minio.prefix`
- `site.base_url` / `site.list_path` / `site.list_pages`
- `cities`: 18 个地市列表（识别续表页用）

## 依赖

```
requests
beautifulsoup4
pdfplumber
boto3
elasticsearch
pyyaml
```

**强依赖 `gov-price-etl`**（部署在 `~/.openclaw/workspace/skills/gov-price-etl`）：
- `collectors.base.SyncRunner`（v0.8 抽象基类）
- `collectors.{get_es_client, get_s3_client, fetch_html, download_file, upload_to_minio, ...}`
- `mappings.{build_ods_mapping, build_progress_mapping}`（v0.5/v0.6 集中维护 mapping）

## 调试

```bash
# 直接跑 Python（输出未缓冲）
python3 -u commands/sync.py --year 2026 --all

# 单期 dry-run
python3 -u commands/sync.py --period 2026.3月 --dry-run --legacy

# Collector 路径只跑前 N 个工作单元（验证用）
python3 -u commands/sync.py --year 2026 --max-units 1

# 跳过网络，单测 PDF 解析
python3 -c "
import sys; sys.path.insert(0, 'commands')
from sync import parse_pdf_tables
print(len(parse_pdf_tables('/path/to/source.pdf', [])))
"
```

## 已知限制

- PDF 续表页按行序对齐（pdfplumber 行数有时不准），个别材料的续表价格可能错位
- PDF 中部分地市格空（缺数据）会跳过
- 暂未接入 `gov-price-etl` 的 `CITY_CONFIGS`（dashboard 端需手动注册 `henan`）

## 关联

- 上游：`http://www.hncost.com/jcxx/004001/subpage2.html`
- 下游：政府材料价格 Dashboard（消费 ES 数据）
- 同类：`sichuan-price` / `chongqing-price` / `jinan-price` / `rizhao-price` / `xian-price` / `shaanxi-price` / `xinjiang-price` / `hainan-price`
- SyncRunner 范式：`chongqing-price`（v0.8 试点，2026-07-02 验证）
