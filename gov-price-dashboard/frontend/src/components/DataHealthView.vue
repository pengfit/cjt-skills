<template>
  <div class="health-page">

    <!-- 四个汇总指标卡（以抓取 skill 为中心） -->
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
          <div class="stat-icon">🧩</div>
          <div class="stat-content">
            <div class="stat-label">抓取任务</div>
            <div class="stat-value"><span class="stat-num">{{ skillStats.total }}</span><span class="stat-unit">个</span></div>
          </div>
          <div class="stat-glow"></div>
        </div>
      </div>
      <div class="stat-card stat-card-warning">
        <div class="stat-card-inner">
          <div class="stat-icon">⏱</div>
          <div class="stat-content">
            <div class="stat-label">平均新鲜度</div>
            <div class="stat-value">
              <span class="stat-num">{{ skillStats.avgFreshness }}</span>
              <span class="stat-unit">天前</span>
            </div>
          </div>
          <div class="stat-glow"></div>
        </div>
      </div>
      <div class="stat-card stat-card-magenta" :class="{ 'stat-alert': anomalyStats.total > 0 }">
        <div class="stat-card-inner">
          <div class="stat-icon">⚠</div>
          <div class="stat-content">
            <div class="stat-label">异常告警</div>
            <div class="stat-value">
              <span class="stat-num">{{ anomalyStats.total }}</span>
              <span class="stat-unit">个 skill 有异常</span>
            </div>
          </div>
          <div class="stat-glow"></div>
        </div>
      </div>
    </div>

    <!-- 技能数据健康表（以 skill 为中心） -->
    <div class="chart-panel">
      <div class="panel-header">
        <div class="panel-title-row">
          <span class="panel-dot panel-dot-purple"></span>
          <span class="panel-title">抓取任务数据健康</span>
        </div>
        <div class="chart-legend">
          <span class="legend-item"><span class="legend-dot legend-fresh"></span>新鲜</span>
          <span class="legend-item"><span class="legend-dot legend-stale"></span>停滞</span>
          <span class="legend-item"><span class="legend-dot legend-down"></span>停更</span>
          <button class="rule-toggle" @click="showRule = !showRule">
            {{ showRule ? '▴ 收起规则' : '▾ 规则说明' }}
          </button>
        </div>
      </div>
      <div v-if="showRule" class="rule-panel">
        <div class="rule-grid">
          <div class="rule-section">
            <h5>健康度（按距今 + 同步状态）</h5>
            <div class="rule-row">
              <span class="health-pill pill-fresh">✓ 新鲜</span>
              <span class="rule-desc">距今 <strong>≤ 3 天</strong>，同步状态正常</span>
            </div>
            <div class="rule-row">
              <span class="health-pill pill-warn">● 一般</span>
              <span class="rule-desc">距今 <strong>4–7 天</strong>，建议关注</span>
            </div>
            <div class="rule-row">
              <span class="health-pill pill-stale">⚠ 停滞</span>
              <span class="rule-desc">距今 <strong>&gt; 7 天</strong>，超一周未抓取</span>
            </div>
            <div class="rule-row">
              <span class="health-pill pill-stale">⚠ 中断</span>
              <span class="rule-desc">同步状态 = <code>interrupted</code></span>
            </div>
            <div class="rule-row">
              <span class="health-pill pill-down">● 停更</span>
              <span class="rule-desc">同步状态 = <code>down</code></span>
            </div>
            <div class="rule-row">
              <span class="health-pill pill-down">✗ 出错</span>
              <span class="rule-desc">同步状态 = <code>error</code></span>
            </div>
            <div class="rule-row">
              <span class="health-pill pill-gray">— 无记录</span>
              <span class="rule-desc">缺失 <code>last_updated</code> 字段</span>
            </div>
          </div>
          <div class="rule-section">
            <h5>规格解析率（按 category 平均 rate）</h5>
            <div class="rule-row">
              <span class="rate-pill rate-good">≥ 90%</span>
              <span class="rule-desc"><strong>良好</strong>，解析规则覆盖充分</span>
            </div>
            <div class="rule-row">
              <span class="rate-pill rate-warn">≥ 70%</span>
              <span class="rule-desc"><strong>一般</strong>，部分分类规则待补</span>
            </div>
            <div class="rule-row">
              <span class="rate-pill rate-bad">&lt; 70%</span>
              <span class="rule-desc"><strong>落后</strong>，建议补全规格规则</span>
            </div>
            <div class="rule-meta">
              数据源：<code>/api/stats/spec-quality?city={skill.key}</code>，
              取 <code>coverage</code> 数组所有 category 的 <code>rate</code> 算术平均
            </div>
          </div>
          <div class="rule-section">
            <h5>异常告警（30 日趋势）</h5>
            <div class="rule-row">
              <span class="legend-dot legend-down inline"></span>
              <span class="rule-desc"><strong>突增</strong>：日增量 &gt; 30 日均值的 <strong>2 倍</strong>（红色）</span>
            </div>
            <div class="rule-row">
              <span class="legend-dot legend-warn inline"></span>
              <span class="rule-desc"><strong>突减</strong>：日增量 &lt; 30 日均值的 <strong>0.3 倍</strong>（橙色）</span>
            </div>
            <div class="rule-row">
              <span class="legend-dot legend-fresh inline"></span>
              <span class="rule-desc"><strong>正常</strong>：落在 [0.3×, 2×] 区间内（蓝色）</span>
            </div>
            <div class="rule-meta">
              异常柱用红/橙标色，markPoint 标 ↑/↓ 提示；图中虚线为 30 日均值参考线
            </div>
          </div>
        </div>
      </div>
      <div class="health-table-scroll">
        <table class="health-table">
          <thead>
            <tr>
              <th>抓取任务</th>
              <th>拼音</th>
              <th>覆盖范围</th>
              <th class="th-num">文档总数</th>
              <th>最后抓取</th>
              <th class="th-num">距今</th>
              <th>健康度</th>
              <th class="th-num">规格解析率</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="s in skillHealthRows" :key="s.key" :class="rowClass(s)">
              <td>
                <span class="skill-tag" :class="`tag-${s.barClass}`">{{ s.label }}</span>
              </td>
              <td class="cell-pinyin">{{ s.key }}</td>
              <td class="cell-scope">{{ s.scope }}</td>
              <td class="cell-num">{{ (s.total_docs || 0).toLocaleString() }}</td>
              <td class="cell-time">{{ s.last_updated || '—' }}</td>
              <td class="cell-num">{{ s.daysAgo === null ? '—' : s.daysAgo + ' 天' }}</td>
              <td>
                <span v-if="s.status === 'error'" class="health-pill pill-down">✗ 出错</span>
                <span v-else-if="s.status === 'interrupted'" class="health-pill pill-stale">⚠ 中断</span>
                <span v-else-if="s.status === 'down'" class="health-pill pill-down">● 停更</span>
                <span v-else-if="s.daysAgo === null" class="health-pill pill-gray">— 无记录</span>
                <span v-else-if="s.daysAgo > 7" class="health-pill pill-stale">⚠ 停滞</span>
                <span v-else-if="s.daysAgo > 3" class="health-pill pill-warn">● 一般</span>
                <span v-else class="health-pill pill-fresh">✓ 新鲜</span>
              </td>
              <td class="cell-num">
                <span v-if="s.spec_rate === null" class="cell-muted">—</span>
                <span v-else :class="rateClass(s.spec_rate)" class="rate-pill">{{ s.spec_rate }}%</span>
                <span v-if="s.spec_total" class="cell-muted cell-muted-small">({{ s.spec_total }} 类)</span>
              </td>
            </tr>
            <tr v-if="!skillHealthRows.length">
              <td colspan="8" class="cell-empty">尚无 skill 数据</td>
            </tr>
          </tbody>
        </table>
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
          <span class="legend-item"><span class="legend-dot legend-fresh"></span>正常</span>
          <span class="legend-item"><span class="legend-dot legend-warn"></span>突减</span>
          <span class="legend-item"><span class="legend-dot legend-down"></span>突增</span>
        </div>
      </div>
      <div id="dailyTrendChart" class="chart-area"></div>
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
import { ref, onMounted, onUnmounted, nextTick, computed } from 'vue'
import axios from 'axios'
import { getGovPriceTheme } from '../composables/useEchartsTheme'
import { markRaw } from 'vue'
import * as echarts from 'echarts'
import SkeletonCard from './SkeletonCard.vue'
import EmptyState from './EmptyState.vue'

