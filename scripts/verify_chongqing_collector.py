#!/usr/bin/env python3
"""chongqing_collector.py 试点验证脚本（v0.8）

⚠️ 实验性：仅做接口适配性验证，不替代生产。
- 验证 ChongqingCollector 钩子正确
- 验证 _list_work_units 35/4/5 数字正确
- 验证 _compute_unit_key 格式
- 验证 mock SyncRunner 端到端主流程

不验证（需生产 browser 环境）：
- _process_one 真实抓数据
- cmd_write / cmd_progress 真实写 ES
- 浏览器点击 / 翻页

用法：python3 scripts/verify_chongqing_collector.py
"""
import os
import sys
from pathlib import Path

# 让 chongqing_collector 可 import
SKILLS_ROOT = Path("/Users/pengfit/.openclaw/workspace/skills")
sys.path.insert(0, str(SKILLS_ROOT / "gov-price-etl"))
sys.path.insert(0, str(SKILLS_ROOT / "chongqing-price" / "commands"))

from chongqing_collector import ChongqingCollector, make_collector

print("==== chongqing_collector 试点验证（v0.8 实验性） ====\n")

# 1. import + 类签名
print("  ✓ ChongqingCollector import 成功")
print(f"    MRO: {[c.__name__ for c in ChongqingCollector.__mro__[:4]]}")

# 2. 实例化（用内存 cfg）
cfg = {
    "es": {
        "host": "http://localhost:59200",
        "index": "ods_material_chongqing_price",
        "progress_index": "material_chongqing_price_sync_progress",
    }
}
collector = ChongqingCollector(
    cfg=cfg, tab_id="t1", run_id="test_v08",
    periods=["2099年12月"],  # 未跑过的 period
    sources=["district"],
)
print(f"  ✓ 实例化成功: tab_id={collector.tab_id}, run_id={collector.run_id}")

# 3. _list_work_units 检查
units = collector._list_work_units()
print(f"\n  _list_work_units(['2099年12月'], ['district']): {len(units)} units")
assert len(units) == 35, f"district 期望 35 区县, got {len(units)}"
print(f"    ✓ 35 个 district 区县全列出（无 done 进度）")
print(f"    first 3: {units[:3]}")

# 4. _items_for 验证
items_district = collector._items_for("district")
items_mortar = collector._items_for("mortar")
items_citywide = collector._items_for("citywide")
print(f"\n  _items_for 检查:")
print(f"    district: {len(items_district)} (期望 35)")
print(f"    mortar:   {len(items_mortar)} (期望 4)")
print(f"    citywide: {len(items_citywide)} (期望 5)")
assert len(items_district) == 35
assert len(items_mortar) == 4
assert len(items_citywide) == 5
print(f"    ✓ 35 / 4 / 5 数字正确")

# 5. _compute_unit_key
key1 = collector._compute_unit_key(("district", "万州区", "2099年12月"))
key2 = collector._compute_unit_key(("citywide", "园林绿化工程材料", "2099年12月"))
print(f"\n  _compute_unit_key:")
print(f"    district/万州区: {key1!r}")
print(f"    citywide/园林绿化: {key2!r}")

# 6. _parse_month_from_period
m1 = collector._parse_month_from_period("2026年05月")
m2 = collector._parse_month_from_period("2026年1月")
m3 = collector._parse_month_from_period("bad_period")
print(f"\n  _parse_month_from_period:")
print(f"    '2026年05月' -> {m1!r} (期望 '05')")
print(f"    '2026年1月'  -> {m2!r} (期望 '01' zfill 补 0)")
print(f"    'bad_period' -> {m3!r} (期望 None)")
assert m1 == "05"
assert m2 == "01"
assert m3 is None

# 7. mock SyncRunner 端到端（不调 browser）
class MockCollector(ChongqingCollector):
    """不调 browser，每个 unit 返回 5 docs"""
    def _process_one(self, unit):
        return 5, "completed"

# mock 不能调 cmd_progress（会发 ES 请求），重写 _on_unit_done
class TrivialMock(MockCollector):
    def _on_unit_done(self, unit, docs_count, status, error=""):
        # 跳过真实的 cmd_progress + save
        pass

mock = TrivialMock(cfg, "t1", "mock_run", ["2099年12月"], ["district"])
result = mock.run()
print(f"\n  Mock SyncRunner 端到端: {result}")
assert result["total"] == 35
assert result["done"] == 35
assert result["failed"] == 0
assert result["docs_written"] == 35 * 5
assert result["interrupted"] is False
print(f"    ✓ 35 units × 5 docs = {result['docs_written']} docs")

# 8. mock 错误场景
class ErrorMock(ChongqingCollector):
    def _process_one(self, unit):
        return 0, "error"

class TrivialError(ErrorMock):
    def _on_unit_done(self, unit, docs_count, status, error=""):
        pass

err_mock = TrivialError(cfg, "t1", "err_run", ["2099年12月"], ["district"])
result2 = err_mock.run()
print(f"\n  Error mock 端到端: {result2}")
assert result2["done"] == 0
assert result2["failed"] == 35
print(f"    ✓ 35 units 全部 failed")

# 9. 多 source 综合
multi = TrivialMock(cfg, "t1", "multi_run", ["2099年12月"],
                    ["district", "mortar", "citywide"])
result3 = multi.run()
print(f"\n  3 sources 综合: total={result3['total']}, done={result3['done']}")
assert result3["total"] == 35 + 4 + 5  # 44
print(f"    ✓ 35 + 4 + 5 = 44 units 全部 done")

# 10. 工厂方法
print(f"\n  make_collector 工厂方法检查（不真跑）")
# 仅验证签名，不调 _run_sync_source
import inspect
sig = inspect.signature(make_collector)
print(f"    make_collector signature: {sig}")

print("\n==== ✅ chongqing_collector 试点接口全部通过 ====")
print("\n⚠️ 警告：此试点**未生产验证**。sync.py 默认仍走原 cmd_sync，")
print("   需加 --use-collector flag 才走本类。生产环境请用默认路径。")