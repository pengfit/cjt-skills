<template>
  <div class="compare-panel">
    <!-- 筛选条 -->
    <div class="compare-filter-bar">
      <div class="filter-group-breed">
        <label class="filter-label">品种</label>
        <input
          v-model="breedInput"
          type="text"
          class="breed-input"
          placeholder="输入品种名（如：热轧带肋钢筋、HRB400、商品混凝土）"
          @keydown.enter="doCompare"
        />
        <div v-if="breedSuggestions.length" class="suggestions">
          <span
            v-for="s in breedSuggestions"
            :key="s"
            class="suggestion-chip"
            @click="pickBreed(s)"
          >{{ s }}</span>
        </div>
      </div>
      <div class="filter-group-cities">
        <label class="filter-label">
          城市（多选，最多 6 个） <span class="city-count">{{ selectedCities.length }}/6</span>
        </label>
        <div class="city-chip-row">
          <span
            v-for="o in cityOptions"
            :key="o.key"
            class="city-chip"
            :class="{ active: selectedCities.includes(o.key) }"
            :style="{ '--chip-color': o.color }"
            @click="toggleCity(o.key)"
          >{{ o.label }}</span>
        </div>
      </div>
      <div class="filter-group-row">
        <div class="filter-mini">
          <label class="filter-mini-label">单位（约束，可选）</label>
          <select v-model="unitConstraint" class="filter-select">
            <option value="">不限</option>
            <option v-for="u in commonUnits" :key="u" :value="u">{{ u }}</option>
          </select>
        </div>
        <div class="filter-mini">
          <label class="filter-mini-label">期数</label>
          <select v-model.number="periods" class="filter-select">
            <option :value="6">最近 6 期</option>
            <option :value="12">最近 12 期</option>
            <option :value="24">最近 24 期</option>
            <option :value="36">最近 36 期</option>
          </select>
        </div>
        <div class="filter-mini">
          <label class="filter-mini-label">Top spec/城</label>
          <select v-model.number="topSpecs" class="filter-select">
            <option :value="1">1</option>
            <option :value="2">2</option>
            <option :value="3">3</option>
            <option :value="5">5</option>
            <option :value="8">8</option>
          </select>
        </div>
        <button
          class="btn-compare"
          :disabled="loading || !breedInput.trim() || selectedCities.length === 0"
          @click="doCompare"
        >
          {{ loading ? '加载中…' : '开始对比' }}
        </button>
      </div>
    </div>

    <!-- 错误 -->
    <div v-if="error" class="compare-error">
      <span class="error-icon">⚠️</span>
      <span>{{ error }}</span>
      <button class="btn-retry" @click="doCompare">重试</button>
    </div>

    <!-- 空状态 -->
    <div v-if="!breedInput.trim() && !data" class="empty-hint">
      <div class="empty-icon">🔍</div>
      <div class="empty-text">输入品种名 + 选若干城市 → 看跨城价格走势对比</div>
      <div v-if="topBreedsByCity.length" class="quick-breeds">
        <div class="quick-breeds-label">热门品种（按出现城市数倒序）：</div>
        <div class="quick-breeds-row">
          <span
            v-for="b in topBreedsByCity.slice(0, 12)"
            :key="b.breed"
            class="quick-breed-chip"
            :title="`覆盖 ${b.city_count} 个城市`"
            @click="quickFill(b.breed)"
          >{{ b.breed }} <small>({{ b.city_count }}城)</small></span>
        </div>
      </div>
    </div>

    <!-- 主视图 -->
    <div v-if="data && data.ok" class="compare-content">
      <!-- 关键统计 -->
      <div class="summary-bar">
        <div class="summary-cell">
          <span class="summary-label">📅 同期对齐</span>
          <span class="summary-value">{{ data.aligned_periods.length }} 期</span>
          <span class="summary-hint">已对齐所有城市时间轴</span>
        </div>
        <div class="summary-cell" v-for="s in data.series" :key="s.city" :style="{ '--accent': s.color }">
          <span class="summary-label" :style="{ color: s.color }">● {{ s.label }}</span>
          <span class="summary-value">
            <template v-if="s.n_total">
              {{ latestPrice(s) ?? '—' }} <small>{{ s.unit_used || '—' }}</small>
            </template>
            <template v-else>无数据</template>
          </span>
          <span class="summary-hint" v-if="s.n_total">
            {{ s.n_total }} 样本 · {{ s.spec_groups.length }} spec
            <em v-if="s.missing_periods.length">漏 {{ s.missing_periods.length }} 期</em>
          </span>
        </div>
      </div>

      <!-- spec 选择（多选，按城市分别用 first spec） -->
      <div v-if="commonSpecKeys.length" class="spec-bar">
        <span class="spec-label">📐 公共规格（同 spec_key 跨城绘线，可多选）：</span>
        <span
          v-for="sk in commonSpecKeys"
          :key="sk.key"
          class="spec-chip"
          :class="{ active: selectedSpecKeys.has(sk.key) }"
          :title="`${sk.total} 样本`"
          @click="toggleSpecKey(sk.key)"
        >{{ sk.label }} <small>({{ sk.total }})</small></span>
        <span class="spec-bar-hint">{{ selectedSpecKeys.size }} / {{ commonSpecKeys.length }} 选中</span>
      </div>

      <!-- 主图：每城市 × 每spec_key 一条线 -->
      <div class="compare-card">
        <div ref="chartEl" class="compare-chart"></div>
      </div>

      <!-- 同期对比表 -->
      <SectionHeader title="同期价对比表（按周期对齐）" dot-color="blue" :subtitle="`每个城市在每个对齐期的均价`" />
      <div class="period-table-scroll">
        <table class="period-table">
          <thead>
            <tr>
              <th class="th-period">周期</th>
              <th
                v-for="s in data.series"
                :key="s.city"
                :style="{ color: s.color }"
                class="th-city"
              >{{ s.label }} <small v-if="s.unit_used">({{ s.unit_used }})</small></th>
              <th class="th-spread">价差区间</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(p, idx) in data.aligned_periods" :key="p.start">
              <td class="td-period">{{ p.label }}</td>
              <td v-for="s in data.series" :key="s.city" class="td-price" :class="{ missing: missingForCityPeriod(s, p.start) }">
                <template v-if="getPriceFor(s, p.start) != null">
                  <div class="price-val" :style="{ color: s.color }">{{ getPriceFor(s, p.start).toFixed(2) }}</div>
                  <div class="price-meta">n={{ getPriceForCount(s, p.start) }}</div>
                </template>
                <span v-else class="no-data">—</span>
              </td>
              <td class="td-spread">
                <template v-if="spreadFor(p.start)">
                  <span class="spread-val">{{ spreadFor(p.start).min.toFixed(2) }} – {{ spreadFor(p.start).max.toFixed(2) }}</span>
                  <span class="spread-pct" :class="spreadClass(p.start)">
                    {{ spreadFor(p.start).spread_pct.toFixed(1) }}%
                  </span>
                </template>
                <span v-else class="no-data">—</span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- 每城市 spec 明细（折叠区） -->
      <SectionHeader
        title="各城市规格明细（spec 拆分）"
        dot-color="green"
        :subtitle="`每个城市的 top ${topSpecs} 个 spec，及其按时序的 min/max/avg`"
      />
      <div class="city-detail-grid">
        <div v-for="s in data.series" :key="s.city" class="city-detail" :style="{ '--accent': s.color }">
          <div class="city-detail-head" :style="{ background: s.color }">
            <span class="city-name">{{ s.label }}</span>
            <span class="city-meta">
              <em v-if="s.unit_fallback" :title="`'${s.unit_used}' 非用户指定，按样本数自动选取`">自动</em>
              {{ s.n_total }} 样本
              <small v-if="s.missing_periods.length" class="missing-tag">漏 {{ s.missing_periods.length }} 期</small>
            </span>
          </div>
          <div v-if="!s.spec_groups.length" class="city-empty">该城市无数据</div>
          <table v-else class="city-spec-table">
            <thead>
              <tr>
                <th>规格</th>
                <th v-for="p in data.aligned_periods" :key="p.start" :title="p.label">
                  {{ p.start.slice(5) }}
                </th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="sg in s.spec_groups" :key="sg.spec_key">
                <td class="td-spec-label" :title="sg.spec_label">
                  {{ sg.spec_label }} <small class="align-tag align-{{ sg.align_method }}">{{ sg.align_method }}</small>
                </td>
                <td v-for="p in data.aligned_periods" :key="p.start" class="td-spec-price">
                  <template v-if="getSpecPt(sg, p.start)">
                    <div class="sp-val">{{ getSpecPt(sg, p.start).avg.toFixed(0) }}</div>
                    <div class="sp-meta">{{ getSpecPt(sg, p.start).min }}~{{ getSpecPt(sg, p.start).max }} · n={{ getSpecPt(sg, p.start).n }}</div>
                  </template>
                  <span v-else class="no-data">—</span>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, watch, nextTick, onBeforeUnmount } from 'vue'
