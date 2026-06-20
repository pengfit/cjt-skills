# 材价通 - 政府材料价格看板

政务数据材料价格查询与可视化平台，基于 Elasticsearch 数据源，支持多维度筛选、价格趋势分析、规格解析质量监控、数据溯源追踪。

> **前台访问**：http://localhost:5300
> **API 文档**：http://localhost:5200/docs

## 功能界面（侧栏导航）

| 标签页 | 路由 | 说明 |
|--------|------|------|
| 🛸 驾驶舱 | `?tab=cockpit` | 全局仪表盘，数据概览卡片 + 省份/城市/分类分布图 |
| 📋 全部数据 | `?tab=list` | 多维筛选搜索，关键词/省市县/分类树/价格区间筛选，分页排序，属性标签展开详情 |
| 📁 全部类别 | `?tab=category` | 类别下钻分析，品种列表 + 规格价格明细 |
| 📊 价格分布 | `?tab=dist` | 省份/城市数据量分布图，价格区间分布图表 |
| 🔄 数据同步 | `?tab=sync` | 各城市抓取进度监控，ODS→DWD→DWS 同步状态 |
| ❤️ 数据健康 | `?tab=health` | 每日入库量、省份新鲜度、增量异常检测 |
| ⚙️ 规格解析 | `?tab=rules` | 规格规则库查询/添加/测试，DWD 抽样质量报告，AI 规则生成 |
| 🏷️ 分类体系 | `?tab=taxonomy` | 分类树浏览、品种→分类映射规则管理、Jaccard 召回、批量 AI 分类 |

## 技术栈

| 层级 | 技术 |
|------|------|
| 后端 | Python 3 + FastAPI + Elasticsearch |
| 前端 | Vue 3 + Vite + ECharts + Axios |
| 数据源 | Elasticsearch（`ES_HOST`，默认 `http://localhost:59200`）|
| 规则库 | SQLite（`rules_vec.db`）+ breed 分类库（`category_v3_rules.db`）|
| AI 集成 | OpenClaw LLM（规格解析规则生成 / 品种批量分类 / 分类推断）|

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
│       ├── App.vue           # 主布局（顶栏 + 侧栏 + 主内容区）
│       ├── main.js
│       ├── style.css
│       ├── composables/      # 可复用逻辑
│       │   ├── useColumnConfig.js
│       │   ├── useEchartsTheme.js
│       │   ├── useFilterOptions.js
│       │   ├── useOverview.js
│       │   ├── useProvinceColor.js
│       │   ├── useSearch.js
│       │   ├── useTabState.js
│       │   └── useToast.js
│       └── components/
│           ├── layout/
│           │   ├── Sidebar.vue         # 侧栏导航
│           │   └── TopBar.vue          # 顶栏（品牌 + 统计）
│           ├── AppButton.vue           # 通用按钮
│           ├── AppCard.vue             # 通用卡片
│           ├── AppPagination.vue       # 通用分页
│           ├── AttrTags.vue            # 规格属性标签渲染
│           ├── BreedMapTab.vue         # 品种→分类映射管理
│           ├── CategoryTaxonomyTab.vue # 分类体系标签页
│           ├── CategoryTaxonomyView.vue# 分类体系视图容器
│           ├── CategoryTreeBrowser.vue # 分类树浏览器
│           ├── CategoryTreeNav.vue     # 分类树导航
│           ├── CategoryTreeSidebar.vue # 分类树侧栏
│           ├── CategoryView.vue        # 类别分析视图
│           ├── CleanDimView.vue        # 清洗维度视图
│           ├── CmdPalette.vue          # ⌘K 命令面板
│           ├── CockpitView.vue         # 驾驶舱视图
│           ├── CustomSelect.vue        # 自定义下拉筛选
│           ├── DataHealthView.vue      # 数据健康视图
│           ├── DataProvenanceView.vue  # 数据溯源视图
│           ├── DistributionChart.vue   # 数据分布图表
│           ├── EmptyState.vue          # 空状态占位
│           ├── ErrorBoundary.vue       # 错误边界
│           ├── ErrorState.vue          # 错误状态占位
│           ├── PageHeader.vue          # 页面标题
│           ├── ScrapeView.vue          # 抓取进度视图
│           ├── SectionHeader.vue       # 区块标题
│           ├── SkeletonCard.vue        # 骨架屏卡片
│           ├── SkeletonChart.vue       # 骨架屏图表
│           ├── SpecQualityPanel.vue    # 规格质量面板
│           ├── SpecSamplePanel.vue     # 规格抽样面板
│           ├── StatCard.vue            # 统计卡片
│           ├── SyncCard.vue            # 同步进度卡片
│           ├── SyncView.vue            # 数据同步视图
│           ├── TreeNode.vue            # 树节点组件
│           └── VecRulesView.vue        # 规格规则库视图
├── docs/
├── screenshots/
└── .vite/
```

## 快速启动

```bash
cd skills/gov-price-dashboard
./start.sh           # 启动
./start.sh status    # 查看状态
./start.sh stop      # 停止
./start.sh restart   # 重启
```

## 支持城市（8 个）

| 城市 | Province | progress_mode | DWS 索引 | 进度追踪 |
|------|----------|---------------|---------|---------|
| 西安 | 陕西 | county | `dws_xian_price` | 6 区县 |
| 四川 | 四川 | catalogue | `dws_sichuan_price` | 21 地市/自治州 |
| 重庆 | 重庆 | county | `dws_chongqing_price` | 35 区县 |
| 济南 | 山东 | catalogue | `dws_jinan_price` | 41 分类目录 |
| 日照 | 山东 | catalogue | `dws_rizhao_price` | 3 类别 |
| 菏泽 | 山东 | period | `dws_heze_price` | 按期期刊 |
| 河南 | 河南 | period | `dws_henan_price` | 18 地市，按期期刊 |
| 青岛 | 山东 | period | `dws_qingdao_price` | 月度期刊 |

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

## 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `ES_HOST` | `http://localhost:59200` | Elasticsearch 地址 |
| `ES_INDEX` | `dwd_xian_price` | 默认查询索引 |
| `SKILLS_ROOT` | `~/.openclaw/workspace/skills` | skill.yml 扫描根目录 |
| `CATEGORY_DB` | `../gov-price-etl/data/category_v3_rules.db` | v3 分类库 SQLite 路径 |

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
| `GET` | `/api/stats/scrape-progress-all` | 全部城市抓取进度汇总 |
| `GET` | `/api/stats/scrape-progress?city=xian` | 单城市抓取进度 |
| `POST`| `/api/scrape/check` | 检查抓取进度增量状态 |
| `GET` | `/api/stats/{city}-sync-progress` | 各城市同步进度（xian/sichuan/chongqing/jinan/rizhao/heze/henan/qingdao） |

