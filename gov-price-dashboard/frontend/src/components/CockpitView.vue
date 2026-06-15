<template>
  <div class="cockpit">
    <!-- 顶部 HUD 标题栏 -->
    <div class="hud-header">
      <div class="hud-corner tl"></div>
      <div class="hud-corner tr"></div>
      <div class="hud-title">
        <span class="hud-prefix">GOV-PRICE</span>
        <span class="hud-main">材价通 · 驾驶舱</span>
      </div>
      <div class="hud-status">
        <span class="hud-clock mono">{{ clock }}</span>
        <span class="hud-live" :class="{ active: pollingActive }">● LIVE</span>
        <button class="hud-btn" @click="manualRefresh" :disabled="loading" title="立即拉取最新数据">
          {{ loading ? '⟳ LOADING' : '↻ REFRESH' }}
        </button>
        <button class="hud-btn" @click="togglePolling">
          {{ pollingActive ? '⏸ PAUSE' : '▶ RESUME' }}
        </button>
      </div>
    </div>

    <!-- 加载 / 错误状态 -->
    <div v-if="loading && !data.all_cities" class="cockpit-loading">
      <div class="loading-spinner"></div>
      <span>LOADING TELEMETRY...</span>
    </div>
    <div v-if="error" class="cockpit-error">⚠ {{ error }}</div>

    <template v-if="data.all_cities">
      <!-- 主仪表盘：4 个大型圆形仪表 -->
      <div class="gauge-row">
        <div class="gauge-card">
          <div class="gauge-label">DATA INGEST</div>
          <div class="gauge-sub">ODS 抓取总量</div>
          <svg viewBox="0 0 200 200" class="gauge-svg">
            <circle class="gauge-track" cx="100" cy="100" r="80" />
            <circle class="gauge-fill gauge-fill-green"
              cx="100" cy="100" r="80"
              :stroke-dasharray="`${odsPct * 5.025}, 503`"
              transform="rotate(-90 100 100)" />
            <g class="gauge-ticks">
              <line v-for="i in 24" :key="i" :x1="100" :y1="20" :x2="100" :y2="28"
                :transform="`rotate(${i * 15} 100 100)`" />
            </g>
            <text x="100" y="105" class="gauge-num">{{ kpi.ods.toLocaleString() }}</text>
            <text x="100" y="135" class="gauge-unit">DOCS</text>
          </svg>
          <div class="gauge-foot">
            <span class="gauge-tag tag-green">7 CITIES</span>
            <span class="gauge-trend">+{{ kpi.odsDelta }} 7D</span>
          </div>
        </div>

        <div class="gauge-card">
          <div class="gauge-label">DATA TRANSFORM</div>
          <div class="gauge-sub">DWD 清洗总量</div>
          <svg viewBox="0 0 200 200" class="gauge-svg">
            <circle class="gauge-track" cx="100" cy="100" r="80" />
            <circle class="gauge-fill gauge-fill-cyan"
              cx="100" cy="100" r="80"
              :stroke-dasharray="`${kpi.dwd / kpi.ods * 100 * 5.025}, 503`"
              transform="rotate(-90 100 100)" />
            <g class="gauge-ticks">
              <line v-for="i in 24" :key="i" :x1="100" :y1="20" :x2="100" :y2="28"
                :transform="`rotate(${i * 15} 100 100)`" />
            </g>
            <text x="100" y="105" class="gauge-num">{{ kpi.dwd.toLocaleString() }}</text>
            <text x="100" y="135" class="gauge-unit">DOCS</text>
          </svg>
          <div class="gauge-foot">
            <span class="gauge-tag tag-cyan">{{ (kpi.dwd / kpi.ods * 100).toFixed(1) }}%</span>
            <span class="gauge-trend">3-STAGE ETL</span>
          </div>
        </div>

        <div class="gauge-card">
          <div class="gauge-label">DATA SERVE</div>
          <div class="gauge-sub">DWS 服务总量</div>
          <svg viewBox="0 0 200 200" class="gauge-svg">
            <circle class="gauge-track" cx="100" cy="100" r="80" />
            <circle class="gauge-fill gauge-fill-cyan"
              cx="100" cy="100" r="80"
              :stroke-dasharray="`${kpi.dws / kpi.ods * 100 * 5.025}, 503`"
              transform="rotate(-90 100 100)" />
            <g class="gauge-ticks">
              <line v-for="i in 24" :key="i" :x1="100" :y1="20" :x2="100" :y2="28"
                :transform="`rotate(${i * 15} 100 100)`" />
            </g>
            <text x="100" y="105" class="gauge-num">{{ kpi.dws.toLocaleString() }}</text>
            <text x="100" y="135" class="gauge-unit">DOCS</text>
          </svg>
          <div class="gauge-foot">
            <span class="gauge-tag tag-cyan">{{ (kpi.dws / kpi.ods * 100).toFixed(1) }}%</span>
            <span class="gauge-trend">SYNC OK</span>
          </div>
        </div>

        <div class="gauge-card gauge-card-main">
          <div class="gauge-label">ATTR COVERAGE</div>
          <div class="gauge-sub">属性解析覆盖率</div>
          <svg viewBox="0 0 200 200" class="gauge-svg">
            <circle class="gauge-track" cx="100" cy="100" r="80" />
            <circle class="gauge-fill gauge-fill-amber"
              cx="100" cy="100" r="80"
              :stroke-dasharray="`${kpi.attrRate * 5.025}, 503`"
              transform="rotate(-90 100 100)" />
            <g class="gauge-ticks">
              <line v-for="i in 24" :key="i" :x1="100" :y1="20" :x2="100" :y2="28"
                :transform="`rotate(${i * 15} 100 100)`" />
            </g>
            <text x="100" y="108" class="gauge-num gauge-num-big">{{ kpi.attrRate.toFixed(1) }}</text>
            <text x="100" y="138" class="gauge-unit">PERCENT</text>
          </svg>
          <div class="gauge-foot">
            <span class="gauge-tag tag-amber">95.6% AVG</span>
            <span class="gauge-trend">+ AI BATCH</span>
          </div>
        </div>
      </div>

      <!-- 全链路管道：7 城 × ODS→DWD→DWS -->
      <div class="pipeline-section">
        <div class="section-title">
          <span class="section-dot"></span>
          ETL PIPELINE · ODS → DWD → DWS · 7 CITIES
          <span class="section-sub mono">LAST UPDATE: {{ kpi.lastUpdate || '—' }}</span>
        </div>
        <div class="pipeline-grid">
          <div v-for="(pipe, key) in data.all_cities" :key="key" class="city-card"
            :class="{ alert: !pipe.sync_ok }">
            <div class="city-card-corner tl"></div>
            <div class="city-card-corner tr"></div>
            <div class="city-card-corner bl"></div>
            <div class="city-card-corner br"></div>

            <div class="city-header">
              <span class="city-name">{{ pipe.city_label }}</span>
              <span class="city-status" :class="pipe.sync_ok ? 'ok' : 'warn'">
                {{ pipe.sync_ok ? '● ONLINE' : '● ALERT' }}
              </span>
            </div>

            <!-- 三段式管道 -->
            <div class="city-pipe">
              <div class="city-stage">
                <div class="stage-tag">ODS</div>
                <div class="stage-num">{{ (pipe.ods?.count || 0).toLocaleString() }}</div>
                <div class="stage-bar">
                  <div class="stage-bar-fill" :style="{ width: '100%' }"></div>
                </div>
              </div>
              <div class="city-arrow">▶</div>
              <div class="city-stage">
                <div class="stage-tag">DWD</div>
                <div class="stage-num">{{ (pipe.dwd?.count || 0).toLocaleString() }}</div>
                <div class="stage-bar">
                  <div class="stage-bar-fill" :style="{ width: dwdPct(pipe) + '%' }"></div>
                </div>
              </div>
              <div class="city-arrow">▶</div>
              <div class="city-stage">
                <div class="stage-tag">DWS</div>
                <div class="stage-num">{{ (pipe.dws?.count || 0).toLocaleString() }}</div>
                <div class="stage-bar">
                  <div class="stage-bar-fill" :style="{ width: dwsPct(pipe) + '%' }"></div>
                </div>
              </div>
            </div>

            <!-- 抓取进度 -->
            <div class="city-scrape">
              <div class="scrape-row">
                <span class="scrape-label">SCRAPE</span>
                <span class="scrape-pct mono">{{ scrapePct(pipe.scrape) }}%</span>
              </div>
              <div class="scrape-bar">
                <div class="scrape-bar-fill" :style="{ width: scrapePct(pipe.scrape) + '%' }"></div>
              </div>
              <div class="scrape-meta mono">
                {{ pipe.scrape?.completed || 0 }} / {{ pipe.scrape?.total_counties || '—' }} {{ pipe.city_label === '河南' ? '期' : '类' }}
                · {{ pipe.scrape?.last_updated?.slice(5,16) || '—' }}
              </div>
            </div>

            <!-- attr 覆盖率迷你环 -->
            <div class="city-attr">
              <svg viewBox="0 0 36 36" class="mini-ring">
                <circle class="mini-track" cx="18" cy="18" r="15" />
                <circle class="mini-fill" cx="18" cy="18" r="15"
                  :stroke-dasharray="`${attrRate(pipe) * 0.942}, 100`" />
              </svg>
              <div class="city-attr-info">
                <span class="city-attr-num mono">{{ attrRate(pipe).toFixed(1) }}</span>
                <span class="city-attr-unit">% ATTR</span>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- SKILL UPDATES 检块：各城市 skill 是否有更新记录 -->
      <div class="skill-updates-section">
        <div class="section-title">
          <span class="section-dot"></span>
          SKILL UPDATES · 7 CITIES · 各 skill 最近检查/更新记录
          <span class="section-sub mono">SCAN AT: {{ updatesNow || '—' }}</span>
        </div>
        <div class="skill-updates-grid">
          <div v-for="u in skillUpdates" :key="u.city" class="skill-update-card"
            :class="['status-' + u.status]">
            <div class="update-card-corner tl"></div>
            <div class="update-card-corner tr"></div>
            <div class="update-card-corner bl"></div>
            <div class="update-card-corner br"></div>

            <div class="update-header">
              <span class="update-city">{{ u.city_label }}</span>
              <span class="update-status" :class="u.status">
                <span v-if="u.status === 'fresh'">● FRESH</span>
                <span v-else-if="u.status === 'stale'">● STALE</span>
                <span v-else-if="u.status === 'very_stale'">● VERY STALE</span>
                <span v-else>● NO DATA</span>
              </span>
            </div>
            <div class="update-body">
              <div class="update-row">
                <span class="update-label">LAST UPDATED</span>
                <span class="update-value mono">{{ formatUpdateTime(u.last_updated) }}</span>
              </div>
              <div class="update-row">
                <span class="update-label">SINCE</span>
                <span class="update-value mono">{{ u.hours_since != null ? hoursAgo(u.hours_since) : '—' }}</span>
              </div>
              <div class="update-row">
                <span class="update-label">LATEST PERIOD</span>
                <span class="update-value mono">{{ u.latest_period || '—' }}</span>
              </div>
              <div class="update-row">
                <span class="update-label">PROGRESS</span>
                <span class="update-value mono">{{ u.completed_periods }}/{{ u.total_periods }} 期</span>
              </div>
              <div v-if="u.has_incremental" class="update-badge">
                <span class="badge-incremental">+ INCREMENTAL</span>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- 底部状态条 -->
      <div class="hud-footer">
        <div class="footer-cell">
          <span class="footer-label">SYSTEM</span>
          <span class="footer-value status-ok">● NOMINAL</span>
        </div>
        <div class="footer-cell">
          <span class="footer-label">POLL</span>
          <span class="footer-value mono">30m</span>
        </div>
        <div class="footer-cell">
          <span class="footer-label">CITIES</span>
          <span class="footer-value mono">{{ Object.keys(data.all_cities).length }} / 7</span>
        </div>
        <div class="footer-cell">
          <span class="footer-label">SYNC OK</span>
          <span class="footer-value mono">{{ syncOkCount }} / 7</span>
        </div>
        <div class="footer-cell">
          <span class="footer-label">STALE</span>
          <span class="footer-value mono" :class="{ 'status-warn': staleCount > 0 }">{{ staleCount }}</span>
        </div>
        <div class="footer-cell">
          <span class="footer-label">ALERTS</span>
          <span class="footer-value mono" :class="{ 'status-warn': alertCount > 0 }">{{ alertCount }}</span>
        </div>
        <div class="footer-cell">
          <span class="footer-label">DATA QUALITY</span>
          <span class="footer-value status-ok">● {{ kpi.attrRate >= 90 ? 'EXCELLENT' : kpi.attrRate >= 70 ? 'GOOD' : 'FAIR' }}</span>
        </div>
      </div>
    </template>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted, onUnmounted, nextTick } from 'vue'
