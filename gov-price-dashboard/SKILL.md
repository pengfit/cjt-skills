---
name: gov-price-dashboard
description: "材价通 — 政府材料价格数据可视化看板。FastAPI :5200 + Vue3 :5300 + ECharts 6.x。公开页 /home（开源项目 landing）+ /market（跨城市场行情，走 NORM 索引）；鉴权 单 admin JWT（/api/* 全部 Bearer）；数据源优先级 NORM > DWS；声明式 skill 注册，新增城市零代码改动。"
---

# 材价通 / cjt-skills Dashboard

政府材料价格数据可视化看板。FastAPI + Vue3，支持多维度筛选、价格趋势分析、涨跌幅监控、跨城归一查询。

## 🚀 快速开始

```bash
cd cjt-skills/gov-price-dashboard
./start.sh                # 启动
./start.sh status         # 查看状态
./start.sh stop           # 停止
./start.sh restart        # 重启
```

- 前端：http://localhost:5300
- API：http://localhost:5200
- API 文档：http://localhost:5200/docs

## 🏗️ 架构

```
ods_material_{city}_price    (ODS 原始层 · 17 城采集)
        ↓
dwd_{city}_price             (DWD 清洗层 · ETL 三段式)
        ↓
dws_{city}_price             (DWS 聚合层)
        ↓
norm_{city}_price            (NORM 标准层 · 默认数据源)
        ↓
gov-price-dashboard API      (FastAPI :5200)
        ↓
gov-price-dashboard 前端     (Vue3 :5300)
```

**数据源优先级**：Dashboard 默认查 `norm_*_price`，缺失自动降级 `dws_*_price`（`DASHBOARD_DATA_LAYER=dws` 可强制回退）。

## 🌐 公开页

### `/home` — Landing（开源项目角度）

公开访问（`/`、`/home`、`/index`），不鉴权。Vue 组件：`HomeView.vue`。

| Section | 内容 |
|---------|------|
| **Hero** | "材价通 / cjt-skills" 大标题 + 数据规模副标 + CTA + GitHub/快速开始 链接 |
| **01 Architecture** | 4 步流程图：源数据 → ETL Pipeline → 跨城归一 → Dashboard |
| **02 Showcase** | "它能做什么"对比表 + 真实部署示例 URL |

### `/market` — 市场行情（跨城归一走 NORM）

公开访问，不鉴权。Vue 组件：`MarketView.vue` + `api/routes/market.py`。

- **数据源**：跨城 `norm_*_price` 索引（20 城），通过 `_norm_indices()` 运行时扫盘获取
- **核心 API**：`/api/market/*`（`/overview` / `/movers` / `/change-heatmap` / `/attr-keys` 等共 9 端点）
- **数据来源模块**：`/api/market/sources` 返回 20 个源站清单，点击直达源网站
- 响应缺 NORM 索引的城市会自动降级到 DWS（不报错）

## 🔐 鉴权（JWT 单 admin）

所有 `/api/*` 强制 Bearer token，仅以下路径公开：

```
/api/auth/login           # 登录端点
/api/showcase/stats       # 公开统计
/api/showcase/insight     # 公开洞察
/api/market/overview      # /market 用
/api/market/movers        # /market 用
/api/market/hot-categories
/api/market/change-heatmap
/api/market/spec-fingerprints
/api/market/attr-keys
/api/market/breed-search
/api/market/random-breeds
/api/market/related-breeds
/api/market/sources       # 数据来源清单
```

**配置**：
- **JWT secret**：从 `.env.auth` 读 `JWT_SECRET`（开发机）或 `.env.auth.docker`（容器）
- **算法**：HS256（`JWT_ALG`）
- **登录端点**：`POST /api/auth/login`，body = `{username, password}`，返回 `{access_token, token_type: "bearer"}`

## 🗂️ 侧栏导航

| 模块 | 标签 | 路由 | 说明 |
|------|------|------|------|
| **数据浏览** | 🛸 驾驶舱 | `cockpit` | 全局仪表盘，数据概览卡片 + 省份/城市/分类分布 |
| | 📋 全部数据 | `list` | 多维筛选搜索，分类树侧栏 |
| | 📁 全部类别 | `category` | 类别下钻分析，品种列表 + 规格价格明细 |
| **数据采集** | 🔄 数据同步 | `sync` | 17 城抓取进度监控，ODS→DWD→DWS 同步状态 |
| | ❤️ 数据健康 | `health` | 每日入库量、省份新鲜度、增量异常检测 |
| **数据治理** | ⚙️ 规格解析 | `rules` | 规格规则库查询/添加/测试，AI 规则生成 |
| | 🏷️ 分类体系 | `taxonomy` | 分类树浏览、品种→分类映射管理 |
| **价格可视化** | 📊 价格分布 | `dist` | 价格区间分布图表 |
| | 📈 趋势 | `trend` | 品类聚合趋势（全国跨城归一，去城市化） |

