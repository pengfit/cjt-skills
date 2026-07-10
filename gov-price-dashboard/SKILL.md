---
name: gov-price-dashboard
description: "政府材料价格数据可视化看板（材价通），基于 FastAPI + Vue3，支持多维度筛选、价格趋势分析、涨跌幅监控。"
---

# 材价通

政府材料价格数据可视化看板，基于 FastAPI + Vue3，支持多维度筛选、价格趋势分析、涨跌幅监控。

## 启动

```bash
cd skills/gov-price-dashboard
./start.sh           # 启动
./start.sh status    # 查看状态
./start.sh stop      # 停止
./start.sh restart   # 重启
```

- 前端：http://localhost:5300
- API：http://localhost:5200
- API 文档：http://localhost:5200/docs

## 架构

```
ods_material_{city}_price    (ODS 原始层)
         ↓
dwd_{city}_price             (DWD 清洗层)
         ↓
dws_{city}_price             (DWS 聚合层，API 查询)
         ↓
gov-price-dashboard API (FastAPI :5200)
         ↓
gov-price-dashboard 前端 (Vue3 :5300)
```

## 侧栏导航

侧栏 4 模块拆分（2026-07-10 调整）：

### 数据浏览

| 标签 | 路由 | 说明 |
|------|------|------|
| 驾驶舱 | `cockpit` | 全局仪表盘，数据概览卡片 + 省份/城市/分类分布图 |
| 全部数据 | `list` | 产品搜索/筛选/列表，支持分类树侧栏 |
| 全部类别 | `category` | 类别下钻分析，品种列表 + 规格价格明细 |

### 数据采集

| 标签 | 路由 | 说明 |
|------|------|------|
| 数据同步 | `sync` | 各城市抓取进度监控，ODS→DWD→DWS 同步状态 |
| 数据健康 | `health` | 每日入库量、省份新鲜度、增量异常检测 |

### 数据治理

| 标签 | 路由 | 说明 |
|------|------|------|
| 规格解析 | `rules` | 规格规则库查询/添加/测试，DWD 抽样质量报告 |
| 分类体系 | `taxonomy` | 分类树浏览、品种→分类映射管理 |

### 价格可视化

| 标签 | 路由 | 说明 |
|------|------|------|
| 价格分布 | `dist` | 价格区间分布图表 |
| 趋势 | `trend` | 品类聚合趋势（全国跨城归一） |

## 项目结构

```
gov-price-dashboard/
├── start.sh                  # 一键启动脚本
│
├── api/
│   ├── main.py               # FastAPI 后端（搜索/统计/同步进度）
│   ├── requirements.txt
│   ├── skill_registry.py     # Skill 注册中心（自动扫 skill.yml）
│   └── routes/
│       ├── provenance.py     # 数据溯源 + 规格解析 + 分类体系路由
│       └── prompts.yml       # AI prompt 模板
│
└── frontend/
    ├── package.json
    ├── vite.config.js
    └── src/
        ├── App.vue            # 主布局（顶栏 + 侧栏 + 主内容区）
        ├── main.js
        ├── style.css
        ├── composables/       # 可复用逻辑
        │   ├── useColumnConfig.js
        │   ├── useEchartsTheme.js
        │   ├── useFilterOptions.js
        │   ├── useOverview.js
        │   ├── useProvinceColor.js
        │   ├── useSearch.js
        │   ├── useTabState.js
        │   └── useToast.js
        └── components/
            ├── layout/
            │   ├── Sidebar.vue         # 侧栏导航
            │   └── TopBar.vue          # 顶栏（品牌 + 统计）
            ├── AppButton.vue           # 通用按钮
            ├── AppCard.vue             # 通用卡片
            ├── AppPagination.vue       # 通用分页
            ├── AttrTags.vue            # 规格属性标签渲染
            ├── BreedMapTab.vue         # 品种→分类映射管理
            ├── CategoryTaxonomyTab.vue # 分类体系标签页
            ├── CategoryTaxonomyView.vue# 分类体系视图容器
            ├── CategoryTreeBrowser.vue # 分类树浏览器
            ├── CategoryTreeNav.vue     # 分类树导航
            ├── CategoryTreeSidebar.vue # 分类树侧栏
            ├── CategoryView.vue        # 类别分析视图
            ├── CleanDimView.vue        # 清洗维度视图
            ├── CmdPalette.vue          # ⌘K 命令面板
            ├── CockpitView.vue         # 驾驶舱视图
            ├── CustomSelect.vue        # 自定义下拉筛选
            ├── DataHealthView.vue      # 数据健康视图
            ├── DataProvenanceView.vue  # 数据溯源视图
            ├── DistributionChart.vue   # 数据分布图表
            ├── EmptyState.vue          # 空状态占位
            ├── ErrorBoundary.vue       # 错误边界
            ├── ErrorState.vue          # 错误状态占位
            ├── PageHeader.vue          # 页面标题
            ├── ScrapeView.vue          # 抓取进度视图
            ├── SectionHeader.vue       # 区块标题
            ├── SkeletonCard.vue        # 骨架屏卡片
            ├── SkeletonChart.vue       # 骨架屏图表
            ├── SpecQualityPanel.vue    # 规格质量面板
            ├── SpecSamplePanel.vue     # 规格抽样面板
            ├── StatCard.vue            # 统计卡片
            ├── SyncCard.vue            # 同步进度卡片
            ├── SyncView.vue            # 数据同步视图
            ├── TreeNode.vue            # 树节点组件
            └── VecRulesView.vue        # 规格规则库视图
```

