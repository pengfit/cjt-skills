<template>
  <div class="sync-card" :class="{ 'sync-card-running': isRunning }">
    <div class="sync-card-bar" :class="`sync-bar-${barClass}`"></div>
    <div class="sync-card-content">
      <div class="sync-card-header">
        <div class="sync-card-title-row">
          <span class="sync-province-tag" :class="`tag-${barClass}`">{{ skill.label || skill.key }}</span>
          <span class="sync-card-title">{{ skillTitle }}</span>
        </div>
        <div class="sync-badges">
          <span v-if="data.spot_check_ok === true" class="badge badge-green">✓ 抽检通过</span>
          <span v-else-if="data.spot_check_ok === false" class="badge badge-red">✗ 抽检异常</span>
          <span v-if="data.has_incremental === true" class="badge badge-green">{{ incrementalBadge }}</span>
          <span v-else-if="data.has_incremental === false && (data.last_sync_date || data.last_sync_period)" class="badge badge-blue">{{ data.last_sync_date || data.last_sync_period }}</span>
          <span v-else-if="data.has_incremental === false && latestPeriod" class="badge badge-blue">{{ latestPeriod }}</span>
        </div>
      </div>
      <div class="sync-card-meta">{{ formatDur(data.duration_sec) }} · {{ data.last_updated || '—' }}</div>

      <div class="sync-card-body">
        <!-- 左侧：进度环 + 状态 + 总文档数 -->
        <div class="sync-info-col">
          <svg class="ring" viewBox="0 0 100 100">
            <circle class="ring-bg" cx="50" cy="50" r="40" />
            <circle class="ring-fill" :class="`ring-${barClass}`" cx="50" cy="50" r="40"
              :stroke-dasharray="251.327"
              :stroke-dashoffset="251.327 * (1 - Math.min(ringPct / 100, 1))" />
            <text class="ring-pct" x="50" y="46" text-anchor="middle" font-size="18" font-weight="700">{{ ringDone }}/{{ ringTotal }}</text>
            <text class="ring-sub" x="50" y="64" text-anchor="middle" font-size="10">{{ isCompleted ? '全部完成' : '进行中' }}</text>
          </svg>
          <div class="sync-status-row">
            <span v-if="data.status === 'running'" class="badge badge-blue">● 同步中</span>
            <span v-else-if="data.status === 'completed' || data.status === 'ok'" class="badge badge-green">✓ 已完成</span>
            <span v-else-if="data.status === 'interrupted'" class="badge badge-yellow">⚠ 已中断</span>
            <span v-else-if="data.status === 'error'" class="badge badge-red">✗ 出错</span>
            <span v-else class="badge badge-gray">— 无记录</span>
          </div>
          <div class="sync-doc-count">{{ (data.total_docs || 0).toLocaleString() }} 条文档</div>
        </div>

        <!-- 右侧：详情列表 -->
        <div class="sync-list-col">
          <!-- 子项目视图（county / catalogue / tab） -->
          <template v-if="viewMode === 'subitem'">
            <div class="list-header mode-subitem">
              <span>{{ subitemHeader }}</span>
              <span>状态</span>
              <span>文档数</span>
              <span>更新时间</span>
            </div>
            <div class="list-scroll">
              <div class="list-row mode-subitem" v-for="(item, idx) in pagedDetails" :key="idx"
                :class="{ 'row-active': data.current_county === item.county || data.current_area === item.area || data.current_tab === item.tab_name || data.current_catalogue_name === item.catalogue_name }">
                <span class="list-name">{{ subitemName(item) }}</span>
                <span>
                  <span v-if="item.status === 'running'" class="badge badge-blue">●</span>
                  <span v-else-if="item.status === 'completed'" class="badge badge-green">✓</span>
                  <span v-else-if="item.status === 'interrupted'" class="badge badge-yellow">⚠</span>
                  <span v-else class="badge badge-gray">—</span>
                </span>
                <span class="list-num">{{ (item.docs_written || item.doc_count || 0).toLocaleString() }}</span>
                <span class="list-date">{{ (item.last_updated || '').slice(5, 16) || '—' }}</span>
              </div>
            </div>
            <div class="list-pagination" v-if="totalDetailPages > 1">
              <button class="pg-btn" @click="page--" :disabled="page <= 1">‹</button>
              <span class="pg-info">{{ page }}/{{ totalDetailPages }}</span>
              <button class="pg-btn" @click="page++" :disabled="page >= totalDetailPages">›</button>
            </div>
            <div class="progress-wrap" v-if="currentItemLabel && isRunning">
              <div class="progress-bar">
                <div class="progress-fill" :class="`progress-fill-${barClass}`" :style="{ width: getCurrentPercent().toFixed(1) + '%' }"></div>
              </div>
              <div class="progress-info">
                <span>{{ currentItemLabel }}</span>
                <span>{{ data.current_page }}/{{ data.total_pages }}页</span>
                <span class="pct-active">{{ getCurrentPercent().toFixed(1) }}%</span>
                <span>{{ (currentItemDocs || 0).toLocaleString() }}条</span>
              </div>
            </div>
          </template>

          <!-- 期期刊视图（heze / henan） -->
          <template v-else-if="viewMode === 'period_log'">
            <div class="list-header mode-period">
              <span>周期</span>
              <span>发布日期</span>
              <span>状态</span>
              <span>文档数</span>
            </div>
            <div class="list-scroll">
              <div class="list-row mode-period" v-for="(p, idx) in (data.period_details || []).slice(0, 20)" :key="idx">
                <span class="list-name">{{ p.period || '—' }}</span>
                <span class="list-date">{{ p.publish_date || '—' }}</span>
                <span>
                  <span v-if="p.status === 'running'" class="badge badge-blue">● 同步中</span>
                  <span v-else-if="p.status === 'completed'" class="badge badge-green">✓ 已完成</span>
                  <span v-else class="badge badge-gray">—</span>
                </span>
                <span class="list-num">{{ (p.docs_written || 0).toLocaleString() }}</span>
              </div>
            </div>
            <div v-if="!data.period_details || !data.period_details.length" class="empty-hint">尚无期记录</div>
          </template>

          <!-- 未知模式 -->
          <template v-else>
            <div class="empty-hint">未识别的 progress_mode: {{ skill.progress_mode }}</div>
          </template>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'

