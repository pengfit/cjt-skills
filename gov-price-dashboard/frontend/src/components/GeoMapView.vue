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
      <!-- 主搜索框：产品名 -->
      <div class="search-box" :class="{ 'has-text': filterBreed }">
        <span class="search-icon">🔍</span>
        <input
          v-model="filterBreed"
          class="search-input"
          placeholder="输产品名查各省价（如：钢筋 / 水泥 / 砼）"
          @keyup.enter="reload"
        />
        <button
          v-if="filterBreed"
          class="search-clear"
          @click="filterBreed = ''; reload()"
          title="清除"
        >✕</button>
        <button class="search-submit" @click="reload" title="搜索 (Enter)">搜索</button>
      </div>
      <div class="filter-item">
        <label>日期</label>
        <div class="date-range">
          <input v-model="dateFrom" class="filter-input" type="date" @change="reload" />
          <span class="dash">—</span>
          <input v-model="dateTo" class="filter-input" type="date" @change="reload" />
        </div>
      </div>
      <!-- 模式切换 -->
      <div class="mode-toggle">
        <button
          class="mode-btn"
          :class="{ active: displayMode === 'coverage' }"
          @click="setMode('coverage')"
          :disabled="!dataItems.length"
          title="数据覆盖热力图（默认）"
        >📦 数据量</button>
        <button
          class="mode-btn"
          :class="{ active: displayMode === 'price' }"
          @click="setMode('price')"
          :disabled="!dataItems.length"
          title="价格热力图"
        >💰 价格</button>
      </div>
      <button
        class="btn-refresh"
        @click="reload"
        :class="{ spinning: loading }"
        :disabled="loading"
        title="刷新数据 (Enter)"
      >🔄</button>
      <button class="btn-ghost" v-if="crumbs.length > 1" @click="goBack">← 返回</button>
    </div>

    <!-- ============ Main Content: Map + Side List ============ -->
    <div class="geo-main">
      <!-- Map -->
      <div class="geo-map-card">
        <div class="map-title">
          <span>{{ crumbs.join(' / ') }} · {{ displayMode === 'coverage' ? '数据覆盖热力图' : '价格热力图' }}</span>
          <span class="map-stat" v-if="!loading">
            <template v-if="displayMode === 'coverage'">
              共 <b>{{ dataItems.length }}</b> 个地区 · <b>{{ totalDocs.toLocaleString() }}</b> 条记录
            </template>
            <template v-else>
              共 <b>{{ dataItems.length }}</b> 个地区 · 平均价 <b>{{ overallAvg.toLocaleString() }}</b> 元
            </template>
          </span>
        </div>
        <div class="map-chart-wrap">
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
      </div>

      <!-- Side List -->
      <div class="geo-side-card">
        <!-- 图例：根据 displayMode 切换 -->
        <div class="side-legend">
          <div class="legend-label">
            {{ displayMode === 'coverage' ? '数据量色阶' : '价格色阶' }}
            <span class="legend-unit">{{ displayMode === 'coverage' ? '（条）' : '（元）' }}</span>
          </div>
          <div class="legend-bar">
            <div class="legend-grad" :class="{ 'legend-grad-price': displayMode === 'price' }"></div>
            <div class="legend-ticks">
              <template v-if="displayMode === 'coverage'">
                <span>{{ formatCount(countRange[1]) }}</span>
                <span>{{ formatCount((countRange[0] + countRange[1]) / 2) }}</span>
                <span>{{ formatCount(countRange[0]) }}</span>
              </template>
              <template v-else>
                <span>{{ formatPrice(valueRange[1]) }}</span>
                <span>{{ formatPrice((valueRange[0] + valueRange[1]) / 2) }}</span>
                <span>{{ formatPrice(valueRange[0]) }}</span>
              </template>
            </div>
          </div>
        </div>
        <div class="side-title">
          {{ displayMode === 'coverage' ? '📊 数据量排行' : '💰 价格排行' }}
          TOP {{ Math.min(dataItems.length, 20) }}
        </div>
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
              <template v-if="displayMode === 'coverage'">
                <div class="avg">{{ item.count.toLocaleString() }}</div>
                <div class="avg-sub">条记录</div>
              </template>
              <template v-else>
                <div class="avg">¥{{ item.value.toLocaleString() }}</div>
                <div class="avg-sub">均价</div>
              </template>
            </div>
            <div class="bar" :style="`--w: ${pctOf(displayMode === 'coverage' ? item.count : item.value)}%`"></div>
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
import EmptyState from './EmptyState.vue'
import { registerGovPriceTheme, getGovPriceTheme } from '../composables/useEchartsTheme.js'

const API = import.meta.env.VITE_API_URL || '/api'
const GEO_BASE = '/geo'

const chartEl = ref(null)
let chart = null

// === Filters ===
const filterBreed = ref('')
const dateFrom = ref('')
const dateTo = ref('')

