<template>
  <div class="dist-page">
    <!-- 页面 header -->
    <PageHeader
      variant="flat"
      title="价格分布"
      subtitle="价格区间分布 / 省份分布 / 主体区间占比，多维度看全国材料价格结构"
    ><template #icon>📈</template></PageHeader>

    <!-- 统计概览 (2026-07-23: /api/stats/overview 下架后不再读 overview.*，改从 rangeData 派生) -->
    <div class="dist-overview-stats">
      <StatCard
        icon="📊"
        label="条价格数据"
        :value="totalCount"
      />
      <StatCard
        icon="📐"
        label="主体区间 200-500元"
        :value="dominantPct + '%'"
        :format="'raw'"
      />
      <StatCard
        icon="💰"
        label="加权平均价格(从区间均价格合)"
        :value="weightedAvgPrice"
        unit="元"
      />
    </div>

    <!-- Chart cards -->
    <div class="dist-cards">
      <div class="dist-card chart-card wide">
        <div class="card-title">价格区间分布</div>
        <div id="rangeBarChart" style="width:100%;height:280px;"></div>
      </div>
    </div>

    <div class="dist-cards">
      <div class="dist-card chart-card wide" style="min-height:700px; padding: 20px;">
        <div class="card-title">各省价格分布</div>
        <div class="province-chart-grid">
          <div
            v-for="p in provinceData"
            :key="p.province"
            class="province-chart-cell province-chart-cell-clickable"
            :data-province="p.province"
            :style="{ '--province-color': getProvinceColor(p.province) }"
            :title="`点击查看 ${p.province} 全部数据 →`"
            @click="goProvince(p.province)"
            role="button"
            tabindex="0"
            @keyup.enter="goProvince(p.province)"
          >
            <div class="province-chart-header">
              <span class="province-dot"></span>
              <div class="province-chart-title">{{ p.province }}</div>
            </div>
            <div class="province-chart-stats">
              <span class="province-count">{{ fmt.int(p.count) }}</span>
            </div>
            <div :id="'provinceChart_' + p.province" class="province-chart-box"></div>
          </div>
        </div>
      </div>
    </div>

    <SkeletonChart v-if="loading" :height="300" variant="bar" :bars="12" :grid-lines="4" :y-labels="4" />
    <ErrorState v-if="error" :title="'加载失败'" :message="error" compact :on-retry="loadData" />
  </div>
</template>

<script setup>
import PageHeader from './PageHeader.vue'
import StatCard from './StatCard.vue'
import ErrorState from './ErrorState.vue'
import SkeletonChart from './SkeletonChart.vue'
import { ref, onMounted, nextTick, watch, onUnmounted, computed } from 'vue'
import { useRouter } from 'vue-router'
import axios from 'axios'
import { getGovPriceTheme, registerGovPriceTheme } from '../composables/useEchartsTheme'
import { useEcharts } from '../composables/useEcharts'
import { useFormatNumber } from '../composables/useFormatNumber.js'
import { markRaw } from 'vue'

onUnmounted(() => {
  mountedRef.value = false
  rangeBarIns.value?.dispose()
  if (observer) { observer.disconnect(); observer = null }
})

const props = defineProps({
  keyword: { type: String, default: '' },
  province: { type: String, default: '' },
  city: { type: String, default: '' },
})

const API = import.meta.env.VITE_API_URL || '/api'
const router = useRouter()
// D.2026-07-12 统一数字格式化
const fmt = useFormatNumber()

// 底部省小图点击下钻到全部数据页(B.2026-07-12 P0)
function goProvince(prov) {
  if (!prov) return
  router.push({ path: '/list', query: { province: prov } })
}
const loading = ref(false)
const error = ref('')
const rangeData = ref([])
const provinceData = ref([])
const overview = ref({ total_docs: 0, total_provinces: 0, total_cities: 0, avg_price: 0 })
const provinceChartIns = {}  // store province chart instances for export
const rangeBarIns = ref(null)

const dominantPct = computed(() => {
  if (!rangeData.value.length) return '0'
  const total = rangeData.value.reduce((s, r) => s + r.count, 0)
  const dominant = rangeData.value.reduce((a, b) => a.count > b.count ? a : b)
  return total ? (dominant.count / total * 100).toFixed(0) : '0'
})

