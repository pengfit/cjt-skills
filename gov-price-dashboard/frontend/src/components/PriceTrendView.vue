<template>
  <div class="trend-page">

    <!-- 顶部信息 -->
    <PageHeader
      variant="flat"
      title="价格走势"
      :subtitle="`基于 DWS 索引的 ${cityLabel} 工程造价材料价格时序曲线，按 period_start（业务期）聚合`"
      :stats="topStats"
    ><template #icon>📈</template></PageHeader>

    <!-- 筛选条 -->
    <div class="trend-filter-bar">
      <CustomSelect
        v-model="city"
        :options="cityOptions"
        placeholder="选城市"
      />
      <CustomSelect
        v-model="periodsLimit"
        :options="periodOptions"
        placeholder="期数"
      />
      <div class="filter-meta">
        <span class="meta-pill">📅 跨度：<strong>{{ periodRangeText }}</strong></span>
        <span class="meta-pill">📦 文档：<strong>{{ data.total_docs || 0 }}</strong></span>
        <span class="meta-pill">🔍 材料：<strong>{{ selectedMaterials.length }} / {{ allMaterials.length }}</strong></span>
      </div>
    </div>

    <!-- 材料选择 chip 栏 -->
    <div class="material-bar" v-if="allMaterials.length">
      <div
        v-for="m in allMaterials"
        :key="m"
        class="material-chip"
        :class="{ active: selectedMaterials.includes(m) }"
        :title="m"
        @click="toggleMaterial(m)"
      >{{ m }}</div>
    </div>

    <!-- 主图 -->
    <div class="trend-card">
      <div v-if="loading" class="trend-loading">
        <SkeletonCard :lines="6" :hide-footer="true" />
      </div>
      <div v-else-if="error" class="trend-error">
        <div class="error-icon">⚠️</div>
        <div class="error-title">{{ error }}</div>
        <button class="btn-primary" @click="loadData">🔄 重试</button>
      </div>
      <div v-else-if="!allPeriods.length" class="trend-empty">
        <div class="empty-icon">📭</div>
        <div class="empty-title">该城市暂无可用时序数据</div>
        <div class="empty-hint">DWS 索引里没有按 period_start 可聚合的多期数据</div>
      </div>
      <div v-else ref="chartEl" class="trend-chart"></div>
    </div>

    <!-- 数据表（每材料 × 每期均价） -->
    <div v-if="!loading && allPeriods.length" class="trend-table-card">
      <SectionHeader title="时序数据表" dot-color="blue" subtitle="每行=一个材料，每列=一个业务期" />
      <div class="trend-table-scroll">
        <table class="trend-table">
          <thead>
            <tr>
              <th>材料</th>
              <th>单位</th>
              <th v-for="p in allPeriods" :key="p.start" :title="`${p.start} ~ ${p.end}`">
                {{ p.start.slice(5) }}
              </th>
              <th class="th-trend">环比</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="s in activeSeries" :key="s.material">
              <td class="cell-material">{{ s.material }}</td>
              <td class="cell-unit">{{ s.unit || '—' }}</td>
              <td v-for="p in allPeriods" :key="p.start" class="cell-price">
                <template v-if="getPoint(s, p.start)">
                  <div class="price-val">{{ getPoint(s, p.start).avg.toFixed(2) }}</div>
                  <div class="price-meta">{{ getPoint(s, p.start).n }}规格</div>
                </template>
                <template v-else><span class="no-data">—</span></template>
              </td>
              <td class="cell-trend">
                <span v-if="trendPct(s) != null" :class="['trend-pct', trendClass(trendPct(s))]">
                  {{ trendPct(s) >= 0 ? '↑' : '↓' }} {{ Math.abs(trendPct(s)).toFixed(1) }}%
                </span>
                <span v-else class="no-data">—</span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, watch, nextTick, onBeforeUnmount } from 'vue'
