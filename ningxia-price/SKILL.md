---
name: "ningxia-price"
description: "宁夏工程造价信息采集：jst.nx.gov.cn《宁夏工程造价》期刊，HTML 列表 + 详情页抓 PDF，按期刊期数入库到 ods_material_ningxia_price。"
---

# ningxia-price

宁夏回族自治区住房和城乡建设厅"造价动态"栏目《宁夏工程造价》期刊采集。从 `jst.nx.gov.cn/ztzl/gczj/zjtt/` 抓取列表（按月发布），访问详情页拿 PDF 链接，下载 PDF，上传 MinIO，pdfplumber 解析为长表，按期刊期数同步至 ES，写入 `ods_material_ningxia_price`。

> **当前数据范围**：2026 年第 1 期（2026-03-20）、2026 年第 2 期（2026-05-18），共 **6405 条**。
> 列表还含 2023-2025 各期，按需扩展。**只保留标题含"《宁夏工程造价》"的期**，跳过其他通知。

## 数据流

```
jst.nx.gov.cn/ztzl/gczj/zjtt/index.html (列表 HTML)
   ↓ + index_2.html / index_3.html ... (共 5 页)
列表 (每期: title, publish_date, detail_url)
   ↓ journal_keyword 过滤（"《宁夏工程造价》"）
详情页
   ↓ fetch_detail_pdf
   ↓ 从 a[href$=pdf] 或 var params="…pdf"; JS 字符串提取 PDF 链接
PDF (154-159 页, ~5-9 MB)
   ↓ upload
MinIO: gov-price-data/ningxia-price/{period}/{basename}.pdf
   ↓ pdfplumber.extract_tables
   ↓ 仅解析"价格资讯"章节，跳过政策文件/改革探索/采集编制说明等
   ↓ 横向"材料×城市"价格表 → 长表展开（每市/县一行）
   ↓ 跳过定额项目价格表（项目编号 5 位）
长表
   ↓ bulk_index
ods_material_ningxia_price
```

## PDF 结构

| 章节 | 内容 | 是否解析 |
|---|---|---|
| 政策文件 / 改革探索 / 信息动态 | 文章 | ❌ 跳过 |
| 采集编制说明 | 文字说明 | ❌ 跳过 |
| 价格资讯 → 人工价格信息 | 工种 × 价格区间 | ❌ 暂未解析（4列简单表，未来可加） |
| 价格资讯 → 定额项目价格（8-11 节） | 项目编号 × 项目名 × 单位 × 价格 | ❌ 暂未解析（横排项目编号） |
| **价格资讯 → 材料价格信息** | 序号 × 材料 × 规格 × 单位 × 各市县价 | ✅ 主体 |
| 价格资讯 → 市政工程主要材料 | 同上结构 | ✅ 兼容（同表头）|
| 价格资讯 → 预拌混凝土 / 绿色认证混凝土 | 地区 × 强度等级 × 多列价格 | ❌ 暂未解析（横排表）|

## 当前解析覆盖（v2）

| 章节 | 条数/期 | 表头结构 | cities 字段 |
|---|---|---|---|
| 一~五、地市基础表（银川/石嘴山/吴忠/固原/中卫）| 22 项 × 2~5 城市 = 70~110 | 6+ 列 | 各县/市 |
| 六、宁东能源化工基地 | 14 项 | 5 列单价格 | 综合价格 |
| 全区建筑工程主要材料价格（p66-p144）| ~1200 项 | 6 列含备注 | 综合价格 |
| 装配式及绿色建材（p145-p148）| ~50 项 | 6 列 | 综合价格 |
| 绿色建材多星等级（p149-p151）| ~150 项 | 8 列 | 一星级/二星级/三星级 |
| 预拌混凝土 / 绿色认证混凝土（p150-p152）| ~150 项 | 12 列 | ❌ 未解析 |

## 字段映射

| 字段 | 来源 |
|---|---|
| `period` | 从 title 提取：`2026年第2期` → `2026.第2期` |
| `section` | 固定 `材料价格` |
| `category` | 固定 `主要材料` |
| `region` | 地市分组（一、银川市 / 二、石嘴山市 / ...）|
| `city` | 表格列头（银川市/灵武市/大武口区/...）|
| `no` | 表格首列（材料序号 1-22）|
| `breed` | 表格第 2 列（材料名称）|
| `spec` | 第 3 列（规格型号）|
| `unit` | 第 4 列（单位）|
| `price` | 城市价格列（去税价？见下）|
| `tax_price` | 含税价（price × 1.13）|

**价格方向**：宁夏 PDF 价格表默认是**不含税价**（表格单位"元"无特别说明），按 13% 增值税率反推含税价。

## 快速启动

```bash
cd skills/ningxia-price

./run.sh preview                    # 预览（不写入 ES、不上传 minio）
./run.sh preview --year 2026         # 指定年份预览
./run.sh sync --year 2026            # 同步 2026 年所有期
./run.sh sync --year 2026 --exclude-period "2026年第1期"  # 跳过某期
./run.sh sync --all                  # 同步所有未入仓的期
./run.sh status                      # 查看同步状态
```

## Dashboard 注册

为了让 `gov-price-dashboard` 自动发现本 skill，根目录需要 `skill.yml`（小写）：

```yaml
key: ningxia
label: 宁夏
province: 宁夏
ods_index: ods_material_ningxia_price
progress_index: ods_material_ningxia_price_sync_progress
progress_mode: period
expand_label: "▾ 期数详情"
config_path: config.yml
cities:
  - 银川市
  - 石嘴山市
  - 吴忠市
  - 固原市
  - 中卫市
```

dashboard 扫描 `~/.openclaw/workspace/skills/*/skill.yml` 自动注册。修改后调用 `POST /api/skill-registry/reload` 触发重扫 + 热更新 ALL_INDICES。

## 依赖

- Python 3
- requests / beautifulsoup4 / pyyaml
- pdfplumber
- boto3 (MinIO S3 兼容)
- elasticsearch

## 已知限制

- **定额项目价格表未解析**（8-11 节项目编号 5 位）——需另外开发 `_parse_quota_table`（已写框架，未启用）
- **人工价格表未解析**（4 列：序号/工种/单位/价格区间"190～230"）
- **预拌混凝土横排表未解析**（地区 × 强度等级 × 12 列价格）——结构特殊
- **2026.1期 偶有 PdfminerException**（p3-p4 封面页），已 try/except 跳过
- **价格含税/不含税方向**：默认按不含税入 price，tax_price = price × 1.13。PDF 实际是含税价还是不含税价，需以原文档为准
- **市/县字段**从表头列名推断；COMMON_COUNTIES 列表需维护新县区时扩展