import axios from 'axios'
import * as echarts from 'echarts'
import SectionHeader from './SectionHeader.vue'

const API = import.meta.env.VITE_API_URL || '/api'

// 状态
const breedInput = ref('热轧带肋钢筋')      // 默认值便于演示
const breedSuggestions = ref([])
const cityOptions = ref([])                  // 全部可用城市
const selectedCities = ref([])               // 选中城市
const unitConstraint = ref('')                // 单位约束
const periods = ref(6)
const topSpecs = ref(3)
const loading = ref(false)
const error = ref('')
const data = ref(null)                        // API 返回
const chartEl = ref(null)
let chartInstance = null

const commonUnits = ref(['t', 'm', 'kg', 'm³', 'm²', '根', '只', '块'])
const topBreedsByCity = ref([])               // 用于空状态热门品种

// 用户选的 spec_key
const selectedSpecKeys = ref(new Set())

// 颜色分配（每城市一条线）— 与 API 返回 color 同步
const COLOR_POOL_OVERRIDE = {}

// 计算属性
const selectedCityCfgs = computed(() =>
  cityOptions.value.filter(c => selectedCities.value.includes(c.key))
)

// 跨城公共规格（同 spec_key 在 ≥ 2 城市出现）
const commonSpecKeys = computed(() => {
  if (!data.value) return []
  const counts = new Map()  // spec_key -> { label, total }
  for (const s of data.value.series) {
    for (const sg of s.spec_groups) {
      if (!selectedSpecKeys.value.size || selectedSpecKeys.value.has(sg.spec_key)) {
        const cur = counts.get(sg.spec_key) || { label: sg.spec_label, total: 0, cities: 0 }
        cur.total += sg.n_total
        cur.cities += 1
        counts.set(sg.spec_key, cur)
      }
    }
  }
  const arr = []
  for (const [key, info] of counts) {
    arr.push({ key, label: info.label, total: info.total, cities: info.cities })
  }
  // 优先按城市数，再按样本数
  arr.sort((a, b) => (b.cities - a.cities) || (b.total - a.total))
  return arr
})