// 2026-07-23: /api/stats/overview 下架后,avg_price 改为从 rangeData 区间均价格合得到
const weightedAvgPrice = computed(() => {
  if (!rangeData.value.length) return 0
  let totalCount = 0, weightedSum = 0
  for (const r of rangeData.value) {
    totalCount += r.count
    weightedSum += r.count * (r.avg_price || 0)
  }
  return totalCount ? Math.round(weightedSum / totalCount) : 0
})

const provinceHeatIns = ref(null)
const mountedRef = ref(true)

watch(() => [props.province, props.city], () => {
  if (mountedRef.value) loadData()
}, { deep: true })

const RANGE_COLORS = ['#6dd5ed','#4facfe','#6a85f5','#9b59b6','#7c3aed','#b45309','#f97316','#dc2626','#e11d48','#06b6d4']

const PROVINCE_COLORS = {
  '辽宁': '#4a90d9', '江苏': '#50c5a8', '新疆': '#f5a623', '陕西': '#e85555',
  '江西': '#9b59b6', '黑龙江': '#34495e', '青海': '#e67e22', '山东': '#1abc9c',
  '上海': '#3498db', '吉林': '#95a5a6', '广东': '#e74c3c', '北京': '#2ecc71',
  '海南': '#f39c12', '重庆': '#c0392b', '宁夏': '#7f8c8d', '湖南': '#8e44ad',
  '内蒙古': '#16a085', '河南': '#d35400', '贵州': '#cf5c2a',
}
let _pIdx = 0
const _pList = Object.values(PROVINCE_COLORS)
function getProvinceColor(p) {
  if (PROVINCE_COLORS[p]) return PROVINCE_COLORS[p]
  PROVINCE_COLORS[p] = _pList[_pIdx % _pList.length]
  _pIdx++
  return PROVINCE_COLORS[p]
}

function getRangeColor(range) {
  const idx = rangeData.value.findIndex(r => r.range === range)
  return idx >= 0 ? RANGE_COLORS[idx] : '#475569'
}

const totalCount = ref(0)
function getPct(count) {
  if (!totalCount.value) return 0
  return ((count / totalCount.value) * 100).toFixed(1)
}

// Export chart as PNG
async function exportChart(chartId) {
  const el = document.getElementById(chartId)
  if (!el) return
  const echarts = await useEcharts()
  const chart = echarts.getInstanceByDom(el)
  if (!chart) return
  const url = chart.getDataURL({ type: 'png', pixelRatio: 2, backgroundColor: '#f8fafc' })
  const a = document.createElement('a')
  a.href = url
  a.download = `${chartId}_${new Date().toISOString().slice(0, 10)}.png`
  a.click()
}

function exportAllCharts() {
  exportChart('rangeBarChart')
  setTimeout(() => {
    for (const province of Object.keys(provinceChartIns || {})) {
      exportChart('provinceChart_' + province)
    }
  }, 300)
}

// Toggle fullscreen for a chart container
function toggleFullscreen(chartId) {
  const el = document.getElementById(chartId)
  if (!el) return
  if (!document.fullscreenElement) {
    el.requestFullscreen?.() || el.webkitRequestFullscreen?.()
  } else {
    document.exitFullscreen?.() || document.webkitExitFullscreen?.()
  }
}

async function loadData() {
  loading.value = true
  error.value = ''
  try {
    // 2026-07-23: /api/stats/overview 整接口下架,overviewData 来源不再走该路径;
    // provinceData 留空,本页后续实际不再展示省份列表子表
    // 2026-07-23: /distribution 页改走 NORM 专属路径(/api/norm/*),与其他页分层
    const distRes = await axios.get(`${API}/norm/price-distribution`)

    rangeData.value = distRes.data?.data || []
    totalCount.value = rangeData.value.reduce((s, r) => s + r.count, 0) || 0
    provinceData.value = []
    overview.value = null
    if (provinceData.value.length) {
      const provNames = provinceData.value.map(p => p.province)
      const rangeRes = await axios.get(`${API}/norm/province-ranges`, {
        params: { provinces: provNames.join(",") }
      })
      const rangeMap = rangeRes.data?.data || {}
      provinceData.value.forEach(p => {
        p.ranges = rangeMap[p.province] || []
      })
    }

    await nextTick()
    await new Promise(r => setTimeout(r, 50))
    renderRangeBar()
    observeCells()
  } catch (e) {
    error.value = '加载失败：' + (e.message || '网络错误')
  } finally {
    loading.value = false
  }
}

