<template>
  <div class="cockpit">
    <!-- 顶部 HUD 标题栏 -->
    <div class="hud-header">
      <div class="hud-title">
        <span class="hud-prefix">驾驶舱 · 实时监控</span>
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
      <!-- 主仪表盘：1 个总量卡 + 3 个转化率圆环 -->
      <div class="gauge-row">
        <!-- 入库总量：大数字卡，不用圆环 -->
        <div class="gauge-card gauge-card-hero">
          <div class="gauge-label">入库总量</div>
          <div class="gauge-sub">ODS 原始数据量</div>
          <div class="hero-stat">
            <div class="hero-num">{{ kpi.ods.toLocaleString() }}</div>
            <div class="hero-unit">条</div>
          </div>
          <div class="hero-meta">
            <div class="hero-meta-row">
              <span class="hero-meta-label">覆盖城市</span>
              <span class="hero-meta-value">{{ cityCount }}</span>
            </div>
            <div class="hero-meta-row">
              <span class="hero-meta-label">DWD 清洗</span>
              <span class="hero-meta-value">{{ kpi.dwd.toLocaleString() }} 条</span>
            </div>
            <div class="hero-meta-row">
              <span class="hero-meta-label">DWS 服务</span>
              <span class="hero-meta-value">{{ kpi.dws.toLocaleString() }} 条</span>
            </div>
          </div>
        </div>

        <div class="gauge-card">
          <div class="gauge-label">清洗完成率</div>
          <div class="gauge-sub">DWD / ODS</div>
          <svg viewBox="0 0 200 200" class="gauge-svg">
            <circle class="gauge-track" cx="100" cy="100" r="80" />
            <circle class="gauge-fill gauge-fill-green"
              cx="100" cy="100" r="80"
              :stroke-dasharray="`${dwdPctAll * 5.025}, 503`"
              transform="rotate(-90 100 100)" />
            <text x="100" y="105" class="gauge-num gauge-num-big">{{ dwdPctAll.toFixed(2) }}</text>
            <text x="100" y="138" class="gauge-unit">%</text>
          </svg>
          <div class="gauge-foot">
            <span class="gauge-tag tag-green">{{ dwdPctAll >= 90 ? '✓ 优秀' : dwdPctAll >= 70 ? '● 良好' : '⚠ 待提升' }}</span>
            <span class="gauge-trend">{{ kpi.dwd.toLocaleString() }} / {{ kpi.ods.toLocaleString() }}</span>
          </div>
        </div>

        <div class="gauge-card">
          <div class="gauge-label">服务覆盖率</div>
          <div class="gauge-sub">DWS / DWD</div>
          <svg viewBox="0 0 200 200" class="gauge-svg">
            <circle class="gauge-track" cx="100" cy="100" r="80" />
            <circle class="gauge-fill gauge-fill-cyan"
              cx="100" cy="100" r="80"
              :stroke-dasharray="`${dwsPctAll * 5.025}, 503`"
              transform="rotate(-90 100 100)" />
            <text x="100" y="105" class="gauge-num gauge-num-big">{{ dwsPctAll.toFixed(2) }}</text>
            <text x="100" y="138" class="gauge-unit">%</text>
          </svg>
          <div class="gauge-foot">
            <span class="gauge-tag tag-cyan">{{ dwsPctAll >= 90 ? '✓ 优秀' : dwsPctAll >= 70 ? '● 良好' : '⚠ 待提升' }}</span>
            <span class="gauge-trend">{{ kpi.dws.toLocaleString() }} / {{ kpi.dwd.toLocaleString() }}</span>
          </div>
        </div>

        <div class="gauge-card gauge-card-main">
          <div class="gauge-label">属性解析覆盖率</div>
          <div class="gauge-sub">数据质量</div>
          <svg viewBox="0 0 200 200" class="gauge-svg">
            <circle class="gauge-track" cx="100" cy="100" r="80" />
            <circle class="gauge-fill gauge-fill-amber"
              cx="100" cy="100" r="80"
              :stroke-dasharray="`${kpi.attrRate * 5.025}, 503`"
              transform="rotate(-90 100 100)" />
            <text x="100" y="108" class="gauge-num gauge-num-big">{{ kpi.attrRate.toFixed(2) }}</text>
            <text x="100" y="138" class="gauge-unit">%</text>
          </svg>
          <div class="gauge-foot">
            <span class="gauge-tag" :class="kpi.attrRate >= 90 ? 'tag-green' : kpi.attrRate >= 70 ? 'tag-cyan' : 'tag-amber'">{{ kpi.attrRate >= 90 ? '✓ 优秀' : kpi.attrRate >= 70 ? '● 良好' : '⚠ 待提升' }}</span>
            <span class="gauge-trend">{{ cityCount }} 城实时</span>
          </div>
        </div>
      </div>

      <!-- 全链路管道：城市 × ODS→DWD→DWS（动态，从 data.all_cities 取） -->
      <div class="pipeline-section">
        <div class="section-title">
          <span class="section-dot"></span>
          数据处理管道 · ODS → DWD → DWS · {{ cityCount }} 城市
          <span class="section-sub mono">最后更新 {{ kpi.lastUpdate || '—' }}</span>
        </div>
        <div class="pipeline-grid">
          <div v-for="(pipe, key) in data.all_cities" :key="key" class="city-card"
            :class="{ alert: attrRate(pipe) < 80 }">

            <div class="city-header">
              <span class="city-name">{{ pipe.city_label }}</span>
              <span class="city-status" :class="attrRate(pipe) >= 80 ? 'ok' : 'warn'">
                {{ attrRate(pipe) >= 80 ? '✓ 在线' : '⚠ 异常' }}
              </span>
            </div>

            <!-- 三段式管道（不展示 ODS/DWD/DWS 分类标签，只留数字） -->
            <div class="city-pipe">
              <div class="city-stage">
                <div class="stage-num">{{ (pipe.ods?.count || 0).toLocaleString() }}</div>
                <div class="stage-bar">
                  <div class="stage-bar-fill" :style="{ width: '100%' }"></div>
                </div>
              </div>
              <div class="city-arrow" aria-hidden="true"><svg width="10" height="10" viewBox="0 0 10 10"><path d="M2 1 L7 5 L2 9" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg></div>
              <div class="city-stage">
                <div class="stage-num">{{ (pipe.dwd?.count || 0).toLocaleString() }}</div>
                <div class="stage-bar">
                  <div class="stage-bar-fill" :style="{ width: dwdPct(pipe) + '%' }"></div>
                </div>
              </div>
              <div class="city-arrow" aria-hidden="true"><svg width="10" height="10" viewBox="0 0 10 10"><path d="M2 1 L7 5 L2 9" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg></div>
              <div class="city-stage">
                <div class="stage-num">{{ (pipe.dws?.count || 0).toLocaleString() }}</div>
                <div class="stage-bar">
                  <div class="stage-bar-fill" :style="{ width: dwsPct(pipe) + '%' }"></div>
                </div>
              </div>
            </div>

            <!-- 抓取进度块整体删（道友 11:09：'6/6 类 信息也不需要展示'） -->

            <!-- attr 覆盖率迷你环 + 趋势 + sparkline -->
            <div class="city-attr">
              <svg viewBox="0 0 36 36" class="mini-ring">
                <circle class="mini-track" cx="18" cy="18" r="15" />
                <circle class="mini-fill" cx="18" cy="18" r="15"
                  :stroke-dasharray="`${attrRate(pipe) * 0.942}, 100`" />
              </svg>
              <div class="city-attr-info">
                <span class="city-attr-num mono">{{ attrRate(pipe).toFixed(1) }}%</span>
                <span class="city-attr-unit">属性解析</span>
              </div>
              <!-- 7 日 sparkline -->
              <div class="city-sparkline-wrap" v-if="pipe.sparkline_7d && pipe.sparkline_7d.length" :title="`近 7 日入库量（按城市）`">
                <svg class="city-sparkline" viewBox="0 0 80 24" preserveAspectRatio="none">
                  <polyline
                    class="spark-line"
                    :points="sparklinePoints(pipe.sparkline_7d)"
                    fill="none"
                    stroke="currentColor"
                    stroke-width="1.5"
                    stroke-linejoin="round"
                  />
                  <polyline
                    class="spark-area"
                    :points="sparklineArea(pipe.sparkline_7d)"
                    fill="currentColor"
                    opacity="0.15"
                  />
                </svg>
                <span class="city-sparkline-trend" :class="sparklineTrendCls(pipe.sparkline_7d)">
                  {{ sparklineTrend(pipe.sparkline_7d) }}
                </span>
              </div>
              <div v-else class="city-sparkline-empty" title="无近期入库记录">—</div>
            </div>
          </div>
        </div>
      </div>

      <!-- SKILL UPDATES 检块：各城市 skill 是否有更新记录 -->
      <div class="skill-updates-section">
        <div class="section-title">
          <span class="section-dot"></span>
          Skill 更新记录 · {{ cityCount }} 城市 · 各 skill 最近检查/更新
          <span class="section-sub mono">扫描于 {{ updatesNow || '—' }}</span>
        </div>
        <div class="skill-updates-grid">
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
      </div>

      <!-- 底部状态条 -->
      <div class="hud-footer">
        <div class="footer-cell">
          <span class="footer-label">系统</span>
          <span class="footer-value status-ok">✓ 正常</span>
        </div>
        <div class="footer-cell">
          <span class="footer-label">轮询</span>
          <span class="footer-value mono">30m</span>
        </div>
        <div class="footer-cell">
          <span class="footer-label">城市</span>
          <span class="footer-value mono">{{ Object.keys(data.all_cities).length }}</span>
        </div>
        <div class="footer-cell">
          <span class="footer-label">属性 OK</span>
          <span class="footer-value mono">{{ syncOkCount }}</span>
        </div>
        <div class="footer-cell">
          <span class="footer-label">过期</span>
          <span class="footer-value mono" :class="{ 'status-warn': staleCount > 0 }">{{ staleCount }}</span>
        </div>
        <div class="footer-cell">
          <span class="footer-label">告警</span>
          <span class="footer-value mono" :class="{ 'status-warn': alertCount > 0 }">{{ alertCount }}</span>
        </div>
        <div class="footer-cell">
          <span class="footer-label">数据质量</span>
          <span class="footer-value status-ok">● {{ kpi.attrRate >= 90 ? '优秀' : kpi.attrRate >= 70 ? 'GOOD' : 'FAIR' }}</span>
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

