# 青岛 · 工程造价材料信息采集

> 数据源:`https://sjw.qingdao.gov.cn/cxjsj13/cxjs_95/cxjsj_zj5/`
> 进度模式:`period` · 范围(1): 青岛
> ETL 索引:`ods_material_qingdao_price` → `dwd_qingdao-price_price` → `dws_qingdao_price`

青岛工程造价材料信息采集,从 `https://sjw.qingdao.gov.cn/cxjsj13/cxjs_95/cxjsj_zj5/` 抓取数据,按期期刊跟踪,同步至 Elasticsearch。覆盖 1 个期数。

## 功能特性

- **进度模式**:`period` — 按期期刊跟踪
- **覆盖范围**:1 个 区县/分类/期数
- **断点续传**:进度保存本地 + ES,中断自动恢复
- **增量检测**:基于 `update_date` / `period` 自动判断
- **幂等写入**:基于 MD5(_id),重复同步不重复入库
- **可降级**:支持 `--legacy` 走老流程(逃生通道)

## 快速开始

```bash
cd <skills>/qingdao-price
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

- `--period` — 指定周期（兼容 v0.8 单周期过滤）
- `--year` — 只入库指定年份（默认走 config.yml 的 default_year，0=不限制）
- `--all` — 同步所有未入仓的期（v0.8 兼容）
- `--reset` — 重置本地进度，从头开始
- `--dry-run` — 预览，不写入 ES / MinIO
- `--latest` — 只同步最新一期
- `--run-id` — 指定 run_id
- `--max-units` — Collector 路径：只跑前 N 个工作单元（验证用）
- `--legacy` — v0.8 兼容：走旧 sync.py（仅在 Collector 异常时备用）

## 配置说明

`config.yml` 主要字段:

```yaml
es:
  host: http://localhost:59200        # Elasticsearch 地址
  index: ods_material_qingdao_price      # ODS 索引
  progress_index: ods_material_qingdao_price_sync_progress  # 同步进度索引

site:
  base_url: https://sjw.qingdao.gov.cn/cxjsj13/cxjs_95/cxjsj_zj5/    # 源站地址
  counties/tabs:
  - 青岛

sync:
  last_period: 
  last_publish_date: 
  default_year: 2026
```

## 数据流

源站 → `commands/sync.py` → `ods_material_qingdao_price` → ETL → `dwd_qingdao-price_price` → `dws_qingdao_price`

ETL 公共层:<skills>/gov-price-etl

## 常见问题

- **断点续传**:进度写入本地 `.sync_progress.json` + ES `ods_material_qingdao_price_sync_progress`,中断后 `./run.sh sync` 自动续传。
- **幂等写入**:`_id` = MD5(breed + spec + unit + county + 月份 + 价格),重复同步不会产生重复数据。
- **增量检测**:基于 `sync.last_update_date` / `sync.last_period`,网站未更新则跳过抓取。

## 相关

- <skills>/gov-price-dashboard — 看板
- <skills>/gov-price-etl — ETL 公共层
- <skills>/gov-price-etl/SKILL.md — ETL 使用文档
