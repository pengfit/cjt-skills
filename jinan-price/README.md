# 济南 · 工程造价材料信息采集

> 数据源:`http://jnxxj.jngczjxh.com:5020/cj/api/build`
> 进度模式:`catalogue` · 范围(1): 济南市
> ETL 索引:`ods_material_jinan_price` → `dwd_jinan_price` → `dws_jinan_price`

济南工程造价材料信息采集,从 `http://jnxxj.jngczjxh.com:5020/cj/api/build` 抓取数据,按分类目录跟踪,同步至 Elasticsearch。覆盖 1 个分类。

## 功能特性

- **进度模式**:`catalogue` — 按分类目录跟踪
- **覆盖范围**:1 个 区县/分类/期数
- **断点续传**:进度保存本地 + ES,中断自动恢复
- **增量检测**:基于 `update_date` / `period` 自动判断
- **幂等写入**:基于 MD5(_id),重复同步不重复入库
- **可降级**:支持 `--legacy` 走老流程(逃生通道)

## 快速开始

```bash
cd <skills>/jinan-price
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

- `--reset` — 重置本地进度，重新开始
- `--legacy` — v0 兼容：走原 sync 主流程（不推荐）
- `--periods` — 多周期，逗号分隔（精确匹配 periodName），如
- `--year` — 按年份过滤（0=用 config.sync.year）
- `--run-id` — 自定义 run_id
- `--dry-run` — 预览模式，不写入 ES
- `--max-units` — 只跑前 N 个工作单元（验证用）

## 配置说明

`config.yml` 主要字段:

```yaml
es:
  host: http://localhost:59200        # Elasticsearch 地址
  index: ods_material_jinan_price      # ODS 索引
  progress_index: material_jinan_price_sync_progress  # 同步进度索引

site:
  base_url: http://jnxxj.jngczjxh.com:5020/cj/api/build    # 源站地址
  counties/tabs:
  - 济南市

sync:
  last_period: 2026年05月材料价格信息
  last_period_id: 811589252355269
  last_run_at: 2026-07-03 15:42:31
  last_run_id: jn_run_20260703_153817
  size_per_page: 100
  year: 2026
```

## 数据流

源站 → `commands/sync.py` → `ods_material_jinan_price` → ETL → `dwd_jinan_price` → `dws_jinan_price`

ETL 公共层:<skills>/gov-price-etl

## 常见问题

- **断点续传**:进度写入本地 `.sync_progress.json` + ES `material_jinan_price_sync_progress`,中断后 `./run.sh sync` 自动续传。
- **幂等写入**:`_id` = MD5(breed + spec + unit + county + 月份 + 价格),重复同步不会产生重复数据。
- **增量检测**:基于 `sync.last_update_date` / `sync.last_period`,网站未更新则跳过抓取。

## 相关

- <skills>/gov-price-dashboard — 看板
- <skills>/gov-price-etl — ETL 公共层
- <skills>/gov-price-etl/SKILL.md — ETL 使用文档
