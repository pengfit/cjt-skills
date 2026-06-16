<template>
  <div class="dist-page">
    <!-- 统计概览 -->
    <div class="dist-overview-stats">
      <div class="ov-stat">
        <span class="ov-icon">📊</span>
        <div class="ov-body">
          <div class="ov-value">{{ overview.total_docs.toLocaleString() }}</div>
          <div class="ov-label">条价格数据</div>
        </div>
      </div>
      <div class="ov-divider"></div>
      <div class="ov-stat">
        <span class="ov-icon">🌍</span>
        <div class="ov-body">
          <div class="ov-value">{{ overview.total_provinces }} 省 / {{ overview.total_cities }} 城</div>
          <div class="ov-label">覆盖范围</div>
        </div>
      </div>
      <div class="ov-divider"></div>
      <div class="ov-stat">
        <span class="ov-icon">💰</span>
        <div class="ov-body">
        </div>
      </div>
      <div class="ov-divider"></div>
      <div class="ov-stat">
        <span class="ov-icon">📐</span>
        <div class="ov-body">
          <div class="ov-value">{{ dominantPct }}%</div>
          <div class="ov-label">主体区间 200-500元</div>
        </div>
      </div>
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
            class="province-chart-cell"
            :data-province="p.province"
            :style="{ '--province-color': getProvinceColor(p.province) }"
          >
            <div class="province-chart-header">
              <span class="province-dot"></span>
              <div class="province-chart-title">{{ p.province }}</div>
            </div>
            <div class="province-chart-stats">
              <span class="province-count">{{ p.count.toLocaleString() }}</span>
            </div>
            <div :id="'provinceChart_' + p.province" class="province-chart-box"></div>
          </div>
        </div>
      </div>
    </div>

    <!-- Range table -->
    <div class="dist-card table-card">
      <div class="card-title">价格区间明细</div>
      <table class="dist-table">
        <thead>
          <tr>
            <th>价格区间</th>
            <th>产品数量</th>
            <th>占比</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="item in rangeData" :key="item.range">
            <td><span class="range-badge">{{ item.range }}</span></td>
            <td>{{ item.count.toLocaleString() }}</td>
            <td>
              <div class="pct-bar-wrap">
                <div class="pct-bar" :style="{ width: getPct(item.count) + '%', background: getRangeColor(item.range) }"></div>
                <span class="pct-label">{{ getPct(item.count) }}%</span>
              </div>
            </td>

          </tr>
        </tbody>
      </table>
    </div>

    <div v-if="loading" class="dist-loading">加载中...</div>
    <ErrorState v-if="error" :title="'加载失败'" :message="error" compact :on-retry="loadData" />
  </div>
</template>

<script setup>
import ErrorState from './ErrorState.vue'
import { ref, onMounted, nextTick, watch, onUnmounted, computed } from 'vue'
import axios from 'axios'
import { getGovPriceTheme } from '../composables/useEchartsTheme'
import { markRaw } from 'vue'
import * as echarts from 'echarts'

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


