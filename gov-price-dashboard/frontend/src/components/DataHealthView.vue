<template>
  <div class="health-page" :class="{ 'show-card-detail': showCardDetail }">

    <!-- 四个汇总指标卡 -->
    <div class="health-cards">
      <div class="stat-card stat-card-primary">
        <div class="stat-card-inner">
          <div class="stat-icon">📄</div>
          <div class="stat-content">
            <div class="stat-label">总数据量</div>
            <div class="stat-value"><span class="stat-num">{{ data.total_docs.toLocaleString() }}</span><span class="stat-unit">条</span></div>
          </div>
          <div class="stat-glow"></div>
        </div>
      </div>
      <div class="stat-card stat-card-cyan">
        <div class="stat-card-inner">
          <div class="stat-icon">🏛️</div>
          <div class="stat-content">
            <div class="stat-label">省份数量</div>
            <div class="stat-value"><span class="stat-num">{{ data.province_count }}</span><span class="stat-unit">个</span></div>
          </div>
          <div class="stat-glow"></div>
        </div>
      </div>
    </div>

    <!-- 图表区域 -->
    <div class="chart-panel">
      <div class="panel-header">
        <div class="panel-title-row">
          <span class="panel-dot panel-dot-blue"></span>
          <span class="panel-title">近30日数据量趋势</span>
        </div>
        <div class="chart-legend">
          <span class="legend-item"><span class="legend-dot"></span>日增量</span>
        </div>
      </div>
      <div id="dailyTrendChart" class="chart-area"></div>
    </div>

    <!-- 省份同步卡片网格 -->
    <div class="sync-grid-tools">
      <span class="sync-grid-hint">默认只显示概览，点击「展开详情」查看区县进度与环状圈</span>
      <button class="sync-grid-toggle" @click="showCardDetail = !showCardDetail">
        {{ showCardDetail ? '▴ 收起详情' : '▾ 展开详情' }}
      </button>
    </div>
    <div class="sync-grid">

      <!-- 西安 -->
      <!-- 动态卡片：从 /api/skill-registry 自动发现，新增 skill 零代码上线 -->
      <SyncCard v-for="s in skills" :key="s.key" :skill="s" :data="syncDataMap[s.key] || {}" />
    </div>

    <div v-if="loading" class="health-loading">
      <SkeletonCard :lines="5" :hide-footer="true" />
    </div>
    <EmptyState v-else-if="!Object.keys(data || {}).length"
      icon="📊" title="暂无数据" message="请稍后再试或检查上游接口" />
    <ErrorState v-if="error" :title="'加载失败'" :message="error" compact :on-retry="loadData" />
  </div>
</template>

<script setup>
import ErrorState from './ErrorState.vue'
import { ref, onMounted, onUnmounted, nextTick, computed, watch } from 'vue'
import axios from 'axios'
import { getGovPriceTheme } from '../composables/useEchartsTheme'
import { markRaw } from 'vue'
import * as echarts from 'echarts'
import SkeletonCard from './SkeletonCard.vue'
import EmptyState from './EmptyState.vue'
import SyncCard from './SyncCard.vue'

const API = import.meta.env.VITE_API_URL || '/api'
const loading = ref(false)
const error = ref('')
const showCardDetail = ref(false)  // 6 城大卡详情默认收起，仅显示概览
const data = ref({
  total_docs: 0, province_count: 0,
  daily: [], provinces: []
})
const PAGE_SIZE = 10

// ==================== 动态 skill 注册（v-for 驱动） ====================
const skills = ref([])
const syncDataMap = ref({})
const pollTimers = ref({})

// 动态加载所有 skill 的同步进度
async function loadAllSkillProgress() {
  try {
    const regRes = await axios.get(`${API}/skill-registry`)
    skills.value = regRes.data.skills || []
  } catch (e) {
    console.warn('skill-registry 加载失败:', e.message)
    return
  }
  const results = await Promise.allSettled(
    skills.value.map(s =>
      axios.get(`${API}/stats/${s.key}-sync-progress`, { timeout: 15000 })
        .then(r => ({ key: s.key, data: r.data || {} }))
    )
  )
  const newMap = {}
  for (const r of results) {
    if (r.status === 'fulfilled' && r.value.data) {
      newMap[r.value.key] = r.value.data
    }
  }
  syncDataMap.value = newMap
}

// 轮询单个 skill
async function pollSkill(key) {
  try {
    const r = await axios.get(`${API}/stats/${key}-sync-progress`, { timeout: 10000 })
    if (r.data) {
      syncDataMap.value = { ...syncDataMap.value, [key]: r.data }
    }
  } catch (e) { /* silent */ }
}

