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
        <button class="poll-toggle" :class="{ active: pollingActive }" @click="togglePolling">
          {{ pollingActive ? '⏸ 暂停轮询' : '▶ 开启轮询' }}
        </button>
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
            <span class="pipeline-status" :class="pipe.sync_ok ? 'ok' : 'warn'">
              {{ pipe.sync_ok ? '✓' : '⚠' }}
            </span>
          </div>
          <div class="pipeline-card-stages">
            <div class="pipe-stage stage-ods">
              <div class="pipe-stage-label stage-ods-label">ODS</div>
              <div class="pipe-stage-count">{{ pipe.ods?.count?.toLocaleString() }}<span class="pipe-stage-unit">条</span></div>
              <div class="pipe-stage-date">{{ pipe.ods?.min_date }} ~ {{ pipe.ods?.max_date }}</div>
            </div>
            <div class="pipe-stage-arrow stage-arrow-dwd">→</div>
            <div class="pipe-stage scrape-stage stage-dwd" :style="{ '--pct': dwdPct(pipe) }" :class="{ disabled: !pipe.dwd?.count }">
              <div class="scrape-inner" @click.stop="openDwdDrilldown(key, pipe)">
                <div class="pipe-stage-label stage-dwd-label">DWD</div>
                <div class="pipe-stage-count">{{ pipe.dwd?.count?.toLocaleString() || "0" }}<span class="pipe-stage-unit">条</span></div>
                <div class="pipe-stage-sub" v-if="pipe.dwd?.count">{{ (pipe.dws?.count || 0).toLocaleString() }}/{{ pipe.dwd.count.toLocaleString() }}</div>
              </div>
              <div class="stage-dwd-right">
                <div class="coverage-ring" :class="coverageClass(pipe.coverage)" :title="coverageTooltip(pipe.coverage)" @click.stop="openDwdDrilldown(key, pipe)">
                  <svg viewBox="0 0 36 36" class="coverage-svg">
                    <circle class="coverage-track" cx="18" cy="18" r="15.9"/>
                    <circle class="coverage-fill" cx="18" cy="18" r="15.9"
                      :stroke-dasharray="`${(pipe.coverage?.rate ?? 0) * 1.004}, 100`"/>
                  </svg>
                  <div class="coverage-text">
                    <span class="coverage-pct">{{ pipe.coverage ? Math.round(pipe.coverage.rate) : '—' }}</span>
                    <span class="coverage-unit">%</span>
                  </div>
                </div>
              </div>
            </div>
            <div class="pipe-stage-arrow stage-arrow-dws">→</div>
            <div class="pipe-stage stage-dws" :style="{'--pct': dwsPct(pipe)}">
              <div class="scrape-inner">
                <div class="pipe-stage-label stage-dws-label">DWS</div>
                <div class="pipe-stage-count">{{ pipe.dws?.count?.toLocaleString() }}<span class="pipe-stage-unit">条</span></div>
                <div class="pipe-stage-date">{{ pipe.dws?.min_date || '—' }} ~ {{ pipe.dws?.max_date || '—' }}</div>
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
    <div v-if="error" class="prov-error">{{ error }}</div>
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
          @fix="openFixCase"
        />
      </div>
    </div>

    <!-- Spec 修复 Modal -->
    <div class="fix-overlay" v-if="fixCase" @click.self="closeFixCase">
      <div class="fix-modal">
        <div class="fix-header">
          <div class="fix-title">✎ Spec 规则修复建议</div>
          <button class="fix-close" @click="closeFixCase">✕</button>
        </div>
        <div class="fix-body">

          <!-- 规格信息卡 -->
          <div class="fix-spec-card">
            <div class="fix-spec-row">
              <span class="fix-spec-label">规格</span>
              <span class="fix-spec-value">{{ fixCase.spec }}</span>
            </div>
            <div class="fix-spec-row" v-if="fixCombinedResult && Object.keys(fixCombinedResult).length">
              <span class="fix-spec-label">AI 解析</span>
              <div class="fix-current">
                <span v-for="(v,k) in fixCombinedResult" :key="k" class="fix-ai-result-chip">{{ k }}: {{ v }}</span>
              </div>
            </div>
            <div class="fix-spec-row" v-if="fixCase.attr_keys?.length">
              <span class="fix-spec-label">已有属性</span>
              <div class="fix-current">
                <span v-for="k in fixCase.attr_keys" :key="k" class="fix-attr-chip">{{ k }}</span>
              </div>
            </div>
          </div>

          <!-- 分析按钮 -->
          <div class="fix-actions">
            <button class="btn-analyze" @click="previewFix" :disabled="fixLoading">
              <span class="btn-analyze-icon">{{ fixLoading ? '⏳' : '✨' }}</span>
              {{ fixLoading ? 'AI 分析中...' : 'AI 建议（规则）' }}
            </button>
          </div>

          <!-- 分析结果 -->
          <div class="fix-suggestions" v-if="fixSuggestions.length">
            <div class="fix-suggestions-header">
              <span class="fix-suggestions-count">{{ fixSuggestions.length }} 条规则建议</span>
            </div>
            <div v-for="(sg, i) in fixSuggestions" :key="i" class="fix-suggestion-card">
              <div class="fix-sg-card-header">
                <div class="fix-sg-rule-badge">
                  <span class="fix-sg-attr-tag">{{ sg.attr }}</span>
                  <span class="fix-sg-note-tag">{{ sg.note }}</span>
                </div>
              </div>
              <div class="fix-sg-card-body">
                <div class="fix-sg-pattern-row">
                  <span class="fix-sg-key">pattern</span>
                  <code class="fix-sg-pattern">{{ sg.pattern }}</code>
                </div>
                <div class="fix-sg-code-block">
                  <pre class="fix-sg-code">{{ sg.code_block }}</pre>
                </div>
                <div class="fix-sg-result-row" v-if="sg.parse_result && Object.keys(sg.parse_result).length">
                  <span class="fix-sg-key">解析结果</span>
                  <div class="fix-sg-result-tags">
                    <span v-for="(v,k) in sg.parse_result" :key="k" class="fix-sg-result-chip">{{ k }}: {{ v }}</span>
                  </div>
                </div>
              </div>
              <div class="fix-sg-card-footer">
                <button class="btn-confirm-fix" :disabled="sg.applied" @click="confirmFix(sg)">
                  {{ sg.applied ? '✓ 已录入' : '✅ 确认录入规则库' }}
                </button>
              </div>
            </div>
          </div>

          <!-- 加载中 -->
          <div class="fix-loading-placeholder" v-else-if="fixLoading">
            <div class="fix-loading-funnel"><div class="funnel-icon">⏳</div></div>
            <span>AI 分析中...</span>
          </div>

          <!-- 结果反馈 -->
          <div class="fix-result" v-if="fixResult">
            <div class="fix-result-ok" v-if="fixResult.ok">✅ {{ fixResult.message }}</div>
            <div class="fix-result-fail" v-else>❌ {{ fixResult.message }}</div>
          </div>

          <!-- 成功弹窗 -->
          <div class="fix-success-modal" v-if="showFixSuccess">
            <div class="fix-success-content">
              <div class="fix-success-icon">✅</div>
              <div class="fix-success-title">规则已录入规则库</div>
              <div class="fix-success-msg">{{ fixSuccessMsg }}</div>
              <button class="btn-ok" @click="showFixSuccess = false">确定</button>
            </div>
          </div>

        </div>
      </div>
    </div>

