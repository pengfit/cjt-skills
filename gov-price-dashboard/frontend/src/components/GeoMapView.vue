<template>
  <div class="geo-map-view">
    <!-- ============ Page Header ============ -->
    <div class="geo-header">
      <div class="geo-title">
        <span class="geo-icon">🗺️</span>
        <div>
          <div class="geo-h1">地理分布</div>
          <div class="geo-sub">按地区聚合材料价格，支持全国 / 省级 / 市级三级下钻</div>
        </div>
      </div>
      <!-- 面包屑 -->
      <div class="geo-breadcrumb" v-if="crumbs.length">
        <span
          v-for="(c, i) in crumbs"
          :key="i"
          class="crumb"
          :class="{ active: i === crumbs.length - 1, clickable: i < crumbs.length - 1 }"
          @click="i < crumbs.length - 1 && goToCrumb(i)"
        >
          {{ c }}
        </span>
        <span v-if="crumbs.length > 1" class="crumb-back" @click="goBack">← 返回上一级</span>
      </div>
    </div>

    <!-- ============ Filter Bar ============ -->
    <div class="geo-filter-bar">
      <div class="filter-item">
        <label>分类</label>
        <CustomSelect
          v-model="filterCategory"
          :options="categoryOptions"
          placeholder="全部分类"
          :searchable="true"
          @change="reload"
        />
      </div>
      <div class="filter-item">
        <label>产品名</label>
        <input
          v-model="filterBreed"
          class="filter-input"
          placeholder="🔍 关键词（可选）"
          @keyup.enter="reload"
        />
      </div>
      <div class="filter-item">
        <label>日期</label>
        <div class="date-range">
          <input v-model="dateFrom" class="filter-input" type="date" @change="reload" />
          <span class="dash">—</span>
          <input v-model="dateTo" class="filter-input" type="date" @change="reload" />
        </div>
      </div>
      <button class="btn-primary" @click="reload">🔄 刷新</button>
      <button class="btn-ghost" v-if="crumbs.length > 1" @click="goBack">← 返回</button>
    </div>

    <!-- ============ Main Content: Map + Side List ============ -->
    <div class="geo-main">
      <!-- Map -->
      <div class="geo-map-card">
        <div class="map-title">
          <span>{{ crumbs.join(' / ') }} · 材料均价热力图</span>
          <span class="map-stat" v-if="!loading">
            共 <b>{{ dataItems.length }}</b> 个地区 · 平均价 <b>{{ overallAvg.toLocaleString() }}</b> 元
          </span>
        </div>
        <div ref="chartEl" class="map-chart" v-show="!loading && dataItems.length"></div>
        <div v-if="loading" class="map-loading">
          <div class="loading-spinner"></div>
          <span>加载地图数据…</span>
        </div>
        <EmptyState
          v-if="!loading && dataItems.length === 0"
          icon="🗺️"
          title="该层级暂无数据"
          message="请调整筛选条件或返回上一级"
        />
      </div>

      <!-- Side List -->
      <div class="geo-side-card">
        <!-- 图例：价格色阶说明（取代 ECharts visualMap，让地图占满画布） -->
        <div class="side-legend">
          <div class="legend-label">价格色阶</div>
          <div class="legend-bar">
            <div class="legend-grad"></div>
            <div class="legend-ticks">
              <span>{{ formatLegendValue(valueRange[1]) }}</span>
              <span>{{ formatLegendValue((valueRange[0] + valueRange[1]) / 2) }}</span>
              <span>{{ formatLegendValue(valueRange[0]) }}</span>
            </div>
          </div>
        </div>
        <div class="side-title">📊 价格排行 TOP {{ Math.min(dataItems.length, 20) }}</div>
        <div class="side-hint" v-if="dataItems.length > 1">
          点击地图区域 / 列表项均可下钻
        </div>
        <div class="side-list" v-if="dataItems.length">
          <div
            v-for="(item, idx) in topN"
            :key="item.name + idx"
            class="side-row"
            :class="{ active: item.name === currentName }"
            @click="onRegionClick(item)"
          >
            <span class="rank" :class="`rank-${Math.min(idx + 1, 3)}`">{{ idx + 1 }}</span>
            <div class="info">
              <div class="name">{{ item.name }}</div>
              <div class="meta">
                <span class="count">{{ item.count.toLocaleString() }} 条</span>
                <span class="range" v-if="item.min && item.max">¥{{ item.min }} ~ {{ item.max }}</span>
              </div>
            </div>
            <div class="price">
              <div class="avg">¥{{ item.value.toLocaleString() }}</div>
              <div class="avg-sub">均价</div>
            </div>
            <div class="bar" :style="`--w: ${pctOf(item.value)}%`"></div>
          </div>
        </div>
        <EmptyState
          v-else
          icon="📭"
          compact
          title="暂无数据"
        />
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onBeforeUnmount, watch, nextTick } from 'vue'
import * as echarts from 'echarts'
import axios from 'axios'
import CustomSelect from './CustomSelect.vue'
import EmptyState from './EmptyState.vue'
import { registerGovPriceTheme, getGovPriceTheme } from '../composables/useEchartsTheme.js'

