---
name: shaanxi-price
description: "陕西工程造价材料信息采集：从 js.shaanxi.gov.cn 抓取全省 10 个设区市 + 省本级的材料价格 PDF（覆盖 2026 年），存到 minio 并入库到 ods_material_shaanxi_price，含 period_start/period_end/period_days 字段。"
---

# shaanxi-price

陕西工程造价材料信息采集 Skill。从 `js.shaanxi.gov.cn`（陕西省住房和城乡建设厅）的 **造价信息** 栏目抓取每月/每期 PDF 附件：覆盖省本级《陕西工程造价信息》和 9 个设区市《XX 建设工程造价信息》。流程参考 `henan-price`：列表 → 详情 → PDF → MinIO → ES 幂等写入。

> **v1.0 重构（2026-07-03）**：模块建构参考 `chongqing-price` v0.9 / `qingdao-price` v0.9，sync.py 从一站式 main() 重写为 `ShaanxiCollector`（继承 `gov_price_etl.collectors.base.SyncRunner`）。同时补齐道友硬要求的 3 个字段：`period_start / period_end / period_days`。
>
> **数据范围**：默认 `year=2026`（`cfg.sync.target_year`），月度/双月度/季度 PDF 全部覆盖。
>
> 旧 `sync.py` 已重命名为 `sync_legacy.py` 作为逃生通道，`--legacy` 走老路径。

## 数据流

```
js.shaanxi.gov.cn/sy/yw/zjglfw/zjxx/  (列表 5 页, 97 条)
       ↓ fetch
列表 (25 期 × 2026年) → 详情页 → PDF 链接
       ↓ download + upload
MinIO: gov-price-data/shaanxi-price/{period}_{name}/source.pdf
       ↓ pypdf / pdfplumber 多格式解析
长表 (材料 × 规格 × 单位 × 设区市/县区 × 价格)
       ↓ bulk_index（含 period_start/end/days）
ods_material_shaanxi_price
```

## 快速启动

```bash
cd skills/shaanxi-price

./run.sh test                          # 测试连通性（ES + MinIO + 源站 + PDF 下载）
./run.sh check                         # 增量检测（不写入）
./run.sh status                        # 查看同步状态
./run.sh status --es                   # 查看 ES 索引详情

./run.sh sync --dry-run                # 预览同步（不写入）
./run.sh sync --year 2026              # 同步所有 2026 年期（默认）
./run.sh sync --latest                 # 同步最新一期
./run.sh sync --period 2026.5期        # 同步指定 period
./run.sh sync --period 2026.5月
./run.sh sync --reset                  # 重置进度，从头开始

# v1.0 新增
./run.sh sync --max-units 3            # 只跑前 3 个 unit（验证用）
./run.sh sync --legacy --year 2026     # 走 v0.5 sync_legacy.py（逃生通道）
./run.sh sync --run-id sn_run_xxx      # 指定 run_id
```

## 数据源

- **列表页**：`https://js.shaanxi.gov.cn/sy/yw/zjglfw/zjxx/index.html` (含分页 1-5)
  - `index.html` + `index_1.html` ... `index_4.html`，共 97 条（2026 年约 25 期）
- **详情页**：`/sy/yw/zjglfw/zjxx/{YYYYMM}/t{YYYYMMDD}_{uuid}.html`
- **PDF 附件**：`/sy/yw/zjglfw/zjxx/{YYYYMM}/P020{YYMMDD}{NNN}.pdf`
- **标题格式**：
  - 设区市：`设区市造价信息---《{city}建设工程造价信息》{YYYY}年第{N}期[（季刊/双月刊）]`
  - 省本级：`{YYYY}年{M}月材料信息价`
- **period 编码**：
  - 设区市：`2026.{N}期` 或 `2026.{N}期(季刊)` / `2026.{N}期(双月刊)`
  - 省本级：`2026.{M}月`

## 覆盖范围

