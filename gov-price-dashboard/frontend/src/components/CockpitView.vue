<template>
  <div class="cockpit">
    <!-- 顶部 HUD 标题栏(P0-2 简化:轮询控制已下沉 TopBar,这里只剩状态展示) -->
    <div class="hud-header">
      <div class="hud-title">
        <span class="hud-prefix">数据驾驶舱</span>
        <span class="hud-prefix-sub">· 全局每 {{ pollIntervalMin }} 分钟自动刷新 · 在顶栏可暂停</span>
      </div>
      <div class="hud-status">
        <span class="hud-clock mono">{{ clock }}</span>
        <span class="hud-live" :class="{ active: !pollingPaused, paused: pollingPaused }">
          {{ pollingPaused ? '⏸ 已暂停' : '● 运行中' }}
        </span>
      </div>
    </div>

    <!-- 加载 / 错误状态 -->
    <div v-if="loading && !data.all_cities" class="cockpit-loading">
      <SkeletonCard :lines="6" :hide-footer="true" />
    </div>
    <div v-else-if="!data.all_cities || Object.keys(data.all_cities).length === 0">
      <EmptyState icon="📡" title="暂无数据" message="驾驶舱数据加载中或上游接口不可用" />
    </div>
    <ErrorState v-if="error" :title="'加载失败'" :message="error" compact :on-retry="loadData" />

    <template v-if="data.all_cities">
      <!-- ============ Row 1: 总览区 = 入库总量 (大字 4列) + 3 转化率圆环 (各 2.67列) ============ -->
      <div class="gauge-row">
        <!-- 2026-07-28:Phase 2 — 入库总量 hero-stat 迁 <el-card> + <el-statistic> -->
        <el-card shadow="hover" class="gauge-card gauge-card-hero cockpit-hero-card">
          <template #header>
            <div class="gauge-label">入库总量</div>
            <div class="gauge-sub">ODS 原始数据量</div>
          </template>
          <el-statistic :value="kpi.ods" class="cockpit-hero-stat">
            <template #suffix><span class="hero-unit"> 条</span></template>
          </el-statistic>
          <div class="hero-meta">
            <div class="hero-meta-row">
              <span class="hero-meta-label">覆盖城市</span>
              <span class="hero-meta-value">{{ cityCount }} 个</span>
            </div>
            <div class="hero-meta-row">
              <span class="hero-meta-label">DWD 清洗</span>
              <span class="hero-meta-value">{{ fmt.compact(kpi.dwd) }} 条</span>
            </div>
            <div class="hero-meta-row">
              <span class="hero-meta-label">DWS 服务</span>
              <span class="hero-meta-value">{{ fmt.compact(kpi.dws) }} 条</span>
            </div>
          </div>
        </el-card>

        <div class="gauge-card">
          <div class="gauge-label">清洗完成率</div>
          <svg viewBox="0 0 200 200" class="gauge-svg">
            <circle class="gauge-track" cx="100" cy="100" r="80" />
            <circle class="gauge-fill"
              cx="100" cy="100" r="80"
              :stroke-dasharray="`${dwdPctAll * 5.025}, 503`"
              transform="rotate(-90 100 100)" />
            <text x="100" y="100" class="gauge-num gauge-num-big">{{ dwdPctAll.toFixed(1) }}</text>
            <text x="100" y="138" class="gauge-unit">%</text>
          </svg>
          <div class="gauge-foot">
            <span class="gauge-tag tag-blue">{{ dwdPctAll >= 90 ? '✓ 优秀' : dwdPctAll >= 70 ? '● 良好' : '⚠ 待提升' }}</span>
            <span class="gauge-trend">{{ fmt.compact(kpi.dwd) }} / {{ fmt.compact(kpi.ods) }}</span>
          </div>
          <div class="gauge-formula" :title="dwdPctFormulaDetail">
            {{ dwdPctAll.toFixed(1) }} = Σ DWD / Σ ODS
          </div>
        </div>

        <div class="gauge-card">
          <div class="gauge-label">服务覆盖率</div>
          <svg viewBox="0 0 200 200" class="gauge-svg">
            <circle class="gauge-track" cx="100" cy="100" r="80" />
            <circle class="gauge-fill"
              cx="100" cy="100" r="80"
              :stroke-dasharray="`${dwsPctAll * 5.025}, 503`"
              transform="rotate(-90 100 100)" />
            <text x="100" y="100" class="gauge-num gauge-num-big">{{ dwsPctAll.toFixed(1) }}</text>
            <text x="100" y="138" class="gauge-unit">%</text>
          </svg>
          <div class="gauge-foot">
            <span class="gauge-tag tag-blue">{{ dwsPctAll >= 90 ? '✓ 优秀' : dwsPctAll >= 70 ? '● 良好' : '⚠ 待提升' }}</span>
            <span class="gauge-trend">{{ fmt.compact(kpi.dws) }} / {{ fmt.compact(kpi.dwd) }}</span>
          </div>
          <div class="gauge-formula" :title="dwsPctFormulaDetail">
            {{ dwsPctAll.toFixed(1) }} = Σ DWS / Σ DWD
          </div>
        </div>

        <div class="gauge-card">
          <div class="gauge-label">属性解析覆盖率</div>
          <svg viewBox="0 0 200 200" class="gauge-svg">
            <circle class="gauge-track" cx="100" cy="100" r="80" />
            <circle class="gauge-fill"
              cx="100" cy="100" r="80"
              :stroke-dasharray="`${kpi.attrRate * 5.025}, 503`"
              transform="rotate(-90 100 100)" />
            <text x="100" y="100" class="gauge-num gauge-num-big">{{ kpi.attrRate.toFixed(1) }}</text>
            <text x="100" y="138" class="gauge-unit">%</text>
          </svg>
          <div class="gauge-foot">
            <span class="gauge-tag tag-blue">{{ kpi.attrRate >= 90 ? '✓ 优秀' : kpi.attrRate >= 70 ? '● 良好' : '⚠ 待提升' }}</span>
            <span class="gauge-trend">{{ cityCount }} 城实时</span>
          </div>
          <div class="gauge-formula" :title="attrRateFormulaDetail">
            {{ kpi.attrRate.toFixed(1) }} = avg({{ cityCount }} 城 with_attr/total)
          </div>
        </div>
      </div>

      <!-- ============ Row 2: 12 栅格 — 地图 8 + 管道 4（地图突出，加高） ============ -->
            <!-- 2026-07-20 修改 13: 删除"数据处理管道 · 20 城"块（接口不共用），地理分布满宽 -->
      <div class="grid-row grid-row-main">
        <section class="grid-cell grid-geo">
          <div class="section-title">
            <span class="section-icon">🗺️</span>
            地理分布
            <span class="section-sub">按地区聚合材料价格 · 点击下钻</span>
          </div>
          <GeoMapView :hide-header="true" />
        </section>
      </div>

      <!-- ============ Row 3: Skill 更新记录（12 列） ============ -->
      <section class="skill-updates-section grid-row grid-row-skill">
        <div class="section-title">
          <span class="section-dot"></span>
          Skill 更新记录 · {{ cityCount }} 城市 · 各 skill 最近检查/更新
          <span class="section-sub mono">扫描于 {{ updatesNow || '—' }}</span>
        </div>
        <div class="skill-updates-grid" style="margin-top:0">
          <div v-for="u in skillUpdates" :key="u.city" class="skill-update-card"
            :class="['status-' + u.status]">

            <div class="update-header">
              <span class="update-city">{{ u.city_label }}</span>
              <span class="update-status" :class="u.status">
                <span v-if="u.status === 'fresh'">✓ 正常</span>
                <span v-else-if="u.status === 'stale'">⚠ 过期</span>
                <span v-else-if="u.status === 'very_stale'">✗ 严重过期</span>
                <span v-else>— 无数据</span>
              </span>
            </div>
            <div class="update-body">
              <div class="update-row">
                <span class="update-label">最后更新</span>
                <span class="update-value mono">{{ formatUpdateTime(u.last_updated) }}</span>
              </div>
              <div class="update-row">
                <span class="update-label">距今</span>
                <span class="update-value mono">{{ u.hours_since != null ? hoursAgo(u.hours_since) : '—' }}</span>
              </div>
              <div class="update-row">
                <span class="update-label">最新周期</span>
                <span class="update-value mono">{{ u.latest_period || '—' }}</span>
              </div>
              <div v-if="u.has_incremental" class="update-badge">
                <span class="badge-incremental">+ 增量</span>
              </div>
            </div>
          </div>
        </div>
      </section>

      <!-- ============ Row 4: 底部状态条(P0-1 拆 3 组：运行 / 数据质量 / 规模) ============ -->
      <div class="hud-footer grid-row grid-row-footer">
        <div class="footer-group" data-group="ops">
          <span class="footer-group-label">运行</span>
          <div class="footer-group-cells">
            <div class="footer-cell">
              <span class="footer-label">系统</span>
              <span class="footer-value status-ok">✓ 正常</span>
            </div>
            <div class="footer-cell">
              <span class="footer-label">轮询</span>
              <span class="footer-value mono">{{ pollMinutes }}</span>
            </div>
            <div class="footer-cell">
              <span class="footer-label">告警</span>
              <span class="footer-value mono" :class="{ 'status-warn': alertCount > 0 }">{{ alertCount }}</span>
            </div>
          </div>
        </div>
        <div class="footer-group" data-group="quality">
          <span class="footer-group-label">数据质量</span>
          <div class="footer-group-cells">
            <div class="footer-cell">
              <span class="footer-label">属性 OK</span>
              <span class="footer-value mono">{{ syncOkCount }}</span>
            </div>
            <div class="footer-cell" :title="`超过 ${STALE_THRESHOLD_DAYS} 天未更新`">
              <span class="footer-label">过期</span>
              <span class="footer-value mono" :class="{ 'status-warn': staleCount > 0 }">{{ staleCount }}</span>
            </div>
            <div class="footer-cell" :title="staleCount > 0 ? `⚠ ${staleCount} 个城市超过 ${STALE_THRESHOLD_DAYS} 天未更新` : ''">
              <span class="footer-label">质量</span>
              <span class="footer-value" :class="staleCount > 5 ? 'status-warn' : 'status-ok'">
                {{ staleCount > 5 ? '需关注' : (kpi.attrRate >= 90 ? '优秀' : kpi.attrRate >= 70 ? '良好' : '一般') }}
              </span>
            </div>
          </div>
        </div>
        <div class="footer-group footer-group-shrink" data-group="scale">
          <span class="footer-group-label">规模</span>
          <div class="footer-group-cells">
            <div class="footer-cell">
              <span class="footer-label">城市</span>
              <span class="footer-value mono">{{ Object.keys(data.all_cities).length }}</span>
            </div>
          </div>
        </div>
      </div>

    </template>
  </div>
