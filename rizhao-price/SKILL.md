---
name: rizhao-price
description: "日照工程造价材料信息采集：从 http://58.59.43.227:81 抓取材料价格数据，v1.1 多期 + REST API 模式 + SyncRunner 抽象基类化 + 必含 period_start/period_end/period_days 字段。"
---

# rizhao-price

日照工程造价材料信息采集 Skill。从 `http://58.59.43.227:81` 抓取材料价格，写入本地 ES `ods_material_rizhao_price`。

> **v1.0（2026-07-03）模块建构参考重庆**：默认走 `RizhaoCollector`（SyncRunner 抽象基类化），`--legacy` 兼容 v0 流式同步。
> **v1.0 字段扩展**：每个 doc 必含 `period_start` / `period_end` / `period_days`（道友要求）。
> **v1.1（2026-07-03）多期 + REST API 模式**：反编译源站 SPA axios 调用 → 走 Playwright + 内部 fetch，1 次启动抓全 5 期 × 3 tab = 15 units。历史期可回溯（`--periods 2026-01..2026-05`）。

## 数据源

- **URL**：`http://58.59.43.227:81/dist/#/index/priceDissemination`（Vue + ElementUI 动态页面）
- **REST endpoint**（v1.1 反编译）：`POST /EpointSDRZ/rest/zjzmaterialpriceserver/getreleaseprice`
  - 接受 `periods='2026-1'/'2026-2'/.../'2026-5'` 历史期
  - `pageSize=2000` + `pageIndex=0` 一次拿全 1084 条
  - 必须在 Playwright 浏览器上下文 fetch（纯 HTTP requests 不返数据）
- **Chrome 路径**：`/Users/pengfit/Library/Caches/ms-playwright/chromium-1217/chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing`
- **数据来源字段**：`clmc`(材料名称)、`ggxh`(规格型号)、`dw`(单位)、`price`(参考价格)、`remark`(备注)

## 三个数据类别 × 五个期间（v1.1 验证）

| tab_type | 名称 | 2026-01 | 2026-02 | 2026-03 | 2026-04 | 2026-05 |
|----------|------|---------|---------|---------|---------|---------|
| `1` | 建设工程材料 | 1078 | 1078 | 1078 | 1084 | 1084 |
| `2` | 园林绿化苗木 | 20 | 20 | 7 | 11 | 2 |
| `3` | 区县建设工程材料 | 60 | 60 | 60 | 60 | 60 |
| **合计** | | **1158** | **1158** | **1145** | **1155** | **1146** |

总计 5762 条（5 期 × 3 tab = 15 units）

## 命令速查

| 命令 | 说明 |
|------|------|
| `./run.sh sync` | 默认走 Collector：3 tab + 2026 年最新期 |
| `./run.sh sync --periods 2026-01..2026-05` | 范围语法：5 期 × 3 tab = 15 units |
| `./run.sh sync --periods 2026-01,2026-02,2026-03` | 列表语法：3 期 × 3 tab = 9 units |
| `./run.sh sync --tabs 1` | 只抓建设工程材料 |
| `./run.sh sync --tabs 1,3` | 抓建设+区县，跳过苗木 |
| `./run.sh sync --reset` | 重置本地进度，重新开始 |
| `./run.sh sync --max-units 1` | 验证：只跑前 1 个 unit |
| `./run.sh sync --legacy` | v0 兼容路径（逃生通道） |
| `./run.sh status` | 查看同步状态（ODS 统计 + 进度） |
| `./run.sh test` | 测试 ES 连接 |
| `./run.sh check` | 检查源站是否有新数据 |

## 配置（config.yml）

```yaml
es:
  host: http://localhost:59200
  index: ods_material_rizhao_price
  progress_index: ods_rizhao_price_sync_progress
  sync_log_index: ods_rizhao_price_sync_log

site:
  base_url: http://58.59.43.227:81/EpointSDRZ
  price_page: http://58.59.43.227:81/dist/#/index/priceDissemination

sync:
  last_period: 2026-05
  tabs: ["1", "2", "3"]
  progress_file: .rizhao_sync_progress.json
```

## 数据字段（v1.0）

| 字段 | 类型 | 说明 |
|------|------|------|
| `breed` | text | 材料名称 |
| `spec` | text | 规格型号 |
| `unit` | keyword | 单位 |
| `price` | float | 参考价格（元） |
| `price_min` | float | 价格下界（v1.0 新增，预留区间价） |
| `price_max` | float | 价格上界（v1.0 新增，预留区间价） |
| `price_range` | keyword | 原始价格字符串 |
| `is_range` | boolean | 是否区间价（默认 false） |
| **`period`** | **keyword** | **业务期 `'2026-05'`** |
| **`period_start`** | **date** | **周期起始日 `'2026-05-01'`（v1.0 新增）** |
| **`period_end`** | **date** | **周期结束日 `'2026-05-31'`（v1.0 新增）** |
| **`period_days`** | **integer** | **周期天数 `31`（v1.0 新增）** |
| `update_date` | date | 更新日期（=period_start） |
| `create_time` | date | 入库时间 |
| `province` | keyword | 山东 |
| `city` | keyword | 日照市 |
| `county` | keyword | 日照市（tab_type=3 时按区县区分） |
| `tab_type` | keyword | 类别 ID（1/2/3） |
| `tab_name` | keyword | 类别名称 |
| `source_index` | keyword | 来源 ODS 索引名 |
| `remark` | text | 备注 |

## ES 索引