const API = import.meta.env.VITE_API_URL || '/api'
const GEO_BASE = '/geo'

const chartEl = ref(null)
let chart = null

// === Filters ===
const filterCategory = ref('')
const filterBreed = ref('')
const dateFrom = ref('')
const dateTo = ref('')
const categoryOptions = ref([])

// === Drilldown state ===
const breadcrumbs = ref([])   // 面包屑栈：[{ level, parent, parent2, label }]
const dataItems = ref([])     // 当前层级的地区聚合
const currentName = ref('')   // 当前 hover/click 选中的地区
const loading = ref(false)

// === Computed ===
const crumbs = computed(() => breadcrumbs.value.map(b => b.label))
const topN = computed(() => dataItems.value.slice(0, 20))
const overallAvg = computed(() => {
  if (!dataItems.value.length) return 0
  const sum = dataItems.value.reduce((s, x) => s + x.value * x.count, 0)
  const cnt = dataItems.value.reduce((s, x) => s + x.count, 0)
  return cnt > 0 ? Math.round(sum / cnt) : 0
})
const valueRange = computed(() => {
  if (!dataItems.value.length) return [0, 1]
  const vals = dataItems.value.map(x => x.value).filter(v => v > 0)
  if (!vals.length) return [0, 1]
  return [Math.min(...vals), Math.max(...vals)]
})

// 侧栏图例价格格式化（Y轴刻度：0, 100, 1.2k, 15k, 1.2M）
function formatLegendValue(v) {
  const n = Number(v)
  if (n >= 10000) return Math.round(n / 1000) + 'k'
  if (n >= 1000) return (n / 1000).toFixed(1) + 'k'
  if (n >= 1) return Math.round(n).toString()
  return n.toFixed(2)
}

// === Lifecycle ===
onMounted(async () => {
  registerGovPriceTheme()
  await loadCategoryOptions()
  await reload()
  window.addEventListener('resize', handleResize)
  // 使用 ResizeObserver 监听容器尺寸变化
  // 解决首次挂载时 v-if 切换导致容器宽度为 0、地图渲染失败的问题
  if (chartEl.value) {
    resizeObserver = new ResizeObserver(entries => {
      for (const entry of entries) {
        const { width, height } = entry.contentRect
        if (width > 0 && height > 0) {
          if (chart) {
            chart.resize()
          } else if (dataItems.value.length) {
            // 容器有尺寸但图表未初始化，重新渲染
            renderMap()
          }
        }
      }
    })
    resizeObserver.observe(chartEl.value)
  }
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', handleResize)
  if (resizeObserver) {
    resizeObserver.disconnect()
    resizeObserver = null
  }
  if (chart) {
    chart.dispose()
    chart = null
  }
})

let resizeObserver = null

function handleResize() {
  chart?.resize()
}

