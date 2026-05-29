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

## 架构

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

## 项目结构

```
gov-price-dashboard/
├── start.sh                  # 一键启动脚本
│
├── api/
│   ├── main.py               # FastAPI 后端
│   ├── requirements.txt
│   └── routes/
│       └── provenance.py     # 数据溯源路由（含规格解析质量、AI规则生成）
│
└── frontend/
    ├── package.json
    ├── vite.config.js
    └── src/
        ├── App.vue            # 主应用（搜索/列表/图表）
        ├── main.js
        ├── style.css
        └── components/
            ├── CategoryView.vue           # 类别分析视图
            ├── DataProvenanceView.vue    # 数据溯源视图
            ├── DistributionChart.vue     # 数据分布图
            ├── CustomSelect.vue          # 自定义下拉筛选
            ├── ErrorBoundary.vue         # 错误边界
            ├── VecRulesView.vue          # 规格规则库视图
            └── BreedCategoryRulesView.vue # 分类规则库视图
```

## API 端点总览（FastAPI :5200）

### 搜索与筛选

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/search` | 价格搜索（分页/筛选/sort） |
| `GET` | `/api/filter-options` | 省市区三级联动选项 |
| `GET` | `/api/stats/overview` | 全局概览（总量/省份/城市/分类分布） |

### 分类与品种

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/stats/categories` | 所有产品类别及数据量 |
| `GET` | `/api/stats/category-detail` | 指定类别省份分布+热门品种+规格价格 |
| `GET` | `/api/stats/category-price-ranges` | 指定类别的动态价格区间（按分位数） |
| `GET` | `/api/stats/category-breeds` | 指定类别的去重品种列表（分页） |
| `GET` | `/api/stats/breed-detail` | 指定品种的规格价格分析（按单位→规格分层） |
| `GET` | `/api/stats/breed-category-rules` | 全量 breed 归属分类（分类规则库下拉） |

### 价格统计

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/stats/price-distribution` | 全局或分类下的价格区间分布 |
| `GET` | `/api/stats/province-ranges` | 多省份价格区间分布对比 |

### 数据质量

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/stats/data-health` | 数据健康度（每日入库量/省份新鲜度/增量异常） |

### 同步进度

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/stats/scrape-progress` | 单城市抓取进度（`?city=xian`） |
| `GET` | `/api/stats/scrape-progress-all` | 全部城市抓取进度汇总 |
| `GET` | `/api/stats/xian-sync-progress` | 西安同步进度（6区县） |
| `GET` | `/api/stats/sichuan-sync-progress` | 四川同步进度（21地市） |
| `GET` | `/api/stats/rizhao-sync-progress` | 日照同步进度（3类别） |
| `GET` | `/api/stats/jinan-sync-progress` | 济南同步进度（41分类目录） |
| `GET` | `/api/stats/chongqing-sync-progress` | 重庆同步进度（35区县） |

### 数据溯源

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/stats/provenance` | 数据溯源（新鲜度/趋势/来源，`?city=all`） |

### 规格解析质量

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/stats/rules-vector` | 规格规则库查询（分页+过滤+搜索） |
| `GET` | `/api/stats/spec-quality` | Spec 解析质量报告（抽样+分类覆盖率） |
| `POST` | `/api/stats/spec-quality/fix-case` | 规则预览/确认（confirm=False 预览，confirm=True 写入） |
| `POST` | `/api/stats/spec-quality/refresh-category` | 触发指定分类的 DWD→DWS 清洗重算 |

### 品种分类规则

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/api/stats/breed-category-rules` | 分页查看品种→分类规则 |
| `POST` | `/api/stats/breed-category-rules` | 手动添加品种→分类规则 |
| `DELETE` | `/api/stats/breed-category-rules/{id}` | 删除指定规则 |
| `POST` | `/api/stats/breed-category-rules/test` | 测试品种名 Jaccard 召回 |
| `POST` | `/api/stats/spec-quality/classify-breed-batch` | 批量 AI 推断品种分类并写入规则库 |