</template>

<script setup>
import { ref, computed, onMounted, onUnmounted, nextTick } from 'vue'
import axios from 'axios'
import * as echarts from 'echarts'
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
const coverageByCity = ref({})  // { city: { rate, with_attr, needs_parse, total } }
let chartIns = null
let pollTimer = null
let pollingActive = ref(false)
const POLL_INTERVAL_MS = 15000

function scrapePct(scrape) {
  if (!scrape?.total_counties) return '0%'
  return ((scrape.completed / scrape.total_counties) * 100).toFixed(1) + '%'
}

function dwdPct(pipe) {
  if (!pipe.ods?.count) return '0%'
  const dwdCount = pipe.dwd?.count || 0
  return ((dwdCount / pipe.ods.count) * 100).toFixed(1) + '%'
}

function dwsPct(pipe) {
  if (!pipe.dwd?.count) return '0%'
  const dwsCount = pipe.dws?.count || 0
  return ((dwsCount / pipe.dwd.count) * 100).toFixed(1) + '%'
}

async function runFlushDws(city) {
  dwsRunning.value = { ...dwsRunning.value, [city]: true }
  try {
    await axios.post(`${API}/stats/provenance/flush-city`, { city })
  } catch (e) {
    console.error('flush-city failed', e)
  } finally {
    dwsRunning.value = { ...dwsRunning.value, [city]: false }
  }
  loadData()
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
      console.log('[coverage] 刷新后钢材分类:', newCoverage.find(c => c.category.includes('钢材')), '城市:', dwdDrilldownCity.value)
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
const fixCase = ref(null)
const fixSuggestions = ref([])
const fixResult = ref(null)
const fixLoading = ref(false)
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
const fixCombinedResult = ref({})
const showFixSuccess = ref(false)
const fixSuccessMsg = ref('')

function openFixCase(s) {
  sqActiveCat.value = ''
  fixCase.value = s
  fixSuggestions.value = []
  fixResult.value = null
}

function closeFixCase() {
  fixCase.value = null
  fixSuggestions.value = []
  fixResult.value = null
  fixCombinedResult.value = {}
}

async function previewFix() {
  if (!fixCase.value) return
  fixLoading.value = true
  fixSuggestions.value = []
  fixResult.value = null
  try {
    const res = await axios.post(`${API}/stats/spec-quality/fix-case`, {
      city: dwdDrilldownCity.value || 'xian',
      spec: fixCase.value.spec,
      breed: fixCase.value.breed || '',
      category: fixCase.value.category || '',
      expected: {},
      confirm: false,
    })
    if (res.data.ok) {
      fixSuggestions.value = res.data.suggestions || []
      fixCombinedResult.value = res.data.parse_result || {}
    } else {
      fixResult.value = { ok: false, message: res.data.message }
    }
  } catch(e) {
    fixResult.value = { ok: false, message: e.message }
  } finally {
    fixLoading.value = false
  }
}

async function confirmFix(sg) {
  if (!fixCase.value) return
  fixLoading.value = true
  fixResult.value = null
  try {
    const res = await axios.post(`${API}/stats/spec-quality/fix-case`, {
      city: dwdDrilldownCity.value || 'xian',
      spec: fixCase.value.spec,
      breed: fixCase.value.breed || '',
      category: fixCase.value.category || '',
      expected: {},
      confirm: true,
      suggestions: [sg],
    })
    fixResult.value = res.data
    if (res.data.ok) {
      sg.applied = true
    }
  } catch(e) {
    fixResult.value = { ok: false, message: e.message }
  } finally {
    fixLoading.value = false
  }
}

function togglePolling() {
  pollingActive.value = !pollingActive.value
  if (pollTimer) { clearInterval(pollTimer); pollTimer = null }
  if (pollingActive.value) {
    loadData()
    pollTimer = setInterval(loadData, POLL_INTERVAL_MS)
  }
}

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
  return `attr 覆盖率: ${c.rate.toFixed(1)}%\n已解析: ${c.with_attr.toLocaleString()}\n待解析: ${c.needs_parse.toLocaleString()}\n总计: ${c.total.toLocaleString()}`
}