## 📁 项目结构

```
gov-price-dashboard/
├── start.sh / deploy.sh     # 启动 / 一键部署
│
├── api/
│   ├── main.py              # FastAPI 后端（中间件 + 路由注册）
│   ├── dependencies.py      # ES client + ALL_INDICES 注入
│   ├── skill_registry.py    # 自动扫 skill.yml
│   ├── auth.py              # JWT 鉴权
│   ├── normalization_bridge.py  # NORM 桥接
│   ├── paths.py             # 路径常量
│   └── routes/
│       ├── auth.py / skill.py / market.py / search.py
│       ├── filter_options.py / norm_search.py / provenance.py
│       ├── trend.py / category_trend.py / breed_recommend.py
│       └── stats/           # overview / distribution / category /
│                            # breed / geo / health / sync / norm
│
└── frontend/
    ├── package.json         # Vue 3 + Vite + ECharts 6.x
    ├── vite.config.js
    └── src/
        ├── App.vue / main.js / style.css
        ├── composables/     # useColumnConfig / useEchartsTheme /
        │                    # useFilterOptions / useOverview / ...
        └── components/
            ├── layout/      # Sidebar / TopBar
            ├── HomeView.vue / MarketView.vue
            ├── CockpitView / CategoryView / DistributionChart / ...
            └── ScrapeView / SyncView / DataHealthView / ...
```

## 🔌 API 端点总览（FastAPI :5200）

完整端点表见 [`api/main.py`](./api/)。核心分组：

| 分组 | 代表端点 | 说明 |
|------|---------|------|
| 搜索与筛选 | `GET /api/search` | 分页/筛选/sort |
| | `GET /api/filter-options` | 省市区三级联动 |
| | `GET /api/stats/overview` | 全局概览 |
| 分类与品种 | `GET /api/stats/categories` | 全量类别及数据量 |
| | `GET /api/stats/breed-detail` | 指定品种规格价格分析 |
| 品类聚合趋势（去城市化） | `GET /api/stats/category-trend` | 全国跨城归一（`city` 留空 = 全国聚合）|
| | `GET /api/stats/category-compare` | 多品类并列对比（2-4 个 normalized_breed）|
| | `GET /api/stats/category-l3-peers` | 同 L3 的所有 normalized_breed |
| 价格统计 | `GET /api/stats/price-distribution` | 价格区间分布 |
| | `GET /api/stats/province-ranges` | 多省份价格区间对比 |
| 数据质量 | `GET /api/stats/data-health` | 每日入库量/新鲜度/异常 |
| 同步进度 | `GET /api/stats/scrape-progress` | 单城抓取进度（`?city=xian`）|
| | `GET /api/stats/scrape-progress-all` | 全城汇总 |
| | `GET /api/stats/{city}-sync-progress` | 各城专用进度端点 |
| 数据溯源 | `GET /api/stats/provenance` | 数据新鲜度/趋势/来源 |
| | `POST /api/stats/provenance/flush-city` | 触发城市刷新 |
| 规格解析质量 | `GET /api/stats/rules-vector` | 规格规则库查询 |
| | `GET /api/stats/spec-quality` | Spec 解析质量报告 |
| | `POST /api/stats/spec-quality/fix-case` | 规则预览/确认 |
| | `POST /api/stats/spec-quality/batch-spec-parse` | 批量规格解析 |
| 分类体系 | `GET /api/taxonomy/v3/tree` | v3 分类树（GB 章节）|
| | `GET /api/stats/category-v2-stats` | v2 分类统计 |
| 品种分类规则 | `GET/POST/DELETE /api/stats/breed-category-rules` | CRUD |
| | `POST /api/stats/breed-category-rules/test` | Jaccard 召回测试 |
| | `POST /api/stats/spec-quality/classify-breed-batch` | 批量 AI 推断 |
| 系统 | `GET /api/skill-registry` | 已注册 skill 清单 |
| | `POST /api/skill-registry/reload` | 热加载（无需重启）|
| | `POST /api/prompts/reload` | 重载 AI prompt |