const props = defineProps({
  skill: { type: Object, required: true },   // 来自 /api/skill-registry 的 skill 配置
  data: { type: Object, default: () => ({}) }, // 来自 /api/stats/{key}-sync-progress
})

const PAGE_SIZE = 10
const page = ref(1)

// 颜色类（与原 DataHealthView 同步）
const barClass = computed(() => {
  const map = {
    xian: 'xa', chongqing: 'cq', sichuan: 'sc',
    jinan: 'jn', rizhao: 'rz', heze: 'hz', henan: 'hn',
  }
  return map[props.skill.key] || 'xa'
})

const skillTitle = computed(() => {
  const t = {
    xian: '工程造价材料信息',
    sichuan: '21 地市材料价格',
    chongqing: '35 区县材料价格',
    jinan: '41 分类目录材料',
    rizhao: '3 类别材料价格',
    heze: '菏泽工程造价信息',
    henan: '18 地市材料价格',
  }
  return t[props.skill.key] || '材料价格信息'
})

const incrementalBadge = computed(() => {
  if (props.skill.key === 'xian' || props.skill.key === 'chongqing') return '有增量'
  return '有新数据'
})

// 视图模式：county/catalogue 是"子项目"视图，period 是"期期刊"视图
const viewMode = computed(() => {
  if (props.skill.progress_mode === 'period') return 'period_log'
  return 'subitem'
})

