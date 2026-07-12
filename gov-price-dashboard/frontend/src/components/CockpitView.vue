<template>
  <div class="cockpit">
    <!-- 顶部 HUD 标题栏 -->
    <div class="hud-header">
      <div class="hud-title">
        <span class="hud-prefix">数据驾驶舱 · 自动每 15 分钟更新</span>
      </div>
      <div class="hud-status">
        <span class="hud-clock mono">{{ clock }}</span>
        <span class="hud-live" :class="{ active: pollingActive }">● 运行中</span>
        <button class="hud-btn" @click="manualRefresh" :disabled="loading" title="立即拉取最新数据">
          {{ loading ? '⟳ 加载中' : '↻ 立即刷新' }}
        </button>
        <button class="hud-btn" @click="togglePolling">
          {{ pollingActive ? '⏸ 暂停' : '▶ 继续' }}
        </button>
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
        <!-- 入库总量：大字 hero，4 列宽 -->
        <div class="gauge-card gauge-card-hero">
          <div class="gauge-label">入库总量</div>
          <div class="gauge-sub">ODS 原始数据量</div>
          <div class="hero-stat">
            <span class="hero-num mono">{{ fmt.int(kpi.ods) }}</span>
            <span class="hero-unit">条</span>
          </div>
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
        </div>

        <div class="gauge-card">
          <div class="gauge-label">清洗完成率</div>
          <div class="gauge-sub">DWD / ODS</div>
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
        </div>

        <div class="gauge-card">
          <div class="gauge-label">服务覆盖率</div>
          <div class="gauge-sub">DWS / DWD</div>
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
        </div>

        <div class="gauge-card">
          <div class="gauge-label">属性解析覆盖率</div>
          <div class="gauge-sub">数据质量</div>
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
        </div>
      </div>

      <!-- ============ Row 2: 12 栅格 — 地图 8 + 管道 4（地图突出，加高） ============ -->
      <div class="grid-row grid-row-main">
        <!-- 地理分布 8 列，加高到 660 -->
        <section class="grid-cell grid-geo">
          <div class="section-title">
            <span class="section-icon">🗺️</span>
            地理分布
            <span class="section-sub">按地区聚合材料价格 · 点击下钻</span>
          </div>
          <GeoMapView :hide-header="true" />
        </section>
        <!-- 数据处理管道 4 列 -->
        <section class="grid-cell grid-pipe">
          <div class="section-title">
            <span class="section-dot"></span>
            数据处理管道 · {{ cityCount }} 城
            <span class="section-sub">最后更新 {{ kpi.lastUpdate || '—' }}</span>
          </div>
          <div class="city-table">
            <div class="city-thead">
              <div class="city-th city-th-name">城市</div>
              <div class="city-th city-th-data">ODS › DWD › DWS</div>
              <div class="city-th city-th-attr">属性</div>
              <div class="city-th city-th-spark">7 日趋势</div>
            </div>
            <div class="city-tbody">
              <div v-for="(pipe, key) in data.all_cities" :key="key" class="city-tr">
                <div class="city-td city-td-name">
                  <span class="city-dot" :class="attrRate(pipe) >= 80 ? 'ok' : 'warn'"></span>
                  <span class="city-name">{{ pipe.city_label }}</span>
                </div>
                <div class="city-td city-td-data">
                  <span class="stage-num mono" :title="fmt.int(pipe.ods?.count || 0) + ' 条 (精确值)'">{{ fmt.compact(pipe.ods?.count) }}</span>
                  <span class="arrow">›</span>
                  <span class="stage-num mono" :title="fmt.int(pipe.dwd?.count || 0) + ' 条 (精确值)'">{{ fmt.compact(pipe.dwd?.count) }}</span>
                  <span class="arrow">›</span>
                  <span class="stage-num mono" :title="fmt.int(pipe.dws?.count || 0) + ' 条 (精确值)'">{{ fmt.compact(pipe.dws?.count) }}</span>
                </div>
                <div class="city-td city-td-attr">
                  <div class="attr-track">
                    <div class="attr-fill" :style="{ width: attrRate(pipe) + '%' }"></div>
                  </div>
                  <span class="attr-pct mono">{{ fmt.pct(attrRate(pipe)) }}</span>
                </div>
                <div class="city-td city-td-spark">
                  <svg v-if="pipe.sparkline_7d && pipe.sparkline_7d.length"
                       class="city-sparkline" viewBox="0 0 60 16" preserveAspectRatio="none">
                    <polyline
                      :points="sparklinePointsCompact(pipe.sparkline_7d)"
                      fill="none"
                      stroke="currentColor"
                      stroke-width="1.2"
                      stroke-linejoin="round"
                    />
                  </svg>
                  <span v-else class="city-spark-empty">—</span>
                  <span v-if="pipe.sparkline_7d && pipe.sparkline_7d.length"
                        class="spark-trend" :class="sparklineTrendCls(pipe.sparkline_7d)">
                    {{ sparklineTrendShort(pipe.sparkline_7d) }}
                  </span>
                </div>
              </div>
            </div>
          </div>
        </section>
      </div>

      <!-- ============ Row 3: Skill 更新记录（12 列） ============ -->

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

      <!-- ============ Row 4: 底部状态条 ============ -->
      <div class="hud-footer grid-row grid-row-footer">
        <div class="footer-cell">
          <span class="footer-label">系统</span>
          <span class="footer-value status-ok">✓ 正常</span>
        </div>
        <div class="footer-cell">
          <span class="footer-label">轮询</span>
          <span class="footer-value mono">{{ pollMinutes }}</span>
        </div>
        <div class="footer-cell">
          <span class="footer-label">城市</span>
          <span class="footer-value mono">{{ Object.keys(data.all_cities).length }}</span>
        </div>
        <div class="footer-cell">
          <span class="footer-label">属性 OK</span>
          <span class="footer-value mono">{{ syncOkCount }}</span>
        </div>
        <div class="footer-cell" :title="`超过 ${STALE_THRESHOLD_DAYS} 天未更新`">
          <span class="footer-label">过期</span>
          <span class="footer-value mono" :class="{ 'status-warn': staleCount > 0 }">{{ staleCount }}</span>
        </div>
        <div class="footer-cell">
          <span class="footer-label">告警</span>
          <span class="footer-value mono" :class="{ 'status-warn': alertCount > 0 }">{{ alertCount }}</span>
        </div>
        <div class="footer-cell" :title="staleCount > 0 ? `⚠ ${staleCount} 个城市超过 ${STALE_THRESHOLD_DAYS} 天未更新` : ''">
          <span class="footer-label">数据质量</span>
          <span class="footer-value" :class="staleCount > 5 ? 'status-warn' : 'status-ok'">
            ● {{ staleCount > 5 ? '需关注' : (kpi.attrRate >= 90 ? '优秀' : kpi.attrRate >= 70 ? 'GOOD' : 'FAIR') }}
          </span>
        </div>
      </div>

    </template>
  </div>
