<template>
  <div class="trend-page">

    <!-- 顶部信息 -->
    <PageHeader
      variant="flat"
      title="价格走势"
      :subtitle="trendMode === 'single'
        ? `基于 DWS 索引的 ${cityLabel} 工程造价材料价格时序曲线，按 period_start（业务期）聚合 · 按规格(spec)拆分`
        : trendMode === 'category'
        ? `基于 normalized_breed 的品类级视角 · ${cityLabel} · 规格热力图 + 价格带 + 同 L3 横向推荐`
        : '跨城同品种时序对比 · 按 attr-based spec_key 拼接 · 同单位约束，周期以日历对齐'"
      :stats="topStats"
    >
      <template #icon>📈</template>
      <template #right>
        <div class="trend-mode-tabs">
          <button
            class="mode-tab"
            :class="{ active: trendMode === 'single' }"
            @click="trendMode = 'single'"
          >单城市</button>
          <button
            class="mode-tab"
            :class="{ active: trendMode === 'category' }"
            @click="trendMode = 'category'"
          >品类聚合</button>
          <button
            class="mode-tab"
            :class="{ active: trendMode === 'compare' }"
            @click="trendMode = 'compare'"
          >跨城市对比</button>
        </div>
      </template>
    </PageHeader>

    <!-- 品类聚合面板 -->
    <CategoryTrendView v-if="trendMode === 'category'" />

    <!-- 跨城对比面板 -->
    <PriceTrendComparePanel v-if="trendMode === 'compare'" />

    <!-- 单城市面板（默认） -->
    <template v-if="trendMode === 'single'">

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
        <span class="meta-pill">📐 规格：<strong>{{ totalSpecRows }}</strong></span>
      </div>
    </div>

    <!-- 材料搜索框（跨城 NORM 统一品种 + 本地 chip 过滤 双能力） -->
    <div v-if="allMaterials.length" class="material-search">
      <div class="material-search-input-wrap" :class="{ focused: normDropdownOpen }">
        <input
          v-model="materialSearch"
          type="text"
          class="material-search-input"
          placeholder="搜索材料（例：商品砼、HRB400、C20 · 跨城 NORM）"
          @focus="normDropdownOpen = true"
          @blur="setTimeout(() => normDropdownOpen = false, 200)"
          @keydown.down.prevent="normMoveFocus(1)"
          @keydown.up.prevent="normMoveFocus(-1)"
          @keydown.enter.prevent="normPickFocused()"
          @keydown.esc="normDropdownOpen = false"
        />
        <button v-if="materialSearch" class="material-search-clear" @click="clearMaterialSearch()" title="清除">×</button>
        <!-- NORM 跨城候选下拉 -->
        <div v-if="normDropdownOpen && materialSearch.trim() && (normCandidates.length || normLoading || filteredMaterials.length)" class="norm-dropdown">
          <div v-if="normLoading" class="norm-dropdown-loading">⏳ 查询 NORM 索引…</div>
          <template v-else>
            <div v-if="normCandidates.length" class="norm-dropdown-section-title">
              🌐 跨城归一品种（{{ normCandidates.length }}）
            </div>
            <div
              v-for="(c, idx) in normCandidates"
              :key="c.normalized_breed + '_n'"
              class="norm-dropdown-item"
              :class="{ focused: normFocusedIdx === idx }"
              :title="c.cities.map(x => x.label + ':' + x.docs).join(' | ')"
              @mousedown.prevent="pickNormCandidate(c)"
            >
              <span class="norm-dropdown-breed">{{ c.normalized_breed }}</span>
              <span class="norm-dropdown-meta">{{ c.cities.length }} 城 · {{ c.total_docs }} 条</span>
            </div>
            <div v-if="filteredMaterials.length" class="norm-dropdown-section-title">
              📦 本地材料（已加载 · 前 8）
            </div>
            <div
              v-for="m in filteredMaterials.slice(0, 8)"
              :key="m + '_l'"
              class="norm-dropdown-item"
              :class="{ dimmed: selectedMaterials.includes(m) }"
              @mousedown.prevent="pickLocalMaterial(m)"
            >
              <span class="norm-dropdown-breed">{{ m }}</span>
              <span class="norm-dropdown-meta">{{ selectedMaterials.includes(m) ? '已选' : '本地' }}</span>
            </div>
            <div v-if="!normCandidates.length && !filteredMaterials.length" class="norm-dropdown-empty">
              无匹配
            </div>
          </template>
        </div>
      </div>
      <span class="material-search-hint">
        {{ filteredMaterials.length }} 本地 · {{ normCandidates.length }} NORM 跨城
      </span>
    </div>

    <!-- 材料选择 chip 栏 -->
    <div class="material-bar" v-if="allMaterials.length">
      <div
        v-for="m in filteredMaterials"
        :key="m"
        class="material-chip"
        :class="{ active: selectedMaterials.includes(m) }"
        :title="m"
        @click="toggleMaterial(m)"
      >{{ m }}</div>
      <div v-if="!filteredMaterials.length" class="material-bar-empty">
        没有匹配“{{ materialSearch }}”的材料
      </div>
    </div>

    <!-- attr_key 多选 chip 栏（仅当前选中材料出现过的 attr_key） -->
    <div v-if="activeSeries.length && availableAttrKeys.length" class="attr-bar">
      <span class="attr-bar-label">拆分维度:</span>
      <div
        v-for="ak in availableAttrKeys"
        :key="ak.key"
        class="attr-chip"
        :class="{ active: selectedAttrKeys.has(ak.key) }"
        :title="`按 ${ak.label} 拆分`"
        @click="toggleAttrKey(ak.key)"
      >{{ ak.displayLabel }}</div>
      <span class="attr-bar-hint">{{ selectedAttrKeys.size }} / {{ availableAttrKeys.length }} 选中</span>
    </div>

    <!-- 主图 -->
    <div class="trend-card">
      <!-- 主次曲线分层（P0-#1）：focused 系列高亮，其余半透明 -->
      <!-- 导出按钮（P1-#6） -->
      <div class="chart-toolbar">
        <div v-if="focusedSeriesName" class="focus-pill">
          🎯 聚焦：<strong>{{ focusedSeriesName }}</strong>
          <button class="focus-clear" @click="clearFocus" title="清除聚焦">×</button>
        </div>
        <div v-if="!loading && allPeriods.length && chartSeries.length" class="export-bar">
          <button class="export-btn" @click="onExportPng" title="导出当前主图为 PNG">📸 PNG</button>
          <button class="export-btn" @click="onExportCsv" title="导出当前规格时序为 CSV">📊 CSV</button>
        </div>
      </div>
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

    <!-- 规格拆分表（每材料 × 每规格 × 每期均价） -->
    <div v-if="!loading && allPeriods.length" class="trend-table-card">
      <SectionHeader
        title="时序数据表（按规格拆分）"
        dot-color="blue"
        :subtitle="`共 ${totalSpecRows} 条规格行（同材料不同规格价差可达数百倍，已拆分）`"
      />
      <div class="trend-table-scroll">
        <table class="trend-table">
          <thead>
            <tr>
              <th>材料</th>
              <th>规格</th>
              <th>单位</th>
              <th v-for="p in allPeriods" :key="p.start" :title="`${p.start} ~ ${p.end}`">
                {{ p.start.slice(5) }}
              </th>
              <th class="th-trend">环比</th>
            </tr>
          </thead>
          <tbody>
            <template v-for="s in activeSeries" :key="s.normalized_breed">
              <tr v-for="(sp, spIdx) in s.specs" :key="`${s.normalized_breed}-${sp.spec}-${sp.unit}`">
                <td v-if="spIdx === 0" class="cell-material" :rowspan="s.specs.length">
                  {{ s.normalized_breed }}
                  <div class="cell-material-meta" v-if="s.specs.length > 1">
                    {{ s.spec_count }}规格 · {{ s.n_total }}样本
                  </div>
                </td>
                <td class="cell-spec" :title="sp.spec">{{ sp.spec }}</td>
                <td class="cell-unit">{{ sp.unit || '—' }}</td>
                <td v-for="p in allPeriods" :key="p.start" class="cell-price">
                  <template v-if="getPoint(sp, p.start)">
                    <div class="price-val">{{ getPoint(sp, p.start).avg.toFixed(2) }}</div>
                    <div class="price-meta">{{ getPoint(sp, p.start).n }}条</div>
                  </template>
                  <template v-else><span class="no-data">—</span></template>
                </td>
                <td class="cell-trend">
                  <span v-if="trendPct(sp) != null" :class="['trend-pct', trendClass(trendPct(sp))]">
                    {{ trendPct(sp) >= 0 ? '↑' : '↓' }} {{ Math.abs(trendPct(sp)).toFixed(1) }}%
                  </span>
                  <span v-else class="no-data">—</span>
                </td>
              </tr>
              <tr v-if="s.specs.length === 0" class="row-empty">
                <td class="cell-material">{{ s.normalized_breed }}</td>
                <td colspan="2" class="no-data">该材料无规格数据</td>
                <td v-for="p in allPeriods" :key="p.start" class="no-data">—</td>
                <td class="no-data">—</td>
              </tr>
            </template>
          </tbody>
        </table>
      </div>
    </div>
    </template>
    <!-- /单城市面板 -->
  </div>
