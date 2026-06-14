---
name: gov-price-etl
description: "政府材料价格数据入仓 ETL：将政府材料价格原始数据（ODS 层）清洗为结构化层（DWD），再聚合为展示层（DWS）。"
---

# gov-price-etl

将政府材料价格原始数据（ODS 层）清洗为结构化层（DWD），再聚合为展示层（DWS）。

## 数据流

```
ods_material_xian_price     ─┐
ods_material_sichuan_price    ─┤
ods_material_chongqing_price  ─┼─→ ETL (cli/etl) ─→ dwd_{city}_price ─┐
ods_material_jinan_price       ─┤                              ↓          │
ods_material_rizhao_price   ─┘       sync_dws (cli/sync_dws) ─→ dws_{city}_price ─┘
```

**DWD → DWS 同步有三种模式**（合并自旧的 3 个独立入口）：

| 模式 | CLI 标志 | 触发条件 | AI 调 |
|---|---|---|---|
| `quick` | `--mode quick` | DWD `attr` 非空 | ❌ |
| `plain` | `--mode plain` | DWD `spec` 非空 | ❌ |
| `ai`    | `--mode ai`    | 缺 attr → 走 AI 补全 | ✅ |

默认模式：`quick`（最快、不调 AI）。需要 AI 补全时显式传 `--mode ai`。

---

## 目录结构（v0.2 重构后）

```
gov-price-etl/
├── SKILL.md
├── SPEC_RULES.md              # parse_spec 规则库使用说明
├── README.md
├── config.yml                # ES 连接配置
├── data/                      # 数据文件集中
│   ├── breed_spec_rules.db    # 规格解析规则（SQLite）
│   ├── breed_category_rules.db # 品种分类规则
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
│   │   ├── doc.py          # transform_doc ODS→DWD
│   │   └── attr_utils.py   # attr 字段提取/转换
│   ├── parse_spec/         # 规格解析引擎
│   │   ├── __init__.py     # get_parser() 入口
│   │   ├── base.py         # BaseParseSpec 基类
│       │   ├── xian.py / sichuan.py / henan.py
│       │   └── rules/
│       │       ├── _attrs.py   # ATTR_SLOTS
│       │       └── vector_store.py  # SQLite 向量规则库
│       ├── classify/           # 品种分类引擎
│       │   ├── __init__.py
│       │   ├── system.py       # 分类体系映射
│       │   └── rules/
│       │       ├── _core.py    # classify_breed
│       │       └── jaccard.py  # Jaccard 召回
│       ├── ai/                 # AI 服务
│       │   ├── __init__.py
│       │   ├── service.py      # parse_spec_batch / classify_breed_batch
│       │   └── cache.py        # SQLite 缓存
│       └── pipeline/
│           ├── __init__.py
│           ├── etl.py          # ODS→DWD 主循环
│           └── dws_sync.py     # DWD→DWS 同步（合一：3 模式）
├── cli/                        # 入口脚本
│   ├── etl.py                  # ODS → DWD → DWS 主入口
│   ├── sync_dws.py             # DWD → DWS 同步（--mode quick|plain|ai）
│   └── reload_prompts.py       # 重读 prompts.yml
├── prompts.yml                 # AI Prompt 模板（从 dashboard 迁移，热重载）
└── commands/                   # ⚠️ 旧入口 shim（已废弃）
    ├── etl.py                  # 转发到 cli/etl.py
    └── sync_dws_quick.py       # 转发到 cli/sync_dws.py --mode quick
```

**对比旧结构（v0.1）**：
- `commands/etl.py` 1107 行 → `pipeline/etl.py` ~250 行 + 4 个独立模块
- 三套 DWS 同步实现 → 一个核心 `sync_dws()` + 3 个薄壳
- 散落的 `commands/{parse_spec,classify,ai_*,clean,...}` → 标准包结构
- 6 处 `sys.path.insert` 黑魔法 → 0 处
- 1 处硬编码绝对路径 → 0 处
- `config.yml` / 4 个 DB 文件位置不动（向后兼容）

---

## 命令与用法

### 1. 主 ETL（ODS → DWD + DWS 同步）

```bash
cd ~/.openclaw/workspace/skills/gov-price-etl

# 全量 ETL（所有城市）
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

### 2. 独立 DWS 同步（仅 DWD → DWS）

```bash
# Quick 模式：只同步已有 attr 的（默认，不调 AI）
./cli/sync_dws.py
./cli/sync_dws.py --city xian

