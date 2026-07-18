<template>
  <div class="prov-page">

    <!-- Header -->
    <div class="prov-header">
    </div>



    <!-- All Cities Pipeline (ODS→DWD→DWS, 抓取模块已拆分到独立 "抓取" 标签页) -->
    <div class="prov-all-pipelines" v-if="data.all_cities">
      <div class="panel-header" style="margin-bottom:12px">
        <span class="panel-dot panel-dot-blue"></span>
        <span class="panel-title">数据处理链路（ODS → DWD → DWS）</span>
      </div>
      <div class="pipelines-grid">
        <div
          v-for="(pipe, key) in data.all_cities"
          :key="key"
          class="pipeline-card"
          :class="{ active: key === selectedCity }"
          @click="selectedCity = key; loadData()"
        >
          <div class="pipeline-card-header">
            <span class="pipeline-card-city">{{ pipe.city_label }}</span>
            <button
              class="pipeline-sync-btn"
              :disabled="!!dwsRunning[key]"
              :title="`立即重跑 DWD→DWS 同步（${pipe.city_label}）`"
              @click.stop="runFlushDws(key)"
            >
              <span v-if="dwsRunning[key]" class="spinner"></span>
              <span v-else>⟳</span>
              {{ dwsRunning[key] ? '同步中' : '同步' }}
            </button>
          </div>
          <div class="pipeline-card-stages">
            <div class="pipe-stage stage-ods">
              <div class="pipe-stage-label stage-ods-label">ODS</div>
              <div class="pipe-stage-count">{{ fmt.int(pipe.ods?.count) }}<span class="pipe-stage-unit">条</span></div>
            </div>
            <div class="pipe-stage-arrow stage-arrow-dwd">
              <span class="arrow-label">→</span>
              <span v-if="pipe.ods?.count != null" class="arrow-delta" :class="dwdDeltaClass(pipe)" :title="`ODS 到 DWD 损耗 = ODS - DWD`">
                {{ formatDelta(pipe.ods?.count, pipe.dwd?.count) }}
              </span>
            </div>
            <div class="pipe-stage scrape-stage stage-dwd" :style="{ '--pct': dwdPct(pipe) }" :class="{ disabled: !pipe.dwd?.count }">
              <div class="scrape-inner" @click.stop="openDwdDrilldown(key, pipe)">
                <div class="pipe-stage-label stage-dwd-label">DWD</div>
                <div class="pipe-stage-count">{{ fmt.int(pipe.dwd?.count) }}<span class="pipe-stage-unit">条</span></div>
              </div>
              <div class="stage-dwd-right">
                <div class="coverage-ring" :class="dwdSyncClass(dwdSyncRate(pipe))" :title="`ODS 分类成功比例: ${dwdSyncRate(pipe)}%（DWD/ODS）`" @click.stop="openDwdDrilldown(key, pipe)">
                  <svg viewBox="0 0 36 36" class="coverage-svg">
                    <circle class="coverage-track" cx="18" cy="18" r="15.9"/>
                    <circle class="coverage-fill" cx="18" cy="18" r="15.9"
                      :stroke-dasharray="`${dwdSyncRate(pipe) * 1.004}, 100`"/>
                  </svg>
                  <div class="coverage-text">
                    <span class="coverage-pct">{{ dwdSyncRate(pipe) }}</span>
                    <span class="coverage-unit">%</span>
                  </div>
                </div>
              </div>
            </div>
            <div class="pipe-stage-arrow stage-arrow-dws">
              <span class="arrow-label">→</span>
              <span v-if="pipe.dwd?.count != null" class="arrow-delta" :class="dwsDeltaClass(pipe)" :title="`DWD 到 DWS 损耗 = DWD - DWS`">
                {{ formatDelta(pipe.dwd?.count, pipe.dws?.count) }}
              </span>
            </div>
            <div class="pipe-stage scrape-stage stage-dws" :style="{'--pct': dwsPct(pipe)}" :class="{ disabled: !pipe.dws?.count }">
              <div class="scrape-inner">
                <div class="pipe-stage-label stage-dws-label">DWS</div>
                <div class="pipe-stage-count">{{ fmt.int(pipe.dws?.count) }}<span class="pipe-stage-unit">条</span></div>
              </div>
              <div class="stage-dws-right">
                <div class="coverage-ring" :class="dwsSyncClass(dwsSyncRate(pipe))" :title="`DWS 同步率: ${dwsSyncRate(pipe)}%（DWS/DWD）`">
                  <svg viewBox="0 0 36 36" class="coverage-svg">
                    <circle class="coverage-track" cx="18" cy="18" r="15.9"/>
                    <circle class="coverage-fill" cx="18" cy="18" r="15.9"
                      :stroke-dasharray="`${dwsSyncRate(pipe) * 1.004}, 100`"/>
                  </svg>
                  <div class="coverage-text">
                    <span class="coverage-pct">{{ dwsSyncRate(pipe) }}</span>
                    <span class="coverage-unit">%</span>
                  </div>
                </div>
              </div>
            </div>
          </div>
          <div class="pipeline-card-etl" v-if="pipe.dwd?.last_etl">
            ETL {{ pipe.dwd?.last_etl }}
          </div>
        </div>
      </div>
    </div>


    <div v-if="loading" class="prov-loading">
      <SkeletonCard :lines="4" :hide-footer="true" />
    </div>
    <EmptyState v-else-if="!data.all_cities || Object.keys(data.all_cities).length === 0"
      icon="🧪" title="暂无数据" message="该页面需要先运行过一次同步任务" />
    <ErrorState v-if="error" :title="'加载失败'" :message="error" compact :on-retry="loadData" />
  </div>

    <!-- DWD 下钻弹窗 -->
    <div class="dwd-drilldown-overlay" v-if="dwdDrilldownCity" @click.self="closeDwdDrilldown">
      <div class="dwd-drilldown-modal">
        <div class="dwd-drilldown-header">
          <div class="dwd-drilldown-title">🔬 DWD 规格解析质量 · {{ cityMap[dwdDrilldownCity] }}</div>
          <button class="dwd-drilldown-close" @click="closeDwdDrilldown">✕</button>
        </div>
        <div class="dwd-drilldown-body">
          <SpecQualityPanel
            :coverage="specQuality.coverage || []"
            :activeCat="sqActiveCat"
            :loading="specQualityLoading"
            :cleaningCat="cleaningCatsKey"
            :cleanDoneCat="cleanDoneCat"
            :cleanDoneOk="cleanDoneOk"
            :toastMsg="sqToast"
            :coverageLoaded="specQualityCoverageLoaded"
            @refresh="refreshSpecQuality"
            @sample="selectCatForSample"
            @clean="handleCleanRequest"
          />

  <!-- SpecSamplePanel is rendered as a standalone modal by the parent (DataProvenanceView) -->
        </div>
      </div>
    </div>

    <!-- Sample modal -->
    <div class="sample-overlay" v-if="sqActiveCat" @click.self="closeSamples">
      <div class="sample-modal">
        <SpecSamplePanel
          :samples="specQuality.samples || []"
          :activeCat="sqActiveCat"
          :loading="sqSamplesLoading"
          :sampleMsg="specQuality.message || ''"
          @close="closeSamples"
        />
      </div>
    </div>

    <!-- Spec 修复 Modal -->

    <!-- 同步 toast(C.2026-07-12 P0) -->
    <Transition name="fade">
      <div v-if="syncToast.show" class="sync-toast" :class="'sync-toast--' + syncToast.type">
        <span class="sync-toast-icon">{{ syncToast.type === 'ok' ? '✓' : syncToast.type === 'error' ? '✕' : '⏳' }}</span>
        <span class="sync-toast-msg">{{ syncToast.msg }}</span>
      </div>
    </Transition>