async function loadData() {
  loading.value = true
  error.value = ''
  try {
    const healthRes = await axios.get(`${API}/stats/data-health`)
    data.value = healthRes.data || {}
  } catch (e) {
    console.warn('data-health 加载失败:', e.message)
  }
  await loadAllSkillProgress()
  error.value = ''
  loading.value = false
  await nextTick()
  renderDailyChart()
}

// 近30日数据量趋势图
function renderDailyChart() {
  const el = document.getElementById('dailyTrendChart')
  if (!el || !data.value.daily?.length) return
  if (dailyChart.value) { dailyChart.value.dispose(); dailyChart.value = null }
  const chart = markRaw(echarts.init(el, getGovPriceTheme()))
  dailyChart.value = chart

  const buckets = data.value.daily
  const labels = buckets.map(b => b.date.slice(5))
  const values = buckets.map(b => b.count)
  const isZero = v => v === 0

  chart.setOption({
    tooltip: {
      trigger: 'axis',
      backgroundColor: 'var(--text)', borderColor: 'var(--text-2)', borderWidth: 1,
      textStyle: { color: 'var(--border-strong)', fontSize: 12 },
      formatter: p => `<b style="color:var(--primary-soft)">${p[0].name}</b><br/>数量: <b style="color:var(--success-light)">${p[0].value.toLocaleString()}</b>`
    },
    grid: { left: '3%', right: '3%', bottom: '10%', top: '14%', containLabel: true },
    xAxis: {
      type: 'category', data: labels,
      axisLabel: { color: 'var(--text-2)', fontSize: 10, rotate: 45, interval: 0 },
      axisLine: { lineStyle: { color: 'var(--text-2)' } },
      axisTick: { show: false },
      splitLine: { show: false }
    },
    yAxis: {
      name: '文档数', nameTextStyle: { color: 'var(--text-2)', fontSize: 10, padding: [0, 0, 0, 30] },
      type: 'value',
      axisLabel: { color: 'var(--text-2)', fontSize: 10 },
      splitLine: { lineStyle: { color: 'var(--border)', type: 'dashed' } }
    },
    series: [{
      type: 'bar', data: values,
      itemStyle: {
        color: p => isZero(p.value) ? 'var(--text)' : new echarts.graphic.LinearGradient(0, 0, 0, 1, [
          { offset: 0, color: 'var(--primary)' },
          { offset: 1, color: 'var(--indigo)' }
        ])
      },
      barMaxWidth: 20,
      emphasis: {
        itemStyle: { color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
          { offset: 0, color: 'var(--primary)' },
          { offset: 1, color: 'var(--primary-soft-light)' }
        ]) }
      }
    }],
  })
  if (dailyResizeHandler) window.removeEventListener('resize', dailyResizeHandler)
  dailyResizeHandler = () => chart.resize()
  window.addEventListener('resize', dailyResizeHandler)
}

const dailyChart = ref(null)
let dailyResizeHandler = null

onMounted(async () => {
  await loadData()
  skills.value.forEach((s, i) => {
    const interval = 5000 + (i * 1700)
    pollTimers.value[s.key] = setInterval(() => pollSkill(s.key), interval)
  })
})

// ==================== 工具函数 ====================

function formatDur(sec) {
  if (!sec) return '—'
  if (sec < 60) return Math.round(sec) + 's'
  if (sec < 3600) return Math.round(sec / 60) + 'm'
  return (sec / 3600).toFixed(1) + 'h'
}

onUnmounted(() => {
  // 清理所有 skill 轮询 timer
  Object.values(pollTimers.value).forEach(t => t && clearInterval(t))
  pollTimers.value = {}
  if (dailyResizeHandler) window.removeEventListener('resize', dailyResizeHandler)
})
</script>

<style scoped>
/* === 亮色版 === */
.health-page {
  display: flex;
  flex-direction: column;
  gap: 16px;
  padding: 16px 20px;
  padding-top: 16px;
  min-height: 100vh;
  background: linear-gradient(180deg, var(--bg) 0%, var(--surface-2) 100%);
  position: static;
  z-index: 10;
  box-sizing: border-box;
  color: var(--surface);
}

