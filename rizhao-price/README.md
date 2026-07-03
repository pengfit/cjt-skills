# rizhao-price · 日照工程造价材料信息采集

日照市住房和城乡建设局发布《日照市建设工程材料价格信息》，数据源：
`http://58.59.43.227:81/dist/#/index/priceDissemination`（Vue + ElementUI 动态页面）。

> 🆕 **v1.0（2026-07-03）模块建构参考重庆**（SyncRunner 抽象基类化）
> + **必含字段** `period_start` / `period_end` / `period_days`

## 模块建构（参考重庆 v0.8 + 河南 v0.8）

```
旧 v0：sync.py 流式主程序（单文件 ~500 行）
      ↓
v1.0：RizhaoCollector(SyncRunner)
      ├── 继承 ETL 公共基类（gov_price_etl.collectors.base.SyncRunner）
      ├── 重写 4 个钩子（_list_work_units / _process_one / _on_unit_done / _compute_unit_key）
      ├── CLI 默认 Collector；--legacy 兼容 v0
      └── 文档字段含 period_start / period_end / period_days
```

## 数据范围

| 类别（tab_type）| 名称 | 2026-05 数量 |
|---|---|---|
| 1 | 建设工程材料 | 1084 |
| 2 | 园林绿化苗木 | 2 |
| 3 | 区县建设工程材料 | 60 |
| **合计** | | **1146** |

- 源站只暴露当前期（`'2026-05'`），历史期不支持回溯
- 默认同步策略：3 tab × 最新期 = 3 units

## 数据字段（v1.0 完整列表）

```json
{
  "breed": "普线",
  "spec": "Φ6.5 Q235",
  "unit": "吨",
  "price": 3863.12,
  "price_min": 3863.12,
  "price_max": 3863.12,
  "price_range": "3863.12",
  "is_range": false,

  "period": "2026-05",
  "period_start": "2026-05-01",
  "period_end": "2026-05-31",
  "period_days": 31,

  "update_date": "2026-05-01",
  "create_time": "2026-07-03 17:12:49",

  "province": "山东",
  "city": "日照市",
  "county": "日照市",
  "tab_type": "1",
  "tab_name": "建设工程材料",
  "source_index": "ods_material_rizhao_price",
  "remark": ""
}
```

**v1.0 必含字段**（道友要求）：
- `period_start`：周期起始日（`'2026-05-01'`）
- `period_end`：周期结束日（`'2026-05-31'`）
- `period_days`：周期天数（`'31'`，5月有31天；2月平年28/闰年29；`calendar.monthrange` 推算）

## 快速开始

```bash
cd ~/.openclaw/workspace/skills/rizhao-price

# 默认同步（Collector 路径）
./run.sh sync

# 只抓某个 tab
./run.sh sync --tabs 1

# 抓多 tab
./run.sh sync --tabs 1,3

# 重置进度重新开始
./run.sh sync --reset

# 验证模式：只跑前 1 个 unit
./run.sh sync --max-units 1

# v0 兼容路径（逃生通道）
./run.sh sync --legacy

# 查看状态
./run.sh status
```

## CLI 高级参数

```bash
python3 commands/sync.py --help
#  --tabs      tab 列表（逗号分隔），如 '1,2,3' 或 '1'
#  --period    指定周期（如 '2026-05'）。默认从源站自动探测
#  --reset     重置本地进度，重新开始
#  --max-units 只跑前 N 个工作单元（验证用）
#  --legacy    走 v0 流式旧路径（逃生通道）
#  --max-pages 最大页数（默认 2000）
#  --run-id    指定 run_id（默认自动生成）
```

## 项目结构

```
rizhao-price/
├── run.sh                       # CLI 入口
├── config.yml                   # 配置文件
├── package.json                 # npm 依赖（playwright）
├── .rizhao_sync_progress.json   # 本地进度（自动生成）
├── .bak_v0/                     # v0 备份（重构前）
└── commands/
    ├── sync.py                  # 同步入口（默认 Collector / --legacy）
    ├── rizhao_collector.py      # v1.0 Collector（SyncRunner 化）★ 新增
    ├── legacy_sync.py           # v0 兼容路径 ★ 新增
    ├── fetch_data.js            # Playwright 浏览器抓取
    ├── utils.py                 # 共用函数
    ├── status.py                # v1.0 状态查看
    ├── check.py                 # 增量检测
    ├── test.py                  # ES 连接测试
    └── preview.py               # 预览（兼容 v0）
```

## ES 索引

| 索引 | 说明 |
|------|------|
| `ods_material_rizhao_price` | 材料价格数据（套用 `gov_ods` ETL 共享 mapping） |
| `ods_rizhao_price_sync_progress` | 同步进度（每个 tab × period 一条） |

## 依赖

- **Python 3.10+** + `requests` `pyyaml`
- **Node.js** + `playwright`（需提前 `npx playwright install chromium`）
- **gov-price-etl skill**（`~/.openclaw/workspace/skills/gov-price-etl`）— 强依赖：
  - `collectors.base.SyncRunner`
  - `indexer.ensure_ods_index`
  - `indexer.ensure_progress_index`
  - `mappings.build_ods_mapping` / `build_progress_mapping`
- **本地 ES**：`http://localhost:59200`

## 故障排查

| 问题 | 解决 |
|------|------|
| `fetch_data.js` 启动失败 | 检查 `package.json` 是否安装 playwright + chromium |
| 进度文件残留导致重复抓 | `rm .rizhao_sync_progress.json` 或 `--reset` |
| ES `dynamic=strict` 写入失败 | 用 `mappings.build_ods_mapping()` 重建 mapping；不可写未声明字段 |
| 浏览器连接超时 | 检查 `CHROME_PATH` 是否有效 |

## 变更日志

### v1.0（2026-07-03）

- **模块建构参考重庆 v0.8**：默认走 `RizhaoCollector`（继承 `SyncRunner` 抽象基类）
  - 重写 4 个钩子：`_list_work_units` / `_process_one` / `_on_unit_done` / `_compute_unit_key`
  - `--legacy` 保留 v0 流式路径作为逃生通道
- **字段扩展**（道友要求）：每个 doc 必含 `period_start` / `period_end` / `period_days`
  - `parse_period_window('2026-05')` → `{'period_start': '2026-05-01', 'period_end': '2026-05-31', 'period_days': 31}`
- **mapping 标准化**：委托到 `gov_price_etl.indexer`，自动含 17 城合集字段
- **CLI 扩展**：`--tabs` / `--period` / `--max-units` / `--legacy`
- **status.py 重写**：按 tab × period 聚合展示，含 period 窗口字段

### v0（2026-05-22）

- 流式 Playwright 抓取（3 tab）
- 单文件 `sync.py` 主程序