| city | 频次 | 2026 期数 |
|------|------|-----------|
| 安康 | 月刊 | 5 期（2026.1-4 为扫描图像 PDF；2026.5 为数字 PDF，2260 条入库）|
| 汉中 | 月刊 | 5 期 |
| 咸阳 | 月刊 | 3 期 |
| 渭南 | 双月刊 | 2 期 |
| 铜川 | 月刊 | 2 期 |
| 榆林 | 月刊 | 2 期 |
| 商洛 | 季刊 | 1 期 |
| 陕西（省本级）| 月刊 | 6 期（每月，已入库到 2026.6）|
| 西安、宝鸡、延安 | - | 源站未在 2026 年发布（由 xian-price / 其他渠道单独采集）|

> 默认 `year=2026`（`cfg.sync.target_year`），`./run.sh sync --year 2026` 即默认全量。

## 数据字段

| 字段 | 说明 |
|------|------|
| `code` | 材料编码（如 `010101303`），部分设区市（汉中/商洛）为空 |
| `breed` | 材料名称（如 `热轧光圆钢筋`） |
| `spec` | 规格型号（如 `HPB300 Φ6~8`） |
| `unit` | 单位（如 `t`、`m³`、`个`、`千块`） |
| `price` | 除税价格（不含进项税） |
| `tax_price` | 含税价格 |
| `category` | 章节类目（如 `黑色及有色金属`） |
| `period` | 周期（如 `2026.5期`、`2026.6月`、`2026.1期(季刊)`） |
| **`period_start`** | **v1.0 必含 — 期间起始日（`yyyy-MM-dd`）** |
| **`period_end`** | **v1.0 必含 — 期间结束日（`yyyy-MM-dd`）** |
| **`period_days`** | **v1.0 必含 — 期间天数（`integer`）** |
| `province` | `陕西` |
| `city` | 设区市名（`安康`/`汉中`/...）或 `陕西`（省本级） |
| `county` | 县/区名（如 `汉滨区`/`南郑`），省本级和单价表为空 |
| `update_date` | 发布日期（列表上的 `YYYY-MM-DD`） |
| `create_time` | 入库时间 |
| `source_pdf` | MinIO 对象 key |
| `source_url` | 详情页 PDF URL |

### period_start / period_end / period_days 推算规则

由 `compute_period_dates(period)` 推算（`commands/shaanxi_collector.py`），覆盖陕西 4 种 period 格式：

| period | 含义 | period_start | period_end | period_days |
|--------|------|--------------|------------|-------------|
| `2026.5月` | 省本级月报 | 2026-05-01 | 2026-05-31 | 31 |
| `2026.5期` | 设区市月刊（第 N 期 = 第 N 月）| 2026-05-01 | 2026-05-31 | 31 |
| `2026.2期(双月刊)` | 设区市双月刊（第 N 期 = ((N-1)·2+1) 月 ~ (N·2) 月）| 2026-03-01 | 2026-04-30 | 61 |
| `2026.1期(季刊)` | 设区市季刊（第 N 期 = ((N-1)·3+1) 月 ~ (N·3) 月）| 2026-01-01 | 2026-03-31 | 90 |

## PDF 格式自动识别（按 city 维度组织）

陕西各设区市 PDF 格式不统一，本 skill **按 city 独立编写解析函数**，不依赖全局页面类型判断。

设计：
- `commands/city_parsers.py`：每个 city 一个独立函数（`parse_<city>(text, page_obj) -> List[MaterialRow]`）
- `commands/pdf_parser.py`：主入口，通过 `CITY_PARSERS` 字典按 city 分发
- 函数内部自动判断页面布局（多布局兼容时优先识别）
- 不识别的页面（工人工资、安装工程、租赁等）返回空列表