</template>

<script setup>
import ErrorState from './ErrorState.vue'
import { ref, reactive, computed, onMounted, onUnmounted, onBeforeUnmount, nextTick, watch } from 'vue'
import axios from 'axios'
import SkeletonCard from './SkeletonCard.vue'
import EmptyState from './EmptyState.vue'
import GeoMapView from './GeoMapView.vue'
import { useFormatNumber } from '../composables/useFormatNumber.js'
// P0-2 订阅全局 tick,跟随 TopBar 节奏刷新
import { useGlobalPolling } from '../composables/useGlobalPolling.js'
import { useRoute } from 'vue-router'

const API = import.meta.env.VITE_API_URL || '/api'
const loading = ref(false)
const error = ref('')
const data = reactive({})
// P0-2 改用全局轮询:CockpitView 不再自己起 setInterval
const { pollingTick, pollingPaused, POLL_INTERVAL_MS } = useGlobalPolling()
const pollIntervalMin = computed(() => Math.round(POLL_INTERVAL_MS / 60000))

const clock = ref('')
const skillUpdates = ref([])   // /api/skill-updates 返回
const updatesNow = ref('')     // skill-updates 扫描时间
let clockTimer = null

// 从 URL query 读日期范围（覆盖率指标只统计 DWS 在该日期范围内的文档）
const route = useRoute()
const dateFrom = ref(String(route.query.date_from || ''))
const dateTo = ref(String(route.query.date_to || ''))

