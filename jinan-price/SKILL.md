---
name: jinan-price
description: "济南工程造价材料信息采集：从 jnxxj.jngczjxh.com:5020 抓取材料价格数据。"
---

# jinan-price

济南工程造价材料信息采集。从 `jnxxj.jngczjxh.com:5020` 抓取 41 个 catalogue × 多周期的材料价格数据。

> **v0.1 (2026-07-03) 模块化重构**：模块建构对齐 chongqing-price（v0.9 模式），继承 `gov_price_etl.collectors.base.SyncRunner` 抽象基类。
> 必含字段补齐：`period_start / period_end / period_days`（道友硬要求，2026-07-03）。
> 2026 年 1-5 月全量已跑通：205 units，190 完成 + 15 跳过（仪表/电气/电梯 3 个分类原站无数据），**25,047 docs 入 ES**。

## 数据源

**URL**: `http://jnxxj.jngczjxh.com:5020`

**认证方式**: 使用 Playwright (Chromium) 启动无头浏览器访问网站，从 `localStorage` 读取 `token` 作为请求认证头。**当前实测**：网站对 token 缺失也放行（API 仍可访问），但保留 Playwright 兜底防站点改版。

**API 端点**（均为 `POST /cj/api/build/material/searchPublishPriceMaterialPage`，JSON body）：

| 用途 | 端点 |
|------|------|
| 搜索材料价格 | `POST /cj/api/build/material/searchPublishPriceMaterialPage` |
| 获取最新周期 ID | `GET /cj/api/build/period/getLastPeriodId` |
| 获取周期名称 | `GET /cj/api/build/period/selectPeriodList?periodId=ID` |
| 获取分类目录树 | `GET /cj/api/build/catalogue/catalogueTree?dataType=TYPE` |

**dataType**: 默认 `2`（信息价材料）

## 命令

| 命令 | 说明 |
|------|------|
| `./run.sh sync` | 增量同步（默认按 config.sync.year=2026 拉所有匹配周期） |
| `./run.sh sync --year 2026` | 指定年份同步 |
| `./run.sh sync --periods "2026年05月材料价格信息,2026年04月材料价格信息"` | 指定周期同步 |
| `./run.sh sync --dry-run` | 预览模式，不写入 ES |
| `./run.sh sync --max-units 5` | 只跑前 5 个工作单元（验证用） |
| `./run.sh sync --reset` | 重置本地进度，重新开始 |
| `./run.sh preview` | 预览数据（按 catalogue 列表分页展示） |
| `./run.sh status` | 查看同步进度（ES 进度 + 本地进度 + config 摘要） |
| `./run.sh test` | 测试 ES 和网站连接 |
| `python3 commands/check.py` | 手动触发增量检测，输出有变化的分类 |

## 配置 (config.yml)

```yaml
es:
  host: http://localhost:59200
  index: ods_material_jinan_price        # 材料价格主索引
  catalogue_index: material_jinan_price_catalogue  # 分类目录索引
  progress_index: ods_material_jinan_price_sync_progress  # 进度记录索引
  sync_log_index: ods_material_jinan_price_sync_log        # 同步日志索引
site:
  base_url: http://jnxxj.jngczjxh.com:5020
  api_base: /cj/api/build
  data_type: '2'    # 信息价材料类型
sync:
  # v0.1 显式声明白名单（参考 chongqing v0.9）
  year: 2026
  periods:
    - '2026年05月材料价格信息'
    - '2026年04月材料价格信息'
    - '2026年03月材料价格信息'
    - '2026年02月材料价格信息'
    - '2026年01月材料价格信息'
  size_per_page: 100
  # 上次同步记录（自动更新）
  last_period: '2026年05月材料价格信息'
  last_period_id: '811589252355269'
  last_run_id: ''
  last_run_at: ''
```

## 项目结构（v0.1 对齐 chongqing v0.9）

```
jinan-price/
├── run.sh
├── config.yml
├── .jinan_sync_progress.json    # 本地进度（自动生成，{done_<period_id>_<cat_id>: ['done'], ...}）
└── commands/
    ├── sync.py               # 薄入口：解析 args → 调 make_collector → collector.run()
    ├── jinan_collector.py   # v0.1 默认：JinanCollector(SyncRunner) 抽象基类化
    ├── write_es.py          # 文档构造（含 period_start/end/days）+ bulk_write + write_progress
    ├── utils.py             # JinAnSiteSession + ensure_index（套用 gov_price_etl.build_ods_mapping）
    ├── check.py             # 增量检测（页面月份 vs ES 最新）
    ├── status.py            # 查看本地/ES 进度（v0.1 适配新进度格式）
    ├── preview.py           # 数据预览
    └── test.py              # ES 连通性测试
```

## ES 索引

