---
name: shanxi-price
description: "山西工程造价材料信息采集,从 `https://zjt.shanxi.gov.cn/fwzl/bzdexx/jgxx/` 抓取数据,按期期刊跟踪,同步至 Elasticsearch。范围：山西省（含 11 市）。时间方法:2026 年(道友要求,默认仅入库 2026 年期)。"
---

# 山西 · 工程造价材料信息采集

> 省份:山西 · 进度模式:`period` · 时间方法:2026 年起 · 6 期/年（双月刊，1-2月/3-4月/...）

## 数据流

```
源站: https://zjt.shanxi.gov.cn/fwzl/bzdexx/jgxx/
   ↓ (commands/sync.py → ShanxiCollector)
ods_material_shanxi_price
   ↓ (<skills>/gov-price-etl cli/etl.py --city shanxi)
dwd_shanxi_price
   ↓ (cli/sync_dws.py --city shanxi --mode quick)
dws_shanxi_price
```

## 快速开始

```bash
cd <skills>/shanxi-price
./run.sh preview          # 预览数据(不写 ES)
./run.sh sync             # 增量同步(默认仅 2026)
./run.sh sync --latest    # 只同步最新一期
./run.sh sync --all       # 同步所有未入仓的期(不限年份)
./run.sh status           # 查看状态
./run.sh check            # 增量检测(不写入)
./run.sh test             # 测试 ES / MinIO / 源站连通性
```

## 命令清单

| 命令 | 脚本 | 说明 |
|------|------|------|
| `preview` | `commands/preview.py` | 预览数据（不写 ES、不传 MinIO） |
| `sync` | `commands/sync.py` | 同步到 ES + MinIO（v1.0 Collector 路径） |
| `status` | `commands/status.py` | 查看 ES / MinIO 状态 |
| `test` | `commands/test.py` | ES + MinIO + 源站连通性 |
| `check` | `commands/check.py` | 增量检测(对比 ES vs 源站最新日期) |

## sync 关键参数

- `--period` — 指定 period（如 `2026.3-4月`）
- `--year` — 默认 `config.sync.default_year=2026`；传 `0` 表示不限
- `--all` — 同步所有未入仓的期，忽略 `--year` 过滤
- `--latest` — 只同步最新一期
- `--reset` — 重置本地进度（ES progress 保留）
- `--dry-run` — 预览，不写入
- `--run-id` — 指定 run_id（默认 `sx_run_YYYYMMDD_HHMMSS`）
- `--max-units` — Collector 路径：只跑前 N 个工作单元（验证用）

## ES 索引

| 索引 | 说明 |
|------|------|
| `ods_material_shanxi_price` | 原始抓取数据（主数据） |
| `ods_material_shanxi_price_sync_progress` | 同步进度（每期一条） |
| `dwd_shanxi_price` | ETL 清洗层 |
| `dws_shanxi_price` | 看板查询层 |

## 周期命名（道友指定）

源站标题格式：`YYYY年M-N月山西省各市常用建设工程材料价格信息(含税|不含税)`
双月刊：`1-2月 / 3-4月 / 5-6月 / 7-8月 / 9-10月 / 11-12月`（6 期/年）。

进度模式 `period` 用 `YYYY.M-N月`（如 `2026.3-4月`）作为业务标识：

  - `period`:        `2026.3-4月`
  - `period_start`:  `2026-03-01`
  - `period_end`:    `2026-04-30`
  - `period_days`:  `61`（M~N 月累计天数）

## 数据获取细节

山西省住建厅站点为**纯 HTML 静态列表**（无 AJAX、无鉴权）：

- **列表端点**：`GET /fwzl/bzdexx/jgxx/index.shtml`（首页）/ `index_2.shtml` ... `index_9.shtml`
  - 总页数从首页 JS 解析：`var countPage = 9; var dataCount = "180";`
  - 每页 20 条，9 页共 180 条（最近约 2.5 年）
- **列表项**：
  ```html
  <li>
    <p><a class="text_p" href='./202605/t20260521_10131405.shtml' title='2026年3-4月山西省各市常用建设工程材料价格信息(不含税)'>...</a></p>
    <a class="text_span" href='./...' title='...'><span>2026-05-21</span></a>
  </li>
  ```
- **详情页 PDF**：
  ```html
  <a href="./P020260521595406680195.pdf"
     OLDSRC="/protect/P0202605/P020260521/P020260521595406680195.pdf"
     download="2026年3-4月山西省各市常用建设工程材料价格信息(不含税).pdf">
  ```
  优先用 `OLDSRC`（/protect/... 路径，下载稳定），fallback 到 `href`（./P...pdf，相对路径）。

## 过滤规则（道友要求）

山西站混杂 6 类文章，按以下规则过滤：

