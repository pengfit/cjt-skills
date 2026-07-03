---
name: hunan-price
description: "湖南建设工程材料价格行情采集：从 zjt.hunan.gov.cn 抓取 14 页列表的 2 类期刊（行情资讯/行情表），PDF 解析后入 ods_material_hunan_price，含 period_start/period_end/period_days 字段（v0.8, 2026-07-03）。"
---

# hunan-price

湖南省住房和城乡建设厅"造价管理"栏目《建设工程材料价格行情》系列采集。从 `zjt.hunan.gov.cn/zjt/hnweb/xzzx/zlxx/` 抓取 14 页列表（HTML），按标题 keyword 过滤 → 访问详情页抽 PDF 链接 → 下载 PDF → 上传 MinIO → pdfplumber 解析为长表 → bulk_index 写入 `ods_material_hunan_price`。

> 🆕 **v0.8（2026-07-03）**：SyncRunner 抽象基类化 + 新增 `period_start/period_end/period_days` 字段（道友要求）
> **当前数据范围**：2026 年共 9 期（行情资讯 1 期 + 行情表 8 期），**2409 docs**（v0.8 首跑）
> 模块结构参考 chongqing v0.8 试点 + huhehaote v0.8（同样是 PDF 期刊类）
> 列表还有 2025/历史 期，按需扩展。**只保留标题含 keyword 的期**。

## 数据流

```
zjt.hunan.gov.cn/zjt/hnweb/xzzx/zlxx/index.html (列表首页)
   ↓ + 13 个分页 (/index_2.html ~ /index_14.html)
列表 (每条: title, detail_url)
   ↓ journal_keywords 过滤
   ↓   "湖南省建设工程材料价格行情资讯"     → kind=zixun（行情资讯，双月刊）
   ↓   "钢筋、水泥、砂石、混凝土材料价格行情表" → kind=hangqingbiao（行情表，半月刊）
详情页 (HTML)
   ↓ fetch_detail_pdf（从 <a href="...files/{hash}.pdf"> 抽 PDF URL）
PDF (1 页 biao / 15 页 zixun, 100KB-3MB)
   ↓ upload（已存在则跳过）
MinIO: gov-price-data/hunan-price/{period}/{basename}.pdf
   ↓ pdfplumber.extract_tables
   ↓ period 窗口解析（zixun 走 title，biao 走 PDF 编制说明"适用时间"）
长表
   ↓ _new_docs_for_es（注入 period_start/end/days）
ods_material_hunan_price
```

## 两种期刊对比

| kind | 标题模式 | 周期 | 表格 | docs/期 | period 窗口源 |
|---|---|---|---|---|---|
| `zixun` | `2026年第一期（1-2月份）...行情资讯` | 双月刊 | p1-2 各市州价格+涨跌幅 / p3-5 全省综合价 / p6-8 综合价指数 / p9-14 图表 / p15 行情报告 | 1783 | title `(M1-M2月份)` 字段 |
| `hangqingbiao` | `2026年全省第八期钢筋、水泥、砂石、混凝土材料价格行情表` | 半月刊 | 14 市州 × 6 材料 × (价格+涨跌幅) | 78-79 | PDF 编制说明第 3 条 `适用时间：YYYY年M月D日-M月D日` |

> 行情表 6 种固定材料：螺纹钢筋（抗震 HRB400E 20-25）/ 普通硅酸盐水泥（P·O 42.5 散装）/ 天然粗砂 / 机制砂（河机砂）/ 碎石（10-20mm）/ 商品混凝土（碎石 C30）

## Period 窗口解析（v0.8 新增）

### 行情资讯（zixun）
title 自带 `(M1-M2月份)`，直接 regex 抽出：
- `'2026年第一期（1-2月份）...行情资讯'` → `period_start=2026-01-01, period_end=2026-02-28, period_days=59`

### 行情表（hangqingbiao）— 权威源：PDF 编制说明
半月刊，PDF 首页"编制说明"第 3 条文字直接写出"适用时间：YYYY年M月D日-M月D日"：
- 期 1 (1月 上半月): `2026-01-01 ~ 2026-01-15` (15d)
- 期 2 (1月 下半月): `2026-01-15 ~ 2026-01-31` (17d)  # PDF 写的就是 1月15日起
- 期 3 (2月 上半月): `2026-02-01 ~ 2026-02-15` (15d)
- 期 4 (2月 下半月): `2026-02-16 ~ 2026-02-28` (13d)
- 期 5-8: 3-4 月各 2 期