## API 端点总览（FastAPI :5200）

### 搜索与筛选

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/search` | 价格搜索（分页/筛选/sort） |
| `GET` | `/api/filter-options` | 省市区三级联动选项 |
| `GET` | `/api/stats/overview` | 全局概览（总量/省份/城市/分类分布） |

### 分类与品种

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/stats/categories` | 所有产品类别及数据量 |
| `GET` | `/api/stats/category-detail` | 指定类别省份分布+热门品种+规格价格 |
| `GET` | `/api/stats/category-price-ranges` | 指定类别的动态价格区间（按分位数） |
| `GET` | `/api/stats/category-breeds` | 指定类别的去重品种列表（分页） |
| `GET` | `/api/stats/breed-detail` | 指定品种的规格价格分析（按单位→规格分层） |
| `GET` | `/api/stats/breed-category-rules` | 全量 breed 归属分类（分类规则库下拉） |

### 品类聚合趋势（2026-07-09 起「去城市化」，全国跨城归一）

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/stats/category-trend` | 单品类规格热力图 + 价格带 + 规格分布。`city` 留空 / `all` / `nation` = 全国聚合（跨 NORM 索引）；保留单城 key 以向后兼容 |
| `GET` | `/api/stats/category-compare` | 多品类并列对比（2-4 个 normalized_breed）。同样支持 city 留空走全国 |
| `GET` | `/api/stats/category-l3-peers` | 同 L3 的所有 normalized_breed。同样支持 city 留空走全国 |

全国聚合响应额外字段：`label="全国 (N 城)"`、`is_aggregate=true`、`cities_meta=[...]`。
后端统一入口：`api/routes/category_trend.py:_resolve_query_indices(city)`。
前端：`/trend` 标签页「品类聚合」（`CategoryTrendView.vue`）已移除城市控件，不再传 city。

### 价格统计

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/stats/price-distribution` | 全局或分类下的价格区间分布 |
| `GET` | `/api/stats/province-ranges` | 多省份价格区间分布对比 |

### 数据质量

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/stats/data-health` | 数据健康度（每日入库量/省份新鲜度/增量异常） |

### 同步进度

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/stats/scrape-progress` | 单城市抓取进度（`?city=xian`） |
| `GET` | `/api/stats/scrape-progress-all` | 全部城市抓取进度汇总 |
| `POST` | `/api/scrape/check` | 检查抓取进度增量状态 |
| `GET` | `/api/stats/xian-sync-progress` | 西安同步进度（6区县） |
| `GET` | `/api/stats/sichuan-sync-progress` | 四川同步进度（21地市） |
| `GET` | `/api/stats/rizhao-sync-progress` | 日照同步进度（3类别） |
| `GET` | `/api/stats/jinan-sync-progress` | 济南同步进度（41分类目录） |
| `GET` | `/api/stats/chongqing-sync-progress` | 重庆同步进度（35区县） |
| `GET` | `/api/stats/heze-sync-progress` | 菏泽同步进度（按期期刊） |
| `GET` | `/api/stats/henan-sync-progress` | 河南同步进度（18地市，按月跟踪 period） |
| `GET` | `/api/stats/qingdao-sync-progress` | 青岛同步进度（月度期刊） |