const API = import.meta.env.VITE_API_URL || '/api'
const loading = ref(false)
const error = ref('')
const data = ref({
  total_docs: 0, province_count: 0,
  daily: [], provinces: []
})

// 以 skill 为中心的数据
const skills = ref([])
const syncDataMap = ref({})
const qualityMap = ref({})  // skill key -> { avg_rate, total_categories, lowest_category }

const SCOPE_MAP = {
  xian: '6 区县',
  sichuan: '21 地市',
  chongqing: '35 区县',
  jinan: '41 分类目录',
  rizhao: '3 类别',
  heze: '期刊',
  henan: '18 地市 / 期刊',
}
const BAR_CLASS_MAP = {
  xian: 'xa', sichuan: 'sc', chongqing: 'cq', jinan: 'jn',
  rizhao: 'rz', heze: 'hz', henan: 'hn',
}

// 计算每行数据（合并 skill 配置 + 同步进度 + 规格质量）
const skillHealthRows = computed(() => {
  return skills.value.map(s => {
    const sync = syncDataMap.value[s.key] || {}
    const quality = qualityMap.value[s.key] || {}
    const lastUpdated = sync.last_updated || ''
    const daysAgo = lastUpdated ? daysSince(lastUpdated) : null
    return {
      key: s.key,
      label: s.label || s.key,
      barClass: BAR_CLASS_MAP[s.key] || 'xa',
      scope: SCOPE_MAP[s.key] || s.province || '—',
      total_docs: sync.total_docs || 0,
      last_updated: lastUpdated ? lastUpdated.replace('T', ' ').slice(0, 16) : '',
      daysAgo,
      status: sync.status || '',
      spec_rate: quality.avg_rate ?? null,
      spec_total: quality.total_categories ?? 0,
    }
  })
})

