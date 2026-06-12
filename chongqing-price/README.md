# 重庆工程造价材料信息采集

从 [重庆市建设工程造价信息网](http://www.cqsgczjxx.org) 抓取重庆市区县材料价格数据，通过 openclaw browser 自动化抓取页面，存储至本地 ES，支持断点续传和增量检测。

---

## 数据源

- **网址**：`http://www.cqsgczjxx.org/Pages/CQZJW/priceInformation.aspx`
- **数据分类**：材料信息价（页面"材料信息价"标签页）
- **页面结构**：月份下拉 + 区县选择 → 分页表格（材料名称 / 规格型号 / 单位 / 含税价格 / 不含税价格）
- **数据周期**：如 `2026年01月`

---

## 快速开始

### 前提条件

openclaw browser 必须已打开目标页面：

```bash
# 查看已打开的标签页
openclaw browser tabs

# 打开目标页面（如尚未打开）
openclaw browser open "http://www.cqsgczjxx.org/Pages/CQZJW/priceInformation.aspx"
```

获取目标 tab ID（如 `t1`），后续命令需要传入 `--tab-id`。

### 同步命令

```bash
cd ~/.openclaw/workspace/skills/chongqing-price

# 全量同步（指定周期和 tab）
python3 commands/sync.py --tab-id t1 --period "2026年01月"

# 重新开始（清除进度）
python3 commands/sync.py --tab-id t1 --reset

# 指定数据来源标签页
python3 commands/sync.py --tab-id t1 --source mortar
python3 commands/sync.py --tab-id t1 --source citywide
python3 commands/sync.py --tab-id t1 --source all

# 增量检测 + 自动触发同步（后台运行）
python3 commands/check.py
```

### 查看状态

```bash
# 查看同步进度
python3 commands/status.py

# 测试 ES 连接
python3 commands/test.py
```

### 初始化 ES 索引

```bash
python3 commands/write_es.py init
```

---

## 支持区县（36 个）

主城区、万州区、涪陵区、黔江区、长寿区、江津区、合川区、永川区、南川区、梁平区、城口县、丰都县、垫江县、忠县、开州区、云阳县、奉节县、巫山县、巫溪县、石柱县、秀山县、酉阳县、大足区、綦江区、万盛经开区、双桥经开区、铜梁区、璧山区、彭水县1、彭水县2、彭水县3、荣昌区1、荣昌区2、潼南区、武隆区

> 注：彭水县分 3 个价格区，荣昌区分 2 个价格区。

---

## ES 索引

| 索引 | 说明 |
|------|------|
| `ods_material_chongqing_price` | 材料价格数据 |
| `ods_chongqing_price_progress` | 同步进度记录 |

---

## 数据字段

| 字段 | 说明 |
|------|------|
| breed | 材料名称 |
| spec | 规格型号 |
| unit | 单位 |
| price | 不含税价格 |
| tax_price | 含税价格 |
| is_tax | 含税/不含税 |
| period | 周期（格式 `YYYY-MM-DD`，如 `2026-01-01`）|
| city / county | 区县名称 |
| update_date | 更新日期 |
| create_time | 入库时间 |

---

## 配置（config.yml）

```yaml
es:
  host: http://localhost:59200
  index: ods_material_chongqing_price
  progress_index: ods_chongqing_price_progress
  sync_log_index: ods_chongqing_price_sync_log

site:
  url: http://www.cqsgczjxx.org/Pages/CQZJW/priceInformation.aspx

sync:
  last_period: '2026'   # 上次同步周期（由 check.py 自动更新）
```

---

## 断点续传

- 进度文件：`.chongqing_sync_progress.json`
- 中断后运行 `sync.py` 自动从上次位置继续
- 传 `--reset` 重新全量同步

---

## 故障排查

```bash
# 确认浏览器状态
openclaw browser status
openclaw browser tabs

# ES 数据验证
curl -s "http://localhost:59200/ods_material_chongqing_price/_count"

# 按区县聚合
curl -s "http://localhost:59200/ods_material_chongqing_price/_search?size=0" \
  -H "Content-Type: application/json" \
  -d '{"aggs": {"by_county": {"terms": {"field": "city", "size": 50}}}}'

# 清空数据并重置
curl -s -XPOST "http://localhost:59200/ods_material_chongqing_price/_delete_by_query" \
  -H "Content-Type: application/json" -d '{"query":{"match_all":{}}}'
python3 commands/sync.py --tab-id t1 --reset

# 查看后台同步日志
tail -f /tmp/chongqing-incremental-sync-*.log
```

---

## 增量检测（check.py）

`check.py` 自动检测网站是否有新周期数据：

1. 检查 browser tab 是否存在并聚焦
2. 从页面提取当前选中周期
3. 对比 `config.yml` 的 `last_period`：
   - 不同 → 发现新周期，触发全量同步
   - 相同 → 检查 ES 最新已完成周期是否有更新
4. 后台启动 `sync.py`，日志写入 `/tmp/chongqing-incremental-sync-<timestamp>.log`