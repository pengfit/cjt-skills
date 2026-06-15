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
    <div v-if="error" class="health-error">{{ error }}</div>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted, nextTick, computed, watch } from 'vue'
import axios from 'axios'
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
/* ===== 整体布局 ===== */
.health-page {
  display: flex;
  flex-direction: column;
  gap: 16px;
  padding: 16px 20px;
  padding-top: 16px;
  min-height: 100vh;
  background: linear-gradient(180deg, #0c1222 0%, #111827 100%);
  position: static;   /* was fixed — let it flow with document */
  z-index: 10;
  box-sizing: border-box;
}

/* ===== 顶部工具栏 ===== */

/* ===== 四个汇总指标卡 ===== */
.health-cards {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 14px;
}
.stat-card {
  background: rgba(15,23,42,0.85);
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  border: 1px solid rgba(255,255,255,0.08);
  border-radius: 14px;
  padding: 0;
  overflow: hidden;
  box-shadow: 0 8px 32px rgba(0,0,0,0.25);
  transition: transform var(--transition), box-shadow var(--transition), border-color var(--transition);
  position: relative;
}
.stat-card:hover {
  transform: translateY(-2px);
  box-shadow: 0 12px 40px rgba(0,0,0,0.35), 0 0 0 1px rgba(56,189,248,0.06);
  border-color: rgba(56,189,248,0.18);
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
.stat-card-primary .stat-icon { background: rgba(59,130,246,0.15); }
.stat-card-cyan .stat-icon { background: rgba(6,182,212,0.15); }
.stat-card-warning .stat-icon { background: rgba(245,158,11,0.15); }
.stat-card-magenta .stat-icon { background: rgba(168,85,247,0.15); }

.stat-content { flex: 1; min-width: 0; }
.stat-label {
  font-size: 12px;
  color: var(--text-3);
  margin-bottom: 6px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.stat-num {
  font-size: 36px;
  font-weight: 800;
  color: var(--primary);
  line-height: 1;
  font-family: ui-monospace, 'SF Mono', Consolas, 'Liberation Mono', monospace;
  text-shadow: 0 0 20px rgba(56,189,248,0.4);
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
  color: #475569;
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
.stat-card-primary .stat-glow { background: radial-gradient(ellipse at top right, rgba(59,130,246,0.12), transparent 70%); }
.stat-card-cyan .stat-glow { background: radial-gradient(ellipse at top right, rgba(6,182,212,0.12), transparent 70%); }
.stat-card-warning .stat-glow { background: radial-gradient(ellipse at top right, rgba(245,158,11,0.12), transparent 70%); }
.stat-card-magenta .stat-glow { background: radial-gradient(ellipse at top right, rgba(168,85,247,0.12), transparent 70%); }

.stat-card-warning.stat-alert { border-color: rgba(245,158,11,0.3); }
.stat-card-warning.stat-alert .stat-value { color: var(--status-warn); }
.stat-card-magenta.stat-alert { border-color: rgba(168,85,247,0.3); }
.stat-card-magenta.stat-alert .stat-value { color: #c084fc; }

.text-up { color: var(--status-ok) !important; }
.text-down { color: var(--status-alert) !important; }

/* ===== 图表面板 ===== */
.chart-panel {
  background: rgba(15,23,42,0.85);
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  border: 1px solid rgba(255,255,255,0.08);
  border-radius: 14px;
  padding: 18px 20px;
  box-shadow: 0 8px 32px rgba(0,0,0,0.25);
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
.panel-dot-blue { background: var(--primary); box-shadow: 0 0 8px rgba(56,189,248,0.5); }
.panel-title { font-size: 14px; font-weight: 700; color: #e2e8f0; }
.chart-legend { display: flex; gap: 16px; }
.legend-item { display: flex; align-items: center; gap: 6px; font-size: 12px; color: var(--text-3); }
.legend-dot { width: 10px; height: 10px; border-radius: 2px; background: linear-gradient(135deg, var(--primary), #6366f1); }
.chart-area { width: 100%; height: 320px; }

/* ===== 省份同步卡片网格 ===== */
.sync-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 14px;
}

/* 6 城大卡详情默认收起：仅显示 header + meta（总览信息） */
.sync-card-body { display: none; }
.health-page.show-card-detail .sync-card-body { display: block; }
.sync-card.show-card-detail,
.health-page.show-card-detail .sync-card { /* keep existing styles intact */ }

/* 收起状态下，body 隐藏，卡片 height 自动收缩 */
.sync-card {
  transition: box-shadow 0.2s, border-color 0.2s;
}
.sync-card-body {
  transition: max-height 0.3s ease;
}

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
  color: var(--text-3);
}
.sync-grid-toggle {
  font-size: 12px;
  padding: 5px 12px;
  border-radius: 6px;
  border: 1px solid rgba(56,189,248,0.25);
  background: rgba(56,189,248,0.06);
  color: var(--primary);
  cursor: pointer;
  font-weight: 600;
  transition: all 0.15s;
  font-family: inherit;
}
.sync-grid-toggle:hover {
  background: rgba(56,189,248,0.14);
  border-color: var(--primary);
}

/* ===== 同步卡片 ===== */
.sync-card {
  background: rgba(15,23,42,0.85);
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  border: 1px solid rgba(255,255,255,0.08);
  border-radius: 14px;
  padding: 0;
  overflow: hidden;
  box-shadow: 0 8px 32px rgba(0,0,0,0.2);
  transition: transform var(--transition), box-shadow var(--transition), border-color var(--transition);
  display: flex;
  flex-direction: row;
  position: relative;
  min-height: 0;
}
.sync-card:hover {
  transform: translateY(-2px);
  box-shadow: 0 12px 40px rgba(0,0,0,0.3), 0 0 0 1px rgba(56,189,248,0.06);
  border-color: rgba(56,189,248,0.2);
}
.sync-card-running {
  border-color: rgba(56,189,248,0.2);
  box-shadow: 0 8px 32px rgba(0,0,0,0.2), 0 0 20px rgba(56,189,248,0.08);
}

/* 左侧彩色边条 */
.sync-card-bar {
  width: 4px;
  flex-shrink: 0;
  border-radius: 14px 0 0 14px;
}
.sync-bar-xa { background: linear-gradient(180deg, #3b82f6, #1d4ed8); }
.sync-bar-sc { background: linear-gradient(180deg, #06b6d4, #0891b2); }
.sync-bar-rz { background: linear-gradient(180deg, #10b981, #059669); }
.sync-bar-jn { background: linear-gradient(180deg, #8b5cf6, #7c3aed); }
.sync-bar-cq { background: linear-gradient(180deg, var(--status-warn), #d97706); }
.sync-bar-hn { background: linear-gradient(180deg, #ec4899, #be185d); }   /* 河南：玫红 */
.sync-bar-hz { background: linear-gradient(180deg, #f59e0b, #d97706); }   /* 菏泽：琥珀 */

.sync-card-content {
  flex: 1;
  padding: 14px 16px;
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.sync-card-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 2px;
  flex-wrap: wrap;
}
.sync-card-title-row {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}
.sync-province-tag {
  font-size: 11px;
  font-weight: 700;
  padding: 2px 8px;
  border-radius: 4px;
  letter-spacing: 0.5px;
  color: #fff;
}
.tag-xa { background: linear-gradient(135deg, #3b82f6, #1d4ed8); }
.tag-sc { background: linear-gradient(135deg, #06b6d4, #0891b2); }
.tag-rz { background: linear-gradient(135deg, #10b981, #059669); }
.tag-jn { background: linear-gradient(135deg, #8b5cf6, #7c3aed); }
.tag-cq { background: linear-gradient(135deg, var(--status-warn), #d97706); }
.tag-hn { background: linear-gradient(135deg, #ec4899, #be185d); }
.tag-hz { background: linear-gradient(135deg, #f59e0b, #d97706); }

.sync-card-title { font-size: 14px; font-weight: 700; color: #e2e8f0; }
.sync-badges { display: flex; gap: 5px; flex-wrap: wrap; }
.sync-card-meta { font-size: 11px; color: #475569; margin-bottom: 12px; }

/* 卡片主体 */
.sync-card-body {
  display: flex;
  gap: 14px;
  align-items: stretch;
  flex: 1;
  min-height: 0;
  overflow: hidden;
}

/* 左侧圆环信息列 */
.sync-info-col {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 5px;
  flex-shrink: 0;
  width: 90px;
}
.ring { width: 76px; height: 76px; }
.ring-bg { fill: none; stroke: rgba(255,255,255,0.06); stroke-width: 8; }
.ring-fill {
  fill: none;
  stroke-width: 8;
  stroke-linecap: round;
  transform: rotate(-90deg);
  transform-origin: 50% 50%;
  transition: stroke-dashoffset 0.6s ease;
}
.ring-xa { stroke: #3b82f6; }
.ring-sc { stroke: #06b6d4; }
.ring-rz { stroke: #10b981; }
.ring-jn { stroke: #8b5cf6; }
.ring-cq { stroke: var(--status-warn); }
.ring-hn { stroke: #ec4899; }
.ring-hz { stroke: #f59e0b; }
.ring-pct { font-size: 18px; font-weight: 700; fill: #f1f5f9; font-family: ui-monospace, 'SF Mono', Consolas, 'Liberation Mono', monospace; }
.ring-sub { font-size: 10px; fill: var(--text-3); }
.sync-status-row { display: flex; justify-content: center; }
.sync-doc-count { font-size: 11px; color: #475569; text-align: center; }

/* 右侧列表列 */
.sync-list-col {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  min-height: 0;
  /* fill parent height so pagination sticks to bottom */
  height: 100%;
}
.list-header {
  display: grid;
  grid-template-columns: 1fr 1fr 1fr 1fr;
  gap: 6px;
  padding: 0 4px 6px;
  border-bottom: 1px solid rgba(255,255,255,0.06);
  font-size: 11px;
  font-weight: 600;
  color: #475569;
  flex-shrink: 0;
}
.list-scroll {
  flex: 1;
  overflow-y: auto;
  min-height: 0;
  /* no fixed max-height — fills available space */
}
.list-scroll::-webkit-scrollbar { width: 3px; }
.list-scroll::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.1); border-radius: 2px; }
.list-scroll::-webkit-scrollbar-track { background: transparent; }
.list-row {
  display: grid;
  grid-template-columns: 1fr 1fr 1fr 1fr;
  gap: 6px;
  align-items: center;
  padding: 5px 4px;
  border-bottom: 1px solid rgba(255,255,255,0.03);
  font-size: 12px;
  border-radius: 4px;
  transition: background 0.15s;
}
.list-row:nth-child(even) { background: rgba(255,255,255,0.02); }
.list-row:last-child { border-bottom: none; }
.list-row.row-active { background: rgba(56,189,248,0.08) !important; }
.list-name { font-weight: 500; color: #cbd5e1; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.list-num, .list-date { font-size: 11px; color: #475569; white-space: nowrap; }

/* 分页 - 吸底 */
.list-pagination {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 6px 8px;
  border-top: 1px solid rgba(255,255,255,0.04);
  flex-shrink: 0;
  background: rgba(15,23,42,0.7);
  border-radius: 0 0 8px 8px;
}
.pg-btn {
  background: rgba(255,255,255,0.05);
  border: 1px solid rgba(255,255,255,0.08);
  border-radius: 4px;
  padding: 2px 8px;
  font-size: 12px;
  color: var(--text-3);
  cursor: pointer;
  transition: all 0.15s;
}
.pg-btn:hover { background: rgba(255,255,255,0.1); color: #e2e8f0; }
.pg-btn:disabled { opacity: 0.3; cursor: not-allowed; }
.pg-info { font-size: 12px; color: #475569; }

/* 进度条 */
.progress-wrap { margin-top: 8px; }
.progress-bar { height: 5px; background: rgba(255,255,255,0.06); border-radius: 3px; overflow: hidden; }
.progress-fill {
  height: 100%;
  border-radius: 3px;
  transition: width 0.4s ease;
}
.progress-fill-xa { background: linear-gradient(90deg, #3b82f6, #60a5fa); }
.progress-fill-sc { background: linear-gradient(90deg, #06b6d4, #22d3ee); }
.progress-fill-rz { background: linear-gradient(90deg, #10b981, var(--status-ok)); }
.progress-fill-jn { background: linear-gradient(90deg, #8b5cf6, var(--purple)); }
.progress-fill-cq { background: linear-gradient(90deg, var(--status-warn), var(--status-warn)); }
.progress-info {
  display: flex;
  gap: 10px;
  font-size: 10px;
  color: #475569;
  margin-top: 3px;
}
.pct-active { color: #60a5fa; font-weight: 600; }

/* ===== 标签 ===== */
.badge {
  font-size: 10px;
  font-weight: 500;
  padding: 2px 6px;
  border-radius: 4px;
  white-space: nowrap;
  letter-spacing: 0.2px;
}
.badge-blue { background: rgba(59,130,246,0.15); color: #60a5fa; border: 1px solid rgba(59,130,246,0.2); }
.badge-green { background: rgba(16,185,129,0.15); color: var(--status-ok); border: 1px solid rgba(16,185,129,0.2); }
.badge-yellow { background: rgba(245,158,11,0.15); color: var(--status-warn); border: 1px solid rgba(245,158,11,0.2); }
.badge-red { background: rgba(239,68,68,0.15); color: var(--status-alert); border: 1px solid rgba(239,68,68,0.2); }
.badge-gray { background: rgba(255,255,255,0.05); color: #475569; border: 1px solid rgba(255,255,255,0.06); }

/* ===== 加载/错误 ===== */
.health-loading {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 12px;
  padding: 20px;
  color: #475569;
  font-size: 13px;
}
.health-error {
  text-align: center;
  padding: 20px;
  color: var(--status-alert);
  font-size: 13px;
}
.loading-spinner {
  width: 20px;
  height: 20px;
  border: 2px solid rgba(255,255,255,0.1);
  border-top-color: #60a5fa;
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}
@keyframes spin {
  to { transform: rotate(360deg); }
}

/* 6 城大卡详情默认收起（必须放在最后以覆盖同选择器） */
.sync-card-body { display: none; }
.health-page.show-card-detail .sync-card-body { display: flex; }
</style>