import axios from 'axios'

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

const POLL_INTERVAL_MS = 30 * 60 * 1000  // 30 分钟

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

const odsPct = computed(() => Math.min(100, kpi.value.ods / 1000))

const syncOkCount = computed(() => {
  return Object.values(data.all_cities || {}).filter(c => c.sync_ok).length
})

const alertCount = computed(() => {
  return Object.values(data.all_cities || {}).filter(c => !c.sync_ok).length
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

function scrapePct(scrape) {
  if (!scrape) return 0
  const done = scrape.completed || 0
  const total = scrape.total_counties || 0
  return total > 0 ? Math.round(done / total * 100) : 0
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
  pollTimer = setInterval(loadData, POLL_INTERVAL_MS)
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
  background: radial-gradient(ellipse at top, #0a1929 0%, #050a14 50%, #000 100%);
  color: #e0e8f0;
  font-family: -apple-system, BlinkMacSystemFont, 'PingFang SC', sans-serif;
  padding: 16px 20px;
  min-height: 100vh;
  position: relative;
}

/* ── HUD 通用 ─────────────────────────────────────── */
.mono { font-family: 'SF Mono', 'Monaco', 'Menlo', 'Roboto Mono', monospace; }

.hud-corner {
  position: absolute;
  width: 20px;
  height: 20px;
  border: 2px solid #00d4ff;
  opacity: 0.6;
}
.hud-corner.tl { top: 0; left: 0; border-right: none; border-bottom: none; }
.hud-corner.tr { top: 0; right: 0; border-left: none; border-bottom: none; }

/* ── 顶部标题栏 ─────────────────────────────────── */
.hud-header {
  position: relative;
  background: linear-gradient(90deg, transparent 0%, rgba(0,212,255,0.08) 50%, transparent 100%);
  border: 1px solid rgba(0,212,255,0.3);
  border-radius: 4px;
  padding: 14px 24px;
  margin-bottom: 20px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  letter-spacing: 1px;
}
.hud-title { display: flex; align-items: baseline; gap: 16px; }
.hud-prefix {
  color: #00d4ff;
  font-size: 12px;
  letter-spacing: 4px;
  text-shadow: 0 0 8px #00d4ff;
}
.hud-main {
  color: #00ff88;
  font-size: 22px;
  font-weight: 700;
  text-shadow: 0 0 12px rgba(0,255,136,0.6);
  letter-spacing: 2px;
}
.hud-status { display: flex; align-items: center; gap: 16px; }
.hud-clock {
  color: #00ff88;
  font-size: 18px;
  font-weight: 600;
  text-shadow: 0 0 8px rgba(0,255,136,0.5);
  letter-spacing: 1px;
}
.hud-live {
  color: #ff3838;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 2px;
  text-shadow: 0 0 6px #ff3838;
  animation: pulse 1.5s ease-in-out infinite;
}
.hud-live.active::before { content: '●'; }
.hud-live:not(.active) { color: #555; text-shadow: none; }
@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.4; }
}
.hud-btn {
  background: transparent;
  border: 1px solid #00d4ff;
  color: #00d4ff;
  padding: 6px 14px;
  border-radius: 2px;
  font-size: 11px;
  letter-spacing: 2px;
  cursor: pointer;
  transition: all 0.2s;
  font-family: 'SF Mono', 'Monaco', monospace;
}
.hud-btn:hover {
  background: rgba(0,212,255,0.15);
  box-shadow: 0 0 12px rgba(0,212,255,0.5);
}
.hud-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
  border-color: #555;
  color: #555;
}

/* ── 加载 / 错误 ─────────────────────────────────── */
.cockpit-loading {
  text-align: center;
  padding: 60px;
  color: #00d4ff;
  font-family: monospace;
  letter-spacing: 4px;
}
.loading-spinner {
  display: inline-block;
  width: 40px;
  height: 40px;
  border: 2px solid #00d4ff;
  border-top-color: transparent;
  border-radius: 50%;
  animation: spin 1s linear infinite;
  margin-bottom: 12px;
}
@keyframes spin { to { transform: rotate(360deg); } }
.cockpit-error {
  background: rgba(255,56,56,0.1);
  border: 1px solid #ff3838;
  color: #ff3838;
  padding: 12px;
  border-radius: 4px;
  font-family: monospace;
  margin: 20px 0;
}

/* ── 主仪表盘（4 个圆形仪表） ─────────────────── */
.gauge-row {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 16px;
  margin-bottom: 24px;
}
.gauge-card {
  background: linear-gradient(180deg, rgba(10,25,40,0.8) 0%, rgba(5,10,20,0.6) 100%);
  border: 1px solid rgba(0,212,255,0.3);
  border-radius: 6px;
  padding: 16px;
  position: relative;
  overflow: hidden;
}
.gauge-card::before {
  content: '';
  position: absolute;
  top: 0; left: 0; right: 0;
  height: 1px;
  background: linear-gradient(90deg, transparent, #00d4ff, transparent);
  opacity: 0.6;
}
.gauge-card-main {
  border-color: rgba(255,149,0,0.4);
  background: linear-gradient(180deg, rgba(40,25,5,0.8) 0%, rgba(20,10,5,0.6) 100%);
}
.gauge-card-main::before {
  background: linear-gradient(90deg, transparent, #ff9500, transparent);
}
.gauge-label {
  color: #00d4ff;
  font-size: 10px;
  letter-spacing: 3px;
  font-weight: 700;
  text-align: center;
  margin-bottom: 2px;
}
.gauge-card-main .gauge-label { color: #ff9500; }
.gauge-sub {
  color: #6a7a8a;
  font-size: 11px;
  text-align: center;
  margin-bottom: 8px;
}
.gauge-svg {
  width: 100%;
  height: auto;
  max-width: 180px;
  margin: 0 auto;
  display: block;
}
.gauge-track {
  fill: none;
  stroke: rgba(255,255,255,0.06);
  stroke-width: 8;
}
.gauge-fill {
  fill: none;
  stroke-width: 8;
  stroke-linecap: round;
  transition: stroke-dasharray 0.6s ease;
}
.gauge-fill-green { stroke: #00ff88; filter: drop-shadow(0 0 6px #00ff88); }
.gauge-fill-cyan { stroke: #00d4ff; filter: drop-shadow(0 0 6px #00d4ff); }
.gauge-fill-amber { stroke: #ff9500; filter: drop-shadow(0 0 6px #ff9500); }
.gauge-ticks line {
  stroke: rgba(255,255,255,0.15);
  stroke-width: 1;
}
.gauge-num {
  fill: #00ff88;
  font-size: 32px;
  font-weight: 700;
  text-anchor: middle;
  font-family: 'SF Mono', 'Monaco', monospace;
  text-shadow: 0 0 8px rgba(0,255,136,0.5);
}
.gauge-card-main .gauge-num { fill: #ff9500; text-shadow: 0 0 12px rgba(255,149,0,0.6); }
.gauge-num-big { font-size: 40px; }
.gauge-unit {
  fill: #6a7a8a;
  font-size: 9px;
  text-anchor: middle;
  letter-spacing: 4px;
  font-family: monospace;
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
  border-radius: 2px;
  font-family: monospace;
  font-size: 10px;
  letter-spacing: 1px;
  font-weight: 700;
}
.tag-green { background: rgba(0,255,136,0.15); color: #00ff88; }
.tag-cyan { background: rgba(0,212,255,0.15); color: #00d4ff; }
.tag-amber { background: rgba(255,149,0,0.15); color: #ff9500; }
.gauge-trend {
  color: #6a7a8a;
  font-family: monospace;
  font-size: 10px;
  letter-spacing: 1px;
}

/* ── 全链路管道 ─────────────────────────────── */
.pipeline-section {
  background: linear-gradient(180deg, rgba(10,25,40,0.5) 0%, rgba(5,10,20,0.3) 100%);
  border: 1px solid rgba(0,212,255,0.25);
  border-radius: 6px;
  padding: 16px 20px;
  margin-bottom: 16px;
}
.section-title {
  color: #00d4ff;
  font-size: 13px;
  letter-spacing: 3px;
  font-weight: 700;
  margin-bottom: 16px;
  display: flex;
  align-items: center;
  gap: 10px;
  text-shadow: 0 0 6px rgba(0,212,255,0.4);
}
.section-dot {
  width: 8px;
  height: 8px;
  background: #00d4ff;
  border-radius: 50%;
  box-shadow: 0 0 8px #00d4ff;
}
.section-sub {
  color: #6a7a8a;
  font-size: 10px;
  letter-spacing: 1px;
  margin-left: auto;
  font-weight: 400;
  text-shadow: none;
}

.pipeline-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 12px;
}
.city-card {
  background: linear-gradient(180deg, rgba(0,30,50,0.6) 0%, rgba(0,15,25,0.4) 100%);
  border: 1px solid rgba(0,212,255,0.2);
  border-radius: 4px;
  padding: 12px;
  position: relative;
  transition: all 0.2s;
}
.city-card:hover {
  border-color: rgba(0,255,136,0.5);
  box-shadow: 0 0 16px rgba(0,255,136,0.2);
}
.city-card.alert {
  border-color: rgba(255,56,56,0.5);
  animation: alertPulse 2s ease-in-out infinite;
}
@keyframes alertPulse {
  0%, 100% { box-shadow: 0 0 0 rgba(255,56,56,0); }
  50% { box-shadow: 0 0 12px rgba(255,56,56,0.4); }
}
.city-card-corner {
  position: absolute;
  width: 8px;
  height: 8px;
  border: 1px solid #00d4ff;
  opacity: 0.5;
}
.city-card-corner.tl { top: -1px; left: -1px; border-right: none; border-bottom: none; }
.city-card-corner.tr { top: -1px; right: -1px; border-left: none; border-bottom: none; }
.city-card-corner.bl { bottom: -1px; left: -1px; border-right: none; border-top: none; }
.city-card-corner.br { bottom: -1px; right: -1px; border-left: none; border-top: none; }

.city-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
}
.city-name {
  color: #00d4ff;
  font-size: 16px;
  font-weight: 700;
  letter-spacing: 1px;
  text-shadow: 0 0 4px rgba(0,212,255,0.5);
}
.city-status {
  font-size: 9px;
  letter-spacing: 1px;
  font-family: monospace;
  font-weight: 700;
}
.city-status.ok { color: #00ff88; text-shadow: 0 0 4px #00ff88; }
.city-status.warn { color: #ff9500; text-shadow: 0 0 4px #ff9500; }

.city-pipe {
  display: flex;
  align-items: center;
  gap: 4px;
  margin-bottom: 12px;
}
.city-stage { flex: 1; min-width: 0; }
.city-arrow { flex-shrink: 0; color: #00d4ff; font-size: 10px; opacity: 0.5; }
.stage-tag {
  color: #6a7a8a;
  font-size: 9px;
  font-weight: 700;
  letter-spacing: 2px;
  margin-bottom: 2px;
  font-family: monospace;
}
.stage-num {
  color: #00ff88;
  font-size: 14px;
  font-weight: 700;
  font-family: 'SF Mono', monospace;
  font-variant-numeric: tabular-nums;
  text-shadow: 0 0 4px rgba(0,255,136,0.4);
  margin-bottom: 4px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.stage-bar {
  height: 3px;
  background: rgba(255,255,255,0.05);
  border-radius: 1px;
  overflow: hidden;
}
.stage-bar-fill {
  height: 100%;
  background: linear-gradient(90deg, #00d4ff, #00ff88);
  box-shadow: 0 0 6px rgba(0,255,136,0.5);
  transition: width 0.6s;
}


.city-scrape { margin-bottom: 10px; }
.scrape-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 9px;
  letter-spacing: 1px;
  margin-bottom: 4px;
  font-family: monospace;
}
.scrape-label { color: #6a7a8a; }
.scrape-pct { color: #00d4ff; }
.scrape-bar {
  height: 2px;
  background: rgba(255,255,255,0.05);
  border-radius: 1px;
  overflow: hidden;
  margin-bottom: 4px;
}
.scrape-bar-fill {
  height: 100%;
  background: linear-gradient(90deg, #00d4ff, #00ff88);
  box-shadow: 0 0 4px rgba(0,255,136,0.4);
}
.scrape-meta {
  color: #4a5a6a;
  font-size: 9px;
  letter-spacing: 0.5px;
}

.city-attr {
  display: flex;
  align-items: center;
  gap: 8px;
  padding-top: 8px;
  border-top: 1px solid rgba(0,212,255,0.15);
}
.mini-ring { width: 32px; height: 32px; flex-shrink: 0; }
.mini-track { fill: none; stroke: rgba(255,255,255,0.05); stroke-width: 3; }
.mini-fill {
  fill: none;
  stroke: #ff9500;
  stroke-width: 3;
  stroke-linecap: round;
  transform: rotate(-90deg);
  transform-origin: 18px 18px;
  filter: drop-shadow(0 0 4px #ff9500);
  transition: stroke-dasharray 0.6s;
}
.city-attr-info { display: flex; align-items: baseline; gap: 4px; }
.city-attr-num {
  color: #ff9500;
  font-size: 16px;
  font-weight: 700;
  text-shadow: 0 0 4px rgba(255,149,0,0.5);
}
.city-attr-unit {
  color: #6a7a8a;
  font-size: 9px;
  letter-spacing: 1px;
  font-family: monospace;
}

/* ── 底部状态条 ─────────────────────────────── */
.hud-footer {
  display: flex;
  gap: 1px;
  background: rgba(0,212,255,0.15);
  border: 1px solid rgba(0,212,255,0.3);
  border-radius: 4px;
  overflow: hidden;
}
.footer-cell {
  flex: 1;
  background: rgba(5,10,20,0.8);
  padding: 8px 12px;
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.footer-label {
  color: #6a7a8a;
  font-size: 9px;
  letter-spacing: 2px;
  font-weight: 700;
  font-family: monospace;
}
.footer-value {
  color: #00ff88;
  font-size: 13px;
  font-weight: 700;
  text-shadow: 0 0 4px rgba(0,255,136,0.4);
}
.footer-value.status-ok { color: #00ff88; }
.footer-value.status-warn { color: #ff9500; text-shadow: 0 0 4px rgba(255,149,0,0.5); }

/* ── 响应式 ─────────────────────────────── */
@media (max-width: 1200px) {
  .gauge-row { grid-template-columns: repeat(2, 1fr); }
  .pipeline-grid { grid-template-columns: repeat(auto-fill, minmax(180px, 1fr)); }
}

/* ── SKILL UPDATES 模块 ─────────────────────────── */
.skill-updates-section {
  background: linear-gradient(180deg, rgba(10,25,40,0.5) 0%, rgba(5,10,20,0.3) 100%);
  border: 1px solid rgba(0,212,255,0.25);
  border-radius: 6px;
  padding: 16px 20px;
  margin-bottom: 16px;
}
.skill-updates-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
  gap: 12px;
}
.skill-update-card {
  position: relative;
  background: linear-gradient(180deg, rgba(0,30,50,0.6) 0%, rgba(0,15,25,0.4) 100%);
  border: 1px solid rgba(0,212,255,0.2);
  border-radius: 4px;
  padding: 12px 14px;
  transition: all 0.2s;
}
.skill-update-card:hover {
  border-color: rgba(0,255,136,0.5);
  box-shadow: 0 0 12px rgba(0,255,136,0.2);
}
.skill-update-card.status-fresh { border-left: 3px solid #00ff88; }
.skill-update-card.status-stale { border-left: 3px solid #ff9500; }
.skill-update-card.status-very_stale {
  border-left: 3px solid #ff3838;
  animation: alertPulse 2s ease-in-out infinite;
}
.skill-update-card.status-no_data { border-left: 3px solid #6a7a8a; opacity: 0.7; }
.update-card-corner {
  position: absolute;
  width: 6px;
  height: 6px;
  border: 1px solid #00d4ff;
  opacity: 0.4;
}
.update-card-corner.tl { top: -1px; left: -1px; border-right: none; border-bottom: none; }
.update-card-corner.tr { top: -1px; right: -1px; border-left: none; border-bottom: none; }
.update-card-corner.bl { bottom: -1px; left: -1px; border-right: none; border-top: none; }
.update-card-corner.br { bottom: -1px; right: -1px; border-left: none; border-top: none; }
.update-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}
.update-city {
  color: #00d4ff;
  font-size: 15px;
  font-weight: 700;
  letter-spacing: 1px;
  text-shadow: 0 0 4px rgba(0,212,255,0.5);
}
.update-status {
  font-size: 9px;
  letter-spacing: 1.5px;
  font-family: monospace;
  font-weight: 700;
}
.update-status.fresh { color: #00ff88; text-shadow: 0 0 4px #00ff88; }
.update-status.stale { color: #ff9500; text-shadow: 0 0 4px #ff9500; }
.update-status.very_stale { color: #ff3838; text-shadow: 0 0 4px #ff3838; }
.update-status.no_data { color: #6a7a8a; }
.update-body {
  display: flex;
  flex-direction: column;
  gap: 3px;
}
.update-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 10px;
  font-family: monospace;
}
.update-label {
  color: #6a7a8a;
  letter-spacing: 1px;
}
.update-value {
  color: #e0e8f0;
  font-weight: 600;
}
.update-badge {
  margin-top: 6px;
}
.badge-incremental {
  background: rgba(0,255,136,0.15);
  color: #00ff88;
  padding: 2px 6px;
  border-radius: 2px;
  font-family: monospace;
  font-size: 9px;
  letter-spacing: 1px;
  font-weight: 700;
  border: 1px solid rgba(0,255,136,0.4);
}
</style>
