# 江西 · 工程造价材料信息采集

> 数据源:`https://zjt.jiangxi.gov.cn/jxszfhcxjst/gqcyc/pc/list.html`
> 进度模式:`period` · 范围(11): 南昌市, 九江市, 上饶市, 抚州市, 宜春市, 吉安市, 赣州市, 景德镇市, 萍乡市, 新余市, 鹰潭市
> ETL 索引:`ods_material_jiangxi_price` → `dwd_jiangxi_price` → `dws_jiangxi_price`

江西工程造价材料信息采集,从 `https://zjt.jiangxi.gov.cn/jxszfhcxjst/gqcyc/pc/list.html` 抓取数据,按期期刊跟踪,同步至 Elasticsearch。覆盖 11 个期数。

## 功能特性

- **进度模式**:`period` — 按期期刊跟踪
- **覆盖范围**:11 个 区县/分类/期数
- **断点续传**:进度保存本地 + ES,中断自动恢复
- **增量检测**:基于 `update_date` / `period` 自动判断
- **幂等写入**:基于 MD5(_id),重复同步不重复入库
- **可降级**:支持 `--legacy` 走老流程(逃生通道)

## 快速开始

```bash
cd <skills>/jiangxi-price
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
| `check` | `commands/check.py` | 增量检测（不写入） |
| `test` | `commands/test.py` | 测试连通性 |

## sync 关键参数

- `--period` — 指定周期（兼容旧参数；Collector 走 --year）
- `--year` — 只入库指定年份（默认 2026）
- `--exclude-period` — 排除指定周期（仅 legacy 路径生效）
- `--all` — 同步所有未入仓的期（仅 legacy 路径生效）
- `--reset` — 重置本地进度，重新开始
- `--dry-run` — 预览，不写入（仅 legacy 路径生效）
- `--latest` — 只同步最新一期（仅 legacy 路径生效）
- `--legacy` — v0.8 兼容：走原 cmd_legacy_sync（旧主流程）。**默认走 Collector**。仅在 Collector 异常时备用。
- `--max-units` — Collector 路径：只跑前 N 个工作单元（验证用），不传则跑全部
- `--run-id` — 指定 run_id（默认自动生成 v09_YYYYMMDD_HHMMSS）

## 配置说明

`config.yml` 主要字段:

```yaml
es:
  host: http://localhost:59200        # Elasticsearch 地址
  index: ods_material_jiangxi_price      # ODS 索引
  progress_index: ods_material_jiangxi_price_sync_progress  # 同步进度索引

site:
  base_url: https://zjt.jiangxi.gov.cn/jxszfhcxjst/gqcyc/pc/list.html    # 源站地址
  counties/tabs:
  - 南昌市
  - 九江市
  - 上饶市
  - 抚州市
  - 宜春市
  - 吉安市
  - 赣州市
  - 景德镇市
  - 萍乡市
  - 新余市
  - 鹰潭市

sync:
  last_period: 
  last_publish_date: 
```

## 数据流

源站 → `commands/sync.py` → `ods_material_jiangxi_price` → ETL → `dwd_jiangxi_price` → `dws_jiangxi_price`

ETL 公共层:<skills>/gov-price-etl

## 常见问题

- **断点续传**:进度写入本地 `.sync_progress.json` + ES `ods_material_jiangxi_price_sync_progress`,中断后 `./run.sh sync` 自动续传。
- **幂等写入**:`_id` = MD5(breed + spec + unit + county + 月份 + 价格),重复同步不会产生重复数据。
- **增量检测**:基于 `sync.last_update_date` / `sync.last_period`,网站未更新则跳过抓取。

## 相关

- <skills>/gov-price-dashboard — 看板
- <skills>/gov-price-etl — ETL 公共层
- <skills>/gov-price-etl/SKILL.md — ETL 使用文档