</template>

<script setup>
import ErrorState from './ErrorState.vue'
import { ref, computed, onMounted, onUnmounted, nextTick } from 'vue'
import axios from 'axios'
import { getGovPriceTheme } from '../composables/useEchartsTheme'
import { useEcharts } from '../composables/useEcharts'
import { useFormatNumber } from '../composables/useFormatNumber.js'
import SpecQualityPanel from './SpecQualityPanel.vue'
import SpecSamplePanel from './SpecSamplePanel.vue'
import SkeletonCard from './SkeletonCard.vue'
import EmptyState from './EmptyState.vue'

const API = import.meta.env.VITE_API_URL || '/api'
const loading = ref(false)
const error = ref('')
const scrapeExpandedCity = ref('')
const scrapeRunning = ref({})
const dwsRunning = ref({})
const selectedCity = ref('xian')
const cityOptions = { xian: '西安', sichuan: '四川', chongqing: '重庆', jinan: '济南', rizhao: '日照', henan: '河南', heze: '菏泽' }
const cityMap = { xian: '西安', sichuan: '四川', chongqing: '重庆', jinan: '济南', rizhao: '日照', henan: '河南', heze: '菏泽' }
const data = ref({
  total: 0,
  recent_7d: 0,
  prev_7d: 0,
  inc_pct: 0,
  daily: [],
  provinces: [],
  top_cities: [],
  pipeline: {},
  all_cities: {},
})
const selectedCityData = ref({})
const specQuality = ref({})
const dwdDrilldownCity = ref(null)
// D.2026-07-12 统一数字格式化
const fmt = useFormatNumber()
const coverageByCity = ref({})  // { city: { rate, with_attr, needs_parse, total } }
let chartIns = null

function scrapePct(scrape) {
  if (!scrape?.total_counties) return '0%'
  return ((scrape.completed / scrape.total_counties) * 100).toFixed(1) + '%'
}

function dwdPct(pipe) {
  if (!pipe.ods?.count) return '0%'
  const dwdCount = pipe.dwd?.count || 0
  return ((dwdCount / pipe.ods.count) * 100).toFixed(1) + '%'
}

/** DWD 同步率（ODS 分类成功比例）数值，供 DWD 卡片 coverage 环使用 */
function dwdSyncRate(pipe) {
  if (!pipe.ods?.count) return 0
  return Number(((pipe.dwd?.count || 0) / pipe.ods.count * 100).toFixed(2))
}

/** DWD 同步率颜色档位 */
function dwdSyncClass(rate) {
  if (rate >= 80) return 'cov-good'
  if (rate >= 30) return 'cov-warn'
  return 'cov-bad'
}

function dwsPct(pipe) {
  if (!pipe.dwd?.count) return '0%'
  const dwsCount = pipe.dws?.count || 0
  return ((dwsCount / pipe.dwd.count) * 100).toFixed(1) + '%'
}

/** DWS 同步率数值（DWS/DWD 同步完成度 %）*/
function dwsSyncRate(pipe) {
  if (!pipe.dwd?.count) return 0
  return Number(((pipe.dws?.count || 0) / pipe.dwd.count * 100).toFixed(2))
}

/** DWS 同步率颜色档位 */
function dwsSyncClass(rate) {
  if (rate >= 80) return 'cov-good'
  if (rate >= 30) return 'cov-warn'
  return 'cov-bad'
}

// ── ODS/DWD 阶段差异量（P3-batch1）：显示 -80/0/+12 让损耗可看 ──
function formatDelta(src, dst) {
  const s = Number(src || 0)
  const d = Number(dst || 0)
  if (!s) return ''
  const diff = s - d
  if (diff === 0) return '±0'
  return (diff > 0 ? '−' : '+') + fmt.int(Math.abs(diff))
}

function dwdDeltaClass(pipe) {
  const ods = Number(pipe.ods?.count || 0)
  const dwd = Number(pipe.dwd?.count || 0)
  if (!ods) return ''
  const diff = ods - dwd
  if (diff === 0) return ''
  // 损耗超 5% 则橘色警示
  return Math.abs(diff) / ods > 0.05 ? 'delta-warn' : 'delta-ok'
}

function dwsDeltaClass(pipe) {
  const dwd = Number(pipe.dwd?.count || 0)
  const dws = Number(pipe.dws?.count || 0)
  if (!dwd) return ''
  const diff = dwd - dws
  if (diff === 0) return ''
  return Math.abs(diff) / dwd > 0.05 ? 'delta-warn' : 'delta-ok'
}

// 轻量 toast(C.2026-07-12 P0:同步反馈)
const syncToast = ref({ show: false, msg: '', type: 'info' })
let _syncToastTimer = null
function showSyncToast(msg, type = 'info') {
  syncToast.value = { show: true, msg, type }
  if (_syncToastTimer) clearTimeout(_syncToastTimer)
  _syncToastTimer = setTimeout(() => { syncToast.value.show = false }, 3500)
}

async function runFlushDws(city) {
  dwsRunning.value = { ...dwsRunning.value, [city]: true }
  try {
    const { data } = await axios.post(`${API}/stats/provenance/flush-city`, { city })
    if (data?.ok) {
      showSyncToast(`${city} 同步完成 · DWS ${data.dws_synced ?? 0} 条`, 'ok')
    } else {
      showSyncToast(`${city} 同步失败: ${data?.message || '未知错误'}`, 'error')
    }
  } catch (e) {
    console.error('flush-city failed', e)
    showSyncToast(`${city} 同步失败: ${e.message || '网络错误'}`, 'error')
  } finally {
    dwsRunning.value = { ...dwsRunning.value, [city]: false }
    loadData()
  }
}

