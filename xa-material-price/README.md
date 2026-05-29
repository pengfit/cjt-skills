# 西安工程造价材料信息采集工具

从 https://zjj.xa.gov.cn/zxcx/gczj/index.aspx 抓取西安 6 个区县材料价格数据，全量/增量同步至本地 Elasticsearch。

## 支持区县（6 个）

阎良区、临潼区、高陵区、鄠邑区、蓝田县、周至县

## 快速开始

```bash
cd ~/.openclaw/workspace/skills/xa-material-price

# 增量同步（自动判断是否有新数据）
./run.sh sync

# 预览数据（不写入 ES）
./run.sh preview
./run.sh preview --pages 3    # 只看前3页

# 强制全量同步（忽略增量判断）
./run.sh sync --force

# 指定区县同步（逗号分隔）
./run.sh sync --counties "蓝田县,周至县"

# 查看同步状态
./run.sh status

# 测试 ES 连接
./run.sh test
```

## 增量检测（自动触发同步）

定时运行 `check` 命令，自动对比网站首页总记录数与 ES 文档数，发现增量后立即触发后台同步：

```bash
./run.sh check     # 手动运行

# 建议每小时一次定时增量检测
0 * * * * cd ~/.openclaw/workspace/skills/xa-material-price && ./run.sh check
```

流程：抓取 6 区县首页 → 比对 `网站总记录数 vs ES 文档数` → 发现增量区县 → 后台触发 `./run.sh sync --force --no-spot-check --counties=增量区县`

## 断点续传（自动）

程序会自动保存进度到 `.sync_progress.json`（按区县分别记录），中断后直接重新运行同一命令，自动从上次位置继续：

```bash
./run.sh sync      # Ctrl+C 中断
./run.sh sync      # 重启后，自动检测进度并续传
```

## 同步参数

| 参数 | 说明 |
|------|------|
| `--counties "区县1,区县2"` | 指定区县，默认全部 6 个 |
| `--reset` | 重置进度，从头开始 |
| `--force` | 强制全量同步，忽略增量判断 |
| `--max-pages N` | 每区县最大页数（默认 2000）|
| `--no-log` | 不写入 ES 进度索引（纯预览）|
| `--no-spot-check` | 跳过抽检（增量同步专用，避免重复抽检）|
| `--resume-from COUNTY` | 从指定区县继续，跳过后续区县 |

## 增量逻辑

基于**更新时间**判断（`./run.sh sync` 自动执行）：

1. 读取 ES 中该区县 `update_date` 最新的一条记录作为 `last_update_date`
2. 抓取每页后，从页脚解析"更新时间：YYYY-MM-DD"
3. 若 `更新时间 < last_update_date` → 停止，已无增量
4. 若 `更新时间 == last_update_date` → 继续抓取
5. 新页面更新时间 < 上次记录时间 → 中断（数据回退）

## 增量抽检（Spot Check）

`sync` 命令开始时自动对 6 个区县逐一抽检（可用 `--no-spot-check` 跳过）：

- **方法**：ES 中该区县 `create_time` 正序前 10 条 vs 网站首页该区县前 10 条
- **匹配键（5 字段）**：`breed + spec + unit + price + tax_price`，完全一致视为同一记录
- **结果写入**：`ods_material_xian_price_sync_progress` 的 `spot_check_ok`（布尔）和 `spot_check_details`（字符串）
- **用途**：供 gov-price-dashboard Web 页面显示"✓ 抽检通过"或"✗ 抽检异常"标签

```bash
# 查看最近一次抽检结果
curl -s "http://localhost:59200/ods_material_xian_price_sync_progress/_search?size=1&sort=last_updated:desc" \
  -H "Content-Type: application/json" \
  -d '{"_source":["spot_check_ok","spot_check_details"]}'
```

## 幂等写入

文档以 `MD5(breed+code+spec+county+update_date+price+tax_price)` 作为 `_id`，重复同步不会产生重复数据。价格变化时生成新文档，能保留价格历史。

## 数据字段

| 字段 | 说明 |
|------|------|
| `code` | 材料编码 |
| `breed` | 材料名称 |
| `spec` | 规格型号 |
| `unit` | 单位 |
| `price` | 除税价格 |
| `tax_price` | 含税价格 |
| `county` | 区县 |
| `province` | 陕西 |
| `city` | 西安 |
| `update_date` | 更新时间（页脚解析） |
| `create_time` | 入库时间 |

## 配置文件

`config.yml` 控制 ES 连接和同步参数：

```yaml
es:
  host: http://localhost:59200
  index: ods_material_xian_price
  progress_index: ods_material_xian_price_sync_progress
  sync_log_index: ods_material_xian_price_sync_log
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

sync:
  last_update_date: '2026-05-28'
```

## 项目结构

```
xa-material-price/
├── README.md
├── SKILL.md
├── run.sh              # 入口脚本
├── config.yml          # ES/站点配置
├── .sync_progress.json # 进度文件（自动生成，按区县分别记录）
└── commands/
    ├── sync.py         # 同步主程序（含 ProgressStore 本地进度 / ProgressLogger ES 进度）
    ├── check.py        # 增量检测（自动触发后台同步）
    ├── preview.py      # 预览模式（不写入 ES）
    ├── status.py       # 查看同步状态
    ├── test.py         # 测试 ES 连接
    └── utils.py        # SiteSession、parse_page_date、parse_table_rows、spot_check_county、ensure_index、load_config
```

## 数据流（完整链路）

```
zjj.xa.gov.cn
     ↓ sync.py
ods_material_xian_price (ES)
     ↓ gov-price-etl (etl.py)
dwd_xian_price
     ↓ sync_dws.py
dws_xian_price
```

## 依赖

- Python 3
- requests
- beautifulsoup4
- pyyaml
- Elasticsearch 7.x / 8.x