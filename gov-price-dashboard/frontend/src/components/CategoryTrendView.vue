<template>
  <div class="cat-trend-page">
    <!-- 筛选条 -->
    <div class="filter-bar">
      <!-- 2026-07-09 去城市化：城市控件移除，仅按 normalized_breed 跨城归一（全国聚合） -->
      <CustomSelect v-model="periodsLimit" :options="periodOptions" placeholder="期数" />
      <CustomSelect v-model="topSpecs" :options="topSpecsOptions" placeholder="热力图规格数" />
    </div>

    <!-- 品类输入 + 自动建议 -->
    <div class="cat-search-row">
      <div class="cat-search-input-wrap" :class="{ focused: dropdownOpen }">
        <input
          v-model="catInput"
          type="text"
          class="cat-search-input"
          placeholder="输入品类名（例：热轧带肋钢筋、PE给水管、PPR管 · 跨城 NORM）"
          @input="onInputChange"
          @focus="dropdownOpen = true"
          @blur="setTimeout(() => dropdownOpen = false, 200)"
          @keydown.down.prevent="moveFocus(1)"
          @keydown.up.prevent="moveFocus(-1)"
          @keydown.enter.prevent="pickFocused()"
          @keydown.esc="dropdownOpen = false"
        />
        <button v-if="catInput" class="clear-btn" @click="clearInput()" title="清除">×</button>

        <!-- NORM 跨城候选下拉 -->
        <div v-if="dropdownOpen && catInput.trim() && (candidates.length || loading)" class="dropdown">
          <div v-if="loading" class="dropdown-loading">⏳ 查询 NORM…</div>
          <template v-else-if="candidates.length">
            <div class="dropdown-section-title">🌐 跨城归一品类（{{ candidates.length }}）</div>
            <div
              v-for="(c, idx) in candidates.slice(0, 12)"
              :key="c.normalized_breed + '_cb'"
              class="dropdown-item"
              :class="{ focused: focusedIdx === idx }"
              @mousedown.prevent="pick(c)"
            >
              <span class="dropdown-breed">{{ c.normalized_breed }}</span>
              <span class="dropdown-meta">{{ c.cities.length }} 城 · {{ c.total_docs }} 样本</span>
            </div>
            <div v-if="candidates.length > 12" class="dropdown-more">还有 {{ candidates.length - 12 }} 个 →</div>
          </template>
        </div>
      </div>

      <button class="load-btn" :disabled="!catInput.trim() || loading" @click="loadData()">
        📊 查看品类趋势
      </button>
    </div>

    <!-- 加载/错误 -->
    <div v-if="loading" class="loading"><div class="loading-spinner"></div> 加载品类数据…</div>
    <div v-else-if="error" class="error">❌ {{ error }}</div>

    <!-- 主内容（已加载） -->
    <template v-else-if="data && data.normalized_breed">

      <!-- 品类元数据 -->
      <div class="cat-meta-card">
        <div class="cat-meta-left">
          <h3 class="cat-title">{{ data.normalized_breed }}</h3>
          <div v-if="data.l3_info && data.l3_info.l3_code" class="cat-l3">
            🏷️
            <span class="cat-l3-code">{{ data.l3_info.l3_code }}</span>
            <span class="cat-l3-name">{{ data.l3_info.name_l1 }} / {{ data.l3_info.name_l2 }} / <em>{{ data.l3_info.name_l3 }}</em></span>
            <span v-if="data.l3_info.gb_50500" class="cat-l3-gb">GB {{ data.l3_info.gb_50500 }}</span>
          </div>
          <div v-else class="cat-l3 cat-l3-empty">未挂载 L3 分类</div>
        </div>
        <div class="cat-meta-stats">
          <div class="meta-stat"><strong>{{ data.meta.spec_count }}</strong><span>规格型号</span></div>
          <div class="meta-stat"><strong>{{ data.meta.sample_count }}</strong><span>价格样本</span></div>
          <div class="meta-stat"><strong>{{ data.meta.city_count }}</strong><span>覆盖城市</span></div>
          <div class="meta-stat"><strong>{{ data.meta.periods_n }}</strong><span>业务期</span></div>
        </div>
      </div>

      <!-- 规格热力图 -->
      <div v-if="data.spec_keys.length" class="chart-card">
        <SectionHeader title="规格热力图" :subtitle="`x=业务期 · y=规格型号 · 色深=均价 · top ${topSpecs} 规格`" />
        <div ref="heatmapEl" class="chart-canvas heatmap-canvas"></div>
        <div class="chart-legend">
          💡 色深 = 该规格当期的均价（仅显示 top {{ topSpecs }} 规格，其余折叠为「其他规格」）
        </div>
      </div>
      <div v-else class="empty-block">该品类在选定时间窗内无价格数据</div>

      <!-- 价格带折线图 -->
      <div v-if="data.price_band.length" class="chart-card">
        <SectionHeader title="价格带" :subtitle="`min / max / avg 三线 · 含全部规格 · 反映该品类的整体价格区间走势`" />
        <div ref="bandEl" class="chart-canvas band-canvas"></div>
      </div>

      <!-- 规格分布表 -->
      <div v-if="data.spec_distribution.length" class="chart-card">
        <SectionHeader title="规格分布" :subtitle="`按样本量倒序，最多显示 top 30 · 含 min/max/avg 价格`" />
        <div class="spec-table-wrap">
          <table class="spec-table">
            <thead>
              <tr>
                <th>#</th>
                <th>规格</th>
                <th>样本数</th>
                <th>最低价</th>
                <th>均价</th>
                <th>最高价</th>
                <th>价差 (max - min)</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="(s, idx) in data.spec_distribution.slice(0, 30)" :key="s.spec">
                <td class="num">{{ idx + 1 }}</td>
                <td class="spec-name">{{ s.spec }}</td>
                <td class="num">{{ s.count }}</td>
                <td class="num">{{ s.min_price?.toLocaleString() }}</td>
                <td class="num highlight">{{ s.avg_price?.toLocaleString() }}</td>
                <td class="num">{{ s.max_price?.toLocaleString() }}</td>
                <td class="num">{{ ((s.max_price || 0) - (s.min_price || 0)).toLocaleString() }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>

      <!-- 同 L3 推荐 -->
      <div v-if="peers.length" class="chart-card">
        <SectionHeader title="同 L3 横向推荐" :subtitle="`${data.l3_info.name_l3 || '该章节'} 下其他品类 · 点击进入趋势 · 长按 shift 多选对比`" />
        <div class="peers-grid">
          <div
            v-for="p in peers"
            :key="p.normalized_breed"
            class="peer-chip"
            :class="{ active: compareSelection.includes(p.normalized_breed) }"
            @click="pickPeer(p.normalized_breed)"
          >
            <span class="peer-breed">{{ p.normalized_breed }}</span>
            <span class="peer-meta">{{ p.spec_count }} 规格 · {{ p.sample_count }} 样本</span>
          </div>
        </div>
        <div v-if="compareSelection.length >= 1" class="compare-action-bar">
          <span>已选 {{ compareSelection.length }} 个品类</span>
          <button class="compare-btn" :disabled="compareSelection.length < 2 || compareLoading" @click="goCompare">
            🔀 多品类对比（{{ compareSelection.length }}/4）
          </button>
        </div>
      </div>

      <!-- 导出 -->
      <div class="export-bar">
        <button class="export-btn" @click="exportHeatmapCsv()">📥 导出热力图 CSV</button>
        <button class="export-btn" @click="exportBandCsv()">📥 导出价格带 CSV</button>
      </div>

    </template>

    <!-- 空状态 -->
    <div v-else-if="!loading && !error" class="empty-block">
      👆 输入品类名（如「热轧带肋钢筋」「PE给水管」）开始查看品类级趋势
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, watch, onBeforeUnmount } from 'vue'
import axios from 'axios'
import { useEcharts } from '../composables/useEcharts'
import SectionHeader from './SectionHeader.vue'
import CustomSelect from './CustomSelect.vue'
import { exportCsvAsFile, withTimestamp } from '../composables/useExport.js'

