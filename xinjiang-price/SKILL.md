---
name: xinjiang-price
description: "新疆工程造价材料信息采集：从 xjzj.com 抓取 16 个地州（市）按月的建设工程综合价格信息 xlsx 附件，解析后入仓 ods_material_xinjiang_price。"
---

# xinjiang-price

新疆工程造价材料信息采集 Skill。从新疆工程造价信息网（`www.xjzj.com`）抓取 16 个地州（市）按月发布的「建设工程综合价格信息」，解析每份 xlsx 附件中的多 sheet 数据，按「地州/县(市)/期/材料」维度写入本地 ES 索引 `ods_material_xinjiang_price`。

## 数据源

- **站点**：`https://www.xjzj.com`
- **列表接口**：`POST /Home/GetPoliciesListBy`（AJAX）
  - 参数：`guid=c8df326e-cf0e-494d-b643-bd45cdb32773`（"价格信息"菜单）、`areaid`、`page`、`pagesize`
- **详情页**：`/Home/PoliciesDetail/<ID>`，从中提取 `LookFile()` 附件链接
- **附件类型**：`.xlsx`（含税/不含税综合信息价，多 sheet 按"县(市)"分）

## 16 个地州（市）

`div.quickLinkDiv` 列出全部地区，按 `areaid` 区分（缺 6 号）：

| areaid | 名称 | city |
|--------|------|------|
| 1 | 伊犁 | 伊犁哈萨克自治州 |
| 2 | 乌鲁木齐 | 乌鲁木齐市 |
| 3 | 昌吉 | 昌吉回族自治州 |
| 4 | 克拉玛依 | 克拉玛依市 |
| 5 | 石河子 | 石河子市 |
| 7 | 塔城 | 塔城地区 |
| 8 | 阿勒泰 | 阿勒泰地区 |
| 9 | 哈密 | 哈密市 |
| 10 | 巴州 | 巴音郭楞蒙古自治州 |
| 11 | 阿克苏 | 阿克苏地区 |
| 12 | 喀什 | 喀什地区 |
| 13 | 五家渠市 | 五家渠市 |
| 14 | 博州 | 博尔塔拉蒙古自治州 |
| 15 | 克州 | 克孜勒苏柯尔克孜自治州 |
| 16 | 和田地区 | 和田地区 |
| 17 | 吐鲁番 | 吐鲁番市 |

## xlsx 结构

- **每个 xlsx 多 sheet**：每个 sheet 对应一个"县(市)"，sheet 名作为 `county` 字段
- **首 sheet**（如"伊宁市、伊宁县、察布查尔县"）通常是大表，跨多列（16285 列源自列合并，无意义）
- **其他 sheet** 50-60 行 × 5-6 列：
  - R1：标题（合并单元，如"霍尔果斯市2026年4月份建设工程综合价格信息"）
  - R2：表头（合并）—— `序号 | 材料名称及规格型号 | 单位 | 除税综合信息价 | 含税综合信息价`
  - R3：分类标题（如"钢材"）
  - R4+：数据行
- **解析后字段**：breed / spec / unit / price（除税）/ tax_price（含税）/ category / sheet_name

## 命令

```bash
./run.sh                  # 帮助
./run.sh sync             # 同步 2026 年全部 16 个 area
./run.sh sync-dry         # dry-run（不写入）
./run.sh sync-area 1      # 只同步 areaid=1（伊犁）
./run.sh reset            # 重置本地进度
./run.sh check            # 增量检测（源站 vs ES）
./run.sh status           # 查看进度（本地 + ES + MinIO）
./run.sh test             # 连通性测试
```

## 数据字段

| 字段 | 说明 |
|------|------|
| `breed` | 材料名称 |
| `spec` | 规格型号 |
| `unit` | 单位 |
| `price` | 除税综合信息价（不含税价） |
| `tax_price` | 含税综合信息价 |
| `category` | 分类（钢材 / 水泥 / 混凝土等，从分类标题行提取） |
| `period` | 周期，格式 `YYYY-MM-DD`（取每月 1 号） |
| `province` | 新疆 |
| `city` | 地州（市）名（如 伊犁哈萨克自治州） |
| `county` | 县(市)名（sheet_name） |
| `area_name` | 地区标签（如 伊犁） |
| `update_date` | 政策发布日期 |
| `create_time` | 入库时间 |
| `source_file` | MinIO key |
| `source_url` | 附件原始 URL |
| `source_id` | 政策 ID（PoliciesDetail/<ID>） |
| `sheet_name` | xlsx sheet 名（即 county） |

## ES 索引

| 索引 | 说明 |
|------|------|
| `ods_material_xinjiang_price` | 材料价格数据 |
| `ods_material_xinjiang_price_sync_progress` | 同步进度（每政策一条） |

## 幂等写入

```
_id = MD5(areaid + period + sheet + breed + spec + unit)
```

同一期同一 sheet 同一材料重复写入会自动覆盖。

## 断点续传

- 本地进度文件：`.xinjiang_sync_progress.json`（`done` = 政策粒度，`areas` = area 汇总）
- 重跑 sync 自动跳过已 `ok` 的政策
- `--no-skip` 强制重新跑所有
- `--reset` 清空进度文件

## 附件存储

每个 xlsx 上传到 MinIO：
```
xinjiang-price/<areaid>/<policy_id>/<original_filename>
```

## Dashboard 注册

`skill.yml` 字段：`key=xinjiang`、`province=新疆`、`progress_mode=county`。

dashboard 启动时会自动扫盘该 skill.yml 并加入同步卡片。

如已启动 dashboard，新增 skill 后可热加载：
```bash
curl -X POST http://localhost:5200/api/skill-registry/reload
```

## 依赖

- Python 3
- requests, pyyaml, elasticsearch, boto3, openpyxl
- MinIO（gov-price-data bucket）+ Elasticsearch
