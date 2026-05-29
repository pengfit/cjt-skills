# gov-price-etl 政府材料价格数据清洗 ETL

将政府材料价格原始数据（ODS 层）清洗为结构化层（DWD），再聚合为展示层（DWS）。

## 数据流

```
ods_material_xian_price     ─┐
ods_material_sichuan_price    ─┤
ods_material_chongqing_price  ─┼─→ ETL(etl.py) ─→ dwd_{city}_price ─┐
ods_material_jinan_price       ─┤                              ↓          │
ods_material_rizhao_price   ─┘       sync_dws.py ─→ dws_{city}_price ─┘
```

**注意**：DWD → DWS 同步有两条独立路径：
1. `etl.py` 内置 `flush_to_dws()` — 在 ETL 过程中实时同步，需 `needs_spec_parse=False` 且至少一个细分字段非空
2. `utils/sync_dws.py` — 独立工具，全量同步（只看 `needs_spec_parse=False`），可单独运行

---

## 目录结构

```
gov-price-etl/
├── SKILL.md
├── SPEC_RULES.md              # parse_spec 规则库使用说明（向量库架构）
├── config.yml                # ES 连接配置
├── commands/
│   ├── __init__.py
│   ├── etl.py                # ODS → DWD 主程序（含内置 DWS 同步）
│   ├── test_etl.py           # 西安快速测试脚本
│   ├── clean.py               # 品种/规格/单位/价格清洗函数
│   ├── classify.py            # 品种分类入口
│   ├── fix_rule.py            # 从错误样本自动分析并写入 base.py 规则
│   ├── parse_spec/            # 规格解析引擎（槽位制 + 向量库）
│   │   ├── __init__.py       # get_parser() 入口，按城市分发
│   │   ├── base.py            # BaseParseSpec 通用解析基类
│   │   ├── xian.py           # 西安专用（暂用 base.py）
│   │   ├── sichuan.py        # 四川专用（暂用 base.py）
│   │   └── rules/
│   │       ├── _attrs.py      # 属性槽位定义（ATTR_SLOTS 来源）
│   │       ├── vector_store.py # 向量规则库（SQLite，唯一规则源）
│   │       └── rules_vec.db   # 规则数据库（SQLite）
│   └── classify/
│       ├── __init__.py
│       └── rules/
│           ├── _core.py       # classify_breed 核心函数
│           ├── jaccard.py     # Jaccard 相似度品种召回
│           └── breed_category_rules 表 # breed→category 查表
└── utils/
    ├── __init__.py
    └── sync_dws.py            # 独立 DWD → DWS 同步工具（全量）
```

---

## 命令与用法

### 1. 主 ETL（ODS → DWD + 实时 DWS 同步）

```bash
cd /Users/pengfit/.openclaw/workspace/skills/gov-price-etl

# 全量 ETL（所有城市）
python3 commands/etl.py

# 只处理指定城市
python3 commands/etl.py --city sichuan

# 增量模式（按 update_date）
python3 commands/etl.py --incremental --since 2026-05-01

# 只清洗指定分类
python3 commands/etl.py --category 瓦

# 批量确认规则（清洗指定分类时：规则已全部确认，直接标记 needs_spec_parse=False，不走 AI）
python3 commands/etl.py --category 瓦 --mark-done

# 预览（前100条，不写入 ES）
python3 commands/etl.py --dry-run

# 指定批量大小
python3 commands/etl.py --batch-size 1000
```

### 2. 独立 DWS 同步（仅 DWD → DWS，全量）

```bash
# 全量同步所有城市
python3 utils/sync_dws.py

# 只同步指定城市
python3 utils/sync_dws.py --city xian

# 预览（不写入）
python3 utils/sync_dws.py --dry-run

# 指定批量大小
python3 utils/sync_dws.py --batch-size 2000
```

### 3. 规格解析测试

```bash
python3 -c "
import sys; sys.path.insert(0, 'commands')
from parse_spec import get_parser
p = get_parser('xian')
print(p.parse_spec('H100~H250 Q235B'))
print(p.parse_spec('400*(800+250)'))
print(p.parse_spec('δ=4.5'))
print(p.parse_spec('D720*8'))
"
```