const API = import.meta.env.VITE_API_URL || '/api'

// ── 基础选项（去城市化后仅保留期数与热力图规格数；2026-07-09） ──
const periodsLimit = ref('12')
const periodOptions = [
  { key: '6',  label: '最近 6 期' },
  { key: '12', label: '最近 12 期' },
  { key: '24', label: '最近 24 期' },
  { key: '36', label: '最近 36 期' },
]
// 2026-07-09 修复：CustomSelect.modelValue 限定 String（options.key 一致），保持类型一致
const topSpecs = ref('10')
const topSpecsOptions = [
  { key: '5',  label: 'top 5 规格' },
  { key: '10', label: 'top 10 规格' },
  { key: '20', label: 'top 20 规格' },
  { key: '30', label: 'top 30 规格' },
]

// ── 品类输入与候选 ──
const catInput = ref('')
const candidates = ref([])
const loading = ref(false)
const dropdownOpen = ref(false)
const focusedIdx = ref(0)
const error = ref('')
let searchTimer = null

function onInputChange() {
  clearTimeout(searchTimer)
  searchTimer = setTimeout(() => searchNorms(catInput.value), 300)
}

async function searchNorms(keyword) {
  const kw = (keyword || '').trim()
  if (!kw) { candidates.value = []; return }
  try {
    const { data: d } = await axios.get(`${API}/norm/breeds/search`, {
      params: { keyword: kw, limit: 20 },
    })
    candidates.value = d.ok ? (d.results || []) : []
    focusedIdx.value = 0
  } catch (e) {
    candidates.value = []
  }
}