### 数据溯源与清洗

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/stats/provenance` | 数据溯源（新鲜度/趋势/来源，`?city=all`） |
| `POST` | `/api/stats/provenance/flush-city` | 触发城市数据刷新 |
| `GET` | `/api/stats/clean-summary` | 清洗摘要统计 |
| `GET` | `/api/skill-updates` | 各 skill 增量检测状态 |

### 规格解析质量

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/stats/rules-vector` | 规格规则库查询（分页+过滤+搜索） |
| `GET` | `/api/stats/spec-quality` | Spec 解析质量报告（抽样+分类覆盖率） |
| `POST` | `/api/stats/spec-quality/fix-case` | 规则预览/确认（confirm=False 预览，confirm=True 写入） |
| `POST` | `/api/stats/spec-quality/refresh-category` | 触发指定分类的 DWD→DWS 清洗重算 |
| `POST` | `/api/stats/spec-quality/batch-spec-parse` | 批量规格解析 |

### 分类体系

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/taxonomy/v3/tree` | v3 分类树（GB 章节体系） |
| `GET` | `/api/stats/category-v2-stats` | v2 分类统计 |
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
| `POST` | `/api/stats/spec-quality/classify-breed-batch` | 批量 AI 推断品种分类并写入规则库 |

### 系统

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/skill-registry` | 返回所有已注册 skill 清单（skill.yml 扫盘结果） |
| `POST` | `/api/skill-registry/reload` | 手动重新扫盘（加新 skill 后无重启生效） |
| `POST` | `/api/prompts/reload` | 重新加载 AI prompt 模板 |

## 搜索 API 参数

```
GET /api/search?keyword=&province=&city=&county=&category=
    &unit=&price_min=&price_max=&page=1&page_size=20
```

### search 返回字段

```json
{
  "id": "_id",
  "breed": "产品名称",
  "spec": "规格",
  "attr": { "thickness": "2mm", "cores": "3芯", "diameter": "150", ... },
  "unit": "单位",
  "price": 100.0,
  "price_t": 100.0,
  "tax_price": 113.0,
  "province": "陕西",
  "city": "西安",
  "county": "阎良区",
  "date": "2026-05-20"
}
```

## attr 字段说明

| 字段 | 说明 | 示例 |
|------|------|------|
| `thickness` | 厚度 | `2mm` |
| `length` | 长度 | `1200mm` |
| `width` | 宽度 | `400mm` |
| `height` | 高度 | `600mm`, `H=0.36m→360mm` |
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

## 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `ES_HOST` | `http://localhost:59200` | Elasticsearch 地址 |
| `ES_INDEX` | `dws_xian_price` | 默认查询 DWS 索引 |
| `SKILLS_ROOT` | `~/.openclaw/workspace/skills` | skill.yml 扫描根目录 |
| `CATEGORY_DB` | `../gov-price-etl/data/category_v3_rules.db` | v3 分类库 SQLite 路径 |

## 支持城市（17 个）

| City | Province | progress_mode | 数据源类型 | 说明 |
|------|----------|---------------|-----------|------|
| 西安 | 陕西 | county | HTML 6 区县 | 按造价信息表月份 |
| 四川 | 四川 | catalogue | ASP.NET 21 地市 | 月度 |
| 重庆 | 重庆 | county | Browser 35 区县 + 3 source | 月份 + v4 区间价 |
| 济南 | 山东 | catalogue | Playwright + REST API 41 目录 | 周期 |
| 日照 | 山东 | catalogue | Playwright + REST 3 tab | 月份 |
| 菏泽 | 山东 | period | API + HTML + PDF | 期刊 |
| 河南 | 河南 | period | HTML 4 页 + PDF | 18 地市，期刊 |
| 青岛 | 山东 | period | HTML + PDF | 月度期刊 |
| 海南 | 海南 | period | HTML 10 页 + PDF | 月度期刊 |
| 呼和浩特 | 内蒙古 | period | HTML + PDF | 双月刊 |
| 湖南 | 湖南 | period | HTML 14 页 + PDF（2 类）| 期刊 |
| 江西 | 江西 | period | HTML articleList JSON + PDF | 期刊 |
| 宁夏 | 宁夏 | period | HTML 5 页 + PDF | 双月刊 |
| 青海 | 青海 | period | HTML 4 页 + PDF | 双月合刊 |
| 陕西 | 陕西 | period | HTML 5 页 + 7 种 PDF 格式 | 省本级 + 9 设区市 |
| 威海 | 山东 | period | jpage dataproxy + PDF | 季度 |
| 新疆 | 新疆 | county | HTML + xlsx 多 sheet | 16 地州 |

