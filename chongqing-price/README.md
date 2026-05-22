# 重庆工程造价材料信息采集

从 http://www.cqsgczjxx.org 抓取重庆市区县材料价格数据，按月周期增量同步至本地 ES。

---

## 快速开始

```bash
cd ~/.openclaw/workspace/skills/chongqing-price

# 前提：确保 openclaw browser 已打开目标页面
python3 commands/sync.py --tab-id <tab-id>

# 重置进度，重新开始
python3 commands/sync.py --tab-id <tab-id> --reset

# 查看同步状态
python3 commands/status.py

# 测试 ES 连接
python3 commands/test.py
```

> **前提条件**：openclaw browser 必须已打开并处于目标页面。
> ```bash
> openclaw browser tabs   # 查看已打开的标签页
> openclaw browser open "http://www.cqsgczjxx.org/Pages/CQZJW/priceInformation.aspx"
> ```

---

## 支持区县（35个）

主城区、万州区、涪陵区、黔江区、长寿区、江津区、合川区、永川区、南川区、梁平区、城口县、丰都县、垫江县、忠县、开州区、云阳县、奉节县、巫山县、巫溪县、石柱县、秀山县、酉阳县、大足区、綦江区、万盛经开区、双桥经开区、铜梁区、璧山区、彭水县1、彭水县2、彭水县3、荣昌区1、荣昌区2、潼南区、武隆区

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
| period | 周期名称（如 2026年01月）|
| city | 城市/区县 |
| county | 同 city |
| update_date | 更新日期 |
| create_time | 入库时间 |

---

## 断点续传

进度保存在 `.chongqing_sync_progress.json`，中断后运行 sync 自动从上次位置继续。

---

## 故障排查

```bash
# 确认浏览器已打开
openclaw browser status
openclaw browser tabs

# ES 数据验证
curl -s "http://localhost:59200/ods_material_chongqing_price/_count"
curl -s "http://localhost:59200/ods_material_chongqing_price/_search?size=0" \
  -H "Content-Type: application/json" \
  -d '{"aggs": {"by_county": {"terms": {"field": "city", "size": 50}}}}'

# 清理并重新同步
curl -s -XPOST "http://localhost:59200/ods_material_chongqing_price/_delete_by_query" \
  -H "Content-Type: application/json" -d '{"query":{"match_all":{}}}'
python3 commands/sync.py --tab-id <tab-id> --reset
```

---

## Dashboard

```bash
cd ~/.openclaw/workspace/gov-price-dashboard
./start.sh start
# 访问 http://localhost:5300
```