import axios from 'axios'
import * as echarts from 'echarts'
import PageHeader from './PageHeader.vue'
import SectionHeader from './SectionHeader.vue'
import CustomSelect from './CustomSelect.vue'
import SkeletonCard from './SkeletonCard.vue'

const API = import.meta.env.VITE_API_URL || '/api'

// ── 状态 ──
// city 不写死：onMounted 拉完 cityOptions 后从列表动态选默认（拼音第一个 = chongqing）
const city = ref('')
const cityOptions = ref([])
const allMaterials = ref([])         // API 返回的该城市所有材料
const selectedMaterials = ref([])    // 当前显示的材料
const allPeriods = ref([])           // 业务期数组 [{start, end, label}]
const data = ref({ series: [], total_docs: 0, periods: [] })
const loading = ref(false)
const error = ref('')
const chartEl = ref(null)
let chartInstance = null

// 期数筛选
const periodsLimit = ref(12)
const periodOptions = ref([
  { key: 6, label: '最近 6 期' },
  { key: 12, label: '最近 12 期' },
  { key: 24, label: '最近 24 期' },
  { key: 36, label: '最近 36 期' },
])

// 颜色（按材料在数据里出现的位置分配稳定色）
const COLOR_POOL = [
  '#dc2626', '#2563eb', '#16a34a', '#ea580c', '#7c3aed',
  '#0891b2', '#db2777', '#65a30d', '#9333ea', '#0d9488',
  '#e11d48', '#4f46e5', '#059669', '#d97706', '#a21caf',
]
const colorMap = {}
function colorOf(material) {
  if (!colorMap[material]) {
    const i = Object.keys(colorMap).length
    colorMap[material] = COLOR_POOL[i % COLOR_POOL.length]
  }
  return colorMap[material]
}

const activeSeries = computed(() => data.value.series.filter(s => selectedMaterials.value.includes(s.material)))
const cityLabel = computed(() => cityOptions.value.find(c => c.key === city.value)?.label || city.value)

const topStats = computed(() => {
  if (loading.value) return []
  return [
    { label: '城市', value: cityLabel.value },
    { label: '期数', value: allPeriods.value.length },
    { label: '材料', value: selectedMaterials.value.length },
  ]
})

const periodRangeText = computed(() => {
  if (allPeriods.value.length === 0) return '—'
  if (allPeriods.value.length === 1) return allPeriods.value[0].label
  return `${allPeriods.value[0].label} ~ ${allPeriods.value.at(-1).label}`
})

// ── 方法 ──
async function loadCityOptions() {
  try {
    const { data: d } = await axios.get(`${API}/skill-registry`)
    const opts = (d?.skills || [])
      .map(s => ({ key: s.key, label: s.label }))
      .sort((a, b) => a.label.localeCompare(b.label, 'zh-CN'))
    cityOptions.value = opts
    // 动态选默认 city：未设置时用拼音第一个（保证不写死、且一定是 registry 里存在的）
    if (!city.value && opts.length) {
      city.value = opts[0].key
    }
  } catch (e) {
    error.value = '加载城市列表失败：' + e.message
  }
}

async function loadData() {
  if (!city.value) return
  // 切城市/期数前 dispose 旧 echarts 实例：
  // loading=true 会卸载 chartEl DOM（template 切到 trend-loading），
  // 旧 chartInstance 还指向已卸载的 DOM，setOption 上去 canvas 不会显示
  if (chartInstance) {
    chartInstance.dispose()
    chartInstance = null
  }
  loading.value = true
  error.value = ''
  data.value = { series: [], total_docs: 0, periods: [] }
  allPeriods.value = []
  allMaterials.value = []
  try {
    const url = `${API}/stats/price-trend?city=${encodeURIComponent(city.value)}&materials=*&periods=${periodsLimit.value}`
    const { data: d } = await axios.get(url)
    if (!d.ok) throw new Error(d.error || 'API 返回错误')
    data.value = d
    allPeriods.value = d.periods || []
    // 默认选前 4 个材料
    allMaterials.value = (d.series || []).map(s => s.material)
    selectedMaterials.value = allMaterials.value.slice(0, 4)
  } catch (e) {
    error.value = e.message || '加载失败'
  } finally {
    loading.value = false
    await nextTick()
    renderChart()
  }
}

