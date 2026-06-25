<template>
  <!--
    Minimal GeoMap：只渲染地图本体。
    - 标题区只剩：面包屑 + 统计
    - 没有 filter bar / 侧栏 / KPI（要筛选去"全部数据"）
    - 支持：hover tooltip + 点击下钻 + 面包屑回退
  -->
  <div class="geo-map-view" :class="{ 'is-fullscreen': isFullscreen }">
    <div v-if="breadcrumbs.length" class="map-title">
      <div class="map-title-left">
        <span
          v-for="(c, i) in crumbs"
          :key="i"
          class="crumb"
          :class="{ active: i === crumbs.length - 1, clickable: i < crumbs.length - 1 }"
          @click="i < crumbs.length - 1 && goToCrumb(i)"
        >
          {{ c }}
        </span>
        <span v-if="breadcrumbs.length" class="crumb-back" @click="goBack" title="返回上一级">↩</span>
      </div>
    </div>

    <div class="map-chart-wrap">
      <div ref="chartEl" class="map-chart" v-show="!loading && dataItems.length"></div>
      <div v-if="loading" class="map-loading">
        <div class="loading-spinner"></div>
      </div>
      <EmptyState
        v-if="!loading && dataItems.length === 0"
        icon="🗺️"
        title="该层级暂无数据"
        compact
      />
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onBeforeUnmount, watch, nextTick } from 'vue'
import * as echarts from 'echarts'
import axios from 'axios'
import EmptyState from './EmptyState.vue'
import { registerGovPriceTheme, getGovPriceTheme } from '../composables/useEchartsTheme.js'

const API = import.meta.env.VITE_API_URL || '/api'
const GEO_BASE = '/geo'

// 嵌在父页面里时关掉自身 header（当前 cockpit section title 已承担标题）
const props = defineProps({
  hideHeader: { type: Boolean, default: false },
})

const chartEl = ref(null)
let chart = null

// === State ===
const dataItems = ref([])
const breadcrumbs = ref([])    // [{ label, parent, parent2, adcode }]
const currentName = ref('')
const loading = ref(false)
const displayMode = ref('coverage')   // 当前只读：当前是 coverage；未来可由 prop 注入
const isFullscreen = ref(false)

// === Computed ===
const crumbs = computed(() => breadcrumbs.value.map(b => b.label))

const totalDocs = computed(() => dataItems.value.reduce((s, x) => s + x.count, 0))
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
const countRange = computed(() => {
  if (!dataItems.value.length) return [0, 1]
  const cnts = dataItems.value.map(x => x.count).filter(c => c > 0)
  if (!cnts.length) return [0, 1]
  return [Math.min(...cnts), Math.max(...cnts)]
})

const currentLevel = computed(() => {
  if (breadcrumbs.value.length === 0) return 'province'
  if (breadcrumbs.value.length === 1) return 'city'
  return 'county'
})
const currentMapName = computed(() => {
  if (breadcrumbs.value.length === 0) return 'china-mainland'
  if (breadcrumbs.value.length === 1) {
    return breadcrumbs.value[0].adcode ? String(breadcrumbs.value[0].adcode) : 'china-mainland'
  }
  return breadcrumbs.value[0]?.adcode ? String(breadcrumbs.value[0].adcode) : 'china-mainland'
})