async function renderRangeBar() {
  const el = document.getElementById('rangeBarChart')
  if (!el || !rangeData.value.length) return
  await registerGovPriceTheme()
  const echarts = await useEcharts()
  if (rangeBarIns.value) { rangeBarIns.value.dispose(); rangeBarIns.value = null }
  const chart = markRaw(echarts.init(el, getGovPriceTheme()))
  rangeBarIns.value = chart

  const sorted = [...rangeData.value]
  const labels = sorted.map(r => r.range)
  const counts = sorted.map(r => r.count)
  const colors = sorted.map(r => getRangeColor(r.range))

  chart.setOption({
    tooltip: {
      trigger: 'axis',
      backgroundColor: 'rgba(255,255,255,0.98)',
      borderColor: '#cbd5e1',
      textStyle: { color: '#0f172a', fontSize: 12 },
      formatter: params => {
        const p = params[0]
        return `<b>${p.name}</b><br/>数量: <b style="color:#2563eb">${fmt.int(p.value)}</b> 条<br/>占比: <b>${fmt.pct(getPct(p.value))}</b>`
      }
    },
    grid: { left: '8%', right: '4%', bottom: '12%', top: '12%', containLabel: true },
    xAxis: {
      type: 'category', data: labels,
      axisLabel: { color: '#475569', fontSize: 10, rotate: 40, interval: 0 },
      axisLine: { lineStyle: { color: '#cbd5e1' } },
      axisTick: { show: false }
    },
    yAxis: {
      name: '产品数量', nameTextStyle: { color: '#64748b', fontSize: 11, padding: [0, 0, 0, 8] },
      type: 'value',
      axisLabel: { color: '#64748b', fontSize: 10, overflow: 'truncate', width: 50 },
      splitLine: { lineStyle: { color: '#e2e8f0', type: 'dashed' } }
    },
    series: [{
      type: 'bar', data: counts, colorBy: 'data',
      itemStyle: { color: (p) => colors[p.dataIndex] },
      barMaxWidth: 50,
      label: {
        show: true, position: 'top',
        color: '#0f172a', fontSize: 11, fontWeight: '700',
        formatter: p => p.value >= 1000 ? (p.value/1000).toFixed(0)+'k' : p.value
      }
    }],
  }, true)
  window.addEventListener('resize', async () => {
    rangeBarIns.value?.resize()
    provinceHeatIns.value?.resize()
    // resize all lazy-rendered province charts
    const echarts = await useEcharts()
    renderedSet.value.forEach(province => {
      const el = document.getElementById('provinceChart_' + province)
      if (el) {
        const inst = echarts.getInstanceByDom(el)
        inst?.resize()
      }
    })
  })
}

const renderedSet = ref(new Set())
let observer = null

function observeCells() {
  if (observer) observer.disconnect()
  const container = document.querySelector('.dist-page')
  const cells = document.querySelectorAll('.province-chart-cell')
  const root = container || null
  observer = new IntersectionObserver((entries) => {
    entries.forEach(entry => {
      if (entry.isIntersecting) {
        const prov = entry.target.dataset.province
        if (prov && !renderedSet.value.has(prov)) {
          renderedSet.value.add(prov)
          renderOneProvince(prov)
        }
      }
    })
  }, { root, rootMargin: '50px', threshold: 0.01 })
  cells.forEach(cell => observer.observe(cell))
}

