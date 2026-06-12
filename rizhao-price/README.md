# rizhao-price 日照工程造价材料信息采集

从 `http://58.59.43.227:81/dist/#/index/priceDissemination` 抓取日照市工程造价材料价格数据，写入本地 ES。

---

## 快速开始

```bash
cd ~/.openclaw/workspace/skills/rizhao-price

# 增量同步（全 tab）
./run.sh sync --force

# 指定类别同步（1=建设工程, 2=园林绿化, 3=区县）
./run.sh sync --type 2

# 预览前 3 页数据
./run.sh preview --pages 3

# 手动增量检测（不写入 ES）
./run.sh check
```

---

## 三个数据类别

| tab_type | 名称 | 数据量 |
|----------|------|--------|
| `1` | 建设工程材料 | ~1083 条 |
| `2` | 园林绿化苗木 | ~7 条 |
| `3` | 区县建设工程材料 | ~60 条 |

---

## 命令参考

| 命令 | 说明 |
|------|------|
| `./run.sh sync` | 增量同步（当前 tab，有新数据才同步）|
| `./run.sh sync --force` | 全量同步（所有 tab，幂等写入自动补漏）|
| `./run.sh sync --type N` | 指定 tab 同步（N=1/2/3）|
| `./run.sh sync --no-check` | 跳过增量检测直接同步 |
| `./run.sh sync --max-pages N` | 最大页数（默认 2000）|
| `./run.sh sync --dry-run` | 预览模式，不写入 ES |
| `./run.sh sync --reset` | 重置进度，从头开始 |
| `./run.sh preview` | 预览数据（默认前 2 页）|
| `./run.sh preview --pages 3 --type 2` | 预览 tab2 前 3 页 |
| `./run.sh check` | 手动增量检测 |
| `./run.sh status` | 查看同步状态和进度 |
| `./run.sh test` | 测试 ES 和源站连接 |

---

## 增量机制

每 30 分钟自动检测一次，无需人工干预。**检测逻辑**分两级：

1. **周期维度**：网站当前期数 vs `config.yml` 中 `last_period` → 不同则触发全量同步
2. **tab 维度**：同周期内，逐 tab 对比网站 `totalCount` vs ES 文档数 → 有差异则触发该 tab 增量同步

触发同步时逐 tab 执行，幂等写入自动补漏：

```
[→] 同步 tab 2 园林绿化苗木...
[✓] tab 2 完成
[→] 同步 tab 3 区县建设工程材料...
[✓] tab 3 完成
[i] 增量同步全部完成
```

---

## 数据字段

每条材料记录包含以下字段：

| 字段 | 说明 |
|------|------|
| `breed` | 材料名称 |
| `spec` | 规格型号 |
| `unit` | 单位 |
| `price` | 参考价格（元）|
| `period` | 期数（如 2026-03）|
| `province` | 山东 |
| `city` | 日照市 |
| `county` | 区县（tab_type=3 时区分具体区县）|
| `tab_type` | 类别 ID（1/2/3）|
| `tab_name` | 类别名称 |
| `update_date` | 更新日期 |
| `create_time` | 入库时间 |

---

## ES 索引

- **数据索引**：`ods_material_rizhao_price`
- **进度索引**：`ods_rizhao_price_progress`

---

## 配置（config.yml）

```yaml
es:
  host: http://localhost:59200
  index: ods_material_rizhao_price
  progress_index: ods_rizhao_price_progress
  sync_log_index: ods_rizhao_price_sync_log

site:
  base_url: http://58.59.43.227:81/EpointSDRZ
  price_page: http://58.59.43.227:81/dist/#/index/priceDissemination

sync:
  last_period: "2026-04"
```

`last_period` 由同步程序自动更新，无需手动修改。

---

## 依赖

- Python 3 + `requests` `pyyaml`
- Node.js + `playwright`（`npx playwright install chromium`）
- 本地 ES：`http://localhost:59200`