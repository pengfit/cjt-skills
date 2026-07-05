# 材价通 - 政府材料价格看板

政务数据材料价格查询与可视化平台，基于 Elasticsearch 数据源，支持 17 个省/市的多维度筛选、价格趋势分析、规格解析质量监控、数据溯源追踪。

> **前台访问**：http://localhost:5300
> **API 文档**：http://localhost:5200/docs

## 功能界面（侧栏导航）

| 标签页 | 路由 | 说明 |
|--------|------|------|
| 🛸 驾驶舱 | `?tab=cockpit` | 全局仪表盘，数据概览卡片 + 省份/城市/分类分布图 |
| 📋 全部数据 | `?tab=list` | 多维筛选搜索，关键词/省市县/分类树/价格区间筛选，分页排序，属性标签展开详情 |
| 📁 全部类别 | `?tab=category` | 类别下钻分析，品种列表 + 规格价格明细 |
| 📊 价格分布 | `?tab=dist` | 省份/城市数据量分布图，价格区间分布图表 |
| 🔄 数据同步 | `?tab=sync` | 17 个城市抓取进度监控，ODS→DWD→DWS 同步状态 |
| ❤️ 数据健康 | `?tab=health` | 每日入库量、省份新鲜度、增量异常检测 |
| ⚙️ 规格解析 | `?tab=rules` | 规格规则库查询/添加/测试，DWD 抽样质量报告，AI 规则生成 |
| 🏷️ 分类体系 | `?tab=taxonomy` | 分类树浏览、品种→分类映射规则管理、Jaccard 召回、批量 AI 分类 |

## 技术栈

| 层级 | 技术 |
|------|------|
| 后端 | Python 3 + FastAPI + Elasticsearch |
| 前端 | Vue 3 + Vite + ECharts 6.x + Axios |
| 数据源 | Elasticsearch（`ES_HOST`，默认 `http://localhost:59200`）|
| 规则库 | SQLite（`breed_spec_rules.db` + `breed_category_rules.db`）|
| AI 集成 | Dify workflow API（规格解析 / 品种批量分类 / 分类推断）|

## 项目结构

```
gov-price-dashboard/
├── start.sh                  # 一键启动/停止/重启/状态
├── README.md
├── SKILL.md
├── api/
│   ├── main.py               # FastAPI 后端（搜索/统计/同步进度接口）
│   ├── requirements.txt
│   ├── skill_registry.py     # Skill 注册中心（自动扫 skill.yml）
│   └── routes/
│       ├── provenance.py     # 数据溯源 + 规格解析 + 分类体系路由
│       └── prompts.yml       # AI prompt 模板
├── frontend/
│   ├── package.json
│   ├── vite.config.js
│   └── src/
│       ├── App.vue           # 主布局
│       ├── composables/      # 可复用逻辑
│       └── components/       # 50+ Vue 组件
│           ├── layout/       # Sidebar / TopBar
│           ├── CockpitView.vue
│           ├── DataHealthView.vue
│           ├── DataProvenanceView.vue
│           ├── ScrapeView.vue
│           ├── SyncCard.vue
│           ├── SpecQualityPanel.vue
│           ├── CategoryTreeBrowser.vue
│           └── ...
└── docs/
```

## 快速启动

```bash
cd skills/gov-price-dashboard
./start.sh           # 启动
./start.sh status    # 查看状态
./start.sh stop      # 停止
./start.sh restart   # 重启
```

## 支持城市（17 个）