function toggleScrapeCounties(city, pipe) {
  scrapeExpandedCity.value = (scrapeExpandedCity.value === city) ? '' : city
}

async function runScrapeCheck(city) {
  scrapeRunning.value = { ...scrapeRunning.value, [city]: true }
  try {
    await axios.post(`${API}/scrape/check`, { city })
  } catch (e) {
    console.error('scrape check failed', e)
  } finally {
    scrapeRunning.value = { ...scrapeRunning.value, [city]: false }
  }
  loadData()
}

async function openDwdDrilldown(city, pipe) {
  if (!pipe.dwd?.count) return
  dwdDrilldownCity.value = city
  specQuality.value = {}   // 先清空，API 返回 coverage（_sample=false 不含抽样）
  specQualityLoading.value = true
  try {
    const sq = await axios.get(`${API}/stats/spec-quality`, { params: { city, _sample: false } })
    specQuality.value = sq.data || {}
    specQualityCoverageLoaded.value = !!specQuality.value.coverage?.length

    if (specQuality.value.message && !specQuality.value.samples?.length) {
      sqToast.value = specQuality.value.message
      setTimeout(() => { sqToast.value = '' }, 4000)
    }
    if (specQuality.value.coverage) {
      sqCatOptions.value = specQuality.value.coverage.map(c => c.category)
    }
  } catch(e) { console.warn("spec-quality failed", e) }
  finally { specQualityLoading.value = false }
}

async function refreshSpecQuality() {
  if (!dwdDrilldownCity.value) return
  // keep existing data while loading, set loading flag only
  specQualityLoading.value = true
  try {
    const _sample = !!sqCatFilter.value
    const _url = `${API}/stats/spec-quality`
    const _params = { city: dwdDrilldownCity.value, category: sqCatFilter.value || '', _sample }

    const sq = await axios.get(_url, { params: _params })
    specQuality.value = sq.data || {}
    specQualityCoverageLoaded.value = !!specQuality.value.coverage?.length

    if (specQuality.value.message && !specQuality.value.samples?.length) {
      sqToast.value = specQuality.value.message
      setTimeout(() => { sqToast.value = '' }, 4000)
    }
    if (specQuality.value.coverage) {
      sqCatOptions.value = specQuality.value.coverage.map(c => c.category)
    }
  } catch(e) { console.warn("spec-quality refresh failed", e) }
  finally { specQualityLoading.value = false }
}

async function refreshSpecQualityCoverage() {
  // 仅刷新 coverage 覆盖率，不触碰 samples / sqCatFilter，分类列表位置固定
  if (!dwdDrilldownCity.value) return
  try {
    const sq = await axios.get(`${API}/stats/spec-quality`, {
      params: { city: dwdDrilldownCity.value, _sample: false },
    })
    if (sq.data?.coverage) {
      const newCoverage = JSON.parse(JSON.stringify(sq.data.coverage))
      // [coverage] refreshed
      specQuality.value = { ...specQuality.value, coverage: newCoverage }
      sqCatOptions.value = sq.data.coverage.map(c => c.category)
    }
  } catch(e) { console.warn("spec-quality coverage refresh failed", e) }
}

function selectCatForSample(cat) {
  sqActiveCat.value = cat
  sqCatFilter.value = cat
  refreshSpecQuality()
}


function closeDwdDrilldown() {
  dwdDrilldownCity.value = null
  specQuality.value = {}
}
const specQualityLoading = ref(false)
const sqSamplesLoading = ref(false)
const specQualityCoverageLoaded = ref(false)
function handleCleanRequest(cat) {
  cleaningCats.value[cat] = true
  if (cleanDoneCat.value === cat) cleanDoneCat.value = ''
  axios.post(`${API}/stats/spec-quality/refresh-category`, {
    city: dwdDrilldownCity.value || 'xian',
    category: cat,
  }).then(async (res) => {
    const d = res.data || {}
    sqToast.value = d.message || (d.ok ? `清洗完成，刷新 ${d.refreshed || 0} 条，DWS 同步 ${d.dws_sync?.ok || 0} 条` : '清洗失败')
    setTimeout(() => { sqToast.value = '' }, 5000)
    cleanDoneOk.value = !!d.ok
    cleanDoneCat.value = cat
    await refreshSpecQualityCoverage()
  }).catch(e => {
    cleanDoneOk.value = false
    cleanDoneCat.value = cat
    sqToast.value = `清洗失败: ${e?.response?.data?.message || e.message || '未知错误'}`
    setTimeout(() => { sqToast.value = '' }, 5000)
    console.warn("refresh-category failed", e)
  }).finally(() => {
    delete cleaningCats.value[cat]
    setTimeout(() => { if (cleanDoneCat.value === cat) cleanDoneCat.value = '' }, 3000)
  })
}
function closeSamples() {
  sqActiveCat.value = ''
  sqCatFilter.value = ''
  specQuality.value = { ...specQuality.value, samples: [] }
}
const refreshLoading = ref(false)
const sqCatFilter = ref('')
const sqCatOptions = ref([])
const sqActiveCat = ref('')
const sqSampleSize = ref(50)
const sqToast = ref('')   // 内联 toast
const cleaningCats = ref({})      // { category: true } 清洗中状态
const cleanDoneCat = ref('')      // 当前显示完成标记的分类
const cleanDoneOk = ref(true)
const cleaningCatsKey = computed(() => {
  const keys = Object.keys(cleaningCats.value)
  return keys.length === 1 ? keys[0] : ''
})
async function loadData() {
  loading.value = true
  error.value = ''
  try {
    const [provRes] = await Promise.all([
      axios.get(`${API}/stats/provenance`),
    ])
    data.value = provRes.data || {}
    await loadCoverageForAllCities()
    await nextTick()
    renderChart()
  } catch (e) {
    error.value = '加载失败：' + (e.message || '网络错误')
  } finally {
    loading.value = false
  }
}