# Plain 模式：spec 非空即同步（不调 AI）
./cli/sync_dws.py --mode plain --city xian

# AI 模式：缺 attr 走 AI 补全
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

### 4. 品种分类测试

```bash
PYTHONPATH=src python3 -c "
from gov_price_etl.classify import classify_breed
print(classify_breed('镀锌钢管'))
print(classify_breed('铸铁井盖'))
"
```

### 5. AI Prompt 模板管理

Prompt 模板从 `gov-price-etl/prompts.yml` 加载（不是 hard-coded，也不是读 gov-price-dashboard）。

```bash
# 重读 prompts.yml（调试场景，yml 改完不需要重启 ETL）
./cli/reload_prompts.py

# 查看当前加载的所有 prompt 概览
./cli/reload_prompts.py --show

# 也能在 Python 里调：
PYTHONPATH=src python3 -c "
from gov_price_etl.ai import reload_prompts, get_prompt
reload_prompts()
print(list(get_prompt('batch_spec_parse').keys()))
"
```

**热重载机制**：进程内缓存 prompts.yml 的 mtime + 内容，下次 `get_prompt()` 调用检测到 mtime 变了就自动重读。**不需要重启 ETL**。

**`prompts.yml` 三个 key**（从 gov-price-dashboard 迁移过来）：
- `fix_case` — 单条 spec → 解析规则
- `classify_breed_batch` — 批量品种 → 分类
- `batch_spec_parse` — 批量 spec → 解析规则

**安全格式化**：`format_prompt()` 处理模板中的字面量花括号（`{diameter:20mm, material:Q235}` 之类的举例文本）不会报 KeyError，也不会跟真占位符（`{specs_str}`、`{ref_names}` 等）冲突。

**修改 prompts.yml**：
1. 直接编辑 `~/.openclaw/workspace/skills/gov-price-etl/prompts.yml`
2. 跑 `./cli/reload_prompts.py`（或等下次 ETL 自动检测 mtime）
3. 验证：用 `--show` 看到新内容
4. 回滚：dashboard 的 `gov-price-dashboard/api/routes/prompts.yml` 仍保留作为只读参考源

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

### parse_spec 规格解析（槽位制 + RAG 向量库）