| city | 函数 | 支持的页面布局 | 说明 |
|------|------|----------------|------|
| 陕西 省本级 | `parse_shaanxi_province` | B 布局 | 月刊《材料信息价》|
| 咸阳 | `parse_xianyang` | B + E 布局 | 主要 B，末页可能 E（county 成组）|
| 铜川 | `parse_tongchuan` | C 布局 | 含税+除税+税率% 3 列价格 |
| 渭南 | `parse_weinan` | B 布局 | 双月刊 |
| 榆林 | `parse_yulin` | B 布局 | 月刊 |
| 汉中 | `parse_hanzhong` | F + B + H 三布局并行 | page 2-4 F（county 表） + page 6+ B（行内价格） + page 5-52 H（清单+价格表） |
| 商洛 | `parse_shangluo` | G 布局（pdfplumber 提取）| 季刊，双列布局 |
| 安康 | （未在 CITY_PARSERS）| 扫描图像型 PDF | OCR 暂未识别 → 标 `skipped_image_pdf` |

`安康` 2026.1-4 期是扫描图像 PDF（每页 3.8MB JPG），pypdf 提取不到文本；OCR 跑过但解析器不识别 OCR 输出格式，sync 流程直接标记 `skipped_image_pdf` 不入库。2026.5期是数字 PDF，正常入库 2260 条。

### 解析限制

- **商洛 PDF** 使用两列布局，pdfplumber 提取的部分行只有价格（前一行材料）；当前只保留 breed+spec 都不为空的行，因此只入库约 13 条/期。如需全量，需引入 cross-page material/price 配对逻辑。
- **汉中 PDF** v1.1 修复后：F 布局（page 2-4 county 表）+ B 布局（行内含价格）+ H 布局（顶材料清单 + 底除税/含税 2 列价格表，无 county 分布）三布局并行解析，5 期各 1100+ 条入库。
- **安康 PDF** 2026.1-4 期是扫描图像型，OCR 跑通但解析器不识别 OCR 输出格式，已标 `skipped_image_pdf` 跳过。需重写解析器支持 OCR 文本的 price-first 布局（010101303/热轧光圆钢筋/HPB300 Φ6~8 t 在除税价行之后）。
- **铜川 PDF**（C 布局）含税率字段，暂未入库（设计上未要求）。

## ES 索引

| 索引 | 说明 |
|------|------|
| `ods_material_shaanxi_price` | 材料价格数据（主数据，含 period_start/end/days） |
| `ods_material_shaanxi_price_sync_progress` | 同步进度（每期一条记录，含 period_start/end/days） |

### 幂等写入

```
_id = MD5(period + code + city + county)        # 有 code 时（绝大多数）
_id = MD5(period + breed + spec + city + county + unit)  # 无 code 时（商洛 G 类型）
```

同一份 PDF 多次同步不会重复入库；同一材料不同期/不同设区市有不同 _id。

## 项目结构

```
shaanxi-price/
├── SKILL.md
├── config.yml
├── run.sh
├── .shaanxi_sync_progress.json     # 本地进度（自动生成）
└── commands/
    ├── sync.py            # 同步入口（v1.0 默认走 ShaanxiCollector；--legacy 走 sync_legacy.py）
    ├── sync_legacy.py     # v0.5 一站式 main()（逃生通道，CLI 兼容）
    ├── shaanxi_collector.py  # v1.0 新增 — SyncRunner 抽象基类化主流程
    ├── preview.py         # 预览模式（不写入）
    ├── status.py          # 状态查询（本地 + ES）
    ├── check.py           # 增量检测
    ├── test.py            # 连通性测试
    ├── utils.py           # ES/MinIO/列表/详情/标题解析
    ├── pdf_parser.py      # 多格式 PDF 解析（A/B/C/D/E/F/G）
    └── city_parsers.py    # 按 city 维度组织的 PDF 解析函数
```

## 模块建构参考

v1.0 同步主流程参考以下 skill 的 SyncRunner 抽象基类化模式：

