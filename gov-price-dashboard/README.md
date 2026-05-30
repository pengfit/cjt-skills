# 政府材料价格看板

政务数据材料价格查询与可视化平台，基于 Elasticsearch 数据源，支持多维度筛选、价格趋势分析、规格解析质量监控、数据溯源追踪。

> **前台访问**：http://localhost:5300
> **API 文档**：http://localhost:5200/docs

## 功能界面

| 标签页 | 说明 |
|--------|------|
| **产品列表** | 多维筛选搜索，含关键词/省市县/分类/价格区间筛选，结果分页排序，attr 标签显示 |
| **数据分布** | 省份/城市数据量分布图，7 天未更新标红提醒 |
| **类别分析** | 分类下钻，含品种列表和规格价格明细 |
| **数据入仓** | ODS→DWD→DWS 同步链路状态、各城市抓取进度监控 |
| **规格规则库** | 规格解析规则查询、添加、测试；AI 生成规则建议；DWD 抽样质量报告 |
| **分类规则库** | 品种→分类映射规则管理，Jaccard 召回，批量 AI 分类 |

## 技术栈

| 层级 | 技术 |
|------|------|
| 后端 | Python 3 + FastAPI + Elasticsearch |
| 前端 | Vue 3 + Vite + ECharts + Axios |
| 数据源 | ES 本地（`http://localhost:59200`）|
| 规则库 | SQLite（`rules_vec.db`）+ 向量检索（parse_spec）|
| AI 集成 | OpenClaw LLM（规格解析规则生成 / 品种批量分类）|

## 快速启动

```bash
cd skills/gov-price-dashboard
./start.sh
```

```bash
./start.sh status   # 查看状态
./start.sh stop     # 停止
./start.sh restart  # 重启
```

## 前台功能详解

### 产品列表 — 多维筛选

- **关键词搜索**：品种名模糊匹配，短词（≤2字符）自动 fuzzy 容错
- **省份 / 城市 / 区县**：三级下拉联动，实时数据量提示
- **价格区间**：`price` 单价范围筛选
- **分类**：33 个分类（管材管件/钢材/水泥/石材/电气材料…）
- **单位**：件/米/吨/立方米等
- **搜索历史**：本地记录最近 10 条关键词

### attr 规格字段（38 个）

| 字段 | 说明 | 示例 |
|------|------|------|
| `thickness` | 厚度/壁厚 | `2mm`, `4.5mm` |
| `length` | 长度 | `1200mm` |
| `width` | 宽度 | `400mm` |
| `height` | 高度 | `600mm` |
| `height_range` | 高度范围 | `H100~H250` |
| `diameter` | 管径/口径 | `DN125~250`, `Φ700` |
| `cross_section` | 电缆截面 | `2.5mm²`, `240mm²` |
| `cores` | 芯数 | `3芯`, `4芯` |
| `voltage` | 电压 | `220`, `380` |
| `current` | 电流 | `16`, `32` |
| `material` | 材质 | `PVC`, `PE`, `铸铁` |
| `color` | 颜色 | `白`, `灰` |
| `grade` | 等级/牌号 | `C30`, `Q235B`, `P.O42.5R` |
| `asphalt_type` | 沥青类型 | `AC-13`, `SBSAC-13` |
| `cement_content` | 水泥含量 | `5%` |
| `channels` | 通道数 | `8路` |
| `doors` | 门数 | `2门` |
| `drain_type` | 排水类型 | `下出水`, `地排水` |
| `installation_type` | 安装类型 | `台下盆`, `立柱盆` |
| `inlet_type` | 进水类型 | `后进水`, `侧进水` |
| `fiber_core` | 光纤芯数 | `12芯`, `24芯` |
| `length_range` | 长度范围 | `2~4m` |
| `media` | 介质 | `水`, `气` |
| `range` | 量程 | `0~100MPa` |
| `output` | 功率 | `50W`, `100W` |
| `cable_length` | 线缆长度 | `5m`, `10m` |
| `temperature` | 温度 | `70℃` |
| `temp_range` | 温度范围 | `-10℃~50℃` |
| `humidity_range` | 湿度范围 | `0~100%RH` |
| `pressure` | 压力等级 | `PN16`, `PN25` |
| `ring_stiffness` | 环刚度 | `SN8` |
| `ip_rating` | 防护等级 | `IP65` |
| `inner_diameter` | 内径 | `DN100` |
| `wall_thickness` | 壁厚 | `5mm` |
| `surface` | 表面处理 | `热镀锌` |
| `fire_rating` | 耐火等级 | `A级` |

### 规格规则库

- **查询**：分页+属性过滤+分类过滤+关键词搜索（pattern/note/code）
- **AI 生成规则**：`fix-case` 端点调用 OpenClaw LLM，从 spec 文本和期望输出推断解析规则
- **规则验证**：预览模式下模拟解析，confirm 模式写入 rules_vec.db
- **分类清洗**：点击分类清洗按钮触发 DWD→DWS 批量重算