| 类别 | 关键词 | 处理 |
|------|--------|------|
| **山西省各市常用建设工程材料价格信息** | 含「建设工程材料价格信息」且**不含**「勘误」 | ✅ 收录 |
| **太原市常用建设工程材料价格信息**（勘误版本） | 含「勘误」 | ❌ 排除（道友要求） |
| **太原市建设工程主要材料价格走势图** | 含「走势图」 | ❌ 排除（图表类，非价格表） |
| **太原地区常用园林苗木秋季价格信息** | 含「园林苗木」 | ❌ 排除（园林非建筑工程材料） |
| 2025 年及更早数据 | 不含「2026」 | ❌ 排除（道友要求 2026 年起） |

关键词配置在 `config.yml.sync.include_keywords` / `exclude_keywords`，可调。

## 配置（config.yml）

```yaml
es:
  host: http://localhost:59200
  ods_index: ods_material_shanxi_price
  progress_index: ods_material_shanxi_price_sync_progress
  batch_size: 1000

minio:
  endpoint: http://localhost:9000
  access_key: minioadmin
  secret_key: minioadmin123
  bucket: gov-price-data
  prefix: shanxi-price
  secure: false

site:
  base_url: https://zjt.shanxi.gov.cn
  list_path: /fwzl/bzdexx/jgxx/
  max_pages: 9
  page_size: 20
  user_agent: "Mozilla/5.0 ..."
  timeout_sec: 30
  referer: https://zjt.shanxi.gov.cn/fwzl/bzdexx/jgxx/

sync:
  default_year: 2026
  include_keywords:
    - 建设工程材料价格信息
  exclude_keywords:
    - 勘误
    - 勘误表
    - 走势图
    - 园林苗木
```

## PDF 解析（best-effort）

山西 PDF 单期一份省级文件（覆盖 11 市），当前采用通用 table 提取（参考 guizhou）：

- pdfplumber `extract_tables()` 全表扫
- 每行最右数字格当 price，前一格当 unit，前面按顺序填 breed/spec/remark
- 解析失败：仍插 1 条 `parse_status='unparsed'` 的 placeholder（标识已归档）

> 提示：首次跑后看 `commands/preview.py` 输出，若 PDF 版式与默认解析不匹配，需在 `commands/sync.py` 的 `parse_pdf_tables` 调整关键字或行结构。

## 项目结构

```
shanxi-price/
├── run.sh
├── config.yml
├── SKILL.md
├── README.md
└── commands/
    ├── check.py
    ├── preview.py
    ├── shanxi_collector.py    # v1.0 SyncRunner 化（默认）
    ├── status.py
    ├── sync.py                # 含 fetch_all_periods / parse_list_page / parse_detail_page
    ├── test.py
    └── utils.py
```

## 依赖

- Python 3
- requests / beautifulsoup4 / pyyaml / elasticsearch
- pdfplumber
- gov_price_etl（本 workspace 内，公共 ETL 层）

## 已知限制与 TODO

### v1.0 已交付
- ✅ 列表抓取（9 页 × 20 = 180 条,首页 JS 自动判页数）
- ✅ 标题过滤：2026 年 + `建设工程材料价格信息` + 排除 `勘误` / `走势图` / `园林苗木`
- ✅ 期号解析：`YYYY年M-N月` → `period_start / period_end / period_days`
- ✅ 详情页 PDF 链接：`href` 优先（200 OK） / `OLDSRC` 兜底（实测 404）
- ✅ PDF 下载 + 上传 MinIO（21MB/期,~60s）
- ✅ ES 占位入仓（`parse_status='unparsed'`）+ 本地进度 + ES progress 同步

### v1.1 已交付（2026-07-17）
- ✅ **OCR 接入** — rapidocr_onnxruntime + pdf2image
- ✅ **结构化解析** — 11 市 × N 材料的宽表矩阵抽取
  · 按 y 容差 15px 分行，x 容差 30px 对齐价格/规格/单位
  · 跨 11 市中位数裁剪滤 OCR 极端误读（如 `23376.22` 滤成 `3376.22`）
  · 价格范围 0.01 ~ 9999
  · section header / 页码 / 单位 词过滤作为材料名
- ✅ **per-page timeout** — `_PAGE_TIMEOUT = 60s`，子线程 + Future.result(timeout)，
  超时跳过该页不中断后续
- ✅ **import 旁路** — `commands/import_remaining.py`，绕过 collector 框架
  直接逐期独立处理（v1.1.1 用）

### v1.1 实测数据（2026-07-17 14:55）
ES `ods_material_shanxi_price` 共 **38,637 条**:
- `2026.3-4月`（不含税 + 含税）: 25,681 条,11 市全部命中,每市 1500~2800 条
- `2026.1-2月`（不含税）: 12,956 条,11 市全部命中,每市 900~1400 条
- `2026.1-2月`（含税）: **未入仓**（PDF 已上传 MinIO 42MB,OCR 阻塞）

### v1.1.1 worklist
- 🚧 **rapidocr 在 Apple Silicon + CoreML 上 hang** — `1-2月含税 PDF` 某页触发
  ONNX Runtime native thread 死锁。多次路径（collector / 独立 script /
  30s/页超时 / fresh subprocess）都未能穿透。
  **workaround**（优先级 p1）：
  ```python
  import onnxruntime as ort
  ort.set_default_logger_severity(3)
  # 显式走 CPUExecutionProvider,避开 CoreML:
  e = RapidOCR(use_cuda=False, use_dml=False, use_coreml=False)
  ```
  或换 pytesseract / PaddleOCR 底座。

