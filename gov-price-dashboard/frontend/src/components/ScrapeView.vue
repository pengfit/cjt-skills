<template>
  <div class="scrape-page">

    <!-- All Cities Scrape Cards -->
    <div class="panel-header" style="margin-bottom:12px">
      <span class="panel-dot panel-dot-purple"></span>
      <span class="panel-title">数据抓取（全部城市）</span>
      <button class="poll-toggle" :class="{ active: pollingActive }" @click="togglePolling">
        {{ pollingActive ? '⏸ 暂停轮询' : '▶ 开启轮询' }}
      </button>
    </div>

    <div class="scrape-grid" v-if="data.all_cities">
      <div
        v-for="(pipe, key) in data.all_cities"
        :key="key"
        class="scrape-card"
        :class="{ running: scrapeRunning[key] }"
      >
        <div class="scrape-card-header">
          <div class="scrape-card-title">
            <span class="scrape-card-city">{{ pipe.city_label }}</span>
            <span class="scrape-card-status" :class="(pipe.scrape_fresh ?? pipe.sync_ok) ? 'ok' : 'warn'">
              {{ (pipe.scrape_fresh ?? pipe.sync_ok) ? '✓ 已同步' : '⚠ 待同步' }}
            </span>
          </div>
          <div class="scrape-card-pct">{{ scrapePct(pipe.scrape) }}%</div>
        </div>

        <div class="scrape-card-progress">
          <div class="scrape-progress-bar" :style="{ width: scrapePct(pipe.scrape) + '%' }"></div>
        </div>

        <div class="scrape-card-meta">
          <div class="scrape-card-meta-item">
            <span class="meta-label">完成</span>
            <span class="meta-value">
              <strong>{{ pipe.scrape?.completed ?? 0 }}</strong>
              <span class="meta-sep">/</span>
              <span>{{ pipe.scrape?.total_counties ?? '—' }}</span>
              <span class="meta-unit">{{ pipe.city_label === '河南' ? '期' : '类' }}</span>
            </span>
          </div>
          <div class="scrape-card-meta-item">
            <span class="meta-label">最后更新</span>
            <span class="meta-value mono">{{ pipe.scrape?.last_updated ? pipe.scrape.last_updated.slice(0,16) : '—' }}</span>
          </div>
        </div>

        <!-- Counties/Periods 列表（展开/收起） -->
        <div v-if="scrapeExpandedCity === key && pipe.scrape?.counties?.length" class="scrape-card-counties">
          <div
            v-for="c in pipe.scrape.counties"
            :key="c.county"
            class="scrape-county-chip"
            :class="c.status || 'not-started'"
          >
            <span class="chip-dot" :class="c.status || 'not-started'"></span>
            <span class="chip-name">{{ c.county }}</span>
            <span class="chip-pct">{{ (c.percent || 0).toFixed(0) }}%</span>
          </div>
        </div>

        <div class="scrape-card-actions">
          <button
            v-if="pipe.scrape?.counties?.length"
            class="scrape-action-btn ghost"
            @click="toggleScrapeCounties(key, pipe)"
          >
            {{ scrapeExpandedCity === key ? '▴ 收起' : expandLabel(pipe) }}
          </button>
          <button
            class="scrape-action-btn primary"
            :disabled="scrapeRunning[key]"
            @click="runScrapeCheck(key)"
          >
            <span v-if="scrapeRunning[key]" class="spin">↻</span>
            <span v-else>⟳</span>
            {{ scrapeRunning[key] ? '检查中...' : '检查更新' }}
          </button>
        </div>
      </div>
    </div>

    <div v-if="loading" class="prov-loading">
      <SkeletonCard :lines="3" :hide-footer="true" />
    </div>
    <EmptyState v-else-if="!data.all_cities || Object.keys(data.all_cities).length === 0"
      icon="📭" title="暂无抓取任务记录" message="该页面需要先运行过一次同步任务" />
    <div v-if="error" class="prov-error">{{ error }}</div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import axios from 'axios'
import SkeletonCard from './SkeletonCard.vue'
import EmptyState from './EmptyState.vue'

const API = import.meta.env.VITE_API_URL || '/api'

const loading = ref(false)
const error = ref('')
const scrapeExpandedCity = ref('')
const scrapeRunning = ref({})
const data = ref({ all_cities: {} })
let pollTimer = null
const pollingActive = ref(false)
const POLL_INTERVAL_MS = 15000

