# jinan-price

济南市工程造价材料信息采集工具。从 `http://jnxxj.jngczjxh.com:5020` 抓取材料价格数据，写入本地 Elasticsearch。

---

## 功能特性

- **多分类目录**：41 个材料分类（黑色金属、橡胶塑料、五金制品、电缆等）
- **多周期管理**：支持多个历史周期，自动跟踪最新周期
- **断点续传**：进度保存在本地 JSON，中断后自动从断点恢复
- **增量检测**：自动对比网站与 ES 记录数，有新增则触发同步
- **去重写入**：基于 MD5(doc key) 的幂等写入，重复数据自动覆盖
- **写入 ES**：目标 `http://localhost:59200`，支持全量检索

---

## 快速开始

```bash
cd ~/.openclaw/workspace/skills/jinan-price

# 增量同步（首次全量，后续自动检测增量）
./run.sh sync

# 强制全量同步（忽略增量检测）
./run.sh sync --force

# 预览模式（不写入 ES）
./run.sh sync --dry-run

# 重置进度，从头开始
./run.sh sync --reset

# 指定周期 ID 同步
./run.sh sync --period-id 800251371103429
```

---

## 命令参考

| 命令 | 说明 |
|------|------|
| `./run.sh sync` | 增量同步（后台运行） |
| `./run.sh sync --force` | 强制全量同步（忽略增量检测） |
| `./run.sh sync --dry-run` | 预览模式，不写入 ES |
| `./run.sh sync --reset` | 重置进度，重新开始 |
| `./run.sh sync --period-id ID` | 指定周期 ID 同步 |
| `./run.sh sync --size N` | 每页大小（默认 100） |
| `./run.sh preview` | 预览数据（前 10 个分类各 2 页） |
| `./run.sh preview --pages 3` | 预览前 3 页 |
| `./run.sh preview --period-id ID` | 预览指定周期 |
| `./run.sh status` | 查看同步进度（ES 计数、本地进度） |
| `./run.sh test` | 测试 ES 和网站连接 |
| `python3 commands/check.py` | 手动增量检测，输出有变化的分类 |

---

## 数据源

**网站**: `http://jnxxj.jngczjxh.com:5020`

**认证**: 使用 Playwright (Chromium) 无头浏览器访问网站，从 `localStorage` 读取 `token`，后续请求附带到请求头。

**API 格式**: `POST /cj/api/build/material/searchPublishPriceMaterialPage`

```json
{
  "periodId": "800251371103429",
  "catalogueId": "...",
  "current": 1,
  "size": 100,
  "dataType": "2",
  "isPreview": true
}
```

响应示例：
```json
{
  "code": 0,
  "successFul": true,
  "data": {
    "total": 150,
    "records": [
      {
        "productName": "圆钢",
        "features": "HPB300 Φ6",
        "unit": "吨",
        "infoPrice": 3850.00,
        "code": "010101001",
        "publishTime": "2026-04-20 10:00:00"
      }
    ]
  }
}
```

---

## 配置

配置文件：`config.yml`

```yaml
es:
  host: http://localhost:59200
  index: ods_material_jinan_price
  catalogue_index: material_jinan_price_catalogue
  progress_index: ods_material_jinan_price_sync_progress
  sync_log_index: ods_material_jinan_price_sync_log

site:
  base_url: http://jnxxj.jngczjxh.com:5020
  api_base: /cj/api/build
  data_type: '2'

sync:
  last_period: 2026年04月材料价格信息
  last_period_id: '800251371103429'
  size_per_page: 100
```

`sync.last_period` 和 `sync.last_period_id` 由同步程序自动更新。

---

## ES 索引与字段

**主索引**：`ods_material_jinan_price`

| 字段 | 说明 |
|------|------|
| `breed` | 材料名称 |
| `spec` | 规格型号 |
| `unit` | 单位 |
| `price` / `tax_price` | 含税价格 |
| `is_tax` | 含税标识 |
| `period` / `period_id` | 周期名称 / ID |
| `province` | 山东 |
| `city` / `county` | 济南 |
| `catalogue` / `catalogue_name` | 分类 ID / 名称 |
| `code` | 材料编码 |
| `update_date` | 更新日期 |
| `publish_time` | 发布时间 |

**分类目录索引**：`material_jinan_price_catalogue`（含 1 个根节点 + 41 个分类）

**进度索引**：`ods_material_jinan_price_sync_progress`（记录运行状态、分类、页码、百分比、耗时）

---

## 增量机制

增量检测由 `commands/check.py` 触发：

1. **周期维度**：获取网站最新 `periodId`，与 `config.yml` 中 `last_period_id` 对比 → 不同则触发**全量同步**
2. **分类维度**：同周期内，逐分类对比网站实际唯一记录数与 ES 计数 → 有差异触发**增量同步**

网站 `total` 字段可能含重复数据，检测时会精确遍历去重（MD5 doc key），确保准确判断。

---

## 断点续传

本地进度保存在 `.jinan_sync_progress.json`，记录当前分类 ID、周期 ID、页码、已写记录数。

中断后运行 `./run.sh sync`，自动从断点继续（同一周期内的后续分类或页面）。

---

## 依赖

- Python 3
- `requests` / `beautifulsoup4` / `pyyaml`
- `playwright` + `chromium`（用于从浏览器 localStorage 获取 token）
- Elasticsearch：`http://localhost:59200`

安装依赖：
```bash
pip3 install requests beautifulsoup4 pyyaml playwright
playwright install chromium
```

---

## 数据流

```
jnxxj.jngczjxh.com:5020
  ↓  (Playwright 获取 token，requests 调用 API)
commands/sync.py
  ↓  (幂等写入，_id = MD5(breed+spec+period+period_id+catalogue_id+price))
Elasticsearch: ods_material_jinan_price
  ↓  (gov-price-etl)
dwd_jinan_price
  ↓  (sync_dws.py)
dws_jinan_price
```