| 维度 | chongqing-price v0.9 | qingdao-price v0.9 | shaanxi-price v1.0 |
|------|---------------------|---------------------|---------------------|
| 工作单元 | `(source, item, period)` | `list item dict` | `list item dict` |
| 浏览器自动化 | ✓（点击 tab + 选月份） | ✗ | ✗ |
| 数据源 | HTML 多页 | PDF 月报 | PDF 多格式（7 种）|
| 必含字段 `period_start/end/days` | ✗ | ✓ | ✓（v1.0 新增）|
| 多 sub-collector | 35 county × 3 source × 5 cat | — | 8 city × 多期 |
| SyncRunner 钩子 | `_list_work_units / _process_one / _on_unit_done / _compute_unit_key` | 同 | 同 |
| 进度 key | `done_<source>_<period>__<item>` | `detail_url` | `detail_url`（与旧 sync.py 等价）|
| legacy 路径 | `--legacy` 走 write_es.py cmd_sync | `--legacy` 走 sync_legacy.py | `--legacy` 走 sync_legacy.py |

## 依赖

- Python 3.10+
- requests / beautifulsoup4 / pyyaml
- pypdf 6.x（PDF 文本提取，自带旋转处理）
- pdfplumber 0.11+（仅 Type G 商洛用）
- boto3（MinIO S3 兼容）
- elasticsearch（ES 8.x 兼容）
- **gov-price-etl skill**（部署在 `~/.openclaw/workspace/skills/gov-price-etl`）— 强依赖：
  - `collectors.base.SyncRunner / LocalProgressStore / SignalHandler`
  - `collectors.client.fetch_html / download_file / upload_to_minio / get_es_client / get_s3_client`
  - `mappings.build_ods_mapping / build_progress_mapping`（已包含 period_start/end/days 字段声明）
  - `check_status.write_status_from_check_output`（dashboard 端 history 复用）

## 与 henan-price 的差异

| 维度 | henan-price | shaanxi-price |
|------|-------------|---------------|
| 列表页分页 | 4 页 | 5 页 |
| 站点架构 | 单域名 + 单期模板 | 政府站 + 多设区市各异模板 |
| PDF 格式 | 同一模板，3 种表格类型 | 7 种表格类型（每个设区市可能不同）|
| 单位工程 | 全部 `henan_price` 一种 | 按 city 字段区分（`安康`/`汉中`/.../`陕西`）|
| county 粒度 | 全省 18 地市同表 | 按设区市再分县区（如安康 11 个）|
| 期次粒度 | 月刊 | 月刊 / 双月刊 / 季刊 / 省本级月刊 |
| PDF URL | `/BigFileUpLoadStorage/...` | `/protect/.../P020...pdf` |

## 已知问题与改进方向

1. **汉中 breed/spec 缺失**（Type F）：当前只有 code + county + price。可通过解析顶部"材料清单"部分反查补全。
2. **商洛部分行丢失**（Type G）：两列布局中"孤儿价格行"（仅右列有数字）当前被过滤。可加 cross-page 配对。
3. **咸阳 Type E**（county 成组，每组 2 价格）已实现但本期咸阳 PDF 似乎未触发该类型。如未来出现可验证。
4. **worker/installation/rental 页面**（如人工成本、安装工程）当前被自动 skip。

## 变更日志

### v1.2（2026-07-04）— 修复汉中 PDF 仅 page2 解析 BUG

**问题**：汉中 PDF 共 52 页，page 2-4 是 F 布局（county × 价格表），page 5-52 是**汉中市本级价格表**（无 county 分布）。原 `parse_hanzhong` 只识别 F 布局，导致 5 期每期仅 30 条入库（page 2 的 6 materials × 5 county ≈ 30），其余 47 页全部漏掉。

**根因**：
- page 5-52 是 H 布局：「编 码 名 称 规格型号 单位 除税价格（元）含税价格（元）」表头 + 顶部材料清单 + 底部价格区，无 county header
- 部分页面（如 page 7, 38）是混合页：上半 B 布局（行内 material+2 价格）+ 下半 H 布局
- 原解析器没识别这两种布局

**修复**：
1. 新增 `_parse_type_H(text)` — 识别「价格表头 + 顶材料清单 + 底除税/含税 2 列」结构
   - 从 raw_lines 中抽材料（按 code 起头收集后续行至下一个 code 或 category）
   - 从 header 后抽价格（每行 1-2 个浮点数）
   - 一一对应配对，生成 MaterialRow
