# 陕西 · 工程造价材料信息采集

> 数据源:`https://js.shaanxi.gov.cn/sy/yw/zjglfw/zjxx/index.html`
> 进度模式:`period` · 范围(11): 陕西, 安康, 汉中, 咸阳, 铜川, 渭南, 延安, 榆林, 商洛, 宝鸡, 西安
> ETL 索引:`ods_material_shaanxi_price` → `dwd_shaanxi_price` → `dws_shaanxi_price`

陕西工程造价材料信息采集,从 `https://js.shaanxi.gov.cn/sy/yw/zjglfw/zjxx/index.html` 抓取数据,按期期刊跟踪,同步至 Elasticsearch。覆盖 11 个期数。

## 功能特性

- **进度模式**:`period` — 按期期刊跟踪
- **覆盖范围**:11 个 区县/分类/期数
- **断点续传**:进度保存本地 + ES,中断自动恢复
- **增量检测**:基于 `update_date` / `period` 自动判断
- **幂等写入**:基于 MD5(_id),重复同步不重复入库
- **可降级**:支持 `--legacy` 走老流程(逃生通道)

## 快速开始

```bash
cd <skills>/shaanxi-price
./run.sh preview          # 预览(默认 1 页)
./run.sh sync             # 增量同步(自动断点续传)
./run.sh sync --force     # 强制全量
./run.sh status           # 查看同步状态
```

## 命令清单

| 命令 | 脚本 | 说明 |
|------|------|------|
| `preview` | `commands/preview.py` | 预览数据（不写 ES、不传 MinIO） |
| `sync` | `commands/sync.py` | 同步到 ES + MinIO |
| `status` | `commands/status.py` | 查看同步状态 |
| `test` | `commands/test.py` | 测试连通性（ES + MinIO + 源站） |
| `check` | `commands/check.py` | 增量检测（不写入） |
| `sync` | `commands/sync.py` | 选项: |
| `--period` | `commands/--period.py` | 2026.5月        指定 period（如 '2026.5月'、'2026.5期'） |
| `--year` | `commands/--year.py` | 2026             只入指定年份（默认配置中的 target_year=2026） |
| `--latest` | `commands/--latest.py` | 只同步最新一期 |
| `--reset` | `commands/--reset.py` | 重置本地进度 |
| `--all` | `commands/--all.py` | 同步所有未入仓的期 |
| `--dry-run` | `commands/--dry-run.py` | 预览，不写入 |

## sync 关键参数

- `--period` — 指定 period（如
- `--year` — 只入库指定年份（默认 cfg.sync.target_year=2026）
- `--all` — 同步所有未入仓的期（v0.5 兼容）
- `--reset` — 重置本地进度，从头开始
- `--dry-run` — 预览，不写入 ES / MinIO
- `--latest` — 只同步最新一期
- `--limit` — 最多同步 N 期（0=全部，兼容 v0.5）
- `--run-id` — 指定 run_id（默认 sn_run_YYYYMMDD_HHMMSS）
- `--max-units` — Collector 路径：只跑前 N 个工作单元（验证用）
- `--legacy` — v0.5 兼容：走 sync_legacy.py（旧生产路径）。**默认走 Collector**。

## 配置说明

`config.yml` 主要字段:

```yaml
es:
  host: http://localhost:59200        # Elasticsearch 地址
  index: ods_material_shaanxi_price      # ODS 索引
  progress_index: ods_material_shaanxi_price_sync_progress  # 同步进度索引

site:
  base_url: https://js.shaanxi.gov.cn/sy/yw/zjglfw/zjxx/index.html    # 源站地址
  counties/tabs:
  - 陕西
  - 安康
  - 汉中
  - 咸阳
  - 铜川
  - 渭南
  - 延安
  - 榆林
  - 商洛
  - 宝鸡
  - 西安

sync:
  target_year: 2026
  last_period: 
  last_publish_date: 
```

## 数据流

源站 → `commands/sync.py` → `ods_material_shaanxi_price` → ETL → `dwd_shaanxi_price` → `dws_shaanxi_price`

ETL 公共层:<skills>/gov-price-etl

## 常见问题

- **断点续传**:进度写入本地 `.sync_progress.json` + ES `ods_material_shaanxi_price_sync_progress`,中断后 `./run.sh sync` 自动续传。
- **幂等写入**:`_id` = MD5(breed + spec + unit + county + 月份 + 价格),重复同步不会产生重复数据。
- **增量检测**:基于 `sync.last_update_date` / `sync.last_period`,网站未更新则跳过抓取。

## 相关

- <skills>/gov-price-dashboard — 看板
- <skills>/gov-price-etl — ETL 公共层
- <skills>/gov-price-etl/SKILL.md — ETL 使用文档
