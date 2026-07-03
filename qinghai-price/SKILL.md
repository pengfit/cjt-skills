---
name: "qinghai-price"
description: "青海建设工程材料价格采集：zjt.qinghai.gov.cn《青海建设工程市场价格信息》期刊，HTML 列表抓 PDF，按期刊期数入库到 ods_material_qinghai_price，含 period_start/period_end/period_days 字段。"
---

# qinghai-price

青海省住房和城乡建设厅"造价信息"栏目《青海建设工程市场价格信息》期刊采集。从 `zjt.qinghai.gov.cn/html/132/List.html` 抓取列表（双月合刊），下载 PDF，上传 MinIO，pdfplumber 解析为长表，按期刊期数同步至 ES，写入 `ods_material_qinghai_price`。

> 🆕 **v0.8（2026-07-03）**：SyncRunner 抽象基类化 + 新增 `period_start/period_end/period_days` 字段（道友要求）
> **当前数据范围**：2026 年共 3 期：
> - `2026.第1期`（2026年第1—2期，2026-02-28 发布）：3985 条
> - `2026.第2期`（2026年第3—4期，2026-04-29 发布）：3992 条
> - `2026.第3期`（2026年第5、6期，2026-07-02 发布）：3916 条
> 列表里还含 2023-2025 各期，按需扩展。**只关注《青海建设工程市场价格信息》**，跳过《青海工程造价管理信息》等其他期刊。

## 数据流

```
zjt.qinghai.gov.cn/html/132/List.html (列表 HTML)
   ↓ + List-1.html / List-2.html / List-3.html（4 页分页）
列表 (每期: title, publish_date, pdf_url 直接挂在 <a href=…pdf>)
   ↓ journal_keyword 过滤
   ↓ download（v0.8.1 加 3 次重试，大文件易断流）
PDF (268 页, 双月合刊, ~95-262 MB)
   ↓ upload
MinIO: gov-price-data/qinghai-price/{period}/{basename}.pdf
   ↓ pdfplumber.extract_tables
长表 (5/6/7-10 列混合)
   ↓ bulk_index（含 period_start/end/days）
ods_material_qinghai_price
```

## PDF 结构

- 双月合刊：每期刊登 2 个月材料价格，标题如 `2026年第1—2期《青海建设工程市场价格信息》`
- 2026 年新格式：第 5、6 期用顿号 `、`（v0.8 兼容）
- 表头多种：5 列基础 / 6 列双价（含税+除税）/ 7-10 列扩展（含牌号/直径/强度）
- 大量数据是"厂商名录 + 部分产品报价"格式（含联系人、地址、含税价）
- 价格：5 列默认含税，6 列有除税+含税双价
- 增值税率：13%（建设工程材料）

## 字段映射

| 字段 | 来源 |
|---|---|
| `period` | title 解析：`2026年第1—2期` → `2026.第1期`（业务期号 = (N1-1)//2 + 1）|
| **`period_start`** | **v0.8 新增**：双月合刊窗口首日（`2026-01-01`）|
| **`period_end`** | **v0.8 新增**：双月合刊窗口末日（`2026-02-28`）|
| **`period_days`** | **v0.8 新增**：窗口天数（`(end - start).days + 1`）|
| `section` | PDF 页眉识别的章节（一级类目）|
| `breed` | 表格第 2 列：材料/产品名称 |
| `spec` | 第 3 列：规格型号（含税表）或 第 3-倒数第 3 列拼接（多列表）|
| `unit` | 倒数第 2 列（多列表）/ 第 4 列（5/6 列表）|
| `price` | 除税价（5 列表反推 / 6 列表直接取）|
| `tax_price` | 含税价（5 列直接取 / 6 列直接取 / 多列末列反推）|
| `price_kind` | `含税` / `双价` |
| `category` | section 第一段（"混凝土"等）|

## period 窗口推算（v0.8 新增）

青海"建设工程市场价格信息"为**双月合刊**：

| 期刊标题 | 业务期号 | 月份范围 | period_start | period_end | period_days |
|---|---|---|---|---|---|
| `2026年第1—2期` | 2026.第1期 | 1-2 月 | 2026-01-01 | 2026-02-28 | 59 |
| `2026年第3—4期` | 2026.第2期 | 3-4 月 | 2026-03-01 | 2026-04-30 | 61 |
| `2026年第5、6期` | 2026.第3期 | 5-6 月 | 2026-05-01 | 2026-06-30 | 61 |
| `2026年第7—8期` | 2026.第4期 | 7-8 月 | 2026-07-01 | 2026-08-31 | 62 |
| `2026年第9—10期` | 2026.第5期 | 9-10 月 | 2026-09-01 | 2026-10-31 | 61 |
| `2026年第11—12期` | 2026.第6期 | 11-12 月 | 2026-11-01 | 2026-12-31 | 61 |

解析规则（`qinghai_collector.parse_period_window`）：
1. 从 title 抽 `(YYYY)年第(N1[—、,])N2期`（兼容破折号 `—` / 顿号 `、` / 半角连字符 `-` / 半角逗号 `,`）
2. 业务期号 = (N1 - 1) // 2 + 1（1-2 月→1, 3-4 月→2, 5-6 月→3, ...）
3. period_start = N1 月 1 日
4. period_end = N2 月末日（calendar.monthrange 推算）
5. period_days = (period_end - period_start).days + 1
6. 兜底：返回空窗口（period_start/end/days 为空）