// 属性解析覆盖率计算公式明细（hover tooltip）
const attrRateFormulaDetail = computed(() => {
  const rates = Object.values(data.all_cities || {})
    .map(c => attrRate(c))
    .filter(v => !isNaN(v) && v > 0)
  if (!rates.length) return '暂无数据'
  const sum = rates.reduce((s, v) => s + v, 0)
  // 超过 10 城只取首尾，中间 “…”
  const shown = rates.length <= 10
    ? rates.map(r => r.toFixed(1)).join(' + ')
    : rates.slice(0, 5).map(r => r.toFixed(1)).join(' + ') + ' + … + ' + rates.slice(-3).map(r => r.toFixed(1)).join(' + ')
  return `(${shown}) ÷ ${rates.length} = ${kpi.value.attrRate.toFixed(1)}%\n各城 with_attr/total 求平均`
})

// 清洗完成率 / 服务覆盖率公式明细（全局聚合，与属性解析的“均值”不同）
const dwdPctFormulaDetail = computed(() => {
  const dwd = kpi.value.dwd
  const ods = kpi.value.ods
  if (!ods) return '暂无数据'
  return `Σ各城 DWD ÷ Σ各城 ODS = ${fmt.compact(dwd)} / ${fmt.compact(ods)} = ${dwdPctAll.value.toFixed(1)}%`
})
const dwsPctFormulaDetail = computed(() => {
  const dws = kpi.value.dws
  const dwd = kpi.value.dwd
  if (!dwd) return '暂无数据'
  return `Σ各城 DWS ÷ Σ各城 DWD = ${fmt.compact(dws)} / ${fmt.compact(dwd)} = ${dwsPctAll.value.toFixed(1)}%`
})