兜底：若 PDF 解析失败（缺 适用时间 字段），从 URL `YYYYMM` 推算当月窗口。

## 项目结构

```
hunan-price/
├── config.yml                      # ES / MinIO / 站点 / 14 市州配置
├── .hunan_sync_progress.json       # 本地进度（断点续传）
├── run.sh                          # 启动脚本
├── skill.yml                       # dashboard registry
└── commands/
    ├── sync.py                 # 同步入口（默认 Collector；--legacy 走 v0.x）
    ├── hunan_collector.py      # v0.8 默认：SyncRunner 抽象基类化
    ├── write_es.py             # （v0.x 兼容，本版未拆分）
    ├── check.py                # 增量检测
    ├── status.py               # 查看本地/ES 进度
    ├── preview.py              # 预览（v0.x）
    └── utils.py                # load_config / es / minio
```

## 快速开始

```bash
cd ~/.openclaw/workspace/skills/hunan-price

# 同步（默认 Collector 路径）
python3 commands/sync.py --year 2026
python3 commands/sync.py --year 2026 --max-units 1     # 验证用
python3 commands/sync.py --year 2026 --kinds zixun      # 只跑行情资讯
python3 commands/sync.py --year 2026 --kinds hangqingbiao  # 只跑行情表

# v0.x 兼容（仅 Collector 异常时备用）
python3 commands/sync.py --legacy --year 2026 --all
python3 commands/sync.py --legacy --latest              # 最新一期

# 其他命令
python3 commands/status.py    # 查看进度
python3 commands/check.py     # 增量检测
```

## v0.8 改造要点

### 1. SyncRunner 抽象基类化（参考 chongqing v0.8 试点 + huhehaote v0.8）
- 抽 `commands/hunan_collector.py`：`HunanCollector` 继承 `gov_price_etl.collectors.base.SyncRunner`
- 通用基础设施（SIGINT / 本地进度 / 进度汇总）由基类提供，hunan 只保留站点特化逻辑
- `commands/sync.py` 改为 CLI 入口：默认走 Collector，--legacy 走 v0.x `cmd_legacy_sync`（逃生通道）

### 2. 字段扩展：period 窗口（道友要求）
- `period`：业务期号（'2026.第1期(行情资讯)' / '2026.第1期(行情表)'）
- **`period_start`**：期首日（'2026-01-01'）
- **`period_end`**：期末日（'2026-01-15' / '2026-02-28'）
- **`period_days`**：期天数（半月 15-17 / 双月 59-61）

解析来源（`hunan_collector.parse_period_window_*`）：
- `zixun` 从 title `(M1-M2月份)` regex
- `hangqingbiao` 从 PDF 首页"编制说明"第 3 条"适用时间"regex
- 兜底：URL YYYYMM → 当月窗口

### 3. 标准 mapping 同步
- v0.8 之前本地手写 mapping 字符串（仅基础字段）
- v0.8 委托到 `gov_price_etl.mappings.build_ods_mapping(city_extension=...)`
- city_extension 字段：no / code / change_rate / index_value / period_sub / price_kind / minio_key / source_pdf / section / update_date / create_time
- 自动含 `period_start / period_end / period_days` 等 49 个标准字段

### 4. 已知 bug 修复
- `parse_period_label` 旧版 `[\d]+` 不匹配中文"第一"，导致 行情表 期号 fallback 到 title[:30]（带乱码）
  - 修：换 `[一二三四五六七八九十\d]+` + `_cn_to_int()` 转阿拉伯
- `fetch_html` / `download_file` 旧版 except 只接 `SSLError`，但 requests 实际抛 `ConnectionError`（包了 SSL 原因）
  - 修：except 加 `ConnectionError, Timeout`

## 字段映射

