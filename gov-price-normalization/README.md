# gov-price-normalization

政府材料价格数据标准化层（NormalizationLayer），v0.1.0（Phase A）。

详细使用说明见 [SKILL.md](./SKILL.md)。本文档是面向贡献者的快速上手。

## 30 秒上手

```bash
cd ~/.openclaw/workspace/cjt/skills/gov-price-normalization

# 跑测试
python3 -m unittest discover tests/

# 单文档测试
echo '{"breed":"HRB400","unit":"kg","price":4500,"period_start":"2026-02-15"}' \
  | python3 -m cli.normalize_one --city xian --l3 01.01.01

# 看某一层
python3 -m cli.inspect_layer units convert --value 100 --from kg --to t
python3 -m cli.inspect_layer periods --city weihai --period-start "2026-Q1"
```

## 添加新城市到 periods 规则

编辑 `gov_price_normalization/data/period_rules.json`：

```json
{
  "newcity": {"granularity": "monthly"}
}
```

加好后跑测试确认 JSON 没坏。

## 添加新单位到换算表

编辑 `gov_price_normalization/data/unit_conversion.json`，在 `units` 加：

```json
"new_unit": {"dim": "mass", "to_base": 100.0, "base": "g"}
```

`dim` 可选：`mass` / `length` / `area` / `volume` / `piece` / `time`。

## 实现新一层（L1 / L4）

1. 在 `gov_price_normalization/layers/<layer>.py` 实现函数（保留已有签名）
2. 去掉 `NotImplementedError`
3. 在 `pipeline.py` 的 `normalize_doc()` 调用新层
4. 写测试到 `tests/test_<layer>.py`
5. 跑测试：`python3 -m unittest discover tests/`

## 数据热替换

把同名 JSON 放到 `gov_price_normalization/data/override/` 优先于主目录加载。调试时常用：

```bash
mkdir -p gov_price_normalization/data/override
cp gov_price_normalization/data/period_rules.json gov_price_normalization/data/override/
# 编辑 override 版本
```

清缓存：

```python
from gov_price_normalization.utils.data_loader import clear_cache
clear_cache()
```

## 调试技巧

```python
# 单步跑某一层
from gov_price_normalization.layers import units
print(units.parse_unit("立方米"))
print(units.convert_price(4, "kg", "t"))  # 4000

# 看数据表元信息
from gov_price_normalization.utils import data_loader
print(data_loader.get_meta("unit_conversion.json"))

# pipeline 单层失败时看 status
from gov_price_normalization import normalize_doc
out = normalize_doc({"breed":"x","unit":"kg","price":100,"period_start":"2026-02"}, "atlantis")
print(out["_norm"]["status"])
# {'L3_periods': 'error: 未知城市: \'atlantis\' | city=atlantis | field=city',
#  'L2_units_parse': 'ok', ...}
```

## 不变性

修改本包时请严守：

- ❌ 不 import ETL 模块（gov_price_etl / gov-price-etl）
- ❌ 不直接读 ES
- ❌ 不引入 dashboard 依赖（vue、echarts 等）
- ✅ 只依赖 Python 标准库
- ✅ 数据外置（JSON），代码只读不写
- ✅ 每层可独立 import、测试、运行

## 架构图

```
┌─────────────────────────────────────────────────────────┐
│  DWS 原始文档 (dws_{city}_price)                        │
│  { breed: "...", attr: [{k,v}], unit: "...", price: ... } │
└──────────────────────────┬──────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────┐
│  NormalizationLayer（4 个子层，可独立替换）             │
├─────────────────────────────────────────────────────────┤
│  L1 字段标准化  ──> fields.py (Phase B)                 │
│  L2 单位换算    ──> units.py (✅)                       │
│  L3 日期对齐    ──> periods.py (✅)                     │
│  L4 跨城映射    ──> cross_city.py (Phase C)            │
└──────────────────────────┬──────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────┐
│  业务 API（trend / compare / search / dist / health）  │
│  只看到标准化后的字段，零 if city 分支                   │
└─────────────────────────────────────────────────────────┘
```

## License

内部使用，无外部 license。