// 拉取每个城市的 spec-quality 覆盖率，并合并到 all_cities
async function loadCoverageForAllCities() {
  const cities = Object.keys(data.value.all_cities || {})
  if (!cities.length) return
  const results = await Promise.allSettled(
    cities.map(city =>
      axios.get(`${API}/stats/spec-quality`, { params: { city, _sample: false } })
        .then(r => ({ city, data: r.data }))
    )
  )
  const next = {}
  for (const r of results) {
    if (r.status === 'fulfilled') {
      const { city, data: sq } = r.value
      const cov = sq.coverage || []
      const total = cov.reduce((s, c) => s + (c.total || 0), 0)
      const withAttr = cov.reduce((s, c) => s + (c.with_attr || 0), 0)
      const rate = total > 0 ? (withAttr / total) * 100 : 0
      next[city] = { rate, with_attr: withAttr, needs_parse: total - withAttr, total }
    }
  }
  coverageByCity.value = next
  // 合并到 data.all_cities 的 pipe.coverage
  for (const [city, cov] of Object.entries(next)) {
    if (data.value.all_cities[city]) {
      data.value.all_cities[city].coverage = cov
    }
  }
}

function coverageClass(c) {
  if (!c || c.rate == null) return 'cov-loading'
  if (c.rate >= 80) return 'cov-good'
  if (c.rate >= 30) return 'cov-warn'
  return 'cov-bad'
}
function coverageTooltip(c) {
  if (!c) return '加载中...'
  if (c.total === 0) return '该城市 DWD 暂无数据'
  return `attr 覆盖率: ${fmt.pct(c.rate, 1)}\n已解析: ${fmt.int(c.with_attr)}\n待解析: ${fmt.int(c.needs_parse)}\n总计: ${fmt.int(c.total)}`
}

async function renderChart() {
  const el = document.getElementById('dailyTrendChart')
  if (!el || !data.value.daily?.length) return
  if (chartIns) chartIns.dispose()

  const echarts = await useEcharts()
  chartIns = echarts.init(el, getGovPriceTheme())
  const daily = data.value.daily

  const dates = daily.map(d => d.date?.slice(5)) // MM-DD
  const counts = daily.map(d => d.count)

  chartIns.setOption({
    backgroundColor: 'transparent',
    grid: { top: 12, bottom: 24, left: 50, right: 16 },
    tooltip: {
      trigger: 'axis',
      backgroundColor: 'rgba(255,255,255,0.98)',
      borderColor: 'rgba(241,245,249,0.6)',
      textStyle: { color: '#1e293b', fontSize: 12 },
      formatter: (params) => `${params[0].name}<br/>入库 <b>${fmt.int(params[0].value)}</b> 条`,
    },
    xAxis: {
      type: 'category',
      data: dates,
      axisLine: { lineStyle: { color: 'rgba(15,23,42,0.08)' } },
      axisTick: { show: false },
      axisLabel: { color: '#475569', fontSize: 10 },
    },
    yAxis: {
      type: 'value',
      splitLine: { lineStyle: { color: 'rgba(15,23,42,0.04)' } },
      axisLabel: { color: '#475569', fontSize: 10 },
    },
    series: [{
      type: 'bar',
      data: counts,
      itemStyle: {
        color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
          { offset: 0, color: '#2563eb' },
          { offset: 1, color: 'rgba(37,99,235,0.3)' },
        ]),
        borderRadius: [2, 2, 0, 0],
      },
      barMaxWidth: 20,
    }],
  }, true)
}

window.addEventListener('resize', () => chartIns?.resize())
onMounted(() => {
  loadData()
})
</script>

<style scoped>
.prov-page {
  padding: 16px 20px 80px;
  min-height: 100vh;
  color: #1e293b;
}