function renderChart() {
  const el = document.getElementById('dailyTrendChart')
  if (!el || !data.value.daily?.length) return
  if (chartIns) chartIns.dispose()

  chartIns = echarts.init(el)
  const daily = data.value.daily

  const dates = daily.map(d => d.date?.slice(5)) // MM-DD
  const counts = daily.map(d => d.count)

  chartIns.setOption({
    backgroundColor: 'transparent',
    grid: { top: 12, bottom: 24, left: 50, right: 16 },
    tooltip: {
      trigger: 'axis',
      backgroundColor: 'rgba(15,23,42,0.95)',
      borderColor: 'rgba(255,255,255,0.1)',
      textStyle: { color: '#e2e8f0', fontSize: 12 },
      formatter: (params) => `${params[0].name}<br/>入库 <b>${params[0].value?.toLocaleString()}</b> 条`,
    },
    xAxis: {
      type: 'category',
      data: dates,
      axisLine: { lineStyle: { color: 'rgba(255,255,255,0.08)' } },
      axisTick: { show: false },
      axisLabel: { color: '#475569', fontSize: 10 },
    },
    yAxis: {
      type: 'value',
      splitLine: { lineStyle: { color: 'rgba(255,255,255,0.04)' } },
      axisLabel: { color: '#475569', fontSize: 10 },
    },
    series: [{
      type: 'bar',
      data: counts,
      itemStyle: {
        color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
          { offset: 0, color: '#38bdf8' },
          { offset: 1, color: 'rgba(56,189,248,0.3)' },
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
  if (pollingActive.value) {
    pollTimer = setInterval(loadData, POLL_INTERVAL_MS)
  }
})
onUnmounted(() => {
  if (pollTimer) clearInterval(pollTimer)
})
</script>

<style scoped>
.prov-page {
  padding: 16px 20px 80px;
  min-height: 100vh;
  color: #e2e8f0;
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
  background: #1e293b;
  color: #e2e8f0;
  border: 1px solid rgba(255,255,255,0.12);
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
  color: #f1f5f9;
  text-shadow: 0 2px 12px rgba(56,189,248,0.2);
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
  background: #0f172a;
  border: 1px solid rgba(255,255,255,0.07);
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
.panel-title { font-size: 13px; font-weight: 600; color: #e2e8f0; }
.panel-hint { font-size: 10px; color: #475569; margin-left: auto; }

/* Province list */
.prov-province-panel {
  background: #0f172a;
  border: 1px solid rgba(255,255,255,0.07);
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
  border-bottom: 1px solid rgba(255,255,255,0.03);
  border-radius: 4px;
}
.province-row:last-child { border-bottom: none; }
.province-row.stale { background: rgba(248,113,113,0.06); }
.province-row.old { background: rgba(245,158,11,0.04); }
.province-info { display: flex; flex-direction: column; gap: 1px; }
.province-name { font-size: 13px; font-weight: 500; color: #cbd5e1; }
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
  background: #0f172a;
  border: 1px solid rgba(255,255,255,0.07);
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
  background: rgba(255,255,255,0.04);
  border: 1px solid rgba(255,255,255,0.07);
  border-radius: 20px;
  padding: 3px 10px;
  font-size: 11px;
}
.city-name { color: #e2e8f0; font-weight: 500; }
.city-province { color: #475569; }
.city-count { color: var(--primary); font-weight: 600; }

/* Loading / Error */
.prov-loading { display: flex; align-items: center; justify-content: center; gap: 10px; padding: 24px; color: #475569; font-size: 13px; }
.prov-error { text-align: center; padding: 20px; color: var(--status-alert); font-size: 13px; }
.loading-spinner { width: 18px; height: 18px; border: 2px solid rgba(255,255,255,0.1); border-top-color: #60a5fa; border-radius: 50%; animation: spin 0.8s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }

@media (max-width: 900px) {
  .prov-stats { grid-template-columns: repeat(2, 1fr); }
  .prov-main { grid-template-columns: 1fr; }
}

/* Pipeline */
.prov-pipeline {
  background: #0f172a;
  border: 1px solid rgba(255,255,255,0.07);
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
.pipeline-title { font-size: 13px; font-weight: 600; color: #e2e8f0; }
.pipeline-status { font-size: 12px; padding: 2px 10px; border-radius: 12px; font-weight: 500; }
.pipeline-status.ok { background: rgba(16,185,129,0.15); color: var(--status-ok); }
.pipeline-status.warn { background: rgba(245,158,11,0.15); color: var(--status-warn); }
.pipeline-stages {
  display: flex;
  align-items: center;
  gap: 0;
}
.pipeline-stage {
  flex: 1;
  background: rgba(255,255,255,0.03);
  border: 1px solid rgba(255,255,255,0.06);
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
.stage-count { font-size: 20px; font-weight: 800; color: #f1f5f9; font-family: ui-monospace, 'SF Mono', Consolas, 'Liberation Mono', monospace; line-height: 1; }
.stage-unit { font-size: 11px; font-weight: 500; color: var(--text-3); margin-left: 2px; }
.stage-date { font-size: 10px; color: #475569; margin-top: 4px; }
.stage-etl { font-size: 10px; color: var(--text-3); margin-top: 2px; }

/* Scrape All Cities */
/* ODS 抓取进度（统一列表） */
.prov-scrape {
  background: #0f172a;
  border: 1px solid rgba(255,255,255,0.07);
  border-radius: 10px;
  padding: 14px 16px;
  margin-bottom: 12px;
}
.scrape-unified-list { display: flex; flex-direction: column; gap: 4px; }
.scrape-unified-card {
  background: rgba(255,255,255,0.03);
  border: 1px solid rgba(255,255,255,0.06);
  border-radius: 8px;
  padding: 10px 12px;
  cursor: pointer;
  transition: all 0.2s;
}
.scrape-unified-card:hover { border-color: rgba(56,189,248,0.25); }
.scrape-unified-card.active {
  border-color: rgba(56,189,248,0.45);
  background: rgba(56,189,248,0.05);
}
.scrape-unified-card.active.running { animation: card-pulse 2s ease-in-out infinite; }
@keyframes card-pulse {
  0%,100%{box-shadow:0 0 0 0 rgba(56,189,248,0)} 50%{box-shadow:0 0 8px 2px rgba(56,189,248,0.15)}
}
.unified-city-row { display: grid; grid-template-columns: 52px 1fr auto; align-items: center; gap: 10px; }
.unified-left { display: flex; align-items: center; gap: 6px; }
.unified-city-label { font-size: 13px; font-weight: 700; color: #f1f5f9; }
.unified-bar-wrap { height: 8px; background: rgba(255,255,255,0.07); border-radius: 4px; overflow: hidden; }
.unified-bar { height: 100%; border-radius: 4px; transition: width 0.8s ease; position: relative; overflow: hidden; }
.unified-bar.completed { background: var(--status-ok); }
.unified-bar.running { background: linear-gradient(90deg, #1e4a6e, var(--primary)); }
.unified-bar.error { background: var(--status-alert); }
.unified-bar-shimmer {
  position: absolute; top: 0; left: -100%;
  width: 55%; height: 100%;
  background: linear-gradient(90deg, transparent, rgba(255,255,255,0.3), transparent);
  animation: shimmer-slide 2s ease-in-out infinite;
}
@keyframes shimmer-slide { 0%{transform:translateX(0)} 100%{transform:translateX(300%)} }
.unified-right { display: flex; align-items: center; gap: 8px; min-width: 130px; justify-content: flex-end; }
.unified-badge { font-size: 11px; font-weight: 600; padding: 2px 7px; border-radius: 10px; }
.unified-badge.completed { background: rgba(52,211,153,0.15); color: var(--status-ok); }
.unified-badge.running { background: rgba(56,189,248,0.12); color: var(--primary); }
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
  border: 1px solid rgba(255,255,255,0.04);
  border-radius: 4px;
  font-size: 10px;
}
.unified-county-chip.running {
  border-color: rgba(56,189,248,0.35);
  background: rgba(56,189,248,0.12);
  box-shadow: 0 0 8px rgba(56,189,248,0.15);
}
.unified-county-chip.completed { border-color: rgba(255,255,255,0.08); background: rgba(255,255,255,0.04); }
.chip-dot { width: 4px; height: 4px; border-radius: 50%; flex-shrink: 0; }
.chip-dot.completed { background: var(--text-3); }
.chip-dot.running { background: var(--primary); animation: pulse-dot 1.5s ease-in-out infinite; }
.chip-dot.not-started { background: #475569; }
.chip-name { color: var(--text-3); }
.chip-pct { color: var(--text-3); font-family: ui-monospace, 'SF Mono', Consolas, 'Liberation Mono', monospace; font-weight: 900; }
.chip-pct.running { color: var(--primary); }
.chip-pct.completed { color: var(--status-ok); }
.chip-pct.not-started { color: #475569; }
.unified-county-empty { font-size: 10px; color: #334155; padding: 4px 0; }

@keyframes pulse-dot {
  0%   { box-shadow: 0 0 0 0 rgba(56,189,248,0.5); transform: scale(1); }
  50%  { box-shadow: 0 0 0 5px rgba(56,189,248,0); transform: scale(1.15); }
  100% { box-shadow: 0 0 0 0 rgba(56,189,248,0); transform: scale(1); }
}
.scrape-pulse-dot {
  width: 7px; height: 7px; border-radius: 50%;
  background: var(--primary);
  animation: pulse-dot 1.5s ease-in-out infinite;
  box-shadow: 0 0 0 0 rgba(56,189,248,0.5);
}

/* Cities Overview */
.prov-cities-overview {
  background: #0f172a;
  border: 1px solid rgba(255,255,255,0.07);
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
  background: rgba(255,255,255,0.03);
  border: 1px solid rgba(255,255,255,0.07);
  border-radius: 8px;
  padding: 10px 14px;
  cursor: pointer;
  transition: all 0.2s;
  position: relative;
}
.city-overview-card:hover {
  border-color: rgba(56,189,248,0.3);
  background: rgba(56,189,248,0.05);
}
.city-overview-card.active {
  border-color: rgba(56,189,248,0.5);
  background: rgba(56,189,248,0.08);
}
.city-overview-label { font-size: 11px; color: var(--text-3); margin-bottom: 4px; font-weight: 600; text-transform: uppercase; }
.city-overview-count { font-size: 20px; font-weight: 800; color: #f1f5f9; font-family: ui-monospace, 'SF Mono', Consolas, 'Liberation Mono', monospace; line-height: 1; }
.city-overview-unit { font-size: 11px; color: var(--text-3); margin-left: 2px; }
.city-overview-date { font-size: 10px; color: #475569; margin-top: 4px; }
.city-overview-status { font-size: 11px; margin-top: 2px; }
.city-overview-status.ok { color: var(--status-ok); }
.city-overview-status.error { color: var(--status-alert); }

/* All Cities Full Pipeline */
.prov-all-pipelines {
  background: #0f172a;
  border: 1px solid rgba(255,255,255,0.07);
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
  background: rgba(255,255,255,0.03);
  border: 1px solid rgba(255,255,255,0.07);
  border-radius: 8px;
  padding: 10px 14px;
  cursor: pointer;
  transition: all 0.2s;
}
.pipeline-card:hover {
  border-color: rgba(56,189,248,0.3);
  background: rgba(56,189,248,0.04);
}
.pipeline-card.active {
  border-color: rgba(56,189,248,0.5);
  background: rgba(56,189,248,0.07);
}
.pipeline-card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
}
.pipeline-card-city { font-size: 13px; font-weight: 700; color: #e2e8f0; }
.pipeline-card-stages {
  display: flex;
  align-items: center;
  gap: 4px;
}
.pipe-stage {
  flex: 1;
  text-align: center;
  background: rgba(255,255,255,0.02);
  border: 1px solid rgba(255,255,255,0.05);
  border-radius: 6px;
  padding: 6px 8px;
}
.pipe-stage-btn { cursor: pointer; transition: all 0.2s; position: relative; }
.pipe-stage-btn::after {
  content: '';
  position: absolute;
  bottom: 0; left: 0; right: 0;
  height: 3px;
  background: linear-gradient(90deg, var(--status-ok) var(--pct, 0%), rgba(255,255,255,0.1) var(--pct, 0%));
  border-radius: 0 0 6px 6px;
  transition: background 0.4s ease;
}
.pipe-progress-wrap { height: 3px; background: rgba(255,255,255,0.08); border-radius: 2px; margin: 4px 0 2px; overflow: hidden; }
.pipe-progress-fill { height: 100%; background: linear-gradient(90deg, var(--primary), var(--status-ok)); border-radius: 2px; transition: width 0.4s ease; }
.pipe-stage-label { font-size: 10px; font-weight: 700; color: var(--primary); letter-spacing: 0.5px; margin-bottom: 2px; }
.pipe-stage-count { font-size: 15px; font-weight: 800; color: #f1f5f9; font-family: ui-monospace, 'SF Mono', Consolas, 'Liberation Mono', monospace; line-height: 1; }
.pipe-stage-unit { font-size: 10px; color: var(--text-3); margin-left: 1px; }
.pipe-stage-date { font-size: 9px; color: #475569; margin-top: 3px; }
.pipe-stage-sub { font-size: 9px; color: var(--status-ok); margin-top: 2px; }
.pipe-stage-arrow { font-size: 14px; color: var(--primary); flex-shrink: 0; padding: 0 2px; }
.pipeline-card-etl { font-size: 10px; color: var(--text-3); margin-top: 6px; }
.pipeline-card-counties {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  margin-top: 8px;
  padding: 6px 8px;
  background: rgba(255,255,255,0.03);
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
  background: rgba(255,255,255,0.04);
  border: 1px solid rgba(255,255,255,0.06);
}
.pipeline-county-chip.running { border-color: rgba(56,189,248,0.3); }
.pipeline-county-chip.completed { border-color: rgba(255,255,255,0.08); }
.pipeline-status { font-size: 12px; font-weight: 600; }
.pipeline-status.ok { color: var(--status-ok); }
.pipeline-status.warn { color: var(--status-warn); }

.fix-success-modal {
  position: fixed;
  inset: 0;
  background: rgba(0,0,0,0.7);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 9999;
}
.fix-success-content {
  background: #1e293b;
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
  color: #0f172a;
  border: none;
  border-radius: 8px;
  padding: 10px 40px;
  font-size: 16px;
  font-weight: 600;
  cursor: pointer;
}
.btn-ok:hover { background: #6ee7b7; }

/* 清洗按钮动态效果 */
.cleaning-spinner {
  display: inline-block;
  width: 12px;
  height: 12px;
  border: 2px solid rgba(255,255,255,0.4);
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
  background: rgba(56,189,248,0.08);
  border: 1px solid rgba(56,189,248,0.25);
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
  background: #1e293b;
  border: 1px solid #334155;
  border-radius: 10px;
  box-shadow: 0 4px 16px rgba(0,0,0,0.25);
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
  color: #f1f5f9;
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
  border: 1px solid #334155;
  border-radius: 8px;
  padding: 7px 14px;
  font-size: 13px;
  cursor: pointer;
  transition: all 0.15s;
}
.sq-confirm-cancel:hover {
  background: #1e293b;
  color: var(--text-3);
  border-color: #475569;
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
  box-shadow: 0 2px 8px rgba(56,189,248,0.35);
  transition: opacity 0.15s, transform 0.1s;
}
.sq-confirm-ok:hover { opacity: 0.88; }
.sq-confirm-ok:active { transform: scale(0.97); }

.sq-toast-hint {
  padding: 12px 16px;
  margin: 8px 16px;
  background: rgba(56,189,248,0.08);
  border: 1px solid rgba(56,189,248,0.25);
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
  background: #0f172a;
  border: 1px solid rgba(255,255,255,0.07);
  border-radius: 10px;
  padding: 14px 16px;
  margin-bottom: 12px;
}
.vec-total-badge {
  font-size: 11px;
  background: rgba(56,189,248,0.12);
  color: var(--primary);
  border-radius: 10px;
  padding: 2px 8px;
  margin-left: 8px;
}
.vec-search {
  margin-left: 12px;
  background: rgba(255,255,255,0.05);
  border: 1px solid rgba(255,255,255,0.1);
  border-radius: 6px;
  color: #e2e8f0;
  font-size: 12px;
  padding: 4px 10px;
  width: 160px;
  outline: none;
}
.vec-search:focus { border-color: var(--primary); }
.vec-attr-select {
  margin-left: 8px;
  background: rgba(255,255,255,0.05);
  border: 1px solid rgba(255,255,255,0.1);
  border-radius: 6px;
  color: #e2e8f0;
  font-size: 12px;
  padding: 4px 8px;
  outline: none;
  cursor: pointer;
}
.vec-table-wrap { overflow-x: auto; margin-top: 10px; }
.vec-table { width: 100%; border-collapse: collapse; font-size: 12px; }
.vec-table th {
  background: rgba(255,255,255,0.04);
  color: var(--text-3);
  font-weight: 600;
  padding: 7px 10px;
  text-align: left;
  white-space: nowrap;
  border-bottom: 1px solid rgba(255,255,255,0.06);
}
.vec-table td {
  padding: 6px 10px;
  border-bottom: 1px solid rgba(255,255,255,0.04);
  vertical-align: top;
}
.vec-table tr:hover td { background: rgba(255,255,255,0.02); }
.vec-id { color: #475569; font-family: monospace; width: 40px; }
.vec-attr-tag {
  display: inline-block;
  background: rgba(56,189,248,0.1);
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
  color: #a5f3fc;
  background: rgba(56,189,248,0.06);
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
  color: #86efac;
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
.vec-empty { text-align: center; color: #334155; padding: 20px; }
.vec-pagination { display: flex; align-items: center; justify-content: center; gap: 12px; margin-top: 12px; }
.vec-page-info { font-size: 12px; color: var(--text-3); }

.scrape-stage { flex: 1; display: flex; align-items: center; background: rgba(255,255,255,0.02); border: 1px solid rgba(255,255,255,0.05); border-radius: 6px; padding: 6px 8px; gap: 4px; }

/* 各阶段独立配色 */
.stage-scrape   { border-color: rgba(168,85,247,0.25); background: rgba(168,85,247,0.04); }
.stage-scrape-label { color: #c084fc !important; }
.stage-arrow-ods   { color: var(--status-warn); }

.stage-ods     { border-color: rgba(245,158,11,0.25); background: rgba(245,158,11,0.04); }
.stage-ods-label { color: var(--status-warn) !important; }
.stage-arrow-dwd   { color: var(--primary); }

.stage-dwd      { border-color: rgba(56,189,248,0.25); background: rgba(56,189,248,0.04); position: relative; }
.stage-dwd-label { color: var(--primary) !important; }

/* DWD 区域右侧：覆盖率环 + 同步按钮 */
.stage-dwd-right { display: flex; flex-direction: column; align-items: center; gap: 4px; flex-shrink: 0; }

.coverage-ring {
  position: relative;
  width: 44px;
  height: 44px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: transform 0.2s;
}
.coverage-ring:hover { transform: scale(1.08); }
.coverage-svg { width: 100%; height: 100%; transform: rotate(-90deg); }
.coverage-track { fill: none; stroke: rgba(255,255,255,0.08); stroke-width: 3; }
.coverage-fill  { fill: none; stroke-width: 3; stroke-linecap: round; transition: stroke-dasharray 0.6s ease, stroke 0.3s; }

.coverage-text {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  font-family: ui-monospace, 'SF Mono', Consolas, 'Liberation Mono', monospace;
  line-height: 1;
}
.coverage-pct { font-size: 12px; font-weight: 800; color: var(--text-3); }
.coverage-unit { font-size: 8px; font-weight: 600; color: var(--text-3); margin-left: 0.5px; margin-top: 1px; }

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
  border: 1px solid rgba(56,189,248,0.3);
  background: rgba(56,189,248,0.08);
  color: var(--primary-light, var(--primary));
  cursor: pointer;
  display: flex; align-items: center; justify-content: center;
  font-size: 14px;
  transition: all 0.2s;
  flex-shrink: 0;
  margin-left: 6px;
}
.scrape-action-btn:hover { background: rgba(56,189,248,0.18); border-color: var(--primary); }
.scrape-action-btn:active { transform: scale(0.92); }
.scrape-action-btn:disabled { opacity: 0.45; cursor: not-allowed; }
.scrape-action-btn .spin { animation: spin 1s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }


</style>