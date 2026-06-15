---
name: gov-price-etl
description: "政府材料价格数据入仓 ETL（v0.3 三段式重构）：ODS → DWD → DWS 节点明确，每段都先查本地规则库，未命中强制走 AI 串行。"
---

# gov-price-etl

政府材料价格数据入仓 ETL，**v0.3 重构后 ODS → DWD → DWS 节点全部三段化**：每段先查本地规则库（`breed_category_rules.db` / `breed_spec_rules.db`），未命中强制走 AI **串行**分类/解析。

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
│  │  命中 → category_source='db_exact', category_stage='1'      │     │
│  └───────────────────────────────────────────────────────┘        │
│                                    ↓ 未命中                          │
│  ┌─ 阶段 2: 本地 DB + Jaccard 模糊召回 ─────────────────┐        │
│  │  倒排精确包含 / Dice + 加权 Jaccard (阈值 0.45)         │     │
│  │  命中 → category_source='db_fuzzy', category_stage='2'  │     │
│  └───────────────────────────────────────────────────────┘        │
│                                    ↓ 未命中                          │
│  ┌─ 阶段 3: AI classify_breed_batch 串行批次分类 ──────┐          │
│  │  攒批 20 条/批 → 逐批调 AI → 回写 DWD                   │       │
│  │  命中 → category_source='ai', category_stage='3'        │      │
│  │  失败兜底 '其他' → category_source='ai_fallback'        │      │
│  └───────────────────────────────────────────────────────┘        │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│  DWD 层（带 category_source / category_stage 字段）                 │
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
│  │  命中 → 回写 DWD attr + 同步 DWS                       │         │
│  │  → attr_source='ai'                                    │         │
│  │  失败兜底空 attr → attr_source='ai_fallback'           │        │
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
- ODS→DWD 阶段：每条 DWD 文档带 `category_source`（`db_exact` / `db_fuzzy` / `ai` / `ai_fallback`）和 `category_stage`（`1` / `2` / `3` / 空）
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
├── cli/                        # 入口脚本
│   ├── etl.py                  # ODS → DWD → DWS 主入口
│   ├── sync_dws.py             # DWD → DWS 同步（--mode quick|plain|ai）
│   └── reload_prompts.py       # 重读 prompts.yml
├── prompts.yml                 # AI Prompt 模板
└── commands/                   # ⚠️ 旧入口 shim（已废弃）
```

---

## 三段式 API 速查

### classify（品种分类，ODS→DWD 用）

```python
from gov_price_etl.classify import (
    classify_breed_db_exact,    # 阶段 1: DB 精确查表 → (cat, 'db_exact'|'')
    classify_breed_db_fuzzy,    # 阶段 2: DB 模糊召回 → (cat, 'db_fuzzy'|'')
    classify_breed_local,       # 阶段 1+2: 本地规则库 → (cat, 'db_exact'|'db_fuzzy'|'')
    classify_breed_ai,          # 阶段 3: AI 串行 → (cat, 'ai'|'ai_fallback')
    classify_breed_with_stages, # 三段合并 → (cat, source, stage)
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

### 4. 品种分类测试（**三段式**）

```bash
PYTHONPATH=src python3 -c "
from gov_price_etl.classify import classify_breed_with_stages
for breed in ['圆钢', '螺纹钢', '矮牵牛', 'xxYYZZ未知']:
    cat, src, stage = classify_breed_with_stages(breed, city='xian', use_ai=False)
    print(f'{breed:15s} → {cat:20s} (source={src}, stage={stage})')
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

### 6. 旧入口 shim（兼容，会打 DeprecationWarning）

```bash
python3 commands/etl.py ...        # → cli/etl.py
python3 commands/sync_dws_quick.py # → cli/sync_dws.py --mode quick
```

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
  │    ├─ 阶段 1: classify_breed_db_exact(breed)     → 'db_exact' / ''
  │    ├─ 阶段 2: classify_breed_db_fuzzy(breed)     → 'db_fuzzy' / ''
  │    └─ 兜底: 返回 ('其他', '', '') → 标记待 AI
  │
  ├─ 阶段 1+2 命中 → 写入 DWD（带 category_source）
  │
  └─ 阶段 1+2 都未命中 → 攒批 → _ai_classify_pending()
       ├─ 阶段 3: classify_breed_ai(breed, city) 串行批次（20条/批）
       └─ 回写 DWD category / category_source='ai'/'ai_fallback'
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
| **`category_source`** | **keyword** | **分类来源：`db_exact`/`db_fuzzy`/`ai`/`ai_fallback`** |
| **`category_stage`** | **keyword** | **命中阶段：`1`/`2`/`3`/空** |
| `attr` | nested | 解析后的规格属性（list of {k, v}） |
| `etl_time` | date | ETL 时间戳 |
| `source_index` | keyword | ODS 索引名 |

**DWS 文档（DWD→DWS 产物）**：

| 字段 | 类型 | 说明 |
|------|------|------|
| (DWD 全部字段) | | |
| **`attr_source`** | **keyword** | **attr 来源：`etl`/`local_db`/`ai`/`ai_fallback`** |

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

---

## 分类体系（28 类）

钢材 / 水泥 / 石材 / 砂石骨料 / 保温材料 / 防水材料 / 管材管件 / 市政设施 / 装饰装修材料 / 涂料油漆 / 陶瓷卫生洁具 / 五金配件 / 密封材料 / 铜材 / 铝材铝合金 / 金属材料 / 绿化苗木 / 铁艺铸铁件 / 消防器材 / 网格布土工材料 / 化工材料 / 龙骨吊顶 / 瓦 / 公用事业费 / 机械设备 / 电气材料 / 劳务工种 / 其他

---

## 三段式重构说明（v0.2 → v0.3）

| 项目 | 旧 (v0.2) | 新 (v0.3) |
|---|---|---|
| ODS→DWD 分类逻辑 | `classify_breed()` 混合（Jaccard + 兜底 "其他"） | 显式三段：`classify_breed_db_exact` / `db_fuzzy` / `ai` |
| DWD→DWS 解析逻辑 | `sync_dws_with_ai()` 混合（已有 attr + 本地 + AI） | 显式三段：attr / local_db / ai |
| `_get_db_conn()` | 误用 vec_store 连接（指向 breed_spec_rules.db） | 独立维护 breed_category_rules.db 连接 |
| AI 批次大小 | 100/批（DWS）+ 20/批（ODS） | 统一 20/批串行（道友要求） |
| source 字段 | 无 | DWD 加 `category_source` / `category_stage`，DWS 加 `attr_source` |
| 阶段 1+2 内嵌 | 不明显（混在 transform_doc 中） | 显式拆出 `classify_breed_with_stages()` |
| 阶段 3 显式触发 | 隐式（凑够批次自动调） | 显式 `_ai_classify_pending()` / `_ai_parse_specs_serial()` |