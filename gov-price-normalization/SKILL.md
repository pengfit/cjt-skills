---
name: gov-price-normalization
description: "政府材料价格数据标准化层（L1字段净化/L2单位/L3期号/L4跨城映射），独立模块，与 ETL 解耦。供 dashboard、API 等下游消费。L1 是 attr 脏数据治本闭环核心。"
---

# gov-price-normalization

政府材料价格数据的**标准化层**，与 ETL 完全解耦。提供 L1~L4 四层纯函数，各层独立可测、可单跑、可组合。

**v0.2（2026-07-22）**：L1 从占位升级为**完整实现**，是 attr 脏数据**治本**核心（详见下文「L1 attr 治本」）。

## 定位

```
gov-price-etl  ── 写 DWS ──→  dws_{city}_price  ── read  ──→  Normalizer ETL (本包内 worker)  ── 写 NORM ──→  norm_{city}_price
                                              ↑                                  ↑                                    ↑
                                       ETL 拥有                           NormalizationLayer 拥有                  ↑
                                                                                                                       │
                                                                    gov-price-dashboard API 默认查 NORM，DWS 作 fallback ─┘
```

**关键不变量**：
- NormalizationLayer **不 import 任何 ETL 模块**，**也不写 ETL 的 DWS 索引**
- ETL 只管写自己的 DWS，写完就不管后续
- Normalizer ETL（在本包内的独立 worker）负责 DWS → NORM 的搬运
- Dashboard 默认查 NORM；NORM 缺失时降级到 DWS
- NORM 索引 `norm_{city}_price` 是 NormalizationLayer 自己的存储，与 DWS 平级但物理独立
- **L1 先于 L2/L3 跑**（attr 净化是上游），L1 失败降级不阻断

## 四层职责

| 层 | 模块 | 职责 | 版本 |
|----|------|------|------|
| **L1** | `layers/fields.py` | **attr 净化**：`sanitize_attr()` 删 9 大脏模式 + L3 类目白名单 + HARD_REJECT 护栏 / **电缆重拆**：`normalize_cable_type()`（GB/T 12706 命名）| ✅ v0.2 完整（治本核心）|
| **L2** | `layers/units.py` | 单位换算、价格归一（按 L3 default_unit） | ✅ Phase A |
| **L3** | `layers/periods.py` | 业务期对齐（monthly/quarterly/bimonthly/irregular） | ✅ Phase A |
| **L4** | `layers/cross_city.py` | 跨城映射 | Phase C（占位）|

## 入口 API

```python
from gov_price_normalization import normalize_doc, normalize_batch

# 单文档
out = normalize_doc(
    doc={
        "breed": "热轧带肋钢筋",
        "unit": "kg",
        "price": 4500,
        "period_start": "2026-02-15",
    },
    city="xian",
    l3_code="01.01.01",   # 可选；提供则做价格归一
    strict=False,          # 任一层失败是否抛异常（默认降级 + 记 status）
)

# out 含原字段 + 标准化字段
# out["canonical_period"]        -> "2026-02"
# out["period_norm"]             -> {raw, parsed, canonical, year, month, quarter, granularity}
# out["unit_norm"]               -> {raw, dim, to_base, base, normalized}
# out["price_norm"]              -> {price_canonical, unit_canonical, converted, factor}
# out["_norm"]["status"]          -> 各层 ok/skipped/error
```

## 各层单独调用

```python
from gov_price_normalization.layers import units, periods

# L2
units.parse_unit("kg")                # → {raw, dim, to_base, base, normalized}
units.convert_value(100, "mm", "m")   # 数量：100mm = 0.1m
units.convert_price(4, "kg", "t")    # 价格：4 元/kg = 4000 元/t
units.normalize_price_to_l3(500, "kg", "01.01.01")  # 按 L3 default_unit 归一

# L3
periods.normalize_period("2026-02-15", "xian")     # 月刊 → "2026-02"
periods.normalize_period("2026-Q1", "weihai")      # 季刊 → "2026-Q1"
periods.city_granularity("weihai")                 # "quarterly"
periods.align_periods(["2026-01", "2026-02"], "xian")
```