### 数据溯源

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/stats/provenance?city=all` | 数据溯源（新鲜度/趋势/来源） |
| `POST`| `/api/stats/provenance/flush-city` | 触发城市数据刷新 |
| `GET` | `/api/stats/clean-summary` | 清洗摘要统计 |
| `GET` | `/api/skill-updates` | 各 skill 增量检测状态 |

### 规格解析质量

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/stats/rules-vector` | 规格规则库查询（分页+过滤+搜索） |
| `GET` | `/api/stats/spec-quality` | Spec 解析质量报告（抽样+分类覆盖率） |
| `POST`| `/api/stats/spec-quality/fix-case` | 规则预览/确认（`confirm: false` 预览，`true` 写入） |
| `POST`| `/api/stats/spec-quality/refresh-category` | 触发指定分类 DWD→DWS 重算 |
| `POST`| `/api/stats/spec-quality/batch-spec-parse` | 批量规格解析 |
| `POST`| `/api/stats/spec-quality/classify-breed-batch` | 批量 AI 推断品种分类并写入规则库 |

### 分类体系（v2 legacy + v3）

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
| `POST`| `/api/stats/breed-category-rules` | 手动添加品种→分类规则 |
| `DELETE` | `/api/stats/breed-category-rules/{id}` | 删除指定规则 |
| `POST`| `/api/stats/breed-category-rules/test` | 测试品种名 Jaccard 召回 |

### 系统

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/skill-registry` | 返回所有已注册 skill 清单 |
| `POST`| `/api/skill-registry/reload` | 重新扫描 skill.yml（热加载） |
| `POST`| `/api/prompts/reload` | 重新加载 AI prompt 模板 |

## 新增 Skill 接入

在 skill 目录下添加 `skill.yml`，然后热加载即可，零代码改动：

```bash
# 方式1：调用 reload 接口
curl -X POST http://localhost:5200/api/skill-registry/reload

# 方式2：重启 dashboard
./start.sh restart
```

详见 `SKILL.md` 中的接入规范。

## 相关项目

| 项目 | 路径 | 说明 |
|------|------|------|
| gov-price-etl | `../gov-price-etl/` | ODS→DWD→DWS 数据入仓 ETL |
| xian-price | `../xian-price/` | 西安数据同步（6 区县） |
| sichuan-price | `../sichuan-price/` | 四川数据同步（21 地市） |
| chongqing-price | `../chongqing-price/` | 重庆数据同步（35 区县） |
| jinan-price | `../jinan-price/` | 济南数据同步（41 分类目录） |
| rizhao-price | `../rizhao-price/` | 日照数据同步（3 类别） |
| heze-price | `../heze-price/` | 菏泽数据同步（按期期刊） |
| henan-price | `../henan-price/` | 河南数据同步（18 地市，按期期刊） |
| qingdao-price | `../qingdao-price/` | 青岛数据同步（月度期刊） |