## ES 索引结构

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

> 索引名由各 skill 的 `skill.yml` 声明，`api/skill_registry.py` 启动时扫盘生成 `ALL_INDICES`。

**默认查询索引**：`dws_xian_price`（可通过 `ES_INDEX` 环境变量切换）

## 新增 skill 接入规范（v1）

Dashboard 采用"声明式配置 + 自动发现"架构。加新 skill **零 dashboard 代码改动**，只需两步：

### 1. 在 skill 目录下加 `skill.yml`

```yaml
# ~/.openclaw/workspace/skills/<skill_dir>/skill.yml
key: mycity                  # URL slug，出现在 /api/stats/mycity-sync-progress
label: 我的城市                # 卡片显示名
province: 省名                 # 用于省市区筛选
ods_index: ods_material_mycity_price
dws_index: dws_mycity_price    # 若 ETL 未启动可留空
progress_index: ods_material_mycity_price_sync_progress
progress_mode: county         # county | period | catalogue
config_path: skills/mycity-price/config.yml
cities:                       # 可选：静态城市/区县列表
  - 区A
  - 区B
```

**字段说明**：
- `key` / `label` / `province`：必填，用于 URL 和显示
- `ods_index` / `dws_index`：ES 索引名；`ALL_INDICES` 会自动拼入
- `progress_index`：进度记录索引。命名不统一也无所谓，registry 会用此字段
- `progress_mode`：决定 `<SyncCard>` 怎么渲染
  - `county`：按区县分组，期望 `county_details` 字段
  - `period`：按期期刊，期望 `period_details` 字段
  - `catalogue`：按分类目录，期望 `catalogue_details` 字段
- `config_path`：用于读 `sync.last_period` / `last_update_date` 做增量检测

### 2. （可选）写一个 sync-progress 端点

`progress_mode` 决定了 `sync-progress` 端点应返回什么字段。

**county 模式**（如 xian / chongqing）：
```python
@app.get("/api/stats/mycity-sync-progress")
def mycity_sync_progress():
    # 查 progress_index，取最新 run_id 的所有 county 记录
    return {
        "status": "running", "completed_counties": 3, "total_counties": 6,
        "current_county": "区A", "current_page": 5, "total_pages": 23,
        "last_updated": "...", "duration_sec": 120,
        "total_docs": 1234,
        "county_details": [{"county": "区A", "status": "completed",
                           "docs_written": 200, "last_updated": "..."}],
    }
```

**period 模式**（如 heze / henan / qingdao）：
```python
@app.get("/api/stats/mycity-sync-progress")
def mycity_sync_progress():
    return {
        "status": "ok", "completed_periods": 2, "total_periods": 5,
        "latest_period": "2026.1", "last_updated": "...",
        "total_docs": 5000,
        "period_details": [{"period": "2026.1", "publish_date": "...",
                            "status": "completed", "docs_written": 2500}],
    }
```

### 3. 热加载（无需重启）

```bash
curl -X POST http://localhost:5200/api/skill-registry/reload
```

或重启 dashboard：

```bash
cd skills/gov-price-dashboard
./start.sh restart
```

刷新页面，新 skill 卡片自动出现。

## 相关项目

| 项目 | 说明 |
|------|------|
| gov-price-etl | ODS→DWD→DWS 数据入仓 ETL |
| xian-price | 西安数据同步（6 区县） |
| sichuan-price | 四川数据同步（21 地市） |
| chongqing-price | 重庆数据同步（35 区县） |
| jinan-price | 济南数据同步（41 分类目录） |
| rizhao-price | 日照数据同步（3 类别） |
| heze-price | 菏泽数据同步（按期期刊） |
| henan-price | 河南数据同步（18 地市，按期期刊） |
| qingdao-price | 青岛数据同步（月度期刊） |

## 停止

```bash
./start.sh stop
# 或手动
kill $(lsof -ti :5200 -ti :5300)
```