// 底栏“轮询 Xm”动态读取
const pollMinutes = computed(() => Math.round(POLL_INTERVAL_MS / 60000) + 'm')

const kpi = computed(() => {
  const cities = Object.values(data.all_cities || {})
  const ods = cities.reduce((s, c) => s + (c.ods?.count || 0), 0)
  const dwd = cities.reduce((s, c) => s + (c.dwd?.count || 0), 0)
  const dws = cities.reduce((s, c) => s + (c.dws?.count || 0), 0)
  // v0.19+ (2026-07-23): 覆盖率优先用 API 加权率(global.rate),避免空城拉低均值。
  // 退路:本地平均时过滤 total=0 的城,不要把没数据的城市算成 0。
  const globalRate = data.global_coverage?.rate
  let attrRateAvg
  if (typeof globalRate === 'number' && globalRate > 0) {
    attrRateAvg = globalRate
  } else {
    const attrRates = cities
      .filter(c => (c.coverage?.total || 0) > 0)
      .map(c => attrRate(c))
      .filter(v => !isNaN(v) && v > 0)
    attrRateAvg = attrRates.length ? attrRates.reduce((s, v) => s + v, 0) / attrRates.length : 0
  }
  const lastUpdate = cities
    .map(c => c.dwd?.last_etl || c.dws?.last_etl)
    .filter(Boolean)
    .sort()
    .reverse()[0] || ''
  return { ods, dwd, dws, attrRate: attrRateAvg, odsDelta: 0, lastUpdate: lastUpdate.slice(0, 19) }
})

// 全局转化率（不含分母为 0 的 NaN 保护）
const dwdPctAll = computed(() => kpi.value.ods > 0 ? (kpi.value.dwd / kpi.value.ods) * 100 : 0)
const dwsPctAll = computed(() => kpi.value.dwd > 0 ? (kpi.value.dws / kpi.value.dwd) * 100 : 0)

const cityCount = computed(() => Object.keys(data.all_cities || {}).length)

const syncOkCount = computed(() => {
  // 与城市卡片 alert 判断口径一致：attr 覆盖率 ≥ 80% 视为健康
  return Object.values(data.all_cities || {}).filter(c => attrRate(c) >= 80).length
})

const alertCount = computed(() => {
  return Object.values(data.all_cities || {}).filter(c => attrRate(c) < 80).length
})

// 与右下 Skill 更新记录卡片统一 7 天阈值（fix 2026-07-12）
const STALE_THRESHOLD_DAYS = 7

const staleCount = computed(() => {
  // 与 skill-updates 接口 hours_since 阈值一致
  const now = new Date()
  return Object.values(data.all_cities || {}).filter(c => {
    const lu = c.scrape?.last_updated
    if (!lu) return false
    const days = (now - new Date(lu)) / 86400000
    return days > STALE_THRESHOLD_DAYS
  }).length
})

function attrRate(pipe) {
  // 从 coverageByCity 算
  return pipe.coverage?.rate ?? 0
}

// Sparkline: 把 7 个数字归一化到 [0, 24] 高度区间，返回 polyline points
function sparklinePoints(arr) {
  if (!arr || arr.length < 2) return ''
  const max = Math.max(...arr, 1)
  const w = 80
  const h = 24
  const stepX = w / (arr.length - 1)
  return arr.map((v, i) => {
    const x = (i * stepX).toFixed(1)
    const y = (h - (v / max) * (h - 2) - 1).toFixed(1)
    return `${x},${y}`
  }).join(' ')
}
function sparklineArea(arr) {
  const linePts = sparklinePoints(arr)
  if (!linePts) return ''
  return `0,24 ${linePts} 80,24`
}
function sparklineTrend(arr) {
  if (!arr || arr.length < 2) return '—'
  const prev = arr.slice(0, -1).reduce((s, v) => s + v, 0)
  const last = arr[arr.length - 1]
  if (prev === 0 && last === 0) return '— 平稳'
  if (prev === 0) return '↑ 新增'
  const diff = last - (prev / (arr.length - 1))
  if (Math.abs(diff) < (prev / (arr.length - 1)) * 0.05) return '→ 平稳'
  return diff > 0 ? `↑ ${fmt.int(Math.round(diff))}` : `↓ ${fmt.int(Math.round(-diff))}`
}
function sparklineTrendCls(arr) {
  if (!arr || arr.length < 2) return ''
  const prev = arr.slice(0, -1).reduce((s, v) => s + v, 0)
  const last = arr[arr.length - 1]
  if (prev === 0 && last === 0) return 'trend-flat'
  if (prev === 0) return 'trend-up'
  const diff = last - (prev / (arr.length - 1))
  if (Math.abs(diff) < (prev / (arr.length - 1)) * 0.05) return 'trend-flat'
  return diff > 0 ? 'trend-up' : 'trend-down'
}