### 分类规则库

- **品种分类管理**：查询/添加/删除 breed→category 映射规则
- **Jaccard 召回测试**：基于文本相似度推断未知品种分类
- **批量 AI 分类**：`classify-breed-batch` 端点，一次最多 50 条品种，AI 批量推断分类并写入规则库

## API 详细说明

### 搜索

```bash
# 产品搜索
GET /api/search
  ?keyword=钢管          # 关键词（≤2字符自动fuzzy）
  ?province=陕西          # 省份
  ?city=西安              # 城市
  ?county=雁塔区          # 区县
  ?category=管材管件      # 分类
  ?unit=米                # 单位
  ?price_min=10           # 最低价
  ?price_max=100          # 最高价
  ?page=1                 # 页码（默认1）
  ?page_size=20           # 每页条数（默认20，最大100）
```

### 分类分析

```bash
# 类别明细（省份分布+热门品种+价格区间）
GET /api/stats/category-detail?category=管材管件

# 类别动态价格区间（按分位数分5段）
GET /api/stats/category-price-ranges?category=管材管件

# 类别品种列表（分页）
GET /api/stats/category-breeds?category=管材管件&page=1&page_size=50

# 品种规格明细（单位→规格分层）
GET /api/stats/breed-detail?category=管材管件&breed=PE管&page=1&page_size=50
```

### 数据溯源

```bash
# 单城市溯源
GET /api/stats/provenance?city=xian

# 全部城市溯源
GET /api/stats/provenance?city=all

# 全部城市抓取进度汇总
GET /api/stats/scrape-progress-all

# 单城市抓取进度
GET /api/stats/scrape-progress?city=xian
```

### 规格质量

```bash
# 质量报告（抽样+分类覆盖率）
GET /api/stats/spec-quality?city=xian&sample_size=50

# 规则预览（不写入）
POST /api/stats/spec-quality/fix-case
{
  "city": "xian",
  "spec": "PV C25 2.0mm",
  "expected": {"material": "PVC", "grade": "25", "thickness": "2.0mm"},
  "confirm": false,
  "breed": "电工套管",
  "category": "电气材料"
}

# 规则确认（写入）
POST /api/stats/spec-quality/fix-case
{
  "city": "xian",
  "spec": "PV C25 2.0mm",
  "expected": {"material": "PVC", "grade": "25", "thickness": "2.0mm"},
  "confirm": true,
  "suggestions": [{"attr": "material", "note": "PVC材质", "pattern": "PVC", "code_block": "result['material'] = 'PVC'\n"}],
  "breed": "电工套管",
  "category": "电气材料"
}

# 触发分类清洗（DWD→DWS）
POST /api/stats/spec-quality/refresh-category
{"city": "xian", "category": "电气材料"}
```

### 批量品种分类

```bash
POST /api/stats/spec-quality/classify-breed-batch
{"breeds": ["PE给水管", "PVC穿线管", "球墨铸铁管"], "city": "xian"}
```

## 支持城市

| 城市 | DWS 索引 | 进度追踪 |
|------|---------|---------|
| 西安 | `dws_xian_price` | 6 区县（阎良区/临潼区/高陵区/鄠邑区/蓝田县/周至县） |
| 四川 | `dws_sichuan_price` | 21 地市/自治州 |
| 重庆 | `dws_chongqing_price` | 35 区县 |
| 济南 | `dws_jinan_price` | 41 分类目录 |
| 日照 | `dws_rizhao_price` | 3 类别（建设工程材料/园林绿化/区县工程） |

## ES 索引

| 城市 | ODS 层 | DWD 层 | DWS 层 | 进度索引 |
|------|--------|--------|--------|---------|
| 西安 | `ods_material_xian_price` | `dwd_xian_price` | `dws_xian_price` | `ods_material_xian_price_sync_progress` |
| 四川 | `ods_material_sichuan_price` | `dwd_sichuan_price` | `dws_sichuan_price` | `ods_material_sichuan_price_sync_progress` |
| 重庆 | `ods_material_chongqing_price` | `dwd_chongqing_price` | `dws_chongqing_price` | `ods_chongqing_price_progress` |
| 济南 | `ods_material_jinan_price` | `dwd_jinan_price` | `dws_jinan_price` | `ods_material_jinan_price_sync_progress` |
| 日照 | `ods_material_rizhao_price` | `dwd_rizhao_price` | `dws_rizhao_price` | `material_rizhao_price_sync_progress` |

## 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `ES_HOST` | `http://localhost:59200` | Elasticsearch 地址 |
| `ES_INDEX` | `dwd_xian_price` | 默认查询索引 |

## 相关项目

- **gov-price-etl**：`/skills/gov-price-etl/` — ODS → DWD → DWS 数据入仓与 ETL
- **xian-material-price** — 西安数据同步
- **sichuan-price** — 四川数据同步
- **chongqing-price** — 重庆数据同步
- **jinan-price** — 济南数据同步
- **rizhao-price** — 日照数据同步