## CLI 工具

```bash
# 单文档标准化（stdin 喂 JSON）
echo '{"breed":"HRB400","unit":"kg","price":4500,"period_start":"2026-02-15"}' \
  | python3 -m cli.normalize_one --city xian --l3 01.01.01

# 单独跑某层
python3 -m cli.inspect_layer units parse --unit "立方米"
python3 -m cli.inspect_layer units convert --value 100 --from kg --to t
python3 -m cli.inspect_layer units price-normalize --value 3500 --from t --to-l3 01.01.01
python3 -m cli.inspect_layer periods --city weihai --period-start "2026-Q1"
python3 -m cli.inspect_layer meta
```

## 数据文件

| 文件 | 内容 | 可热替换 |
|------|------|---------|
| `gov_price_normalization/data/unit_conversion.json` | 单位→量纲+换算系数 + L3 default_unit | ✅ 放 `data/override/` |
| `gov_price_normalization/data/period_rules.json` | 17 城粒度规则 | ✅ 同上 |

数据加载是 lazy + 缓存（见 `utils/data_loader.py`），更新文件后调 `data_loader.clear_cache()` 即可热重载。

## 项目结构

```
gov-price-normalization/
├── SKILL.md
├── README.md
│
├── gov_price_normalization/           ← Python 包
│   ├── __init__.py                    ← 导出 normalize_doc / normalize_batch
│   ├── pipeline.py                    ← 串联 L1+L2+L3+L4
│   ├── layers/
│   │   ├── fields.py                  ← L1 占位
│   │   ├── units.py                   ← L2 完整
│   │   ├── periods.py                 ← L3 完整
│   │   └── cross_city.py              ← L4 占位
│   ├── data/
│   │   ├── unit_conversion.json
│   │   └── period_rules.json
│   └── utils/
│       ├── data_loader.py             ← lazy load + cache
│       └── errors.py                  ← 异常族
│
├── cli/
│   ├── normalize_one.py               ← 单文档测试
│   └── inspect_layer.py               ← 单层调试
│
└── tests/
    ├── test_units.py                  ← L2 单元测试
    ├── test_periods.py                ← L3 单元测试
    └── test_pipeline.py               ← pipeline 串联测试
```

## 与 dashboard 集成

Dashboard 通过 `api/normalization_bridge.py` 接入，不修改自身代码路径：

```python
# 在 trend.py 等任意 dashboard api 模块顶部加一行
from api.normalization_bridge import normalize_doc

# 然后就能直接用
out = normalize_doc(dws_doc, city="xian", l3_code="01.01.01")
```

Bridge 只做两件事：
1. 把 `gov-price-normalization/` 加入 `sys.path`
2. re-export 主入口

**绝不 import ETL 模块**——这层只关心 DWS 文档字段，不关心数据怎么来的。

## 测试

```bash
cd skills/gov-price-normalization
python3 -m unittest discover tests/ -v
```

## 设计原则

1. **不依赖 ETL**：包内无任何 `import gov_price_etl`，反过来 ETL 也不依赖本包
2. **模块独立**：L1/L2/L3/L4 互相只通过纯函数接口调用，无共享状态
3. **数据外置**：映射表在 JSON 文件，模块只读不写
4. **可单跑**：每个模块独立测试、独立 CLI 运行
5. **可组合**：`pipeline.normalize_doc()` 串联四层，也可单独调用任一层
6. **降级而非崩溃**：单层失败不阻断整流程，记 `_norm.status`

## Roadmap