## 搜索 API 参数

```
GET /api/search?keyword=&province=&city=&county=&category=
    &unit=&price_min=&price_max=&page=1&page_size=20
```

### search 返回字段

```json
{
  "id": "_id",
  "breed": "产品名称",
  "spec": "规格",
  "attr": { "thickness": "2mm", "cores": "3芯", "diameter": "150", ... },
  "unit": "单位",
  "price": 100.0,
  "price_t": 100.0,
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
| `length` | 长度 | `1200mm` |
| `width` | 宽度 | `400mm` |
| `height` | 高度 | `600mm`, `H=0.36m→360mm` |
| `height_range` | 高度范围 | `H100~H250` |
| `diameter` | 管径/口径 | `DN125~250`, `Φ700` |
| `cross_section` | 电缆截面 | `2.5mm²`, `240mm²` |
| `cores` | 芯数 | `3芯`, `4芯` |
| `voltage` | 电压 | `220`, `380` |
| `current` | 电流 | `16`, `32` |
| `material` | 材质 | `PVC`, `PE`, `铸铁` |
| `color` | 颜色 | `白`, `灰` |
| `grade` | 等级/牌号 | `C30`, `Q235B`, `P.O42.5R` |
| `asphalt_type` | 沥青类型 | `AC-13`, `SBSAC-13` |
| `cement_content` | 水泥含量 | `5%` |
| `channels` | 通道数 | `8路` |
| `doors` | 门数 | `2门` |
| `drain_type` | 排水类型 | `下出水`, `地排水` |
| `installation_type` | 安装类型 | `台下盆`, `立柱盆` |
| `inlet_type` | 进水类型 | `后进水`, `侧进水` |
| `fiber_core` | 光纤芯数 | `12芯`, `24芯` |
| `length_range` | 长度范围 | `2~4m` |
| `media` | 介质 | `水`, `气` |
| `range` | 量程 | `0~100MPa` |
| `output` | 功率 | `50W`, `100W` |
| `cable_length` | 线缆长度 | `5m`, `10m` |
| `temperature` | 温度 | `70℃` |
| `temp_range` | 温度范围 | `-10℃~50℃` |
| `humidity_range` | 湿度范围 | `0~100%RH` |
| `pressure` | 压力等级 | `PN16`, `PN25` |
| `ring_stiffness` | 环刚度 | `SN8` |
| `ip_rating` | 防护等级 | `IP65` |
| `inner_diameter` | 内径 | `DN100` |
| `wall_thickness` | 壁厚 | `5mm` |
| `surface` | 表面处理 | `热镀锌` |
| `fire_rating` | 耐火等级 | `A级` |

## ES 索引结构

| 城市 | ODS 层 | DWD 层 | DWS 层 | 进度索引 |
|------|--------|--------|--------|---------|
| 西安 | `ods_material_xian_price` | `dwd_xian_price` | `dws_xian_price` | `ods_material_xian_price_sync_progress` |
| 四川 | `ods_material_sichuan_price` | `dwd_sichuan_price` | `dws_sichuan_price` | `ods_material_sichuan_price_sync_progress` |
| 重庆 | `ods_material_chongqing_price` | `dwd_chongqing_price` | `dws_chongqing_price` | `ods_chongqing_price_progress` |
| 济南 | `ods_material_jinan_price` | `dwd_jinan_price` | `dws_jinan_price` | `ods_material_jinan_price_sync_progress` |
| 日照 | `ods_material_rizhao_price` | `dwd_rizhao_price` | `dws_rizhao_price` | `material_rizhao_price_sync_progress` |

**默认查询索引**：`dws_xian_price`（可通过 `ES_INDEX` 环境变量切换）

## 停止

```bash
./start.sh stop
# 或手动
kill $(lsof -ti :5200 -ti :5300)
```