</template>

<script setup>
import { ref, computed, onMounted, watch, nextTick, onBeforeUnmount, defineAsyncComponent } from 'vue'
// 三个子 tab 视图都 async 化（首屏只加载 PageHeader 架子，切 tab 才拉对应代码；2026-07-09 优化）
const PriceTrendComparePanel = defineAsyncComponent(() => import('./PriceTrendComparePanel.vue'))
const CategoryTrendView = defineAsyncComponent(() => import('./CategoryTrendView.vue'))

// 顶部 tab 状态：'single'（默认）| 'category' | 'compare'
const trendMode = ref('single')
import axios from 'axios'
import * as echarts from 'echarts'
import PageHeader from './PageHeader.vue'
import SectionHeader from './SectionHeader.vue'
import CustomSelect from './CustomSelect.vue'
import SkeletonCard from './SkeletonCard.vue'
import { exportChartAsPng, exportCsvAsFile, withTimestamp } from '../composables/useExport.js'

const API = import.meta.env.VITE_API_URL || '/api'

// ── 状态 ──
const city = ref('')
const cityOptions = ref([])
const allMaterials = ref([])         // API 返回的该城市所有材料
const selectedMaterials = ref([])    // 当前显示的材料
const materialSearch = ref('')        // 材料名搜索关键字（双用：本地过滤 + NORM 跨城调）
const filteredMaterials = computed(() => {
  if (!materialSearch.value.trim()) return allMaterials.value
  const k = materialSearch.value.trim().toLowerCase()
  return allMaterials.value.filter(m => m.toLowerCase().includes(k))
})
const allPeriods = ref([])           // 业务期数组 [{start, end, label}]
const data = ref({ series: [], total_docs: 0, periods: [] })
const loading = ref(false)
const error = ref('')
const chartEl = ref(null)
let chartInstance = null

