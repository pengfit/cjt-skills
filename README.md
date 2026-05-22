# cjt-skills

政府材料价格数据流水线技能集合，包含数据同步、ETL 清洗、数据可视化全链路。

## 架构

```
原始数据源 (政府工程造价网站)
    ↓
[城市]-material-price (数据同步)
    ↓
ods_material_{city}_price (原始层)
    ↓
gov-price-etl (ETL 清洗)
    ↓
dwd_{city}_price (清洗层)
    ↓
gov-price-etl/sync_dws (聚合同步)
    ↓
dws_{city}_price (聚合层)
    ↓
gov-price-dashboard (可视化)
```

## 目录结构

```
cjt-skills/
├── gov-price-etl/          # ETL 清洗逻辑
│   ├── commands/
│   │   ├── etl.py         # ODS → DWD
│   │   └── parse_spec/   # 规格解析规则（rules/ 目录驱动）
│   └── utils/
│       └── sync_dws.py    # DWD → DWS
│
├── gov-price-dashboard/     # 数据可视化看板
│   ├── api/                # FastAPI 后端 :5200
│   └── frontend/           # Vue3 前端 :5300
│
├── xa-material-price/      # 西安数据同步
├── sichuan-price/          # 四川数据同步
├── chongqing-price/        # 重庆数据同步
├── jinan-price/            # 济南数据同步
└── rizhao-price/           # 日照数据同步
```

## 快速启动

### 数据同步（单个城市）
```bash
cd skills/xa-material-price
./run.sh sync
```

### ETL 清洗
```bash
cd skills/gov-price-etl
python3 commands/etl.py
```

### 数据看板
```bash
cd skills/gov-price-dashboard
./start.sh
# 前端: http://localhost:5300
# API:  http://localhost:5200
# 溯源:  http://localhost:5300 → 点击"数据溯源"标签
```

## 数据层说明

| 层次 | 说明 | 示例索引 |
|------|------|---------|
| **ODS** | 原始数据，未清洗 | `ods_material_xian_price` |
| **DWD** | 清洗数据，含 attr 结构化字段 | `dwd_xian_price` |
| **DWS** | 聚合数据，API 查询层 | `dws_xian_price` |

## attr 解析字段

parse_spec.py 将复合规格解析为结构化字段：

- 尺寸：`thickness` `length` `width` `height` `diameter`
- 电缆：`cross_section` `cores` `voltage` `current`
- 材质：`material` `color` `grade`
- 专业：`asphalt_type` `cement_content` `channels` `doors`
- 洁具：`drain_type` `installation_type` `inlet_type`
- 其他：`temperature` `temp_range` `humidity_range` `length_range` `height_range`

## 支持城市

- 西安 (xian)
- 四川 (sichuan)
- 重庆 (chongqing)
- 济南 (jinan)
- 日照 (rizhao)

## 环境依赖

| 组件 | 依赖 |
|------|------|
| gov-price-etl | Python 3, requests, elasticsearch |
| gov-price-dashboard | Python 3, FastAPI, requests; Node.js 18+, Vue3 |

## 相关文档

- [gov-price-etl](./gov-price-etl/SKILL.md)
- [gov-price-dashboard](./gov-price-dashboard/SKILL.md)