## 快速启动

```bash
cd skills/qinghai-price

# v0.8 默认走 Collector（SyncRunner 抽象基类）
./run.sh sync --year 2026 --all               # 同步 2026 年所有期
./run.sh sync --year 2026 --latest            # 只同步最新一期
./run.sh sync --year 2026 --max-units 1       # Collector 路径：只跑前 N 个工作单元（验证用）

# --legacy 走原 v0.x main 流程（逃生通道）
./run.sh sync --year 2026 --all --legacy      # 走原 v0.x 流程（含 v0.8 字段扩展）

# 预览（不写入 ES / 不上传 MinIO）
./run.sh preview --year 2026                  # 预览 2026 年所有期
./run.sh preview --latest                     # 预览最新一期

# 查看进度 / 检测增量
./run.sh status                               # 查看本地 + ES + MinIO 进度
./run.sh check                                # 增量检测（dashboard chip 复用）
```

## v0.8 改造要点

### 1. SyncRunner 抽象基类化（参考 chongqing v0.8 试点 + henan v0.8 + huhehaote v0.8）
- 抽 `commands/qinghai_collector.py`：`QinghaiCollector` 继承 `gov_price_etl.collectors.base.SyncRunner`
- 通用基础设施（SIGINT / 本地进度 / 进度汇总）由基类提供，青海只保留站点特化逻辑（PDF 解析）
- `commands/sync.py` 改为 CLI 入口：默认走 Collector，--legacy 走 v0.x `cmd_legacy_sync`（逃生通道）

### 2. 字段扩展：period 窗口（道友要求）
- `period`：业务期号（"2026.第1期"）
- **`period_start`**：期首日（"2026-01-01"）
- **`period_end`**：期末日（"2026-02-28"）
- **`period_days`**：期天数（59 天 = 1 月 + 2 月）

### 3. 标准 mapping 同步
- v0.8 之前本地手写 mapping 字符串（仅基础字段）
- v0.8 委托到 `gov_price_etl.mappings.build_ods_mapping` / `build_progress_mapping`
- 自动含 `period_start / period_end / period_days / city` 等 36+ 字段
- 城市特化字段：section（text+keyword）、price_kind（keyword）

### 4. 大文件下载重试（v0.8.1 增量）
- 青海政府站 PDF 95-275 MB，单次下载常因 IncompleteRead 失败
- 在 collector 和 legacy 路径都包了 3 次重试 + 2/4/6s 退避
- 重试全失败才报 error

## Dashboard 注册

为了让 `gov-price-dashboard` 自动发现本 skill，根目录需要 `skill.yml`（小写）：

```yaml
key: qinghai
label: 青海
province: 青海
ods_index: ods_material_qinghai_price
dwd_index: dwd_qinghai_price
dws_index: dws_qinghai_price
progress_index: ods_material_qinghai_price_sync_progress
progress_mode: period
expand_label: "▾ 期数详情"
config_path: config.yml
cities:
  - 青海
```

dashboard 扫描 `~/.openclaw/workspace/skills/*/skill.yml` 自动注册。修改后调用 `POST /api/skill-registry/reload` 触发重扫 + 热更新 ALL_INDICES。

## 依赖

- Python 3
- requests / beautifulsoup4 / pyyaml
- pdfplumber
- boto3 (MinIO S3 兼容)
- elasticsearch

**强依赖 `gov-price-etl`**（部署在 `~/.openclaw/workspace/skills/gov-price-etl`）：
- `collectors.base.SyncRunner`（v0.8 抽象基类）
- `collectors.{get_es_client, get_s3_client, fetch_html, download_file, upload_to_minio, ...}`
- `mappings.{build_ods_mapping, build_progress_mapping}`（v0.5/v0.6 集中维护 mapping）

## 已知限制

- **section 字段含书名号《》**：因为 PDF 页眉偶尔带标题符号，dashboard 拼接会显得冗长
- **厂商地址未归一化 city**：所有数据 city="青海"，address 在 PDF 但未抽到结构化字段
- **多列表抽取简化**：7-10 列表只取末列作价格，其他列拼到 spec，复杂表头（型号/规格/直径多列）会丢信息
- **未过滤"备注"行**：部分 PDF 行包含大段说明文字（如"含税，税率13%..."），会进 breed/spec 字段（如需可加 skip 规则）
- **"涂料及防腐防水材料"占比异常高**（约 81%）：怀疑是 PDF 章节识别被该章节页眉频繁触发，下一步可加章节切换校验
- **2026 年 PDF 格式变更**：从破折号 `1—2期` 变为顿号 `5、6期`（v0.8 已兼容）

## 关联

- 上游：`http://zjt.qinghai.gov.cn/html/132/List.html`（首页 + 3 个分页）
- 下游：政府材料价格 Dashboard（消费 ES 数据）
- 同类：`sichuan-price` / `chongqing-price` / `jinan-price` / `rizhao-price` / `xian-price` / `shaanxi-price` / `xinjiang-price` / `hainan-price` / `henan-price` / `qingdao-price` / `weihai-price` / `hunan-price` / `ningxia-price` / `huhehaote-price` / `heze-price`
- SyncRunner 范式：`chongqing-price`（v0.8 试点，2026-07-02 验证）+ `henan-price`（v0.8 试点，2026-07-03 验证）+ `huhehaote-price`（v0.8，2026-07-03 验证）