// ── 方法 ──
async function loadCityOptions() {
  try {
    const { data: d } = await axios.get(`${API}/skill-registry`)
    cityOptions.value = (d?.skills || [])
      .filter(s => s.dws_index)  // 只要有 DWS 索引的
      .map(s => {
        // 用省份色（如无则灰）
        const colors = {
          '陕西':'#dc2626', '四川':'#2563eb', '重庆':'#16a34a',
          '山东':'#ea580c', '河南':'#7c3aed', '湖南':'#0891b2',
          '江西':'#db2777', '宁夏':'#65a30d', '青海':'#9333ea',
          '新疆':'#0d9488', '内蒙古':'#e11d48', '海南':'#4f46e5',
        }
        return {
          key: s.key,
          label: s.label || s.key,
          province: s.province || '',
          color: colors[s.province] || colors[s.label] || '#64748b',
        }
      })
      .sort((a, b) => a.label.localeCompare(b.label, 'zh-CN'))
    // 默认选前 2 个 DWS 存在的城市
    if (!selectedCities.value.length) {
      const withDws = cityOptions.value.filter(c => c.key === 'hainan' || c.key === 'chongqing')
      selectedCities.value = withDws.slice(0, 2).map(c => c.key) || cityOptions.value.slice(0, 2).map(c => c.key)
    }
    await loadTopBreeds()
  } catch (e) {
    error.value = '加载城市列表失败：' + e.message
  }
}