### 4. 品种分类测试

```bash
python3 commands/classify.py 镀锌钢管
python3 commands/classify/rules/_core.py 铸铁井盖
```

### 5. 规则自动修复（从错误样本写入 base.py）

```bash
# 自动分析 spec 错误样本，生成并验证规则
python3 commands/fix_rule.py --spec "D720*8" --expected '{"diameter":"D720","thickness":"8mm"}'
python3 commands/fix_rule.py --spec "袋装P.S.A32.5" --expected '{"grade":"P.S.A32.5"}'
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

**规则唯一来源**：`parse_spec/rules/rules_vec.db`（SQLite），不再从 rules/*.py 读取。

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
  ├── 1. 精确查 breed_category_rules（DB）
  ├── 2. Jaccard 相似度召回（jaccard.py）
  │       rules/*.py 静态规则 + breed_category_rules DB 规则
  └── 3. 未命中 → "其他"（AI 批量分类由 etl.py 单独处理）
```

**Jaccard 召回**：基于字符 bigram（n=2）相似度，默认阈值 0.35；精确匹配优先（按 breed 长度降序）。

### ETL 转换逻辑（transform_doc）

```
品种清洗: clean_breed() 去除噪声字符（? 、, （）等）
       去除: 含税、报价、含税等噪声词

规格清洗: spec 原样保留（写入 spec），由 parse_spec 解析为细分字段
       needs_spec_parse = (spec非空 且 所有细分字段都为空)

单位清洗: clean_unit() 映射为标准单位（t/kg/m³/m²/m/个/根/卷等）

价格清洗: clean_price() 转为浮点数，无效返 None

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
| `needs_spec_parse` | boolean | 规格是否需二次解析 |
| `unit` | keyword | 标准单位 |
| `price/tax_price` | float | 单价/含税价 |
| `category` | keyword | 分类名称 |
| `province/city/county` | keyword | 地域信息 |
| `update_date/publish_time/period/code` | keyword/date | 时间/编码字段 |
| `source_index` | keyword | ODS 索引名 |
| `etl_time` | date | ETL 时间戳 |

### DWS 层结构（attr nested）

`etl.py` 中 `flush_to_dws()` 构建的 DWS：`attr` 字段为 `nested` object，扁平字段聚合为嵌套对象。

`utils/sync_dws.py` 独立同步：`attr` 字段为普通 `object`（字段映射不同）。

入 DWS 条件（`flush_to_dws`，需同时满足）：
- `needs_spec_parse = False`
- 至少一个细分字段非空

独立 sync_dws.py 入 DWS 条件（只看 `needs_spec_parse=False`）。

### 城市配置

| 城市 | ODS 索引 | DWD 索引 | DWS 索引 |
|------|---------|---------|---------|
| xian | `ods_material_xian_price` | `dwd_xian_price` | `dws_xian_price` |
| sichuan | `ods_material_sichuan_price` | `dwd_sichuan_price` | `dws_sichuan_price` |
| chongqing | `ods_material_chongqing_price` | `dwd_chongqing_price` | `dws_chongqing_price` |
| jinan | `ods_material_jinan_price` | `dwd_jinan_price` | `dws_jinan_price` |
| rizhao | `ods_material_rizhao_price` | `dwd_rizhao_price` | `dws_rizhao_price` |

---

## 分类体系（28 类）

钢材 / 水泥 / 石材 / 砂石骨料 / 保温材料 / 防水材料 / 管材管件 / 市政设施 / 装饰装修材料 / 涂料油漆 / 陶瓷卫生洁具 / 五金配件 / 密封材料 / 铜材 / 铝材铝合金 / 金属材料 / 绿化苗木 / 铁艺铸铁件 / 消防器材 / 网格布土工材料 / 化工材料 / 龙骨吊顶 / 瓦 / 公用事业费 / 机械设备 / 电气材料 / 劳务工种 / 其他