// attr_key 多选过滤。默认全选；用户在 chip 栏勾选/取消。仅显示选中 attr_key 的 specs。
// 切换材料时重置为“所有出现的 attr_key 全选”（避免保留旧选择导致 0 specs）。
const selectedAttrKeys = ref(new Set())

// 主次曲线分层（P0-#1）：hover 自动高亮（ECharts 内置），
// click 系列则“锁定聚焦”，其余曲线变淡 + 减细
const focusedSeriesName = ref(null)
watch(selectedMaterials, () => {
  const keys = new Set()
  for (const s of data.value.series) {
    if (selectedMaterials.value.includes(s.normalized_breed)) {
      for (const ak of (s.available_attr_keys || [])) keys.add(ak.key)
    }
  }
  selectedAttrKeys.value = keys
}, { deep: true })
// 数据加载后默认全选
watch(() => data.value.series, (newSeries) => {
  if (newSeries && newSeries.length) {
    const keys = new Set()
    for (const s of newSeries) for (const ak of (s.available_attr_keys || [])) keys.add(ak.key)
    if (selectedAttrKeys.value.size === 0) selectedAttrKeys.value = keys
  }
}, { deep: true })
function toggleAttrKey(k) {
  const s = new Set(selectedAttrKeys.value)
  if (s.has(k)) s.delete(k); else s.add(k)
  selectedAttrKeys.value = s
}