const 轮询_INTERVAL_MS = 30 * 60 * 1000  // 30 分钟

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

const staleCount = computed(() => {
  // 简易 stale 判定：scrape 超过 30 天未更新
  const now = new Date()
  return Object.values(data.all_cities || {}).filter(c => {
    const lu = c.scrape?.last_updated
    if (!lu) return false
    const days = (now - new Date(lu)) / 86400000
    return days > 30
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
  return diff > 0 ? `↑ ${Math.round(diff).toLocaleString()}` : `↓ ${Math.round(-diff).toLocaleString()}`
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
    // 补每个城市的 attr 覆盖率
    const cities = Object.keys(data.all_cities || {})
    const results = await Promise.allSettled(
      cities.map(city =>
        axios.get(`${API}/stats/spec-quality`, { params: { city, _sample: false } })
          .then(r => ({ city, data: r.data }))
      )
    )
    for (const r of results) {
      if (r.status === 'fulfilled') {
        const { city, data: sq } = r.value
        const cov = sq.coverage || []
        const total = cov.reduce((s, c) => s + (c.total || 0), 0)
        const withAttr = cov.reduce((s, c) => s + (c.with_attr || 0), 0)
        const rate = total > 0 ? (withAttr / total) * 100 : 0
        if (data.all_cities[city]) {
          data.all_cities[city].coverage = { rate, with_attr: withAttr, total }
        }
      }
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
  grid-template-columns: repeat(4, 1fr);
  gap: 16px;
  margin-bottom: 20px;
}
.gauge-card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 16px;
  box-shadow: var(--shadow-card);
  transition: transform var(--transition), box-shadow var(--transition);
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
  justify-content: center;
}
.hero-stat {
  text-align: center;
  padding: 12px 0 8px;
}
.hero-num {
  font-size: 36px;
  font-weight: 800;
  color: var(--text);
  font-family: var(--font-mono-num);
  line-height: 1.1;
  letter-spacing: -1px;
}
.hero-unit {
  font-size: 12px;
  color: var(--text-3);
  margin-top: 2px;
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
  max-width: 160px;
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
.gauge-fill-green { stroke: var(--success); }
.gauge-fill-cyan { stroke: var(--primary); }
.gauge-fill-amber { stroke: var(--warning); }
.gauge-num {
  fill: var(--text);
  font-size: 30px;
  font-weight: 700;
  text-anchor: middle;
}
.gauge-num-big { font-size: 38px; }
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
.tag-green { background: rgba(var(--success-rgb), 0.1); color: var(--success); }
.tag-cyan { background: rgba(var(--primary-rgb), 0.08); color: var(--primary); }
.tag-amber { background: rgba(var(--warning-rgb), 0.1); color: var(--warning); }
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
  gap: 12px;
}
.city-card,
.skill-update-card {
  background: var(--surface);
  border: 1px solid var(--border-light);
  border-radius: var(--radius-sm);
  padding: 12px;
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
  margin-bottom: 10px;
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

/* ── SKILL 卡片 body ── */
.update-body { display: flex; flex-direction: column; gap: 3px; }
.update-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 11px;
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

/* ── 响应式 ── */
@media (max-width: 1200px) {
  .gauge-row { grid-template-columns: repeat(2, 1fr); }
}
</style>