</template>

<script setup>
import ErrorState from './ErrorState.vue'
import { ref, reactive, computed, onMounted, onUnmounted, nextTick } from 'vue'
import axios from 'axios'
import SkeletonCard from './SkeletonCard.vue'
import EmptyState from './EmptyState.vue'
import GeoMapView from './GeoMapView.vue'
import { useFormatNumber } from '../composables/useFormatNumber.js'

const API = import.meta.env.VITE_API_URL || '/api'
const loading = ref(false)
const error = ref('')
const data = reactive({})
const pollingActive = ref(true)
const clock = ref('')
const skillUpdates = ref([])   // /api/skill-updates 返回
const updatesNow = ref('')     // skill-updates 扫描时间
let pollTimer = null
let clockTimer = null

const 轮询_INTERVAL_MS = 15 * 60 * 1000  // 15 分钟（与城市检测 cron 节拍对齐）

// 底栏"轮询 Xm"动态读取,避免硬编码失同步（fix 2026-07-12 P3-batch1）
const pollMinutes = computed(() => Math.round(轮询_INTERVAL_MS / 60000) + 'm')

const kpi = computed(() => {
  const cities = Object.values(data.all_cities || {})
  const ods = cities.reduce((s, c) => s + (c.ods?.count || 0), 0)
  const dwd = cities.reduce((s, c) => s + (c.dwd?.count || 0), 0)
  const dws = cities.reduce((s, c) => s + (c.dws?.count || 0), 0)
  const attrRates = cities.map(c => attrRate(c)).filter(v => !isNaN(v))
  const attrRateAvg = attrRates.length ? attrRates.reduce((s, v) => s + v, 0) / attrRates.length : 0
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
      const allRes = await axios.get(`${API}/stats/spec-quality-all`, { params: { cities: cities.join(',') } })
      const citiesData = allRes.data?.cities || {}
      for (const city of cities) {
        const sq = citiesData[city] || {}
        if (data.all_cities[city]) {
          data.all_cities[city].coverage = {
            rate: sq.rate || 0,
            with_attr: sq.with_attr || 0,
            total: sq.total || 0,
          }
        }
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

function togglePolling() {
  pollingActive.value = !pollingActive.value
  if (pollingActive.value) {
    startPolling()
  } else {
    stopPolling()
  }
}

function manualRefresh() {
  if (loading.value) return
  loadData()
}

function startPolling() {
  stopPolling()
  pollTimer = setInterval(loadData, 轮询_INTERVAL_MS)
}

function stopPolling() {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

onMounted(() => {
  loadData()
  updateClock()
  clockTimer = setInterval(updateClock, 1000)
  startPolling()
})

onUnmounted(() => {
  stopPolling()
  if (clockTimer) clearInterval(clockTimer)
})
</script>

<style scoped>
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
.hud-live:not(.active) { color: var(--text-3); animation: none; }
@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.5; }
}
.hud-btn {
  background: var(--surface);
  border: 1px solid var(--border);
  color: var(--text-2);
  padding: 5px 12px;
  border-radius: var(--radius-sm);
  font-size: 12px;
  cursor: pointer;
  transition: all var(--transition-fast);
  font-family: inherit;
}
.hud-btn:hover {
  background: rgba(var(--primary-rgb), 0.06);
  color: var(--primary);
  border-color: rgba(var(--primary-rgb), 0.25);
}
.hud-btn:disabled { opacity: 0.4; cursor: not-allowed; }

/* ── 加载 / 错误 ── */
.cockpit-loading { padding: 60px; }

/* ── 4 个圆形仪表 ── */
.gauge-row {
  display: grid;
  grid-template-columns: 4fr 2.67fr 2.67fr 2.67fr;
  gap: 12px;
  margin-bottom: 14px;
  align-items: stretch;  /* 4 卡等高：stretch 到行内最高卡 */
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
  justify-content: center;  /* 垂直居中让内容 */
}
.gauge-card:hover {
  transform: translateY(-2px);
  box-shadow: 0 6px 20px rgba(15,23,42,0.08), 0 2px 8px rgba(15,23,42,0.04);
}
.gauge-card-main {
  border-color: rgba(var(--primary-rgb), 0.2);
}

/* ── Hero stat card (first gauge) ── */
.gauge-card-hero {
  display: flex;
  flex-direction: column;
  align-items: center;
  text-align: center;
}
.hero-stat {
  text-align: center;
  padding: 12px 0 8px;
  display: flex;
  align-items: baseline;
  justify-content: center;
  gap: 6px;
}
.hero-num {
  font-size: 44px;
  font-weight: 800;
  color: var(--text);
  font-family: var(--font-mono-num);
  line-height: 1.1;
  letter-spacing: -1px;
}
.hero-unit {
  font-size: 14px;
  color: var(--text-3);
  font-weight: 500;
}
.hero-meta {
  width: 100%;
  text-align: left;
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
  stroke-width: 8;
  stroke-linecap: round;
  transition: stroke-dasharray 0.6s ease;
}
.gauge-fill { stroke: var(--primary); }
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
.tag-green { background: rgba(var(--success-rgb), 0.1); color: var(--success); }
.gauge-trend {
  color: var(--text-3);
  font-family: var(--font-mono-num);
  font-size: 10px;
}

/* ── 管道区 ── */
.pipeline-section,
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
.section-icon {
  font-size: 15px;
}
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
.section-sub {
  color: var(--text-3);
  font-size: 10px;
  margin-left: auto;
  font-weight: 400;
}
.pipeline-grid,
.skill-updates-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 8px;
}
.city-card,
.skill-update-card {
  background: var(--surface);
  border: 1px solid var(--border-light);
  border-radius: var(--radius-sm);
  padding: 8px 10px;
  transition: all var(--transition-fast);
}
.city-card:hover {
  border-color: var(--border-strong);
  box-shadow: var(--shadow-sm);
  transform: translateY(-2px);
}
.skill-update-card:hover { border-color: var(--border-strong); box-shadow: var(--shadow-sm); }
.city-card.alert {
  border-top-color: var(--danger);
  border-color: rgba(var(--danger-rgb), 0.4);
}
.skill-update-card.status-fresh { border-left: 3px solid var(--success); }
.skill-update-card.status-stale { border-left: 3px solid var(--warning); }
.skill-update-card.status-very_stale { border-left: 3px solid var(--danger); }
.skill-update-card.status-no_data { border-left: 3px solid var(--text-3); opacity: 0.6; }

.city-header,
.update-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 6px;
}
.city-name,
.update-city {
  color: var(--text);
  font-size: 14px;
  font-weight: 700;
}
.city-status,
.update-status {
  font-size: 10px;
  font-weight: 600;
  padding: 2px 6px;
  border-radius: var(--radius-round);
}
.city-status.ok,
.update-status.fresh { background: var(--status-ok-bg); color: var(--status-ok); }
.city-status.warn,
.update-status.stale { background: var(--status-warn-bg); color: var(--status-warn); }
.update-status.very_stale { background: var(--status-alert-bg); color: var(--status-alert); }
.update-status.no_data { background: var(--status-muted-bg); color: var(--status-muted); }

