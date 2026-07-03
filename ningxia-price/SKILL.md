---
name: "ningxia-price"
description: "宁夏工程造价信息采集：jst.nx.gov.cn《宁夏工程造价》期刊，HTML 列表 + 详情页抓 PDF，按期刊期数入库到 ods_material_ningxia_price，含 period_start/period_end/period_days 字段（v0.8, 2026-07-03）。"
---

# ningxia-price

宁夏回族自治区住房和城乡建设厅"造价动态"栏目《宁夏工程造价》期刊采集。从 `jst.nx.gov.cn/ztzl/gczj/zjtt/` 抓取列表（按月发布），访问详情页拿 PDF 链接，下载 PDF，上传 MinIO，pdfplumber 解析为长表，按期刊期数同步至 ES，写入 `ods_material_ningxia_price`。

> 🆕 **v0.8（2026-07-03）**：SyncRunner 抽象基类化 + 新增 `period_start/period_end/period_days` 字段（道友要求）
> **当前数据范围**：2026 年第 1 期 + 第 2 期，**6403 docs**
> 模块结构参考 chongqing v0.9 试点（chongqing_collector.py）+ huhehaote v0.8（huhehaote_collector.py）+ hunan v0.8（hunan_collector.py）
> 列表还含 2023-2025 各期，按需扩展。**只保留标题含"《宁夏工程造价》"的期**，跳过其他通知。

## 数据流

```
jst.nx.gov.cn/ztzl/gczj/zjtt/index.html (列表 HTML)
   ↓ + index_2.html / index_3.html ... (共 5 页)
列表 (每期: title, publish_date, detail_url)
   ↓ journal_keyword 过滤（"《宁夏工程造价》"）
详情页
   ↓ fetch_detail_pdf
   ↓ 从 a[href$=pdf] 或 var params="…pdf"; JS 字符串提取 PDF 链接
PDF (154-159 页, ~5-9 MB)
   ↓ upload
MinIO: gov-price-data/ningxia-price/{period}/{basename}.pdf
   ↓ pdfplumber.extract_tables
   ↓ 仅解析"价格资讯"章节，跳过政策文件/改革探索/采集编制说明等
   ↓ 横向"材料×城市"价格表 → 长表展开（每市/县一行）
   ↓ 跳过定额项目价格表（项目编号 5 位）
长表
   ↓ bulk_index（含 period_start/end/days）
ods_material_ningxia_price
```

## v0.8 改造要点

### 1. SyncRunner 抽象基类化（参考 chongqing v0.9 + hunan v0.8）
- 抽 `commands/ningxia_collector.py`：`NingxiaCollector` 继承 `gov_price_etl.collectors.base.SyncRunner`
- 通用基础设施（SIGINT / 本地进度 / 进度汇总）由基类提供，ningxia 只保留站点特化逻辑
- `commands/sync.py` 改为 CLI 入口：默认走 Collector，--legacy 走 v3 `cmd_legacy_sync`（逃生通道）
- `commands/sync_v3_legacy.py` 保留 v3 主流程 + `cmd_legacy_sync()` 函数
- `commands/sync_legacy.py` 作为 v3 旧路径的导入别名（avoid 命名冲突），供 collector 复用

### 2. 字段扩展：period 窗口（道友要求字段不能缺）
- `period`：业务期号（'2026.第1期' / '2026.第2期'）
- **`period_start`**：期首日（'2026-01-01' / '2026-03-01'）
- **`period_end`**：期末日（'2026-02-28' / '2026-04-30'）
- **`period_days`**：期天数（59 / 61）

解析来源（双月刊策略）：
- 宁夏 PDF 是**双月刊**（每年 6 期：1-2 / 3-4 / 5-6 / 7-8 / 9-10 / 11-12 月）
- 第 N 期 → 覆盖 (N-1)*2+1 月 至 N*2 月
- 例：第2期 → 2026-03-01 ~ 2026-04-30（61 天）
- PDF 本身没有"适用时间"文本，所以用业务期号 + 双月刊规律推算
- 算法：`parse_period_window_from_issue(year, issue_num)`
  - start_month = (issue_num - 1) * 2 + 1
  - end_month = issue_num * 2
  - period_start = 每月 1 日，period_end = 每月末日

