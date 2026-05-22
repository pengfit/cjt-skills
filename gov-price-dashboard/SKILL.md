# gov-price-dashboard

政府材料价格数据可视化看板，基于 FastAPI + Vue3，支持多维度筛选、价格趋势分析、涨跌幅监控。

## 启动

```bash
cd skills/gov-price-dashboard
./start.sh
```

- 前端：http://localhost:5300
- API：http://localhost:5200
- API 文档：http://localhost:5200/docs

## 数据架构

```
ods_material_{city}_price    (ODS 原始层)
         ↓
dwd_{city}_price             (DWD 清洗层)
         ↓
dws_{city}_price             (DWS 聚合层，API 查询)
         ↓
gov-price-dashboard API (FastAPI :5200)
         ↓
gov-price-dashboard 前端 (Vue3 :5300)
```

## API 端点

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/search` | 搜索查询，支持关键词/省份/城市/区县/价格范围分页 |
| GET | `/api/stats/overview` | 全局概览：总量、省份/城市/品类分布 |
| GET | `/api/stats/categories` | 品类统计 |
| GET | `/api/stats/category-detail` | 品类明细 |
| GET | `/api/stats/category-price-ranges` | 品类价格区间 |
| GET | `/api/stats/breed-detail` | 品牌明细 |
| GET | `/api/stats/data-health` | 数据健康度 |
| GET | `/api/stats/price-distribution` | 价格分布 |
| GET | `/api/stats/xian-sync-progress` | 西安同步进度 |
| GET | `/api/stats/sichuan-sync-progress` | 四川同步进度 |
| GET | `/api/stats/rizhao-sync-progress` | 日照同步进度 |
| GET | `/api/stats/jinan-sync-progress` | 济南同步进度 |
| GET | `/api/stats/chongqing-sync-progress` | 重庆同步进度 |

## 搜索 API 参数

```
GET /api/search?keyword=&province=&city=&county=&category=
    &min_price=&max_price=&page=1&page_size=20&sort=date&order=desc
```

## search 返回字段

```json
{
  "id": "_id",
  "breed": "产品名称",
  "spec": "规格",
  "attr": { "thickness": "2mm", "cores": "3芯", "diameter": "150", ... },
  "unit": "单位",
  "price": 100.0,
  "tax_price": 113.0,
  "province": "陕西",
  "city": "西安",
  "county": "阎良区",
  "date": "2026-05-20"
}
```

## attr 字段说明

| 字段 | 说明 | 示例 |
|------|------|------|
| `thickness` | 厚度 | `2mm` |
| `length` | 长度 | `1000mm` |
| `width` | 宽度 | `800mm` |
| `height` | 高度 | `600mm`, `H=0.36m→360mm` |
| `height_range` | 高度范围 | `H100~H250` |
| `diameter` | 直径 | `150` |
| `cross_section` | 电缆截面 | `2.5mm²` |
| `cores` | 芯数 | `3芯` |
| `voltage` | 电压 | `220` |
| `current` | 电流 | `16` |
| `material` | 材质 | `PE` |
| `color` | 颜色 | `白` |
| `grade` | 等级/牌号 | `Q235B`, `C30` |
| `asphalt_type` | 沥青类型 | `AC-13` |
| `cement_content` | 水泥含量 | `5%` |
| `channels` | 路数 | `8路` |
| `doors` | 门数 | `2门` |
| `drain_type` | 排水类型 | `下出水` |
| `installation_type` | 安装类型 | `台下盆` |
| `inlet_type` | 进水类型 | `后进水` |
| `length_range` | 长度范围 | `2~4m` |
| `temperature` | 温度 | `70℃` |
| `temp_range` | 温度范围 | `-10℃~50℃` |
| `humidity_range` | 湿度范围 | `0~100%RH` |

## 数据索引（API 查询）

| 索引 | 说明 |
|------|------|
| `dws_{city}_price` | API 查询层 |
| `ods_material_{city}_price` | ODS 原始层（同步进度查询） |
| `ods_material_{city}_price_sync_progress` | 同步进度 |

## 停止

```bash
kill $(lsof -ti :5173 -ti :5200)
```

## 项目结构

```
gov-price-dashboard/
├── start.sh
├── api/
│   ├── main.py              # FastAPI 后端
│   └── requirements.txt
└── frontend/
    ├── package.json
    ├── vite.config.js
    └── src/
        ├── App.vue          # 主应用（搜索/列表/图表）
        └── style.css        # 全局样式
```