// === Display Mode ===
// coverage：默认以“数据量”热力（看哪省数据全/新）
// price：有筛选时以“均价”热力（看同材料不同省价格）
const displayMode = ref('coverage')  // 'coverage' | 'price'
const hasMaterialFilter = computed(() => !!filterBreed.value)
// 选了产品名筛选后自动切到价格模式
watch(filterBreed, () => {
  displayMode.value = hasMaterialFilter.value ? 'price' : 'coverage'
})

// === Drilldown state ===
const breadcrumbs = ref([])   // 面包屑栈：[{ level, parent, parent2, label }]
const dataItems = ref([])     // 当前层级的地区聚合
const currentName = ref('')   // 当前 hover/click 选中的地区
const loading = ref(false)

// === Computed ===
const crumbs = computed(() => breadcrumbs.value.map(b => b.label))
// TOP 20 根据 displayMode 排序
const topN = computed(() => {
  const list = [...dataItems.value]
  if (displayMode.value === 'coverage') {
    list.sort((a, b) => b.count - a.count)
  } else {
    list.sort((a, b) => b.value - a.value)
  }
  return list.slice(0, 20)
})
const overallAvg = computed(() => {
  if (!dataItems.value.length) return 0
  const sum = dataItems.value.reduce((s, x) => s + x.value * x.count, 0)
  const cnt = dataItems.value.reduce((s, x) => s + x.count, 0)
  return cnt > 0 ? Math.round(sum / cnt) : 0
})
const totalDocs = computed(() => dataItems.value.reduce((s, x) => s + x.count, 0))
// 价格范围
const valueRange = computed(() => {
  if (!dataItems.value.length) return [0, 1]
  const vals = dataItems.value.map(x => x.value).filter(v => v > 0)
  if (!vals.length) return [0, 1]
  return [Math.min(...vals), Math.max(...vals)]
})
// 文档数范围
const countRange = computed(() => {
  if (!dataItems.value.length) return [0, 1]
  const cnts = dataItems.value.map(x => x.count).filter(c => c > 0)
  if (!cnts.length) return [0, 1]
  return [Math.min(...cnts), Math.max(...cnts)]
})

// 侧栏图例价格格式化（Y轴刻度：0, 100, 1.2k, 15k, 1.2M）
function formatPrice(v) {
  const n = Number(v)
  if (n >= 10000) return Math.round(n / 1000) + 'k'
  if (n >= 1000) return (n / 1000).toFixed(1) + 'k'
  if (n >= 1) return Math.round(n).toString()
  return n.toFixed(2)
}

// 侧栏图例数据量格式化
function formatCount(v) {
  const n = Number(v)
  if (n >= 100000) return Math.round(n / 10000) + '万'
  if (n >= 10000) return (n / 10000).toFixed(1) + '万'
  if (n >= 1000) return (n / 1000).toFixed(1) + 'k'
  return Math.round(n).toString()
}

// 手动切换模式（覆盖自动选择）
function setMode(m) {
  displayMode.value = m
}