// 期数筛选（CustomSelect.modelValue 限定 String，options.key 一致）
const periodsLimit = ref('12')
const periodOptions = ref([
  { key: '6',  label: '最近 6 期'  },
  { key: '12', label: '最近 12 期' },
  { key: '24', label: '最近 24 期' },
  { key: '36', label: '最近 36 期' },
])

// 颜色（按 seriesName 在 activeSpecs 里出现的位置分配稳定色）
const COLOR_POOL = [
  '#dc2626', '#2563eb', '#16a34a', '#ea580c', '#7c3aed',
  '#0891b2', '#db2777', '#65a30d', '#9333ea', '#0d9488',
  '#e11d48', '#4f46e5', '#059669', '#d97706', '#a21caf',
  '#b45309', '#0369a1', '#15803d', '#a16207', '#9333ea',
]
const colorMap = {}
function colorOf(seriesName) {
  if (!colorMap[seriesName]) {
    const i = Object.keys(colorMap).length
    colorMap[seriesName] = COLOR_POOL[i % COLOR_POOL.length]
  }
  return colorMap[seriesName]
}

// 展平每个 series 的 specs 为独立的 chart series（用于图表多曲线）
// 同时根据 selectedAttrKeys 过滤 specs（前端过滤，不重发 API）
const activeSeries = computed(() => data.value.series
  .filter(s => selectedMaterials.value.includes(s.normalized_breed))
  .map(s => ({
    ...s,
    specs: (s.specs || []).filter(sp => selectedAttrKeys.value.has(sp.attr_key)),
  })))

// 收集当前选中材料下出现过的 attr_key（去重保序）
// 若不同 attr_key 映射成同一 label（例 grade + strength 都是「强度」），
// 会加上 attr_key 后缀区分（例「强度(grade)」/「强度(strength)」）
const availableAttrKeys = computed(() => {
  const seen = new Set()
  const raw = []
  for (const s of activeSeries.value) {
    for (const ak of (s.available_attr_keys || [])) {
      if (!seen.has(ak.key)) {
        seen.add(ak.key)
        raw.push({ ...ak })
      }
    }
  }
  // 统计 label 冲突
  const labelCount = {}
  for (const ak of raw) labelCount[ak.label] = (labelCount[ak.label] || 0) + 1
  return raw.map(ak => ({
    ...ak,
    displayLabel: labelCount[ak.label] > 1 ? `${ak.label}(${ak.key})` : ak.label,
  }))
})

const chartSeries = computed(() => {
  const out = []
  for (const s of activeSeries.value) {
    for (const sp of (s.specs || [])) {
      out.push({
        name: `${s.normalized_breed} / ${sp.spec}`,
        material: s.normalized_breed,
        spec: sp.spec,
        unit: sp.unit,
        points: sp.points,
      })
    }
  }
  return out
})

const totalSpecRows = computed(() =>
  activeSeries.value.reduce((acc, s) => acc + (s.specs?.length || 0), 0)
)

const cityLabel = computed(() => cityOptions.value.find(c => c.key === city.value)?.label || city.value)

const topStats = computed(() => {
  if (loading.value) return []
  return [
    { label: '城市', value: cityLabel.value },
    { label: '期数', value: allPeriods.value.length },
    { label: '材料', value: selectedMaterials.value.length },
    { label: '规格行', value: totalSpecRows.value },
  ]
})