### 3. Mapping 扩展
- `utils.ensure_ods_index` 注入 ningxia 特有字段：`region` / `breed_table_kind` / `publish_date`
- `period_start/end/days` 自动从 `build_ods_mapping` 标准模板继承

### 4. 已知 bug 修复
- `config.yml` 的 `list_pages` 从 6 改为 5（实际只有 5 页，page 6 已 404）
- `fetch_all_periods` 把 404 当作"已超出范围，正常结束"（不再硬 fail）

## 快速启动

```bash
cd ~/.openclaw/workspace/skills/ningxia-price

# 默认走 collector（v0.8）
./run.sh sync --year 2026
./run.sh sync --year 2026 --period "2026年第2期"   # 限定单期
./run.sh sync --year 2026 --max-units 1           # 测试跑 1 期
./run.sh sync --year 2026 --dry-run              # 预览（不入库）
./run.sh sync --year 2026 --reset                # 重置本地进度

# v3 逃生通道（仅 collector 异常时用）
./run.sh sync --year 2026 --legacy

# 其他命令（用 run.sh 也行）
./run.sh status     # 查看同步状态
./run.sh check      # 增量检测（不写入）
```

## PDF 结构

| 章节 | 内容 | 是否解析 |
|---|---|---|
| 政策文件 / 改革探索 / 信息动态 | 文章 | ❌ 跳过 |
| 采集编制说明 | 文字说明 | ❌ 跳过 |
| 价格资讯 → 人工价格信息 | 工种 × 价格区间 | ❌ 暂未解析（4列简单表，未来可加） |
| 价格资讯 → 定额项目价格（8-11 节） | 项目编号 × 项目名 × 单位 × 价格 | ❌ 暂未解析（横排项目编号） |
| **价格资讯 → 材料价格信息** | 序号 × 材料 × 规格 × 单位 × 各市县价 | ✅ 主体 |
| 价格资讯 → 市政工程主要材料 | 同上结构 | ✅ 兼容（同表头）|
| 价格资讯 → 预拌混凝土 / 绿色认证混凝土 | 地区 × 强度等级 × 多列价格 | ❌ 暂未解析（横排表）|

## 当前解析覆盖（v2）

| 章节 | 条数/期 | 表头结构 | cities 字段 |
|---|---|---|---|
| 一~五、地市基础表（银川/石嘴山/吴忠/固原/中卫）| 22 项 × 2~5 城市 = 70~110 | 6+ 列 | 各县/市 |
| 六、宁东能源化工基地 | 14 项 | 5 列单价格 | 综合价格 |
| 全区建筑工程主要材料价格（p66-p144）| ~1200 项 | 6 列含备注 | 综合价格 |
| 装配式及绿色建材（p145-p148）| ~50 项 | 6 列 | 综合价格 |
| 绿色建材多星等级（p149-p151）| ~150 项 | 8 列 | 一星级/二星级/三星级 |
| 预拌混凝土 / 绿色认证混凝土（p150-p152）| ~150 项 | 12 列 | ❌ 未解析 |

## 字段映射

| 字段 | 来源 |
|---|---|
| `period` | 从 title 提取：`2026年第2期` → `2026.第2期` |
| `period_start` | 双月刊规律推算：第1期 → YYYY-01-01 |
| `period_end` | 双月刊规律推算：第1期 → YYYY-02-末日 |
| `period_days` | `(period_end - period_start).days + 1` |
| `publish_date` | 列表 `<time class="fr">` 抽的发布日期 |
| `section` | 固定 `材料价格` |
| `category` | 固定 `主要材料` |
| `region` | 地市分组（一、银川市 / 二、石嘴山市 / ...）|
| `city` | 表格列头（银川市/灵武市/大武口区/...）|
| `no` | 表格首列（材料序号 1-22）|
| `breed` | 表格第 2 列（材料名称）|
| `spec` | 第 3 列（规格型号）|
| `unit` | 第 4 列（单位）|
| `price` | 城市价格列（去税价？见下）|
| `tax_price` | 含税价（price × 1.13）|
| `province` | 固定 `宁夏` |
| `source_pdf` | MinIO 路径（`{prefix}/{period}/{basename}.pdf`）|
| `source_url` | 原始 PDF URL |
| `create_time` | 索引写入时间 |
| `breed_table_kind` | 表格类型（`material` / `quota`） |

