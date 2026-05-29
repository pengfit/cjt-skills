---
name: xa-material-price
description: "西安工程造价材料信息采集：从 zjj.xa.gov.cn 抓取西安 6 个区县材料价格数据。"
---

# xa-material-price

西安工程造价材料信息采集。从 `zjj.xa.gov.cn` 抓取西安 6 个区县材料价格数据，按更新日期增量同步至本地 ES。

## 数据流

```
zjj.xa.gov.cn
     ↓ (sync.py)
ods_material_xian_price (ES)
     ↓ (gov-price-etl / etl.py)
dwd_xian_price
     ↓ (sync_dws.py)
dws_xian_price
```

## 快速启动

```bash
cd skills/xa-material-price

./run.sh preview --pages 3    # 预览前3页（不写ES）
./run.sh sync                  # 增量同步（自动断点续传）
./run.sh sync --force          # 强制全量同步
./run.sh sync --reset          # 重置进度，从第1页重新开始
./run.sh sync --counties "蓝田县,周至县"   # 指定区县
./run.sh check                 # 增量检测
./run.sh status                # 查看同步状态
./run.sh test                  # 测试 ES 连接
```

## 命令清单

| 命令 | 脚本 | 说明 |
|------|------|------|
| `sync` | `commands/sync.py` | 同步主程序，支持增量/断点续传/进度写入 ES |
| `check` | `commands/check.py` | 增量检测，发现新增数据后后台触发 sync |
| `preview` | `commands/preview.py` | 预览数据（不写 ES），默认 1 页 |
| `status` | `commands/status.py` | 查看同步状态、ES 文档数、各区县统计 |
| `test` | `commands/test.py` | 测试 ES 连接与索引存在性 |

### sync 命令参数

| 参数 | 说明 |
|------|------|
| `--force` | 强制全量同步，忽略增量判断 |
| `--reset` | 重置进度，从头开始 |
| `--counties "区县1,区县2"` | 指定区县（逗号分隔），默认全部 6 个 |
| `--max-pages N` | 每区县最大页数（默认 2000）|
| `--no-log` | 不写入 ES 进度索引（纯预览）|
| `--no-spot-check` | 跳过增量抽检（增量同步专用）|
| `--resume-from COUNTY` | 从指定区县继续，跳过后续区县 |

### preview 命令参数

| 参数 | 说明 |
|------|------|
| `--pages N` | 预览页数（默认 1）|
| `--county 区县` | 只抓取指定区县 |

## 配置文件 config.yml

```yaml
es:
  host: http://localhost:59200
  index: ods_material_xian_price          # 数据目标索引
  progress_index: ods_material_xian_price_sync_progress  # 进度索引
  sync_log_index: ods_material_xian_price_sync_log       # 同步日志索引
  batch_size: 500
  timeout: 30

site:
  base_url: https://zjj.xa.gov.cn/zxcx/gczj/index.aspx
  counties:
    - 阎良区
    - 临潼区
    - 高陵区
    - 鄠邑区
    - 蓝田县
    - 周至县
  page_param: page

sync:
  last_update_date: '2026-05-28'   # 自动维护，记录最近一次同步的更新日期
```

## ES 索引

| 索引 | 说明 |
|------|------|
| `ods_material_xian_price` | 材料价格数据（主数据） |
| `ods_material_xian_price_sync_progress` | 同步进度（按 run_id + county 分录） |

### 数据字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `code` | keyword | 材料编码 |
| `breed` | text + keyword | 材料名称 |
| `spec` | text + keyword | 规格型号 |
| `unit` | keyword | 单位 |
| `price` | float | 除税价格 |
| `tax_price` | float | 含税价格 |
| `county` | keyword | 区县 |
| `province` | keyword | 陕西 |
| `city` | keyword | 西安 |
| `update_date` | date | 更新时间（来源页脚解析） |
| `create_time` | date | 入库时间 |

## 增量逻辑

基于**更新时间**判断：

1. 读取 ES 中该区县 `update_date` 最新的一条记录作为 `last_update_date`
2. 抓取每页后，从页脚解析"更新时间：YYYY-MM-DD"
3. 若 `更新时间 < last_update_date` → 停止（已无增量）
4. 若 `更新时间 == last_update_date` → 继续抓取
5. 新页面更新时间 < 上次记录时间 → 中断（数据回退）

## 增量抽检（Spot Check）

`sync` 命令开始时自动对 6 个区县逐一抽检（可用 `--no-spot-check` 跳过）：

- **方法**：ES 中该区县 `create_time` 正序前 10 条 vs 网站首页该区县前 10 条
- **匹配键（5 字段）**：`breed + spec + unit + price + tax_price`，完全一致视为同一记录
- **结果写入**：`ods_material_xian_price_sync_progress` 的 `spot_check_ok`（布尔）和 `spot_check_details`（字符串）

## 断点续传

进度保存到本地 `.sync_progress.json`（按区县分别记录页码），中断后运行 `./run.sh sync` 自动从上次位置继续。

ES 进度索引 `ods_material_xian_price_sync_progress` 实时记录每个区县的同步状态（page/percent/docs_written/duration），_id = `{run_id}_{county}`。

## 幂等写入

```
_id = MD5(breed + code + spec + county + update_date + price + tax_price)
```

同一材料在同一区县、日期、价格下重复同步不会产生重复数据。价格变化时生成新文档，保留价格历史。

## 项目结构

```
xa-material-price/
├── run.sh                          # 入口脚本
├── config.yml                      # ES/站点配置
├── .sync_progress.json             # 本地进度文件（自动生成）
└── commands/
    ├── sync.py     # 同步主程序（含 ProgressStore/ProgressLogger）
    ├── check.py    # 增量检测（自动触发后台 sync）
    ├── preview.py  # 预览模式（不写入 ES）
    ├── status.py   # 查看同步状态
    ├── test.py     # 测试 ES 连接
    └── utils.py    # SiteSession、解析函数、抽检、索引创建
```

## 依赖

- Python 3
- requests
- beautifulsoup4
- pyyaml
- elasticsearch（ES 8.x 兼容）