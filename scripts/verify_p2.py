#!/usr/bin/env python3
"""P2 (v0.8 SiteCollector 抽象基类) 验证脚本。

P2 阶段只做**接口设计**（不强迁 17 城 sync.py），所以本验证脚本只检查
collectors.base 的基类 API 正确性 + 单元级 mock 测试。

不验证：
- 17 城 sync.py 是否继承 SyncRunner（不强求）
- 17 城 main() 是否重写钩子（不强求）

未来 chongqing v0.8 试点迁移后，扩展本脚本检查 chongqing 端到端集成。

用法：python3 scripts/verify_p2.py
"""
def _resolve_etl_root():
    """解析 gov-price-etl 项目根路径。

    优先级：
      1) 环境变量 GOV_PRICE_ETL_ROOT（部署/调试可显式覆盖）
      2) 自动反推：从本文件路径向上找 'gov-price-etl' 同级目录，
         不依赖硬编码的 workspace 名 / 目录深度。
      3) 兜底扫描：~/.openclaw/workspace/*/skills/gov-price-etl,
         不预设 workspace 名。
      4) 仍找不到：抛错提示用户设环境变量。绝不默默返回错误路径。
    """
    import os
    from pathlib import Path
    env = os.environ.get("GOV_PRICE_ETL_ROOT")
    if env and os.path.isdir(env):
        return env
    p = Path(__file__).resolve().parent
    for _ in range(6):
        candidate = p / "gov-price-etl"
        if candidate.is_dir():
            return str(candidate)
        p = p.parent
    workspace_root = Path.home() / ".openclaw" / "workspace"
    if workspace_root.is_dir():
        for ws in workspace_root.iterdir():
            candidate = ws / "skills" / "gov-price-etl"
            if candidate.is_dir():
                return str(candidate)
    raise FileNotFoundError(
        "找不到 gov-price-etl 项目根。"
        "请设置环境变量 GOV_PRICE_ETL_ROOT 指向项目根，"
        "或确认 ETL 已部署在 <workspace>/skills/gov-price-etl。"
    )


import os
import sys
import tempfile
from pathlib import Path

# 让 etl 模块可被 import
ETL_ROOT = Path(_resolve_etl_root())
sys.path.insert(0, str(ETL_ROOT))

from gov_price_etl.collectors.base import (
    SignalHandler,
    LocalProgressStore,
    SyncRunner,
)

print("==== P2 基类 API 验证 ====\n")

# 1. SignalHandler：上下文管理器 + interrupted 状态
sig = SignalHandler()
assert sig.interrupted is False
print("  ✓ SignalHandler 初始 interrupted=False")

with sig:
    assert sig.interrupted is False
print("  ✓ SignalHandler __enter__/__exit__ 工作正常")

# 模拟 SIGINT：直接调用 _handler
sig2 = SignalHandler()
sig2._handler(2, None)  # 模拟 SIGINT
assert sig2.interrupted is True
print("  ✓ SignalHandler 接收 SIGINT 后 interrupted=True")


# 2. LocalProgressStore：load / save / reset / is_done / mark_done
with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
    tmppath = f.name

try:
    store = LocalProgressStore(tmppath)
    assert store.load() == {}, f"load() empty file 应返回 {{}}, got {store.load()}"
    print("  ✓ LocalProgressStore.load() 空文件返回 {}")

    store.save({"run_id": "test_run", "done_A": ["x", "y"]})
    loaded = store.load()
    assert loaded["run_id"] == "test_run"
    assert loaded["done_A"] == ["x", "y"]
    assert "saved_at" in loaded
    print(f"  ✓ LocalProgressStore.save() 写盘 + saved_at 自动注入: {loaded['saved_at']}")

    assert store.is_done("done_A") is True
    assert store.is_done("done_B") is False
    print("  ✓ LocalProgressStore.is_done(key) 检查 list 非空")

    # mark_done
    prog = store.load()
    store.mark_done("done_B", "item1", prog)
    store.mark_done("done_B", "item2", prog)
    assert "item1" in prog["done_B"]
    assert "item2" in prog["done_B"]
    print("  ✓ LocalProgressStore.mark_done(key, item) 追加到 list")

    # reset
    store.reset()
    assert store.load() == {}
    print("  ✓ LocalProgressStore.reset() 清空文件")
finally:
    if os.path.exists(tmppath):
        os.unlink(tmppath)


# 3. SyncRunner：mock 子类端到端
class MockRunner(SyncRunner):
    """测试用 Mock 采集器"""

    def _list_work_units(self):
        return ["unit1", "unit2", "unit3"]

    def _process_one(self, unit):
        if unit == "unit2":
            return 0, "error"
        return 10, "completed"

    def _on_unit_start(self, unit):
        print(f"  [start] {unit}")

    def _on_unit_done(self, unit, docs_count, status, error=""):
        icon = "✓" if status == "completed" else "✗"
        print(f"  [done] {icon} {unit}: {docs_count} docs ({status})")


with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
    tmppath = f.name

try:
    store = LocalProgressStore(tmppath)
    mock = MockRunner(store, "http://localhost:59200", "test_index", "test_progress")
    result = mock.run()
    assert result["total"] == 3, f"total 应为 3, got {result['total']}"
    assert result["done"] == 2, f"done 应为 2, got {result['done']}"
    assert result["failed"] == 1, f"failed 应为 1, got {result['failed']}"
    assert result["docs_written"] == 20, f"docs_written 应为 20, got {result['docs_written']}"
    assert result["interrupted"] is False
    print(f"\n  ✓ SyncRunner mock 端到端: total=3 done=2 failed=1 docs=20")
    print(f"    result = {result}")
finally:
    if os.path.exists(tmppath):
        os.unlink(tmppath)


# 4. SyncRunner max_units 限制
class FiveUnitRunner(SyncRunner):
    def _list_work_units(self):
        return ["u1", "u2", "u3", "u4", "u5"]
    def _process_one(self, unit):
        return 1, "completed"

with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
    tmppath = f.name
try:
    store = LocalProgressStore(tmppath)
    runner = FiveUnitRunner(store, "http://x", "i", "p")
    result = runner.run(max_units=2)
    assert result["done"] == 2, f"max_units=2 时 done 应为 2, got {result['done']}"
    print(f"  ✓ SyncRunner max_units=2: done=2")
finally:
    if os.path.exists(tmppath):
        os.unlink(tmppath)


# 5. SyncRunner 跳过已完成
class AllUnitsRunner(SyncRunner):
    def _list_work_units(self):
        return ["u1", "u2"]
    def _process_one(self, unit):
        return 1, "completed"

with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
    tmppath = f.name
try:
    # 预先标记 u1 done
    store = LocalProgressStore(tmppath)
    store.save({"u1": ["x"]})  # 让 is_done('u1') = True
    runner = AllUnitsRunner(store, "http://x", "i", "p")
    result = runner.run()
    # is_done('u1') 看 list 长度 > 0 = True，跳过 u1
    # u2 走 _process_one
    assert result["done"] == 1, f"u1 跳过时 done 应为 1, got {result['done']}"
    assert result["skipped"] == 1, f"u1 跳过时 skipped 应为 1, got {result['skipped']}"
    print(f"  ✓ SyncRunner 跳过已 done 单元: done=1 skipped=1")
finally:
    if os.path.exists(tmppath):
        os.unlink(tmppath)


print("\n==== ✅ P2 基类 API 全部通过 ====")
print("chongqing v0.8 试点迁移待后续 session 推进。")