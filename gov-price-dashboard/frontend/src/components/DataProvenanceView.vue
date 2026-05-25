<template>
  <div class="prov-page">

    <!-- Header -->
    <div class="prov-header">
      <div class="prov-title">🔍 数据溯源</div>
      <div class="prov-subtitle">数据来源分布 · 新鲜度追踪</div>
    </div>

    <!-- Summary Cards -->
    <div class="prov-stats">
      <div class="stat-card">
        <div class="stat-icon">📊</div>
        <div class="stat-body">
          <div class="stat-value primary">{{ data.total?.toLocaleString() }}</div>
          <div class="stat-unit">条价格数据</div>
        </div>
      </div>
      <div class="stat-card" :class="{ alert: data.stale_provinces > 0 }">
        <div class="stat-icon">⏰</div>
        <div class="stat-body">
          <div class="stat-value" :class="data.stale_provinces > 0 ? 'danger' : 'success'">{{ data.stale_provinces }}</div>
          <div class="stat-unit">数据滞后省份</div>
        </div>
      </div>
      <div class="stat-card">
        <div class="stat-icon">🆕</div>
        <div class="stat-body">
          <div class="stat-value primary">{{ data.recent_7d?.toLocaleString() }}</div>
          <div class="stat-unit">近7天入库</div>
        </div>
      </div>
      <div class="stat-card">
        <div class="stat-icon">🌍</div>
        <div class="stat-body">
          <div class="stat-value primary">{{ data.fresh_provinces }}/{{ data.provinces?.length || 0 }}</div>
          <div class="stat-unit">覆盖省份</div>
        </div>
      </div>
    </div>

    <!-- All Cities Full Pipeline -->
    <div class="prov-all-pipelines" v-if="data.all_cities">
      <div class="panel-header" style="margin-bottom:12px">
        <span class="panel-dot panel-dot-blue"></span>
        <span class="panel-title">数据同步链路（全部城市）</span>
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
            <div class="pipe-stage">
              <div class="pipe-stage-label">ODS</div>
              <div class="pipe-stage-count">{{ pipe.ods?.count?.toLocaleString() }}<span class="pipe-stage-unit">条</span></div>
              <div class="pipe-stage-date">{{ pipe.ods?.min_date }} ~ {{ pipe.ods?.max_date }}</div>
            </div>
            <div class="pipe-stage-arrow">→</div>
            <button class="pipe-stage pipe-stage-btn" @click.stop="openDwdDrilldown(key, pipe)" :class="{ disabled: !pipe.dwd?.count }">
              <div class="pipe-stage-label">DWD</div>
              <div class="pipe-stage-count">{{ pipe.dwd?.count?.toLocaleString() || "0" }}<span class="pipe-stage-unit">条</span></div>
              <div class="pipe-stage-date">{{ pipe.dwd?.min_date || "无数据" }} ~ {{ pipe.dwd?.max_date }}</div>
            </button>
            <div class="pipe-stage-arrow">→</div>
            <div class="pipe-stage">
              <div class="pipe-stage-label">DWS</div>
              <div class="pipe-stage-count">{{ pipe.dws?.count?.toLocaleString() }}<span class="pipe-stage-unit">条</span></div>
              <div class="pipe-stage-date">{{ pipe.dws?.min_date }} ~ {{ pipe.dws?.max_date }}</div>
            </div>
          </div>
          <div class="pipeline-card-etl" v-if="pipe.dwd?.last_etl">
            ETL {{ pipe.dwd?.last_etl }}
          </div>
        </div>
      </div>
    </div>

    <!-- Scrape Progress - All Cities -->
    <div class="prov-scrape" v-if="Object.keys(data.scrapeData || {}).length">
      <div class="panel-header" style="margin-bottom:12px">
        <span class="panel-dot panel-dot-amber"></span>
        <span class="panel-title">📡 ODS 抓取进度（全部城市）</span>
      </div>
      <div class="scrape-unified-list">
        <div
          v-for="(sc, scCity) in data.scrapeData"
          :key="scCity"
          class="scrape-unified-card"
          :class="{ active: scCity === selectedCity }"
          @click="selectedCity = scCity === selectedCity ? '' : scCity; loadData()"
        >
          <!-- 城市基本信息行 -->
          <div class="unified-city-row">
            <div class="unified-left">
              <span class="unified-city-label">{{ sc.city_label }}</span>
              <span v-if="sc.running > 0" class="scrape-pulse-dot"></span>
            </div>
            <div class="unified-center">
              <div class="unified-bar-wrap">
                <div class="unified-bar"
                  :class="sc.error > 0 ? 'error' : sc.completed === sc.total_counties && sc.total_counties > 0 ? 'completed' : 'running'"
                  :style="{ width: (sc.total_counties > 0 ? (sc.completed / sc.total_counties * 100) : 0) + '%' }">
                  <span v-if="sc.running > 0" class="unified-bar-shimmer"></span>
                </div>
              </div>
            </div>
            <div class="unified-right">
              <span class="unified-badge" :class="sc.error > 0 ? 'error' : sc.completed === sc.total_counties && sc.total_counties > 0 ? 'completed' : 'running'">
                {{ sc.completed }}/{{ sc.total_counties }}
              </span>
              <span class="unified-docs">{{ sc.total_docs?.toLocaleString() }}条</span>
              <span class="unified-pct">{{ sc.total_counties > 0 ? (sc.completed / sc.total_counties * 100).toFixed(1) : 0 }}%</span>
              <span class="unified-expand" :class="{ rotated: scCity === selectedCity }" @click.stop="selectedCity = scCity === selectedCity ? '' : scCity; loadData()">▶</span>
            </div>
          </div>

          <!-- 区县明细（仅激活城市展开，单行显示全部区县） -->
          <div v-if="scCity === selectedCity && selectedCityData?.counties?.length" class="unified-county-strip">
            <div
              v-for="c in selectedCityData.counties"
              :key="c.county"
              class="unified-county-chip"
              :class="c.status || 'not-started'"
            >
              <span class="chip-dot" :class="c.status || 'not-started'"></span>
              <span class="chip-name">{{ c.county }}</span>
              <span class="chip-pct" :class="c.status || 'not-started'">{{ (c.percent || 0).toFixed(0) }}%</span>
            </div>
          </div>
          <div v-else-if="scCity === selectedCity" class="unified-county-empty">暂无区县数据</div>
        </div>
      </div>
    </div>

    <div v-if="loading" class="prov-loading">
      <div class="loading-spinner"></div>
      <span>加载中...</span>
    </div>
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
          <div class="spec-quality-panel" v-if="specQuality.coverage?.length || specQuality.samples?.length">

            <div class="sq-header">
              <span class="panel-dot panel-dot-green"></span>
              <span class="panel-title">🔬 Spec 解析质量</span>
              <span class="sq-coverage-summary">
                <span class="sq-green-dot"></span>
                {{ specQuality.coverage?.filter(c => c.rate >= 80).length }} ≥80%
                <span class="sq-red-dot"></span>
                {{ specQuality.coverage?.filter(c => c.rate < 30).length }} &lt;30%
              </span>
            </div>
            <div class="sq-coverage" v-if="specQuality.coverage?.length">
              <div class="sq-cov-list">
                <div v-for="c in specQuality.coverage" :key="c.category" class="sq-cov-item" :class="sqActiveCat === c.category ? 'cat-active' : ''">
                  <span class="sq-cov-cat">{{ c.category }}</span>
                  <div class="sq-cov-bar-wrap">
                    <div class="sq-cov-bar" :style="{width: c.rate + '%'}" :class="c.rate < 10 ? 'bar-red' : c.rate < 50 ? 'bar-amber' : 'bar-green'"></div>
                  </div>
                  <span class="sq-cov-pct">{{ c.rate }}%</span>
                  <span class="sq-cov-count">{{ c.with_attr }}/{{ c.total }}</span>
                  <button class="sq-sample-btn" :class="sqActiveCat === c.category ? 'btn-active' : ''" @click="selectCatForSample(c.category)">抽样</button>
                  <button class="sq-clean-btn" :disabled="refreshLoading || cleaningCats[c.category]" @click.stop="refreshCategory(c.category)">
                    <span v-if="cleaningCats[c.category]" class="cleaning-spinner"></span>
                    <span v-else-if="cleanDoneCat === c.category">{{ cleanDoneOk ? '✓' : '✕' }}</span>
                    <span v-else>清洗</span>
                  </button>
                </div>
              </div>
            </div>
            <div v-else-if="specQuality.message" class="sq-message-hint">{{ specQuality.message }}</div>
            <div v-else class="sq-empty-hint">暂无数据</div>

            <!-- 内联确认提示 -->
            <div v-if="sqConfirmMsg" class="sq-confirm-hint">
              <span>{{ sqConfirmMsg }}</span>
              <div style="margin-top:8px;display:flex;gap:8px">
                <button class="btn-sm btn-primary" @click="handleConfirmOk">确认</button>
                <button class="btn-sm" @click="sqConfirmMsg = ''">取消</button>
              </div>
            </div>

            <!-- 内联 toast 提示 -->
            <div v-if="sqToast" class="sq-toast-hint">{{ sqToast }}</div>

            <!-- DWD 抽样 -->
            <div class="sq-samples" v-if="specQuality.samples?.length">
              <div style="font-size:11px;color:#666;padding:4px 8px;background:#fafafa;border-radius:4px;margin-bottom:8px">
                抽样结果: {{ specQuality.samples.length }} 条
                <span v-if="specQuality.message" style="color:#d97706;margin-left:8px">{{ specQuality.message }}</span>
              </div>

              <div class="sq-sample-grid">
                <div v-for="s in specQuality.samples" :key="s.spec" class="sq-sample-card" :class="s.has_attr ? 'has-attr' : 'no-attr'">
                  <div class="sq-sample-top">
                    <span class="sq-sample-spec">{{ s.spec }}</span>
                    <span class="sq-sample-status" :class="s.has_attr ? 'status-ok' : 'status-empty'">{{ s.has_attr ? '✓' : '空' }}</span>
                  </div>
                  <div class="sq-sample-meta">
                    <span class="sq-sample-cat">{{ s.category }}</span>
                    <span class="sq-sample-breed" v-if="s.breed">{{ s.breed }}</span>
                  </div>
                  <div v-if="s.attr_keys?.length" class="sq-sample-attrs">
                    <span v-for="k in s.attr_keys" :key="k" class="attr-chip">{{ k }}</span>
                  </div>
                  <div class="sq-sample-footer">
                    <button class="fix-btn" @click.stop="openFixCase(s)">修</button>
                  </div>
                </div>
              </div>
            </div>
          </div>
          <div v-else class="dwd-loading">加载中...</div>
        </div>
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
            <div class="fix-spec-row">
              <span class="fix-spec-label">当前解析</span>
              <div class="fix-current" v-if="fixCase.parsed && Object.keys(fixCase.parsed).length">
                <span v-for="(v,k) in fixCase.parsed" :key="k" class="fix-attr-chip">{{ k }}: {{ v }}</span>
              </div>
              <span class="fix-current-empty" v-else>无属性</span>
            </div>
            <!-- 规则合并解析结果 -->
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
              <span class="btn-analyze-icon">{{ fixLoading ? '⏳' : '🔍' }}</span>
              {{ fixLoading ? '分析中...' : '分析规则建议' }}
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
                  {{ sg.applied ? '✓ 已写入' : '✅ 确认写入规则 + ETL' }}
                </button>
              </div>
            </div>
          </div>

          <!-- 加载中 -->
          <div class="fix-loading-placeholder" v-else-if="fixLoading">
            <div class="fix-loading-dots"><div class="dot"></div><div class="dot"></div><div class="dot"></div></div>
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
              <div class="fix-success-title">规则已写入成功</div>
              <div class="fix-success-msg">{{ fixSuccessMsg }}</div>
              <button class="btn-ok" @click="showFixSuccess = false">确定</button>
            </div>
          </div>

        </div>
      </div>
    </div>