| 城市 | Province | progress_mode | 数据源类型 | DWS 索引 |
|------|----------|---------------|-----------|---------|
| 西安 | 陕西 | county | HTML 6 区县 | `dws_xian_price` |
| 四川 | 四川 | catalogue | ASP.NET 21 地市 | `dws_sichuan_price` |
| 重庆 | 重庆 | county | Browser 35 区县 + 3 source | `dws_chongqing_price` |
| 济南 | 山东 | catalogue | Playwright + REST API 41 目录 | `dws_jinan_price` |
| 日照 | 山东 | catalogue | Playwright + REST 3 tab | `dws_rizhao_price` |
| 菏泽 | 山东 | period | API + HTML + PDF | `dws_heze_price` |
| 河南 | 河南 | period | HTML 4 页 + PDF | `dws_henan_price` |
| 青岛 | 山东 | period | HTML + PDF | `dws_qingdao_price` |
| 海南 | 海南 | period | HTML 10 页 + PDF | `dws_hainan_price` |
| 呼和浩特 | 内蒙古 | period | HTML + PDF | `dws_huhehaote_price` |
| 湖南 | 湖南 | period | HTML 14 页 + PDF（2 类）| `dws_hunan_price` |
| 江西 | 江西 | period | HTML articleList JSON + PDF | `dws_jiangxi_price` |
| 宁夏 | 宁夏 | period | HTML 5 页 + PDF | `dws_ningxia_price` |
| 青海 | 青海 | period | HTML 4 页 + PDF | `dws_qinghai_price` |
| 陕西 | 陕西 | period | HTML 5 页 + 7 种 PDF 格式 | `dws_shaanxi_price` |
| 威海 | 山东 | period | jpage dataproxy + PDF | `dws_weihai_price` |
| 新疆 | 新疆 | county | HTML + xlsx 多 sheet | `dws_xinjiang_price` |

> 新增城市只需在对应 skill 目录添加 `skill.yml`，调用 `POST /api/skill-registry/reload` 即可热加载，无需重启。

## ES 索引全表

| 城市 | ODS 层 | DWD 层 | DWS 层 | 进度索引 |
|------|--------|--------|--------|---------|
| 西安 | `ods_material_xian_price` | `dwd_xian_price` | `dws_xian_price` | `ods_material_xian_price_sync_progress` |
| 四川 | `ods_material_sichuan_price` | `dwd_sichuan_price` | `dws_sichuan_price` | `material_sichuan_price_sync_progress` |
| 重庆 | `ods_material_chongqing_price` | `dwd_chongqing_price` | `dws_chongqing_price` | `material_chongqing_price_sync_progress` |
| 济南 | `ods_material_jinan_price` | `dwd_jinan_price` | `dws_jinan_price` | `material_jinan_price_sync_progress` |
| 日照 | `ods_material_rizhao_price` | `dwd_rizhao_price` | `dws_rizhao_price` | `material_rizhao_price_sync_progress` |
| 菏泽 | `ods_material_heze_price` | `dwd_heze_price` | `dws_heze_price` | `ods_material_heze_price_sync_progress` |
| 河南 | `ods_material_henan_price` | `dwd_henan_price` | `dws_henan_price` | `ods_material_henan_price_sync_progress` |
| 青岛 | `ods_material_qingdao_price` | `dwd_qingdao_price` | `dws_qingdao_price` | `ods_material_qingdao_price_sync_progress` |
| 海南 | `ods_material_hainan_price` | `dwd_hainan_price` | `dws_hainan_price` | `ods_material_hainan_price_sync_progress` |
| 呼和浩特 | `ods_material_huhehaote_price` | `dwd_huhehaote_price` | `dws_huhehaote_price` | `ods_material_huhehaote_price_sync_progress` |
| 湖南 | `ods_material_hunan_price` | `dwd_hunan_price` | `dws_hunan_price` | `ods_material_hunan_price_sync_progress` |
| 江西 | `ods_material_jiangxi_price` | `dwd_jiangxi_price` | `dws_jiangxi_price` | `ods_material_jiangxi_price_sync_progress` |
| 宁夏 | `ods_material_ningxia_price` | `dwd_ningxia_price` | `dws_ningxia_price` | `ods_material_ningxia_price_sync_progress` |
| 青海 | `ods_material_qinghai_price` | `dwd_qinghai_price` | `dws_qinghai_price` | `ods_material_qinghai_price_sync_progress` |
| 陕西 | `ods_material_shaanxi_price` | `dwd_shaanxi_price` | `dws_shaanxi_price` | `ods_material_shaanxi_price_sync_progress` |
| 威海 | `ods_material_weihai_price` | `dwd_weihai_price` | `dws_weihai_price` | `ods_material_weihai_price_sync_progress` |
| 新疆 | `ods_material_xinjiang_price` | `dwd_xinjiang_price` | `dws_xinjiang_price` | `ods_material_xinjiang_price_sync_progress` |

