---
name: "huhehaote-price"
description: "呼和浩特建设工程材料价格采集：zfcxjsj.huhhot.gov.cn 信息价期刊，HTML 列表抓 PDF，按期刊期数入库到 ods_material_huhehaote_price，含 period_start/period_end/period_days 字段。"
---

# huhehaote-price

呼和浩特市住房和城乡建设局"造价信息"栏目《信息价》期刊采集。从 `zfcxjsj.huhhot.gov.cn/bsfw_91/xzzx/zjxx/index.html` 抓取列表（单页），访问详情页拿 PDF 链接，下载 PDF，上传 MinIO，pdfplumber 解析为长表，按期刊期数同步至 ES，写入 `ods_material_huhehaote_price`。

> 🆕 **v0.8（2026-07-03）**：SyncRunner 抽象基类化 + 新增 `period_start/period_end/period_days` 字段（道友要求）
> **当前数据范围**：2026 年第 1 期（2026-03-31），共 **1854 条**（v0.x 历史同步）。
> 列表还含 2022/2025 各期，按需扩展。**只保留标题含"信息价"的期**，跳过其他通知。

## 数据流

```
zfcxjsj.huhhot.gov.cn/bsfw_91/xzzx/zjxx/index.html (列表 HTML)
   ↓ 无分页（单页）
列表 (每期: title, publish_date, detail_url)
   ↓ journal_keyword 过滤（"信息价"）
详情页
   ↓ fetch_detail_pdf
   ↓ 从 JS 字符串 var fujian='…pdf'; 或 <video src="…pdf"> 提取 PDF 链接
PDF (86 页, ~580 KB)
   ↓ upload
MinIO: gov-price-data/huhehaote-price/{period}/{basename}.pdf
   ↓ pdfplumber.extract_tables
   ↓ 仅解析"价格资讯"章节：4 类表格
   ↓ 7 列表材料价格（编码/名称/单位/含税/除税/税率/备注）→ 长表
   ↓ 4 列表人工成本（序号/工种/日工资/备注）→ 长表
   ↓ 5 列表机械租赁（序号/名称/型号/单位/价格）→ 长表
长表
   ↓ bulk_index（含 period_start/end/days）
ods_material_huhehaote_price
```

## PDF 结构

| 章节 | 内容 | 表头结构 | 是否解析 |
|---|---|---|---|
| p1-p79: 呼市地区建设工程材料市场价格信息采集 | 7 列（编码/名称/单位/含税价/除税价/税率/备注）| ✅ 主体 |
| ├ 01 黑色及有色金属 / 02 水泥 / ... 32 花卉苗木 | 数字小节 | ✅ 数字 section |
| ├ 一、通用及建筑装饰材料 | 中文大类 | ✅ |
| p80-p83: 五、旗县区 | 同 7 列表 | ✅ |
| ├ 1、土左旗 / 2、托克托县 / 3、和林格尔县 / 4、武川县 / 5、清水河县 | 旗县标题行 | ✅ city 区分 |
| p84: 呼市地区建筑工种人工成本信息 | 4 列（序号/工种/日工资/备注）| ✅ |
| p85: 呼市地区建设工程施工机械租赁价格信息 | 5 列（序号/名称/型号/单位/价格）| ✅ |
| p86: 二〇二五年末建筑安装工程单方造价参考信息 | 5 列（区间值，参考信息）| ❌ 暂不解析 |

## 字段映射

| 字段 | 来源 |
|---|---|
| `period` | title 提取：`2026年信息价1期` → `2026.第1期` |
| `period_start` | 期刊窗口首日（双月刊第 N 期 = (2N-1) 月 1 日）|
| `period_end` | 期刊窗口末日（双月刊第 N 期 = (2N) 月末日）|
| `period_days` | (period_end - period_start).days + 1 |
| `category` | `材料价格` / `人工成本` / `机械租赁` |
| `section` | 数字小章节（"01 黑色及有色金属"）/ 中文大类（"通用及建筑装饰材料"）/ `人工成本` / `机械租赁` |
| `city` | "呼和浩特"（全市统一价）或旗县名（"土左旗" / "托克托县" / ...）|
| `no` | 材料编码（6-9 位数字，如 `01010001` / `099100001`）|
| `breed` | 材料名称 / 工种 / 机械名称 |
| `spec` | 型号规格（仅机械表）|
| `unit` | 计量单位 |
| `price` | 除税价（材料表）/ 单价（人工/机械）|
| `tax_price` | 含税价（材料表）/ 等于 price（人工/机械）|
| `vat_rate` | 平均税率（仅材料表，从 PDF 直接读）|

### period 窗口推算（v0.8 新增）

呼和浩特"造价信息"为**双月刊**（每期覆盖 2 个连续月份）：