### v1.1.1 已交付（2026-07-17 16:30）
- ✅ **PDF 旋转 90° CCW** — 原 PDF 是横版扫描成竖版, 旋转后 layout 变标准宽表
  (header 行: 序号|材料名称|规格型号|单位|11市, data 行: 1材×11市)。
  ⚠️ 旋转版不能抓数据行里的 unit (x=904 列 OCR 大部分为空), 需补第 2 OCR 路径。
- ✅ **双 OCR 路径** — parse_pdf_tables 每页走 2 次 OCR:
  1. 旋转后抓 breed/spec/11 市价格
  2. 原始方向抓「单位」行 + 「材料名称」行, 按 x 位置配对 → breed→unit 映射表
  data 行 unit 为空时查表补齐 (实测覆盖率 64% → 75%)
- ✅ **OCR 噪声单位清洗** — `_clean_unit()` 归一 `m3→m³` `㎡→m²` `m→m³`
  `m?→m³` `100m/100ms/100ml/之副/之剖` → 空
- ✅ **材料名→单位推断** — `_UNIT_INFERENCE` 关键词表 (14 类: 钢/砂石/砖/木/玻/涂料/
  电线/苗木/管/佝件/门/灯具/阀), 推断 fallback 补 5-10% 空 unit

### v1.1.2 已交付（2026-07-17 16:55）— 增量防退化
- ✅ **`commands/update_units.py`** — 后处理脚本 (update_by_query + bulk):
  - step 1: `m` → `m³` (归一 OCR 噪声)
  - step 2: `m?` → `m³`
  - step 3: 空 unit → `_infer_unit(breed)` 扫 + bulk 补齐
  - step 4: 残余噪声 (`100m`/`100ms`/`之副`) → 清空等下次 OCR
  - 用法: `python3 commands/update_units.py` / `--dry-run` / `--step N`
- ✅ **`test.py` 加 unit 覆盖率断言** — 阈值默认 80% (可调 `SHANXI_UNIT_COVERAGE_MIN`),
  低于阈值打印警告 + 修复提示; 设 `SHANXI_STRICT=1` 则 exit 2 (适合 cron)
- ✅ **parse_pdf_tables 加 unit_map 命中日志** — 每页 print `unit_map 命中 X/Y 行`,
  可观测 dual-OCR 是否生效

### 已知 hang 风险（推荐增量路径）
- ⚠️ **Collector 长寿命问题** — `shanxi_collector.py` 多次跨 PDF hang (CoreML native thread).
  **推荐**: 增量跳过 collector, 直接用 `commands/import_remaining.py`.
  - 独立 Python 进程, 无长寿命状态
  - 每期约 5 min (双 OCR 含进去 ~6 min)
  - 4 期总 ~25 min
  - 不受 CoreML 死锁影响 (page 5-10 仍能走完)

## 增量 SOP（防踩坑）

```bash
cd ~/.openclaw/workspace/cjt/skills/shanxi-price

# 1. 预览（不写）
./run.sh preview

# 2. 连通 + 覆盖率自检
./run.sh test                    # 看 unit 覆盖率是否 ≥ 80%

# 3. 入仓（跳过 collector, 走 import_remaining）
python3 commands/import_remaining.py --run-id sx_$(date +%Y%m%d_%H%M%S)

# 4. 后处理 (归一 + 补空 unit)
python3 commands/update_units.py  # 全跑; 或 --step 1 2 3 4 分步

# 5. 验证
./run.sh test                    # unit 覆盖率应 80%+
./run.sh status                  # 各期 + MinIO 看总览
```

## 增量踩坑记录（2026-07-17 当天修复）
1. **OCR 抓不到数据行 unit** → 双 OCR 路径 (旋转 + 原始) + _infer_unit fallback
2. **OCR 噪声单位** (m / m? / 100m) → `_clean_unit` + update_units 归一
3. **Collector long-running hang** → 改用 import_remaining.py 独立进程
4. **LocalProgressStore 不写盘** → collector `_on_unit_done` 加 `progress.save()`
5. **Mapping strict 护 `parse_status`** → shanxi_collector `_ensure_indices` 加
   `city_extension` + PUT mapping
6. **OLDSRC 路径 404** → `parse_detail_page` 主走 `href` (相对路径), OLDSRC 兑底

### v1.2 候选
- 多市拆分: DWD 层按 city 拆出明细表
- 含税标识: `is_tax` 已在 ETL mapping 预留,补到 sync.py 填充
- CoreML hang 根治: 换 pytesseract / PaddleOCR (v1.1.2 是临时绕过)

## 相关

- `<skills>/gov-price-dashboard` — 看板（查 DWS 数据）
- `<skills>/gov-price-etl` — ETL 公共层
- `<skills>/guizhou-price` — 参考模板（同 v1.0 SyncRunner 结构）
- `<skills>/shaanxi-price` — 同省西北参考（注意：陕西 ≠ 山西）