async function loadTopBreeds() {
  // 用 search 拉高频品种（粗略；实际跨城要 JOIN，但 MVP 用搜索代替）
  try {
    const { data: d } = await axios.get(`${API}/search?page=1&page_size=20`)
    const breeds = d?.data || []
    // 按品种名汇总（province 数 + 文档数）
    const byBreed = new Map()
    for (const h of breeds) {
      const k = h.breed
      if (!byBreed.has(k)) byBreed.set(k, { breed: k, count: 0, provinces: new Set() })
      const cur = byBreed.get(k)
      cur.count += 1
      if (h.province) cur.provinces.add(h.province)
    }
    const arr = [...byBreed.values()].map(v => ({
      ...v, provinces: undefined, city_count: v.provinces.size,
    }))
    arr.sort((a, b) => (b.city_count - a.city_count) || (b.count - a.count))
    topBreedsByCity.value = arr
  } catch (e) {
    console.warn('loadTopBreeds failed:', e)
  }
}

function toggleCity(key) {
  const i = selectedCities.value.indexOf(key)
  if (i >= 0) selectedCities.value.splice(i, 1)
  else if (selectedCities.value.length < 6) selectedCities.value.push(key)
}

function quickFill(breed) {
  breedInput.value = breed
  doCompare()
}

function pickBreed(s) {
  breedInput.value = s
  breedSuggestions.value = []
}

async function doCompare() {
  if (!breedInput.value.trim() || selectedCities.value.length === 0) return
  loading.value = true
  error.value = ''
  try {
    const url = `${API}/stats/price-trend-compare?` +
      new URLSearchParams({
        breed: breedInput.value.trim(),
        cities: selectedCities.value.join(','),
        unit: unitConstraint.value || '',
        periods: String(periods.value),
        top_specs: String(topSpecs.value),
      })
    const { data: d } = await axios.get(url)
    if (!d.ok) throw new Error(d.error || 'API 返回错误')
    data.value = d
    // 默认全选公共 spec_key
    selectedSpecKeys.value = new Set(d.series.flatMap(s => s.spec_groups.map(g => g.spec_key)))
    await nextTick()
    renderChart()
  } catch (e) {
    error.value = e.message
  } finally {
    loading.value = false
  }
}

function toggleSpecKey(key) {
  const s = new Set(selectedSpecKeys.value)
  if (s.has(key)) s.delete(key); else s.add(key)
  selectedSpecKeys.value = s
  // 不重新发 API，前端过滤即可
  renderChart()
}

// 视图工具
function latestPrice(s) {
  // 取该城市最大的 spec 在最近一期的价格
  if (!s.spec_groups.length) return null
  const all_pts = s.spec_groups.flatMap(g => g.points)
  if (!all_pts.length) return null
  all_pts.sort((a, b) => (a.period_start < b.period_start ? 1 : -1))
  const last = all_pts[0].avg
  if (Math.abs(last) >= 1000) return last.toFixed(0)
  return last.toFixed(2)
}

