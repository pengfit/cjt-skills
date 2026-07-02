"""collectors/base.py - 采集器抽象基类（v0.8, 2026-07-02 设计阶段）

P2 阶段设计：17 城 sync.py 各自实现主流程（多周期 / 多 source / 断点续传 /
SIGINT / 保护告警），共 9000+ 行，逻辑高度相似但站点特化逻辑差异大。

本模块提供**接口抽象**（不强制迁移），分三层：
1. SignalHandler —— SIGINT 中断上下文管理器
2. LocalProgressStore —— 通用本地 JSON 进度存储（key 形状灵活）
3. SyncRunner —— 主流程基类（多周期 × 多工作单元 × 断点续传 × 进度上报）

设计原则：
- **接口稳定**：子类重写钩子函数，不必继承 SyncRunner（duck typing）
- **不强迁**：chongqing v3 已最完整，作为参考实现保留现有写法
- **可测试**：每个组件可独立 mock
- **chongqing 试点**（v0.8 后续）：让 chongqing v3 内部用本框架重写，验证 API 合理性

**v0.8 决策记录**（参考 P0/P1 经验）：
- 主流程**不能**一刀切抽到基类——站点特化逻辑占代码 80%（chongqing browser / qingdao PDF /
  sichuan ASP.NET requests / xinjiang xlsx），强行抽象会导致"为了抽象而抽象"
- **只抽通用基础设施**：SIGINT / 本地进度 / 进度上报，**让 sync.py 主流程各自实现**
- 长期目标：未来加新城市时参考 SyncRunner 设计，自己实现 main 流程 + 复用基类组件

## 迁移路线图（v0.8+）

### chongqing（v0.8 试点，最完整）
- 把 `_load_progress` / `_save_progress_all` / `_reset_progress` 委托到 LocalProgressStore
- 把 SIGINT 信号处理改用 SignalHandler 上下文
- 验证：35 个 county × 5 category × 多周期跑通

### 16 城（v0.9+ 渐进迁移，不强求）
- 各城市按需选用 SignalHandler / LocalProgressStore
- 主流程 main() 保持各自实现（站点特化）

## 使用示例

```python
# chongqing 未来 v0.8 重构后：
from gov_price_etl.collectors.base import (
    LocalProgressStore, SignalHandler, SyncRunner,
)

class ChongqingCollector(SyncRunner):
    def __init__(self, cfg):
        super().__init__(
            progress=LocalProgressStore(cfg['sync']['progress_file']),
            es_host=cfg['es']['host'],
            es_index=cfg['es']['ods_index'],
            progress_index=cfg['es']['progress_index'],
        )
        self.tab_id = None  # 浏览器
    
    def _list_work_units(self):
        # 35 county × 3 source × 多 period
        ...
    
    def _process_one(self, unit):
        # 浏览器点击 + 抓数据 + 解析 + 写 ES
        ...
```
"""
from __future__ import annotations

import json
import os
import signal
import time
from abc import ABC, abstractmethod
from contextlib import contextmanager
from typing import Callable, Optional


# ─────────────────────────────────────────────────────────────
# SignalHandler - SIGINT 中断上下文管理器
# ─────────────────────────────────────────────────────────────

class SignalHandler:
    """SIGINT 中断上下文管理器（v0.8, 2026-07-02）。

    适用场景：sync 主循环需要响应 Ctrl+C，触发 finally 钩子保存进度。

    用法：
        sig = SignalHandler()
        sig.install()
        try:
            for unit in units:
                if sig.interrupted:
                    break
                process_one(unit)
        finally:
            on_interrupt()
            sig.uninstall()
    """

    def __init__(self):
        self.interrupted = False
        self._old_handler = None

    def install(self) -> None:
        """注册 SIGINT 处理器。"""
        self._old_handler = signal.signal(signal.SIGINT, self._handler)

    def uninstall(self) -> None:
        """恢复原 SIGINT 处理器。"""
        if self._old_handler is not None:
            signal.signal(signal.SIGINT, self._old_handler)
            self._old_handler = None

    def _handler(self, signum, frame):
        self.interrupted = True

    def __enter__(self):
        self.install()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.uninstall()
        return False  # 不抑制异常


# ─────────────────────────────────────────────────────────────
# LocalProgressStore - 本地 JSON 进度存储
# ─────────────────────────────────────────────────────────────

