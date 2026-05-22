# jinan-price

济南市工程造价材料信息采集工具。从 `http://jnxxj.jngczjxh.com:5020/cj/material-wave` 抓取材料价格数据，写入本地 ES。

---

## 功能特性

- **多分类目录**：41 个材料分类（黑色金属、橡胶塑料、五金制品、电缆等）
- **多周期管理**：支持 12 个历史周期，自动跟踪最新周期
- **断点续传**：进度保存在本地 JSON 中，中断后自动从断点恢复
- **增量检测**：每 30 分钟定时检测，有新增记录自动触发同步
- **去重写入**：基于 MD5(doc key) 的幂等写入，重复数据自动覆盖
- **增量到 ES**：写入 `http://localhost:59200`，支持全量检索

---

## 快速开始

```bash
# 首次全量同步
cd ~/.openclaw/workspace/skills/jinan-price
./run.sh sync

# 预览（不写入 ES）
./run.sh preview

# 强制全量同步（忽略增量检测）
./run.sh sync --force

# 重置进度，从头开始
./run.sh sync --reset
```

---

## 定时增量

每 30 分钟自动检测一次，无需人工干预：

```bash
# 手动触发增量检测
python3 commands/check.py
```

检测逻辑：
1. 获取网站最新周期 ID，与 `config.yml` 中 `last_period_id` 对比 → 不同则触发全量同步
2. 同周期内，逐分类对比**网站总数 vs ES 计数** → 有差异则触发增量同步
3. 同步完成后自动更新 `config.yml` 中的 `last_period_id`

---

## 命令参考

| 命令 | 说明 |
|------|------|
| `./run.sh sync` | 全量同步（增量模式） |
| `./run.sh sync --force` | 强制全量同步 |
| `./run.sh sync --dry-run` | 预览模式，不写入 ES |
| `./run.sh sync --reset` | 重置进度，重新开始 |
| `./run.sh sync --period-id ID` | 指定周期 ID 同步 |
| `./run.sh preview` | 预览数据 |
| `./run.sh preview --pages 3` | 预览前 3 页 |
| `./run.sh status` | 查看同步进度 |
| `./run.sh test` | 测试 ES 和网站连接 |
| `python3 commands/check.py` | 手动增量检测 |

---

## 数据输出

**ES 索引**：`material_jinan_price`

**分类目录索引**：`material_jinan_price_catalogue`（42 条，含 1 个根节点 + 41 个分类）

**进度索引**：`material_jinan_price_sync_progress`

每条材料记录字段：breed（材料名称）、spec（规格型号）、unit（单位）、price（含税价格）、period（周期名称）、period_id、catalogue（分类ID）、catalogue_name（分类名称）、publish_time、update_date 等。

---

## 依赖

- Python 3.14
- `requests` / `beautifulsoup4` / `pyyaml` / `playwright`
- 本地 ES：`http://localhost:59200`

安装依赖：
```bash
pip3 install requests beautifulsoup4 pyyaml playwright
playwright install chromium
```