.prov-header {
  margin-bottom: 16px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.prov-city-select {
  margin-top: 8px;
}
.prov-city-select select {
  background: var(--surface, #ffffff);
  color: #1e293b;
  border: 1px solid rgba(15,23,42,0.12);
  border-radius: 6px;
  padding: 5px 12px;
  font-size: 12px;
  cursor: pointer;
  outline: none;
}
.prov-city-select select:focus {
  border-color: var(--primary);
}
.prov-title {
  font-size: 18px;
  font-weight: 700;
  color: #0f172a;
  text-shadow: 0 2px 12px rgba(37,99,235,0.2);
}


/* Main layout */
.prov-main {
  display: grid;
  grid-template-columns: 1fr 360px;
  gap: 12px;
  margin-bottom: 12px;
}

/* Chart */
.prov-chart-panel {
  background: #ffffff;
  border: 1px solid rgba(15,23,42,0.07);
  border-radius: 10px;
  padding: 14px 16px;
}
.chart-area { height: 180px; }

.panel-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
}
.panel-dot { width: 8px; height: 8px; border-radius: 50%; }
.panel-dot-blue { background: var(--primary); }
.panel-dot-green { background: var(--status-ok); }
.panel-dot-amber { background: var(--status-warn); }
.panel-title { font-size: 13px; font-weight: 600; color: #1e293b; }
.panel-hint { font-size: 10px; color: #475569; margin-left: auto; }

/* Province list */
.prov-province-panel {
  background: #ffffff;
  border: 1px solid rgba(15,23,42,0.07);
  border-radius: 10px;
  padding: 14px 16px;
  max-height: 360px;
  display: flex;
  flex-direction: column;
}
.province-list {
  overflow-y: auto;
  flex: 1;
}
.province-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 6px 4px;
  border-bottom: 1px solid rgba(15, 23, 42, 0.04);
  border-radius: 4px;
}
.province-row:last-child { border-bottom: none; }
.province-row.stale { background: rgba(248,113,113,0.06); }
.province-row.old { background: rgba(245,158,11,0.04); }
.province-info { display: flex; flex-direction: column; gap: 1px; }
.province-name { font-size: 13px; font-weight: 500; color: var(--text-2, #475569); }
.province-count { font-size: 10px; color: #475569; }
.province-right { display: flex; flex-direction: column; align-items: flex-end; gap: 2px; }
.province-date { font-size: 11px; }
.province-date.stale { color: var(--status-alert); }
.province-date.old { color: var(--status-warn); }
.province-date.fresh { color: var(--status-ok); }
.province-badge { font-size: 10px; padding: 1px 5px; border-radius: 3px; }
.province-badge.stale { background: rgba(248,113,113,0.15); color: var(--status-alert); }
.province-badge.old { background: rgba(245,158,11,0.15); color: var(--status-warn); }
.province-badge.fresh { background: rgba(16,185,129,0.15); color: var(--status-ok); }

/* City grid */
.prov-cities-panel {
  background: #ffffff;
  border: 1px solid rgba(15,23,42,0.07);
  border-radius: 10px;
  padding: 14px 16px;
}
.city-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.city-chip {
  display: flex;
  align-items: center;
  gap: 5px;
  background: rgba(15,23,42,0.04);
  border: 1px solid rgba(15,23,42,0.07);
  border-radius: 20px;
  padding: 3px 10px;
  font-size: 11px;
}
.city-name { color: #1e293b; font-weight: 500; }
.city-province { color: #475569; }
.city-count { color: var(--primary); font-weight: 600; }

/* Loading / Error */
.prov-loading { display: flex; align-items: center; justify-content: center; gap: 10px; padding: 24px; color: #475569; font-size: 13px; }
.prov-error { text-align: center; padding: 20px; color: var(--status-alert); font-size: 13px; }
.loading-spinner { width: 18px; height: 18px; border: 2px solid rgba(241,245,249,0.6); border-top-color: #3b82f6; border-radius: 50%; animation: spin 0.8s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }

@media (max-width: 900px) {
  .prov-stats { grid-template-columns: repeat(2, 1fr); }
  .prov-main { grid-template-columns: 1fr; }
}

/* Pipeline */
.prov-pipeline {
  background: #ffffff;
  border: 1px solid rgba(15,23,42,0.07);
  border-radius: 10px;
  padding: 14px 16px;
  margin-bottom: 12px;
}
.pipeline-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
}
.pipeline-title { font-size: 13px; font-weight: 600; color: #1e293b; }
.pipeline-stages {
  display: flex;
  align-items: center;
  gap: 0;
}
.pipeline-stage {
  flex: 1;
  background: rgba(15, 23, 42, 0.04);
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  padding: 10px 14px;
  text-align: center;
}
.pipeline-arrow {
  font-size: 18px;
  color: var(--primary);
  padding: 0 8px;
  flex-shrink: 0;
}
.stage-name { font-size: 11px; font-weight: 700; color: var(--primary); letter-spacing: 1px; margin-bottom: 4px; }
.stage-count { font-size: 20px; font-weight: 800; color: #0f172a; font-family: ui-monospace, 'SF Mono', Consolas, 'Liberation Mono', monospace; line-height: 1; }
.stage-unit { font-size: 11px; font-weight: 500; color: var(--text-3); margin-left: 2px; }
.stage-date { font-size: 10px; color: #475569; margin-top: 4px; }
.stage-etl { font-size: 10px; color: var(--text-3); margin-top: 2px; }

/* Scrape All Cities */
/* ODS 抓取进度（统一列表） */
.prov-scrape {
  background: #ffffff;
  border: 1px solid rgba(15,23,42,0.07);
  border-radius: 10px;
  padding: 14px 16px;
  margin-bottom: 12px;
}
.scrape-unified-list { display: flex; flex-direction: column; gap: 4px; }
.scrape-unified-card {
  background: rgba(15, 23, 42, 0.04);
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  padding: 10px 12px;
  cursor: pointer;
  transition: all 0.2s;
}
.scrape-unified-card:hover { border-color: rgba(37,99,235,0.25); }
.scrape-unified-card.active {
  border-color: rgba(37,99,235,0.45);
  background: rgba(37,99,235,0.05);
}
.scrape-unified-card.active.running { animation: card-pulse 2s ease-in-out infinite; }
@keyframes card-pulse {
  0%,100%{box-shadow:0 0 0 0 rgba(37,99,235,0)} 50%{box-shadow:0 0 8px 2px rgba(37,99,235,0.15)}
}
.unified-city-row { display: grid; grid-template-columns: 52px 1fr auto; align-items: center; gap: 10px; }
.unified-left { display: flex; align-items: center; gap: 6px; }
.unified-city-label { font-size: 13px; font-weight: 700; color: #0f172a; }
.unified-bar-wrap { height: 8px; background: rgba(15,23,42,0.07); border-radius: 4px; overflow: hidden; }
.unified-bar { height: 100%; border-radius: 4px; transition: width 0.8s ease; position: relative; overflow: hidden; }
.unified-bar.completed { background: var(--status-ok); }
.unified-bar.running { background: linear-gradient(90deg, #1e4a6e, var(--primary)); }
.unified-bar.error { background: var(--status-alert); }
.unified-bar-shimmer {
  position: absolute; top: 0; left: -100%;
  width: 55%; height: 100%;
  background: linear-gradient(90deg, transparent, rgba(15,23,42,0.3), transparent);
  animation: shimmer-slide 2s ease-in-out infinite;
}
@keyframes shimmer-slide { 0%{transform:translateX(0)} 100%{transform:translateX(300%)} }
.unified-right { display: flex; align-items: center; gap: 8px; min-width: 130px; justify-content: flex-end; }
.unified-badge { font-size: 11px; font-weight: 600; padding: 2px 7px; border-radius: 10px; }
.unified-badge.completed { background: rgba(52,211,153,0.15); color: var(--status-ok); }
.unified-badge.running { background: rgba(37,99,235,0.12); color: var(--primary); }
.unified-badge.error { background: rgba(248,113,113,0.12); color: var(--status-alert); }
.unified-docs { font-size: 11px; color: #475569; }
.unified-pct { font-size: 11px; color: var(--text-3); min-width: 36px; text-align: right; font-family: ui-monospace, 'SF Mono', Consolas, 'Liberation Mono', monospace; }
.unified-expand { font-size: 11px; color: var(--text-3); transition: transform 0.2s, color 0.2s; margin-left: 4px; flex-shrink: 0; }
.unified-expand.rotated { transform: rotate(90deg); color: var(--primary); font-size: 12px; }
.unified-county-strip {
  margin-top: 5px;
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
}
.unified-county-chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 3px 8px;
  background: rgba(0,0,0,0.2);
  border: 1px solid rgba(15,23,42,0.04);
  border-radius: 4px;
  font-size: 10px;
}
.unified-county-chip.running {
  border-color: rgba(37,99,235,0.35);
  background: rgba(37,99,235,0.12);
  box-shadow: 0 0 8px rgba(37,99,235,0.15);
}
.unified-county-chip.completed { border-color: rgba(15,23,42,0.08); background: rgba(15,23,42,0.04); }
.chip-dot { width: 4px; height: 4px; border-radius: 50%; flex-shrink: 0; }
.chip-dot.completed { background: var(--text-3); }
.chip-dot.running { background: var(--primary); animation: pulse-dot 1.5s ease-in-out infinite; }
.chip-dot.not-started { background: #475569; }
.chip-name { color: var(--text-3); }
.chip-pct { color: var(--text-3); font-family: ui-monospace, 'SF Mono', Consolas, 'Liberation Mono', monospace; font-weight: 900; }
.chip-pct.running { color: var(--primary); }
.chip-pct.completed { color: var(--status-ok); }
.chip-pct.not-started { color: #475569; }
.unified-county-empty { font-size: 10px; color: var(--text-3, #94a3b8); padding: 4px 0; }

@keyframes pulse-dot {
  0%   { box-shadow: 0 0 0 0 rgba(37,99,235,0.5); transform: scale(1); }
  50%  { box-shadow: 0 0 0 5px rgba(37,99,235,0); transform: scale(1.15); }
  100% { box-shadow: 0 0 0 0 rgba(37,99,235,0); transform: scale(1); }
}
.scrape-pulse-dot {
  width: 7px; height: 7px; border-radius: 50%;
  background: var(--primary);
  animation: pulse-dot 1.5s ease-in-out infinite;
  box-shadow: 0 0 0 0 rgba(37,99,235,0.5);
}

/* Cities Overview */
.prov-cities-overview {
  background: #ffffff;
  border: 1px solid rgba(15,23,42,0.07);
  border-radius: 10px;
  padding: 14px 16px;
  margin-bottom: 12px;
}
.cities-overview-grid {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
}
.city-overview-card {
  flex: 1;
  min-width: 120px;
  background: rgba(15, 23, 42, 0.04);
  border: 1px solid rgba(15,23,42,0.07);
  border-radius: 8px;
  padding: 10px 14px;
  cursor: pointer;
  transition: all 0.2s;
  position: relative;
}
.city-overview-card:hover {
  border-color: rgba(37,99,235,0.3);
  background: rgba(37,99,235,0.05);
}
.city-overview-card.active {
  border-color: rgba(37,99,235,0.5);
  background: rgba(37,99,235,0.08);
}
.city-overview-label { font-size: 11px; color: var(--text-3); margin-bottom: 4px; font-weight: 600; text-transform: uppercase; }
.city-overview-count { font-size: 20px; font-weight: 800; color: #0f172a; font-family: ui-monospace, 'SF Mono', Consolas, 'Liberation Mono', monospace; line-height: 1; }
.city-overview-unit { font-size: 11px; color: var(--text-3); margin-left: 2px; }
.city-overview-date { font-size: 10px; color: #475569; margin-top: 4px; }
.city-overview-status { font-size: 11px; margin-top: 2px; }
.city-overview-status.ok { color: var(--status-ok); }
.city-overview-status.error { color: var(--status-alert); }

/* All Cities Full Pipeline */
.prov-all-pipelines {
  background: #ffffff;
  border: 1px solid rgba(15,23,42,0.07);
  border-radius: 10px;
  padding: 14px 16px;
  margin-bottom: 12px;
}
.pipelines-grid {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.pipeline-card {
  background: rgba(15, 23, 42, 0.04);
  border: 1px solid rgba(15,23,42,0.07);
  border-radius: 8px;
  padding: 10px 14px;
  cursor: pointer;
  transition: all 0.2s;
}
.pipeline-card:hover {
  border-color: rgba(37,99,235,0.3);
  background: rgba(37,99,235,0.04);
}
.pipeline-card.active {
  border-color: rgba(37,99,235,0.5);
  background: rgba(37,99,235,0.07);
}
.pipeline-card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
}
.pipeline-card-city { font-size: 13px; font-weight: 700; color: #1e293b; }

/* 立即同步按钮(C.2026-07-12 P0)：调 /api/stats/provenance/flush-city */
.pipeline-sync-btn {
  display: inline-flex; align-items: center; gap: 4px;
  padding: 3px 9px;
  font-size: 11px; font-weight: 600;
  color: var(--primary-light, var(--primary));
  background: rgba(37,99,235,0.08);
  border: 1px solid rgba(37,99,235,0.25);
  border-radius: 4px;
  cursor: pointer;
  transition: all 0.18s;
  white-space: nowrap;
}
.pipeline-sync-btn:hover:not(:disabled) {
  background: var(--primary);
  color: #fff;
  border-color: var(--primary);
  transform: translateY(-1px);
  box-shadow: 0 2px 6px rgba(37,99,235,0.3);
}
.pipeline-sync-btn:active:not(:disabled) { transform: translateY(0); }
.pipeline-sync-btn:disabled {
  opacity: 0.55;
  cursor: wait;
  background: rgba(37,99,235,0.04);
}
.pipeline-sync-btn .spinner {
  width: 10px; height: 10px;
  border: 1.5px solid currentColor;
  border-top-color: transparent;
  border-radius: 50%;
  display: inline-block;
  animation: sync-spin 0.8s linear infinite;
}
@keyframes sync-spin { to { transform: rotate(360deg); } }

/* 同步 toast(C.2026-07-12 P0) */
.sync-toast {
  position: fixed;
  right: 28px; bottom: 28px;
  z-index: 9999;
  display: flex; align-items: center; gap: 10px;
  padding: 11px 18px;
  border-radius: 8px;
  background: var(--surface);
  color: var(--text);
  border: 1px solid var(--border);
  box-shadow: 0 8px 24px rgba(15,23,42,0.18), 0 2px 4px rgba(15,23,42,0.08);
  font-size: 13px; font-weight: 500;
  min-width: 220px; max-width: 420px;
}
.sync-toast--ok    { border-left: 3px solid var(--status-ok); }
.sync-toast--error { border-left: 3px solid var(--status-alert); }
.sync-toast--info  { border-left: 3px solid var(--primary); }
.sync-toast-icon   { font-size: 16px; flex-shrink: 0; }
.sync-toast--ok .sync-toast-icon    { color: var(--status-ok); }
.sync-toast--error .sync-toast-icon { color: var(--status-alert); }
.sync-toast--info .sync-toast-icon  { color: var(--primary); }

.fade-enter-active, .fade-leave-active { transition: opacity 0.22s, transform 0.22s; }
.fade-enter-from { opacity: 0; transform: translateY(8px); }
.fade-leave-to   { opacity: 0; transform: translateY(8px); }
.pipeline-card-stages {
  display: flex;
  align-items: stretch;
  gap: 4px;
}
/* ODS 卡片用纵向 flex + 居中：保证与 DWD/DWS 卡片等高时 label+count 居中 */
.pipeline-card-stages > .pipe-stage:not(.scrape-stage) {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
}
.pipe-stage {
  flex: 1;
  text-align: center;
  background: rgba(15, 23, 42, 0.03);
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  padding: 6px 8px;
}
.pipe-stage-btn { cursor: pointer; transition: all 0.2s; position: relative; }
.pipe-stage-btn::after {
  content: '';
  position: absolute;
  bottom: 0; left: 0; right: 0;
  height: 3px;
  background: linear-gradient(90deg, var(--status-ok) var(--pct, 0%), rgba(241,245,249,0.6) var(--pct, 0%));
  border-radius: 0 0 6px 6px;
  transition: background 0.4s ease;
}
.pipe-progress-wrap { height: 3px; background: rgba(15,23,42,0.08); border-radius: 2px; margin: 4px 0 2px; overflow: hidden; }
.pipe-progress-fill { height: 100%; background: linear-gradient(90deg, var(--primary), var(--status-ok)); border-radius: 2px; transition: width 0.4s ease; }
.pipe-stage-label { font-size: 10px; font-weight: 700; color: var(--primary); letter-spacing: 0.5px; margin-bottom: 2px; }
.pipe-stage-count { font-size: 15px; font-weight: 800; color: #0f172a; font-family: ui-monospace, 'SF Mono', Consolas, 'Liberation Mono', monospace; line-height: 1; }
.pipe-stage-unit { font-size: 10px; color: var(--text-3); margin-left: 1px; }
.pipe-stage-arrow {
  font-size: 14px;
  color: var(--primary);
  flex-shrink: 0;
  padding: 0 4px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 1px;
  min-width: 28px;
}
.pipe-stage-arrow .arrow-label { line-height: 1; }
/* 差异量（P3-batch1）：损耗量化 */
.pipe-stage-arrow .arrow-delta {
  font-size: 9px;
  font-weight: 600;
  font-family: var(--font-mono-num);
  padding: 1px 4px;
  border-radius: 3px;
  white-space: nowrap;
}
.pipe-stage-arrow .arrow-delta.delta-ok {
  background: rgba(34,197,94,0.12);
  color: #16a34a;
}
.pipe-stage-arrow .arrow-delta.delta-warn {
  background: rgba(220,38,38,0.12);
  color: #dc2626;
}
.pipeline-card-etl { font-size: 10px; color: var(--text-3); margin-top: 6px; }
.pipeline-card-counties {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  margin-top: 8px;
  padding: 6px 8px;
  background: rgba(15, 23, 42, 0.04);
  border-radius: 6px;
  max-height: 80px;
  overflow-y: auto;
}
.pipeline-county-chip {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 10px;
  background: rgba(15,23,42,0.04);
  border: 1px solid #e2e8f0;
}
.pipeline-county-chip.running { border-color: rgba(37,99,235,0.3); }
.pipeline-county-chip.completed { border-color: rgba(15,23,42,0.08); }

.fix-success-modal {
  position: fixed;
  inset: 0;
  background: #cbd5e1;
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 9999;
}
.fix-success-content {
  background: var(--surface, #ffffff);
  border: 1px solid var(--status-ok);
  border-radius: 16px;
  padding: 40px 48px;
  text-align: center;
  max-width: 420px;
}
.fix-success-icon { font-size: 64px; margin-bottom: 16px; }
.fix-success-title { font-size: 22px; font-weight: 700; color: var(--status-ok); margin-bottom: 12px; }
.fix-success-msg { font-size: 14px; color: var(--text-3); margin-bottom: 28px; line-height: 1.6; }
.btn-ok {
  background: var(--status-ok);
  color: #ffffff;
  border: none;
  border-radius: 8px;
  padding: 10px 40px;
  font-size: 16px;
  font-weight: 600;
  cursor: pointer;
}
.btn-ok:hover { background: #059669; }

/* 清洗按钮动态效果 */
.cleaning-spinner {
  display: inline-block;
  width: 12px;
  height: 12px;
  border: 2px solid rgba(241,245,249,0.7);
  border-top-color: #fff;
  border-radius: 50%;
  animation: spin 0.7s linear infinite;
}
@keyframes spin {
  to { transform: rotate(360deg); }
}
.sq-empty-hint {
  padding: 24px;
  text-align: center;
  color: #888;
  font-size: 13px;
}
.sq-message-hint {
  padding: 14px 16px;
  margin: 8px 16px;
  background: rgba(37,99,235,0.08);
  border: 1px solid rgba(37,99,235,0.25);
  border-radius: 8px;
  color: var(--primary);
  font-size: 13px;
  line-height: 1.6;
}
.sq-confirm-modal {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 14px 16px;
  margin: 8px 16px;
  background: var(--surface, #ffffff);
  border: 1px solid var(--surface-3, #e2e8f0);
  border-radius: 10px;
  box-shadow: var(--shadow, 0 1px 2px rgba(15,23,42,0.04));
}
.sq-confirm-icon {
  font-size: 22px;
  line-height: 1;
  flex-shrink: 0;
}
.sq-confirm-body {
  flex: 1;
  min-width: 0;
}
.sq-confirm-title {
  font-size: 14px;
  font-weight: 600;
  color: #0f172a;
  margin-bottom: 4px;
}
.sq-confirm-msg {
  font-size: 13px;
  color: var(--text-3);
  line-height: 1.5;
}
.sq-confirm-actions {
  display: flex;
  gap: 8px;
  flex-shrink: 0;
}
.sq-confirm-cancel {
  background: transparent;
  color: var(--text-3);
  border: 1px solid var(--surface-3, #e2e8f0);
  border-radius: 8px;
  padding: 7px 14px;
  font-size: 13px;
  cursor: pointer;
  transition: all 0.15s;
}
.sq-confirm-cancel:hover {
  background: var(--surface-2, #f1f5f9);
  color: var(--text-3);
  border-color: var(--surface-3, #e2e8f0);
}
.sq-confirm-ok {
  background: linear-gradient(135deg, var(--primary), var(--primary-dark));
  color: #fff;
  border: none;
  border-radius: 8px;
  padding: 7px 18px;
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  box-shadow: 0 2px 8px rgba(37,99,235,0.35);
  transition: opacity 0.15s, transform 0.1s;
}
.sq-confirm-ok:hover { opacity: 0.88; }
.sq-confirm-ok:active { transform: scale(0.97); }

.sq-toast-hint {
  padding: 12px 16px;
  margin: 8px 16px;
  background: rgba(37,99,235,0.08);
  border: 1px solid rgba(37,99,235,0.25);
  border-radius: 8px;
  color: var(--primary);
  font-size: 13px;
  animation: sq-toast-in 0.2s ease;
}
@keyframes sq-toast-in {
  from { opacity: 0; transform: translateY(-4px); }
  to { opacity: 1; transform: translateY(0); }
}

/* Vec Rules Panel */
.vec-panel {
  background: #ffffff;
  border: 1px solid rgba(15,23,42,0.07);
  border-radius: 10px;
  padding: 14px 16px;
  margin-bottom: 12px;
}
.vec-total-badge {
  font-size: 11px;
  background: rgba(37,99,235,0.12);
  color: var(--primary);
  border-radius: 10px;
  padding: 2px 8px;
  margin-left: 8px;
}
.vec-search {
  margin-left: 12px;
  background: #e2e8f0;
  border: 1px solid rgba(241,245,249,0.6);
  border-radius: 6px;
  color: #1e293b;
  font-size: 12px;
  padding: 4px 10px;
  width: 160px;
  outline: none;
}
.vec-search:focus { border-color: var(--primary); }
.vec-attr-select {
  margin-left: 8px;
  background: #e2e8f0;
  border: 1px solid rgba(241,245,249,0.6);
  border-radius: 6px;
  color: #1e293b;
  font-size: 12px;
  padding: 4px 8px;
  outline: none;
  cursor: pointer;
}
.vec-table-wrap { overflow-x: auto; margin-top: 10px; }
.vec-table { width: 100%; border-collapse: collapse; font-size: 12px; }
.vec-table th {
  background: rgba(15,23,42,0.04);
  color: var(--text-3);
  font-weight: 600;
  padding: 7px 10px;
  text-align: left;
  white-space: nowrap;
  border-bottom: 1px solid #e2e8f0;
}
.vec-table td {
  padding: 6px 10px;
  border-bottom: 1px solid rgba(15,23,42,0.04);
  vertical-align: top;
}
.vec-table tr:hover td { background: rgba(15, 23, 42, 0.03); }
.vec-id { color: #475569; font-family: monospace; width: 40px; }
.vec-attr-tag {
  display: inline-block;
  background: rgba(37,99,235,0.1);
  color: var(--primary);
  border-radius: 4px;
  padding: 1px 6px;
  font-size: 11px;
  font-weight: 600;
}
.vec-cat { color: var(--text-3); font-size: 11px; }
.vec-pattern {
  font-family: 'Courier New', monospace;
  font-size: 11px;
  color: var(--primary, #2563eb);
  background: rgba(37,99,235,0.06);
  border-radius: 3px;
  padding: 2px 5px;
  word-break: break-all;
  max-width: 200px;
  display: inline-block;
}
.vec-note { color: var(--text-3); max-width: 150px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.vec-code {
  font-family: 'Courier New', monospace;
  font-size: 10px;
  color: #059669;
  background: rgba(16,185,129,0.06);
  border-radius: 3px;
  padding: 3px 6px;
  white-space: pre;
  max-width: 300px;
  overflow: hidden;
  text-overflow: ellipsis;
  max-height: 40px;
  display: block;
}
.vec-date { color: #475569; white-space: nowrap; font-size: 11px; }
.vec-empty { text-align: center; color: var(--text-3, #94a3b8); padding: 20px; }
/* vec-pagination removed — 统一使用 AppPagination */

.scrape-stage { flex: 1; display: flex; align-items: center; background: rgba(15, 23, 42, 0.03); border: 1px solid #e2e8f0; border-radius: 6px; padding: 6px 8px; gap: 4px; }

/* 各阶段独立配色 */
.stage-scrape   { border-color: rgba(168,85,247,0.25); background: rgba(168,85,247,0.04); }
.stage-scrape-label { color: #7c3aed !important; }
.stage-arrow-ods   { color: var(--status-warn); }

.stage-ods     { border-color: rgba(245,158,11,0.25); background: rgba(245,158,11,0.04); }
.stage-ods-label { color: var(--status-warn) !important; }
.stage-arrow-dwd   { color: var(--primary); }

.stage-dwd      { border-color: rgba(37,99,235,0.25); background: rgba(37,99,235,0.04); position: relative; }
.stage-dwd-label { color: var(--primary) !important; }

/* DWD 区域右侧：覆盖率环 + 同步按钮 */
.stage-dwd-right { display: flex; flex-direction: column; align-items: center; gap: 4px; flex-shrink: 0; }

/* DWS 区域右侧：同步率环 */
.stage-dws-right { display: flex; flex-direction: column; align-items: center; gap: 4px; flex-shrink: 0; }

.coverage-ring {
  position: relative;
  width: 76px;
  height: 76px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: transform 0.2s;
}
.coverage-ring:hover { transform: scale(1.08); }
.coverage-svg { width: 100%; height: 100%; transform: rotate(-90deg); }
.coverage-track { fill: none; stroke: rgba(15,23,42,0.08); stroke-width: 2.5; }
.coverage-fill  { fill: none; stroke-width: 2.5; stroke-linecap: round; transition: stroke-dasharray 0.6s ease, stroke 0.3s; }

.coverage-text {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  font-family: ui-monospace, 'SF Mono', Consolas, 'Liberation Mono', monospace;
  line-height: 1;
}
.coverage-pct { font-size: 17px; font-weight: 800; color: var(--text-3); }
.coverage-unit { font-size: 10px; font-weight: 600; color: var(--text-3); margin-left: 1px; margin-top: 3px; }

.coverage-ring.cov-good .coverage-fill  { stroke: var(--status-ok); }
.coverage-ring.cov-good .coverage-pct   { color: var(--status-ok); }
.coverage-ring.cov-warn .coverage-fill  { stroke: var(--status-warn); }
.coverage-ring.cov-warn .coverage-pct   { color: var(--status-warn); }
.coverage-ring.cov-bad  .coverage-fill  { stroke: var(--status-alert); }
.coverage-ring.cov-bad  .coverage-pct   { color: var(--status-alert); }
.coverage-ring.cov-loading .coverage-fill { stroke: #475569; }
.stage-arrow-dws   { color: var(--status-ok); }

.stage-dws      { border-color: rgba(52,211,153,0.25); background: rgba(52,211,153,0.04); }

.scrape-inner { flex: 1; display: flex; flex-direction: column; align-items: center; cursor: pointer; }
.scrape-action-btn {
  width: 30px; height: 30px;
  border-radius: 6px;
  border: 1px solid rgba(37,99,235,0.3);
  background: rgba(37,99,235,0.08);
  color: var(--primary-light, var(--primary));
  cursor: pointer;
  display: flex; align-items: center; justify-content: center;
  font-size: 14px;
  transition: all 0.2s;
  flex-shrink: 0;
  margin-left: 6px;
}
.scrape-action-btn:hover { background: rgba(37,99,235,0.18); border-color: var(--primary); }
.scrape-action-btn:active { transform: scale(0.92); }
.scrape-action-btn:disabled { opacity: 0.45; cursor: not-allowed; }
.scrape-action-btn .spin { animation: spin 1s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }


</style>