function moveFocus(d) {
  if (!candidates.value.length) return
  focusedIdx.value = (focusedIdx.value + d + candidates.value.length) % candidates.value.length
}

function pickFocused() {
  if (candidates.value.length) pick(candidates.value[focusedIdx.value])
}

function pick(c) {
  catInput.value = c.normalized_breed
  dropdownOpen.value = false
  candidates.value = []
  loadData()
}

function clearInput() {
  catInput.value = ''
  candidates.value = []
  data.value = null
  error.value = ''
}

// ── 主数据 ──
const data = ref(null)
const peers = ref([])
const compareSelection = ref([])
const compareLoading = ref(false)

// ── 顶部统计 ──
const topStats = computed(() => {
  if (!data.value) return []
  return [
    { label: '品类', value: data.value.normalized_breed },
    { label: '规格数', value: data.value.meta.spec_count },
    { label: '样本数', value: data.value.meta.sample_count },
    { label: '覆盖城市', value: data.value.meta.city_count },
    { label: '业务期', value: data.value.meta.periods_n },
  ]
})

// ── 数据加载 ──
async function loadData() {
  if (!catInput.value.trim()) return
  loading.value = true
  error.value = ''
  data.value = null
  peers.value = []
  try {
    const { data: d } = await axios.get(`${API}/stats/category-trend`, {
      params: {
        // 2026-07-09 起：不传 city，默认全国跨城归一
        normalized_breed: catInput.value.trim(),
        periods: parseInt(periodsLimit.value, 10),
        top_specs: parseInt(topSpecs.value, 10),
      },
    })
    if (!d.ok) {
      error.value = d.error || '查询失败'
      return
    }
    data.value = d
    // 修复 v-if 嵌套 + nextTick 时序陷阱：nextTick 触发时 DOM 挂载但 layout 还没跑
    // ECharts init() 会拿到 offsetHeight=0 → 图表空白
    // setTimeout 80ms 等两帧后 layout/paint 完成再 init
    setTimeout(() => {
      try { renderHeatmap() } catch (e) { console.error('renderHeatmap failed:', e) }
      try { renderBand() } catch (e) { console.error('renderBand failed:', e) }
    }, 80)
    if (d.l3_info?.l3_code) {
      loadPeers(d.l3_info.l3_code)
    }
  } catch (e) {
    error.value = e.message || '网络错误'
  } finally {
    loading.value = false
  }
}