</template>

<script setup>
import { ref, onMounted, onUnmounted, nextTick } from 'vue'
import axios from 'axios'
import * as echarts from 'echarts'

const API = import.meta.env.VITE_API_URL || '/api'
const loading = ref(false)
const error = ref('')
const selectedCity = ref('xian')
const cityOptions = { xian: '西安', sichuan: '四川', chongqing: '重庆', jinan: '济南', rizhao: '日照' }
const cityMap = { xian: '西安', sichuan: '四川', chongqing: '重庆', jinan: '济南', rizhao: '日照' }
const data = ref({
  total: 0,
  stale_provinces: 0,
  fresh_provinces: 0,
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
let chartIns = null
let pollTimer = null
let pollingActive = ref(false)
const POLL_INTERVAL_MS = 15000

async function openDwdDrilldown(city, pipe) {
  if (!pipe.dwd?.count) return
  dwdDrilldownCity.value = city
  specQuality.value = {}   // 先清空，API 返回 coverage（_sample=false 不含抽样）
  try {
    const sq = await axios.get(`${API}/stats/spec-quality`, { params: { city, _sample: false } })
    specQuality.value = sq.data || {}

    if (specQuality.value.message && !specQuality.value.samples?.length) {
      sqToast.value = specQuality.value.message
      setTimeout(() => { sqToast.value = '' }, 4000)
    }
    if (specQuality.value.coverage) {
      sqCatOptions.value = specQuality.value.coverage.map(c => c.category)
    }
  } catch(e) { console.warn("spec-quality failed", e) }
}

async function refreshSpecQuality() {
  if (!dwdDrilldownCity.value) return
  specQuality.value = {}
  try {
    const _sample = !!sqCatFilter.value
    const _url = `${API}/stats/spec-quality`
    const _params = { city: dwdDrilldownCity.value, category: sqCatFilter.value || '', _sample }

    const sq = await axios.get(_url, { params: _params })

    specQuality.value = sq.data || {}

    if (specQuality.value.message && !specQuality.value.samples?.length) {
      sqToast.value = specQuality.value.message
      setTimeout(() => { sqToast.value = '' }, 4000)
    }
    if (specQuality.value.coverage) {
      sqCatOptions.value = specQuality.value.coverage.map(c => c.category)
    }
  } catch(e) { console.warn("spec-quality refresh failed", e) }
}

async function refreshCategory(cat) {
  if (sqConfirmMsg.value) return  // already showing a confirmation
  sqConfirmMsg.value = `确认清洗分类「${cat}」？同一分类下所有规格规则已确认后将触发 DWD 重新清洗。`
  window._sqConfirmCat = cat  // store cat for handlers below
  cleaningCats.value[cat] = true
  if (cleanDoneCat.value === cat) cleanDoneCat.value = ''
  try {
    await axios.post(`${API}/stats/spec-quality/refresh-category`, {
      city: dwdDrilldownCity.value || 'xian',
      category: cat,
    })
    sqActiveCat.value = cat
    sqCatFilter.value = cat
    cleanDoneOk.value = true
    cleanDoneCat.value = cat
    await refreshSpecQuality()
  } catch(e) {
    cleanDoneOk.value = false
    cleanDoneCat.value = cat
    console.warn("refresh-category failed", e)
  } finally {
    delete cleaningCats.value[cat]
    // 3s 后清除完成标记
    setTimeout(() => { if (cleanDoneCat.value === cat) cleanDoneCat.value = '' }, 3000)
  }
}

function selectCatForSample(cat) {
  sqActiveCat.value = cat
  sqCatFilter.value = cat
  refreshSpecQuality()
}

function handleConfirmOk() {
  const cat = window._sqConfirmCat || ''
  sqConfirmMsg.value = ''
  if (!cat) return
  cleaningCats.value[cat] = true
  if (cleanDoneCat.value === cat) cleanDoneCat.value = ''
  axios.post(`${API}/stats/spec-quality/refresh-category`, {
    city: dwdDrilldownCity.value || 'xian',
    category: cat,
  }).then(() => {
    sqActiveCat.value = cat
    sqCatFilter.value = cat
    cleanDoneOk.value = true
    cleanDoneCat.value = cat
    refreshSpecQuality()
  }).catch(e => {
    cleanDoneOk.value = false
    cleanDoneCat.value = cat
    console.warn("refresh-category failed", e)
  }).finally(() => {
    delete cleaningCats.value[cat]
    setTimeout(() => { if (cleanDoneCat.value === cat) cleanDoneCat.value = '' }, 3000)
  })
}

function closeDwdDrilldown() {
  dwdDrilldownCity.value = null
  specQuality.value = {}
}

const attrFields = ["diameter","thickness","length","width","height","material","grade","pressure","drain_type","inlet_type","voltage","current","cross_section","cores"]
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
const sqConfirmMsg = ref('')  // 内联确认提示
const cleaningCats = ref({})      // { category: true } 清洗中状态
const cleanDoneCat = ref('')      // 当前显示完成标记的分类
const cleanDoneOk = ref(true)
const fixCombinedResult = ref({})
const showFixSuccess = ref(false)
const fixSuccessMsg = ref('')

function openFixCase(s) {
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
      // 成功弹窗
      fixSuccessMsg.value = res.data.message
      showFixSuccess.value = true
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
    const [provRes, scrapeAllRes, scrapeSingleRes] = await Promise.all([
      axios.get(`${API}/stats/provenance`),
      axios.get(`${API}/stats/scrape-progress-all`),
      axios.get(`${API}/stats/scrape-progress`, { params: { city: selectedCity.value } }),
    ])
    data.value = provRes.data || {}
    data.value.scrapeData = scrapeAllRes.data || {}
    selectedCityData.value = scrapeSingleRes.data || {}
    await nextTick()
    renderChart()
  } catch (e) {
    error.value = '加载失败：' + (e.message || '网络错误')
  } finally {
    loading.value = false
  }
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
  border-color: #38bdf8;
}
.prov-title {
  font-size: 18px;
  font-weight: 700;
  color: #f1f5f9;
  text-shadow: 0 2px 12px rgba(56,189,248,0.2);
}
.prov-subtitle {
  font-size: 12px;
  color: #64748b;
  margin-top: 4px;
}

/* Summary Cards */
.prov-stats {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 12px;
  margin-bottom: 16px;
}
.stat-card {
  background: rgba(15,23,42,0.85);
  border: 1px solid rgba(255,255,255,0.08);
  border-radius: 14px;
  padding: 18px 20px;
  display: flex;
  align-items: center;
  gap: 14px;
  backdrop-filter: blur(12px);
}
.stat-card.alert { border-color: rgba(248,113,113,0.3); }
.stat-icon { font-size: 24px; line-height: 1; flex-shrink: 0; }
.stat-body { display: flex; flex-direction: column; gap: 3px; }
.stat-value {
  font-size: 20px;
  font-weight: 800;
  font-family: 'DIN Alternate', Arial, sans-serif;
  line-height: 1.1;
}
.stat-value.primary { color: #38bdf8; }
.stat-value.success { color: #34d399; }
.stat-value.danger { color: #f87171; }
.stat-unit { font-size: 11px; color: #64748b; }

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
.panel-dot-blue { background: #38bdf8; }
.panel-dot-green { background: #34d399; }
.panel-dot-amber { background: #fbbf24; }
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
.province-date.stale { color: #f87171; }
.province-date.old { color: #fbbf24; }
.province-date.fresh { color: #34d399; }
.province-badge { font-size: 10px; padding: 1px 5px; border-radius: 3px; }
.province-badge.stale { background: rgba(248,113,113,0.15); color: #f87171; }
.province-badge.old { background: rgba(245,158,11,0.15); color: #fbbf24; }
.province-badge.fresh { background: rgba(16,185,129,0.15); color: #34d399; }

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
.city-count { color: #38bdf8; font-weight: 600; }

/* Loading / Error */
.prov-loading { display: flex; align-items: center; justify-content: center; gap: 10px; padding: 24px; color: #475569; font-size: 13px; }
.prov-error { text-align: center; padding: 20px; color: #f87171; font-size: 13px; }
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
.pipeline-status.ok { background: rgba(16,185,129,0.15); color: #34d399; }
.pipeline-status.warn { background: rgba(245,158,11,0.15); color: #fbbf24; }
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
  color: #38bdf8;
  padding: 0 8px;
  flex-shrink: 0;
}
.stage-name { font-size: 11px; font-weight: 700; color: #38bdf8; letter-spacing: 1px; margin-bottom: 4px; }
.stage-count { font-size: 20px; font-weight: 800; color: #f1f5f9; font-family: 'DIN Alternate', Arial, sans-serif; line-height: 1; }
.stage-unit { font-size: 11px; font-weight: 500; color: #64748b; margin-left: 2px; }
.stage-date { font-size: 10px; color: #475569; margin-top: 4px; }
.stage-etl { font-size: 10px; color: #64748b; margin-top: 2px; }

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
.unified-bar.completed { background: #34d399; }
.unified-bar.running { background: linear-gradient(90deg, #1e4a6e, #38bdf8); }
.unified-bar.error { background: #f87171; }
.unified-bar-shimmer {
  position: absolute; top: 0; left: -100%;
  width: 55%; height: 100%;
  background: linear-gradient(90deg, transparent, rgba(255,255,255,0.3), transparent);
  animation: shimmer-slide 2s ease-in-out infinite;
}
@keyframes shimmer-slide { 0%{transform:translateX(0)} 100%{transform:translateX(300%)} }
.unified-right { display: flex; align-items: center; gap: 8px; min-width: 130px; justify-content: flex-end; }
.unified-badge { font-size: 11px; font-weight: 600; padding: 2px 7px; border-radius: 10px; }
.unified-badge.completed { background: rgba(52,211,153,0.15); color: #34d399; }
.unified-badge.running { background: rgba(56,189,248,0.12); color: #38bdf8; }
.unified-badge.error { background: rgba(248,113,113,0.12); color: #f87171; }
.unified-docs { font-size: 11px; color: #475569; }
.unified-pct { font-size: 11px; color: #64748b; min-width: 36px; text-align: right; font-family: 'DIN Alternate', Arial, sans-serif; }
.unified-expand { font-size: 11px; color: #64748b; transition: transform 0.2s, color 0.2s; margin-left: 4px; flex-shrink: 0; }
.unified-expand.rotated { transform: rotate(90deg); color: #38bdf8; font-size: 12px; }
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
.chip-dot.completed { background: #94a3b8; }
.chip-dot.running { background: #38bdf8; animation: pulse-dot 1.5s ease-in-out infinite; }
.chip-dot.not-started { background: #475569; }
.chip-name { color: #94a3b8; }
.chip-pct { color: #94a3b8; font-family: 'DIN Alternate', Arial, sans-serif; font-weight: 900; }
.chip-pct.running { color: #38bdf8; }
.chip-pct.completed { color: #34d399; }
.chip-pct.not-started { color: #475569; }
.unified-county-empty { font-size: 10px; color: #334155; padding: 4px 0; }

@keyframes pulse-dot {
  0%   { box-shadow: 0 0 0 0 rgba(56,189,248,0.5); transform: scale(1); }
  50%  { box-shadow: 0 0 0 5px rgba(56,189,248,0); transform: scale(1.15); }
  100% { box-shadow: 0 0 0 0 rgba(56,189,248,0); transform: scale(1); }
}
.scrape-pulse-dot {
  width: 7px; height: 7px; border-radius: 50%;
  background: #38bdf8;
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
.city-overview-label { font-size: 11px; color: #64748b; margin-bottom: 4px; font-weight: 600; text-transform: uppercase; }
.city-overview-count { font-size: 20px; font-weight: 800; color: #f1f5f9; font-family: 'DIN Alternate', Arial, sans-serif; line-height: 1; }
.city-overview-unit { font-size: 11px; color: #64748b; margin-left: 2px; }
.city-overview-date { font-size: 10px; color: #475569; margin-top: 4px; }
.city-overview-status { font-size: 11px; margin-top: 2px; }
.city-overview-status.ok { color: #34d399; }
.city-overview-status.error { color: #f87171; }

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
.pipe-stage-label { font-size: 10px; font-weight: 700; color: #38bdf8; letter-spacing: 0.5px; margin-bottom: 2px; }
.pipe-stage-count { font-size: 15px; font-weight: 800; color: #f1f5f9; font-family: 'DIN Alternate', Arial, sans-serif; line-height: 1; }
.pipe-stage-unit { font-size: 10px; color: #64748b; margin-left: 1px; }
.pipe-stage-date { font-size: 9px; color: #475569; margin-top: 3px; }
.pipe-stage-arrow { font-size: 14px; color: #38bdf8; flex-shrink: 0; padding: 0 2px; }
.pipeline-card-etl { font-size: 10px; color: #64748b; margin-top: 6px; }
.pipeline-status { font-size: 12px; font-weight: 600; }
.pipeline-status.ok { color: #34d399; }
.pipeline-status.warn { color: #fbbf24; }

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
  border: 1px solid #34d399;
  border-radius: 16px;
  padding: 40px 48px;
  text-align: center;
  max-width: 420px;
}
.fix-success-icon { font-size: 64px; margin-bottom: 16px; }
.fix-success-title { font-size: 22px; font-weight: 700; color: #34d399; margin-bottom: 12px; }
.fix-success-msg { font-size: 14px; color: #94a3b8; margin-bottom: 28px; line-height: 1.6; }
.btn-ok {
  background: #34d399;
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
  padding: 16px 20px;
  margin: 8px 16px;
  background: #fefce8;
  border: 1px solid #fbbf24;
  border-radius: 6px;
  color: #92400e;
  font-size: 13px;
  line-height: 1.6;
}
.sq-confirm-hint {
  padding: 12px 16px;
  margin: 0 16px 12px;
  background: #fffbeb;
  border: 1px solid #f59e0b;
  border-radius: 8px;
  color: #92400e;
  font-size: 13px;
  box-shadow: 0 2px 8px rgba(0,0,0,0.08);
}
.sq-toast-hint {
  padding: 12px 16px;
  margin: 0 16px 12px;
  background: #fffbeb;
  border: 1px solid #f59e0b;
  border-radius: 8px;
  color: #92400e;
  font-size: 13px;
  box-shadow: 0 2px 8px rgba(0,0,0,0.08);
  animation: sq-toast-in 0.2s ease;
}
@keyframes sq-toast-in {
  from { opacity: 0; transform: translateY(-4px); }
  to { opacity: 1; transform: translateY(0); }
}
</style>