.city-pipe {
  display: flex;
  align-items: center;
  gap: 4px;
  margin-bottom: 10px;
}
.city-stage { flex: 1; min-width: 0; }
.city-arrow { flex-shrink: 0; color: var(--text-3); }
.stage-num {
  color: var(--text);
  font-size: 14px;
  font-weight: 700;
  font-family: var(--font-mono-num);
  font-variant-numeric: tabular-nums;
  margin-bottom: 4px;
}
.stage-bar {
  height: 3px;
  background: var(--surface-2);
  border-radius: 2px;
  overflow: hidden;
}
.stage-bar-fill {
  height: 100%;
  background: var(--primary);
  transition: width 0.5s;
}

.city-attr {
  display: flex;
  align-items: center;
  gap: 8px;
  padding-top: 8px;
  border-top: 1px solid var(--border-light);
}
.mini-ring { width: 28px; height: 28px; flex-shrink: 0; }
.mini-track { fill: none; stroke: var(--surface-2); stroke-width: 3; }
.mini-fill {
  fill: none;
  stroke: var(--primary);
  stroke-width: 3;
  stroke-linecap: round;
  transform: rotate(-90deg);
  transform-origin: 18px 18px;
  transition: stroke-dasharray 0.6s;
}
.city-attr-info { display: flex; align-items: baseline; gap: 4px; }
.city-attr-num { color: var(--primary); font-size: 15px; font-weight: 700; }
.city-attr-unit { color: var(--text-3); font-size: 10px; }