function toggleMaterial(m) {
  if (selectedMaterials.value.includes(m)) {
    if (selectedMaterials.value.length > 1) {
      selectedMaterials.value = selectedMaterials.value.filter(x => x !== m)
    }
  } else {
    selectedMaterials.value = [...selectedMaterials.value, m]
  }
  renderChart()
}

function getPoint(s, periodStart) {
  return s.points.find(p => p.period_start === periodStart)
}

// 环比：首末两期
function trendPct(s) {
  const pts = s.points
  if (pts.length < 2) return null
  const first = pts[0].avg
  const last = pts.at(-1).avg
  if (!first || first <= 0) return null
  return ((last - first) / first) * 100
}

function trendClass(pct) {
  if (pct == null) return ''
  return pct >= 0 ? 'trend-up' : 'trend-down'
}

function renderChart() {
  if (!chartEl.value || !allPeriods.value.length) {
    if (chartInstance) { chartInstance.dispose(); chartInstance = null }
    return
  }
  if (!chartInstance) {
    chartInstance = echarts.init(chartEl.value)
    window.addEventListener('resize', chartInstance.resize)
  }
  const periodMap = {}
  allPeriods.value.forEach(p => { periodMap[p.start] = p })

  const xData = allPeriods.value.map(p => p.label)

  const option = {
    tooltip: {
      trigger: 'axis',
      backgroundColor: 'rgba(255,255,255,0.98)',
      borderColor: '#cbd5e1',
      textStyle: { color: '#0f172a' },
      formatter: (params) => {
        const head = params[0].axisValue
        const period = periodMap[Object.keys(periodMap).find(k => periodMap[k].label === head)] || {}
        const range = period.start && period.end ? `（${period.start} ~ ${period.end}）` : ''
        let html = `<b>${head}</b>${range}<br/>`
        params.forEach(p => {
          const d = p.data
          if (d && d.avg != null) {
            html += `${p.marker} ${p.seriesName}: <b>${d.avg.toFixed(2)}</b> ${d.unit || ''}<br/>`
            html += `&nbsp;&nbsp;min ${d.min} · max ${d.max} · ${d.n}规格<br/>`
          }
        })
        return html
      }
    },
    legend: { top: 0, type: 'scroll', textStyle: { color: '#475569' } },
    grid: { left: 80, right: 30, top: 50, bottom: 60 },
    xAxis: { type: 'category', data: xData, axisLine: { lineStyle: { color: '#cbd5e1' } } },
    yAxis: { type: 'value', name: '价格', nameTextStyle: { color: '#64748b' },
             axisLabel: { color: '#475569' }, splitLine: { lineStyle: { color: '#e2e8f0' } } },
    series: activeSeries.value.map(s => ({
      name: s.material + (s.unit ? ` (${s.unit})` : ''),
      type: 'line',
      data: allPeriods.value.map(p => {
        const pt = getPoint(s, p.start)
        if (!pt) return { value: null, avg: null, min: null, max: null, n: 0, unit: s.unit }
        return { value: pt.avg, avg: pt.avg, min: pt.min, max: pt.max, n: pt.n, unit: s.unit }
      }),
      smooth: false,
      symbol: 'circle',
      symbolSize: 8,
      lineStyle: { width: 2.5, color: colorOf(s.material) },
      itemStyle: { color: colorOf(s.material) },
      emphasis: { focus: 'series' },
      connectNulls: true,
    })),
  }
  chartInstance.setOption(option, true)
}

// 注意：v-model="city" 双向绑定会让 city.value 变化时同步更新，watch(city) 统一负责触发 loadData
// 因此 CustomSelect 不再需要 @change 回调