// === Lifecycle ===
onMounted(async () => {
  registerGovPriceTheme()
  await reload()
  window.addEventListener('resize', handleResize)
  if (chartEl.value) {
    resizeObserver = new ResizeObserver(entries => {
      for (const entry of entries) {
        const { width, height } = entry.contentRect
        if (width > 0 && height > 0) {
          if (chart) {
            chart.resize()
          } else if (dataItems.value.length) {
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
function handleResize() { chart?.resize() }

// === API ===
async function reload() {
  const level = currentLevel.value
  const parent = breadcrumbs.value[breadcrumbs.value.length - 1]?.parent
  const parent2 = breadcrumbs.value[breadcrumbs.value.length - 1]?.parent2
  loading.value = true
  try {
    const params = { level }
    if (parent) params.parent = parent
    if (parent2) params.parent2 = parent2
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

// === Map Render ===
// 当前地图的全部 feature 名称（ensureMapLoaded 后填充），用于补齐无数据的 feature
const mapFeatures = ref([])

async function renderMap() {
  await nextTick()
  if (!chartEl.value) return
  const rect = chartEl.value.getBoundingClientRect()
  if (rect.width === 0 || rect.height === 0) {
    requestAnimationFrame(() => chartEl.value && renderMap())
    return
  }
  if (!chart) {
    chart = echarts.init(chartEl.value, getGovPriceTheme())
  }
  const mapName = await ensureMapLoaded(currentMapName.value)
  if (!mapName) return

  // 把 ES 数据归一为地图 feature 名（与 feature.properties.name 对齐）
  // province level：原始名不带后缀；city/county level：以 mapFeatures 为准反查常见后缀。
  const featureNameSet = new Set(mapFeatures.value || [])
  const normalizeName = (raw) => {
    if (currentLevel.value === 'province') {
      return PROVINCE_NAME_MAP[raw] || raw
    }
    if (featureNameSet.has(raw)) return raw
    // 尝试常见后缀：市、区、县、自治县、自治州 等
    const SUFFIXES = ['市', '区', '县', '自治县', '自治州', '盟', '地区']
    for (const s of SUFFIXES) {
      if (featureNameSet.has(raw + s)) return raw + s
    }
    // fallback：prefix 匹配
    for (const fn of mapFeatures.value || []) {
      if (fn.startsWith(raw) || raw.startsWith(fn)) return fn
    }
    return raw
  }
  const normalized = dataItems.value.map(d => {
    const name = normalizeName(d.name)
    return { name, count: d.count, value: d.value, rawName: d.name }
  })
  // 用全部 feature 名构建 data，未匹配的填 null（让 visualMap.outOfRange 生效）
  const featureNames = (mapFeatures.value && mapFeatures.value.length)
    ? mapFeatures.value
    : Array.from(echarts.getMap(mapName)?.geoJson?.features || []).map(f => f?.properties?.name).filter(Boolean)
  const data = (featureNames.length ? featureNames : normalized.map(n => n.name))
    .map(name => {
      const hit = normalized.find(n => n.name === name)
      return hit
        ? {
            name,
            value: displayMode.value === 'coverage' ? hit.count : hit.value,
            _count: hit.count,
            _price: hit.value,
            _rawName: hit.rawName,
          }
        : { name, value: null, _count: 0, _price: 0, _rawName: null }
    })

  const isPrice = displayMode.value === 'price'
  const range = isPrice ? valueRange.value : countRange.value
  // 退化区间保护：max <= min 时强制拉开 1 个单位，避免所有数据点同色
  const vMin = range[0]
  const vMax = range[1] > range[0] ? range[1] : range[0] + 1
  const colorRange = isPrice
    ? ['#fef3c7', '#fde68a', '#fbbf24', '#f97316', '#dc2626', '#7f1d1d']
    : ['#f0fdf4', '#bbf7d0', '#22c55e', '#15803d', '#14532d']

  const option = {
    backgroundColor: 'transparent',
    tooltip: {
      show: false,
    },
    visualMap: {
      show: false,
      min: vMin,
      max: vMax,
      inRange: { color: colorRange },
      // 无数据的 feature 显式置灰（比 inRange 最浅色还浅，避免和数据区混淆）
      outOfRange: { color: '#e5e7eb', colorAlpha: 0.6 },
      calculable: false,
      seriesIndex: 0,
    },
    series: [{
      type: 'map',
      map: mapName,
      roam: false,
      // 让地图填满 canvas：
      // - province level（中国全图）：用 boundingCoords 锁定陆地经纬度范围，
      //   避免默认按 geoJson 海域包围盒渲染导致的底部大片空白
      // - city/county level（省级/市级地图）：用 layoutCenter + layoutSize 按容器缩放
      ...(currentLevel.value === 'province'
        ? { boundingCoords: [[73, 53.5], [137, 18]] }
        : { layoutCenter: ['50%', '50%'], layoutSize: '100%' }),
      label: {
        show: true,
        fontSize: 9,
        color: '#0f172a',
        fontWeight: 500,
        textBorderColor: '#fff',
        textBorderWidth: 2.5,
      },
      labelLayout: { hideOverlap: true },
      itemStyle: { borderColor: '#fff', borderWidth: 1 },
      emphasis: {
        label: { show: true, fontSize: 12, fontWeight: 700, color: '#fff', textBorderColor: '#0f172a', textBorderWidth: 2 },
        itemStyle: { areaColor: '#facc15' },
      },
      select: { label: { show: true, color: '#fff', fontWeight: 700 }, itemStyle: { areaColor: '#f59e0b' } },
      data,
    }],
  }
  chart.setOption(option, true)
  chart.off('click')
  chart.on('click', (params) => {
    if (params.componentType === 'series' && params.seriesType === 'map' && params.data) {
      // params.name 来自地图 feature（如“威海市”），dataItems 里是 ES 名（如“威海”）。
      // 双向宽松匹配：去“市”后缀后相等。
      const stripShi = (s) => s.endsWith('市') ? s.slice(0, -1) : s
      const target = stripShi(params.name)
      const item = dataItems.value.find(d => {
        const candidate = PROVINCE_NAME_MAP[d.name] || d.name
        return stripShi(candidate) === target
      })
      if (item) onRegionClick(item)
    }
  })
}

async function ensureMapLoaded(mapKey) {
  const url = (mapKey === 'china' || mapKey === 'china-mainland') ? `${GEO_BASE}/100000_full.json` : `${GEO_BASE}/${mapKey}_full.json`
  try {
    const resp = await fetch(url)
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`)
    const geo = await resp.json()
    // 过滤掉九段线/南海诸岛（adcode=100000_JD，properties.name 为空）
    if (Array.isArray(geo?.features)) {
      geo.features = geo.features.filter(f => f?.properties?.adcode !== '100000_JD')
    }
    // 不缓存：每次都重新 registerMap（ECharts 覆盖式），保证 filter 生效
    echarts.registerMap(mapKey, geo)
    // 同步 feature 名称列表，供 renderMap 补齐无数据的项
    mapFeatures.value = (geo?.features || [])
      .map(f => f?.properties?.name)
      .filter(Boolean)
    return mapKey
  } catch (e) {
    console.warn(`地图 ${mapKey} 加载失败：`, e)
    if (mapKey !== 'china-mainland') return ensureMapLoaded('china-mainland')
    return null
  }
}

// === Drilldown ===
function onRegionClick(item) {
  if (currentLevel.value === 'province') {
    const adcode = PROVINCE_ADCODE[item.name]
    if (!adcode) {
      console.warn('未找到省份 adcode:', item.name)
      return
    }
    breadcrumbs.value.push({ label: item.name, parent: item.name, parent2: '', adcode })
  } else if (currentLevel.value === 'city') {
    breadcrumbs.value.push({
      label: item.name,
      parent: item.name,
      parent2: breadcrumbs.value[breadcrumbs.value.length - 1].parent,
      adcode: breadcrumbs.value[breadcrumbs.value.length - 1].adcode,
    })
  }
  currentName.value = item.name
  reload()
}

function goBack() {
  if (breadcrumbs.value.length === 0) return
  breadcrumbs.value.pop()
  reload()
}

function goToCrumb(idx) {
  const target = idx - 1
  if (target < 0) breadcrumbs.value = []
  else breadcrumbs.value = breadcrumbs.value.slice(0, target + 1)
  reload()
}

// === Maps ===
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
</script>

<style scoped>
.geo-map-view {
  display: flex;
  flex-direction: column;
  width: 100%;
  height: 100%;
  min-height: 0;
  background: var(--surface);
  border-radius: var(--radius);
  overflow: hidden;
}
.geo-map-view.is-fullscreen {
  position: fixed;
  inset: 0;
  z-index: 50;
  background: var(--bg, #f8fafc);
}

/* 紧凑标题（面包屑 + 统计） */
.map-title {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 12px;
  font-weight: 500;
  color: var(--text-2);
  padding: 8px 12px;
  border-bottom: 1px solid var(--border);
  flex-shrink: 0;
  background: var(--surface-2);
}
.map-title-left {
  display: flex;
  align-items: center;
  gap: 4px;
}
.crumb {
  padding: 1px 6px;
  border-radius: 3px;
  font-size: 12px;
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
  color: var(--text);
  font-weight: 600;
}
.crumb:not(:last-of-type)::after {
  content: '›';
  margin-left: 4px;
  color: var(--text-3);
  font-weight: 400;
}
.crumb-back {
  margin-left: 6px;
  padding: 0 6px;
  height: 20px;
  display: inline-flex;
  align-items: center;
  background: var(--primary-dim);
  color: var(--primary);
  border-radius: 3px;
  cursor: pointer;
  font-size: 12px;
  font-weight: 600;
  transition: all 0.15s;
}
.crumb-back:hover {
  background: var(--primary);
  color: white;
}
.map-title-right {
  font-size: 11px;
  color: var(--text-3);
  font-family: var(--font-mono-num);
}
.map-title-right b {
  color: var(--text);
  font-weight: 700;
}

/* 地图区 */
.map-chart-wrap {
  flex: 1;
  min-height: 0;
  display: flex;
  align-items: stretch;
  justify-content: center;
  position: relative;
}
.map-chart {
  width: 100%;
  height: 100%;
}
.map-loading {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--text-3);
}
.loading-spinner {
  width: 28px;
  height: 28px;
  border: 3px solid var(--surface-2);
  border-top-color: var(--primary);
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}
@keyframes spin {
  to { transform: rotate(360deg); }
}
</style>
