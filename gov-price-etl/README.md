# gov-price-etl

政府材料价格数据入仓 ETL 流水线。

> 📘 详细 Skill 描述见 [SKILL.md](./SKILL.md)

## 简介

将各城市 ODS 层原始数据（`ods_material_{city}_price`）清洗为结构化层（DWD）`dwd_{city}_price`，再聚合同步到展示层（DWS）`dws_{city}_price`。

支持城市：`xian` / `sichuan` / `chongqing` / `jinan` / `rizhao`（henan 待接入）。

## 快速开始

```bash
cd skills/gov-price-etl

# 全量 ETL（所有城市）
python3 commands/etl.py

# 只处理一个城市
python3 commands/etl.py --city sichuan

# 增量模式（按 update_date）
python3 commands/etl.py --incremental --since 2026-05-01

# 预览（不写入 ES）
python3 commands/etl.py --dry-run

# 独立 DWS 同步（跳过 AI）
python3 commands/sync_dws_quick.py --city xian
```

## 目录结构

```
gov-price-etl/
├── SKILL.md                  # Skill 描述
├── README.md                 # 本文件
├── config.yml                # ES 连接配置
├── SPEC_RULES.md             # parse_spec 规则库使用说明
└── commands/
    ├── etl.py                # ODS → DWD 主程序（含内置 DWS 同步）
    ├── sync_dws_quick.py     # 独立 DWD → DWS 同步（跳过 AI）
    ├── clean.py              # 品种/规格/单位/价格清洗
    ├── classify.py           # 品种分类入口
    ├── parse_spec/           # 规格解析引擎（槽位制 + 向量库）
    │   ├── __init__.py       # get_parser() 入口
    │   ├── base.py           # BaseParseSpec 通用基类
    │   ├── xian.py           # 西安专用
    │   ├── sichuan.py        # 四川专用
    │   └── rules/
    │       ├── _attrs.py          # 槽位定义
    │       ├── vector_store.py    # 向量规则库
    │       ├── breed_spec_rules.db    # spec → 属性规则
    │       └── rules_vec.db           # 规则向量
    └── classify/             # 品种分类规则
        ├── __init__.py
        └── rules/
            ├── _core.py
            ├── jaccard.py
            └── breed_category_rules.db
```

## 数据流

```
ods_material_xian_price     ─┐
ods_material_sichuan_price    ─┤
ods_material_chongqing_price  ─┼─→ ETL(etl.py) ─→ dwd_{city}_price ─┐
ods_material_jinan_price       ─┤                              ↓          │
ods_material_rizhao_price   ─┘       sync_dws.py ─→ dws_{city}_price ─┘
```

**两层 DWS 同步路径**：
1. `etl.py` 内置 `flush_to_dws_with_ai()` — ETL 过程中实时同步，会调 AI 补全 `attr`
2. `commands/sync_dws_quick.py` — 独立工具，全量同步（只看 DWD 中非空 `attr`），可单独运行

## 核心组件

### `transform_doc()` (etl.py)
ODS 原始文档 → DWD 结构化文档：
- `clean_breed()` 去除品种名噪声字符
- `clean_unit()` 映射标准单位
- `clean_price()` 转 float
- `classify_breed()` 推断分类（28 类）
- `parser.parse()` 解析 spec 为细分属性（diameter/thickness/...）
- 合并到 DWD 文档（nested `attr`）

### `parse_spec` 规格解析
- **规则源**：`parse_spec/rules/breed_spec_rules.db`（SQLite）
- **架构**：槽位制（`ATTR_SLOTS` 从 `_attrs.py` 加载）+ 向量召回
- **流程**：slot → 规则召回 → regex match → fill
- **未命中** → 调 `localhost:5200` fix-case API

### `flush_to_dws` DWS 同步
- 读 DWD 文档，提取 `attr`
- 写入 DWS（attr 为 nested object）
- `flush_to_dws_with_ai` 还会在本地规则未命中时调 AI

## 关键字段

DWD 输出：
- `breed` / `breed_clean` / `spec` / `unit` / `price` / `tax_price`
- `category` / `province` / `city` / `county` / `period` / `update_date`
- 细分属性：`thickness` / `length` / `width` / `diameter` / `grade` / `material` / ...
- `attr` (nested) — 全部细分属性的统一载体
- `needs_spec_parse` (bool) — 是否需要二次解析
- `source_index` / `etl_time`

DWS 结构：
- `attr` (nested `{k, v}[]`) 或 `attr` (object)
- 业务字段同 DWD

## 配置

`config.yml`：
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

## 添加新城市

`etl.py` 中 `CITY_CONFIGS` 注册：
```python
'henan': {
    'city_label': '河南',
    'ods': 'ods_material_henan_price',
    'dwd': 'dwd_henan_price',
    'dws': 'dws_henan_price',
}
```

`commands/parse_spec/__init__.py` 中 `get_parser()` 添加映射（如继承 `BaseParseSpec` 即可）。

## 依赖

```
requests
pyyaml
elasticsearch
jieba  # 品种分词
pdfplumber  # 不在 etl 内，但 henan 入库时会用
```

## 调试

```bash
# 测试规格解析
python3 -c "
import sys; sys.path.insert(0, 'commands')
from parse_spec import get_parser
p = get_parser('xian')
print(p.parse_spec('H100~H250 Q235B'))
"

# 测试品种分类
python3 commands/classify.py 镀锌钢管

# 单条文档 dry-run
python3 -c "
import sys; sys.path.insert(0, 'commands')
from etl import transform_doc
print(transform_doc({'breed':'普通硅酸盐水泥', 'spec':'42.5(散装)', 'unit':'t', 'price':'300', 'city':'郑州', 'period':'2026.3月'}, 'ods', 'sichuan'))
"
```

## 关联

- 上游：各 `[城市]-price` skill（写入 ODS）
- 下游：`gov-price-dashboard`（消费 DWS）
- 同类：跨城市统一的 ETL/分类/规格解析逻辑