async function loadPeers(l3_code) {
  try {
    // 2026-07-09 起：不传 city，默认全国跨城归一
    const { data: d } = await axios.get(`${API}/stats/category-l3-peers`, {
      params: { l3_code, min_count: 3, limit: 30 },
    })
    if (d.ok && d.peers) {
      // 排除当前品类
      peers.value = d.peers.filter(p => p.normalized_breed !== data.value?.normalized_breed)
    }
  } catch (e) {
    peers.value = []
  }
}

// ── ECharts 渲染 ──
const heatmapEl = ref(null)
const bandEl = ref(null)
let heatmapInstance = null
let bandInstance = null

async function renderHeatmap() {
  if (!heatmapEl.value || !data.value?.spec_keys?.length) return
  if (heatmapInstance) heatmapInstance.dispose()
  const echarts = await useEcharts()
  heatmapInstance = echarts.init(heatmapEl.value)
  const periods = data.value.periods.map(p => p.label)
  const specs = data.value.spec_keys
  const heatmap = data.value.heatmap
  const heatmap_n = data.value.heatmap_n

  // 收集所有非空值用于视觉映射
  let allVals = []
  for (const row of heatmap) {
    for (const v of row) {
      if (typeof v === 'number') allVals.push(v)
    }
  }
  const minV = allVals.length ? Math.min(...allVals) : 0
  const maxV = allVals.length ? Math.max(...allVals) : 1

  const seriesData = []
  for (let i = 0; i < specs.length; i++) {
    for (let j = 0; j < periods.length; j++) {
      const v = heatmap[i][j]
      const n = heatmap_n[i][j]
      if (typeof v === 'number') {
        seriesData.push({
          value: [j, i, v, n],
          v: v,
          n: n,
        })
      }
    }
  }

  heatmapInstance.setOption({
    tooltip: {
      position: 'top',
      formatter: (p) => {
        const [j, i, v, n] = p.value
        return `<b>${specs[i]}</b><br/>${periods[j]}<br/>均价: <b>${v?.toLocaleString()}</b><br/>样本: ${n}`
      },
    },
    grid: { top: 10, left: 160, right: 30, bottom: 60 },
    xAxis: {
      type: 'category',
      data: periods,
      splitArea: { show: true },
      axisLabel: { rotate: 30, fontSize: 11 },
    },
    yAxis: {
      type: 'category',
      data: specs,
      splitArea: { show: true },
      axisLabel: { fontSize: 11 },
    },
    visualMap: {
      min: minV,
      max: maxV,
      calculable: true,
      orient: 'horizontal',
      left: 'center',
      bottom: 5,
      textStyle: { fontSize: 11 },
      inRange: { color: ['#fef3c7', '#fcd34d', '#fbbf24', '#f59e0b', '#dc2626'] },
    },
    series: [{
      type: 'heatmap',
      data: seriesData,
      label: {
        show: true,
        formatter: (p) => {
          const n = p.data.n
          return n > 0 ? `${p.data.v.toFixed(0)}` : ''
        },
        fontSize: 10,
      },
      emphasis: {
        itemStyle: { shadowBlur: 8, shadowColor: 'rgba(0,0,0,0.4)' },
      },
    }],
  })
}

