---
name: gov-price-etl
description: "政府材料价格数据入仓 ETL（v0.10，2026-07-22）：17 个城市 ODS→DWD 三段式（DB 5 段式 + AI 攒批）+ DWD→DWS 三段式（attr / 本地规则库 / AI 串行），v3 GB 章节 4 层分类体系（8 L1 / 42 L2 / 145 L3），AI 调用走 Dify workflow。attr 治本闭环 L2 封堵层（与 NORM L1 净化组合）；v0.10 起 DWD→DWS 阶段 3 AI ok=false 也入 DWS，标 ai_ok/ai_failed_reason 双 audit 字段。"
---

# gov-price-etl

政府材料价格数据入仓 ETL，**v0.6（2026-06-19）**：
- **ODS → DWD**：**二段式**（先 DB 5 段式后 AI 攒批）— 阶段 1 breed_l3_map 精确 → 阶段 2 Jaccard 模糊 → 阶段 3 L4 pattern → 阶段 4 unit 兜底 → 阶段 5 AI 攒批（classify_v3_batch，未命中时 Dify workflow）
- **DWD → DWS**：**三段式**（attr / 本地规则库 / AI 串行）— 阶段 1 已有 attr → 阶段 2 走 breed_spec_rules.db → 阶段 3 Dify AI 攒批

v1 大类字典（breed_category_rules.db）+ v1 26 类分类法已废（2026-06-16），统一用 v3 4 层分类（8 L1 / 42 L2 / 145 L3，按 GB 50854-2013 / GB/T 50856-2024 / GB 50857-2013 / GB 50858-2013 重建）。AI 调用 2026-06-18 起统一走 Dify workflow API（替代 OpenClaw gateway）。

---

## 数据流（三段式，节点明确）

```
┌─────────────────────────────────────────────────────────────────────┐
│  ODS 层                                                             │
│  ods_material_xian_price     ─┐                                     │
│  ods_material_sichuan_price    ─┤                                   │
│  ods_material_chongqing_price  ─┤                                  │
│  ods_material_jinan_price       ─┤                                  │
│  ods_material_rizhao_price      ─┤                                 │
│  ods_material_henan_price       ─┤                                 │
│  ods_material_heze_price        ─┘                                 │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│  ODS → DWD 阶段（pipeline.etl.etl_city）                          │
│                                                                       │
│  ┌─ 阶段 1: 本地 breed_category_rules.db 精确查表 ────────┐        │
│  │  SQL: SELECT category WHERE breed = ?                       │     │
│  │  命中 → category_v2_source='db_exact_v3'                    │     │
│  └───────────────────────────────────────────────────────┘        │
│                                    ↓ 未命中                          │
│  ┌─ 阶段 2: 本地 DB + Jaccard 模糊召回 ─────────────────┐        │
│  │  倒排精确包含 / Dice + 加权 Jaccard (阈值 0.45)         │     │
│  │  命中 → category_v2_source='db_fuzzy_v3'                  │     │
│  └───────────────────────────────────────────────────────┘        │
│                                    ↓ 未命中                          │
│  ┌─ 阶段 3: AI classify_breed_batch 串行批次分类 ──────┐          │
│  │  攒批 20 条/批 → 逐批调 AI → 回写 DWD                   │       │
│  │  命中 → category_v2_source='ai'                         │       │
│  │  失败兜底 '其他' → category_v2_source='ai_fallback'      │      │
│  └───────────────────────────────────────────────────────┘        │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│  DWD 层（带 category_v2_source 字段，无 category_stage）             │
│  dwd_xian_price / dwd_sichuan_price / ...                            │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│  DWD → DWS 阶段（pipeline.dws_sync._dwd_to_dws_three_stages）      │
│                                                                       │
│  ┌─ 阶段 1: DWD attr 非空 → 直接同步 ─────────────────┐            │
│  │  ODS→DWD 时已解析过，attr 已有值                       │         │
│  │  不调本地规则库、不调 AI                                  │        │
│  │  → attr_source='etl'                                    │         │
│  └───────────────────────────────────────────────────────┘        │
│                                    ↓ DWD attr 为空                  │
│  ┌─ 阶段 2: 本地 breed_spec_rules.db 解析 ────────────┐            │
│  │  BaseParseSpec.parse()（vector_store 召回）            │         │
│  │  命中 → 回写 DWD attr + 同步 DWS                       │         │
│  │  → attr_source='local_db'                              │         │
│  └───────────────────────────────────────────────────────┘        │
│                                    ↓ 未命中                          │
│  ┌─ 阶段 3: AI batch_spec_parse 串行解析 ─────────────┐           │
│  │  按 (breed, spec) 去重，20 条/批串行调 AI              │        │
│  │  命中 → 回写 DWD attr（ai_ok=true）+ 同步 DWS          │         │
│  │  → attr_source='ai' / ai_ok=true                       │         │
│  │  失败/Dify 拒解析 → 入 DWS（不回写 DWD），标 audit     │        │
│  │  → attr_source='ai_fallback' / ai_ok=false            │        │
│  │    + ai_failed_reason（详 2026-07-22 道友需求：         │        │
│  │    ok=false 也入库，便于运营按 ai_ok=false 巡检）      │        │
│  └───────────────────────────────────────────────────────┘        │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│  DWS 层（带 attr_source 字段）                                       │
│  dws_xian_price / dws_sichuan_price / ...                            │
└─────────────────────────────────────────────────────────────────────┘
```

