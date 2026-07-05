# 新疆 · 工程造价材料信息采集

> 数据源:`https://www.xjzj.com`
> 进度模式:`county` · 范围(16): 伊犁, 乌鲁木齐, 昌吉, 克拉玛依, 石河子, 塔城, 阿勒泰, 哈密, 巴州, 阿克苏, 喀什, 五家渠市, 博州, 克州, 和田地区, 吐鲁番
> ETL 索引:`ods_material_xinjiang_price` → `dwd_xinjiang_price` → `dws_xinjiang_price`

新疆工程造价材料信息采集,从 `https://www.xjzj.com` 抓取数据,按区县跟踪,同步至 Elasticsearch。覆盖 16 个区县。

## 功能特性

- **进度模式**:`county` — 按区县跟踪
- **覆盖范围**:16 个 区县/分类/期数
- **断点续传**:进度保存本地 + ES,中断自动恢复
- **增量检测**:基于 `update_date` / `period` 自动判断
- **幂等写入**:基于 MD5(_id),重复同步不重复入库
- **可降级**:支持 `--legacy` 走老流程(逃生通道)

## 快速开始

```bash
cd <skills>/xinjiang-price
./run.sh preview          # 预览(默认 1 页)
./run.sh sync             # 增量同步(自动断点续传)
./run.sh sync --force     # 强制全量
./run.sh status           # 查看同步状态
```

## 命令清单

| 命令 | 脚本 | 说明 |
|------|------|------|
| `sync` | commands/sync.py | 同步到 ES |
| `status` | commands/status.py | 查看状态 |
| `test` | commands/test.py | 测试连通性 |
| `check` | commands/check.py | 增量检测 |

## sync 关键参数

- `--year` — 目标年份
- `--areaid` — 只同步指定 areaid（0=全部）
- `--reset` — 重置进度
- `--dry-run` — 只下载 + 解析，不入库
- `--no-skip` — 不跳过已完成的条目

## 配置说明

`config.yml` 主要字段:

```yaml
es:
  host: http://localhost:59200        # Elasticsearch 地址
  index: ods_material_xinjiang_price      # ODS 索引
  progress_index: ods_material_xinjiang_price_sync_progress  # 同步进度索引

site:
  base_url: https://www.xjzj.com    # 源站地址
  counties/tabs:
  - 伊犁
  - 乌鲁木齐
  - 昌吉
  - 克拉玛依
  - 石河子
  - 塔城
  - 阿勒泰
  - 哈密
  - 巴州
  - 阿克苏
  - 喀什
  - 五家渠市
  - 博州
  - 克州
  - 和田地区
  - 吐鲁番

sync:
  year: 2026
  last_period: 
```

## 数据流

源站 → `commands/sync.py` → `ods_material_xinjiang_price` → ETL → `dwd_xinjiang_price` → `dws_xinjiang_price`

ETL 公共层:<skills>/gov-price-etl

## 常见问题

- **断点续传**:进度写入本地 `.sync_progress.json` + ES `ods_material_xinjiang_price_sync_progress`,中断后 `./run.sh sync` 自动续传。
- **幂等写入**:`_id` = MD5(breed + spec + unit + county + 月份 + 价格),重复同步不会产生重复数据。
- **增量检测**:基于 `sync.last_update_date` / `sync.last_period`,网站未更新则跳过抓取。

## 相关

- <skills>/gov-price-dashboard — 看板
- <skills>/gov-price-etl — ETL 公共层
- <skills>/gov-price-etl/SKILL.md — ETL 使用文档
