---
name: gov-price-auto-mine
description: "Playwright 浏览器自动化：驱动 gov-price-dashboard UI 完成规格规则挖掘全流程，无需本地 AI 模型和数据库交互。"
---

# gov-price-auto-mine

**纯浏览器自动化方案** — 通过 Playwright 连接 OpenClaw 已打开的 Chrome（CDP），模拟人工在 Dashboard 上操作，完成规格解析规则挖掘全部流程。不另起窗口，不影响 OpenClaw 自身的 browser 工具。

## 流程（自动化）

```
展开城市 → DWD 按钮 → 规格解析质量面板
    ↓
遍历分类卡片（解析率 < 80% 的优先）：
    ↓
  ① 「抽」→ 抽样面板
    ↓
  ② 点击未解析样本 → fix-case 弹窗
    ↓
  ③ 「AI 建议」→ 规则生成
    ↓
  ④ 逐条「确认录入」→ 规则库
    ↓
  ⑤ 关闭弹窗 → 关闭抽样面板
    ↓
  ⑥ 「洗」→ 确认清洗弹窗 → 等待完成
    ↓
循环直到分类解析率 ≥ 80%
```

## 用法

```bash
# 后台运行（非阻塞主会话）
bash run.sh rizhao        # 仅日照
bash run.sh xian          # 仅西安
bash run.sh all           # 全部城市
bash run.sh rizhao --headless   # 无头模式

# 直接运行（阻塞）
python3 scripts/playwright-auto-mine.py --city rizhao
python3 scripts/playwright-auto-mine.py --city all --headless
```

日志文件：`logs/auto-mine-YYYYMMDD-HHMMSS.log`

## 依赖

- Dashboard 运行于 `http://localhost:5300`
- OpenClaw 已打开的 Chrome（通过 CDP `http://127.0.0.1:18800` 复用）
- `pip install playwright`

## 解析率阈值

解析率 ≥ **80%** 视为已完成，脚本自动跳过该分类。

## 城市 key

| key | 城市 |
|-----|------|
| `xian` | 西安 |
| `sichuan` | 四川 |
| `chongqing` | 重庆 |
| `jinan` | 济南 |
| `rizhao` | 日照 |