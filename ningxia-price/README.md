# 宁夏 · 工程造价材料信息采集

> 数据源:`https://jst.nx.gov.cn/ztzl/gczj/zjtt/index.html`
> 进度模式:`period` · 范围(5): 银川市, 石嘴山市, 吴忠市, 固原市, 中卫市
> ETL 索引:`ods_material_ningxia_price` → `dwd_ningxia_price` → `dws_ningxia_price`

宁夏工程造价材料信息采集,从 `https://jst.nx.gov.cn/ztzl/gczj/zjtt/index.html` 抓取数据,按期期刊跟踪,同步至 Elasticsearch。覆盖 5 个期数。

## 功能特性

- **进度模式**:`period` — 按期期刊跟踪
- **覆盖范围**:5 个 区县/分类/期数
- **断点续传**:进度保存本地 + ES,中断自动恢复
- **增量检测**:基于 `update_date` / `period` 自动判断
- **幂等写入**:基于 MD5(_id),重复同步不重复入库
- **可降级**:支持 `--legacy` 走老流程(逃生通道)

## 快速开始

```bash
cd <skills>/ningxia-price
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

- `--year` — 同步年份（默认 2026）
- `--period` — 限定周期（标题含此串），如
- `--exclude-period` — 排除周期
- `--all` — 同步所有未入仓的期（不限于指定年份）
- `--reset` — 重置本地进度
- `--dry-run` — 只解析不入库
- `--latest` — 只同步最新一期
- `--max-units` — 最多处理多少期（测试用，0=全部）
- `--legacy` — 走 v3 旧路径（逃生通道）
- `--run-id` — 本次运行标识（默认自动生成）

## 配置说明

`config.yml` 主要字段:

```yaml
es:
  host: http://localhost:59200        # Elasticsearch 地址
  index: ods_material_ningxia_price      # ODS 索引
  progress_index: ods_material_ningxia_price_sync_progress  # 同步进度索引

site:
  base_url: https://jst.nx.gov.cn/ztzl/gczj/zjtt/index.html    # 源站地址
  counties/tabs:
  - 银川市
  - 石嘴山市
  - 吴忠市
  - 固原市
  - 中卫市

sync:
  last_period: 
  last_publish_date: 
```

## 数据流

源站 → `commands/sync.py` → `ods_material_ningxia_price` → ETL → `dwd_ningxia_price` → `dws_ningxia_price`

ETL 公共层:<skills>/gov-price-etl

## 常见问题

- **断点续传**:进度写入本地 `.sync_progress.json` + ES `ods_material_ningxia_price_sync_progress`,中断后 `./run.sh sync` 自动续传。
- **幂等写入**:`_id` = MD5(breed + spec + unit + county + 月份 + 价格),重复同步不会产生重复数据。
- **增量检测**:基于 `sync.last_update_date` / `sync.last_period`,网站未更新则跳过抓取。

## 相关

- <skills>/gov-price-dashboard — 看板
- <skills>/gov-price-etl — ETL 公共层
- <skills>/gov-price-etl/SKILL.md — ETL 使用文档
