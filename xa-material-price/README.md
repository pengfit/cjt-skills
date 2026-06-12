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

# 按周期（造价信息表月份）同步 ⭐ 新增
./run.sh sync --period 2026-01 --counties 阎良区
./run.sh sync --period 2026-01,2026-02 --counties 阎良区,周至县
./run.sh sync --periods-year 2025                # 2025 整年
./run.sh sync --periods-all --counties 阎良区     # 该区县所有周期

# 列出全部可用周期
./run.sh sync --list-periods

# 查看同步状态
./run.sh status

# 测试 ES 连接
./run.sh test
```

## 增量检测（自动触发同步）

定时运行 `check` 命令，按 **区县×周期** 粒度检测 ES 缺失，发现后自动后台触发 sync 补抓。

```bash
./run.sh check                  # 手动运行（默认按区县×周期粒度）
./run.sh check --counties 阎良区  # 只检测某个区县
./run.sh check --dry-run        # 只检测不触发同步
./run.sh check --legacy         # 用老逻辑：按区县总记录数对比（不区分周期）

# 建议每小时一次定时增量检测
0 * * * * cd ~/.openclaw/workspace/skills/xa-material-price && ./run.sh check
```

**检测流程**（新逻辑）：

1. 对 6 个区县逐一拉取所有有数据的周期（源站 `Handler.ashx`）
2. 对每个 (county, month) 组合：
   - 拿网站该月首页 total
   - 拿 ES 中 `term: {county, month}` 的 count
   - 差异 > 0 → 加入缺失列表
3. 按区县聚合缺失周期，后台触发 `./run.sh sync --period YYYY-MM[,...] --counties 区县`

示例输出：

```
[i] 增量检测开始...
[i] 模式: 按区县×周期粒度
  [阎良区] 共 8 个周期待检测
    [阎良区 2025-07] 网站 2059 > ES 0  (+2059)  ⚠ 待补
    [阎良区 2025-08] 网站 2060 > ES 0  (+2060)  ⚠ 待补
    ...
    [阎良区 2026-01] ✓ 2060 条已齐
    [阎良区 2026-02] ✓ 2060 条已齐

[i] 发现 6 个 (区县×周期) 缺失:
  阎良区 2025-07: 缺 2059 条
  ...

[→] 触发增量同步（按区县聚合,后台运行）...
  [阎良区] PID 12345  周期:2025-07,2025-08,2025-09,2025-10,2025-11,2025-12  日志:/tmp/xian-sync-阎良区.log
```

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
| `--dry-run` | 预览模式（不写入 ES） |
| `--period YYYY-MM[,...]` | 指定造价信息表月份 |
| `--periods-year YYYY` | 抓取整年所有月份 |
| `--periods-all` | 抓取所有有数据的周期 |
| `--list-periods` | 只列出可用周期，不抓取 |
| `--config PATH` | 指定配置文件路径 |

## 按周期同步（计价信息表）

源站 zjj.xa.gov.cn 为每个月发布一份“造价信息表”，本参数可以指定区县×月份的组合精确抓取。

- 进度按 `区豍@YYYY-MM` 独立保存，多周期可交替同步
- 文档 `_id` 包含 `month`，同一材料不同月份的记录 _id 唯一，能保留各月价格历史
- 跳过 `update_date` 增量判断（周期已明确指定）
- 新增字段：`month`（YYYY-MM 字符串）、`gkbh`（源站周期 ID）、`published_at`（页脚时间别名）

示例：

```bash
# 抓阎良区 2026年1月 的造价信息表
./run.sh sync --period 2026-01 --counties 阎良区

# 抓两个区县某两月的数据
./run.sh sync --period 2026-01,2026-02 --counties 阎良区,周至县

# 抓 2025 整年 6 个区县的所有月份（80+ 任务）
./run.sh sync --periods-year 2025

# 抓 阎良区 所有有数据的年月（2024 至今）
./run.sh sync --periods-all --counties 阎良区

# 先看可用周期（不抓取）
./run.sh sync --list-periods --counties 阎良区 --periods-year 2025
```

**ES 查询示例：**

```bash
# 查某区县某月所有材料价格
curl -s "http://localhost:59200/ods_material_xian_price/_search" -H 'Content-Type: application/json' -d '{
  "query": {"bool": {"must": [
    {"term": {"county": "阎良区"}},
    {"term": {"month": "2026-01"}}
  ]}}
}'

# 查某材料各月价格走势
curl -s "http://localhost:59200/ods_material_xian_price/_search" -H 'Content-Type: application/json' -d '{
  "query": {"bool": {"must": [
    {"term": {"code": "010101303"}},
    {"term": {"county": "阎良区"}}
  ]}},
  "size": 24,
  "sort": [{"month": "asc"}],
  "_source": ["month", "price", "tax_price", "spec"]
}'
```

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

文档以 `MD5(breed+code+spec+county+month_or_update_date+price+tax_price)` 作为 `_id`：

- 带 `--period`：使用 `month`（YYYY-MM），同一材料不同月份的记录 _id 唯一
- 无 `--period`：使用 `update_date`（页脚 YYYY-MM-DD），兼容旧版

重复同步不会产生重复数据。价格变化时生成新文档，能保留价格历史。

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
| `month` | 所属月份 YYYY-MM（**仅 `--period` 模式写入**） |
| `gkbh` | 源站周期 ID（**仅 `--period` 模式写入**） |
| `published_at` | 与 update_date 同义（**仅 `--period` 模式写入**） |

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
    ├── sync_diff.py    # 差量同步（仅补缺失周期）
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