**规则唯一来源**：`data/breed_spec_rules.db`（SQLite），不再从 rules/*.py 读取。

**解析流程（槽位制）**：
1. 动态加载 `ATTR_SLOTS`（从 `_attrs.py` 提取所有 `"attr" → "描述"` 行）
2. 对每个 slot 独立调用 `vector_store.search()` 召回候选规则（top_k=10）
3. 对 spec 字符串生成结构语义 tokens（`_build_spec_tokens`），与规则 tokens 做 Jaccard 相似度过滤（score ≥ 0.001）
4. 按 score 排序，同 (attr, pattern) 去重保留最高分
5. 逐条执行 regex match + code，填入对应 slot
6. 全部未命中 → 调用 fix-case API（`http://localhost:5200`）

**ATTR_SLOTS 全部槽位**：
```
diameter, thickness, length, width, height,       # 尺寸
material, grade, pressure, cores, voltage, current, # 材质/电气
form, color, series, temperature,                  # 形态/外观
temp_range, humidity_range, length_range, height_range,  # 范围
inner_diameter, wall_thickness, fiber_core, cable_length, # 管线
channels, doors, media, range, output,             # 设备/变送器
ip_rating, fire_rating, ring_stiffness,            # 等级/安全
cross_section, drain_type, inlet_type, installation_type, # 电缆/排水
asphalt_type, cement_content, surface             # 专业属性
```

**向量库两张表**：

| 表 | 用途 | 关键字段 |
|----|------|---------|
| `breed_spec_rules` | spec→属性解析规则 | pattern, attr, note, code, breed, category, tokens |
| `breed_category_rules` | breed→category 分类查表 | breed, category, source |

### 品种分类流程（3 级召回）

```
classify_breed(breed_clean)
  ├── 1. Jaccard 相似度召回（rules/jaccard.py，阈值 0.45）
  ├── 2. DB breed_category_rules 精确查表
  └── 3. 未命中 → "其他"（AI 批量分类由 etl.py 单独处理）
```

**Jaccard 召回**：基于字符 bigram（n=2）相似度 + 词级加权 + Dice 系数，默认阈值 0.45。

### ETL 转换逻辑（transform_doc）

```
品种清洗: clean_breed() 去除噪声字符（? 、, （）等）
       去除: 含税、报价、含税等噪声词

规格清洗: spec 原样保留（写入 spec），由 parse_spec 解析为细分字段

单位清洗: clean_unit() 映射为标准单位（t/kg/m³/m²/m/个/根/卷等）

价格清洗: clean_price() 转为浮点数，无效返 None
       Crawler bug 修复: price==0 但 tax_price 有值时互换

分类:
  classify_breed() → 查 DB → 查 Jaccard → "其他"
  "其他" → 批量 AI 分类 → 回写 DWD category
```

### DWD 输出字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `breed` | text+keyword | 原始品种名 |
| `breed_clean` | keyword | 清洗后品种名 |
| `spec` | text+keyword | 原始规格 |
| `thickness/length/width/height/diameter` | keyword | 解析后尺寸 |
| `ring_stiffness/pressure/material/color/grade` | keyword | 材质/等级属性 |
| `voltage/current/cross_section/cores/fiber_core` | keyword | 电气属性 |
| `asphalt_type/cement_content/channels/doors` | keyword | 专业属性 |
| `length_range/height_range/temp_range/humidity_range` | keyword | 范围字段 |
| `media/range/output/cable_length` | keyword | 变送器属性 |
| `surface/series/fire_rating/temperature` | keyword | 扩展字段 |
| `inner_diameter/wall_thickness` | keyword | 管壁属性 |
| `installation_type/drain_type/inlet_type/form/ip_rating` | keyword | 安装/排水/形态 |
| `unit` | keyword | 标准单位 |
| `price/tax_price` | float | 单价/含税价 |
| `category` | keyword | 分类名称 |
| `category_system/category_system_name` | keyword | 分类体系 code/name |
| `province/city/county` | keyword | 地域信息 |
| `update_date/publish_time/period/code` | keyword/date | 时间/编码字段 |
| `source_index` | keyword | ODS 索引名 |
| `etl_time` | date | ETL 时间戳 |
| `attr` | nested | 解析后的规格属性（list of {k, v}） |

### 城市配置

| 城市 | ODS 索引 | DWD 索引 | DWS 索引 |
|------|---------|---------|---------|
| xian | `ods_material_xian_price` | `dwd_xian_price` | `dws_xian_price` |
| sichuan | `ods_material_sichuan_price` | `dwd_sichuan_price` | `dws_sichuan_price` |
| chongqing | `ods_material_chongqing_price` | `dwd_chongqing_price` | `dws_chongqing_price` |
| jinan | `ods_material_jinan_price` | `dwd_jinan_price` | `dws_jinan_price` |
| rizhao | `ods_material_rizhao_price` | `dwd_rizhao_price` | `dws_rizhao_price` |
| henan | `ods_material_henan_price` | `dwd_henan_price` | `dws_henan_price` |
| heze | `ods_material_heze_price` | `dwd_heze_price` | `dws_heze_price` |

---

## 分类体系（28 类）

钢材 / 水泥 / 石材 / 砂石骨料 / 保温材料 / 防水材料 / 管材管件 / 市政设施 / 装饰装修材料 / 涂料油漆 / 陶瓷卫生洁具 / 五金配件 / 密封材料 / 铜材 / 铝材铝合金 / 金属材料 / 绿化苗木 / 铁艺铸铁件 / 消防器材 / 网格布土工材料 / 化工材料 / 龙骨吊顶 / 瓦 / 公用事业费 / 机械设备 / 电气材料 / 劳务工种 / 其他

---

## 重构说明（v0.1 → v0.2）

| 项目 | 旧 (v0.1) | 新 (v0.2) |
|---|---|---|
| `commands/etl.py` | 1107 行（22 个函数） | 拆为 7 个模块，每个 < 250 行 |
| DWS 同步入口 | 3 处独立实现（行为不一致） | 1 核心 + 3 薄壳，行为可参数化 |
| 包结构 | 散文件 + sys.path 黑魔法 | 标准 `gov_price_etl/` 包，0 黑魔法 |
| DB 路径解析 | `os.path.join(__file__, ...)` | `paths.py` 中心化管理 |
| 硬编码绝对路径 | 1 处（`/Users/pengfit/.../breed_category_rules.db`） | 0 处 |
| 入口脚本 | `python3 commands/etl.py` | `./cli/etl.py`（旧入口保留为 shim + DeprecationWarning） |
| `utils/` 目录 | 几乎空 | 删除 |
| `commands/classify.py` | 12 行重复 `__main__` 块 | 删除（`classify/__init__.py` 已带） |
| 死代码 | `_query_breed_rules_db`（定义后未调用） | 删除 |