## 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `ES_HOST` | `http://localhost:59200` | Elasticsearch 地址 |
| `ES_INDEX` | `dwd_xian_price` | 默认查询索引 |
| `SKILLS_ROOT` | `~/.openclaw/workspace/skills` | skill.yml 扫描根目录 |
| `CATEGORY_DB` | `../gov-price-etl/data/breed_category_rules.db` | v3 分类库 SQLite 路径 |

## attr 字段说明（37+ 种）

`parse_spec` 把复合规格解析为结构化字段：

| 分类 | 字段 |
|------|------|
| **尺寸** | `thickness` `length` `width` `height` `height_range` `diameter` `inner_diameter` `wall_thickness` `length_range` |
| **电缆** | `cross_section` `cores` `voltage` `current` `fiber_core` `cable_length` |
| **材质** | `material` `color` `grade` `surface` |
| **专业** | `asphalt_type` `cement_content` `channels` `doors` `fire_rating` `ip_rating` |
| **洁具** | `drain_type` `installation_type` `inlet_type` |
| **其他** | `temperature` `temp_range` `humidity_range` `pressure` `ring_stiffness` `media` `range` `output` |

## API 端点概览

### 搜索与筛选

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/search` | 产品搜索（关键词/省市县/分类树/价格区间/分页/排序） |
| `GET` | `/api/filter-options` | 省市区三级联动选项 |
| `GET` | `/api/stats/overview` | 全局概览（总量/省份/城市/分类分布） |

### 分类与品种

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/stats/categories` | 所有产品类别及数据量 |
| `GET` | `/api/stats/category-detail` | 指定类别省份分布+热门品种+规格价格 |
| `GET` | `/api/stats/category-price-ranges` | 指定类别动态价格区间（分位数） |
| `GET` | `/api/stats/category-breeds` | 指定类别去重品种列表（分页） |
| `GET` | `/api/stats/breed-detail` | 指定品种规格价格分析（单位→规格分层） |

### 价格统计

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/stats/price-distribution` | 全局或分类下价格区间分布 |
| `GET` | `/api/stats/province-ranges` | 多省份价格区间分布对比 |

### 数据健康

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/stats/data-health` | 每日入库量/省份新鲜度/增量异常 |

### 同步进度

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/stats/scrape-progress-all` | 全部 17 城市抓取进度汇总 |
| `GET` | `/api/stats/scrape-progress?city={key}` | 单城市抓取进度 |
| `POST` | `/api/scrape/check` | 检查抓取进度增量状态 |
| `GET` | `/api/stats/{city}-sync-progress` | 各城市同步进度（17 个端点） |

### 数据溯源

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/stats/provenance?city=all` | 数据溯源（新鲜度/趋势/来源） |
| `POST` | `/api/stats/provenance/flush-city` | 触发城市数据刷新 |
| `GET` | `/api/stats/clean-summary` | 清洗摘要统计 |
| `GET` | `/api/skill-updates` | 各 skill 增量检测状态 |

### 规格解析质量

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/stats/rules-vector` | 规格规则库查询（分页+过滤+搜索） |
| `GET` | `/api/stats/spec-quality` | Spec 解析质量报告 |
| `POST` | `/api/stats/spec-quality/fix-case` | 规则预览/确认（`confirm: false` 预览，`true` 写入） |
| `POST` | `/api/stats/spec-quality/refresh-category` | 触发指定分类 DWD→DWS 重算 |
| `POST` | `/api/stats/spec-quality/batch-spec-parse` | 批量规格解析 |
| `POST` | `/api/stats/spec-quality/classify-breed-batch` | 批量 AI 推断品种分类并写入规则库 |

### 分类体系（v3 GB 章节）

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/taxonomy/v3/tree` | v3 分类树（GB 章节体系，4 层） |
| `GET` | `/api/stats/category-v2-stats` | v2 分类统计（legacy） |
| `GET` | `/api/stats/category-v2-taxonomy` | v2 分类层级树 |
| `GET` | `/api/stats/category-v2-breed-map` | v2 品种→分类映射 |
| `GET` | `/api/stats/category-v2-l3-detail` | v2 L3 分类明细 |