// 健康度规则说明面板（默认收起）
const showRule = ref(false)

const skillStats = computed(() => {
  const rows = skillHealthRows.value
  const total = rows.length
  const daysList = rows.filter(r => r.daysAgo !== null).map(r => r.daysAgo)
  const avg = daysList.length ? Math.round(daysList.reduce((a, b) => a + b, 0) / daysList.length) : '—'
  const stale = rows.filter(r => r.daysAgo !== null && r.daysAgo > 7).length
  return { total, avgFreshness: avg, staleCount: stale }
})

// 异常告警统计（停滞 + 同步错误 + 突增/突减）
const anomalyStats = computed(() => {
  const rows = skillHealthRows.value
  const daily = data.value.daily || []
  const anomalies = detectAnomalies(daily)
  let stale = 0, errored = 0, anomalyCount = 0
  for (const r of rows) {
    let hasIssue = false
    if (r.daysAgo !== null && r.daysAgo > 7) { stale++; hasIssue = true }
    if (r.status === 'error' || r.status === 'interrupted') { errored++; hasIssue = true }
    if (hasIssue) anomalyCount++
  }
  return { total: anomalyCount, stale, errored, dailyAnomalies: anomalies }
})

function detectAnomalies(buckets) {
  if (!buckets?.length) return { spikes: 0, drops: 0, latest: null }
  const values = buckets.map(b => b.count).filter(v => v > 0)
  if (values.length < 3) return { spikes: 0, drops: 0, latest: null }
  const avg = values.reduce((a, b) => a + b, 0) / values.length
  let spikes = 0, drops = 0, latest = null
  for (let i = 0; i < buckets.length; i++) {
    const v = buckets[i].count
    if (v === 0 || avg === 0) continue
    const ratio = v / avg
    const kind = ratio > 2 ? 'spike' : (ratio < 0.3 ? 'drop' : null)
    if (kind) {
      if (kind === 'spike') spikes++; else drops++
      if (i === buckets.length - 1 || (i === buckets.length - 2 && buckets[buckets.length-1].count === 0)) {
        latest = { date: buckets[i].date, kind, ratio: Math.round(ratio * 10) / 10 }
      }
    }
  }
  return { spikes, drops, latest }
}