const periodRangeText = computed(() => {
  if (allPeriods.value.length === 0) return '—'
  if (allPeriods.value.length === 1) return allPeriods.value[0].label
  return `${allPeriods.value[0].label} ~ ${allPeriods.value.at(-1).label}`
})

// ── 方法 ──
// NORM 跨城品种搜索（debounce 300ms）
const normCandidates = ref([])
const normLoading = ref(false)
const normFocusedIdx = ref(0)
const normDropdownOpen = ref(false)
let normSearchTimer = null

async function searchNormBreeds(keyword) {
  const kw = (keyword || '').trim()
  if (!kw) {
    normCandidates.value = []
    normLoading.value = false
    return
  }
  normLoading.value = true
  try {
    const { data: d } = await axios.get(`${API}/norm/breeds/search`, {
      params: { keyword: kw, limit: 12 },
    })
    normCandidates.value = d.ok ? (d.results || []) : []
    normFocusedIdx.value = 0
  } catch (e) {
    normCandidates.value = []
  } finally {
    normLoading.value = false
  }
}

function clearMaterialSearch() {
  materialSearch.value = ''
  normCandidates.value = []
  normFocusedIdx.value = 0
}

function pickNormCandidate(c) {
  // 重载该品种趋势数据（点选式，覆盖当前 selectedMaterials）
  selectedMaterials.value = [c.normalized_breed]
  clearMaterialSearch()
  normDropdownOpen.value = false
  loadData({ materials: c.normalized_breed })
}
function pickLocalMaterial(m) {
  // toggleMaterial 但不依赖 dropdown 是否开
  toggleMaterial(m)
  clearMaterialSearch()
  normDropdownOpen.value = false
}
function normMoveFocus(delta) {
  const len = normCandidates.value.length
  if (!len) return
  let i = normFocusedIdx.value + delta
  if (i < 0) i = len - 1
  if (i >= len) i = 0
  normFocusedIdx.value = i
}
function normPickFocused() {
  const c = normCandidates.value[normFocusedIdx.value]
  if (c) pickNormCandidate(c)
}

watch(materialSearch, (v) => {
  if (normSearchTimer) clearTimeout(normSearchTimer)
  const kw = (v || '').trim()
  if (!kw) {
    normCandidates.value = []
    normFocusedIdx.value = 0
    return
  }
  normSearchTimer = setTimeout(() => searchNormBreeds(kw), 300)
})

async function loadCityOptions() {
  try {
    const { data: d } = await axios.get(`${API}/skill-registry`)
    const opts = (d?.skills || [])
      .map(s => ({ key: s.key, label: s.label }))
      .sort((a, b) => a.label.localeCompare(b.label, 'zh-CN'))
    cityOptions.value = opts
    if (!city.value && opts.length) {
      city.value = opts[0].key
    }
  } catch (e) {
    error.value = '加载城市列表失败：' + e.message
  }
}