// === API ===
async function loadCategoryOptions() {
  try {
    const { data } = await axios.get(`${API}/filter-options`)
    const cats = (data.categories || []).map(c => ({ key: c, label: c }))
    categoryOptions.value = cats
  } catch (e) {
    console.warn('加载分类选项失败', e)
  }
}

async function reload() {
  const level = currentLevel.value
  const parent = breadcrumbs.value[breadcrumbs.value.length - 1]?.parent
  const parent2 = breadcrumbs.value[breadcrumbs.value.length - 1]?.parent2
  loading.value = true
  try {
    const params = { level }
    if (parent) params.parent = parent
    if (parent2) params.parent2 = parent2
    if (filterCategory.value) params.category = filterCategory.value
    if (filterBreed.value) params.breed = filterBreed.value
    if (dateFrom.value) params.date_from = dateFrom.value
    if (dateTo.value) params.date_to = dateTo.value
    const { data } = await axios.get(`${API}/stats/geo-distribution`, { params })
    dataItems.value = data.items || []
    await renderMap()
  } catch (e) {
    console.error('加载地理分布失败', e)
    dataItems.value = []
  } finally {
    loading.value = false
  }
}

const currentLevel = computed(() => {
  if (breadcrumbs.value.length === 0) return 'province'
  if (breadcrumbs.value.length === 1) return 'city'
  return 'county'
})

const currentMapName = computed(() => {
  if (breadcrumbs.value.length === 0) return 'china'
  if (breadcrumbs.value.length === 1) {
    const adcode = breadcrumbs.value[0].adcode
    return adcode ? String(adcode) : 'china'
  }
  // 市级：需要市级 adcode，这里用省级 adcode 兜底
  return breadcrumbs.value[0]?.adcode ? String(breadcrumbs.value[0].adcode) : 'china'
})

// === Map Render ===
async function renderMap() {
  await nextTick()
  if (!chartEl.value) return
  // 检查容器尺寸，避免在 0x0 容器上初始化导致警告
  const rect = chartEl.value.getBoundingClientRect()
  if (rect.width === 0 || rect.height === 0) {
    // 容器还没布局好，等下一帧再试（ResizeObserver 会接住）
    requestAnimationFrame(() => {
      if (chartEl.value) renderMap()
    })
    return
  }
  if (!chart) {
    chart = echarts.init(chartEl.value, getGovPriceTheme())
  }
  // 加载地图 GeoJSON
  const mapName = await ensureMapLoaded(currentMapName.value)
  if (!mapName) {
    console.warn('地图加载失败')
    return
  }
  // 准备 data
  // 映射短名→GeoJSON 全名（仅 province 层级需要）
  // ES 数据中省份是 "四川"，DataV.GeoAtlas 用 "四川省"
  const data = dataItems.value
    .filter(d => d.value > 0)
    .map(d => ({
      name: currentLevel.value === 'province' ? (PROVINCE_NAME_MAP[d.name] || d.name) : d.name,
      value: d.value,
      count: d.count,
      min: d.min,
      max: d.max,
    }))
  // visualMap 范围
  const [min, max] = valueRange.value
  const option = {
    tooltip: {
      trigger: 'item',
      formatter: (p) => {
        if (p.seriesType === 'map') {
          const c = p.data?.count
          if (c === undefined) return `${p.name}：暂无数据`
          return [
            `<b>${p.name}</b>`,
            `均价：<b style="color:#2563eb">¥${Number(p.value).toLocaleString()}</b>`,
            `数据量：${Number(c).toLocaleString()} 条`,
            `区间：¥${p.data.min} ~ ¥${p.data.max}`,
            '',
            '💡 点击下钻',
          ].join('<br/>')
        }
        return p.name
      },
    },
    series: [
      {
        name: '均价',
        type: 'map',
        map: mapName,
        roam: true,
        zoom: 1.45,
        // 地图填满整个画布，ECharts 自动中心化
        top: 16,
        bottom: 16,
        left: 16,
        right: 16,
        label: { show: true, fontSize: 10, color: '#0f172a' },
        itemStyle: {
          borderColor: '#ffffff',
          borderWidth: 1,
        },
        emphasis: {
          label: { show: true, fontSize: 12, fontWeight: 700 },
          itemStyle: { areaColor: '#facc15' },
        },
        select: {
          label: { show: true, color: '#0f172a' },
          itemStyle: { areaColor: '#f59e0b' },
        },
        data,
      },
    ],
    // visualMap 放到独立 DOM（侧栏），不占地图空间
  }
  chart.setOption(option, true)
  // 绑定 click
  chart.off('click')
  chart.on('click', (params) => {
    if (params.componentType === 'series' && params.seriesType === 'map' && params.data) {
      const item = dataItems.value.find(d => d.name === params.name)
      if (item) onRegionClick(item)
    }
  })
}