### 品种分类规则

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/stats/breed-category-rules` | 分页查看品种→分类规则 |
| `POST` | `/api/stats/breed-category-rules` | 手动添加品种→分类规则 |
| `DELETE` | `/api/stats/breed-category-rules/{id}` | 删除指定规则 |
| `POST` | `/api/stats/breed-category-rules/test` | 测试品种名 Jaccard 召回 |

### 系统

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/skill-registry` | 返回所有已注册 skill 清单（skill.yml 扫盘结果） |
| `POST` | `/api/skill-registry/reload` | 手动重新扫盘（加新 skill 后无重启生效） |
| `POST` | `/api/prompts/reload` | 重新加载 AI prompt 模板 |

## 新增 Skill 接入（v1 零代码）

在 skill 目录下添加 `skill.yml`，然后热加载即可：

```bash
# 方式1：调用 reload 接口
curl -X POST http://localhost:5200/api/skill-registry/reload

# 方式2：重启 dashboard
./start.sh restart
```

`skill.yml` 字段（最小集）：

```yaml
key: mycity                  # URL slug，出现在 /api/stats/mycity-sync-progress
label: 我的城市                # 卡片显示名
province: 省名                 # 用于省市区筛选
ods_index: ods_material_mycity_price
dws_index: dws_mycity_price    # 若 ETL 未启动可留空
progress_index: ods_material_mycity_price_sync_progress
progress_mode: county         # county | period | catalogue
config_path: config.yml
cities:                       # 可选：静态城市/区县列表
  - 区A
  - 区B
```

`progress_mode` 决定 sync-progress 端点应返回什么字段：
- `county`：期望 `county_details`（如 xian / chongqing / xinjiang）
- `period`：期望 `period_details`（如 heze / henan / qingdao / 9 个 PDF skill）
- `catalogue`：期望 `catalogue_details`（如 sichuan / jinan / rizhao）

详见 `SKILL.md` 中的接入规范。

## 相关项目

| 项目 | 路径 | 说明 |
|------|------|------|
| gov-price-etl | `../gov-price-etl/` | ODS→DWD→DWS 数据入仓 ETL（v0.6）|
| xian-price | `../xian-price/` | 西安（6 区县）|
| sichuan-price | `../sichuan-price/` | 四川（21 地市）|
| chongqing-price | `../chongqing-price/` | 重庆（35 区县 + 3 source）|
| jinan-price | `../jinan-price/` | 济南（41 分类目录）|
| rizhao-price | `../rizhao-price/` | 日照（3 类别）|
| heze-price | `../heze-price/` | 菏泽（期刊）|
| henan-price | `../henan-price/` | 河南（18 地市）|
| qingdao-price | `../qingdao-price/` | 青岛（月度）|
| hainan-price | `../hainan-price/` | 海南（月度）|
| huhehaote-price | `../huhehaote-price/` | 呼和浩特（双月刊）|
| hunan-price | `../hunan-price/` | 湖南（14 页 2 类期刊）|
| jiangxi-price | `../jiangxi-price/` | 江西（articleList JSON）|
| ningxia-price | `../ningxia-price/` | 宁夏（双月刊）|
| qinghai-price | `../qinghai-price/` | 青海（双月合刊）|
| shaanxi-price | `../shaanxi-price/` | 陕西（省本级 + 9 设区市）|
| weihai-price | `../weihai-price/` | 威海（季度）|
| xinjiang-price | `../xinjiang-price/` | 新疆（16 地州 + xlsx）|

## 停止

```bash
./start.sh stop
# 或手动
kill $(lsof -ti :5200 -ti :5300)
```