| 索引 | 说明 |
|------|------|
| `ods_material_jinan_price` | 材料价格数据（套用 `gov_ods` 模板，含 period_start/end/days） |
| `material_jinan_price_catalogue` | 分类目录 |
| `ods_material_jinan_price_sync_progress` | 同步进度（每 unit 一行，含 period_start/end/days） |
| `ods_material_jinan_price_sync_log` | 同步日志 |

## 数据字段（v0.1 必含字段）

| 字段 | 类型 | 说明 |
|------|------|------|
| `breed` | text+keyword | 材料名称（productName） |
| `spec` | text+keyword | 规格型号（features） |
| `unit` | text+keyword | 单位 |
| `price` | float | 含税价格（infoPrice） |
| `tax_price` | float | 含税价格（同 price） |
| `price_min` | float | 区间下界（infoPriceMin，单值时=price） |
| `price_max` | float | 区间上界（infoPriceMax） |
| `is_range` | boolean | 是否区间价 |
| `period` | **keyword** | 周期名称（v0.1 改 keyword，可聚合） |
| `period_start` | **date** | 期间起始日（v0.1 新增） |
| `period_end` | **date** | 期间结束日（v0.1 新增） |
| `period_days` | **integer** | 期间天数（v0.1 新增，2月闰年=28） |
| `province` | **keyword** | 山东 |
| `city` / `county` | **keyword** | 济南 |
| `catalogue` / `catalogue_name` | **keyword** | 分类 ID / 名称 |
| `code` | **keyword** | 材料编码 |
| `update_date` | date | 更新日期（publishTime[:10]） |
| `publish_time` | date | 发布时间 |
| `run_id` | **keyword** | 本次运行 ID |
| `source` | keyword | 固定 'jinan' |
| `source_index` | keyword | 'ods_material_jinan_price' |

## 幂等写入

```
_id = MD5(breed + spec + period + period_id + catalogue_id + price)
```

## 断点续传

本地进度 `.jinan_sync_progress.json`（由 `LocalProgressStore` 管理），key 形状 `done_<period_id>_<cat_id>`，value 是非空 list 即代表已完成。`_compute_unit_key` 派生同一 key，`is_done()` 跳过已完成的。

## 增量机制

1. **周期维度**: 配置文件声明 `sync.year`（2026），CLI `--year` 可覆盖；sync.py 按年过滤 `get_all_periods()` 返回的列表
2. **白名单维度**: `sync.periods` 显式列出 2026 各月 periodName，精确匹配

## 模块建构对齐 chongqing v0.9（v0.1 2026-07-03）

| 设计 | chongqing v0.9 | jinan v0.1 |
|------|----------------|-----------|
| 抽象基类 | `SyncRunner` | ✓ 继承 |
| 入口模式 | `sync.py` 薄入口 + `make_collector` | ✓ 同步 |
| 工作单元 | `(source, county, period)` | `(period_id, period_name, cat_id, cat_name)` |
| 本地进度 | `LocalProgressStore` | ✓ 同步 |
| SIGINT | `SignalHandler` 上下文 | ✓ 继承基类 |
| period 必含字段 | `period_start/end/days` | ✓ 同步 |
| 索引 mapping | `build_ods_mapping` | ✓ 同步 |
| 价格区间解析 | `parse_price.parse_interval_price` | ✓ 同步（用 infoPriceMin/Max 字段） |

## 依赖

- Python 3.10+
- requests / beautifulsoup4 / pyyaml
- playwright + chromium（用于从浏览器 localStorage 获取 token）
- Elasticsearch（`http://localhost:59200`）
- **gov-price-etl skill**（强依赖）：
  - `collectors.base.SyncRunner` / `LocalProgressStore` / `SignalHandler`
  - `mappings.build_ods_mapping` / `build_progress_mapping`
  - `indexer.ensure_ods_index` / `ensure_progress_index`
  - `parse_price.parse_interval_price`（兜底）

安装依赖：
```bash
pip3 install requests beautifulsoup4 pyyaml playwright
playwright install chromium
```

## 验证清单

跑完 2026 同步后逐条核对：

- [x] ES 文档数 25,047（5 期 × 41 类 - 仪表/电气/电梯 3 类 5 期无数据）
- [x] `period_start` 字段是 date 类型，5 个不同值（2026-01-01 ~ 2026-05-01）
- [x] `period_end` 字段是 date 类型，对应月末
- [x] `period_days` 字段是 integer：31/30/28（2 月闰年 28 天）
- [x] 完整性：count(missing period_*) = 0
- [x] `period/catalogue/catalogue_name/province/city/code/run_id` 全部 keyword 类型（可 terms 聚合）
- [x] 按周期 keyword 聚合：5 个桶，docs 数为 5043/5043/5008/4978/4975