// D.2026-07-12 统一使用 useFormatNumber
const fmt = useFormatNumber()

// 紧凑 sparkline：60×16 视图
function sparklinePointsCompact(arr) {
  if (!arr || arr.length < 2) return ''
  const max = Math.max(...arr, 1)
  const w = 60
  const h = 16
  const stepX = w / (arr.length - 1)
  return arr.map((v, i) => {
    const x = (i * stepX).toFixed(1)
    const y = (h - (v / max) * (h - 2) - 1).toFixed(1)
    return `${x},${y}`
  }).join(' ')
}

// 紧凑趋势：↑ 1.2k / ↓ 500
function sparklineTrendShort(arr) {
  if (!arr || arr.length < 2) return '—'
  const prev = arr.slice(0, -1).reduce((s, v) => s + v, 0)
  const last = arr[arr.length - 1]
  if (prev === 0 && last === 0) return '→'
  if (prev === 0) return '↑'
  const avg = prev / (arr.length - 1)
  const diff = last - avg
  if (Math.abs(diff) < avg * 0.05) return '→'
  return diff > 0 ? `↑${fmt.compact(Math.round(diff))}` : `↓${fmt.compact(Math.round(-diff))}`
}

function dwdPct(pipe) {
  const ods = pipe.ods?.count || 0
  const dwd = pipe.dwd?.count || 0
  return ods > 0 ? (dwd / ods * 100) : 0
}

function dwsPct(pipe) {
  const dwd = pipe.dwd?.count || 0
  const dws = pipe.dws?.count || 0
  return dwd > 0 ? (dws / dwd * 100) : 0
}

async function loadData() {
  loading.value = true
  error.value = ''
  try {
    const r = await axios.get(`${API}/stats/provenance`)
    Object.assign(data, r.data || {})
    // 补每个城市的 attr 覆盖率（fix 2026-07-12：聚合端点一次拉全）
    const cities = Object.keys(data.all_cities || {})
    try {
      const allRes = await axios.get(`${API}/stats/spec-quality-all`, {
        params: {
          cities: cities.join(','),
          ...(dateFrom.value && { date_from: dateFrom.value }),
          ...(dateTo.value && { date_to: dateTo.value }),
        },
      })
      const sq = allRes.data || {}
      const citiesData = sq.cities || {}
      for (const city of cities) {
        const c = citiesData[city] || {}
        if (data.all_cities[city]) {
          data.all_cities[city].coverage = {
            rate: c.rate || 0,
            with_attr: c.with_attr || 0,
            total: c.total || 0,
          }
        }
      }
      // 全局 attr_source 分布（供 Cockpit 第 4 仪表展示）
      data.attr_source_breakdown = sq.global?.attr_source_breakdown || []
      data.global_coverage = {
        rate: sq.global?.rate || 0,
        with_attr: sq.global?.with_attr || 0,
        total: sq.global?.total || 0,
      }
    } catch (e) {
      console.warn('spec-quality-all 失败:', e?.message)
    }
    // 并行拉 skill-updates（不阻塞主流程）
    axios.get(`${API}/skill-updates`).then(su => {
      skillUpdates.value = su.data?.updates || []
      updatesNow.value = (su.data?.now || '').replace('T', ' ').slice(0, 19)
    }).catch(() => {
      // 静默失败
    })
  } catch (e) {
    error.value = '加载失败：' + (e.message || '网络错误')
  } finally {
    loading.value = false
  }
}

function hoursAgo(h) {
  if (h == null) return '—'
  if (h < 1) return `${Math.round(h * 60)}m ago`
  if (h < 24) return `${h.toFixed(1)}h ago`
  const d = h / 24
  if (d < 30) return `${d.toFixed(1)}d ago`
  return `${Math.round(d)}d ago`
}

