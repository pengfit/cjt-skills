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
            <div class="list-header">
              <span>{{ subitemHeader }}</span>
              <span>状态</span>
              <span>文档数</span>
              <span>更新时间</span>
            </div>
            <div class="list-scroll">
              <div class="list-row" v-for="(item, idx) in pagedDetails" :key="idx"
                :class="{ 'row-active': data.current_county === item.county || data.current_area === item.area || data.current_tab === item.tab_name || data.current_catalogue_name === item.catalogue_name }">
                <span class="list-name">{{ subitemName(item) }}</span>
                <span>
                  <span v-if="item.status === 'running'" class="badge badge-blue">●</span>
                  <span v-else-if="item.status === 'completed'" class="badge badge-green">✓</span>
                  <span v-else-if="item.status === 'interrupted'" class="badge badge-yellow">⚠</span>
                  <span v-else class="badge badge-gray">—</span>
                </span>
                <span class="list-num">{{ (item.docs_written || item.doc_count || 0).toLocaleString() }}</span>
                <span class="list-date">{{ (item.last_updated || '').slice(0, 16) || '—' }}</span>
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
            <div class="list-header">
              <span>周期</span>
              <span>发布日期</span>
              <span>状态</span>
              <span>文档数</span>
            </div>
            <div class="list-scroll">
              <div class="list-row" v-for="(p, idx) in (data.period_details || []).slice(0, 20)" :key="idx">
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
  return props.data.completed_counties || props.data.completed_periods || 0
})

