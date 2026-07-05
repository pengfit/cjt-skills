# 西安 · 工程造价材料信息采集

> 数据源:`https://zjj.xa.gov.cn/zxcx/gczj/index.aspx`
> 进度模式:`county` · 范围(6): 阎良区, 临潼区, 高陵区, 鄠邑区, 蓝田县, 周至县
> ETL 索引:`ods_material_xian_price` → `dwd_xian_price` → `dws_xian_price`

西安工程造价材料信息采集,从 `https://zjj.xa.gov.cn/zxcx/gczj/index.aspx` 抓取数据,按区县跟踪,同步至 Elasticsearch。覆盖 6 个区县。

## 功能特性

- **进度模式**:`county` — 按区县跟踪
- **覆盖范围**:6 个 区县/分类/期数
- **断点续传**:进度保存本地 + ES,中断自动恢复
- **增量检测**:基于 `update_date` / `period` 自动判断
- **幂等写入**:基于 MD5(_id),重复同步不重复入库
- **可降级**:支持 `--legacy` 走老流程(逃生通道)

## 快速开始

```bash
cd <skills>/xian-price
./run.sh preview          # 预览(默认 1 页)
./run.sh sync             # 增量同步(自动断点续传)
./run.sh sync --force     # 强制全量
./run.sh status           # 查看同步状态
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

- `--force` — _无说明_
- `--max-pages` — _无说明_
- `--counties` — _无说明_
- `--resume-from` — _无说明_
- `--reset` — _无说明_
- `--no-log` — _无说明_
- `--no-spot-check` — _无说明_
- `--period` — 指定周期，逗号分隔，如 2026-01,2026-02
- `--periods-year` — 指定整年的所有月份，如 2026
- `--periods-all` — 抓取所有有数据的年月（源站 2024 至今）
- `--list-periods` — 只列出可用周期，不抓取
- `--dry-run` — 预览模式（不写入 ES）
- `--periods` — 多周期，逗号分隔，如
- `--list-year` — --list-periods 时限定年份
- `--max-units` — 只跑前 N 个 unit（验证用）
- `--run-id` — 指定 run_id（默认自动生成）
- `--legacy` — v0.6 兼容：走原 main 流程。默认走 Collector。
- `--no-progress` — 不写 ES progress 索引

## 配置说明

`config.yml` 主要字段:

```yaml
es:
  host: http://localhost:59200        # Elasticsearch 地址
  index: ods_material_xian_price      # ODS 索引
  progress_index: ods_material_xian_price_sync_progress  # 同步进度索引

site:
  base_url: https://zjj.xa.gov.cn/zxcx/gczj/index.aspx    # 源站地址
  counties/tabs:
  - 阎良区
  - 临潼区
  - 高陵区
  - 鄠邑区
  - 蓝田县
  - 周至县

sync:
  last_update_date: 2026-06-24
```

## 数据流

源站 → `commands/sync.py` → `ods_material_xian_price` → ETL → `dwd_xian_price` → `dws_xian_price`

ETL 公共层:<skills>/gov-price-etl

## 常见问题

- **断点续传**:进度写入本地 `.sync_progress.json` + ES `ods_material_xian_price_sync_progress`,中断后 `./run.sh sync` 自动续传。
- **幂等写入**:`_id` = MD5(breed + spec + unit + county + 月份 + 价格),重复同步不会产生重复数据。
- **增量检测**:基于 `sync.last_update_date` / `sync.last_period`,网站未更新则跳过抓取。

## 相关

- <skills>/gov-price-dashboard — 看板
- <skills>/gov-price-etl — ETL 公共层
- <skills>/gov-price-etl/SKILL.md — ETL 使用文档