async function renderOneProvince(province) {
  const p = provinceData.value.find(p => p.province === province)
  if (!p) return
  const el = document.getElementById('provinceChart_' + province)
  if (!el) return
  await registerGovPriceTheme()
  const echarts = await useEcharts()
  const chart = markRaw(echarts.init(el, getGovPriceTheme()))
  provinceChartIns[province] = chart
  const validRanges = p.ranges.filter(r => r.count)
  if (!validRanges.length) return

  const labels = validRanges.map(r => r.range)
  const values = validRanges.map(r => r.count)
  const colors = validRanges.map(r => {
    const idx = rangeData.value.findIndex(rng => rng.range === r.range)
    return RANGE_COLORS[idx] || '#475569'
  })

  chart.setOption({
    backgroundColor: 'transparent',
    grid: { left: '3%', right: '3%', bottom: '16%', top: '4%', containLabel: true },
    tooltip: {
      trigger: 'axis',
      backgroundColor: 'rgba(255,255,255,0.98)', borderColor: '#cbd5e1',
      textStyle: { color: '#0f172a', fontSize: 10 },
      formatter: params => {
        const p = params[0]
        const total = values.reduce((s, v) => s + v, 0)
        const pct = total ? ((p.value / total) * 100).toFixed(1) : '0'
        return `<b>${p.name}</b><br/>数量: <b style="color:#2563eb">${fmt.int(p.value)}</b> 条<br/>占比: <b>${fmt.pct(pct)}</b><br/>${province} 总量: <b>${fmt.int(p.count || total)}</b>`
      },
      formatter: p => `<b>${p.name}</b><br/>数量: <b style="color:#2563eb">${fmt.int(p.value)}</b>`
    },
    xAxis: {
      type: 'category',
      data: labels,
      axisLabel: { color: '#475569', fontSize: 8, rotate: 30, interval: 0 },
      axisLine: { lineStyle: { color: '#cbd5e1' } },
      axisTick: { show: false },
    },
    yAxis: {
      type: 'value', show: false,
      splitLine: { show: false }
    },
    series: [{
      type: 'bar',
      data: values,
      colorBy: 'data',
      itemStyle: { color: (p) => colors[p.dataIndex], borderRadius: [2, 2, 0, 0] },
      barMaxWidth: 18,
      label: {
        show: true, position: 'top',
        color: '#0f172a', fontSize: 8, fontWeight: '700',
        formatter: p => p.value >= 1000 ? (p.value/1000).toFixed(0)+'k' : p.value
      }
    }],
  })
  setTimeout(() => chart.resize(), 60)
}

onMounted(() => { mountedRef.value = true; loadData() })
</script>

<style scoped>
.dist-page {
  display: flex;
  flex-direction: column;
  gap: 16px;
  padding: 16px 20px 60px;
  min-height: 100vh;
  background: var(--bg);
  box-sizing: border-box;
  padding-top: 16px;
}


/* 统计概览卡片（已迁移至 StatCard） */
.dist-overview-stats {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
  margin-top: 16px;
  margin-bottom: 16px;
}

.dist-cards {
  display: grid;
  grid-template-columns: 1fr;
  gap: 16px;
}

.dist-card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 14px;
  padding: 18px 20px;
  box-shadow: var(--shadow);
}

.dist-card.wide {
  grid-column: 1 / -1;
}

.card-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-3);
  margin-bottom: 12px;
}

.province-chart-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  grid-auto-rows: 260px;
  gap: 10px;
}

.province-chart-cell {
  background: var(--surface);
  border: 1px solid var(--border);
  border-left: 3px solid var(--province-color, var(--primary));
  border-radius: 10px;
  padding: 10px;
  display: flex;
  flex-direction: column;
  gap: 4px;
  transition: all 0.3s ease;
  box-shadow: var(--shadow-sm);
  overflow: visible;
  height: 260px;
  position: relative;
}

.province-chart-cell:hover {
  transform: translateY(-2px);
  border-color: var(--province-color, var(--primary));
  box-shadow: var(--shadow-lg);
}

/* 底部省小图 → 可点击下钻(B.2026-07-12 P0) */
.province-chart-cell-clickable {
  cursor: pointer;
}
.province-chart-cell-clickable:hover {
  background: rgba(var(--primary-rgb), 0.04);
  border-color: var(--province-color, var(--primary));
  box-shadow: var(--shadow-md), 0 0 0 1px var(--province-color, var(--primary));
}
.province-chart-cell-clickable:active {
  transform: translateY(0);
}
.province-chart-cell-clickable:focus-visible {
  outline: none;
  box-shadow: 0 0 0 2px var(--primary);
}
.province-chart-cell-clickable::after {
  content: '→';
  position: absolute;
  right: 8px; bottom: 6px;
  font-size: 12px;
  color: var(--text-3);
  opacity: 0;
  transition: opacity 0.18s;
}
.province-chart-cell-clickable:hover::after { opacity: 0.7; }

.province-chart-header {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}

.province-chart-stats {
  display: flex;
  align-items: baseline;
  gap: 10px;
  flex-shrink: 0;
  padding-bottom: 6px;
  border-bottom: 1px solid #e2e8f0;
}

.province-count {
  font-size: 15px;
  font-weight: 800;
  font-family: ui-monospace, 'SF Mono', Consolas, 'Liberation Mono', monospace;
  color: var(--province-color, var(--primary));
  text-shadow: none;
}

.province-avg {
  font-size: 11px;
  color: var(--text-3);
  font-weight: 400;
}

.province-chart-box {
  width: 100%;
  height: 200px;
  min-height: 200px;
}
</style>