// 进度环数字
const isCompleted = computed(() => {
  const s = props.data.status
  return s === 'completed' || s === 'ok'
})

const isRunning = computed(() => props.data.status === 'running')

const ringDone = computed(() => {
  // 优先使用后端 summary 字段，否则从 details 数组中实时统计 completed
  if (props.data.completed_counties) return props.data.completed_counties
  if (props.data.completed_periods) return props.data.completed_periods
  const details = props.data.county_details
    || props.data.area_details
    || props.data.tab_details
    || props.data.catalogue_details
    || []
  return details.filter(d => d.status === 'completed').length
})

const ringTotal = computed(() => {
  if (props.data.total_counties) return props.data.total_counties
  if (props.data.total_periods) return props.data.total_periods
  return (props.data.county_details
    || props.data.area_details
    || props.data.tab_details
    || props.data.catalogue_details
    || []).length
})

const ringPct = computed(() => {
  if (!ringTotal.value) return 0
  return Math.round(ringDone.value / ringTotal.value * 100)
})

const latestPeriod = computed(() => {
  return props.data.es_latest_period || props.data.period || props.data.update_date || ''
})

// 子项目视图：details 数组（county_details / area_details / tab_details / catalogue_details）
const details = computed(() => {
  return props.data.county_details
      || props.data.area_details
      || props.data.catalogue_details
      || props.data.tab_details
      || []
})

const subitemHeader = computed(() => {
  if (props.data.county_details) return '区县'
  if (props.data.area_details) return '地区'
  if (props.data.tab_details) return '类别'
  if (props.data.catalogue_details) return '分类'
  return '项目'
})

function subitemName(item) {
  // 优先取语义字段；如果带空格后缀（如 "鄠邑区 2026-01"），截掉后缀
  let name = item.county || item.area || item.tab_name || item.catalogue_name || item.catalogue || '—'
  // 处理 "区县名 YYYY-MM" 或 "区县名 YYYY.MM" 这类后缀
  const m = String(name).match(/^(.+?)\s+\d{4}[\.\-/年]?\d{0,2}/)
  if (m) name = m[1]
  return name
}

const pagedDetails = computed(() => {
  const start = (page.value - 1) * PAGE_SIZE
  return details.value.slice(start, start + PAGE_SIZE)
})

const totalDetailPages = computed(() => Math.ceil(details.value.length / PAGE_SIZE))

// 当前正在跑的子项目（county / area / tab_name / catalogue_name）
const currentItemLabel = computed(() => {
  return props.data.current_county
      || props.data.current_area
      || props.data.current_tab
      || props.data.current_catalogue_name
      || props.data.current_catalogue
      || ''
})

const currentItemDocs = computed(() => {
  const item = details.value.find(d =>
    d.county === currentItemLabel.value ||
    d.area === currentItemLabel.value ||
    d.tab_name === currentItemLabel.value ||
    d.catalogue_name === currentItemLabel.value
  )
  return item ? (item.docs_written || item.doc_count || 0) : 0
})

function getCurrentPercent() {
  const cp = props.data.current_page || 0
  const tp = props.data.total_pages || 1
  return tp > 0 ? Math.round(cp / tp * 100 * 10) / 10 : 0
}

function formatDur(sec) {
  if (!sec) return '—'
  if (sec < 60) return Math.round(sec) + 's'
  if (sec < 3600) return Math.round(sec / 60) + 'm'
  return (sec / 3600).toFixed(1) + 'h'
}
</script>