.city-sparkline-wrap {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 2px;
  margin-left: auto;
  min-width: 80px;
}
.city-sparkline {
  width: 80px;
  height: 24px;
  color: var(--primary);
  display: block;
}
.city-sparkline-trend {
  font-size: 10px;
  font-family: var(--font-mono-num);
  font-weight: 600;
}
.city-sparkline-trend.trend-up   { color: var(--success); }
.city-sparkline-trend.trend-down { color: var(--danger); }
.city-sparkline-trend.trend-flat { color: var(--text-3); }
.city-sparkline-empty {
  margin-left: auto;
  color: var(--text-3);
  font-size: 12px;
  font-family: var(--font-mono-num);
  align-self: center;
}

/* ── 底部状态条 ── */
.hud-footer {
  display: flex;
  gap: 1px;
  background: var(--border);
  border-radius: var(--radius-sm);
  overflow: hidden;
}
.footer-cell {
  flex: 1;
  background: var(--surface);
  padding: 8px 12px;
  display: flex;
  flex-direction: column;
  gap: 2px;
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
.grid-row-main { align-items: stretch; }
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

/* 地图 8 列 + 管道 4 列：地图容器比例 1.23:1 匹配地图本体，无留白 */
.grid-geo {
  grid-column: span 8;
  aspect-ratio: 1.23 / 1;
  align-self: start;  /* 不 stretch，让 aspect-ratio 决定高度 */
}
.grid-pipe {
  grid-column: span 4;
  height: 100%;  /* 跟 grid-row 高度一致（=地图高度） */
  align-self: stretch;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}
.grid-pipe .city-table {
  flex: 1;
  min-height: 0;
}
.grid-pipe .city-tbody {
  overflow-y: auto;
}
.grid-geo .geo-map-view {
  flex: 1;
  min-height: 0;
}

/* 紧凑城市表格（4 列：城市 / 数据 / 属性 / 7d） — 跟随地图的克制蓝调风格 */
.city-table {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.city-thead {
  display: grid;
  grid-template-columns: minmax(70px, 1.1fr) 1.4fr 1.1fr 1.2fr;
  gap: 8px;
  padding: 7px 12px;
  font-size: 10px;
  font-weight: 600;
  color: var(--text-3);
  letter-spacing: 0.5px;
  text-transform: uppercase;
  border-bottom: 1px solid var(--border);
  background: transparent;
  flex-shrink: 0;
}
.city-tbody {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
}
.city-tr {
  flex: 0 0 auto;
  min-height: 36px;
  display: grid;
  grid-template-columns: minmax(70px, 1.1fr) 1.4fr 1.1fr 1.2fr;
  gap: 8px;
  align-items: center;
  padding: 6px 12px;
  border-bottom: 1px solid var(--border-light);
  transition: background var(--transition-fast);
}
.city-tr:last-child { border-bottom: none; }
.city-tr:hover { background: var(--surface-2); }

.city-td-name {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
  overflow: visible;
}
.city-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  flex-shrink: 0;
}
.city-dot.ok { background: var(--primary); }
.city-dot.warn { background: var(--warning); }
.city-td-name .city-name {
  font-size: 12px;
  font-weight: 600;
  color: var(--text);
  white-space: nowrap;
  flex-shrink: 0;
  letter-spacing: -0.2px;
}

.city-td-data {
  display: flex;
  align-items: center;
  gap: 5px;
  font-family: var(--font-mono-num);
  white-space: nowrap;
}
.city-td-data .stage-num {
  font-weight: 700;
  color: var(--text);
  font-size: 12px;
  letter-spacing: -0.2px;
}
.city-td-data .arrow {
  color: var(--text-3);
  font-size: 11px;
}

.city-td-attr {
  display: flex;
  align-items: center;
  gap: 6px;
}
.attr-track {
  flex: 1;
  height: 4px;
  background: var(--surface-2);
  border-radius: 2px;
  overflow: hidden;
}
.attr-fill {
  height: 100%;
  background: linear-gradient(to right, #93c5fd, var(--primary));
  border-radius: 2px;
  transition: width 0.3s;
}
.attr-pct {
  font-size: 11px;
  color: var(--text-2);
  font-weight: 600;
  min-width: 36px;
  text-align: right;
}

.city-td-spark {
  display: flex;
  align-items: center;
  gap: 4px;
  color: var(--primary);
  min-width: 0;
  overflow: hidden;
  white-space: nowrap;
}
.city-td-spark .city-sparkline {
  width: 40px;
  height: 14px;
  flex-shrink: 0;
  color: var(--primary);
  opacity: 0.7;
}
.city-td-spark .city-spark-empty {
  color: var(--text-3);
  font-size: 11px;
  width: 44px;
}
.city-td-spark .spark-trend {
  font-size: 10px;
  font-weight: 600;
  color: var(--text-2);
  font-family: var(--font-mono-num);
  min-width: 32px;
}

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

/* ── 响应式 ──
   1100px 是平板断点（侧栏已折叠为图标列 64px），4 列仪表降至 2x2 */
@media (max-width: 1100px) {
  .gauge-row { grid-template-columns: repeat(2, 1fr); }
  /* 地图 + 管道在平板竖排，避免 8/4 横排太挤 */
  .grid-row-main {
    grid-template-columns: 1fr;
    grid-template-rows: auto auto;
  }
  .grid-geo {
    grid-column: span 1;
    aspect-ratio: auto;
    min-height: 420px;
  }
  .grid-pipe {
    grid-column: span 1;
    height: auto;
    max-height: 480px;
  }
}
</style>
