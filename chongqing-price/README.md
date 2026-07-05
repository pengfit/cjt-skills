# 重庆 · 工程造价材料信息采集

> 数据源:`http://www.cqsgczjxx.org/Pages/CQZJW/priceInformation.aspx`
> 进度模式:`county` · 范围:35 项
> ETL 索引:`ods_material_chongqing_price` → `dwd_chongqing_price` → `dws_chongqing_price`

重庆工程造价材料信息采集,从 `http://www.cqsgczjxx.org/Pages/CQZJW/priceInformation.aspx` 抓取数据,按区县跟踪,同步至 Elasticsearch。覆盖 35 个区县。

## 功能特性

- **进度模式**:`county` — 按区县跟踪
- **覆盖范围**:35 个 区县/分类/期数
- **断点续传**:进度保存本地 + ES,中断自动恢复
- **增量检测**:基于 `update_date` / `period` 自动判断
- **幂等写入**:基于 MD5(_id),重复同步不重复入库
- **可降级**:支持 `--legacy` 走老流程(逃生通道)

## 快速开始

```bash
cd <skills>/chongqing-price
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

- `--reset` — 重置进度，重新开始
- `--period` — 目标周期（兼容旧参数，等价 --periods 单值）
- `--periods` — 多周期，逗号分隔，如
- `--run-id` — 指定 run_id
- `--tab-id` — 浏览器标签页 ID（必填）
- `--source` — 数据来源: district / mortar / citywide / all
- `--legacy` — v3 兼容：走原 cmd_sync（旧生产路径）。**默认走 Collector**。仅在 Collector 异常时备用。
- `--max-units` — Collector 路径：只跑前 N 个工作单元（验证用），不传则跑全部

## 配置说明

`config.yml` 主要字段:

```yaml
es:
  host: http://localhost:59200        # Elasticsearch 地址
  index: ods_material_chongqing_price      # ODS 索引
  progress_index: material_chongqing_price_sync_progress  # 同步进度索引

site:
  base_url: http://www.cqsgczjxx.org/Pages/CQZJW/priceInformation.aspx    # 源站地址
  counties/tabs:
  - 主城区
  - 万州区
  - 涪陵区
  - 黔江区
  - 长寿区
  - 江津区
  - 合川区
  - 永川区
  - 南川区
  - 梁平区
  - 城口县
  - 丰都县
  - 垫江县
  - 忠县
  - 开州区
  - 云阳县
  - 奉节县
  - 巫山县
  - 巫溪县
  - 石柱县
  - 秀山县
  - 酉阳县
  - 大足区
  - 綦江区
  - 万盛经开区
  - 双桥经开区
  - 铜梁区
  - 璧山区
  - 彭水县1
  - 彭水县2
  - 彭水县3
  - 荣昌区1
  - 荣昌区2
  - 潼南区
  - 武隆区

sync:
  last_period: 2026
```

## 数据流

源站 → `commands/sync.py` → `ods_material_chongqing_price` → ETL → `dwd_chongqing_price` → `dws_chongqing_price`

ETL 公共层:<skills>/gov-price-etl

## 常见问题

- **断点续传**:进度写入本地 `.sync_progress.json` + ES `material_chongqing_price_sync_progress`,中断后 `./run.sh sync` 自动续传。
- **幂等写入**:`_id` = MD5(breed + spec + unit + county + 月份 + 价格),重复同步不会产生重复数据。
- **增量检测**:基于 `sync.last_update_date` / `sync.last_period`,网站未更新则跳过抓取。

## 相关

- <skills>/gov-price-dashboard — 看板
- <skills>/gov-price-etl — ETL 公共层
- <skills>/gov-price-etl/SKILL.md — ETL 使用文档
