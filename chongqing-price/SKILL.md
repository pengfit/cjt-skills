---
name: chongqing-price
description: "重庆工程造价材料信息采集：从 www.cqsgczjxx.org 抓取区县材料价格数据。"
---

# chongqing-price

重庆工程造价材料信息采集 Skill。从 `www.cqsgczjxx.org`（重庆市建设工程造价信息网）抓取区县材料价格数据，通过 openclaw browser 自动化抓取页面，批量写入本地 ES 索引 `ods_material_chongqing_price`。

## 数据源

- **网址**：`http://www.cqsgczjxx.org/Pages/CQZJW/priceInformation.aspx`
- **分类**：材料信息价（点击"材料信息价"标签页）
- **页面结构**：区县下拉 → 分页表格（材料名称 / 规格型号 / 单位 / 含税价格 / 不含税价格）
- **目标周期**：从 config.yml 的 `sync.last_period` 读取，格式如 `2026年01月`

## 项目结构

```
chongqing-price/
├── config.yml                    # 配置文件（ES、站点、同步周期）
├── .chongqing_sync_progress.json # 本地进度文件（断点续传）
└── commands/
    ├── sync.py        # 同步入口（调用 write_es.cmd_sync）
    ├── write_es.py    # ES 写入核心 + 浏览器自动化实现
    ├── check.py       # 增量检测：根据页面最新周期触发同步
    ├── status.py      # 查看本地/ES 同步进度
    ├── test.py        # 测试 ES 连接
    └── utils.py       # load_config 工具函数
```

## 命令详解

### sync.py — 同步入口

```bash
python3 commands/sync.py --tab-id <tab-id> [--period <周期>] [--reset] [--run-id <id>] [--source <source>]
```

- **--tab-id**：必填，openclaw browser 已打开的标签页 ID（格式如 `t1`）
- **--period**：目标周期，默认 `2026年01月`（从 URL 提取月份数字，如 `04` 月）
- **--reset**：清除本地进度文件，重新全量同步
- **--run-id**：指定本次运行的标识，默认自动生成
- **--source**：数据来源标签页，默认 `district`；可用 `district` / `mortar` / `citywide` / `all`

流程：
1. 初始化 ES 索引（若不存在则创建）
2. 聚焦指定 browser tab，点击"材料信息价"标签页
3. 选中目标月份，遍历所有 36 个区县
4. 每个区县：点击区县 → 翻页提取表格 → 写入 ES → 更新进度
5. 支持 Ctrl+C 中断，保存进度后退出

### write_es.py — 多子命令工具

```bash
# 初始化 ES 索引
python3 commands/write_es.py init

# 写入数据（供 browser 侧调用）
python3 commands/write_es.py write <run_id> <county> <period> <result_json>

# 更新进度
python3 commands/write_es.py progress <run_id> <county> <period> <page> <total_pages> <docs_written> <status> [error] [duration]

# 同步完成汇总
python3 commands/write_es.py summary <run_id> <total_counties> <completed> <total_docs> <duration_sec>

# 完整同步流程
python3 commands/write_es.py sync --tab-id <tab-id> [--period <周期>] [--reset]
```

### check.py — 增量检测（推荐自动化使用）

```bash
python3 commands/check.py
```

自动判断是否需要触发同步：
- 对比 config `last_period` 与网站当前周期，发现新周期则触发全量同步
- 对比 ES 最新已完成周期与 config，判断增量或断点续传
- 后台启动 `sync.py`，日志写入 `/tmp/chongqing-incremental-sync-<timestamp>.log`

前提：browser 已打开目标页面并聚焦到重庆市建设工程造价信息网标签页。

### status.py — 查看进度

```bash
python3 commands/status.py
```

输出：
- 本地进度文件（`.chongqing_sync_progress.json`）：run_id、已完成区县数、保存时间
- ES 进度索引（`ods_chongqing_price_progress`）：各区县同步状态、文档数
- config 中的 `last_period`

### test.py — ES 连接测试

```bash
python3 commands/test.py
```

验证 ES 集群连接是否正常，输出集群状态。

## 配置（config.yml）

```yaml
es:
  host: http://localhost:59200        # ES 地址
  index: ods_material_chongqing_price # 数据索引
  progress_index: ods_chongqing_price_progress  # 进度索引
  sync_log_index: ods_chongqing_price_sync_log  # 同步日志索引
  timeout: 30

site:
  url: http://www.cqsgczjxx.org/Pages/CQZJW/priceInformation.aspx

sync:
  last_period: '2026'                 # 上次同步周期（自动更新）
```

## 数据字段

| 字段 | 说明 |
|------|------|
| `breed` | 材料名称 |
| `spec` | 规格型号 |
| `unit` | 单位 |
| `price` | 不含税价格（浮点数） |
| `tax_price` | 含税价格（浮点数） |
| `is_tax` | 含税/不含税 |
| `period` | 周期（格式 `YYYY-MM-DD`，如 `2026-01-01`） |
| `province` | 重庆 |
| `city` / `county` | 区县名称 |
| `area_code` | 同 county |
| `update_date` | 更新日期（YYYY-MM-DD） |
| `create_time` | 入库时间（YYYY-MM-DD HH:MM:SS） |

## ES 索引

| 索引 | 说明 |
|------|------|
| `ods_material_chongqing_price` | 材料价格数据 |
| `ods_chongqing_price_progress` | 同步进度记录（每区县一条） |

## 支持区县（36 个）

主城区、万州区、涪陵区、黔江区、长寿区、江津区、合川区、永川区、南川区、梁平区、城口县、丰都县、垫江县、忠县、开州区、云阳县、奉节县、巫山县、巫溪县、石柱县、秀山县、酉阳县、大足区、綦江区、万盛经开区、双桥经开区、铜梁区、璧山区、彭水县1、彭水县2、彭水县3、荣昌区1、荣昌区2、潼南区、武隆区

> 注：彭水县分 3 个价格区（1/2/3），荣昌区分 2 个价格区（1/2）。

## 幂等写入

```
_id = MD5(breed + spec + period + price + tax_price + county)
```

同一材料在同一周期同一区县下重复写入会自动覆盖，保证数据一致性。

## 断点续传

- 本地进度文件：`.chongqing_sync_progress.json`（JSON 格式，记录已完成的区县列表）
- 中断后重新运行 `sync.py`，自动跳过已完成的区县
- 传 `--reset` 可清除进度，从头开始

## 依赖

- Python 3
- openclaw（browser 自动化，需先打开目标页面）
- requests、pyyaml、elasticsearch