2. `parse_hanzhong` 重构为多布局并行 + 去重：
   - F 布局（≥5 county hits）→ `_parse_type_F`
   - 否则 `_parse_type_B` + `_parse_type_H` + `_parse_type_D` 合并
   - 按 `(code|breed|spec|unit|county)` 去重

**验证**：
- 5 期 dry-run 总计 5704 条（之前 141 条），每期 1100+ 条
- 实际入库：1169/1141/1123/1137/1134 条
- 已清理 ES 旧数据（141 条）+ progress（10 条）+ 本地进度（5 条）后重跑入库
- 单一期入 ES + 进度 + MinIO 完整

**遗留问题**：
- 部分材料行被 pypdf 拆成多行（数字独立成行如 `3 / 0 / m / m`），spec 拼接后含空格但数据可入库
- B 布局有少数页脚数字被误识别为价格（已在 H 布局配对时去重）
- county 分布数据少（27-30 条/期）因 page 4 county header 被布局打乱

### v1.1（2026-07-03）— 修复 _id 静默去重 bug
**问题**：`_id = MD5(period+code+city+county)`，当同 `code+city+county` 出现在 PDF 不同行（不同 breed/spec/unit）时，被 ES bulk `index` 操作 upsert 静默去重。导致咸阳/铜川/榆林 每期丢 ~50-130 条 (道友发现的全不全的根因)。

**修复**：
1. `_doc_id` 加入 `breed / spec / unit / county` 拼接：`MD5(period|code|breed|spec|unit|city|county)`
2. `_process_one` 加源文档去重（PDF parser 偶尔重复识别同一行），用 `seen_keys` 集合
3. 同步 `sync_legacy.py` 旧路径（escape hatch 同样修复）

**验证**：
- 22 期期望条数 == ES 实际条数（ALL MATCH）
- ES 总 32266 条（修复前被去重为 32043，少 223 条；期望应该是 32266）
- 4 期安康 `skipped_image_pdf` 保留为不入库（扫描图像型 PDF）

### v1.0（2026-07-03）— SyncRunner 抽象基类化 + 3 个新字段
- 模块建构参考 `chongqing-price` v0.9 / `qingdao-price` v0.9：sync.py 重写为 `ShaanxiCollector`，继承 `gov_price_etl.collectors.base.SyncRunner`
- 新增字段 `period_start / period_end / period_days`（道友硬要求，2026-07-03），由 `compute_period_dates(period)` 推算
- 4 种 period 格式（月报/月刊/双月刊/季刊）全部支持
- CLI 兼容原 `--year/--period/--latest/--reset/--dry-run`，新增 `--run-id/--max-units/--legacy`
- 旧 `sync.py` 重命名为 `sync_legacy.py`，从 `sync.py` 透传 `fetch_all_periods / PROGRESS_FILE / load_progress` 让 check.py / preview.py / status.py 保持兼容
- 进度 key 仍为 `detail_url`，已入仓的 21 期 ok + 4 期 skipped_image_pdf 天然不重抓

### v0.5（2026-06-26）— 首次入仓
- 25 期 PDF 抓取入 ES，共 30609 条
- 安康 2026.1-4 期是扫描图像 PDF，标 `skipped_image_pdf` 跳过

## 复用参考

若需新增其他省份的工程造价采集 skill：

1. 参考 `henan-price`/`shaanxi-price` 的目录结构和 `commands/utils.py`（ES/MinIO/列表/详情抽取）
2. 各省 PDF 格式差异较大，主要工作集中在 `commands/pdf_parser.py`（新增页面类型 + 解析函数）
3. `commands/sync.py` 的列表抓取/进度/入库逻辑基本可复用，只需调整 `city_patterns` 和 period 解析
4. v1.0 起建议同步主流程用 `SyncRunner` 抽象基类化（参考 `shaanxi_collector.py`），复用 `LocalProgressStore` + `SignalHandler` + `gov_price_etl.collectors.client` 通用工具
5. 必含字段 `period_start / period_end / period_days` 已纳入 `gov_price_etl.mappings._ODS_BASE_FIELDS`，新增省份零成本继承