const ringTotal = computed(() => {
  return props.data.total_counties || props.data.total_periods || 0
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
  return item.county || item.area || item.tab_name || item.catalogue_name || item.catalogue || '—'
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
/* 与原 DataHealthView 卡片样式一致 */
.sync-card {
  position: relative;
  background: #1e293b;
  border-radius: 12px;
  overflow: hidden;
  border: 1px solid rgba(148, 163, 184, 0.1);
  transition: all 0.2s;
}
.sync-card:hover {
  border-color: rgba(96, 165, 250, 0.3);
  transform: translateY(-1px);
}
.sync-card-running {
  border-color: rgba(59, 130, 246, 0.4);
  box-shadow: 0 0 20px rgba(59, 130, 246, 0.15);
}
.sync-card-bar {
  height: 3px;
  background: linear-gradient(90deg, #38bdf8, #818cf8);
  width: 100%;
}
.sync-bar-xa { background: linear-gradient(90deg, #f59e0b, #f97316); }
.sync-bar-cq { background: linear-gradient(90deg, #ec4899, #be185d); }
.sync-bar-sc { background: linear-gradient(90deg, #10b981, #059669); }
.sync-bar-jn { background: linear-gradient(90deg, #6366f1, #4f46e5); }
.sync-bar-rz { background: linear-gradient(90deg, #14b8a6, #0d9488); }
.sync-bar-hz { background: linear-gradient(90deg, #a855f7, #7e22ce); }
.sync-bar-hn { background: linear-gradient(90deg, #ef4444, #b91c1c); }
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
  background: rgba(96, 165, 250, 0.15);
  color: #60a5fa;
}
.tag-xa { background: rgba(245, 158, 11, 0.15); color: #f59e0b; }
.tag-cq { background: rgba(236, 72, 153, 0.15); color: #ec4899; }
.tag-sc { background: rgba(16, 185, 129, 0.15); color: #10b981; }
.tag-jn { background: rgba(99, 102, 241, 0.15); color: #818cf8; }
.tag-rz { background: rgba(20, 184, 166, 0.15); color: #14b8a6; }
.tag-hz { background: rgba(168, 85, 247, 0.15); color: #a855f7; }
.tag-hn { background: rgba(239, 68, 68, 0.15); color: #ef4444; }
.sync-card-title {
  font-size: 14px;
  font-weight: 500;
  color: #cbd5e1;
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
.badge-green { background: rgba(16, 185, 129, 0.15); color: #10b981; }
.badge-red { background: rgba(239, 68, 68, 0.15); color: #ef4444; }
.badge-blue { background: rgba(59, 130, 246, 0.15); color: #60a5fa; }
.badge-yellow { background: rgba(245, 158, 11, 0.15); color: #f59e0b; }
.badge-gray { background: rgba(100, 116, 139, 0.2); color: #94a3b8; }
.sync-card-meta {
  font-size: 12px;
  color: #64748b;
  margin-bottom: 12px;
}
.sync-card-body {
  display: grid;
  grid-template-columns: 200px 1fr;
  gap: 20px;
}
.sync-info-col {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
}
.ring {
  width: 100px;
  height: 100px;
  transform: rotate(-90deg);
}
.ring-bg {
  fill: none;
  stroke: rgba(148, 163, 184, 0.15);
  stroke-width: 8;
}
.ring-fill {
  fill: none;
  stroke: #38bdf8;
  stroke-width: 8;
  stroke-linecap: round;
  transition: stroke-dashoffset 0.5s ease;
}
.ring-xa { stroke: #f59e0b; }
.ring-cq { stroke: #ec4899; }
.ring-sc { stroke: #10b981; }
.ring-jn { stroke: #6366f1; }
.ring-rz { stroke: #14b8a6; }
.ring-hz { stroke: #a855f7; }
.ring-hn { stroke: #ef4444; }
.ring-pct, .ring-sub { transform: rotate(90deg); transform-origin: center; }
.sync-status-row { display: flex; gap: 4px; }
.sync-doc-count {
  font-size: 12px;
  color: #94a3b8;
}
.sync-list-col {
  display: flex;
  flex-direction: column;
  gap: 6px;
  min-width: 0;
}
.list-header, .list-row {
  display: grid;
  grid-template-columns: 1fr 80px 80px 110px;
  gap: 8px;
  padding: 6px 8px;
  font-size: 12px;
}
.list-header {
  color: #64748b;
  font-weight: 500;
  border-bottom: 1px solid rgba(148, 163, 184, 0.1);
}
.list-row {
  color: #cbd5e1;
  border-radius: 4px;
  transition: background 0.15s;
}
.list-row:hover { background: rgba(148, 163, 184, 0.05); }
.row-active { background: rgba(59, 130, 246, 0.1); }
.list-name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.list-num { text-align: right; color: #94a3b8; }
.list-date { color: #64748b; font-family: monospace; font-size: 11px; }
.list-scroll {
  max-height: 180px;
  overflow-y: auto;
}
.list-pagination {
  display: flex;
  justify-content: center;
  align-items: center;
  gap: 12px;
  padding: 4px 0;
  font-size: 12px;
  color: #94a3b8;
}
.pg-btn {
  background: rgba(59, 130, 246, 0.1);
  color: #60a5fa;
  border: 1px solid rgba(59, 130, 246, 0.2);
  border-radius: 4px;
  padding: 2px 10px;
  cursor: pointer;
  font-size: 14px;
}
.pg-btn:disabled { opacity: 0.3; cursor: not-allowed; }
.pg-info { font-family: monospace; }
.progress-wrap {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 6px 0 0 0;
}
.progress-bar {
  height: 6px;
  background: rgba(148, 163, 184, 0.1);
  border-radius: 3px;
  overflow: hidden;
}
.progress-fill {
  height: 100%;
  background: linear-gradient(90deg, #38bdf8, #818cf8);
  transition: width 0.5s ease;
}
.progress-fill-xa { background: linear-gradient(90deg, #f59e0b, #f97316); }
.progress-fill-cq { background: linear-gradient(90deg, #ec4899, #be185d); }
.progress-fill-sc { background: linear-gradient(90deg, #10b981, #059669); }
.progress-fill-jn { background: linear-gradient(90deg, #6366f1, #4f46e5); }
.progress-fill-rz { background: linear-gradient(90deg, #14b8a6, #0d9488); }
.progress-fill-hz { background: linear-gradient(90deg, #a855f7, #7e22ce); }
.progress-fill-hn { background: linear-gradient(90deg, #ef4444, #b91c1c); }
.progress-info {
  display: flex;
  justify-content: space-between;
  font-size: 11px;
  color: #94a3b8;
}
.pct-active { color: #60a5fa; font-weight: 600; }
.empty-hint {
  padding: 20px;
  text-align: center;
  color: #64748b;
  font-size: 12px;
}
</style>