function daysSince(ts) {
  if (!ts) return null
  const d = new Date(ts)
  if (isNaN(d.getTime())) return null
  const diff = Date.now() - d.getTime()
  return Math.floor(diff / 86400000)
}

function rowClass(row) {
  if (row.status === 'down' || row.status === 'error') return 'row-down'
  if (row.daysAgo !== null && row.daysAgo > 7) return 'row-stale'
  if (row.daysAgo !== null && row.daysAgo > 3) return 'row-warn'
  return 'row-fresh'
}

function rateClass(rate) {
  if (rate >= 90) return 'rate-good'
  if (rate >= 70) return 'rate-warn'
  return 'rate-bad'
}

async function loadData() {
  loading.value = true
  error.value = ''
  try {
    const [healthRes, regRes] = await Promise.allSettled([
      axios.get(`${API}/stats/data-health`),
      axios.get(`${API}/skill-registry`),
    ])
    if (healthRes.status === 'fulfilled') {
      data.value = healthRes.value.data || {}
    } else {
      console.warn('data-health 加载失败:', healthRes.reason?.message)
    }
    if (regRes.status === 'fulfilled') {
      skills.value = regRes.value.data?.skills || []
    }
    // 并行拉取每个 skill 的同步进度 + 规格质量
    if (skills.value.length) {
      const [syncResults, qualityResults] = await Promise.all([
        Promise.allSettled(
          skills.value.map(s =>
            axios.get(`${API}/stats/${s.key}-sync-progress`, { timeout: 15000 })
              .then(r => ({ key: s.key, data: r.data || {} }))
          )
        ),
        Promise.allSettled(
          skills.value.map(s =>
            axios.get(`${API}/stats/spec-quality`, {
              params: { city: s.key, _sample: false, sample_size: 0 },
              timeout: 20000,
            }).then(r => ({ key: s.key, coverage: r.data?.coverage || [] }))
              .catch(() => ({ key: s.key, coverage: [] }))
          )
        ),
      ])
      const newMap = {}
      for (const r of syncResults) {
        if (r.status === 'fulfilled' && r.value.data) {
          newMap[r.value.key] = r.value.data
        }
      }
      syncDataMap.value = newMap
      const qMap = {}
      for (const r of qualityResults) {
        if (r.status === 'fulfilled') {
          const cov = r.value.coverage || []
          const avg = cov.length ? Math.round(cov.reduce((a, b) => a + (b.rate || 0), 0) / cov.length * 10) / 10 : null
          qMap[r.value.key] = { avg_rate: avg, total_categories: cov.length }
        }
      }
      qualityMap.value = qMap
    }
  } catch (e) {
    console.warn('data-health 加载失败:', e.message)
  }
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
  // 计算异常点（>平均 2 倍 = spike 突增，<0.3 倍 = drop 突减）
  const nonZero = values.filter(v => v > 0)
  const avg = nonZero.length ? nonZero.reduce((a, b) => a + b, 0) / nonZero.length : 0
  const markPoints = []
  for (let i = 0; i < values.length; i++) {
    const v = values[i]
    if (v === 0 || avg === 0) continue
    const ratio = v / avg
    if (ratio > 2) markPoints.push({ idx: i, kind: 'spike', v, ratio })
    else if (ratio < 0.3) markPoints.push({ idx: i, kind: 'drop', v, ratio })
  }

  chart.setOption({
    tooltip: {
      trigger: 'axis',
      backgroundColor: 'rgba(255,255,255,0.98)', borderColor: '#cbd5e1', borderWidth: 1,
      textStyle: { color: '#0f172a', fontSize: 12 },
      formatter: p => {
        const i = p[0].dataIndex
        const v = values[i]
        const avgLine = avg > 0 ? `<br/>30日均: ${Math.round(avg).toLocaleString()}` : ''
        const ratio = avg > 0 ? (v / avg).toFixed(2) : '-'
        const flag = v > 0 && avg > 0 && (v / avg > 2 || v / avg < 0.3)
          ? `<br/><b style="color:${v/avg > 2 ? '#dc2626' : '#ea580c'}">${v/avg > 2 ? '↑ 突增' : '↓ 突减'} (×${ratio})</b>` : ''
        return `<b style="color:#3b82f6">${p[0].name}</b><br/>数量: <b style="color:#10b981">${v.toLocaleString()}</b>${avgLine}${flag}`
      }
    },
    grid: { left: '3%', right: '3%', bottom: '10%', top: '14%', containLabel: true },
    xAxis: {
      type: 'category', data: labels,
      axisLabel: { color: '#475569', fontSize: 10, rotate: 45, interval: 0 },
      axisLine: { lineStyle: { color: '#cbd5e1' } },
      axisTick: { show: false },
      splitLine: { show: false }
    },
    yAxis: {
      name: '文档数', nameTextStyle: { color: '#64748b', fontSize: 10, padding: [0, 0, 0, 30] },
      type: 'value',
      axisLabel: { color: '#64748b', fontSize: 10 },
      splitLine: { lineStyle: { color: '#e2e8f0', type: 'dashed' } }
    },
    series: [{
      type: 'bar', data: values,
      itemStyle: {
        color: p => {
          if (isZero(p.value)) return '#e2e8f0'
          if (avg > 0) {
            const ratio = p.value / avg
            if (ratio > 2) return '#dc2626'  // 突增 - 红
            if (ratio < 0.3) return '#ea580c'  // 突减 - 橙
          }
          return new echarts.graphic.LinearGradient(0, 0, 0, 1, [
            { offset: 0, color: '#2563eb' },
            { offset: 1, color: '#6366f1' }
          ])
        }
      },
      markLine: avg > 0 ? {
        silent: true,
        symbol: 'none',
        lineStyle: { color: '#94a3b8', type: 'dashed', width: 1 },
        label: { show: true, position: 'end', formatter: `均值 ${Math.round(avg).toLocaleString()}`, color: '#64748b', fontSize: 10 },
        data: [{ yAxis: avg }]
      } : undefined,
      markPoint: markPoints.length ? {
        symbol: 'pin',
        symbolSize: 32,
        data: markPoints.map(m => ({
          name: m.kind === 'spike' ? '突增' : '突减',
          value: m.kind === 'spike' ? '↑' : '↓',
          xAxis: m.idx,
          yAxis: m.v,
          itemStyle: { color: m.kind === 'spike' ? '#dc2626' : '#ea580c' }
        })),
        label: { color: '#fff', fontSize: 11, fontWeight: 700 }
      } : undefined,
      barMaxWidth: 20,
      emphasis: {
        itemStyle: { color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
          { offset: 0, color: '#2563eb' },
          { offset: 1, color: '#818cf8' }
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
})

onUnmounted(() => {
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

/* 7 城同步卡片已从本视图移除（避免与同步页抓取任务重复），卡片逻辑迁到 components/SyncCard.vue 仅供其他视图使用 */

/* ===== 技能数据健康表（以 skill 为中心）===== */
.legend-fresh { background: #16a34a; }
.legend-warn { background: #ea580c; }
.legend-stale { background: #ea580c; }
.legend-down  { background: #dc2626; }

.health-table-scroll {
  overflow-x: auto;
  max-height: 360px;
  overflow-y: auto;
}
.health-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12.5px;
}
.health-table thead th {
  position: sticky;
  top: 0;
  background: var(--surface);
  color: var(--text-2);
  font-weight: 500;
  text-align: left;
  padding: 8px 12px;
  border-bottom: 1px solid var(--border-strong);
  font-size: 11px;
  letter-spacing: 0.2px;
  z-index: 1;
}
.health-table th.th-num { text-align: right; }
.health-table tbody td {
  padding: 10px 12px;
  border-bottom: 1px solid var(--border);
  color: var(--text);
  vertical-align: middle;
}
.health-table tbody tr:last-child td { border-bottom: none; }
.health-table tbody tr:hover { background: var(--bg); }

.health-table .cell-num { text-align: right; font-variant-numeric: tabular-nums; }
.health-table .cell-time { color: var(--text-2); font-family: ui-monospace, 'SF Mono', Consolas, monospace; font-size: 11.5px; }
.health-table .cell-scope { color: var(--text-2); }
.health-table .cell-empty { text-align: center; color: var(--text-3); padding: 24px; }

.row-fresh td:first-child { border-left: 3px solid #16a34a; }
.row-warn  td:first-child { border-left: 3px solid #ea580c; }
.row-stale td:first-child { border-left: 3px solid #dc2626; }
.row-down  td:first-child { border-left: 3px solid #dc2626; background: rgba(220, 38, 38, 0.04); }

.skill-tag {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 4px;
  font-size: 12px;
  font-weight: 600;
  margin-right: 6px;
}
.tag-xa { background: #fff7ed; color: #c2410c; }
.tag-sc { background: #ecfdf5; color: #047857; }
.tag-cq { background: #fdf2f8; color: #be185d; }
.tag-jn { background: #eef2ff; color: #4338ca; }
.tag-rz { background: #f0fdfa; color: #0f766e; }
.tag-hz { background: #faf5ff; color: #7e22ce; }
.tag-hn { background: #fef2f2; color: #b91c1c; }

.skill-key {
  font-family: ui-monospace, 'SF Mono', Consolas, monospace;
  font-size: 11px;
  color: var(--text-3);
}

.cell-pinyin {
  font-family: ui-monospace, 'SF Mono', Consolas, monospace;
  font-size: 11.5px;
  color: var(--text-2);
  white-space: nowrap;
}

.health-pill {
  display: inline-block;
  padding: 1px 8px;
  border-radius: 10px;
  font-size: 11px;
  font-weight: 500;
  white-space: nowrap;
}
.pill-fresh { background: #d1fae5; color: #047857; }
.pill-warn  { background: #fed7aa; color: #c2410c; }
.pill-stale { background: #fee2e2; color: #b91c1c; }
.pill-down  { background: #fee2e2; color: #b91c1c; }
.pill-gray  { background: var(--text); color: var(--text-2); }

.rate-pill {
  display: inline-block;
  padding: 1px 8px;
  border-radius: 10px;
  font-size: 11px;
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}
.rate-good { background: #d1fae5; color: #047857; }
.rate-warn { background: #fed7aa; color: #c2410c; }
.rate-bad  { background: #fee2e2; color: #b91c1c; }

.cell-muted { color: var(--text-3); font-size: 11px; }
.cell-muted-small { font-size: 10px; margin-left: 2px; }

/* ===== 规则说明面板（折叠）===== */
.rule-toggle {
  font-size: 11px;
  font-weight: 600;
  padding: 3px 10px;
  border-radius: 4px;
  border: 1px solid var(--border);
  background: var(--surface);
  color: var(--primary);
  cursor: pointer;
  font-family: inherit;
  transition: all 0.15s;
}
.rule-toggle:hover {
  background: var(--primary-light);
  border-color: var(--primary);
}

.rule-panel {
  background: rgba(241, 245, 249, 0.6);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 14px 18px;
  margin-bottom: 12px;
  font-size: 12px;
}
.rule-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 18px;
}
.rule-section h5 {
  margin: 0 0 10px;
  font-size: 12px;
  font-weight: 700;
  color: var(--text);
  letter-spacing: 0.2px;
}
.rule-row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 4px 0;
  color: var(--text-2);
}
.rule-row strong { color: var(--text); font-weight: 700; }
.rule-row code {
  font-family: ui-monospace, 'SF Mono', Consolas, monospace;
  font-size: 11px;
  background: rgba(37, 99, 235, 0.08);
  color: var(--primary);
  padding: 1px 5px;
  border-radius: 3px;
}
.rule-desc { font-size: 12px; }
.rule-meta {
  margin-top: 8px;
  font-size: 11px;
  color: var(--text-3);
  line-height: 1.6;
  border-top: 1px dashed var(--border);
  padding-top: 6px;
}
.legend-dot.inline { display: inline-block; margin: 0; }

@media (max-width: 1100px) {
  .rule-grid { grid-template-columns: 1fr; }
}

</style>
