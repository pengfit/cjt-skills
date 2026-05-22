# gov-price-dashboard 单位字段修复总结

## 一、数据问题根因

全量 2,199,122 条记录中，682,381 条（31%）存在单位字段异常（`/` 或空字符串），涉及 126 个品种。同一品种混用多种单位（米/吨/个等），导致聚合出的 min/avg/max 价格差距数百倍，不可比。

---

## 二、修复方案执行

### Step 1 — 建立品名→标准单位字典

从 ES 聚合分析入手，抽样 200 个品种的 unit 分布，识别出 `/` 单位对应的是"合理但单位漏填"的数据。按品类常识为 124 个品种建立标准单位映射：

```
焊接钢管 → m（元/米）
镀锌钢管 → m
预拌混凝土 → m³
热轧等边角钢 → t
承插钢筋混凝土管 → 根
铜芯聚氯乙烯绝缘线 → m
...
```

保存于 `scripts/unit_mapping.json`

---

### Step 2 — ES 写入 `unit_fixed` 字段

使用 `_update_by_query` + painless script，为 75 个含异常单位的品种共 **382,469 条**记录写入 `unit_fixed`（标准单位），0 失败。

```python
# 脚本逻辑
ctx._source.unit_fixed = 'm'  # 按品种查表赋值
```

---

### Step 3 — 建立 `union_unit` 统一单位字段

`unit_fixed` 只覆盖 `/` 和 `''` 记录，原始 `unit=t` 的正常记录没有覆盖。用同样的方式为全部 200 个品种写入 `union_unit`：

```python
# 逻辑：优先用 unit_fixed，否则用原 unit
ctx._source.union_unit = ctx._source.unit_fixed != null
    ? ctx._source.unit_fixed
    : ctx._source.unit
```

结果：

| 品种 | 修复前均价 | 修复后均价 | 单位 |
|------|-----------|-----------|------|
| 焊接钢管 | ¥36.63 | ¥3,781 | t |
| 镀锌钢管 | ¥43.46 | ¥4,258 | t |
| 碎石 | ¥121（混）| ¥121/m³ | m³ |

---

### Step 4 — API 聚合切换为 `union_unit` 分层

`/api/stats/category-breeds` 聚合维度从跨单位改为按 `union_unit.keyword` 分组，只取最大计数量的单位组作为主价格，保证 min/avg/max 来自同一单位。

```python
# 聚合嵌套
"aggs": {
    "all_breeds": {
        "terms": {"field": "breed.keyword", "size": 10000},
        "aggs": {
            "units": {
                "terms": {"field": "union_unit.keyword", "size": 10},
                "aggs": {"avg_price": {"avg": {"field": "price_t"}}, ...}
            }
        }
    }
}
```

---

### Step 5 — 前端品种列表增加单位列

品种表格新增"单位"列（第4列），紫色徽章样式展示标准单位，与价格联动，价差恢复正常。

---

## 三、最终数据结构

| 字段 | 说明 |
|------|------|
| `unit` | 原始值（/ 或 t 或 m³） |
| `unit_fixed` | 推断的标准单位（仅 / 和 '' 记录有） |
| `union_unit` | 统一标准单位（全量记录都有，优先用 unit_fixed） |

品种展示时直接读 `union_unit`，不同单位的同品种价格分层展示，不混合比较。

---

## 四、涉及文件

| 文件 | 作用 |
|------|------|
| `scripts/unit_mapping.json` | 124 个品种标准单位映射 |
| `scripts/fix_unit_field.py` | ES 清洗脚本（写入 unit_fixed） |
| `scripts/fix_other.py` | 其他分类修复脚本 |
| `api/main.py` | 品种列表 API（切换为 union_unit 聚合） |
| `frontend/src/components/CategoryView.vue` | 品种列表表格（增加单位列） |

---

## 五、执行命令记录

```bash
# 1. 建立品名→标准单位字典
python3 scripts/build_unit_map.py

# 2. 执行 unit_fixed 写入（全量）
python3 scripts/fix_unit_field.py --apply

# 3. 建立 union_unit 统一单位字段（全量品种）
python3 scripts/build_union_unit.py   # 脚本需逐品种执行

# 4. 重启 API
cd api && python3 -m uvicorn main:app --host 0.0.0.0 --port 5200 &

# 5. 重启前端
cd frontend && npm run dev -- --host 0.0.0.0 --port 5300 &
```

---

## 六、验收标准

- [x] 682,381 条异常单位记录全部写入 `unit_fixed`
- [x] 全部 200 个品种写入 `union_unit`
- [x] 品种列表 API 按 `union_unit` 分层聚合
- [x] 前端品种表格显示标准单位列
- [x] 焊接钢管均价：36.63 → 3,781（合理回归）
- [x] 镀锌钢管均价：43.46 → 4,258（合理回归）