**价格方向**：宁夏 PDF 价格表默认是**不含税价**（表格单位"元"无特别说明），按 13% 增值税率反推含税价。

## 项目结构

```
ningxia-price/
├── config.yml                          # ES / MinIO / 站点配置
├── .ningxia_sync_progress.json         # 本地进度
├── run.sh                              # 启动脚本
├── skill.yml                           # dashboard 注册
└── commands/
    ├── sync.py                     # v0.8 CLI 入口（默认走 collector，--legacy 走 v3）
    ├── ningxia_collector.py        # v0.8 默认：SyncRunner 抽象基类化
    ├── sync_v3_legacy.py           # v3 主流程（逃生通道，含 cmd_legacy_sync 函数）
    ├── sync_legacy.py              # v3 旧路径的导入别名，供 collector 复用
    ├── check.py                    # 增量检测
    ├── status.py                   # 查看本地/ES 进度
    ├── preview.py                  # v3 预览（已迁入 sync.py --dry-run）
    └── utils.py                    # load_config / es / minio
```

## Dashboard 注册

为了让 `gov-price-dashboard` 自动发现本 skill，根目录需要 `skill.yml`（小写）：

```yaml
key: ningxia
label: 宁夏
province: 宁夏
ods_index: ods_material_ningxia_price
progress_index: ods_material_ningxia_price_sync_progress
progress_mode: period
expand_label: "▾ 期数详情"
config_path: config.yml
cities:
  - 银川市
  - 石嘴山市
  - 吴忠市
  - 固原市
  - 中卫市
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
- `mappings.{build_ods_mapping, build_progress_mapping}`（含 `period_start/end/days` 标准字段）

## 已知限制

- **定额项目价格表未解析**（8-11 节项目编号 5 位）——需另外开发 `_parse_quota_table`（已写框架，未启用）
- **人工价格表未解析**（4 列：序号/工种/单位/价格区间"190～230"）
- **预拌混凝土横排表未解析**（地区 × 强度等级 × 12 列价格）——结构特殊
- **2026.1期 偶有 PdfminerException**（p3-p4 封面页），已 try/except 跳过
- **价格含税/不含税方向**：默认按不含税入 price，tax_price = price × 1.13。PDF 实际是含税价还是不含税价，需以原文档为准
- **市/县字段**从表头列名推断；COMMON_COUNTIES 列表需维护新县区时扩展
- **period 窗口**基于业务期号 + 双月刊规律推算（非 PDF 显式声明），若发布周期变化需检查算法

## 关联

- 上游：`https://jst.nx.gov.cn/ztzl/gczj/zjtt/`
- 下游：政府材料价格 Dashboard（消费 ES 数据）
- 同类：`chongqing-price` / `huhehaote-price` / `sichuan-price` / `henan-price` / `hainan-price` / `qingdao-price` / `qinghai-price` / `hunan-price` / `jiangxi-price` / `weihai-price` / `shaanxi-price` / `xinjiang-price` / `xian-price` / `jinan-price` / `rizhao-price` / `heze-price`
- SyncRunner 范式：`chongqing-price`（v0.9 试点，2026-07-02 验证）+ `huhehaote-price`（v0.8，2026-07-03 验证）+ `hunan-price`（v0.8，2026-07-03 验证）+ `ningxia-price`（v0.8，2026-07-03 验证）