**关键约定**：
- ODS→DWD 阶段：每条 DWD 文档带 `category_v2_source`（`db_exact_v3` / `db_fuzzy_v3` / `ai` / `ai_fallback`）。**当前实现不写 stage 字段**——`category_stage` 在 SKILL.md 早期版本里描述过，但代码未落地，命中阶段只能从 `category_v2_source` 的后缀推断（`db_*_v3` = DB 阶段 1/2，剩余归 AI 阶段 3）
- DWD→DWS 阶段：每条 DWS 文档带 `attr_source`（`etl` / `local_db` / `ai` / `ai_fallback`）
- AI 调用严格**串行**（默认 20 条/批，逐批调用，批间 sleep 0.5s 限速），不并发

---

## 目录结构（v0.3 重构后）

```
gov-price-etl/
├── SKILL.md
├── SPEC_RULES.md              # parse_spec 规则库使用说明
├── README.md
├── config.yml                # ES 连接配置
├── data/                      # 数据文件集中
│   ├── breed_spec_rules.db    # 规格解析规则（SQLite）—— DWD→DWS 阶段 2 使用
│   ├── breed_category_rules.db # 品种分类规则 —— ODS→DWD 阶段 1+2 使用
│   ├── category_in_system.json # 分类体系映射
│   └── ai_cache.db            # AI 调用缓存（.gitignore）
├── gov_price_etl/             # 真正的包
│   ├── __init__.py
│   ├── paths.py            # 路径中心
│   ├── config.py           # 配置 + CITY_CONFIGS
│   ├── es_client.py        # ES 客户端 + bulk
│   ├── mappings.py         # DWD/DWS mappings
│   ├── indexer.py          # 索引模板 / ensure_indices
│   ├── transform/
│   │   ├── __init__.py
│   │   ├── clean.py        # 品种/规格/单位/价格清洗
│   │   ├── doc.py          # transform_doc ODS→DWD（不含 AI）
│   │   └── attr_utils.py   # attr 字段提取/转换
│   ├── parse_spec/         # 规格解析引擎
│   │   ├── __init__.py     # get_parser() 入口
│   │   ├── base.py         # BaseParseSpec 基类（仅查 breed_spec_rules.db）
│   │   ├── xian.py / sichuan.py / henan.py
│   │   └── rules/
│   │       ├── _attrs.py
│   │       └── vector_store.py  # SQLite 向量规则库
│   ├── classify/           # 品种分类引擎（三段式）
│   │   ├── __init__.py     # 导出 classify_breed_db_exact/db_fuzzy/ai/with_stages
│   │   ├── system.py       # 分类体系映射
│   │   └── rules/
│   │       ├── _core.py    # 阶段 1: DB 精确 / 阶段 2: DB+Jaccard / 阶段 3: AI
│   │       └── jaccard.py  # Jaccard 召回引擎
│   ├── ai/                 # AI 服务
│   │   ├── __init__.py
│   │   ├── service.py      # parse_spec_batch / classify_breed_batch（20条/批串行）
│   │   ├── prompts.py
│   │   └── cache.py        # SQLite 缓存
│   └── pipeline/
│       ├── __init__.py
│       ├── etl.py          # ODS→DWD 三段式（阶段1+2内置 + 阶段3 AI 攒批回写）
│       └── dws_sync.py     # DWD→DWS 三段式（阶段1 attr+阶段2 local_db+阶段3 ai）
│   └── collectors/         # 采集器抽象基类（v0.8+）
│       ├── __init__.py
│       ├── base.py         # SignalHandler / LocalProgressStore / SyncRunner
│       └── client.py       # ES 写入工具（bulk 封装）
├── cli/                        # 入口脚本
│   ├── etl.py                  # ODS → DWD → DWS 主入口
│   ├── sync_dws.py             # DWD → DWS 同步（--mode quick|plain|ai）
│   └── reload_prompts.py       # 重读 prompts.yml
└── prompts.yml                 # AI Prompt 模板
```

