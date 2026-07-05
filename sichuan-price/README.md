# 四川 · 工程造价材料信息采集

> 数据源:`http://202.61.90.35:8032/pubpages/pricelist.aspx`
> 进度模式:`catalogue` · 范围:21 项
> ETL 索引:`ods_material_sichuan_price` → `dwd_sichuan_price` → `dws_sichuan_price`

四川工程造价材料信息采集,从 `http://202.61.90.35:8032/pubpages/pricelist.aspx` 抓取数据,按分类目录跟踪,同步至 Elasticsearch。覆盖 21 个分类。

## 功能特性

- **进度模式**:`catalogue` — 按分类目录跟踪
- **覆盖范围**:21 个 区县/分类/期数
- **断点续传**:进度保存本地 + ES,中断自动恢复
- **增量检测**:基于 `update_date` / `period` 自动判断
- **幂等写入**:基于 MD5(_id),重复同步不重复入库
- **可降级**:支持 `--legacy` 走老流程(逃生通道)

## 快速开始

```bash
cd <skills>/sichuan-price
./run.sh preview          # 预览(默认 1 页)
./run.sh sync             # 增量同步(自动断点续传)
./run.sh sync --force     # 强制全量
./run.sh status           # 查看同步状态
```

## 命令清单

| 命令 | 脚本 | 说明 |
|------|------|------|
| `preview` | `commands/preview.py` | 预览数据（不写入 ES） |
| `preview` | `commands/preview.py` | --pages N    预览前 N 页 |
| `sync` | `commands/sync.py` | 同步到 ES（有增量检测） |
| `sync` | `commands/sync.py` | --dry-run       预览同步（不写入） |
| `sync` | `commands/sync.py` | --force         强制全量同步（跳过增量检测） |
| `sync` | `commands/sync.py` | --reset         重置进度，重新开始 |
| `sync` | `commands/sync.py` | --period \"2026年03月\"  指定周期 |
| `status` | `commands/status.py` | 查看同步状态 |
| `test` | `commands/test.py` | 测试 ES 连接 |
| `check` | `commands/check.py` | 检查源站是否有新数据 |
| `增量逻辑：按时间周期判断。同步完成后自动更新` | `commands/增量逻辑：按时间周期判断。同步完成后自动更新.py` | last_period。 |
| `定时任务建议：crontab` | `commands/定时任务建议：crontab.py` | 设置 ./run.sh check，有更新时自动 sync |
| `支持翻页：ASP.NET` | `commands/支持翻页：ASP.NET.py` | POST 翻页，rptPager_input |

## sync 关键参数

- `--reset` — 重置进度，重新开始
- `--dry-run` — 预览模式，不写入 ES
- `--force` — 强制全量同步
- `--period` — 指定周期（如 2026年03月），默认自动获取最新）
- `--periods` — 批量周期（逗号分隔，如
- `--year` — 按年份批量抓取（如 2026 → 该年所有 State=1 周期）
- `--max-pages` — 最大页数
- `--no-check` — 跳过增量检测，直接同步

## 配置说明

`config.yml` 主要字段:

```yaml
es:
  host: http://localhost:59200        # Elasticsearch 地址
  index: ods_material_sichuan_price      # ODS 索引
  progress_index: ods_material_sichuan_price_sync_progress  # 同步进度索引

site:
  base_url: http://202.61.90.35:8032/pubpages/pricelist.aspx    # 源站地址
  counties/tabs:
  - 成都市
  - 绵阳市
  - 自贡市
  - 攀枝花市
  - 泸州市
  - 德阳市
  - 广元市
  - 遂宁市
  - 内江市
  - 乐山市
  - 资阳市
  - 宜宾市
  - 南充市
  - 达州市
  - 雅安市
  - 阿坝州
  - 甘孜州
  - 凉山州
  - 广安市
  - 巴中市
  - 眉山市

sync:
  last_period: 2026年05月
```

## 数据流

源站 → `commands/sync.py` → `ods_material_sichuan_price` → ETL → `dwd_sichuan_price` → `dws_sichuan_price`

ETL 公共层:<skills>/gov-price-etl

## 常见问题

- **断点续传**:进度写入本地 `.sync_progress.json` + ES `ods_material_sichuan_price_sync_progress`,中断后 `./run.sh sync` 自动续传。
- **幂等写入**:`_id` = MD5(breed + spec + unit + county + 月份 + 价格),重复同步不会产生重复数据。
- **增量检测**:基于 `sync.last_update_date` / `sync.last_period`,网站未更新则跳过抓取。

## 相关

- <skills>/gov-price-dashboard — 看板
- <skills>/gov-price-etl — ETL 公共层
- <skills>/gov-price-etl/SKILL.md — ETL 使用文档
