---
name: jilin-price
description: "吉林工程造价材料信息采集,从 `http://www.jlszjw.com/city/price_list.php?city=140` 抓取数据,按月份跟踪,同步至 Elasticsearch。仅抓 2026 年数据。"
---

# 吉林 · 工程造价材料信息采集

> 省份:吉林 · 进度模式:`period` · 范围:吉林市（永吉/蛟河/桦甸/舒兰/磐石 5 县暂无源数据）

## 数据流

```
源站: http://www.jlszjw.com/city/price_list.php?city=140
   ↓ (commands/jilin_collector.py, JilinCollector v0.1, 2026-07-07)
ods_material_jilin_price
   ↓ (<skills>/gov-price-etl cli/etl.py --city jilin)
dwd_jilin_price
   ↓ (cli/sync_dws.py --city jilin --mode quick)
dws_jilin_price
```

## 快速开始

```bash
cd <skills>/jilin-price
./run.sh preview          # 预览数据(不写 ES)
./run.sh sync             # 同步(默认 year=2026, 到当前月)
./run.sh sync --reset     # 强制全量重跑
./run.sh sync --max-month 7   # 只跑到 7 月
./run.sh status           # 查看同步状态
./run.sh check            # 增量检测(不写入)
./run.sh test             # 测试 ES / 源站连通性
```

## 命令清单

| 命令 | 脚本 | 说明 |
|------|------|------|
| `preview` | `commands/preview.py` | 预览数据 |
| `sync` | `commands/sync.py` | 同步到 ES |
| `status` | `commands/status.py` | 查看状态 |
| `test` | `commands/test.py` | 测试连通性 |
| `check` | `commands/check.py` | 增量检测（不写入） |

## sync 关键参数

- `--year` — 抓取年份（默认 2026）
- `--max-month` — 最大月份（0=当前月），如 7 表示只跑到 7 月
- `--diqu` — 地区筛选（默认空 = 吉林市整体）
- `--reset` — 重置本地进度，重新开始
- `--max-units` — 最多处理几个工作单元（验证用）
- `--run-id` — 指定 run_id（默认自动生成 `jl_run_YYYYMMDD_HHMMSS`）

## ES 索引

| 索引 | 说明 |
|------|------|
| `ods_material_jilin_price` | 原始抓取数据（主数据） |
| `ods_material_jilin_price_sync_progress` | 同步进度（按 period 分桶） |
| `dwd_jilin_price` | ETL 清洗层 |
| `dws_jilin_price` | 看板查询层 |

## 配置（config.yml）

```yaml
es:
  host: http://localhost:59200
  index: ods_material_jilin_price
  progress_index: ods_material_jilin_price_sync_progress
site:
  base_url: http://www.jlszjw.com/city/price_list.php
  # PHP 页面查询字符串按 GBK 解析，所以 URL 中文参数必须用 GBK 编码。
  # 不要用 UTF-8 编码的查询参数（"2026年1月份" → 2026%E5%B9%B41...），会查不到数据。
  city_id: 140
  city_name: 吉林市
  counties:
    - 吉林市       # 默认（diqu 空值 = 吉林市整体）
    - 永吉县
    - 蛟河市
    - 桦甸市
    - 舒兰市
    - 磐石市       # 后 5 个县实测无源数据
sync:
  year: 2026           # 只抓 2026 年数据（道友要求）
  page_size: 20        # 源站每页 20 条
  strip_breed_prefix: true   # 名称清洗：去前缀括号
  max_retries: 3
  request_timeout: 30
```

## 源站特性（踩坑笔记）

1. **URL 中文参数按 GBK 编码**（不是 UTF-8）。`utils.gbk_urlencode()` 专门处理。
2. **price_time 是精确匹配**（不是 ≥ 关系）。`2026年1月份` 只返回 2026-01 月份数据。
3. **county 字段有两种写法**：`吉林市` 和 `吉林市-吉林市`。已通过 `utils.normalize_county()` 统一为 `吉林市`。
4. **breed_raw 偶尔只是标题行**：`（2024年补充）`。清洗后会 fallback 从 spec 推导。
5. **需要 session cookie + Referer**：第一次 GET 首页拿 cookie，后续带 referer 才能正常翻页。

## 名称清洗规则

源站 breed_raw 示例：
- `（2025年补充）干混抹灰砂浆` → breed=`干混抹灰砂浆` ✓
- `（2025年补充）PE20` → breed=`PE20` ✓
- `（2024年补充）` → breed=`(spec 前 30 字)`（标题行 fallback）
- `调音台` → breed=`调音台` ✓（无前缀直接保留）

实现：`utils.strip_breed_prefix()` 正则匹配 `^[\(（\[【][^)\]】]+[\)）\]【]` 多次去前缀。

## 项目结构

```
jilin-price/
├── run.sh
├── SKILL.md
├── config.yml
├── skill.yml
└── commands/
    ├── check.py
    ├── jilin_collector.py    # SyncRunner 化主流程（v0.1）
    ├── preview.py
    ├── status.py
    ├── sync.py
    ├── test.py
    └── utils.py              # GBK 编码 / HTML 解析 / 名称清洗
```

## 同步策略

- **1 个 unit = 1 个月**：`(period, diqu)` 元组
- 默认 `diqu=""`（吉林市整体）抓 7 个月 = 7 个 unit
- 每月翻页到末页（`< page_size` 终止）
- 客户端防串：清洗后再校验 period 字段匹配

## 依赖

- Python 3
- requests / beautifulsoup4 / pyyaml
- gov-price-etl（共用 SyncRunner 基类 + ensure_progress_index）

## 相关

- `<skills>/gov-price-dashboard` — 看板（查 DWS 数据）
- `<skills>/gov-price-etl` — ETL 公共层
- `<skills>/chongqing-price` — 参考模板（浏览器自动化模式）
- `<skills>/jiangxi-price` — 参考模板（SyncRunner 化 + PDF 解析）

## 后续工作

1. ETL ODS→DWD：用 `cli/etl.py --city jilin` 跑清洗层（当前直接 ODS 同步到 DWS via quick 模式可行）
2. ETL 阶段处理长 breed_raw（breed + spec 混在一起）→ ETL 时用 AI 拆 breed / spec
3. 其他区县：源站暂无数据，等源站更新后会自动入仓（diqu 参数已支持）