class LocalProgressStore:
    """本地 JSON 进度存储（v0.8, 2026-07-02）。

    适用场景：断点续传，把"已完成 key"存到本地文件，避免跨重启重复抓取。

    通用 API：
    - load() → dict（整个进度字典，文件不存在返回空 dict）
    - save(progress: dict) → None
    - reset() → None（清空）
    - is_done(key: str) → bool
    - mark_done(key: str) → None（不实际写盘，需配合 save()）

    key 形状灵活：chongqing 用 'done_<source>_<period>'，其他城市可用任意字符串。
    """

    def __init__(self, path: str):
        self.path = path

    def load(self) -> dict:
        """加载进度文件，文件不存在/解析失败返回空 dict。"""
        if not os.path.exists(self.path):
            return {}
        try:
            with open(self.path, encoding="utf-8") as f:
                return json.load(f) or {}
        except Exception:
            return {}

    def save(self, progress: dict) -> None:
        """保存进度到文件（含 saved_at 时间戳）。"""
        progress["saved_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(progress, f, ensure_ascii=False, indent=2)

    def reset(self) -> None:
        """清空进度文件。"""
        if os.path.exists(self.path):
            os.remove(self.path)

    def is_done(self, key: str) -> bool:
        """检查某 key 是否在进度字典中（list 类型检查第一个元素即可）。"""
        progress = self.load()
        val = progress.get(key, [])
        if isinstance(val, list):
            return len(val) > 0  # 简化：非空列表 = 已完成
        return bool(val)

    def mark_done(self, key: str, item: str, progress: Optional[dict] = None) -> dict:
        """标记某 key 下的某 item 完成（in-memory，不写盘）。

        Returns:
            修改后的 progress dict（也写回 progress 参数，如有）。
        """
        if progress is None:
            progress = self.load()
        lst = progress.setdefault(key, [])
        if item not in lst:
            lst.append(item)
        return progress


# ─────────────────────────────────────────────────────────────
# SyncRunner - 主流程抽象基类
# ─────────────────────────────────────────────────────────────

class SyncRunner(ABC):
    """同步主流程抽象基类（v0.8, 2026-07-02 设计阶段）。

    提供：
    - 工作单元列表（多周期 × 多 source）
    - 断点续传（LocalProgressStore）
    - SIGINT 中断（SignalHandler）
    - run 汇总（cmd_summary 风格）

    子类**重写钩子**（不必继承所有逻辑）：
    - _list_work_units() → list of unit（unit 形状由子类定义）
    - _process_one(unit) → tuple[int, str]（返回 docs_count, status）
    - _on_unit_start(unit) → None（可选，默认 print）
    - _on_unit_done(unit, docs_count, status) → None（可选，默认 print）

    **不强求使用**：17 城 sync.py 各自实现 main()，本基类作为未来重构参考。
    chongqing v0.8 试点用本基类重写，验证 API 合理性后再决定是否全量推广。
    """

    def __init__(
        self,
        progress: LocalProgressStore,
        es_host: str,
        es_index: str,
        progress_index: str,
    ):
        self.progress = progress
        self.es_host = es_host
        self.es_index = es_index
        self.progress_index = progress_index

    @abstractmethod
    def _list_work_units(self) -> list:
        """返回工作单元列表（形状由子类定义）。

        例 chongqing：[(source, county, period), ...]
        例 qingdao：  [{'period': ..., 'pdf_url': ...}, ...]
        """
        raise NotImplementedError

    @abstractmethod
    def _process_one(self, unit) -> tuple[int, str]:
        """处理单个工作单元：抓 + 解析 + 写 ES。

        Returns:
            (docs_count, status) 元组，status = 'completed' | 'error'。
        """
        raise NotImplementedError

    def _on_unit_start(self, unit) -> None:
        """工作单元开始钩子（默认 print）。子类可重写。"""
        print(f"[{self.__class__.__name__}] >>> {unit}")

    def _on_unit_done(self, unit, docs_count: int, status: str, error: str = "") -> None:
        """工作单元完成钩子（默认 print）。子类可重写。"""
        icon = "✓" if status == "completed" else "✗"
        print(f"  [{icon}] {unit}: {docs_count} docs ({status})")

    def _compute_unit_key(self, unit) -> str:
        """工作单元的本地进度 key（默认用 str(unit)，子类可重写）。"""
        return str(unit)

    def run(self, max_units: Optional[int] = None, reset: bool = False) -> dict:
        """主流程：遍历工作单元 × 抓 + 解析 + 写 ES × 进度上报。

        Args:
            max_units: 最多处理多少个单元（测试用，None = 全部）
            reset: 是否重置本地进度

        Returns:
            {
                'total': int,         # 总单元数
                'done': int,          # 完成数
                'failed': int,        # 失败数
                'skipped': int,       # 跳过数（已 done）
                'docs_written': int,  # 写入文档总数
                'duration_sec': float,
                'interrupted': bool,
            }
        """
        if reset:
            self.progress.reset()

        units = self._list_work_units()
        print(f"[{self.__class__.__name__}] 共 {len(units)} 个工作单元")

        sig = SignalHandler()
        sig.install()
        start = time.time()
        done = failed = skipped = 0
        total_docs = 0

        try:
            for i, unit in enumerate(units, 1):
                if sig.interrupted:
                    break
                if max_units and done >= max_units:
                    break
                key = self._compute_unit_key(unit)
                if self.progress.is_done(key):
                    skipped += 1
                    continue
                self._on_unit_start(unit)
                try:
                    docs_count, status = self._process_one(unit)
                    self._on_unit_done(unit, docs_count, status)
                    if status == "completed":
                        done += 1
                        total_docs += docs_count
                    else:
                        failed += 1
                except Exception as e:
                    self._on_unit_done(unit, 0, "error", str(e))
                    failed += 1
        finally:
            sig.uninstall()

        return {
            "total": len(units),
            "done": done,
            "failed": failed,
            "skipped": skipped,
            "docs_written": total_docs,
            "duration_sec": time.time() - start,
            "interrupted": sig.interrupted,
        }


# ─────────────────────────────────────────────────────────────
# 公开 API
# ─────────────────────────────────────────────────────────────

__all__ = [
    "SignalHandler",
    "LocalProgressStore",
    "SyncRunner",
]