## 🔧 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `ES_HOST` | `http://localhost:59200` | Elasticsearch 地址 |
| `ES_INDEX` | `dws_xian_price` | 默认查询索引 |
| `SKILLS_ROOT` | `~/.openclaw/workspace/skills` | skill.yml 扫描根目录 |
| `CATEGORY_DB` | `../gov-price-etl/data/category_v3_rules.db` | v3 分类库 |
| `DASHBOARD_DATA_LAYER` | `norm` | 默认数据层（`dws` 强制回退）|
| `GOV_CHECK_STATUS_DIR` | `/tmp/gov-check-status` | cron 状态目录（可挂 VOLUME）|
| `GOV_PRICE_SUMMARY_DIR` | `/tmp/gov-price-summary` | 每日汇总目录（可挂 VOLUME）|

## 🏙️ 支持城市（17 个）

| City | Province | progress_mode | 数据源类型 |
|------|----------|---------------|-----------|
| 西安 | 陕西 | county | HTML 6 区县 |
| 四川 | 四川 | catalogue | ASP.NET 21 地市 |
| 重庆 | 重庆 | county | Browser 35 区县 + 3 source |
| 济南 | 山东 | catalogue | Playwright + REST API 41 目录 |
| 日照 | 山东 | catalogue | Playwright + REST 3 tab |
| 菏泽 / 河南 / 青岛 / 海南 / 呼和浩特 / 湖南 / 江西 / 宁夏 / 青海 / 陕西 / 威海 | 各省 | period | HTML + PDF，按期期刊 |
| 新疆 | 新疆 | county | HTML + xlsx 多 sheet |

完整字段定义见各 `*-price/SKILL.md`。

## 🔌 新增 skill 接入规范（v1 · 零 dashboard 代码改动）

声明式配置 + 自动发现架构。两步接入：

### 1. 在 skill 目录下加 `skill.yml`

```yaml
# ~/.openclaw/workspace/skills/<skill_dir>/skill.yml
key: mycity                  # URL slug
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

### 2. （可选）写一个 sync-progress 端点

`progress_mode` 决定端点应返回什么字段：

- **county 模式**：返回 `county_details` 列表（每区县一条）
- **period 模式**：返回 `period_details` 列表（每期一条）
- **catalogue 模式**：返回 `catalogue_details` 列表（每目录一条）

### 3. 热加载

```bash
curl -X POST http://localhost:5200/api/skill-registry/reload
```

无需重启，刷新页面新 skill 卡片自动出现。

## 🚢 部署（deploy.sh · 阿里云 ACR）

```bash
./deploy.sh login             # 首次：登录 ACR
./deploy.sh release           # 一条龙：build + tag + push + deploy
./deploy.sh status            # 查看容器/镜像状态
./deploy.sh rollback [tag]    # 回滚
```

| 环境变量 | 默认值 | 说明 |
|----------|--------|------|
| `ACR_REGISTRY` | `registry.cn-hangzhou.aliyuncs.com` | registry 地址 |
| `ACR_NAMESPACE` | `pengfit` | 命名空间 |
| `ACR_IMAGE` | `dashboard` | 镜像名 |
| `IMAGE_TAG` | `latest` | tag |

**镜像特点**：多阶段构建（Node 20 前端 + Python 3.11 slim），`skills/` 全部打包进镜像实现自包含部署，当前约 **325 MB**。

## 🛑 停止

```bash
./start.sh stop
# 或部署版本：
docker stop gov-price-dashboard && docker rm gov-price-dashboard
```

## 🤝 贡献

PR 永远欢迎。常见贡献方向：

- **新页面 / 新图表**：在 `frontend/src/components/` 加 Vue 组件，在 `api/routes/` 加对应端点
- **新数据源**：参照 `*-price/SKILL.md` 写 `skill.yml` + `config.yml` + `commands/sync.py`
- **Bug 报告**：附 ES 索引名 + 复现命令，提交到 issue tracker

## 📄 License

[MIT License](../README.md) — 根目录有完整 LICENSE 文件。

## 🙏 致谢

- **数据来源**：17 个省/市住建局官方造价信息期刊
- **AI 编排**：[Dify](https://dify.ai) workflow
- **多模型协作**：[OpenClaw](https://openclaw.ai)
- **可视化**：[Apache ECharts](https://echarts.apache.org)