const highPricePct = computed(() => {
  if (!rangeData.value.length) return '0'
  const total = rangeData.value.reduce((s, r) => s + r.count, 0)
  const high = rangeData.value
    .filter(r => ['3000-4000','4000-5000','>5000'].includes(r.range))
    .reduce((s, r) => s + r.count, 0)
  return total ? (high / total * 100).toFixed(1) : '0'
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

function getRangePct(count, total) {
  if (!total) return 0
  return (count / total) * 100
}

// Export chart as PNG
function exportChart(chartId) {
  const el = document.getElementById(chartId)
  if (!el) return
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
    const [distRes, provRes] = await Promise.all([
      axios.get(`${API}/stats/price-distribution`),
      axios.get(`${API}/stats/overview`),
    ])

    rangeData.value = distRes.data?.data || []
    totalCount.value = rangeData.value.reduce((s, r) => s + r.count, 0) || 0

    const overviewData = provRes.data
    overview.value = overviewData
    provinceData.value = (overviewData.by_province || [])
      .sort((a, b) => b.count - a.count)
      .slice(0, 20)
      .map(p => ({
        province: p.province,
        count: p.count,
        avg_price: p.avg_price,
        ranges: []
      }))

    // Load range breakdown for all provinces in ONE call
    const provNames = provinceData.value.map(p => p.province)
    const rangeRes = await axios.get(`${API}/stats/province-ranges`, {
      params: { provinces: provNames.join(",") }
    })
    const rangeMap = rangeRes.data?.data || {}
    provinceData.value.forEach(p => {
      p.ranges = rangeMap[p.province] || []
    })

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

function renderRangeBar() {
  const el = document.getElementById('rangeBarChart')
  if (!el || !rangeData.value.length) return
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
        return `<b>${p.name}</b><br/>数量: <b style="color:#2563eb">${p.value.toLocaleString()}</b> 条<br/>占比: <b>${getPct(p.value)}%</b>`
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
  window.addEventListener('resize', () => {
    rangeBarIns.value?.resize()
    provinceHeatIns.value?.resize()
    // resize all lazy-rendered province charts
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

function renderOneProvince(province) {
  const p = provinceData.value.find(p => p.province === province)
  if (!p) return
  const el = document.getElementById('provinceChart_' + province)
  if (!el) return
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
      backgroundColor: 'rgba(255,255,255,0.98)', borderColor: '#cbd5e1',
      textStyle: { color: '#0f172a', fontSize: 10 },
      formatter: p => `<b>${p.name}</b><br/>数量: <b style="color:#2563eb">${Number(p.value).toLocaleString()}</b>`
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


/* 统计概览卡片 */
.dist-overview-stats {
  display: flex;
  align-items: center;
  gap: 0;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 14px;
  padding: 20px 28px;
}
.ov-stat {
  display: flex;
  align-items: center;
  gap: 14px;
  flex: 1;
}
.ov-icon { font-size: 22px; line-height: 1; }
.ov-body { display: flex; flex-direction: column; gap: 2px; }
.ov-value { font-size: 16px; font-weight: 700; color: #0f172a; font-family: ui-monospace, 'SF Mono', Consolas, 'Liberation Mono', monospace; }
.ov-label { font-size: 11px; color: var(--text-3); }
.ov-divider { width: 1px; height: 36px; background: var(--border); margin: 0 24px; flex-shrink: 0; }

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

.dist-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}

.dist-table th {
  text-align: left;
  padding: 11px 14px;
  background: rgba(15, 23, 42, 0.04);
  color: var(--text-3);
  font-weight: 600;
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  border-bottom: 1px solid var(--border);
}

.dist-table td {
  padding: 10px 14px;
  border-bottom: 1px solid rgba(15,23,42,0.04);
  color: #1e293b;
}

.dist-table tr:last-child td {
  border-bottom: none;
}

.dist-table tr:hover td { background: rgba(37,99,235,0.04); }

.range-badge {
  display: inline-block;
  padding: 2px 8px;
  background: rgba(37,99,235,0.12);
  color: var(--primary);
  border-radius: 4px;
  font-size: 12px;
  font-weight: 500;
}

.pct-bar-wrap {
  display: flex;
  align-items: center;
  gap: 8px;
}

.pct-bar {
  height: 6px;
  border-radius: 3px;
  min-width: 4px;
  transition: width 0.3s;
}

.pct-label {
  font-size: 12px;
  color: var(--text-3);
  white-space: nowrap;
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
}

.province-chart-cell:hover {
  transform: translateY(-2px);
  border-color: var(--province-color, var(--primary));
  box-shadow: var(--shadow-lg);
}

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

.dist-loading, .dist-error {
  text-align: center;
  padding: 24px;
  color: var(--text-3);
  font-size: 13px;
}

.dist-error {
  color: var(--status-alert);
}
</style>