function getPriceFor(s, periodStart) {
  if (!s.spec_groups.length) return null
  const pts = s.spec_groups.flatMap(g => g.points).filter(p => p.period_start === periodStart)
  if (!pts.length) return null
  const sum = pts.reduce((acc, p) => acc + p.avg * p.n, 0)
  const cnt = pts.reduce((acc, p) => acc + p.n, 0)
  return cnt ? sum / cnt : null
}

function getPriceForCount(s, periodStart) {
  if (!s.spec_groups.length) return 0
  return s.spec_groups.flatMap(g => g.points).filter(p => p.period_start === periodStart).reduce((acc, p) => acc + p.n, 0)
}

function missingForCityPeriod(s, periodStart) {
  return s.missing_periods.includes(periodStart)
}

function spreadFor(periodStart) {
  // 价差区间 + spread%
  const prices = []
  for (const s of data.value.series) {
    const p = getPriceFor(s, periodStart)
    if (p != null) prices.push({ city: s.label, price: p, color: s.color })
  }
  if (prices.length < 2) return null
  const vals = prices.map(p => p.price)
  const min = Math.min(...vals)
  const max = Math.max(...vals)
  const mid = vals.reduce((a, b) => a + b, 0) / vals.length
  return {
    min, max,
    spread_pct: mid ? ((max - min) / mid) * 100 : 0,
    cities: prices,
  }
}

function spreadClass(periodStart) {
  const s = spreadFor(periodStart)
  if (!s) return ''
  if (s.spread_pct >= 20) return 'spread-huge'
  if (s.spread_pct >= 5) return 'spread-mid'
  return 'spread-low'
}

function getSpecPt(sg, periodStart) {
  return sg.points.find(p => p.period_start === periodStart)
}

// ── 主图渲染 ──
function renderChart() {
  if (!chartEl.value || !data.value?.aligned_periods?.length) return
  if (!chartInstance) {
    chartInstance = echarts.init(chartEl.value)
    window.addEventListener('resize', chartInstance.resize)
  }
  const periodLabels = data.value.aligned_periods.map(p => p.label)
  const selected = selectedSpecKeys.value.size === 0
    ? new Set(data.value.series.flatMap(s => s.spec_groups.map(g => g.spec_key)))
    : selectedSpecKeys.value

  // 选最多 1 个 spec_key 作为主绘线（避免挤）；多选时只绘第一个
  // 否则每城市 × 每 spec 一条线会太多
  const pickedSpecKey = [...selected][0]

  const series = []
  for (const s of data.value.series) {
    if (!s.spec_groups.length) continue
    // 优先用 pickedSpecKey，否则取第一个
    const sg = s.spec_groups.find(g => g.spec_key === pickedSpecKey) || s.spec_groups[0]
    // 注意：不能用 const data = ...（与外层 ref(data) 同名触发 TDZ；ref 遮蔽导致 ReferenceError）
    const points = data.value.aligned_periods.map(p => {
      const pt = getSpecPt(sg, p.start)
      if (!pt) return null
      return {
        value: pt.avg,
        avg: pt.avg, min: pt.min, max: pt.max, n: pt.n,
        spec_label: sg.spec_label,
      }
    })
    series.push({
      name: `${s.label} · ${sg.spec_label}`,
      type: 'line',
      data: points,
      smooth: false,
      symbol: 'circle',
      symbolSize: 8,
      lineStyle: { width: 2.5, color: s.color },
      itemStyle: { color: s.color },
      emphasis: { focus: 'series' },
      connectNulls: true,
    })
  }

  // 同期 overall（每城市加权均价，不分 spec）
  for (const s of data.value.series) {
    if (!s.spec_groups.length) continue
    const overall = data.value.aligned_periods.map(p => {
      const pts = s.spec_groups.flatMap(g => g.points).filter(pt => pt.period_start === p.start)
      if (!pts.length) return null
      const sum = pts.reduce((acc, pt) => acc + pt.avg * pt.n, 0)
      const cnt = pts.reduce((acc, pt) => acc + pt.n, 0)
      return cnt ? { value: sum / cnt, avg: sum / cnt, n: cnt, overall: true } : null
    })
    series.push({
      name: `${s.label} · 同期整体`,
      type: 'line',
      data: overall,
      smooth: false,
      symbol: 'diamond',
      symbolSize: 6,
      lineStyle: { width: 1.5, color: s.color, type: 'dashed', opacity: 0.5 },
      itemStyle: { color: s.color, opacity: 0.5 },
      emphasis: { focus: 'series' },
      connectNulls: true,
    })
  }

  const option = {
    tooltip: {
      trigger: 'axis',
      backgroundColor: 'rgba(255,255,255,0.98)',
      borderColor: '#cbd5e1',
      textStyle: { color: '#0f172a' },
      formatter: (params) => {
        const head = params[0]?.axisValue || ''
        let html = `<b>${head}</b><br/>`
        for (const p of params) {
          const d = p.data
          if (!d) {
            html += `${p.marker} ${p.seriesName}: <em>无数据</em><br/>`
            continue
          }
          const v = d.avg.toFixed(2)
          const tail = d.overall ? '' : ` <small>(min ${d.min} – max ${d.max})</small>`
          html += `${p.marker} ${p.seriesName}: <b>${v}</b>${tail}<br/>`
        }
        return html
      }
    },
    legend: { top: 0, type: 'scroll', textStyle: { color: '#475569' } },
    grid: { left: 70, right: 24, top: 50, bottom: 70 },
    xAxis: {
      type: 'category', data: periodLabels,
      axisLine: { lineStyle: { color: '#cbd5e1' } },
    },
    yAxis: {
      type: 'value', name: '均价',
      nameTextStyle: { color: '#64748b' },
      axisLabel: { color: '#475569' },
      splitLine: { lineStyle: { color: '#e2e8f0' } },
    },
    series,
  }
  chartInstance.setOption(option, true)
}