function formatUpdateTime(t) {
  if (!t) return '—'
  // 处理 'YYYY-MM-DD HH:MM:SS' 和 'YYYY-MM-DDTHH:MM:SS' 两种
  return t.replace('T', ' ').slice(0, 19)
}

function updateClock() {
  const d = new Date()
  const pad = n => String(n).padStart(2, '0')
  clock.value = `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
}

// P0-2 跟随全局 tick 刷新;bumpTick() 时也会触发
watch(pollingTick, () => {
  if (!loading.value) loadData()
})

onMounted(() => {
  loadData()
  updateClock()
  clockTimer = setInterval(updateClock, 1000)
  // P0-2: 不再本地 startPolling,跟随全局 tick
})

onUnmounted(() => {
  if (clockTimer) clearInterval(clockTimer)
})
</script>

<style scoped>
/* 2026-07-28 Phase 2 cleanup:
   入库总量 hero-stat 迁 <el-card>+<el-statistic>(保留 3 个 SVG 圆环 - 自研太精致)。
   已删除: .hud-btn(下沉 TopBar) / .gauge-card-main / .hero-stat / .hero-num / 
            .tag-green / .pipeline-section / .pipeline-grid / .city-card* / .city-name /
            .city-status / .city-pipe / .city-stage / .city-arrow / .stage-num / .stage-bar / 
            .stage-bar-fill / .city-attr / .mini-ring / .mini-track / .mini-fill / .city-attr-info /
            .city-attr-num / .city-attr-unit / .city-sparkline-wrap / .city-sparkline / 
            .city-sparkline-trend / .city-sparkline-empty / .grid-geo .geo-map-view / 
            .city-table / .city-thead / .city-tbody / .city-tr / .city-td-* / .city-dot / 
            .attr-track / .attr-fill / .attr-pct / .city-spark-empty / .spark-trend /
            移动端内 .hero-num / h1/h2/h3 / button 兜底 等。 */

/* ── 页面容器 ── */
.cockpit {
  padding: 16px 20px;
}

/* ── 通用 ── */
.mono { font-family: var(--font-mono-num); }

/* ── 顶部标题栏 ── */
.hud-header {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 12px 20px;
  margin-bottom: 20px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  box-shadow: var(--shadow-sm);
}
.hud-prefix {
  color: var(--text);
  font-size: 15px;
  font-weight: 700;
}
.hud-prefix-sub {
  color: var(--text-3);
  font-size: 12px;
  font-weight: 400;
  margin-left: 6px;
}
.hud-status { display: flex; align-items: center; gap: 12px; }
.hud-clock {
  color: var(--primary);
  font-size: 18px;
  font-weight: 600;
  letter-spacing: 0.5px;
  font-family: var(--font-mono-num);
}
.hud-live {
  font-size: 11px;
  font-weight: 600;
  animation: pulse 1.5s ease-in-out infinite;
}
.hud-live.active { color: var(--success); }
.hud-live.active::before { content: '● '; }
.hud-live.paused { color: var(--warning-orange, #ea580c); animation: none; }
.hud-live:not(.active):not(.paused) { color: var(--text-3); animation: none; }
@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.5; }
}

/* ── 加载 / 错误 ── */
.cockpit-loading { padding: 60px; }

/* ── 4 个仪表 ── */
.gauge-row {
  display: grid;
  grid-template-columns: 4fr 2.67fr 2.67fr 2.67fr;
  gap: 12px;
  margin-bottom: 14px;
  align-items: stretch;
}
.gauge-card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 18px 18px;
  box-shadow: var(--shadow-card);
  transition: transform var(--transition), box-shadow var(--transition);
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
}
.gauge-card:hover {
  transform: translateY(-2px);
  box-shadow: 0 6px 20px rgba(15,23,42,0.08), 0 2px 8px rgba(15,23,42,0.04);
}

/* ── Hero stat card (第一个仪表,内嵌 el-statistic) ── */
.gauge-card-hero {
  display: flex;
  flex-direction: column;
  align-items: center;
  text-align: center;
}
.hero-unit {
  font-size: 14px;
  color: var(--text-3);
  font-weight: 500;
}
.hero-meta {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 12px 0 0;
  border-top: 1px solid var(--border-light);
}
.hero-meta-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 12px;
}
.hero-meta-label {
  color: var(--text-3);
  font-weight: 500;
}
.hero-meta-value {
  color: var(--text);
  font-weight: 600;
  font-family: var(--font-mono-num);
}
.cockpit-hero-stat {}

/* ── 3 个 SVG 圆环(保留,自研太精致) ── */
.gauge-label {
  color: var(--text);
  font-size: 12px;
  font-weight: 600;
  text-align: center;
  margin-bottom: 2px;
}
.gauge-sub {
  color: var(--text-3);
  font-size: 11px;
  text-align: center;
  margin-bottom: 6px;
}
.gauge-svg {
  width: 100%;
  height: auto;
  max-width: 210px;
  margin: 0 auto;
  display: block;
}
.gauge-track {
  fill: none;
  stroke: var(--surface-2);
  stroke-width: 8;
}
.gauge-fill {
  fill: none;
  stroke: var(--primary);
  stroke-width: 8;
  stroke-linecap: round;
  transition: stroke-dasharray 0.6s ease;
}
.gauge-num {
  fill: var(--text);
  font-size: 30px;
  font-weight: 700;
  text-anchor: middle;
}
.gauge-num-big { font-size: 42px; }
.gauge-unit {
  fill: var(--text-3);
  font-size: 11px;
  text-anchor: middle;
  font-family: var(--font-mono-num);
}
.gauge-foot {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-top: 8px;
  font-size: 11px;
}
.gauge-tag {
  padding: 2px 8px;
  border-radius: var(--radius-round);
  font-size: 11px;
  font-weight: 500;
  background: rgba(var(--primary-rgb), 0.06);
  color: var(--primary);
}
.tag-blue { background: rgba(var(--primary-rgb), 0.08); color: var(--primary); }
.gauge-trend {
  color: var(--text-3);
  font-family: var(--font-mono-num);
  font-size: 10px;
}

/* 属性解析覆盖率计算说明(hover 看明细) */
.gauge-formula {
  font-size: 10px;
  color: var(--text-3);
  margin-top: 6px;
  text-align: center;
  font-family: var(--font-mono-num);
  cursor: help;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 100%;
}

/* ── Skill 更新记录区 ── */
.skill-updates-section {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 16px 20px;
  margin-bottom: 16px;
  box-shadow: var(--shadow-card);
}
.section-title {
  color: var(--text);
  font-size: 13px;
  font-weight: 700;
  margin-bottom: 16px;
  display: flex;
  align-items: center;
  gap: 8px;
}
.section-icon { font-size: 15px; }
.section-sub {
  font-size: 11px;
  font-weight: 400;
  color: var(--text-3);
  margin-left: 4px;
}
.section-dot {
  width: 6px;
  height: 6px;
  background: var(--primary);
  border-radius: 50%;
  flex-shrink: 0;
}
/* 第二个 .section-sub 定义:右侧带时间戳(扫描时间)的版本,margin-left:auto */
.section-sub {
  color: var(--text-3);
  font-size: 10px;
  margin-left: auto;
  font-weight: 400;
}
.skill-updates-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 8px;
}
.skill-update-card {
  background: var(--surface);
  border: 1px solid var(--border-light);
  border-radius: var(--radius-sm);
  padding: 8px 10px;
  transition: all var(--transition-fast);
}
.skill-update-card:hover { border-color: var(--border-strong); box-shadow: var(--shadow-sm); }
.skill-update-card.status-fresh { border-left: 3px solid var(--success); }
.skill-update-card.status-stale { border-left: 3px solid var(--warning); }
.skill-update-card.status-very_stale { border-left: 3px solid var(--danger); }
.skill-update-card.status-no_data { border-left: 3px solid var(--text-3); opacity: 0.6; }

.update-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 6px;
}
.update-city {
  color: var(--text);
  font-size: 14px;
  font-weight: 700;
}
.update-status {
  font-size: 10px;
  font-weight: 600;
  padding: 2px 6px;
  border-radius: var(--radius-round);
}
.update-status.fresh { background: var(--status-ok-bg); color: var(--status-ok); }
.update-status.stale { background: var(--status-warn-bg); color: var(--status-warn); }
.update-status.very_stale { background: var(--status-alert-bg); color: var(--status-alert); }
.update-status.no_data { background: var(--status-muted-bg); color: var(--status-muted); }

/* ── SKILL 卡片 body ── */
.update-body { display: flex; flex-direction: column; gap: 2px; }
.update-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 10px;
}
.update-label { color: var(--text-3); }
.update-value { color: var(--text); font-weight: 600; }
.badge-incremental {
  background: var(--status-ok-bg);
  color: var(--status-ok);
  padding: 2px 6px;
  border-radius: var(--radius-sm);
  font-size: 10px;
  font-weight: 600;
}

/* ── 底部状态条(P0-1 拆组:运行 / 数据质量 / 规模) ── */
.hud-footer {
  display: flex;
  gap: 0;
  background: var(--border);
  border-radius: var(--radius-sm);
  overflow: hidden;
}
.footer-group {
  flex: 1;
  background: var(--surface);
  display: flex;
  align-items: stretch;
  position: relative;
}
.footer-group + .footer-group {
  border-left: 1px solid var(--border);
}
.footer-group-label {
  display: flex;
  align-items: center;
  padding: 8px 6px;
  font-size: 9px;
  font-weight: 700;
  color: var(--text-3);
  letter-spacing: 0.4px;
  text-transform: uppercase;
  writing-mode: vertical-rl;
  text-orientation: mixed;
  border-right: 1px solid var(--border-light);
  background: var(--surface-2);
  flex-shrink: 0;
  user-select: none;
}
/* 窄屏改横排 label,避免挤压 */
@media (max-width: 900px) {
  .footer-group-label {
    writing-mode: horizontal-tb;
    text-orientation: mixed;
    border-right: none;
    border-bottom: 1px solid var(--border-light);
    padding: 6px 10px;
    flex: 0 0 auto;
  }
  .footer-group-cells { flex: 1; }
}
.footer-group-cells {
  flex: 1;
  display: flex;
  gap: 1px;
  background: var(--border-light);
}
.footer-group-shrink { flex: 0 0 auto; }
.footer-cell {
  flex: 1;
  background: var(--surface);
  padding: 8px 12px;
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 56px;
}
.footer-label {
  color: var(--text-3);
  font-size: 9px;
  font-weight: 600;
}
.footer-value {
  color: var(--text);
  font-size: 13px;
  font-weight: 700;
}
.footer-value.status-ok { color: var(--success); }
.footer-value.status-warn { color: var(--warning); }

/* ── 12 栅格网格矩阵 ── */
.grid-row {
  display: grid;
  grid-template-columns: repeat(12, 1fr);
  gap: 8px;
  margin-bottom: 14px;
}
.grid-cell {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 12px 14px;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.grid-row-main {
  align-items: stretch;
}
.grid-row-skill {
  display: block;
  padding: 14px 16px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  margin-bottom: 14px;
}
.grid-row-footer {
  display: flex;
  gap: 1px;
  background: var(--border);
  border-radius: var(--radius-sm);
  padding: 0;
  border: none;
  margin-bottom: 0;
  overflow: hidden;
  position: sticky;
  bottom: 0;
  z-index: 10;
  box-shadow: 0 -4px 12px rgba(15, 23, 42, 0.04);
}

/* 地图满宽(8/4 横排改为满宽 12 列) */
.grid-geo {
  grid-column: span 12;
  aspect-ratio: 1.85 / 1;
  min-height: 0;
}

/* ── 响应式 ──
   1100px 是平板断点(侧栏已折叠为图标列 64px),4 列仪表降至 2x2 */
@media (max-width: 1100px) {
  .gauge-row { grid-template-columns: repeat(2, 1fr); }
  .grid-row-main {
    grid-template-columns: 1fr;
    grid-template-rows: auto auto;
  }
  .grid-geo {
    grid-column: span 1;
    aspect-ratio: auto;
    min-height: 420px;
  }
}

/* ── 移动端适配 v2 (2026-07-25 P0-fix): 等比例缩小 + 单列 + 紧凑 ── */
@media (max-width: 768px) {
  /* gauge-row 1 列 */
  .gauge-row { grid-template-columns: 1fr; gap: 10px; }
  .gauge-card { padding: 14px 12px; }
  .hero-unit { font-size: 12px; }
  .hero-meta-row { font-size: 13px; }
  /* hud 头部改竖排 */
  .hud-header { flex-direction: column; align-items: flex-start; gap: 8px; padding: 10px 12px; }
  .hud-status { width: 100%; justify-content: space-between; }
  .hud-prefix { font-size: 14px; }
  .hud-prefix-sub { font-size: 11px; }
  .hud-clock { font-size: 13px; }
  .hud-live { font-size: 12px; }
  /* 整页级:紧凑 */
  .cockpit { padding: 0 !important; }
  /* 视觉降级:radial 大块/背景简化,避免移动 GPU 占用 */
  .gauge-svg { width: 140px; height: 140px; }
}
</style>