function scrapePct(scrape) {
  if (!scrape?.total_counties) return '0'
  return ((scrape.completed / scrape.total_counties) * 100).toFixed(0)
}

function toggleScrapeCounties(city, pipe) {
  scrapeExpandedCity.value = (scrapeExpandedCity.value === city) ? '' : city
}

// 各城市拓展按钮的文案（按数据维度命名）
const EXPAND_LABELS = {
  '西安': '▾ 区县记录',  // 6 区县 × 期数
  '四川': '▾ 地市详情',  // 21 地级市/自治州
  '重庆': '▾ 区县详情',  // 35 区县
  '济南': '▾ 分类详情',  // 41 产品分类
  '日照': '▾ 分类详情',  // 3 产品分类
  '河南': '▾ 期数详情',  // 按 PDF 期数
}
function expandLabel(pipe) {
  return EXPAND_LABELS[pipe.city_label] || '▾ 任务详情'
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

async function loadData() {
  loading.value = true
  error.value = ''
  try {
    const provRes = await axios.get(`${API}/stats/provenance`)
    data.value = provRes.data || { all_cities: {} }
  } catch (e) {
    error.value = '加载失败：' + (e.message || '网络错误')
  } finally {
    loading.value = false
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
.scrape-page {
  padding: 16px 20px 80px;
  min-height: 100vh;
  color: #1e293b;
}

/* === Panel header === */
.panel-header {
  display: flex;
  align-items: center;
  gap: 8px;
}
.panel-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  display: inline-block;
}
.panel-dot-blue   { background: var(--primary); box-shadow: 0 0 8px rgba(37,99,235,0.6); }
.panel-dot-purple { background: #a855f7; box-shadow: 0 0 8px rgba(168,85,247,0.6); }
/* panel-dot-cyan: 统一表示同步进行中，与主色一致 */
.panel-dot-cyan { background: var(--primary); box-shadow: 0 0 8px rgba(37,99,235,0.6); }
.panel-title {
  font-size: 14px;
  font-weight: 700;
  color: #1e293b;
  letter-spacing: 0.3px;
  margin-right: auto;
}
.poll-toggle {
  font-size: 11px;
  padding: 4px 12px;
  border-radius: 12px;
  border: 1px solid rgba(241,245,249,0.6);
  background: rgba(15, 23, 42, 0.03);
  color: var(--text-3);
  cursor: pointer;
  transition: all 0.2s;
}
.poll-toggle:hover { border-color: rgba(37,99,235,0.3); color: #1e293b; }
.poll-toggle.active {
  background: rgba(37,99,235,0.12);
  border-color: var(--primary);
  color: var(--primary);
}

/* === Scrape grid + cards === */
.scrape-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
  gap: 12px;
  margin-top: 8px;
}
.scrape-card {
  background: rgba(241,245,249,0.8);
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  padding: 14px 16px;
  transition: all 0.2s;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.scrape-card:hover { border-color: rgba(168,85,247,0.25); }
.scrape-card.running { animation: card-pulse 2s ease-in-out infinite; }

@keyframes card-pulse {
  0%, 100% { border-color: rgba(37,99,235,0.3); }
  50%      { border-color: rgba(37,99,235,0.6); }
}

.scrape-card-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 8px;
}
.scrape-card-title {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.scrape-card-city {
  font-size: 15px;
  font-weight: 700;
  color: #0f172a;
}
.scrape-card-status {
  font-size: 10px;
  padding: 2px 8px;
  border-radius: 10px;
  font-weight: 600;
  width: max-content;
}
.scrape-card-status.ok   { background: rgba(16,185,129,0.12); color: var(--status-ok); }
.scrape-card-status.warn { background: rgba(245,158,11,0.12); color: var(--status-warn); }
.scrape-card-pct {
  font-size: 24px;
  font-weight: 800;
  color: #7c3aed;
  font-family: ui-monospace, 'SF Mono', Consolas, 'Liberation Mono', monospace;
  line-height: 1;
}

/* === Progress bar === */
.scrape-card-progress {
  width: 100%;
  height: 6px;
  background: rgba(15,23,42,0.04);
  border-radius: 3px;
  overflow: hidden;
}
.scrape-progress-bar {
  height: 100%;
  background: linear-gradient(90deg, var(--primary), var(--primary-dark));
  border-radius: 3px;
  box-shadow: 0 0 12px rgba(37,99,235,0.4);
  transition: width 0.6s ease;
}

/* === Meta === */
.scrape-card-meta {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
  padding: 8px 0;
  border-top: 1px solid rgba(15,23,42,0.04);
  border-bottom: 1px solid rgba(15,23,42,0.04);
}
.scrape-card-meta-item {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.meta-label {
  font-size: 9px;
  color: var(--text-3);
  text-transform: uppercase;
  letter-spacing: 0.5px;
}
.meta-value {
  font-size: 13px;
  color: #1e293b;
  font-weight: 600;
}
.meta-value strong { color: #0f172a; font-weight: 800; }
.meta-value.mono { font-family: 'SF Mono', Consolas, monospace; font-size: 11px; }
.meta-sep { color: #475569; margin: 0 2px; }
.meta-unit { font-size: 10px; color: var(--text-3); margin-left: 2px; }

/* === Counties chips === */
.scrape-card-counties {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  padding: 6px 0;
  max-height: 140px;
  overflow-y: auto;
}
.scrape-county-chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 3px 8px;
  border-radius: 12px;
  background: rgba(15, 23, 42, 0.04);
  border: 1px solid #e2e8f0;
  font-size: 10px;
  color: var(--text-3);
}
.scrape-county-chip.completed {
  border-color: rgba(16,185,129,0.2);
  color: var(--status-ok);
}
.scrape-county-chip.running {
  border-color: rgba(37,99,235,0.3);
  color: var(--primary);
}
.scrape-county-chip.error {
  border-color: rgba(239,68,68,0.3);
  color: var(--status-alert);
}
.scrape-county-chip.not-started {
  opacity: 0.5;
}
.chip-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #475569;
}
.chip-dot.completed   { background: var(--status-ok); }
.chip-dot.running     { background: var(--primary); animation: dot-pulse 1.5s ease-in-out infinite; }
.chip-dot.error       { background: var(--status-alert); }
.chip-dot.not-started { background: #475569; }
.chip-pct {
  font-weight: 700;
  color: inherit;
  margin-left: 2px;
}
@keyframes dot-pulse {
  0%, 100% { opacity: 1; }
  50%      { opacity: 0.4; }
}

/* === Actions === */
.scrape-card-actions {
  display: flex;
  gap: 6px;
  margin-top: auto;
}
.scrape-action-btn {
  flex: 1;
  font-size: 12px;
  padding: 6px 10px;
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.2s;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 4px;
  font-weight: 600;
}
.scrape-action-btn.ghost {
  background: rgba(15, 23, 42, 0.03);
  border: 1px solid rgba(15,23,42,0.08);
  color: var(--text-3);
}
.scrape-action-btn.ghost:hover {
  background: #e2e8f0;
  border-color: #cbd5e1;
  color: #1e293b;
}
.scrape-action-btn.primary {
  background: rgba(168,85,247,0.12);
  border: 1px solid rgba(168,85,247,0.3);
  color: #7c3aed;
}
.scrape-action-btn.primary:hover:not(:disabled) {
  background: rgba(168,85,247,0.2);
  border-color: #a855f7;
}
.scrape-action-btn:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}
.scrape-action-btn .spin {
  animation: spin 1s linear infinite;
  display: inline-block;
}

/* === Loading / error === */
.prov-loading {
  display: flex;
  align-items: center;
  gap: 8px;
  color: var(--text-3);
  padding: 16px;
  font-size: 13px;
}
.loading-spinner {
  width: 16px;
  height: 16px;
  border: 2px solid rgba(37,99,235,0.2);
  border-top-color: var(--primary);
  border-radius: 50%;
  animation: spin 1s linear infinite;
}
@keyframes spin {
  to { transform: rotate(360deg); }
}
.prov-error {
  padding: 12px 16px;
  background: rgba(239,68,68,0.08);
  border: 1px solid rgba(239,68,68,0.2);
  border-radius: 8px;
  color: var(--status-alert);
  font-size: 13px;
}

@media (max-width: 768px) {
  .scrape-stats { grid-template-columns: repeat(2, 1fr); }
  .scrape-grid  { grid-template-columns: 1fr; }
}
</style>