/* ===== 顶部汇总指标卡 ===== */
.health-cards {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 14px;
}
.stat-card {
  background: var(--surface);
  border: 1px solid var(--border-strong);
  border-radius: 14px;
  padding: 0;
  overflow: hidden;
  box-shadow: 0 1px 2px rgba(var(--text-rgb), 0.04), 0 2px 6px rgba(var(--text-rgb), 0.03);
  transition: transform 0.2s, box-shadow 0.2s, border-color 0.2s;
  position: relative;
}
.stat-card:hover {
  transform: translateY(-2px);
  box-shadow: 0 6px 20px rgba(var(--text-rgb), 0.08), 0 2px 4px rgba(var(--text-rgb), 0.04);
  border-color: var(--text-2);
}
.stat-card-inner {
  padding: 18px 20px;
  display: flex;
  align-items: center;
  gap: 14px;
  position: relative;
}
.stat-icon {
  font-size: 24px;
  width: 44px;
  height: 44px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}
.stat-card-primary  .stat-icon { background: var(--primary-light); }
.stat-card-cyan     .stat-icon { background: var(--cyan-tint); }
.stat-card-warning  .stat-icon { background: var(--amber-tint); }
.stat-card-magenta  .stat-icon { background: var(--purple-tint); }

.stat-content { flex: 1; min-width: 0; }
.stat-label {
  font-size: 12px;
  color: var(--text-2);
  margin-bottom: 6px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.stat-num {
  font-size: 36px;
  font-weight: 800;
  color: var(--text);
  line-height: 1;
  font-family: ui-monospace, 'SF Mono', Consolas, 'Liberation Mono', monospace;
  display: block;
}

.stat-value {
  display: flex;
  align-items: baseline;
  gap: 4px;
}
.stat-unit {
  font-size: 13px;
  font-weight: 400;
  margin-left: 4px;
  color: var(--text-2);
}
.stat-glow {
  position: absolute;
  top: 0;
  right: 0;
  width: 80px;
  height: 60px;
  border-radius: 0 14px 0 0;
  pointer-events: none;
}
.stat-card-primary .stat-glow { background: radial-gradient(ellipse at top right, rgba(var(--primary-rgb), 0.10), transparent 70%); }
.stat-card-cyan    .stat-glow { background: radial-gradient(ellipse at top right, rgba(6, 182, 212, 0.10),  transparent 70%); }
.stat-card-warning .stat-glow { background: radial-gradient(ellipse at top right, rgba(245, 158, 11, 0.10), transparent 70%); }
.stat-card-magenta .stat-glow { background: radial-gradient(ellipse at top right, rgba(var(--purple-rgb), 0.10), transparent 70%); }

.stat-card-warning.stat-alert { border-color: var(--warning-dark); }
.stat-card-warning.stat-alert .stat-value { color: var(--warning-dark); }
.stat-card-magenta.stat-alert { border-color: var(--purple); }
.stat-card-magenta.stat-alert .stat-value { color: var(--purple); }

.text-up   { color: var(--success-dark) !important; }
.text-down { color: var(--danger) !important; }

/* ===== 图表面板 ===== */
.chart-panel {
  background: var(--surface);
  border: 1px solid var(--border-strong);
  border-radius: 14px;
  padding: 18px 20px;
  box-shadow: 0 1px 2px rgba(var(--text-rgb), 0.04), 0 2px 6px rgba(var(--text-rgb), 0.03);
  flex-shrink: 0;
}
.panel-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
}
.panel-title-row {
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
.panel-dot-blue { background: var(--primary); }
.panel-title { font-size: 14px; font-weight: 700; color: var(--text); }
.chart-legend { display: flex; gap: 16px; }
.legend-item { display: flex; align-items: center; gap: 6px; font-size: 12px; color: var(--text-2); }
.legend-dot { width: 10px; height: 10px; border-radius: 2px; background: linear-gradient(135deg, var(--primary), var(--indigo)); }
.chart-area { width: 100%; height: 320px; }

/* ===== 省份同步卡片网格 ===== */
.sync-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 14px;
}

/* 卡片样式已全部迁出到 components/SyncCard.vue */

/* 全局展开/收起 工具条 */
.sync-grid-tools {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 4px 10px;
  margin-top: 6px;
}
.sync-grid-hint {
  font-size: 11px;
  color: var(--text-2);
}
.sync-grid-toggle {
  font-size: 12px;
  padding: 5px 12px;
  border-radius: 6px;
  border: 1px solid var(--sky-tint-2);
  background: var(--info-tint);
  color: var(--primary-dark);
  cursor: pointer;
  font-weight: 600;
  transition: all 0.15s;
  font-family: inherit;
}
.sync-grid-toggle:hover {
  background: var(--sky-tint);
  border-color: var(--primary);
  color: var(--sky-dark);
}

</style>