| 索引 | 说明 |
|------|------|
| `ods_material_rizhao_price` | 材料价格数据（套用 `gov_ods` ETL 共享 mapping） |
| `ods_rizhao_price_sync_progress` | 同步进度（每个 tab × period 一条） |

## v1.0 + v1.1 设计要点

### 模块建构（参考重庆 v0.8 + 河南 v0.8）

- **继承 `SyncRunner`**：复用 ETL 公共基类的 SIGINT / 本地进度 / run 汇总
- **重写 4 个钩子**：
  - `_list_work_units()`：按 `(period, tab)` 扁平化（v1.1 默认 5 期 × 3 tab = 15 units）
  - `_process_one(unit)`：v1.1 走 `fetch_data.py`（Playwright + 内部 fetch API）→ bulk 写 ES
  - `_on_unit_done(unit, docs_count, status)`：写 ES progress + 保存本地进度
  - `_compute_unit_key(unit)`：`done_<tab>_<period>`
- **CLI 默认 Collector**：`./run.sh sync` 走 `rizhao_collector.py`；`--legacy` 走 v0 流式

### 字段扩展（v1.0）

`parse_period_window(period)` 从 `'YYYY-MM'` 推算三个新字段：

```python
parse_period_window('2026-05')
# → {'period': '2026-05',
#    'period_start': '2026-05-01',
#    'period_end': '2026-05-31',
#    'period_days': 31,
#    'period_unit': '月'}

parse_period_window('2026-02')  # 平年 2 月
# → {'period': '2026-02',
#    'period_start': '2026-02-01',
#    'period_end': '2026-02-28',
#    'period_days': 28,
#    'period_unit': '月'}
```

### v1.1 API 抓取（反编译源站 axios 调用）

**v1.1 关键发现**：
1. 源站 SPA 内部走 axios POST：
   - URL: `http://58.59.43.227:81/EpointSDRZ/rest/zjzmaterialpriceserver/getreleaseprice`
   - Content-Type: `application/x-www-form-urlencoded`
   - Body: **裸 JSON 字符串**（不是 form-encoded `params=...`），形如
     ```json
     {"params":"{\"pageIndex\":0,\"pageSize\":2000,\"condition\":\"\",\"periods\":\"2026-1\",\"tabType\":\"1\",\"id\":\"f9root\"}"}
     ```
2. periods 字段接受历史期（`2026-1` ~ `2026-5`，无前导 0）→ 可回溯
3. pageIndex 起始是 0；pageSize 上限 2000
4. 必须在 Playwright 浏览器上下文 fetch（纯 HTTP requests 不返数据，因后端用 session 限制）

**v1.1 优势**：
- 无浏览器翻页：1 个 API 请求拿全 1 期 1 tab 的全量数据
- 5 期 × 3 tab = 15 unit，1 次浏览器启动约 80 秒完成
- 历史期可回溯（`--periods 2026-01..2026-05`）

## 项目结构

```
rizhao-price/
├── run.sh                       # CLI 入口（封装命令）
├── config.yml                   # 配置文件
├── package.json                 # npm 依赖（playwright）
├── .rizhao_sync_progress.json   # 本地进度（自动生成，v1.0 新格式）
└── commands/
    ├── sync.py                  # 同步入口（默认 Collector / --legacy，v1.1 加 --periods）
    ├── rizhao_collector.py      # v1.0 Collector（SyncRunner 化）
    ├── fetch_data.py            # v1.1 REST API 抓取（Playwright + 内部 fetch）★ 新增
    ├── legacy_sync.py           # v0 兼容路径（逃生通道）
    ├── fetch_data.js            # v0 Playwright 流式抓取（保留为兜底）
    ├── utils.py                 # 共用函数（ES 索引创建委托给 ETL）
    ├── status.py                # v1.0 状态查看
    ├── check.py                 # 增量检测
    ├── test.py                  # ES 连接测试
    └── preview.py               # 预览（兼容 v0）
```

## 依赖

- **Python 3.10+** + `requests` `pyyaml`
- **Node.js** + `playwright`（需提前 `npx playwright install chromium`）
- **gov-price-etl skill**（部署在 `~/.openclaw/workspace/skills/gov-price-etl`）— 强依赖：
  - `collectors.base.SyncRunner`
  - `indexer.ensure_ods_index`
  - `indexer.ensure_progress_index`
  - `mappings.build_ods_mapping` / `build_progress_mapping`（自动含 `period_*` 字段）
- **本地 ES**：`http://localhost:59200`

## v1.1 验证记录（2026-07-03 试跑）

`--periods 2026-01..2026-05` → 15 units，5762 条入库，period_* 字段 100% 覆盖：

```
── ES ODS 索引 ──
  总文档数: 5762
  tab=1: 5402 条（建设工程材料）
  tab=2: 60 条（园林绿化苗木）
  tab=3: 300 条（区县建设工程材料）

── 期间分布 ──
  period=2026-01: 1158 条 (2026-01-01 ~ 2026-01-31, 31 天)
  period=2026-02: 1158 条 (2026-02-01 ~ 2026-02-28, 28 天)
  period=2026-03: 1145 条 (2026-03-01 ~ 2026-03-31, 31 天)
  period=2026-04: 1155 条 (2026-04-01 ~ 2026-04-30, 30 天)
  period=2026-05: 1146 条 (2026-05-01 ~ 2026-05-31, 31 天)

── 耗时：79.2s（1 次浏览器启动 3.5s + 15 unit API 调用）
```