const _loadedMaps = new Set()

async function ensureMapLoaded(mapKey) {
  // mapKey: 'china' | adcode 字符串
  if (_loadedMaps.has(mapKey)) return mapKey
  let url
  if (mapKey === 'china') {
    url = `${GEO_BASE}/100000_full.json`
  } else {
    url = `${GEO_BASE}/${mapKey}_full.json`
  }
  try {
    const resp = await fetch(url)
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
    const geo = await resp.json()
    echarts.registerMap(mapKey, geo)
    _loadedMaps.add(mapKey)
    return mapKey
  } catch (e) {
    console.warn(`地图 ${mapKey} 加载失败：`, e)
    // 兜底：退回中国地图
    if (mapKey !== 'china') {
      return ensureMapLoaded('china')
    }
    return null
  }
}

// === Drilldown ===
function onRegionClick(item) {
  if (currentLevel.value === 'province') {
    // 准备省级 adcode 映射
    const adcode = PROVINCE_ADCODE[item.name]
    if (!adcode) {
      console.warn('未找到省份 adcode:', item.name)
      return
    }
    breadcrumbs.value.push({
      label: item.name,
      parent: item.name,
      parent2: '',
      adcode,
    })
    reload()
  } else if (currentLevel.value === 'city') {
    breadcrumbs.value.push({
      label: item.name,
      parent: item.name,
      parent2: breadcrumbs.value[breadcrumbs.value.length - 1].parent,
      adcode: breadcrumbs.value[breadcrumbs.value.length - 1].adcode,
    })
    reload()
  }
  // county 暂不继续下钻（先看效果）
  currentName.value = item.name
}

function goBack() {
  if (breadcrumbs.value.length === 0) return
  breadcrumbs.value.pop()
  reload()
}

function goToCrumb(idx) {
  // 跳到指定面包屑
  breadcrumbs.value = breadcrumbs.value.slice(0, idx + 1)
  reload()
}

// 短名→GeoJSON 全名映射（用于 ECharts 地图匹配）
const PROVINCE_NAME_MAP = {
  '北京': '北京市', '天津': '天津市', '河北': '河北省', '山西': '山西省',
  '内蒙古': '内蒙古自治区', '辽宁': '辽宁省', '吉林': '吉林省', '黑龙江': '黑龙江省',
  '上海': '上海市', '江苏': '江苏省', '浙江': '浙江省', '安徽': '安徽省',
  '福建': '福建省', '江西': '江西省', '山东': '山东省', '河南': '河南省',
  '湖北': '湖北省', '湖南': '湖南省', '广东': '广东省', '广西': '广西壮族自治区',
  '海南': '海南省', '重庆': '重庆市', '四川': '四川省', '贵州': '贵州省',
  '云南': '云南省', '西藏': '西藏自治区', '陕西': '陕西省', '甘肃': '甘肃省',
  '青海': '青海省', '宁夏': '宁夏回族自治区', '新疆': '新疆维吾尔自治区', '台湾': '台湾省',
}

