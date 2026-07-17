# 山西工程造价材料信息采集 (shanxi-price)

山西省住房和城乡建设厅 → 服务专栏 → 数字造价服务 → 价格信息
源站: https://zjt.shanxi.gov.cn/fwzl/bzdexx/jgxx/

## 数据范围

- **时间**：2026 年起（道友要求，默认仅入库 2026 年期）
- **类别**：山西省各市常用建设工程材料价格信息（含税 / 不含税）
- **排除**：勘误（道友要求）、走势图（图表类）、园林苗木（非建筑工程材料）

## 周期

双月刊（6 期/年）：`1-2月 / 3-4月 / 5-6月 / 7-8月 / 9-10月 / 11-12月`

`period` 命名：`YYYY.M-N月`（如 `2026.3-4月`）

## 快速使用

```bash
cd ~/.openclaw/workspace/cjt/skills/shanxi-price
./run.sh test     # 连通性自检（ES + MinIO + 源站）
./run.sh preview  # 预览将入仓的期
./run.sh sync     # 同步到 ES + MinIO
./run.sh status   # 查看状态
./run.sh check    # 增量检测（不写入）
```

## ES 索引

- `ods_material_shanxi_price` — 原始抓取
- `ods_material_shanxi_price_sync_progress` — 同步进度
- `dwd_shanxi_price` / `dws_shanxi_price` — ETL 清洗 + 看板层

## MinIO

- bucket: `gov-price-data`
- prefix: `shanxi-price/`

详见 `SKILL.md`。