---

## API 速查

### collectors（采集器抽象基类，v0.8+）

供各城市 sync.py 共用「**多周期 × 多 source × 断点续传 × SIGINT × 进度上报**」基础设施。设计原则：**接口稳定不强迁**——各城市可独立继承使用，不必改造现有 sync.py。

```
SignalHandler        SIGINT 中断上下文（Ctrl+C 安全）
LocalProgressStore   本地 JSON 进度存储（key 形状灵活）
SyncRunner (ABC)     主流程基类（子类重写钩子）
```

**SyncRunner 钩子**：

| 钩子 | 默认 | 用途 |
|---|---|---|
| `_list_work_units()` | abstract | 扁平化所有工作单元（如 `(source, county, period)` 三元组）|
| `_process_one(unit)` | abstract | 处理单个单元：抓 + 解析 + 写 ES，返回 `(docs_count, status)` |
| `_on_unit_start(unit)` | print | 单元开始钩子（可重写）|
| `_on_unit_done(unit, n, status)` | print | 单元完成钩子（可重写）|
| `_compute_unit_key(unit)` | str(unit) | 本地进度 key（可重写）|

**已接入城市**：

- **chongqing**（v0.8 试点，v0.9 默认路径）—— `chongqing_collector.py` 用 SyncRunner 重构原 cmd_sync 主流程
- 其他 16 城按需渐进接入，不强制