// 省份 adcode（与后端 _PROVINCE_ADCODE 保持一致）
const PROVINCE_ADCODE = {
  '北京': 110000, '天津': 120000, '河北': 130000, '山西': 140000,
  '内蒙古': 150000, '辽宁': 210000, '吉林': 220000, '黑龙江': 230000,
  '上海': 310000, '江苏': 320000, '浙江': 330000, '安徽': 340000,
  '福建': 350000, '江西': 360000, '山东': 370000, '河南': 410000,
  '湖北': 420000, '湖南': 430000, '广东': 440000, '广西': 450000,
  '海南': 460000, '重庆': 500000, '四川': 510000, '贵州': 520000,
  '云南': 530000, '西藏': 540000, '陕西': 610000, '甘肃': 620000,
  '青海': 630000, '宁夏': 640000, '新疆': 650000, '台湾': 710000,
}

// 辅助：求占比（用于侧栏 bar 宽度）
function pctOf(v) {
  const [min, max] = valueRange.value
  if (max === min) return 50
  return Math.round(((v - min) / (max - min)) * 100)
}
</script>

<style scoped>
.geo-map-view {
  display: flex;
  flex-direction: column;
  gap: 14px;
  padding: 0 4px 24px;
}

.geo-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 12px;
}

.geo-title {
  display: flex;
  align-items: center;
  gap: 12px;
}

.geo-icon {
  font-size: 32px;
  filter: drop-shadow(0 2px 4px rgba(37, 99, 235, 0.2));
}

.geo-h1 {
  font-size: 20px;
  font-weight: 700;
  color: var(--text);
  letter-spacing: 0.5px;
}

.geo-sub {
  font-size: 12px;
  color: var(--text-3);
  margin-top: 2px;
}

.geo-breadcrumb {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  color: var(--text-2);
  background: var(--surface-2);
  padding: 6px 12px;
  border-radius: 6px;
  border: 1px solid var(--border);
}

.crumb {
  padding: 2px 8px;
  border-radius: 4px;
}

.crumb.clickable {
  cursor: pointer;
  color: var(--text-3);
  transition: all 0.15s;
}

.crumb.clickable:hover {
  color: var(--primary);
  background: var(--primary-dim);
}

.crumb.active {
  color: var(--primary);
  font-weight: 600;
}

.crumb:not(:last-child)::after {
  content: '›';
  margin-left: 8px;
  color: var(--text-3);
  font-weight: 400;
}

.crumb-back {
  margin-left: 12px;
  color: var(--primary);
  cursor: pointer;
  font-size: 12px;
  padding: 2px 8px;
  border-radius: 4px;
  transition: all 0.15s;
}

.crumb-back:hover {
  background: var(--primary-dim);
}

/* Filter Bar */
.geo-filter-bar {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 16px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  flex-wrap: wrap;
}

.filter-item {
  display: flex;
  align-items: center;
  gap: 6px;
}

.filter-item label {
  font-size: 12px;
  color: var(--text-3);
  font-weight: 600;
}

.filter-input {
  height: 32px;
  padding: 0 10px;
  border: 1px solid var(--border);
  border-radius: 5px;
  background: var(--surface);
  color: var(--text);
  font-size: 13px;
  outline: none;
  transition: all 0.15s;
  font-family: var(--font-sans);
}

.filter-input:focus {
  border-color: var(--primary);
  box-shadow: 0 0 0 2px var(--primary-dim);
}

.date-range {
  display: flex;
  align-items: center;
  gap: 4px;
}

.date-range .dash {
  color: var(--text-3);
}

.btn-primary, .btn-ghost {
  height: 32px;
  padding: 0 14px;
  border: 1px solid transparent;
  border-radius: 5px;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.15s;
  font-family: var(--font-sans);
}

.btn-primary {
  background: var(--primary);
  color: white;
  border-color: var(--primary);
}

.btn-primary:hover {
  filter: brightness(0.92);
}

.btn-ghost {
  background: transparent;
  border-color: var(--border);
  color: var(--text-2);
}

.btn-ghost:hover {
  background: var(--surface-2);
  color: var(--text);
}

/* Main */
.geo-main {
  display: grid;
  grid-template-columns: 1fr 300px;
  gap: 14px;
}

.geo-map-card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 12px;
  /* 优先取 78vh（适配大屏）但不低于 700px（避免小屏太挤） */
  min-height: max(700px, 78vh);
  display: flex;
  flex-direction: column;
}