async function renderBand() {
  if (!bandEl.value || !data.value?.price_band?.length) return
  if (bandInstance) bandInstance.dispose()
  const echarts = await useEcharts()
  bandInstance = echarts.init(bandEl.value)
  const periods = data.value.price_band.map(p => p.label)
  const minVals = data.value.price_band.map(p => p.min)
  const maxVals = data.value.price_band.map(p => p.max)
  const avgVals = data.value.price_band.map(p => p.avg)
  const counts = data.value.price_band.map(p => p.n_total)

  bandInstance.setOption({
    tooltip: {
      trigger: 'axis',
      formatter: (params) => {
        const idx = params[0].dataIndex
        const pb = data.value.price_band[idx]
        return `<b>${pb.period_start}</b><br/>最高: ${pb.max?.toLocaleString()}<br/>均价: ${pb.avg?.toLocaleString()}<br/>最低: ${pb.min?.toLocaleString()}<br/>样本: ${pb.n_total} · 规格: ${pb.spec_count}`
      },
    },
    legend: { top: 5 },
    grid: { top: 35, left: 60, right: 30, bottom: 30 },
    xAxis: { type: 'category', data: periods, axisLabel: { rotate: 30, fontSize: 11 } },
    yAxis: { type: 'value', name: '价格', nameTextStyle: { fontSize: 11 } },
    series: [
      {
        name: '最高', type: 'line', data: maxVals, smooth: true,
        lineStyle: { color: '#dc2626', width: 1.5 },
        itemStyle: { color: '#dc2626' },
        areaStyle: { color: 'rgba(220,38,38,0.06)' },
      },
      {
        name: '均价', type: 'line', data: avgVals, smooth: true,
        lineStyle: { color: '#2563eb', width: 2.5 },
        itemStyle: { color: '#2563eb' },
      },
      {
        name: '最低', type: 'line', data: minVals, smooth: true,
        lineStyle: { color: '#16a34a', width: 1.5 },
        itemStyle: { color: '#16a34a' },
        areaStyle: { color: 'rgba(22,163,74,0.06)' },
      },
    ],
  })
}

// ── 同 L3 peer 操作 ──
function pickPeer(breed) {
  const idx = compareSelection.value.indexOf(breed)
  if (idx >= 0) {
    compareSelection.value.splice(idx, 1)
  } else {
    if (compareSelection.value.length >= 4) {
      compareSelection.value.shift()
    }
    compareSelection.value.push(breed)
  }
}

function goCompare() {
  if (compareSelection.value.length < 2) return
  compareLoading.value = true
  const breedsParam = encodeURIComponent([data.value.normalized_breed, ...compareSelection.value].join(','))
  // 2026-07-09 去城市化：跳到 compare Panel 时不再传 city，由其走全国跨城
  const target = `${window.location.origin}/trend?compare=${breedsParam}&mode=compare`
  window.location.href = target
  setTimeout(() => compareLoading.value = false, 1500)
}

// ── 导出 ──
function exportHeatmapCsv() {
  if (!data.value) return
  const rows = [['period', ...data.value.spec_keys]]
  for (let j = 0; j < data.value.periods.length; j++) {
    const row = [data.value.periods[j].start]
    for (let i = 0; i < data.value.spec_keys.length; i++) {
      row.push(data.value.heatmap[i][j] ?? '')
    }
    rows.push(row)
  }
  const csv = rows.map(r => r.map(c => typeof c === 'string' && c.includes(',') ? `"${c}"` : c).join(',')).join('\n')
  // 2026-07-09 去城市化：csv 文件名去掉 city 段，用后端响应里的 label（"全国"）代替
  exportCsvAsFile(csv, `heatmap_${data.value.normalized_breed}_${data.value.label || 'nation'}_${withTimestamp()}.csv`)
}

function exportBandCsv() {
  if (!data.value) return
  const rows = [['period_start', 'min', 'avg', 'max', 'n_total', 'spec_count']]
  for (const pb of data.value.price_band) {
    rows.push([pb.period_start, pb.min, pb.avg, pb.max, pb.n_total, pb.spec_count])
  }
  const csv = rows.map(r => r.join(',')).join('\n')
  exportCsvAsFile(csv, `band_${data.value.normalized_breed}_${data.value.label || 'nation'}_${withTimestamp()}.csv`)
}

// ── 生命周期（2026-07-09 去城市化：loadCities 移除，无需加载城市列表） ──
onMounted(() => {
  window.addEventListener('resize', handleResize)
})
onBeforeUnmount(() => {
  if (heatmapInstance) heatmapInstance.dispose()
  if (bandInstance) bandInstance.dispose()
  window.removeEventListener('resize', handleResize)
})