// === Lifecycle ===
onMounted(async () => {
  registerGovPriceTheme()
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
async function reload() {
  const level = currentLevel.value
  const parent = breadcrumbs.value[breadcrumbs.value.length - 1]?.parent
  const parent2 = breadcrumbs.value[breadcrumbs.value.length - 1]?.parent2
  loading.value = true
  try {
    const params = { level }
    if (parent) params.parent = parent
    if (parent2) params.parent2 = parent2
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
  // 根据 displayMode 决定 ECharts 的主数值：
  //   - coverage: 主数值 = count（数据量），color 生调用 countRange
  //   - price:    主数值 = value（均价），color 生调用 valueRange
  const data = dataItems.value
    .filter(d => d.value > 0 || d.count > 0)
    .map(d => ({
      name: currentLevel.value === 'province' ? (PROVINCE_NAME_MAP[d.name] || d.name) : d.name,
      value: displayMode.value === 'coverage' ? d.count : d.value,
      // 保留原始字段供 tooltip 使用
      _count: d.count,
      _price: d.value,
      _min: d.min,
      _max: d.max,
    }))
  // visualMap 范围（根据 displayMode 决定）
  const isPrice = displayMode.value === 'price'
  const range = isPrice ? valueRange.value : countRange.value
  const min = range[0]
  const max = range[1]
  // 数据量模式用浅蓝→深蓝渐变，价格模式用更深的蓝渐变
  const colorRange = isPrice
    ? ['#e0f2fe', '#7dd3fc', '#0284c7', '#075985', '#0c4a6e']
    : ['#f1f5f9', '#93c5fd', '#3b82f6', '#1d4ed8', '#1e3a8a']
  const option = {
    tooltip: {
      trigger: 'item',
      formatter: (p) => {
        if (p.seriesType === 'map') {
          const c = p.data?._count
          const v = p.data?._price
          if (!c && !v) return `${p.name}：暂无数据`
          const lines = [`<b>${p.name}</b>`]
          if (v) {
            lines.push(`均价：<b style="color:#2563eb">¥${Number(v).toLocaleString()}</b>`)
            if (p.data?._min && p.data?._max) {
              lines.push(`区间：¥${p.data._min} ~ ¥${p.data._max}`)
            }
          }
          if (c) {
            lines.push(`数据量：${Number(c).toLocaleString()} 条`)
          }
          lines.push('', '💡 点击下钻')
          return lines.join('<br/>')
        }
        return p.name
      },
    },
    // 隐藏的 visualMap 仅负责上色（UI 由侧栏自定义图例负责）
    visualMap: {
      show: false,
      min, max,
      inRange: { color: colorRange },
      calculable: false,
      seriesIndex: 0,
    },
    series: [
      {
        name: '均价',
        type: 'map',
        map: mapName,
        roam: true,
        zoom: 1.0,
        label: { show: true, fontSize: 9, color: '#0f172a' },
        // labelLayout 隐藏重叠的 label（解决海南/南每诸岛等省份名重复出现的问题）
        labelLayout: { hideOverlap: true },
        itemStyle: {
          borderColor: '#ffffff',
          borderWidth: 1,
        },
        emphasis: {
          label: { show: true, fontSize: 11, fontWeight: 700 },
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

/* 主搜索框（产品名） */
.search-box {
  display: flex;
  align-items: center;
  height: 40px;
  flex: 1;
  min-width: 320px;
  max-width: 480px;
  padding: 0 4px 0 12px;
  background: var(--surface);
  border: 1.5px solid var(--border);
  border-radius: 8px;
  transition: all 0.15s;
}
.search-box:hover {
  border-color: var(--primary);
}
.search-box:focus-within {
  border-color: var(--primary);
  box-shadow: 0 0 0 3px var(--primary-dim);
}
.search-box.has-text {
  border-color: var(--primary);
}
.search-icon {
  font-size: 16px;
  margin-right: 8px;
  color: var(--text-3);
  pointer-events: none;
}
.search-input {
  flex: 1;
  height: 100%;
  border: none;
  background: transparent;
  color: var(--text);
  font-size: 14px;
  outline: none;
  font-family: var(--font-sans);
  min-width: 0;
}
.search-input::placeholder {
  color: var(--text-3);
}
.search-clear {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  border: none;
  background: var(--surface-2);
  color: var(--text-2);
  border-radius: 50%;
  cursor: pointer;
  font-size: 12px;
  margin-right: 6px;
  transition: all 0.15s;
}
.search-clear:hover {
  background: var(--primary);
  color: white;
}
.search-submit {
  height: 30px;
  padding: 0 16px;
  border: none;
  background: var(--primary);
  color: white;
  border-radius: 6px;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: filter 0.15s;
  font-family: var(--font-sans);
}
.search-submit:hover {
  filter: brightness(0.92);
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

/* 刷新按钮：仅图标，圆形，匹配搜索框高度 */
.btn-refresh {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 40px;
  height: 40px;
  border: 1.5px solid var(--border);
  background: var(--surface);
  color: var(--text-2);
  border-radius: 8px;
  font-size: 18px;
  cursor: pointer;
  transition: all 0.2s;
  font-family: var(--font-sans);
  flex-shrink: 0;
}
.btn-refresh:hover:not(:disabled) {
  border-color: var(--primary);
  color: var(--primary);
  background: var(--primary-dim);
}
.btn-refresh:disabled {
  opacity: 0.5;
  cursor: wait;
}
.btn-refresh.spinning {
  animation: spin 0.8s linear infinite;
  color: var(--primary);
  border-color: var(--primary);
}

/* 模式切换 */
.mode-toggle {
  display: inline-flex;
  border: 1px solid var(--border);
  border-radius: 5px;
  overflow: hidden;
  background: var(--surface-2);
}
.mode-btn {
  height: 32px;
  padding: 0 12px;
  border: none;
  background: transparent;
  color: var(--text-2);
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.15s;
  font-family: var(--font-sans);
}
.mode-btn:not(:last-child) {
  border-right: 1px solid var(--border);
}
.mode-btn:hover:not(:disabled) {
  background: var(--surface);
  color: var(--text);
}
.mode-btn.active {
  background: var(--primary);
  color: white;
}
.mode-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
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

.map-chart-wrap {
  flex: 1;
  min-height: 0;
  display: flex;
  align-items: center;
  justify-content: center;
}
.map-chart {
  width: 100%;
  /* 强制 chart 比例 1.23:1（中国地图自然比例） */
  aspect-ratio: 1.23 / 1;
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
  background: linear-gradient(to right, #f1f5f9 0%, #93c5fd 30%, #3b82f6 70%, #1e3a8a 100%);
}
.legend-grad-price {
  background: linear-gradient(to right, #e0f2fe 0%, #7dd3fc 25%, #0284c7 60%, #075985 85%, #0c4a6e 100%);
}
.legend-unit {
  font-size: 10px;
  color: var(--text-3);
  font-weight: 400;
  margin-left: 4px;
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