.map-title {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 13px;
  font-weight: 600;
  color: var(--text);
  padding: 4px 8px 8px;
  border-bottom: 1px solid var(--border);
  margin-bottom: 8px;
}

.map-stat {
  font-size: 12px;
  font-weight: 400;
  color: var(--text-3);
}

.map-stat b {
  color: var(--primary);
  font-weight: 700;
}

.map-chart {
  flex: 1;
  width: 100%;
  min-height: 0;
}

.map-loading {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 12px;
  color: var(--text-3);
  font-size: 13px;
  min-height: 0;
}

.loading-spinner {
  width: 32px;
  height: 32px;
  border: 3px solid var(--surface-2);
  border-top-color: var(--primary);
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

/* Side List */
.geo-side-card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 12px;
  display: flex;
  flex-direction: column;
  max-height: max(700px, 78vh);
}

/* 侧栏图例（取代 ECharts visualMap） */
.side-legend {
  padding: 4px 6px 12px;
  border-bottom: 1px solid var(--border);
  margin-bottom: 10px;
}
.legend-label {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-2);
  margin-bottom: 6px;
}
.legend-bar {
  position: relative;
}
.legend-grad {
  width: 100%;
  height: 8px;
  border-radius: 4px;
  background: linear-gradient(to right, #e0f2fe 0%, #7dd3fc 25%, #0284c7 60%, #075985 85%, #0c4a6e 100%);
}
.legend-ticks {
  display: flex;
  justify-content: space-between;
  margin-top: 4px;
  font-size: 10px;
  color: var(--text-3);
  font-family: var(--font-mono-num);
}

.side-title {
  font-size: 13px;
  font-weight: 700;
  color: var(--text);
  padding: 4px 0 8px;
  border-bottom: 1px solid var(--border);
  margin-bottom: 8px;
}

.side-hint {
  font-size: 11px;
  color: var(--text-3);
  padding: 0 0 8px;
  border-bottom: 1px dashed var(--border);
  margin-bottom: 4px;
}

.side-list {
  flex: 1;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
}

.side-row {
  position: relative;
  display: grid;
  grid-template-columns: 24px 1fr auto;
  align-items: center;
  gap: 10px;
  padding: 8px 10px;
  border-radius: 5px;
  cursor: pointer;
  transition: background 0.15s;
  border: 1px solid transparent;
}

.side-row:hover {
  background: var(--surface-2);
}

.side-row.active {
  background: var(--primary-dim);
  border-color: rgba(var(--primary-rgb), 0.18);
}

.side-row .bar {
  position: absolute;
  left: 8px;
  right: 8px;
  bottom: 2px;
  height: 2px;
  background: linear-gradient(to right, var(--primary) var(--w), transparent var(--w));
  border-radius: 1px;
  opacity: 0.5;
  pointer-events: none;
}

.rank {
  font-size: 12px;
  font-weight: 700;
  font-family: var(--font-mono-num);
  text-align: center;
  color: var(--text-3);
  width: 20px;
  height: 20px;
  line-height: 20px;
  border-radius: 50%;
  background: var(--surface-2);
}

.rank-1 { background: #fde047; color: #713f12; }
.rank-2 { background: #e2e8f0; color: #334155; }
.rank-3 { background: #fed7aa; color: #7c2d12; }

.info {
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.info .name {
  font-size: 13px;
  font-weight: 600;
  color: var(--text);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.info .meta {
  font-size: 11px;
  color: var(--text-3);
  margin-top: 2px;
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.info .range {
  font-family: var(--font-mono-num);
}

.price {
  text-align: right;
}

.price .avg {
  font-size: 13px;
  font-weight: 700;
  color: var(--primary);
  font-family: var(--font-mono-num);
}

.price .avg-sub {
  font-size: 10px;
  color: var(--text-3);
  margin-top: 1px;
}

@media (max-width: 1024px) {
  .geo-main {
    grid-template-columns: 1fr;
  }
  .geo-side-card {
    max-height: 400px;
  }
}
</style>
