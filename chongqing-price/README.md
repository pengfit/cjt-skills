# 重庆工程造价材料信息采集

> **v0.9 (2026-07-02)**：`chongqing_collector` SyncRunner 路径切为默认（`sync.py` 不再需要 `--use-collector`），`--legacy` 走 v3 `cmd_sync`。
>
> **v0.8 (2026-07-02) 重写**：在 v0.6 基础上加 `ChongqingCollector` SyncRunner 试点；
> `run.sh` 启动脚本；`check.py` 增强（自动开 tab）；sync.py 多周期 + 多 source。
>
> **v0.6 (2026-07-02)**：3 个 source × 5 个 citywide 子分类、v4 价格模型（区间价）、
> 通用层进度跟踪、2 道保护告警。

从 [重庆市建设工程造价信息网](http://www.cqsgczjxx.org) 抓取重庆市区县材料价格数据，
通过 openclaw browser 自动化抓取页面，存储至本地 Elasticsearch，支持断点续传、
增量检测、5 个分类全量覆盖。

---

## 1. 概览

### 数据源

- **网址**：`http://www.cqsgczjxx.org/Pages/CQZJW/priceInformation.aspx`
- **3 个 source × 5 个 citywide 子分类**

| source | 中文标签 | 区县数 | 页面 div | 价格特征 |
|---|---|---|---|---|
| `district` | 区县主要材料信息价 | 35 | `gqxdfclDiv` | 7 列单值价 |
| `mortar` | 预拌砂浆信息价 | 4 | `ybsjDiv` | 7 列单值价 |
| `citywide` | 重庆市材料信息价 | 1（主城区） | `zyclDiv` | 见下表 ↓ |

**citywide 5 个子分类**（左侧类目切换，实际原站仅 3 个分类有数据）：

| category | 列数 | 价格特征 | 源站现状 |
|---|---|---|---|
| 建安工程材料 | 7 | 单值价 | ✅ 有数据 |
| **园林绿化工程材料** | **11** | **区间价**（"115-173 元/株"）+ 全冠/全干特殊值 | ✅ 有数据（v4.1 重点）|
| 绿色、节能建筑工程材料 | 7 | 单值价 | ✅ 有数据 |
| 装配式建筑工程成品构件 | 7 | 单值价 | ⚪ 原站无数据 |
| 城市轨道交通工程材料 | 7 | 单值价 | ⚪ 原站无数据 |

> 后两个分类页面存在但未发布任何材料条目，抓取预期为空。

### 当前生产状态（截至 2026-07-02）

- ODS 数据：**8552 条**（citywide 5639 / district 2638 / mortar 275）
- 进度文档：242 条（180 district + 42 citywide + 20 mortar，35 个 county）
- 区间价记录：**940 条**（is_range=true）
- 当前已采集到 **2026年05月**（源站 06 月份尚未发布）
- **v0.9 默认路径**：重庆接入 `gov_price_etl.collectors.base.SyncRunner` 抽象基类，
  `sync.py` 默认走 `ChongqingCollector`；`--legacy` 走 v3 `cmd_sync`（逃生通道）
- **v0.8 生产试跑**（run_id=`v08_pilot_full_20260702`，5 个月全量）：
  - district：175 county 全 completed
  - mortar：20 county 全 completed
  - citywide：15 subcategory 全 completed（仅 3 个有数据的分类 × 5 月）
  - 注："装配式"和"城市轨道"两个 citywide 分类原网站无数据，ES progress 里 status=error 实为预期空

---

## 2. v0.9 更新要点（2026-07-02）

### Collector 切默认路径

`sync.py` 不再需要 `--use-collector` flag，`--legacy` 走 v3 `cmd_sync`（仅作逃生通道）。

```bash
# 默认走 Collector（推荐）
python3 commands/sync.py --tab-id t1 --source all --period "2026年05月"

# Collector 验证用：仅跑前 5 个工作单元
python3 commands/sync.py --tab-id t1 --source all \
  --max-units 5 --periods "2026年05月"

# v3 兼容（仅 Collector 异常时备用）
python3 commands/sync.py --tab-id t1 --legacy --source all --period "2026年05月"
```

### v0.8 生产试跑结果

2026-07-02 用 `v08_pilot_full_20260702` 跑 5 个月全量（district + mortar + citywide）：
- ✅ district 175 county + mortar 20 county 全 completed
- ✅ citywide 5 × 3 = 15 subcategory 全 completed（建安/园林/绿色节能 3 个有数据分类）

> "装配式建筑工程成品构件"和"城市轨道交通工程材料"两个分类在原网站页面存在但未发布任何材料数据，
> collector 抓取结果为空属预期（ES progress 文档 status=error 是因"无数据可写"，不是 bug）。

### v0.8 新增基础设施

- `chongqing_collector.py`：用 `gov_price_etl.collectors.base.SyncRunner` 抽象基类重构主流程
- `run.sh`：启动脚本封装
- `check.py`：browser tab 不存在时自动 `openclaw browser open`

### run.sh 启动脚本

```bash
cd ~/.openclaw/workspace/skills/chongqing-price
./run.sh sync   --tab-id t1 --source all --period "2026年05月"
./run.sh check
./run.sh status
./run.sh test
```

### check.py 增强

- browser tab 不存在 → 主动调用 `openclaw browser open`（cron 友好）
- 返回 `tabId` 而非 `targetId`（与 sync.py 一致）
- **v0.9 新增 check_log 写入**：检测结果写入 `chongqing_price_check_log` 索引（`_id = check_{YYYY-MM-DD}` 幂等），供 dashboard /sync 顶部“最近检查”卡片读取

---

## 3. v0.6 更新要点（2026-07-02）

### P0 · 进度跟踪统一

- 委托 `gov_price_etl.indexer.ensure_progress_index` 创建 ES progress 索引
- **`_id` 标准化**（v0.6 之前是单下划线 `run_id_county`，现在是双下划线）：
  - 区县进度：`{run_id}__{source}__{county}__{period}`
  - run 汇总：`{run_id}__summary__{period}`
- 老 `_id` 文档保留兼容（dashboard 按 `last_updated:desc` 读，不依赖 `_id`）

### v4.1 · 园林景观 11 列 + 区间价解析

- 区间价 `"115-173 元/株"` → `price_min=115, price_max=173, price_range="115-173", is_range=true`
- 单值价 `"3353.98 元/m³"` → `price_min=3353.98, price_max=0, price_range="3353.98", is_range=false`
- "全冠" / "全干" 特殊值（价格留空但条目有效）→ `price_min=0, notes="全冠"`
- 解析委托到 `gov_price_etl.parse_price.parse_interval_price`

### 2 道保护告警（防 silent 漏抓）

- **保护 1：园林景观列数自检** — 原站表格列数从 11 变 10 或更少时，跳过 + WARN（不入库）
- **保护 2：价格解析失败告警** — 园林景观价格列有原文但 `price_min=0` 时，打印 WARN（仍入库，但 `_is_price_valid` 会过滤不进 DWS）

### 通用层依赖（hard 强制）

`write_es.py` 强依赖两个通用层函数（找不到直接 raise）：

```python
from gov_price_etl.parse_price import parse_interval_price as _parse_interval_price
from gov_price_etl.indexer import ensure_progress_index as _ensure_progress_index
```

部署 chongqing-price 时必须先部署 `gov-price-etl` skill 到 `~/.openclaw/workspace/skills/gov-price-etl`。

---

## 4. 项目结构

```
chongqing-price/
├── config.yml                    # ES / 站点 / 同步配置
├── .chongqing_sync_progress.json # 本地进度（断点续传）
├── run.sh                        # 启动脚本（sync/status/test/check）
├── skill.yml                     # skill 注册信息（dashboard registry 读取）
└── commands/
    ├── sync.py               # 同步入口（默认 Collector；--legacy 走 v3 cmd_sync）
    ├── write_es.py           # 核心：浏览器自动化 + ES 写入 + 进度跟踪（v3 fallback）
    ├── chongqing_collector.py# v0.8+ 默认：SyncRunner 抽象基类化
    ├── check.py              # 增量检测（页面解析 + 后台 sync）
    ├── status.py             # 查看本地/ES 进度
    ├── test.py               # 测试 ES 连接
    └── utils.py              # load_config
```

---

## 5. 快速开始

### 前提条件

openclaw browser 必须已打开目标页面（或 `check.py` 自动打开）：

```bash
# 查看已打开的标签页
openclaw browser tabs

# 打开目标页面（如尚未打开）
openclaw browser open "http://www.cqsgczjxx.org/Pages/CQZJW/priceInformation.aspx"
```

获取 tab ID（如 `t1`），后续命令需要传入 `--tab-id`。

### 同步命令

```bash
cd ~/.openclaw/workspace/skills/chongqing-price

# 全量同步（指定周期和 tab）
python3 commands/sync.py --tab-id t1 --period "2026年05月"

# 多周期批量同步（v3+）⭐
python3 commands/sync.py --tab-id t1 --periods "2026年01月,2026年02月,2026年03月,2026年04月,2026年05月"

# 全 3 source + 全 5 子分类一次跑（推荐 cron 用法）
python3 commands/sync.py --tab-id t1 --source all --period "2026年05月"

# 指定单一 source
python3 commands/sync.py --tab-id t1 --source mortar --period "2026年05月"
python3 commands/sync.py --tab-id t1 --source citywide --period "2026年05月"

# 重新开始（清除本地进度文件）
python3 commands/sync.py --tab-id t1 --reset --period "2026年05月"

# 增量检测 + 自动触发同步（后台运行）
python3 commands/check.py
```

### 查看状态

```bash
# 查看本地 + ES 进度
python3 commands/status.py

# 测试 ES 连接
python3 commands/test.py

# 初始化 ES 索引（首次部署）
python3 commands/write_es.py init
```

---

## 6. 数据字段（v4 ODS）

| 字段 | 类型 | 说明 |
|---|---|---|
| `breed` | text/keyword | 材料名称 |
| `spec` | text/keyword | 规格型号 |
| `unit` | keyword | 单位 |
| **`price_min`** | float | **价格下限**（区间价取左值，单值价取主价格） |
| **`price_max`** | float | **价格上限**（区间价取右值，单值价为 0） |
| **`price_range`** | keyword | **价格原文**（"115-173" 或 "3353.98"） |
| **`is_range`** | boolean | **是否区间价**（true=区间，false=单值） |
| `is_tax` | keyword | 含税/不含税 |
| `notes` | text | 备注（"全冠"/"全干" 等特殊值写这里） |
| `period` | keyword | 业务期（"2026年05月"） |
| `period_start` | date | 周期起始日（2026-05-01） |
| `period_end` | date | 周期结束日（2026-05-31） |
| `period_days` | integer | 周期天数 |
| `month` | keyword | 业务期月份（YYYY-MM） |
| `published_at` | date | 源站页脚公布日期 |
| `province` | keyword | "重庆" |
| `city` / `county` | keyword | 区县名（主城区 / 万州区 等） |
| `area_code` | keyword | 同 county |
| `category` | keyword | 5 个 citywide 子分类（其他 source 留空） |
| `source` | keyword | district / mortar / citywide |
| `code` | keyword | 源站材料编码 |
| `update_date` | date | 数据日期（YYYY-MM-DD） |
| `create_time` | date | 入库时间 |

> ODS mapping 来自 `gov_price_etl.build_ods_mapping`（45 字段），`dynamic=strict` 保护。
> 新增字段必须先扩 `_ODS_BASE_FIELDS`，不允许动态推断。

---

## 7. ES 索引

| 索引 | mapping 来源 | 说明 |
|---|---|---|
| `ods_material_chongqing_price` | `gov_price_etl.build_ods_mapping` | 材料价格数据（dynamic=strict） |
| `material_chongqing_price_sync_progress` | `gov_price_etl.build_progress_mapping` | 同步进度（dynamic=strict） |

> **命名约定例外**：chongqing 的 progress_index 命名跟其他 skill 不一致（不带 `ods_` 前缀），
> 是历史遗留。`skill.yml` 显式指定 `progress_index` 字段覆盖默认推断。

### 进度文档 schema（v0.6）

```
_id: {run_id}__{source}__{county}__{period}  (区县进度)
_id: {run_id}__summary__{period}              (run 汇总)

{
  "run_id": "cq_rerun_landscape_v4b",
  "source": "district",
  "area": "区县材料-万州区",
  "period": "2026年05月",
  "status": "completed",       # running / completed / error / interrupted
  "current_page": 1,
  "total_pages": 1,
  "docs_written": 15,
  "percent": 100.0,
  "duration_sec": 23.4,
  "last_updated": "2026-07-02 08:42:02",
  "error": ""
}
```

---

## 8. 同步命令详解

### sync.py — 同步入口（参数透传给 `write_es.cmd_sync`）

```bash
python3 commands/sync.py [选项]
```

| 参数 | 默认值 | 说明 |
|---|---|---|
| `--tab-id` | （空） | 浏览器 tab ID（必填，可用 `t1`） |
| `--period` | `2026年01月` | 单周期（兼容旧参数） |
| `--periods` | （空） | **多周期，逗号分隔**，如 `"2026年01月,2026年02月"` |
| `--source` | `all` | district / mortar / citywide / all |
| `--reset` | false | 清除本地进度文件，重新开始 |
| `--run-id` | 自动 | 指定 run_id（默认 `cq_<timestamp>`） |
| `--legacy` | false | **v3 兼容**：走原 `cmd_sync`（逃生通道），默认走 Collector |
| `--max-units` | None | **Collector 路径**：仅跑前 N 个工作单元（验证用） |

**流程**：
1. 初始化 ES 索引（已存在走 noop）
2. 聚焦指定 browser tab，点击"材料信息价"标签页
3. 遍历 `--periods` 中每个周期 × 每个 source
4. district/mortar 模式：遍历 35/4 个区县 → 翻页提取 → 写入 ES → 更新进度
5. citywide 模式：主城区下切换 5 个 category → 翻页提取
6. 每个区县完成立即写入 progress 文档（断点续传）
7. 支持 Ctrl+C 中断，保存本地进度后退出

### write_es.py 子命令

```bash
# 初始化 ES 索引（幂等）
python3 commands/write_es.py init

# 写入数据（供 browser 侧 / 单元测试调用）
python3 commands/write_es.py write <run_id> <county> <period> <result_json>

# 更新单条区县进度
python3 commands/write_es.py progress <run_id> <county> <period> <page> <total_pages> <docs_written> <status> [error] [duration]

# run 汇总
python3 commands/write_es.py summary <run_id> <target_period> <total_counties> <completed> <total_docs> <duration_sec>

# 完整同步流程（CLI 方式）
python3 commands/write_es.py sync --tab-id t1 [--period|--periods] [--source] [--reset]
```

### check.py — 增量检测

```bash
python3 commands/check.py
```

自动判断是否需要触发同步（无需参数）：
1. 检查 ES 最新已采集周期（按 `create_time desc`）
2. 检查 browser tab（不存在则主动打开 + 聚焦）
3. 提取页面当前年份（`select.selectedIndex.text`）+ class=`month` 的月份列表
4. 取源站最新月份 → 与 ES 最新周期对比
5. 源站有更新 → 打印 `[重庆] 🔔 有更新！...`（不直接触发，留给 cron 决策）
6. 无更新 → 打印 `[重庆] ✅ 无新数据`

> **v0.6 注意**：本脚本对比的是 `period` 字段（YYYY-MM-DD 格式），**不再读
> `config.yml.sync.last_period`**（之前是按年，现在是按月对比）。

### status.py — 查看进度

```bash
python3 commands/status.py
```

输出：
- **本地进度文件**（`.chongqing_sync_progress.json`）：run_id、已完成区县数、保存时间
- **ES 进度索引**（`material_chongqing_price_sync_progress`）：各区县最新状态（按 `last_updated desc`，取最近 10 条）
- config 中的 `last_period`（仅供参考，check.py 不再用）

### test.py — ES 连接测试

```bash
python3 commands/test.py
```

---

## 9. 保护机制（2026-07-02 加）

防源站表格格式变化导致 silent 漏抓。**只在园林绿化工程材料类目触发**，其他类目不受影响。

### 保护 1：园林景观列数自检

```python
if is_landscape and len(row) < 11:
    counters["col_count_short"] += 1
    continue  # 跳过，不入 ES
```

- **触发条件**：原站园林景观表列数从 11 变 10 或更少
- **行为**：跳过 + 打印 WARN+sample
- **防什么**：原站表头缩减，silent 漏抓新品种

### 保护 2：价格解析失败告警

```python
_KNOWN_SPECIAL = {"全冠", "全干"}
if is_landscape and price_str and price_str != "0" and price_min == 0 and price_str not in _KNOWN_SPECIAL:
    counters["price_parse_fail"] += 1
```

- **触发条件**：园林景观价格列有原文（如 "0.2万/棵"、"面议"、"200元/株"），但
  `parse_interval_price` 没解出有效数字（且不是"全冠/全干"）
- **行为**：打印 WARN+sample（仍写入 ES，`price_min=0` 会被 `_is_price_valid` 过滤不进 DWS）
- **防什么**：原站加新单位/格式

### 已知合法特殊值（白名单）

| 原文 | 含义 | 处理 |
|---|---|---|
| `全冠` | 苗木全冠移植 | `price_min=0, notes="全冠"` |
| `全干` | 苗木全干规格 | `price_min=0, notes="全干"` |
| `0` | 空价格（无报价） | `price_min=0` |
| ``（空字符串） | 缺价格 | `price_min=0` |

> 6 月份 cron 自动跑时，监控 sync log 看保护告警即可。
> 若出现保护触发但**不是**已知情况，需检查源站表格格式是否变化。

---

## 10. 断点续传 + 进度跟踪（v0.6）

### 两层进度

1. **本地进度文件** `.chongqing_sync_progress.json`：
   - 字段：`done`（已完成 county 列表，按 source 分组）+ `run_id` + `saved_at`
   - 作用：sync 进程内断点续传（中断后重启继续）
   - `--reset` 清除

2. **ES progress 索引** `material_chongqing_price_sync_progress`：
   - 字段：每区县每 period 每 source 一条文档 + 每个 run 一条 summary
   - 作用：跨进程可见性（dashboard 实时显示）
   - **v0.6 委托到 `gov_price_etl.indexer.ensure_progress_index`**

### _id 规则（v0.6 标准化）

```
区县进度: {run_id}__{source}__{county}__{period}    # 双下划线
run 汇总: {run_id}__summary__{period}
```

老 `_id`（单下划线 `run_id_county`）继续兼容（dashboard 按 `last_updated desc` 读），
新 run 自动按新格式写。

---

## 11. 配置（config.yml）

```yaml
es:
  host: http://localhost:59200                  # ES 地址
  index: ods_material_chongqing_price           # ODS 数据索引
  progress_index: material_chongqing_price_sync_progress  # 进度索引（注意无 ods_ 前缀）
  sync_log_index: ods_chongqing_price_sync_log  # 同步日志索引（保留但 v0.6 未启用）
  timeout: 30

site:
  url: http://www.cqsgczjxx.org/Pages/CQZJW/priceInformation.aspx

sync:
  last_period: '2026'                           # 仅供参考，check.py 不再读此字段
```

### skill.yml（dashboard registry 用）

```yaml
key: chongqing
label: 重庆
ods_index: ods_material_chongqing_price
progress_index: material_chongqing_price_sync_progress
progress_mode: county                           # dashboard 按 county 模式分组
county_field: area                              # progress 文档主字段（不是 county）
summary_marker: "全部完成"                       # 过滤汇总占位
expand_label: "▾ 区县详情"
```

---

## 12. 故障排查

### 同步失败

```bash
# 1. 确认浏览器状态
openclaw browser status
openclaw browser tabs

# 2. 手动聚焦 tab 重试
python3 commands/sync.py --tab-id t1 --period "2026年05月"

# 3. 跳过本地进度重跑
python3 commands/sync.py --tab-id t1 --period "2026年05月" --reset
```

### ES 数据验证

```bash
# 文档总数
curl -s "http://localhost:59200/ods_material_chongqing_price/_count"

# 按区县 + source 聚合
curl -s "http://localhost:59200/ods_material_chongqing_price/_search?size=0" \
  -H "Content-Type: application/json" \
  -d '{"aggs":{"by_county_source":{"terms":{"field":"county","size":50},"aggs":{"by_source":{"terms":{"field":"source"}}}}}}'

# 按周期 + category 聚合（看 5 子分类分布）
curl -s "http://localhost:59200/ods_material_chongqing_price/_search?size=0" \
  -H "Content-Type: application/json" \
  -d '{"aggs":{"by_period":{"terms":{"field":"period","size":20},"aggs":{"by_category":{"terms":{"field":"category"}}}}}}'

# 区间价占比
curl -s "http://localhost:59200/ods_material_chongqing_price/_search?size=0" \
  -H "Content-Type: application/json" \
  -d '{"aggs":{"by_range":{"terms":{"field":"is_range"}}}}'
```

### 进度跟踪查询

```bash
# 最新 10 条进度
curl -s "http://localhost:59200/material_chongqing_price_sync_progress/_search?size=10&sort=last_updated:desc" \
  | python3 -m json.tool

# 错误记录
curl -s "http://localhost:59200/material_chongqing_price_sync_progress/_search?size=20" \
  -H "Content-Type: application/json" \
  -d '{"query":{"term":{"status":"error"}},"sort":[{"last_updated":"desc"}]}' \
  | python3 -m json.tool
```

### 通用层依赖缺失

```bash
# write_es.py 会 hard raise：
# "chongqing-price 依赖 gov_price_etl.parse_price，
#  未在 ~/.openclaw/workspace/skills/gov-price-etl 找到。"
# 解决：确认 gov-price-etl skill 已部署到上述路径
ls ~/.openclaw/workspace/skills/gov-price-etl/gov_price_etl/parse_price.py
ls ~/.openclaw/workspace/skills/gov-price-etl/gov_price_etl/indexer.py
```

### 清空数据并重置

```bash
# 清空 ODS
curl -s -XPOST "http://localhost:59200/ods_material_chongqing_price/_delete_by_query" \
  -H "Content-Type: application/json" -d '{"query":{"match_all":{}}}' | python3 -m json.tool

# 清空 progress
curl -s -XPOST "http://localhost:59200/material_chongqing_price_sync_progress/_delete_by_query" \
  -H "Content-Type: application/json" -d '{"query":{"match_all":{}}}' | python3 -m json.tool

# 删除本地进度
rm -f .chongqing_sync_progress.json

# 重新初始化 ES 索引 + 全量同步
python3 commands/write_es.py init
python3 commands/sync.py --tab-id t1 --period "2026年05月" --source all --reset
```

### 后台同步日志

```bash
tail -f /tmp/chongqing-incremental-sync-*.log
```

---

## 13. 依赖

- Python 3.10+
- openclaw（browser 自动化）
- requests、pyyaml、elasticsearch
- **gov-price-etl skill**（部署在 `~/.openclaw/workspace/skills/gov-price-etl`）

---

## 14. 区县清单（district source 35 个 + mortar 4 个 + citywide 5 子分类）

**district（35 个）**：主城区、万州区、涪陵区、黔江区、长寿区、江津区、合川区、永川区、
南川区、梁平区、城口县、丰都县、垫江县、忠县、开州区、云阳县、奉节县、巫山县、巫溪县、
石柱县、秀山县、酉阳县、大足区、綦江区、万盛经开区、双桥经开区、铜梁区、璧山区、
彭水县1、彭水县2、彭水县3、荣昌区1、荣昌区2、潼南区、武隆区

**mortar（4 个）**：主城区、永川区、綦江区、璧山区

**citywide（1 个）**：主城区（5 个子分类：建安工程、园林绿化、绿色节能、装配式、城市轨道）

**citywide 5 子分类**：建安工程材料 / 园林绿化工程材料 / 绿色、节能建筑工程材料 / 装配式建筑工程成品构件 / 城市轨道交通工程材料

> 注：彭水县分 3 个价格区（1/2/3），荣昌区分 2 个价格区（1/2）。

---

## 15. 变更日志

| 版本 | 日期 | 主要变更 |
|---|---|---|
| **v0.9** | 2026-07-02 | `chongqing_collector` 切为默认路径；`--legacy` 走 v3 `cmd_sync`；`check.py` 加 check_log ES 写入（供 dashboard /sync 顶部卡片） |
| **v0.8** | 2026-07-02 | 新增 `chongqing_collector.py` SyncRunner 试点（`--use-collector`）；`run.sh` 启动脚本；`check.py` 自动开 tab；sync.py 多周期 + 多 source |
| **v0.6** | 2026-07-02 | 进度跟踪切到 gov_price_etl 通用层；_id 标准化（双下划线）；园林景观 11 列 + 区间价；2 道保护告警 |
| v0.5 | 2026-06-28 | 切到通用层 parse_price + build_ods_mapping（45 字段，dynamic=strict）|
| v0.4 | 2026-06-15 | 多周期 `--periods` + 4 道保护告警 + 进度 percent 字段 |
| v0.3 | 2026-05 | citywide 5 子分类扩展 + 增量续传 |
| v0.2 | 2026-04 | 切到 openclaw browser 自动化（旧 selenium 弃用）|
| v0.1 | 2026-03 | 初版（仅 district source）|