| 字段 | 来源 |
|---|---|
| `period` | 业务期号（'2026.第1期(行情表)' / '2026.第1期(行情资讯)'）|
| `period_start` | zixun: title 抽 (M1-M2月份) / hangqingbiao: PDF "适用时间" 字段 |
| `period_end` | 同上 |
| `period_days` | (period_end - period_start).days + 1 |
| `section` | `'各市州建设工程主要材料价格表'` / `'建设工程主要材料全省综合价表'` / `'建设工程主要材料全省综合价指数表'` / `'钢筋、水泥、砂石、混凝土材料价格行情表'` |
| `city` | 14 市州之一（长沙/株洲/.../邵阳），全省综合价表写 `'湖南省'` |
| `period_sub` | 子期（'1月' / '2月' / '1.1-1.10'）—— 仅 行情资讯 p1/p2 表用 |
| `no` | 材料序号（'1'~'200+'）|
| `breed` | 材料名称 |
| `spec` | 规格 |
| `unit` | 单位 |
| `price` | 单价（除税价）|
| `change_rate` | 涨跌幅（百分点，如 0.0243 = 2.43%）|
| `index_value` | 价格指数（定基/环比/同比）|
| `minio_key` | `hunan-price/{period}/{basename}.pdf` |
| `source_url` | PDF 源 URL |
| `publish_date` | 从 URL `tYYYYMMDD_xxx.html` 抽发布日期 |

## Dashboard 注册

为了让 `gov-price-dashboard` 自动发现本 skill，根目录需要 `skill.yml`（小写）：

```yaml
key: hunan
label: 湖南
province: 湖南
ods_index: ods_material_hunan_price
dwd_index: dwd_hunan_price
dws_index: dws_hunan_price
progress_index: ods_material_hunan_price_sync_progress
progress_mode: period
expand_label: "▾ 期数详情"
config_path: config.yml
cities:
  - 长沙市
  - 株洲市
  # ... 14 个市州
```

dashboard 扫描 `~/.openclaw/workspace/skills/*/skill.yml` 自动注册。修改后调用 `POST /api/skill-registry/reload` 触发重扫 + 热更新 ALL_INDICES。

## 依赖

- Python 3.10+
- pdfplumber
- boto3 (MinIO S3 兼容)
- elasticsearch
- requests / beautifulsoup4 / pyyaml

**强依赖 `gov-price-etl`**（部署在 `~/.openclaw/workspace/skills/gov-price-etl`）：
- `collectors.base.SyncRunner`（v0.8 抽象基类）
- `collectors.{get_es_client, get_s3_client, fetch_html, download_file, upload_to_minio, ...}`
- `mappings.{build_ods_mapping, build_progress_mapping}`（v0.5/v0.6 集中维护 mapping）

## 已知限制

- **2026 年仅 9 期**：源站 2026 年发了 1 期 行情资讯 + 8 期 行情表（覆盖 1-4 月）
- **半月表 6 种材料硬编码**：PDF 表头固定（螺纹钢/水泥/砂/碎石/混凝土），无独立规格列，sync 时硬拆 breed/spec/unit
- **行情资讯 p2 涨跌幅表不入库**：仅入价格表 p1 + 全省综合价 p3-5 + 综合价指数 p6-8（涨跌幅表 price=0 被过滤，无价值）
- **行情资讯 p9-14 图表 + p15 综述不入库**：图表无法解析，综述是文本
- **v0.x legacy 路径**：保留 v0.x `cmd_legacy_sync` 作为逃生通道（`--legacy`），数据写入仍含 v0.8 新字段（period 窗口）
- **MinIO 已存在检测**：`_minio_exists()` 检查后跳过重复上传（`head_object` → 404 才上传）
- **进度 key 用 `hn:` 前缀**：与 LocalProgressStore 平铺 key 兼容（详情 key = `hn:<detail_url>`）

## 关联

- 上游：`https://zjt.hunan.gov.cn/zjt/hnweb/xzzx/zlxx/`
- 下游：政府材料价格 Dashboard（消费 ES 数据）
- 同类：`chongqing-price` / `huhehaote-price` / `sichuan-price` / `henan-price` / `hainan-price` / `qingdao-price` / `qinghai-price` / `ningxia-price` / `jiangxi-price` / `weihai-price` / `shaanxi-price` / `xinjiang-price` / `xian-price` / `jinan-price` / `rizhao-price` / `heze-price`
- SyncRunner 范式：`chongqing-price`（v0.8 试点，2026-07-02 验证）+ `huhehaote-price`（v0.8，2026-07-03 验证）+ `hunan-price`（v0.8，2026-07-03 验证）