<style scoped>
/* === 亮色版（与 DataHealthView 页面整体明亮主题一致） === */
.sync-card {
  position: relative;
  background: var(--surface);
  border-radius: 12px;
  overflow: hidden;
  border: 1px solid var(--border-strong);
  box-shadow: 0 1px 2px rgba(var(--text-rgb), 0.04), 0 2px 6px rgba(var(--text-rgb), 0.03);
  transition: all 0.2s;
}
.sync-card:hover {
  border-color: var(--text-2);
  box-shadow: 0 4px 12px rgba(var(--text-rgb), 0.06), 0 2px 4px rgba(var(--text-rgb), 0.04);
  transform: translateY(-1px);
}
.sync-card-running {
  border-color: var(--primary-dark);
  box-shadow: 0 0 0 3px rgba(var(--primary-rgb), 0.10), 0 1px 2px rgba(var(--text-rgb), 0.04);
}
.sync-card-bar {
  height: 3px;
  background: linear-gradient(90deg, var(--primary), var(--primary-soft));
  width: 100%;
}
.sync-bar-xa { background: linear-gradient(90deg, #b45309, #f97316); }
.sync-bar-cq { background: linear-gradient(90deg, #ec4899, #be185d); }
.sync-bar-sc { background: linear-gradient(90deg, #10b981, #059669); }
.sync-bar-jn { background: linear-gradient(90deg, #6366f1, #4f46e5); }
.sync-bar-rz { background: linear-gradient(90deg, #0d9488, #0d9488); }
.sync-bar-hz { background: linear-gradient(90deg, #a855f7, #7e22ce); }
.sync-bar-hn { background: linear-gradient(90deg, #dc2626, #b91c1c); }
.sync-card-content { padding: 16px 20px; }
.sync-card-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 8px;
  gap: 12px;
}
.sync-card-title-row {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.sync-province-tag {
  display: inline-block;
  padding: 2px 10px;
  border-radius: 4px;
  font-size: 12px;
  font-weight: 600;
  background: var(--primary-light);
  color: var(--primary-dark);
}
.tag-xa { background: #fff7ed; color: #c2410c; }
.tag-cq { background: #fdf2f8; color: #be185d; }
.tag-sc { background: #ecfdf5; color: #047857; }
.tag-jn { background: #eef2ff; color: #4338ca; }
.tag-rz { background: #f0fdfa; color: #0f766e; }
.tag-hz { background: #faf5ff; color: #7e22ce; }
.tag-hn { background: #fef2f2; color: #b91c1c; }
.sync-card-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--surface);
}
.sync-badges {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}
.badge {
  display: inline-block;
  padding: 1px 8px;
  border-radius: 4px;
  font-size: 11px;
  font-weight: 500;
  white-space: nowrap;
}
.badge-green { background: var(--success-bg-light); color: #047857; }
.badge-red   { background: var(--danger-bg-light); color: #b91c1c; }
.badge-blue  { background: var(--primary-bg-light); color: var(--primary-dark); }
.badge-yellow{ background: var(--warning-bg-light); color: #b45309; }
.badge-gray  { background: var(--text); color: var(--text-2); }
.sync-card-meta {
  font-size: 12px;
  color: var(--text-2);
  margin-bottom: 12px;
}
.sync-card-body {
  display: flex;
  gap: 14px;
  align-items: stretch;
  flex: 1;
  min-height: 0;
  overflow: hidden;
}
.sync-info-col {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
  width: 84px;
}
.ring {
  width: 76px;
  height: 76px;
  transform: rotate(-90deg);
}
.ring-bg {
  fill: none;
  stroke: var(--border-strong);
  stroke-width: 8;
}
.ring-fill {
  fill: none;
  stroke: var(--primary);
  stroke-width: 8;
  stroke-linecap: round;
  transition: stroke-dashoffset 0.5s ease;
}
.ring-xa { stroke: #b45309; }
.ring-cq { stroke: #ec4899; }
.ring-sc { stroke: #10b981; }
.ring-jn { stroke: #6366f1; }
.ring-rz { stroke: #0d9488; }
.ring-hz { stroke: #a855f7; }
.ring-hn { stroke: #dc2626; }
.ring-pct, .ring-sub { transform: rotate(90deg); transform-origin: 50px 50px; }
.ring-pct {
  fill: var(--text);
  font-size: 16px;
  font-weight: 700;
  font-family: var(--font-mono-num);
}
.ring-sub { fill: var(--text-3); font-size: 9px; letter-spacing: 0.5px; }
.sync-status-row { display: flex; gap: 4px; }
.sync-doc-count {
  font-size: 12px;
  color: var(--text-2);
}
.sync-list-col {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
  min-height: 0;
}
.list-header, .list-row {
  display: grid;
  gap: 4px;
  padding: 6px 6px;
  font-size: 10.5px;
  align-items: center;
}
.list-header.mode-subitem,
.list-row.mode-subitem {
  /* 区县/地区/分类/类别：名称 1fr，状态 30，文档数 52，更新时间 70
     总宽 = 60+30+52+70+12gap = 224，留 buffer */
  grid-template-columns: minmax(60px, 1fr) 30px 52px 70px;
}
.list-header.mode-period,
.list-row.mode-period {
  /* 周期期刊：周期 1fr，发布日期 70，状态 60，文档数 50
     总宽 = 50+70+60+50+12gap = 242 */
  grid-template-columns: minmax(50px, 1fr) 70px 60px 50px;
}
.list-header {
  color: var(--text-2);
  font-weight: 500;
  border-bottom: 1px solid var(--border-strong);
  font-size: 10px;
  letter-spacing: 0.2px;
}
.list-row {
  color: var(--text);
  border-radius: 4px;
  transition: background 0.15s;
}
.list-row:hover { background: var(--bg); }
.row-active { background: var(--primary-light); }
.list-name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; min-width: 0; }
.list-num { text-align: right; color: var(--text-2); white-space: nowrap; }
.list-date { color: var(--text-2); font-family: ui-monospace, 'SF Mono', Consolas, monospace; font-size: 11px; white-space: nowrap; }
.list-scroll {
  max-height: 320px;
  overflow-y: auto;
}
.list-pagination {
  display: flex;
  justify-content: center;
  align-items: center;
  gap: 12px;
  padding: 4px 0;
  font-size: 12px;
  color: var(--text-2);
  flex-shrink: 0;
}
.pg-btn {
  background: var(--surface);
  color: var(--text-2);
  border: 1px solid var(--border);
  border-radius: 4px;
  padding: 2px 10px;
  cursor: pointer;
  font-size: 14px;
  transition: all 0.15s;
}
.pg-btn:hover:not(:disabled) { background: var(--surface-2); color: var(--text); border-color: var(--border-strong); }
.pg-btn:disabled { opacity: 0.3; cursor: not-allowed; }
.pg-info { font-family: ui-monospace, 'SF Mono', Consolas, monospace; }
.progress-wrap {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 6px 0 0 0;
}
.progress-bar {
  height: 6px;
  background: var(--border);
  border-radius: 3px;
  overflow: hidden;
}
.progress-fill {
  height: 100%;
  background: linear-gradient(90deg, var(--primary), var(--primary-soft));
  transition: width 0.5s ease;
}
.progress-fill-xa { background: linear-gradient(90deg, #b45309, #f97316); }
.progress-fill-cq { background: linear-gradient(90deg, #ec4899, #be185d); }
.progress-fill-sc { background: linear-gradient(90deg, #10b981, #059669); }
.progress-fill-jn { background: linear-gradient(90deg, #6366f1, #4f46e5); }
.progress-fill-rz { background: linear-gradient(90deg, #0d9488, #0d9488); }
.progress-fill-hz { background: linear-gradient(90deg, #a855f7, #7e22ce); }
.progress-fill-hn { background: linear-gradient(90deg, #dc2626, #b91c1c); }
.progress-info {
  display: flex;
  justify-content: space-between;
  font-size: 11px;
  color: var(--text-2);
}
.pct-active { color: var(--primary-dark); font-weight: 600; }
.empty-hint {
  padding: 20px;
  text-align: center;
  color: var(--text-2);
  font-size: 12px;
}
</style>