| Phase | 内容 | 状态 |
|-------|------|------|
| **A** | L2 units + L3 periods + NORM index 架构 | ✅ |
| **A+** | NORM worker + Dashboard NORM 优先查询（`/market` 公开页跨城归一走 NORM）| ✅ |
| **B** | L1 fields attr 净化（治本核心）| ✅ v0.2 完成 |
| **C** | L4 cross_city 跨城品种映射 | 待做 |
| **D** | 全 trend/compare 接入 NORM，移除 DWS fallback | 待做（Phase C 后）|

## 版本

- **v0.2**（2026-07-22）：L1 fields 完整实现（attr 净化 + 电缆重拆），attr 脏率 32.66% → 0%
- v0.1.0（2026-07-08）：Phase A — L2 + L3 完整

---

## L1 attr 治本（v0.2 核心）

L1 是 attr 脏数据治本闭环的**第一道防线**（治本核心）。三层架构，按"净化上游 → 封堵中游 → 修正下游"分层：

```
┌─────────────────────────────────────────────────────────────────────┐
│ L1 NORM 净化（治本核心）                                              │
│                                                                       │
│  layers/fields.py::sanitize_attr(doc, l3_code=None)                  │
│                                                                       │
│  ┌─ 9 大脏模式删除 ─────────────────────────────────┐              │
│  │  volume / package_type / cross_section_area          │             │
│  │  height_min / thickness_min / mix_grade              │             │
│  │  particle_size / brand=DN / 价格                     │             │
│  └──────────────────────────────────────────────────────┘             │
│                          ↓                                           │
│  ┌─ L3 类目白名单 ─────────────────────────────────────┐             │
│  │  data/category_attr_whitelist.json（按 l3_code 限定）│             │
│  │  不在白名单的 attr key 直接丢弃                        │             │
│  └──────────────────────────────────────────────────────┘             │
│                          ↓                                           │
│  ┌─ HARD_REJECT 通用护栏 ──────────────────────────────┐             │
│  │  非数值/无单位/纯描述 字段直接拒绝                      │             │
│  └──────────────────────────────────────────────────────┘             │
└─────────────────────────────────────────────────────────────────────┘
```

**关键 API**：

```python
from gov_price_normalization.layers.fields import sanitize_attr

# 输入 DWS 文档 attr (list of {k, v} 或 dict)
result = sanitize_attr(doc, l3_code='01.05.07')
# 返回: {attr_norm: list, dropped_attrs: list, status: 'ok'|'skipped'|'error'}
```

**数据驱动**（`data/attr_filters.json` + `data/cable_type_rules.json`）：所有脏模式规则在 JSON 配置，更新后 `data_loader.clear_cache()` 热重载，零代码改动。

**与 L2/L3 的顺序**：`pipeline.normalize_doc()` 中 L1 **先于** L2/L3 执行，因为：
- L2 units 需要干净的 attr 才能正确换算
- L3 periods 不依赖 attr
- L1 失败降级为保留原值 + `_norm.status='error'`，不阻断整流程

**与 ETL 层 L2 封堵的关系**：本层是治本（净化上游），ETL 层 `transform/attr_utils.py` + `parse_spec/base.py` 是治标（封堵中游）。两层独立运行、互不依赖，组成"上游净化 + 中游封堵"双保险。

---

## 与 dashboard 集成

Dashboard 通过 `api/normalization_bridge.py` 接入：

```python
# 在 trend.py 等任意 dashboard api 模块顶部加一行
from api.normalization_bridge import normalize_doc
out = normalize_doc(dws_doc, city='xian', l3_code='01.05.07')
```

Bridge 做两件事：
1. 把 `gov-price-normalization/` 加入 `sys.path`
2. re-export 主入口

**绝不 import ETL 模块**——这层只关心 DWS 文档字段，不关心数据怎么来的。

Dashboard 默认查 NORM（`norm_{city}_price`），缺失时降级到 DWS。`/market` 公开市场行情页（`api/routes/market.py`）跨城归一全部走 NORM 索引。