| 期号 | 月份范围 | 示例（2026） |
|---|---|---|
| 第 1 期 | 1-2 月 | period_start=2026-01-01, period_end=2026-02-28, period_days=59 |
| 第 2 期 | 3-4 月 | period_start=2026-03-01, period_end=2026-04-30, period_days=61 |
| 第 3 期 | 5-6 月 | period_start=2026-05-01, period_end=2026-06-30, period_days=61 |
| 第 4 期 | 7-8 月 | period_start=2026-07-01, period_end=2026-08-31, period_days=62 |
| 第 5 期 | 9-10 月 | period_start=2026-09-01, period_end=2026-10-31, period_days=61 |
| 第 6 期 | 11-12 月 | period_start=2026-11-01, period_end=2026-12-31, period_days=61 |

解析规则（`huhehaote_collector.parse_period_window`）：
1. 优先从 title 抽 `(M1-M2月)` 范围（如"2025年第六期（11-12月份）"）
2. 否则按双月刊规律：第 N 期 = (2N-1, 2N) 月
3. 兜底：返回空窗口（period_start/end/days 为空）

## 快速启动

```bash
cd skills/huhehaote-price

# v0.8 默认走 Collector（SyncRunner 抽象基类）
./run.sh sync --year 2026 --all            # 同步 2026 年所有期
./run.sh sync --year 2026 --latest         # 同步 2026 年最新一期
./run.sh sync --year 2026 --max-units 1    # Collector 路径：只跑前 N 个工作单元（验证用）

# --legacy 走原 v0.x main 流程（逃生通道）
./run.sh sync --year 2026 --all --legacy   # 走原 v0.x 流程（含 v0.8 字段扩展）

# 预览（不写入 ES / 不上传 MinIO）
./run.sh preview --year 2026               # 预览 2026 年所有期
./run.sh preview --latest                  # 预览最新一期

# 查看进度 / 检测增量
./run.sh status                            # 查看本地 + ES + MinIO 进度
./run.sh check                             # 增量检测（dashboard chip 复用）
```

## v0.8 改造要点

### 1. SyncRunner 抽象基类化（参考 chongqing v0.8 试点 + henan v0.8）
- 抽 `commands/huhehaote_collector.py`：`HuhehaoteCollector` 继承 `gov_price_etl.collectors.base.SyncRunner`
- 通用基础设施（SIGINT / 本地进度 / 进度汇总）由基类提供，huhehaote 只保留站点特化逻辑（PDF 解析、详情页 JS 提取）
- `commands/sync.py` 改为 CLI 入口：默认走 Collector，--legacy 走 v0.x `cmd_legacy_sync`（逃生通道）

### 2. 字段扩展：period 窗口（道友要求）
- `period`：业务期号（"2026.第1期"）
- **`period_start`**：期首日（"2026-01-01"）
- **`period_end`**：期末日（"2026-02-28"）
- **`period_days`**：期天数（59 天 = 1月 + 2月）

### 3. 标准 mapping 同步
- v0.8 之前本地手写 mapping 字符串（仅基础字段）
- v0.8 委托到 `gov_price_etl.mappings.build_ods_mapping` / `build_progress_mapping`
- 自动含 `period_start / period_end / period_days / city` 等 36+ 字段
- 进度索引同步扩展（v0.8 改：`build_progress_mapping._PROGRESS_BASE_FIELDS` 新增 3 字段）

## Dashboard 注册

为了让 `gov-price-dashboard` 自动发现本 skill，根目录需要 `skill.yml`（小写）：

```yaml
key: huhehaote
label: 呼和浩特
province: 内蒙古
ods_index: ods_material_huhehaote_price
progress_index: ods_material_huhehaote_price_sync_progress
progress_mode: period
expand_label: "▾ 期数详情"
config_path: config.yml
cities:
  - 呼和浩特
  - 土默特左旗
  - 托克托县
  - 和林格尔县
  - 武川县
  - 清水河县
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

- **2026 年仅 1 期**：源站 2026 年只发了 1 期（2026-03-31），其他是 2022/2025 历史期
- **单方造价参考信息未解析**（p86，区间值）
- **subsection 检测严格**：单行 ≤ 20 字符，避免"编者按"等说明性长文本被识别成章节
- **机械表 _id 加入 spec**：多型号机械共用 `no+breed`，需 spec 区分（如 no=1 履带式推土机 75KW / 95KW）
- **旗县价格简版**：旗县区只有 11-15 项基础材料（钢筋/水泥/砂石/砖等），全市材料表有 1700+ 项
- **v0.x legacy 路径**：保留 v0.x main 流程作为逃生通道（`--legacy`），数据写入仍含 v0.8 新字段（period 窗口）

## 关联

- 上游：`http://zfcxjsj.huhhot.gov.cn/bsfw_91/xzzx/zjxx/index.html`
- 下游：政府材料价格 Dashboard（消费 ES 数据）
- 同类：`sichuan-price` / `chongqing-price` / `jinan-price` / `rizhao-price` / `xian-price` / `shaanxi-price` / `xinjiang-price` / `hainan-price` / `henan-price` / `qingdao-price` / `weihai-price`
- SyncRunner 范式：`chongqing-price`（v0.8 试点，2026-07-02 验证）+ `henan-price`（v0.8 试点，2026-07-03 验证）