**架构详见** [README.md#采集器抽象基类](./README.md#采集器抽象基类)

### classify（品种分类，v3 5 段式，ODS→DWD 用）

```python
from gov_price_etl.classify import (
    classify_v3,        # 单条 5 段式（阶段 1-3 DB 命中即返回，阶段 4 unit 兜底，阶段 5 是 ai_batch）
    classify_v3_batch,  # 批量 AI 攒批入口（pipeline.etl 第二轮用，DB 优先 + 未命中调 Dify + 写回 DB）
    close_singleton,    # 关 DB 连接（CLI 退出时调）
)
```

### pipeline（DWD→DWS 三段式 + 配置常量）

```python
from gov_price_etl.pipeline import (
    # ODS → DWD
    etl_city, run_etl,
    AI_CATEGORY_BATCH_SIZE,         # 默认 20（AI 串行批次大小）
    AI_CATEGORY_BATCH_SLEEP_S,      # 默认 0.5（批间限速）
    # DWD → DWS
    sync_dws, sync_dws_with_ai, sync_dws_plain, sync_dws_quick,
    _dwd_to_dws_three_stages,       # 三段式核心
    _parse_spec_local,              # 阶段 2: 本地规则库解析
    _ai_parse_specs_serial,         # 阶段 3: AI 串行解析
    AI_PARSE_BATCH_SIZE,            # 默认 20
    AI_PARSE_BATCH_SLEEP_S,         # 默认 0.5
)
```

---

## 命令与用法

### 1. 主 ETL（ODS → DWD + DWS 同步，**三段式**）

```bash
cd ~/.openclaw/workspace/skills/gov-price-etl

# 全量 ETL（所有城市，跑三段式）
./cli/etl.py

# 只处理指定城市
./cli/etl.py --city sichuan

# 增量模式（按 update_date）
./cli/etl.py --incremental --since 2026-05-01

# 只清洗指定分类
./cli/etl.py --category 瓦

# 批量确认规则（清洗指定分类时：规则已全部确认，直接标记 needs_spec_parse=False，不走 AI）
./cli/etl.py --category 瓦 --mark-done

# 预览（前100条，不写入 ES）
./cli/etl.py --dry-run

# 只跑 ETL（跳过 DWS 同步）
./cli/etl.py --no-dws

# 指定批量大小
./cli/etl.py --batch-size 1000
```

**输出示例**：
```
[ETL] xian: ods_material_xian_price (23,404 条) → dwd_xian_price
  [STG3 AI] xian: 待 AI 分类品种 12 种 (500 条)
  [STG3 AI] 批量回写: 更新 500/500 条，错误 0
  [ETL] xian 完成: → dwd_xian_price | etled=22904, failed=0, ai_updated=500
  [DWS+AI] xian: dwd_xian_price → dws_xian_price (23,404 条)
  [DWS+AI] xian 完成: s1(etl)=18400, s2(local_db)=4504, s3(ai)=500, failed=0
```

### 2. 独立 DWS 同步（DWD → DWS，**三段式**）

```bash
# Quick 模式：只同步已有 attr 的（默认，不调 AI；等价于阶段 1）
./cli/sync_dws.py --mode quick

# Plain 模式：spec 非空即同步（不调 AI）
./cli/sync_dws.py --mode plain --city xian

# AI 模式：缺 attr 走阶段 2（本地规则库）→ 阶段 3（AI 串行）
./cli/sync_dws.py --mode ai --city xian

# 预览（不写入）
./cli/sync_dws.py --mode ai --dry-run

# 指定批量大小
./cli/sync_dws.py --mode quick --batch-size 2000
```

### 3. 规格解析测试

```bash
PYTHONPATH=src python3 -c "
from gov_price_etl.parse_spec import get_parser
p = get_parser('xian')
print(p.parse_spec('H100~H250 Q235B'))
print(p.parse_spec('400*(800+250)'))
print(p.parse_spec('δ=4.5'))
print(p.parse_spec('D720*8'))
"
```

### 4. 品种分类测试（v3 5 段式）

```bash
python3 -c "
from gov_price_etl.classify import classify_v3
for breed in ['圆钢', '螺纹钢', '矮牵牛', 'xxYYZZ未知']:
    v2 = classify_v3(breed, spec='', unit='', breed_clean=breed)
    l3 = v2.get('l3', '?')
    src = v2.get('category_v2_source', '?')
    conf = v2.get('category_v2_confidence', 0.0)
    name = v2.get('name_l3', v2.get('name_l1', '?'))
    print(f'{breed:15s} → L3={l3:8s} {name:20s} (source={src}, conf={conf:.2f})')
"
```

### 5. AI Prompt 模板管理

Prompt 模板从 `gov-price-etl/prompts.yml` 加载（不是 hard-coded，也不是读 gov-price-dashboard）。

```bash
# 重读 prompts.yml（调试场景，yml 改完不需要重启 ETL）
./cli/reload_prompts.py

# 查看当前加载的所有 prompt 概览
./cli/reload_prompts.py --show
```

**prompts.yml 三个 key**：
- `fix_case` — 单条 spec → 解析规则
- `classify_breed_batch` — 批量品种 → 分类（阶段 3 使用）
- `batch_spec_parse` — 批量 spec → 解析规则（阶段 3 使用）

---

## 配置（config.yml）

```yaml
es:
  host: http://localhost:59200
  ods_index: ods_material_xian_price
  dwd_index: dwd_xian_price
  dws_index: dws_gov_price_data
  batch_size: 500

sync:
  last_update_date: ""
```

---

## 关键实现细节

### ODS→DWD 三段式（pipeline/etl.py）

```
etl_city(es_host, city, cfg)
  │
  ├─ 滚动拉 ODS（按 update_date asc）
  │
  ├─ 每条 → transform_doc() 内部调 classify_breed_with_stages(breed, use_ai=False)
  │    ├─ 阶段 1: classify_breed_db_exact(breed)     → 'db_exact_v3' / ''
  │    ├─ 阶段 2: classify_breed_db_fuzzy(breed)     → 'db_fuzzy_v3' / ''
  │    └─ 兜底: 返回 ('其他', '', '') → 标记待 AI
  │
  ├─ 阶段 1+2 命中 → 写入 DWD（带 category_v2_source）
  │
  └─ 阶段 1+2 都未命中 → 攒批 → _ai_classify_pending()
       ├─ 阶段 3: classify_breed_ai(breed, city) 串行批次（20条/批）
       └─ 回写 DWD category / category_v2_source='ai'/'ai_fallback'
```

### DWD→DWS 三段式（pipeline/dws_sync.py）

```
_dwd_to_dws_three_stages(es_host, city, cfg)
  │
  ├─ search_after 滚动拉 DWD
  │
  ├─ 每条 DWD 判断：
  │    ├─ 阶段 1: build_attr(d) 非空 → 直接同步 DWS（attr_source='etl'）
  │    ├─ 阶段 2: _parse_spec_local(spec, breed, cat, city) 命中
  │    │         → 回写 DWD attr + 同步 DWS（attr_source='local_db'）
  │    └─ 阶段 3: 攒批 → _ai_parse_specs_serial()（20条/批串行）
  │              → 回写 DWD attr + 同步 DWS（attr_source='ai'/'ai_fallback'）
  │
  └─ 输出 (s1, s2, s3, failed) 三段计数
```

### 关键字段

**DWD 文档（ODS→DWD 产物）**：

| 字段 | 类型 | 说明 |
|------|------|------|
| `breed` | text+keyword | 原始品种名 |
| `breed_clean` | keyword | 清洗后品种名 |
| `spec` | text+keyword | 原始规格 |
| `category` | keyword | 分类名称 |
| **`category_v2_source`** | **keyword** | **分类来源：`db_exact_v3`/`db_fuzzy_v3`/`ai`/`ai_fallback`** |
| `category_stage` | — | **当前未实现**（SKILL.md 早期版本描述过，代码未落地） |
| `attr` | nested | 解析后的规格属性（list of {k, v}） |
| `etl_time` | date | ETL 时间戳 |
| `source_index` | keyword | ODS 索引名 |

**DWS 文档（DWD→DWS 产物）**：

| 字段 | 类型 | 说明 |
|------|------|------|
| (DWD 全部字段) | | |
| **`attr_source`** | **keyword** | **attr 来源：`etl`/`local_db`/`ai`/`ai_fallback`** |
| **`ai_ok`** | **boolean** | **AI 阶段 3 整体调用是否成功（true=拿到有效 suggestions；false=Dify 业务失败/JSON 解析失败/AI 显式拒解析）。v0.10+：ok=false 也入 DWS，加此字段供运营按 `ai_ok=false` 巡检** |
| **`ai_failed_reason`** | **text+keyword** | **AI 失败原因摘要（截 500 字符）；`ai_ok=false` 时填。v0.10+ 加** |

### 城市配置

| 城市 | ODS 索引 | DWD 索引 | DWS 索引 |
|------|---------|---------|---------|
| xian | `ods_material_xian_price` | `dwd_xian_price` | `dws_xian_price` |
| sichuan | `ods_material_sichuan_price` | `dwd_sichuan_price` | `dws_sichuan_price` |
| chongqing | `ods_material_chongqing_price` | `dwd_chongqing_price` | `dws_chongqing_price` |
| jinan | `ods_material_jinan_price` | `dwd_jinan_price` | `dws_jinan_price` |
| rizhao | `ods_material_rizhao_price` | `dwd_rizhao_price` | `dws_rizhao_price` |
| henan | `ods_material_henan_price` | `dwd_henan_price` | `dwd_henan_price` |
| heze | `ods_material_heze_price` | `dwd_heze_price` | `dws_heze_price` |
| qingdao | `ods_material_qingdao_price` | `dwd_qingdao_price` | `dws_qingdao_price` |
| hainan | `ods_material_hainan_price` | `dwd_hainan_price` | `dws_hainan_price` |
| huhehaote | `ods_material_huhehaote_price` | `dwd_huhehaote_price` | `dws_huhehaote_price` |
| hunan | `ods_material_hunan_price` | `dwd_hunan_price` | `dws_hunan_price` |
| jiangxi | `ods_material_jiangxi_price` | `dwd_jiangxi_price` | `dws_jiangxi_price` |
| ningxia | `ods_material_ningxia_price` | `dwd_ningxia_price` | `dws_ningxia_price` |
| qinghai | `ods_material_qinghai_price` | `dwd_qinghai_price` | `dws_qinghai_price` |
| shaanxi | `ods_material_shaanxi_price` | `dwd_shaanxi_price` | `dws_shaanxi_price` |
| weihai | `ods_material_weihai_price` | `dwd_weihai_price` | `dws_weihai_price` |
| xinjiang | `ods_material_xinjiang_price` | `dwd_xinjiang_price` | `dws_xinjiang_price` |

---

## attr 治本 L2 封堵（v0.9）

ETL 层是 attr 脏数据治本闭环的**第二道防线**（治标），与 NORM 层 L1 净化（治本上游）组合形成"上游净化 + 中游封堵"双保险。

**关键实现位置**：

| 机制 | 文件 | 作用 |
|------|------|------|
| 写入前 attr 质量校验 | `transform/attr_utils.py::sanitize_attr()` | 丢弃非数值/无单位/纯描述污染值（例：wall_thickness='不分规格' / 'δ4'）|
| volume/brand 黑名单 | `transform/attr_utils.py` | 拒绝量纲不匹配和 brand=DN 错位 |
| material 描述词拒 | `transform/attr_utils.py` | 拒绝纯描述性材质词被误当 attr |
| CATCH_ALL 关键字禁 | `parse_spec/base.py::_CATCH_ALL_FORBIDDEN_KEYS` | `{volume, package_type, height_min, thickness_min, cross_section_area}` 一律不进 catch-all |
| 电缆命名标准化 | `parse_spec/cable.py` + `parse_spec/__init__.py::_CableAwareParseSpec` | GB/T 12706 电缆命名（cross_section / cores / voltage 互斥规则）|

**关键不变量**：

- L1 NORM 净化在 ETL 之后跑（数据先入 DWS，DWS 读出来再净化入 NORM）
- L2 ETL 封堵在 DWS 写入前跑（attr_utils.sanitize_attr 在 DWD→DWS 阶段被调）
- 两层独立运行、互不依赖；任一层失败不阻断另一层
- 治本核心是 L1（治标只补刀），但双层防御保证 attr 干净率 32.66% → 0%

详见 [`gov-price-normalization/SKILL.md`](../gov-price-normalization/SKILL.md) 的「L1 attr 治本」章节。

---

## v3 分类体系（4 层 GB 章节）

**结构**（按 GB 50854-2013 / GB/T 50856-2024 / GB 50857-2013 / GB 50858-2013 重建）：

- **8 L1 专业大类**：建筑工程 / 装饰装修 / 安装工程 / 市政工程 / 园林景观 / 水利工程 / 公路工程 / 其他
- **42 L2 分部工程**
- **145 L3 分项工程**
- 4 层联合主键：L1 + L2 + L3 + L4

数据源：`data/breed_category_rules.db`（SQLite）+ `data/category_in_system.json`（体系映射）。

v1 大类字典（28 类）+ v2 4 层 64 节点已于 2026-06 废止。

---

## 版本

- **v0.10**（2026-07-22）DWD→DWS 阶段 3 AI ok=false 也入 DWS：
  - `_ai_parse_specs_serial` 返回值从 2 元组扩展到 4 元组 `(attrs, src, ok, failed_reason)`
  - `_flush_ai_batch_to_dws` 移除两处拦截：`if src=="ai_fallback": continue`（AI 拒解析）+ `if not attrs: continue`（attrs 空），统计入 DWS
  - DWS mapping 新增 `ai_ok` (boolean) + `ai_failed_reason` (text+keyword) 双 audit 字段，供运营按 `ai_ok=false` 巡检拒解析文档
  - AI fallback 时仍不写 DWD attr（保持源头干净），但 DWS doc 写入以保留价格文档可检索
  - 起因：2026-07-22 道友需求，背景是 DWD 文档价格有效但 AI 拒解析时，原逻辑不进 DWS，DWS 只能看到 DWD 70% 数据，丢去很多价格 document
- **v0.9**（2026-07-22）attr 治本 L2 封堵（transform/attr_utils.py + parse_spec/base.py + cable.py）
- v0.6（2026-06-19）v2 → v3 GB 章节 4 层分类体系重建；collectors 抽象基类 v0.8+