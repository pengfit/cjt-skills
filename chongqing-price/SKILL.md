---
name: chongqing-price
description: "重庆工程造价材料信息采集：从 www.cqsgczjxx.org 抓取 3 个 source（district/mortar/citywide）+ 5 个 citywide 子分类的材料价格，支持 v4 区间价解析。"
---

# chongqing-price

重庆工程造价材料信息采集 Skill。从 `www.cqsgczjxx.org` 抓取**3 个 source × 5 个 citywide 子分类**的建材价格，写入本地 ES `ods_material_chongqing_price`。

> 默认走 `chongqing_collector`（v0.9 SyncRunner 抽象基类版本）。`--legacy` 走 v3 `cmd_sync`。
> 已在 2026-07-02 生产试跑 1 次（run_id=`v08_pilot_full_20260702`，5 个月全量）。

## 数据源

| source | 区县数 | 页面 div | 价格特征 |
|---|---|---|---|
| `district` | 35 | `gqxdfclDiv` | 7 列单值 |
| `mortar` | 4 | `ybsjDiv` | 7 列单值 |
| `citywide` | 1（主城区） | `zyclDiv` | 见下 |

**citywide 5 个子分类**（实际 3 个有数据）：

| category | 列数 | 价格特征 | 源站现状 |
|---|---|---|---|
| 建安工程材料 | 7 | 单值 | ✅ |
| **园林绿化工程材料** | **11** | **区间价**（"115-173 元/株"）+ 全冠/全干特殊值 | ✅ |
| 绿色、节能建筑工程材料 | 7 | 单值 | ✅ |
| 装配式建筑工程成品构件 | 7 | 单值 | ⚪ 原站无数据 |
| 城市轨道交通工程材料 | 7 | 单值 | ⚪ 原站无数据 |

## 项目结构

```
chongqing-price/
├── config.yml                    # ES / 站点配置
├── .chongqing_sync_progress.json # 本地进度（断点续传）
├── run.sh                        # 启动脚本
├── skill.yml                     # dashboard registry
└── commands/
    ├── sync.py               # 同步入口（默认 Collector；--legacy 走 v3）
    ├── write_es.py           # v3 fallback + ES 写入 + 进度
    ├── chongqing_collector.py# v0.9 默认：SyncRunner 抽象基类化
    ├── check.py              # 增量检测（页面月份 vs ES 最新）
    ├── status.py             # 查看本地/ES 进度
    ├── test.py               # ES 连通性测试
    └── utils.py              # load_config
```

## 快速开始

```bash
cd ~/.openclaw/workspace/skills/chongqing-price

# 同步（默认 Collector 路径）
python3 commands/sync.py --tab-id t1 --source all --period "2026年05月"

# 多周期批量
python3 commands/sync.py --tab-id t1 --periods "2026年01月,2026年02月,2026年03月,2026年04月,2026年05月"

# 单 source
python3 commands/sync.py --tab-id t1 --source district --period "2026年05月"

# v3 兼容（仅 Collector 异常时备用）
python3 commands/sync.py --tab-id t1 --legacy --source all --period "2026年05月"

# 其他命令（用 run.sh 也行）
python3 commands/check.py      # 增量检测
python3 commands/status.py     # 查看进度
python3 commands/test.py       # ES 连通性
```

## 关键特性

- **断点续传**：本地 + ES 双层进度，按 `done_<source>_<period>` 隔离；`--reset` 清除
- **幂等写入**：`_id` = `hash(breed + spec + period + price_min/max + county)`
- **v4.1 区间价**：`"115-173"` → `price_min/price_max/is_range`；特殊值"全冠/全干"走 `range_notes`
- **2 道保护告警**（仅园林景观类目触发）：
  - 列数 < 11 → 跳过 + WARN（防原站表头变化）
  - 价格解析失败 → WARN+sample（仍入库但 DWS 过滤）
- **SIGINT 安全**：Ctrl+C 保存进度后退出
- **Collector 默认**：`chongqing_collector.py` 用 `gov_price_etl.collectors.base.SyncRunner` 抽象基类

## 依赖

- Python 3.10+
- openclaw（browser 自动化）
- requests、pyyaml
- **gov-price-etl skill**（部署在 `~/.openclaw/workspace/skills/gov-price-etl`）— 强依赖：
  - `parse_price.parse_interval_price`
  - `indexer.ensure_progress_index`
  - `collectors.base.SyncRunner`
  - `build_ods_mapping` / `build_progress_mapping`
  - 部署缺失时 `write_es.py` 顶部会 hard raise

---

**完整手册见 [README.md](./README.md)**（含完整参数表、数据字段、故障排查、变更日志）。