---
name: shaanxi-price
description: "陕西工程造价材料信息采集：从 js.shaanxi.gov.cn 抓取全省 10 个设区市 + 省本级的材料价格 PDF（覆盖 2026 年），存到 minio 并入库到 ods_material_shaanxi_price。"
---

# shaanxi-price

陕西工程造价材料信息采集 Skill。从 `js.shaanxi.gov.cn`（陕西省住房和城乡建设厅）的 **造价信息** 栏目抓取每月/每期 PDF 附件：覆盖省本级《陕西工程造价信息》和 9 个设区市《XX 建设工程造价信息》。流程参考 `henan-price`：列表 → 详情 → PDF → MinIO → ES 幂等写入。

## 数据流

```
js.shaanxi.gov.cn/sy/yw/zjglfw/zjxx/  (列表 5 页, 96 条)
       ↓ fetch
列表 (25 期 × 2026年) → 详情页 → PDF 链接
       ↓ download + upload
MinIO: gov-price-data/shaanxi-price/{period}_{name}/source.pdf
       ↓ pdfplumber / pypdf 多格式解析
长表 (材料 × 规格 × 单位 × 设区市/县区 × 价格)
       ↓ bulk_index
ods_material_shaanxi_price
```

## 快速启动

```bash
cd skills/shaanxi-price

./run.sh test                       # 测试连通性（ES + MinIO + 源站 + PDF 下载）
./run.sh preview                    # 预览前 3 期（不写 ES、不传 MinIO）
./run.sh preview --limit 25         # 预览全部 2026 期
./run.sh check                      # 增量检测（不写入）
./run.sh status                     # 查看同步状态
./run.sh status --es                # 查看 ES 索引详情

./run.sh sync --dry-run             # 预览同步（不写入）
./run.sh sync --latest              # 同步最新一期
./run.sh sync --year 2026           # 同步所有 2026 年期（默认）
./run.sh sync --period 2026.5期     # 同步指定 period
./run.sh sync --period 2026.5月
./run.sh sync --reset               # 重置进度，从头开始
```

## 数据源

- **列表页**：`https://js.shaanxi.gov.cn/sy/yw/zjglfw/zjxx/index.html` (含分页 1-5)
  - `index.html` + `index_1.html` ... `index_4.html`，共 96 条
- **详情页**：`/sy/yw/zjglfw/zjxx/{YYYYMM}/t{YYYYMMDD}_{uuid}.html`
- **PDF 附件**：`/sy/yw/zjglfw/zjxx/{YYYYMM}/P020{YYMMDD}{NNN}.pdf`
- **标题格式**：
  - 设区市：`设区市造价信息---《{city}建设工程造价信息》{YYYY}年第{N}期[（季刊/双月刊）]`
  - 省本级：`{YYYY}年{M}月材料信息价`
- **period 编码**：
  - 设区市：`2026.{N}期` 或 `2026.{N}期(季刊/双月刊)`
  - 省本级：`2026.{M}月`

## 覆盖范围

| city | 频次 | 2026 期数 |
|------|------|-----------|
| 安康 | 月刊 | 5 期 |
| 汉中 | 月刊 | 5 期 |
| 咸阳 | 月刊 | 3 期（部分期尚未发布）|
| 渭南 | 双月刊 | 2 期 |
| 铜川 | 月刊 | 2 期 |
| 榆林 | 月刊 | 2 期 |
| 商洛 | 季刊 | 1 期 |
| 陕西（省本级）| 月刊 | 5 期（每月）|
| 西安、宝鸡、延安 | - | 源站未在 2026 年发布（由 xian-price / 其他渠道单独采集）|

> ⚠️ 用户要求**只抓 2026 年数据**，`--year 2026` 默认开启。

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
| `period` | 周期（如 `2026.5期`、`2026.5月`、`2026.1期(季刊)`） |
| `province` | `陕西` |
| `city` | 设区市名（`安康`/`汉中`/...）或 `陕西`（省本级） |
| `county` | 县/区名（如 `汉滨区`/`南郑`），省本级和单价表为空 |
| `update_date` | 发布日期（列表上的 `YYYY-MM-DD`） |
| `create_time` | 入库时间 |
| `source_pdf` | MinIO 对象 key |
| `source_url` | 详情页 PDF URL |

## PDF 格式自动识别

陕西各设区市 PDF 格式不统一，本 skill 实现 **7 种页面类型自动识别**：

| Type | 描述 | 出现的设区市 | 解析策略 |
|------|------|--------------|----------|
| A | 多县区表（除税价 + 含税价 各一行） | 安康 | 11 counties × N materials |
| B | 单价表 6 列（除税价 + 含税价） | 陕西province / 渭南 / 咸阳 / 榆林 | 1 row × 1 material |
| C | 单价表 7 列（含税+除税+税率，列序不同） | 铜川 | 1 row × 1 material |
| D | 多县区表（仅除税价一行） | (保留) | 同 A 但无含税价 |
| E | 多县区表（county 成组，每组 2 价格） | 咸阳 last section | (保留) |
| F | 汉中县区表（自定义：顶材料清单 + 中间表头 + 底价格行） | 汉中 | 10 counties × M materials |
| G | 商洛（pdfplumber layout-aware） | 商洛 | 仅保留有完整材料信息的行 |

每种类型在 `pdf_parser.py` 有独立解析函数 + 单元测试入口。

### 解析限制

- **商洛 PDF** 使用两列布局，pdfplumber 提取的部分行只有价格（前一行材料）；当前只保留 breed+spec 都不为空的行，因此只入库约 13 条/期。如需全量，需引入 cross-page material/price 配对逻辑。
- **汉中 PDF**（Type F）当前仅记录 code + county + price（breed/spec/unit 为空）。原因是汉中 PDF 把材料表头与价格表拆在不同位置，跨段配对容易错位。可后续增强。
- **铜川 PDF**（Type C）包含税率字段，暂未入库（设计上未要求）。

## ES 索引

| 索引 | 说明 |
|------|------|
| `ods_material_shaanxi_price` | 材料价格数据（主数据） |
| `ods_material_shaanxi_price_sync_progress` | 同步进度（每期一条记录） |

### 幂等写入

```
_id = MD5(period + code + breed + spec + city + county)
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
    ├── sync.py        # 同步主程序（列表→详情→PDF→MinIO→ES）
    ├── preview.py     # 预览模式（不写入）
    ├── status.py      # 状态查询（本地 + ES）
    ├── check.py       # 增量检测
    ├── test.py        # 连通性测试
    ├── utils.py       # ES/MinIO/列表/详情/标题解析
    └── pdf_parser.py  # 多格式 PDF 解析（A/B/C/D/E/F/G）
```

## 依赖

- Python 3
- requests / beautifulsoup4 / pyyaml
- pypdf 6.x（PDF 文本提取，自带旋转处理）
- pdfplumber 0.11+（仅 Type G 商洛用）
- boto3（MinIO S3 兼容）
- elasticsearch（ES 8.x 兼容）

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

## 复用参考

若需新增其他省份的工程造价采集 skill：

1. 参考 `henan-price`/`shaanxi-price` 的目录结构和 `commands/utils.py`（ES/MinIO/列表/详情抽取）
2. 各省 PDF 格式差异较大，主要工作集中在 `commands/pdf_parser.py`（新增页面类型 + 解析函数）
3. `commands/sync.py` 的列表抓取/进度/入库逻辑基本可复用，只需调整 `city_patterns` 和 period 解析
