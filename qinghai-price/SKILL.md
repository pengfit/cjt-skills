---
name: "qinghai-price"
description: "青海建设工程材料价格采集：zjt.qinghai.gov.cn《青海建设工程市场价格信息》期刊，HTML 列表抓 PDF，按期刊期数入库到 ods_material_qinghai_price。"
---

# qinghai-price

青海省住房和城乡建设厅"造价信息"栏目《青海建设工程市场价格信息》期刊采集。从 `zjt.qinghai.gov.cn/html/132/List.html` 抓取列表（双月合刊），下载 PDF，上传 MinIO，pdfplumber 解析为长表，按期刊期数同步至 ES，写入 `ods_material_qinghai_price`。

> **当前数据范围**：2026 年第 1—2 期（2026-02-28）、2026 年第 3—4 期（2026-04-29），共 7977 条。
> 列表里还含 2023-2025 各期，按需扩展。**只关注《青海建设工程市场价格信息》**，跳过《青海工程造价管理信息》等其他期刊。

## 数据流

```
zjt.qinghai.gov.cn/html/132/List.html (列表 HTML)
   ↓ + List-1.html / List-2.html / List-3.html（4 页分页）
列表 (每期: title, publish_date, pdf_url 直接挂在 <a href=…pdf>)
   ↓ journal_keyword 过滤
   ↓ download
PDF (268 页, 双月合刊, ~95-262 MB)
   ↓ upload
MinIO: gov-price-data/qinghai-price/{period}/{basename}.pdf
   ↓ pdfplumber.extract_tables
长表 (5/6/7-10 列混合)
   ↓ bulk_index
ods_material_qinghai_price
```

## PDF 结构

- 双月合刊：每期刊登 2 个月材料价格，标题如 `2026年第1—2期《青海建设工程市场价格信息》`
- 表头多种：5 列基础 / 6 列双价（含税+除税）/ 7-10 列扩展（含牌号/直径/强度）
- 大量数据是"厂商名录 + 部分产品报价"格式（含联系人、地址、含税价）
- 价格：5 列默认含税，6 列有除税+含税双价
- 增值税率：13%（建设工程材料）

## 字段映射

| 字段 | 来源 |
|---|---|
| `period` | title（`2026年第3—4期《青海建设工程市场价格信息》`） |
| `section` | PDF 页眉识别的章节（一级类目）|
| `breed` | 表格第 2 列：材料/产品名称 |
| `spec` | 第 3 列：规格型号（含税表）或 第 3-倒数第 3 列拼接（多列表）|
| `unit` | 倒数第 2 列（多列表）/ 第 4 列（5/6 列表）|
| `price` | 除税价（5 列表反推 / 6 列表直接取）|
| `tax_price` | 含税价（5 列直接取 / 6 列直接取 / 多列末列反推）|
| `price_kind` | `含税` / `双价` |
| `category` | section 第一段（"混凝土"等）|

## 快速启动

```bash
cd skills/qinghai-price

./run.sh preview                  # 预览（不写入 ES、不上传 minio）
./run.sh preview --year 2026       # 指定年份预览
./run.sh sync --year 2026          # 同步 2026 年所有期
./run.sh sync --year 2026 --exclude-period "2026年第1—2期"  # 同步 2026 年跳过某期
./run.sh sync --all                # 同步所有未入仓的期
./run.sh status                    # 查看同步状态
```

## Dashboard 注册

为了让 `gov-price-dashboard` 自动发现本 skill，根目录需要 `skill.yml`（小写）：

```yaml
key: qinghai
label: 青海
province: 青海
ods_index: ods_material_qinghai_price
progress_index: ods_material_qinghai_price_sync_progress
progress_mode: period
expand_label: "▾ 期数详情"
config_path: config.yml
cities:
  - 青海
```

dashboard 扫描 `~/.openclaw/workspace/skills/*/skill.yml` 自动注册。修改后调用 `POST /api/skill-registry/reload` 触发重扫 + 热更新 ALL_INDICES。

## 依赖

- Python 3
- requests / beautifulsoup4 / pyyaml
- pdfplumber
- boto3 (MinIO S3 兼容)
- elasticsearch

## 已知限制

- **section 字段含书名号《》**：因为 PDF 页眉偶尔带标题符号，dashboard 拼接会显得冗长
- **厂商地址未归一化 city**：所有数据 city="青海"，address 在 PDF 但未抽到结构化字段
- **多列表抽取简化**：7-10 列表只取末列作价格，其他列拼到 spec，复杂表头（型号/规格/直径多列）会丢信息
- **未过滤"备注"行**：部分 PDF 行包含大段说明文字（如"含税，税率13%..."），会进 breed/spec 字段（如需可加 skip 规则）