onMounted(async () => {
  await loadCityOptions()
  // loadData 由 watch(city) 触发（city.value 在 loadCityOptions 内被 set）
})

// city 变化时（包括初次从 '' 切到首个 city）自动 loadData
watch(city, (newCity) => {
  if (newCity) loadData()
})

onBeforeUnmount(() => {
  if (chartInstance) chartInstance.dispose()
})

watch(periodsLimit, () => loadData())
</script>

<style scoped>
.trend-page {
  padding: 16px 20px 80px;
  min-height: 100vh;
  color: #1e293b;
}

.trend-filter-bar {
  display: flex;
  align-items: center;
  gap: 12px;
  margin: 12px 0;
  flex-wrap: wrap;
}
.filter-meta {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}
.meta-pill {
  background: #fff;
  border: 1px solid #e2e8f0;
  padding: 4px 10px;
  border-radius: 4px;
  font-size: 12px;
  color: #475569;
}
.meta-pill strong { color: #0f172a; }

.material-bar {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin: 12px 0;
  background: #fff;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  padding: 10px 12px;
}
.material-chip {
  display: inline-block;
  padding: 3px 10px;
  border-radius: 3px;
  font-size: 12px;
  background: #f1f5f9;
  color: #94a3b8;
  cursor: pointer;
  border: 1px solid transparent;
  max-width: 280px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  transition: all 0.15s;
}
.material-chip:hover { border-color: #cbd5e1; }
.material-chip.active {
  background: #dbeafe;
  color: #1d4ed8;
  border-color: #93c5fd;
  font-weight: 500;
}

.trend-card {
  background: #fff;
  border-radius: 8px;
  border: 1px solid #e2e8f0;
  padding: 16px;
  margin-top: 8px;
  min-height: 480px;
  box-shadow: 0 1px 3px rgba(15,23,42,0.04);
}
.trend-chart { width: 100%; height: 540px; }
.trend-loading, .trend-error, .trend-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  min-height: 420px;
  gap: 8px;
}
.error-icon, .empty-icon { font-size: 36px; }
.error-title, .empty-title { font-size: 14px; font-weight: 600; }
.empty-hint { font-size: 12px; color: #94a3b8; }
.btn-primary {
  margin-top: 8px;
  padding: 6px 14px;
  background: #2563eb;
  color: #fff;
  border: none;
  border-radius: 4px;
  cursor: pointer;
  font-size: 12px;
}

.trend-table-card {
  background: #fff;
  border-radius: 8px;
  border: 1px solid #e2e8f0;
  padding: 16px;
  margin-top: 16px;
  box-shadow: 0 1px 3px rgba(15,23,42,0.04);
}
.trend-table-scroll { overflow-x: auto; }
.trend-table { width: 100%; border-collapse: collapse; font-size: 12px; }
.trend-table th, .trend-table td {
  padding: 8px 10px;
  text-align: left;
  border-bottom: 1px solid #f1f5f9;
}
.trend-table th {
  background: #f8fafc;
  font-weight: 600;
  color: #475569;
  text-transform: uppercase;
  font-size: 11px;
  letter-spacing: 0.4px;
}
.th-trend { background: #eff6ff !important; }
.cell-material { color: #0f172a; font-weight: 500; min-width: 200px; }
.cell-unit { color: #64748b; }
.cell-price { text-align: right; min-width: 80px; }
.cell-price .price-val { font-weight: 600; color: #0f172a; font-variant-numeric: tabular-nums; }
.cell-price .price-meta { font-size: 10px; color: #94a3b8; }
.cell-trend { text-align: right; }
.trend-pct { font-weight: 600; font-variant-numeric: tabular-nums; padding: 2px 8px; border-radius: 3px; }
.trend-pct.trend-up { color: #dc2626; background: #fef2f2; }
.trend-pct.trend-down { color: #16a34a; background: #f0fdf4; }
.no-data { color: #cbd5e1; }
</style>