// watch 渲染
watch(() => data.value?.series, () => nextTick(renderChart), { deep: true })

// 生命周期
onMounted(async () => {
  await loadCityOptions()
})
onBeforeUnmount(() => {
  if (chartInstance) chartInstance.dispose()
})
</script>

<style scoped>
.compare-panel {
  padding: 4px 0 80px;
}

.compare-filter-bar {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 14px;
  margin: 12px 0;
  background: #fff;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  padding: 12px 16px;
}
.filter-label {
  display: block;
  font-size: 12px;
  font-weight: 600;
  color: #475569;
  margin-bottom: 6px;
}
.city-count {
  font-size: 10px;
  color: #94a3b8;
  margin-left: 4px;
}
.breed-input {
  width: 100%;
  box-sizing: border-box;
  padding: 8px 12px;
  border: 1px solid #cbd5e1;
  border-radius: 6px;
  font-size: 13px;
  outline: none;
  transition: border-color 0.15s, box-shadow 0.15s;
}
.breed-input:focus {
  border-color: #3b82f6;
  box-shadow: 0 0 0 2px rgba(59, 130, 246, 0.15);
}
.suggestions {
  margin-top: 6px;
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}
.suggestion-chip {
  font-size: 11px;
  padding: 2px 8px;
  background: #f1f5f9;
  color: #475569;
  border-radius: 3px;
  cursor: pointer;
}
.suggestion-chip:hover { background: #dbeafe; color: #1d4ed8; }

.city-chip-row {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.city-chip {
  --chip-color: #64748b;
  display: inline-block;
  padding: 4px 12px;
  border-radius: 4px;
  font-size: 12px;
  background: #f1f5f9;
  color: var(--chip-color);
  border: 1.5px solid transparent;
  cursor: pointer;
  transition: all 0.15s;
}
.city-chip:hover {
  border-color: var(--chip-color);
}
.city-chip.active {
  background: var(--chip-color);
  color: #fff;
  font-weight: 500;
}

.filter-group-row {
  grid-column: 1 / 3;
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  align-items: flex-end;
  padding-top: 10px;
  border-top: 1px dashed #e2e8f0;
}
.filter-mini { display: flex; flex-direction: column; }
.filter-mini-label {
  font-size: 11px;
  color: #64748b;
  margin-bottom: 2px;
}
.filter-select {
  padding: 6px 10px;
  border: 1px solid #cbd5e1;
  border-radius: 4px;
  font-size: 12px;
  background: #fff;
  color: #0f172a;
}
.btn-compare {
  margin-left: auto;
  padding: 8px 20px;
  background: linear-gradient(135deg, #2563eb, #1d4ed8);
  color: #fff;
  border: none;
  border-radius: 6px;
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.15s;
}
.btn-compare:hover:not(:disabled) {
  box-shadow: 0 2px 6px rgba(37, 99, 235, 0.3);
  transform: translateY(-1px);
}
.btn-compare:disabled { opacity: 0.4; cursor: not-allowed; }

.empty-hint {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
  padding: 60px 20px;
  background: #fff;
  border: 1px dashed #cbd5e1;
  border-radius: 8px;
  margin: 12px 0;
}
.empty-icon { font-size: 48px; }
.empty-text { font-size: 13px; color: #64748b; }
.quick-breeds { width: 100%; max-width: 720px; }
.quick-breeds-label { font-size: 11px; color: #94a3b8; text-align: left; margin-bottom: 6px; }
.quick-breeds-row { display: flex; flex-wrap: wrap; gap: 6px; }
.quick-breed-chip {
  font-size: 12px;
  padding: 4px 10px;
  background: #eff6ff;
  color: #1d4ed8;
  border: 1px solid #bfdbfe;
  border-radius: 4px;
  cursor: pointer;
  transition: all 0.15s;
}
.quick-breed-chip:hover { background: #dbeafe; }
.quick-breed-chip small { color: #64748b; margin-left: 4px; }

.compare-error {
  display: flex;
  gap: 10px;
  align-items: center;
  background: #fef2f2;
  border: 1px solid #fca5a5;
  color: #991b1b;
  padding: 10px 14px;
  border-radius: 6px;
  margin: 12px 0;
}
.error-icon { font-size: 18px; }
.btn-retry {
  margin-left: auto;
  padding: 4px 12px;
  background: #dc2626;
  color: #fff;
  border: none;
  border-radius: 4px;
  cursor: pointer;
}

.summary-bar {
  display: grid;
  grid-template-columns: auto repeat(auto-fit, minmax(180px, 1fr));
  gap: 12px;
  margin: 12px 0;
}
.summary-cell {
  background: #fff;
  border: 1px solid #e2e8f0;
  border-left: 3px solid #64748b;
  border-radius: 6px;
  padding: 10px 14px;
  --accent: #64748b;
  border-left-color: var(--accent);
}
.summary-label {
  font-size: 11px;
  color: #475569;
  font-weight: 600;
}
.summary-value {
  display: block;
  font-size: 18px;
  font-weight: 700;
  color: #0f172a;
  margin: 4px 0;
  font-variant-numeric: tabular-nums;
}
.summary-value small {
  font-size: 11px;
  font-weight: 400;
  color: #64748b;
  margin-left: 2px;
}
.summary-hint {
  font-size: 10px;
  color: #94a3b8;
}
.summary-hint em {
  font-style: normal;
  color: #ea580c;
  margin-left: 4px;
}

.spec-bar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  margin: 8px 0 12px;
  padding: 8px 12px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
}
.spec-label {
  font-size: 11px;
  font-weight: 600;
  color: #475569;
  margin-right: 4px;
}
.spec-chip {
  font-size: 11px;
  padding: 3px 9px;
  background: #f1f5f9;
  color: #475569;
  border: 1px solid transparent;
  border-radius: 3px;
  cursor: pointer;
  transition: all 0.15s;
}
.spec-chip small { color: #94a3b8; }
.spec-chip:hover { border-color: #cbd5e1; }
.spec-chip.active {
  background: #ecfdf5;
  color: #047857;
  border-color: #6ee7b7;
  font-weight: 500;
}
.spec-chip.active small { color: #047857; }
.spec-bar-hint {
  margin-left: auto;
  font-size: 10px;
  color: #94a3b8;
}

.compare-card {
  background: #fff;
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  padding: 16px;
  margin: 8px 0 16px;
  min-height: 480px;
  box-shadow: 0 1px 3px rgba(15,23,42,0.04);
}
.compare-chart { width: 100%; height: 540px; }

.period-table-scroll, .city-detail { overflow-x: auto; }
.period-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
  margin: 12px 0;
  background: #fff;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
}
.period-table th, .period-table td {
  padding: 8px 10px;
  text-align: left;
  border-bottom: 1px solid #f1f5f9;
}
.period-table th {
  background: #f8fafc;
  font-weight: 600;
  color: #475569;
  font-size: 11px;
}
.period-table th.th-spread { background: #eff6ff; }
.th-city { font-weight: 600 !important; }
.td-period { color: #0f172a; font-weight: 500; }
.td-price { text-align: right; vertical-align: middle; }
.price-val {
  font-weight: 700;
  font-variant-numeric: tabular-nums;
}
.price-meta { font-size: 10px; color: #94a3b8; }
.td-price.missing { background: #fafafa; }
.td-spread { vertical-align: middle; }
.spread-val {
  font-weight: 600;
  font-variant-numeric: tabular-nums;
  color: #0f172a;
}
.spread-pct {
  display: inline-block;
  margin-left: 6px;
  padding: 2px 6px;
  font-size: 10px;
  font-weight: 600;
  border-radius: 3px;
}
.spread-pct.spread-low { background: #ecfdf5; color: #047857; }
.spread-pct.spread-mid { background: #fef3c7; color: #a16207; }
.spread-pct.spread-huge { background: #fef2f2; color: #b91c1c; }
.no-data { color: #cbd5e1; }

.city-detail-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(360px, 1fr));
  gap: 12px;
  margin: 12px 0;
}
.city-detail {
  --accent: #64748b;
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  background: #fff;
}
.city-detail-head {
  padding: 8px 14px;
  color: #fff;
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  border-radius: 6px 6px 0 0;
}
.city-name { font-size: 13px; font-weight: 600; }
.city-meta { font-size: 11px; opacity: 0.9; }
.city-meta em {
  font-style: normal;
  background: rgba(255, 255, 255, 0.25);
  padding: 0 4px;
  border-radius: 2px;
  margin-right: 4px;
  font-size: 10px;
}
.city-meta .missing-tag { margin-left: 6px; color: #fef08a; }
.city-empty { padding: 30px; text-align: center; color: #94a3b8; font-size: 12px; }
.city-spec-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 11px;
}
.city-spec-table th {
  background: #f8fafc;
  padding: 6px;
  font-weight: 500;
  color: #64748b;
  text-align: right;
  border-bottom: 1px solid #e2e8f0;
}
.city-spec-table th:first-child { text-align: left; }
.city-spec-table td {
  padding: 5px 6px;
  border-bottom: 1px solid #f1f5f9;
  text-align: right;
  font-variant-numeric: tabular-nums;
}
.td-spec-label {
  text-align: left !important;
  color: #0f172a;
  font-weight: 500;
  max-width: 180px;
  overflow: hidden;
  text-overflow: ellipsis;
}
.align-tag {
  display: inline-block;
  margin-left: 4px;
  padding: 0 4px;
  border-radius: 2px;
  font-size: 9px;
  font-weight: 500;
}
.align-tag.align-attr { background: #dbeafe; color: #1d4ed8; }
.align-tag.align-spec_norm { background: #fef3c7; color: #a16207; }
.align-tag.align-fallback { background: #f1f5f9; color: #64748b; }
.sp-val { font-weight: 600; color: #0f172a; }
.sp-meta { font-size: 9px; color: #94a3b8; }
</style>