async function loadData(opts = {}) {
  if (!city.value) return
  if (chartInstance) {
    chartInstance.dispose()
    chartInstance = null
  }
  // 重置颜色 map（新数据重新分配颜色）
  Object.keys(colorMap).forEach(k => delete colorMap[k])

  loading.value = true
  error.value = ''
  data.value = { series: [], total_docs: 0, periods: [] }
  allPeriods.value = []
  allMaterials.value = []
  try {
    // 支持从 NORM 点选后传单个品种（逗号分隔或多品种数组）
    let materials = '*'
    if (opts.materials != null) {
      materials = Array.isArray(opts.materials) ? opts.materials.join(',') : String(opts.materials)
    }
    // 单品种调用时 max_breeds 不起作用，调小防 top_specs 误算（API 自己处理）
    const url = `${API}/stats/price-trend?city=${encodeURIComponent(city.value)}&materials=${encodeURIComponent(materials)}&periods=${parseInt(periodsLimit.value, 10)}&top_specs=8&max_breeds=30`
    const { data: d } = await axios.get(url)
    if (!d.ok) throw new Error(d.error || 'API 返回错误')
    data.value = d
    allPeriods.value = d.periods || []
    allMaterials.value = (d.series || []).map(s => s.normalized_breed)
    // 点选 NORM 后保持 selectedMaterials 不被自动重置（保留单品种突出显示）
    if (!opts.materials) {
      selectedMaterials.value = allMaterials.value.slice(0, 4)
    }
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

function getPoint(spec, periodStart) {
  return (spec.points || []).find(p => p.period_start === periodStart)
}

// 环比：首末两期
function trendPct(spec) {
  const pts = spec.points || []
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

// ── 导出（P1-#6） ──
function onExportPng() {
  const base = `${cityLabel.value}-${selectedMaterials.value.join('+') || 'data'}`
  const fname = `${withTimestamp(base)}.png`
  exportChartAsPng(chartInstance, fname)
}

function onExportCsv() {
  // 表头：材料 | 规格 | 单位 | 样本数 | <每期: 期_均价> | 首期均价 | 末期均价 | 涨跌幅%
  const rows = []
  const header = ['材料', '规格', '单位', '样本数', ...allPeriods.value.map(p => `${p.label}_均价`), '首期', '末期', '涨跌幅%']
  rows.push(header)
  for (const s of chartSeries.value) {
    const fullName = `${s.name}${s.unit ? ` (${s.unit})` : ''}`
    const [mat, spec] = s.name.split(' / ')
    const ptByPeriod = {}
    let first = null, last = null
    for (const p of allPeriods.value) {
      const pt = getPoint(s, p.start)
      if (pt) {
        ptByPeriod[p.start] = pt.avg
        if (first === null) first = pt.avg
        last = pt.avg
      }
    }
    const cells = allPeriods.value.map(p => {
      const v = ptByPeriod[p.start]
      return v == null ? '' : v.toFixed(2)
    })
    const changePct = (first && last) ? (((last - first) / first) * 100).toFixed(2) + '%' : ''
    rows.push([
      mat || fullName,
      spec || '',
      s.unit || '',
      String(s.points.reduce((acc, p) => acc + (p.n || 0), 0)),
      ...cells,
      first == null ? '' : first.toFixed(2),
      last == null ? '' : last.toFixed(2),
      changePct,
    ])
  }
  const base = `${cityLabel.value}-${selectedMaterials.value.join('+') || 'data'}`
  exportCsvAsFile(rows, `${withTimestamp(base)}.csv`)
}

function clearFocus() {
  focusedSeriesName.value = null
  renderChart()
}

function onChartClick(params) {
  // 点击系列 → 锁定聚焦；再点同一系列或点击空白区域 → 清除
  if (params && params.componentType === 'series') {
    const name = params.seriesName
    if (focusedSeriesName.value === name) {
      focusedSeriesName.value = null
    } else {
      focusedSeriesName.value = name
    }
    renderChart()
  } else if (params && (params.componentType === 'xAxis' || params.componentType === 'yAxis')) {
    // 点击坐标轴 → 清除聚焦
    if (focusedSeriesName.value) {
      focusedSeriesName.value = null
      renderChart()
    }
  }
}

function renderChart() {
  if (!chartEl.value || !allPeriods.value.length) {
    if (chartInstance) { chartInstance.dispose(); chartInstance = null }
    return
  }
  if (!chartInstance) {
    chartInstance = echarts.init(chartEl.value)
    window.addEventListener('resize', chartInstance.resize)
    chartInstance.on('click', onChartClick)
  }
  const periodMap = {}
  allPeriods.value.forEach(p => { periodMap[p.start] = p })

  const xData = allPeriods.value.map(p => p.label)

  const seriesArr = chartSeries.value.map(s => {
    const fullName = `${s.name}${s.unit ? ` (${s.unit})` : ''}`
    const isFocused = focusedSeriesName.value
    const isThis = isFocused === fullName
    const opacity = !isFocused ? 1 : (isThis ? 1 : 0.18)
    const lineW = isThis ? 3 : 2
    return {
      name: fullName,
      type: 'line',
      data: allPeriods.value.map(p => {
        const pt = getPoint(s, p.start)
        if (!pt) return { value: null, avg: null, min: null, max: null, n: 0, unit: s.unit }
        return { value: pt.avg, avg: pt.avg, min: pt.min, max: pt.max, n: pt.n, unit: s.unit }
      }),
      smooth: false,
      symbol: 'circle',
      symbolSize: isThis ? 9 : 6,
      lineStyle: { width: lineW, color: colorOf(s.name), opacity },
      itemStyle: { color: colorOf(s.name), opacity },
      emphasis: {
        focus: 'series',
        lineStyle: { width: 3, opacity: 1 },
        itemStyle: { opacity: 1 },
      },
      connectNulls: true,
      z: isThis ? 5 : 1,
    }
  })

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
            html += `&nbsp;&nbsp;min ${d.min} · max ${d.max} · ${d.n}条<br/>`
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
    series: seriesArr,
  }
  chartInstance.setOption(option, true)
}

onMounted(async () => {
  await loadCityOptions()
})

watch(city, (newCity) => {
  if (newCity) loadData()
})

onBeforeUnmount(() => {
  if (chartInstance) chartInstance.dispose()
  if (normSearchTimer) clearTimeout(normSearchTimer)
})

watch(periodsLimit, () => loadData())
</script>

<style scoped>
.trend-page {
  padding: 16px 20px 80px;
  min-height: 100vh;
  color: #1e293b;
}

/* 顶部 tab：单城市 / 跨城对比 */
.trend-mode-tabs {
  display: inline-flex;
  background: #f1f5f9;
  border-radius: 6px;
  padding: 3px;
  gap: 2px;
}
.mode-tab {
  border: none;
  background: transparent;
  padding: 6px 14px;
  border-radius: 4px;
  font-size: 12px;
  color: #64748b;
  cursor: pointer;
  transition: all 0.15s;
}
.mode-tab:hover { color: #0f172a; }
.mode-tab.active {
  background: #fff;
  color: #1d4ed8;
  font-weight: 600;
  box-shadow: 0 1px 3px rgba(15,23,42,0.08);
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

.material-search {
  display: flex; align-items: center; gap: 8px;
  margin: 8px 0 0;
}
.material-search-input-wrap {
  position: relative; flex: 1;
}
.material-search-input {
  width: 100%; box-sizing: border-box;
  padding: 7px 32px 7px 12px;
  border: 1px solid #cbd5e1; border-radius: 6px;
  font-size: 12px; outline: none;
  background: #fff; color: var(--text, #0f172a);
  transition: border-color 0.15s, box-shadow 0.15s;
}
.material-search-input:focus {
  border-color: #3b82f6;
  box-shadow: 0 0 0 2px rgba(59,130,246,0.15);
}
.material-search-clear {
  position: absolute; right: 4px; top: 50%; transform: translateY(-50%);
  width: 22px; height: 22px; border: none; border-radius: 50%;
  background: #94a3b8; color: #fff; font-size: 14px;
  cursor: pointer; line-height: 1; padding: 0;
  display: flex; align-items: center; justify-content: center;
}
.material-search-clear:hover { background: #64748b; }
.material-search-input-wrap.focused { box-shadow: 0 0 0 2px rgba(59,130,246,0.18); border-color: #3b82f6; }
.norm-dropdown {
  position: absolute;
  top: calc(100% + 4px);
  left: 0;
  right: 0;
  background: #fff;
  border: 1px solid #cbd5e1;
  border-radius: 6px;
  box-shadow: 0 6px 16px rgba(15,23,42,0.12);
  z-index: 30;
  max-height: 360px;
  overflow-y: auto;
  padding: 4px 0;
}
.norm-dropdown-loading, .norm-dropdown-empty {
  padding: 10px 12px;
  font-size: 12px;
  color: #64748b;
  font-style: italic;
}
.norm-dropdown-section-title {
  padding: 6px 12px 4px;
  font-size: 10px;
  color: #64748b;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  background: #f8fafc;
  border-top: 1px solid #f1f5f9;
}
.norm-dropdown-section-title:first-child { border-top: none; }
.norm-dropdown-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 6px 12px;
  cursor: pointer;
  font-size: 12px;
  color: #0f172a;
}
.norm-dropdown-item:hover, .norm-dropdown-item.focused {
  background: #eff6ff;
}
.norm-dropdown-item.dimmed { color: #94a3b8; }
.norm-dropdown-breed {
  flex: 1;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.norm-dropdown-meta {
  font-size: 11px;
  color: #64748b;
  background: #f1f5f9;
  padding: 1px 6px;
  border-radius: 3px;
  white-space: nowrap;
}
.material-search-hint {
  font-size: 11px; color: var(--text-3, #94a3b8);
  white-space: nowrap;
}
.material-bar-empty {
  padding: 10px;
  font-size: 12px;
  color: var(--text-3, #94a3b8);
  font-style: italic;
}

/* attr_key chip 栏（多选，仿 material-bar 风格） */
.attr-bar {
  display: flex; flex-wrap: wrap; align-items: center; gap: 6px;
  margin: -4px 0 12px;
  padding: 6px 12px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
}
.attr-bar-label {
  font-size: 11px; color: #64748b; font-weight: 600;
  margin-right: 4px;
}
.attr-chip {
  display: inline-block; padding: 3px 9px; border-radius: 3px;
  font-size: 11px; background: #f1f5f9; color: #94a3b8;
  cursor: pointer; border: 1px solid transparent;
  transition: all 0.15s;
}
.attr-chip:hover { border-color: #cbd5e1; }
.attr-chip.active {
  background: #ecfdf5; color: #047857;
  border-color: #6ee7b7; font-weight: 500;
}
.attr-bar-hint {
  margin-left: auto; font-size: 10px; color: #94a3b8;
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

/* 图表顶部工具栏：聚焦 pill + 导出按钮 */
.chart-toolbar {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 10px;
  flex-wrap: wrap;
}
.export-bar {
  display: inline-flex;
  gap: 6px;
  margin-left: auto;
}
.export-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 4px 10px;
  background: #fff;
  border: 1px solid #cbd5e1;
  border-radius: 4px;
  font-size: 11px;
  color: #475569;
  cursor: pointer;
  transition: all 0.15s;
}
.export-btn:hover {
  border-color: #2563eb;
  color: #1d4ed8;
  background: #eff6ff;
}

/* 聚焦 pill（P0-#1 主次曲线分层） */
.focus-pill {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 5px 6px 5px 12px;
  background: #fef3c7;
  border: 1px solid #fde68a;
  border-radius: 16px;
  font-size: 12px;
  color: #78350f;
  margin-bottom: 10px;
}
.focus-pill strong { color: #92400e; }
.focus-clear {
  width: 20px;
  height: 20px;
  border: none;
  border-radius: 50%;
  background: #f59e0b;
  color: #fff;
  font-size: 14px;
  line-height: 1;
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 0;
}
.focus-clear:hover { background: #d97706; }
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
.cell-material { color: #0f172a; font-weight: 500; min-width: 180px; vertical-align: middle; }
.cell-material-meta { font-size: 10px; color: #94a3b8; font-weight: 400; margin-top: 2px; }
.cell-spec { color: #475569; min-width: 100px; max-width: 200px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.cell-unit { color: #64748b; }
.cell-price { text-align: right; min-width: 80px; }
.cell-price .price-val { font-weight: 600; color: #0f172a; font-variant-numeric: tabular-nums; }
.cell-price .price-meta { font-size: 10px; color: #94a3b8; }
.cell-trend { text-align: right; }
.trend-pct { font-weight: 600; font-variant-numeric: tabular-nums; padding: 2px 8px; border-radius: 3px; }
.trend-pct.trend-up { color: #dc2626; background: #fef2f2; }
.trend-pct.trend-down { color: #16a34a; background: #f0fdf4; }
.no-data { color: #cbd5e1; }
.row-empty { background: #fafafa; }
</style>