function handleResize() {
  if (heatmapInstance) heatmapInstance.resize()
  if (bandInstance) bandInstance.resize()
}

watch([periodsLimit, topSpecs], () => {
  if (data.value) loadData()
})
</script>

<style scoped>
.cat-trend-page {
  padding: 16px 20px 80px;
  min-height: 100vh;
  color: #1e293b;
}

.filter-bar {
  display: flex;
  gap: 12px;
  align-items: center;
  margin: 12px 0;
  flex-wrap: wrap;
}

/* 2026-07-09 修复：CustomSelect.cs-wrapper 默认 width:100%，flex 容器里会撑满导致
   多个 select 上下堆叠。覆写为 auto 宽度，min-width 保证可点击区域 */
.filter-bar :deep(.cs-wrapper) {
  width: auto;
  flex: 0 0 auto;
  min-width: 200px;
}

.cat-search-row {
  display: flex;
  gap: 12px;
  margin: 16px 0;
  align-items: flex-start;
}

.cat-search-input-wrap {
  position: relative;
  flex: 1;
  min-width: 320px;
}
.cat-search-input {
  width: 100%;
  padding: 10px 36px 10px 14px;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  font-size: 14px;
  background: #fff;
  box-sizing: border-box;
}
.cat-search-input:focus {
  outline: none;
  border-color: #3b82f6;
  box-shadow: 0 0 0 3px rgba(59,130,246,0.1);
}
.clear-btn {
  position: absolute;
  right: 8px;
  top: 50%;
  transform: translateY(-50%);
  border: none;
  background: #e2e8f0;
  width: 22px;
  height: 22px;
  border-radius: 50%;
  cursor: pointer;
  font-size: 14px;
  line-height: 1;
  color: #64748b;
}
.clear-btn:hover { background: #cbd5e1; color: #0f172a; }

.dropdown {
  position: absolute;
  top: 100%;
  left: 0;
  right: 0;
  background: #fff;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  box-shadow: 0 4px 16px rgba(0,0,0,0.1);
  margin-top: 4px;
  z-index: 100;
  max-height: 360px;
  overflow-y: auto;
}
.dropdown-section-title {
  padding: 6px 12px;
  font-size: 11px;
  color: #64748b;
  background: #f8fafc;
  border-bottom: 1px solid #e2e8f0;
}
.dropdown-item {
  padding: 8px 12px;
  cursor: pointer;
  display: flex;
  justify-content: space-between;
  align-items: center;
  border-bottom: 1px solid #f1f5f9;
}
.dropdown-item:hover, .dropdown-item.focused { background: #eff6ff; }
.dropdown-item:last-child { border-bottom: none; }
.dropdown-breed { font-weight: 500; color: #1e293b; font-size: 13px; }
.dropdown-meta { font-size: 11px; color: #64748b; }
.dropdown-loading { padding: 12px; color: #64748b; font-size: 13px; text-align: center; }
.dropdown-more { padding: 6px 12px; font-size: 11px; color: #64748b; background: #f8fafc; }

.load-btn {
  padding: 10px 18px;
  background: #1d4ed8;
  color: #fff;
  border: none;
  border-radius: 6px;
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  white-space: nowrap;
}
.load-btn:hover:not(:disabled) { background: #1e40af; }
.load-btn:disabled { background: #94a3b8; cursor: not-allowed; }

.loading, .error, .empty-block {
  padding: 40px 20px;
  text-align: center;
  color: #64748b;
  background: #fff;
  border: 1px dashed #e2e8f0;
  border-radius: 6px;
  margin: 20px 0;
}
.error { color: #dc2626; }
.loading-spinner {
  display: inline-block;
  width: 18px;
  height: 18px;
  border: 2px solid #e2e8f0;
  border-top-color: #3b82f6;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
  vertical-align: middle;
  margin-right: 6px;
}
@keyframes spin { to { transform: rotate(360deg); } }

.cat-meta-card {
  background: linear-gradient(135deg, #eff6ff, #dbeafe);
  border: 1px solid #bfdbfe;
  border-radius: 8px;
  padding: 16px 20px;
  margin: 16px 0;
  display: flex;
  justify-content: space-between;
  align-items: center;
  flex-wrap: wrap;
  gap: 16px;
}
.cat-meta-left { flex: 1; min-width: 280px; }
.cat-title {
  margin: 0 0 6px;
  font-size: 18px;
  font-weight: 700;
  color: #1e3a8a;
}
.cat-l3 {
  font-size: 12px;
  color: #475569;
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  align-items: center;
}
.cat-l3-code {
  background: #1e40af;
  color: #fff;
  padding: 2px 6px;
  border-radius: 3px;
  font-family: 'JetBrains Mono', monospace;
  font-weight: 600;
}
.cat-l3-name em { font-style: normal; font-weight: 600; color: #1e40af; }
.cat-l3-gb {
  background: #fff;
  border: 1px solid #93c5fd;
  padding: 2px 6px;
  border-radius: 3px;
  color: #1e40af;
  font-family: 'JetBrains Mono', monospace;
  font-size: 11px;
}
.cat-l3-empty { color: #f59e0b; font-style: italic; }

.cat-meta-stats { display: flex; gap: 24px; }
.meta-stat { text-align: center; }
.meta-stat strong { display: block; font-size: 22px; color: #1e3a8a; }
.meta-stat span { font-size: 11px; color: #64748b; }

.chart-card {
  background: #fff;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  padding: 16px 20px;
  margin: 16px 0;
}
.chart-canvas { width: 100%; }
.heatmap-canvas { height: 360px; }
.band-canvas { height: 280px; }
.chart-legend {
  font-size: 11px;
  color: #94a3b8;
  padding-top: 8px;
  border-top: 1px solid #f1f5f9;
  margin-top: 8px;
}

.spec-table-wrap { overflow-x: auto; }
.spec-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}
.spec-table th {
  background: #f8fafc;
  padding: 8px 10px;
  text-align: left;
  font-size: 11px;
  color: #64748b;
  font-weight: 600;
  border-bottom: 1px solid #e2e8f0;
}
.spec-table td {
  padding: 6px 10px;
  border-bottom: 1px solid #f1f5f9;
}
.spec-table td.num { text-align: right; font-family: 'JetBrains Mono', monospace; }
.spec-table td.highlight { color: #1e40af; font-weight: 600; }
.spec-table td.spec-name { font-family: 'JetBrains Mono', monospace; font-weight: 500; }
.spec-table tr:hover td { background: #f8fafc; }

.peers-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 8px;
}
.peer-chip {
  padding: 8px 12px;
  background: #fff;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  cursor: pointer;
  display: flex;
  flex-direction: column;
  transition: all 0.15s;
}
.peer-chip:hover { border-color: #3b82f6; background: #eff6ff; }
.peer-chip.active {
  background: #1d4ed8;
  color: #fff;
  border-color: #1d4ed8;
}
.peer-chip.active .peer-meta { color: #dbeafe; }
.peer-breed { font-size: 13px; font-weight: 500; }
.peer-meta { font-size: 11px; color: #64748b; margin-top: 2px; }

.compare-action-bar {
  margin-top: 12px;
  padding: 10px 14px;
  background: #eff6ff;
  border: 1px solid #bfdbfe;
  border-radius: 6px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 13px;
  color: #1e40af;
}
.compare-btn {
  padding: 6px 14px;
  background: #1d4ed8;
  color: #fff;
  border: none;
  border-radius: 4px;
  cursor: pointer;
  font-size: 12px;
  font-weight: 500;
}
.compare-btn:hover:not(:disabled) { background: #1e40af; }
.compare-btn:disabled { background: #94a3b8; cursor: not-allowed; }

.export-bar {
  display: flex;
  gap: 8px;
  margin: 20px 0;
}
.export-btn {
  padding: 8px 14px;
  background: #fff;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  cursor: pointer;
  font-size: 12px;
  color: #475569;
}
.export-btn:hover { background: #f8fafc; border-color: #cbd5e1; }
</style>