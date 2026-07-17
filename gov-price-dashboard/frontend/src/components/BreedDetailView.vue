<!--
  跨页详情中心入口页 (2026-07-15 改造 A)
  - 数据源:`GET /api/stats/breed-detail?category=X&breed=Y` (后端已存在)
  - 路由:`/breed-detail?category=X&breed=Y` (单页,不走 currentTab 切换)
  - 来源:从 /list / /taxonomy / /spec-rules 任意品种处点击跳转
-->
<template>
  <div class="breed-page">

    <!-- 顶部导航条 -->
    <div class="back-bar">
      <button class="back-btn" @click="goBack">← 返回</button>
      <span class="back-hint">{{ fromPageHint }}</span>
    </div>

    <!-- Loading state -->
    <div v-if="loading" class="breed-loading">
      <div class="breed-spinner"></div>
      <span>加载品种详情...</span>
    </div>

    <!-- Error state -->
    <div v-else-if="error" class="breed-error">
      <div class="breed-error-icon">⚠️</div>
      <div class="breed-error-title">{{ error }}</div>
      <button class="btn-primary" @click="loadDetail">🔄 重试</button>
    </div>

    <!-- Empty state -->
    <div v-else-if="!data || (data.units || []).length === 0" class="breed-empty">
      <div class="breed-empty-icon">📦</div>
      <div class="breed-empty-title">{{ breed }} 暂无规格价格数据</div>
      <div class="breed-empty-hint">该品种尚未进入 DWS 索引族,或分类编码错误:<code>{{ category || '—' }}</code></div>
    </div>

    <!-- Content -->
    <template v-else>

      <!-- PageHeader(与 4 个 tab 对齐, margin-top: -16px 抵容器 padding) -->
      <PageHeader
        variant="flat"
        :title="breed || '—'"
        :subtitle="categoryHint"
        :stats="[
          { label: '总记录数', value: fmt.int(totalRecords), title: 'DWS 索引族总命中条数' },
          { label: '单位数', value: units.length, title: '该品种出现过的计量单位' },
          { label: '规格数', value: totalSpecs, title: '该品种出现的去重规格数' },
          { label: '整体均价', value: overallAvg ? fmt.money(overallAvg) : '—', unit: overallUnit, title: '跨单位加权均价' },
        ]"
      />

      <!-- 各单位下的规格价格明细 -->
      <div class="unit-stack">
        <div
          v-for="u in units"
          :key="u.key"
          class="unit-card"
        >
          <div class="unit-head">
            <span class="unit-name">{{ u.key || '/' }}</span>
            <span class="unit-meta">
              <strong>{{ fmt.int(u.count) }}</strong> 条 · 均价 <strong>{{ fmt.money(u.avg_price) }}</strong> 元/{{ u.key }}
            </span>
            <span class="unit-specs-count">{{ u.spec_total }} 个规格</span>
          </div>

          <!-- 该单位的规格表 -->
          <div class="unit-table-wrap">
            <div class="grid-table spec-grid">
              <div class="grid-header">
                <div class="grid-head-cell col-spec text-left">规格</div>
                <div class="grid-head-cell col-count text-right">记录数</div>
                <div class="grid-head-cell col-avg text-right">均价</div>
                <div class="grid-head-cell col-range text-right">价格区间</div>
                <div class="grid-head-cell col-province text-right">主要省份</div>
              </div>
              <div
                v-for="s in u.specs"
                :key="s.key"
                class="grid-row"
              >
                <div class="grid-cell col-spec text-left" :title="s.key">
                  <span class="spec-tag">{{ s.key }}</span>
                </div>
                <div class="grid-cell col-count text-right">{{ fmt.int(s.count) }}</div>
                <div class="grid-cell col-avg text-right">{{ fmt.money(s.avg_price) }}</div>
                <div class="grid-cell col-range text-right">
                  <span class="range-min">{{ fmt.money(s.min_price) }}</span>
                  <span class="range-sep">~</span>
                  <span class="range-max">{{ fmt.money(s.max_price) }}</span>
                </div>
                <div class="grid-cell col-province text-right">
                  <span class="province-chip">{{ s.province || '—' }}</span>
                </div>
              </div>
              <div v-if="!u.specs?.length" class="grid-row grid-row-empty">
                <div class="grid-cell" style="grid-column: 1 / -1;">该单位下暂无规格数据</div>
              </div>
            </div>
          </div>
        </div>
      </div>

    </template>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import PageHeader from './PageHeader.vue'
import { useFormatNumber } from '../composables/useFormatNumber.js'
import { useFormatMoney } from '../composables/useFormatNumber.js'

const fmt = useFormatNumber()
const fmtMoney = useFormatMoney()

// 兼容(防止 useFormatMoney 不存在时崩)
const money = (v) => (fmtMoney ? fmtMoney(v) : (v == null ? '—' : Number(v).toFixed(2)))

const route = useRoute()
const router = useRouter()

const API = import.meta.env.VITE_API_URL || '/api'

const breed = computed(() => String(route.query.breed || ''))
// 后端端点要求 category 必传,但旧调用习惯用 l3 — 两种 key 都兼容
const category = computed(() => String(route.query.category || route.query.l3 || ''))
const fromPage = computed(() => String(route.query.from || ''))

const fromPageHint = computed(() => {
  if (fromPage.value === 'list') return '从全部数据列表进入'
  if (fromPage.value === 'taxonomy') return '从分类体系进入'
  if (fromPage.value === 'spec-rules') return '从规格规则库进入'
  return ''
})

const categoryHint = computed(() => {
  if (!category.value) return '品种详情 · 跨城市规格价格分析'
  return `分类 ${category.value} · 跨城市规格价格分析`
})

const data = ref(null)
const loading = ref(false)
const error = ref('')

const units = computed(() => (data.value?.units || []).filter(u => u.count > 0))
const totalRecords = computed(() => {
  if (!data.value) return 0
  return data.value.total_records || units.value.reduce((a, u) => a + u.count, 0)
})
const totalSpecs = computed(() => units.value.reduce((a, u) => a + (u.spec_total || 0), 0))

// 整体均价 = 各单位 (count * avg_price) 之和 / 总条数
const overallAvg = computed(() => {
  const total = totalRecords.value
  if (!total || !units.value.length) return null
  let num = 0
  for (const u of units.value) num += (u.avg_price || 0) * (u.count || 0)
  return num / total
})
const overallUnit = computed(() => {
  if (units.value.length === 1) return units.value[0].key
  if (units.value.length > 1) return units.value.map(u => u.key).join('/')
  return ''
})

async function loadDetail() {
  if (!breed.value) {
    error.value = '品种名为空,请从 /list 或 /taxonomy 进入'
    data.value = null
    return
  }
  loading.value = true
  error.value = ''
  data.value = null
  try {
    const params = { breed: breed.value, page: 1, page_size: 200 }
    // category 后端是必传,即使未知也传空字符串让后端走全品类聚合(比如仅按 breed 匹配)
    params.category = category.value || ''
    const res = await axios.get(`${API}/stats/breed-detail`, { params })
    const payload = res.data?.data || res.data || {}
    data.value = payload
    if (!payload.units || payload.units.length === 0) {
      data.value = { ...payload, units: [] }  // 触发 empty 态
    }
  } catch (e) {
    if (e?.response?.status === 404) {
      error.value = '该品种不存在或参数错误'
    } else {
      error.value = e?.response?.data?.detail || e.message || '加载失败'
    }
    data.value = null
  } finally {
    loading.value = false
  }
}

function goBack() {
  // 按 from 退回原页面;若没记录则回 /list(常见入口)
  if (fromPage.value === 'taxonomy') {
    router.push({ path: '/taxonomy', query: { ...route.query, from: undefined } })
  } else if (fromPage.value === 'spec-rules') {
    router.push({ path: '/spec-rules', query: { ...route.query, from: undefined } })
  } else {
    router.push({ path: '/list', query: { ...route.query, from: undefined } })
  }
}

watch(() => route.query.breed + '|' + route.query.category, loadDetail, { immediate: false })

onMounted(() => {
  loadDetail()
})
</script>

<style scoped>
/* ─────────────────────────────────────────────
   跨页详情中心 (BreedDetailView)
   - PageHeader 同 4 tab 对齐(margin-top: -16px)
   - 单位卡片 + 同 subgrid 规格表
   ───────────────────────────────────────────── */
.breed-page {
  padding: 16px 28px 64px;
  min-height: 100vh;
  background: linear-gradient(180deg, var(--bg) 0%, var(--surface-2) 100%);
  box-sizing: border-box;
}

/* Back bar */
.back-bar {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 12px;
}
.back-btn {
  background: var(--surface);
  border: 1px solid var(--border);
  color: var(--text-2);
  padding: 6px 14px;
  border-radius: 8px;
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  font-family: inherit;
  transition: all 0.15s;
}
.back-btn:hover {
  background: var(--primary-light);
  border-color: var(--primary);
  color: var(--primary);
}
.back-hint {
  font-size: 12px;
  color: var(--text-3);
}

/* PageHeader 顶部对齐补偿(与其他 4 tab 一致) */
.page-header { margin-top: -16px; margin-bottom: 16px; }

/* Loading / Error / Empty 统一态 */
.breed-loading,
.breed-error,
.breed-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 60px 16px;
  color: var(--text-2);
  gap: 12px;
}
.breed-spinner {
  width: 24px; height: 24px;
  border: 3px solid rgba(15, 23, 42, 0.08);
  border-top-color: rgba(37, 99, 235, 0.7);
  border-radius: 50%;
  animation: spin 0.8s linear infinite;
}
@keyframes spin { to { transform: rotate(360deg); } }
.breed-error-icon,
.breed-empty-icon { font-size: 56px; opacity: 0.6; }
.breed-error-title,
.breed-empty-title { font-size: 16px; font-weight: 600; color: var(--text); }
.breed-empty-hint { font-size: 13px; color: var(--text-3); }
.breed-empty-hint code {
  background: var(--surface-2);
  color: var(--primary);
  padding: 1px 6px;
  border-radius: 3px;
  font-family: ui-monospace, monospace;
  font-size: 12px;
}
.btn-primary {
  background: var(--primary);
  color: white;
  border: none;
  padding: 8px 18px;
  border-radius: 6px;
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  font-family: inherit;
}
.btn-primary:hover { background: #1d4ed8; }

/* 单位卡片堆叠 */
.unit-stack {
  display: flex;
  flex-direction: column;
  gap: 14px;
}
.unit-card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 12px;
  box-shadow: 0 1px 2px rgba(0,0,0,0.04);
  overflow: hidden;
}
.unit-head {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 12px 18px;
  background: linear-gradient(180deg, var(--surface-2) 0%, transparent 100%);
  border-bottom: 1px solid var(--border);
}
.unit-name {
  font-size: 17px;
  font-weight: 700;
  color: var(--text);
  font-family: ui-monospace, monospace;
  min-width: 32px;
  text-align: center;
  padding: 2px 8px;
  background: rgba(37,99,235,0.12);
  border-radius: 4px;
  color: var(--primary);
}
.unit-meta {
  font-size: 13px;
  color: var(--text-2);
}
.unit-meta strong {
  color: var(--text);
  font-weight: 700;
  font-variant-numeric: tabular-nums;
}
.unit-specs-count {
  margin-left: auto;
  font-size: 12px;
  color: var(--text-3);
  padding: 2px 8px;
  background: var(--surface-2);
  border-radius: 12px;
  font-weight: 500;
}

.unit-table-wrap { padding: 0; }

/* ──── Grid (同其他 tab 的 subgrid 架构) ──── */
.spec-grid {
  display: grid;
  grid-template-columns:
    minmax(180px, 1fr)
    minmax(90px, max-content)
    minmax(90px, max-content)
    minmax(170px, max-content)
    minmax(120px, max-content);
  grid-auto-rows: auto;
  width: 100%;
}
.spec-grid > .grid-header,
.spec-grid > .grid-row {
  display: grid;
  grid-template-columns: subgrid;
  grid-column: 1 / -1;
  align-items: stretch;
}
.spec-grid .grid-header {
  position: sticky;
  top: 0;
  z-index: 3;
  background: var(--surface-2);
  box-shadow: 0 1px 0 var(--border);
}
.spec-grid .grid-head-cell,
.spec-grid .grid-cell {
  display: flex;
  align-items: center;
  padding: 8px 14px;
  border-right: 1px solid var(--border);
  min-width: 0;
  overflow: hidden;
  font-size: 13px;
  color: var(--text);
  box-sizing: border-box;
  justify-content: center;
}
.spec-grid .grid-cell:last-child,
.spec-grid .grid-head-cell:last-child { border-right: none; }
.spec-grid .text-left { justify-content: flex-start; text-align: left; }
.spec-grid .text-right { justify-content: flex-end; padding-right: 14px; }
.spec-grid .grid-head-cell {
  font-weight: 700;
  font-size: 11.5px;
  color: var(--text-2);
}
.spec-grid .grid-row {
  border-bottom: 1px solid var(--border);
  background: var(--surface);
  transition: background 0.1s;
}
.spec-grid .grid-row:hover { background: rgba(37,99,235,0.04); }
.spec-grid .grid-row:nth-child(even) { background: var(--surface-2, #f8fafc); }
.spec-grid .grid-row:nth-child(even):hover { background: rgba(37,99,235,0.06); }
.spec-grid .grid-row-empty { cursor: default; }
.spec-grid .grid-row-empty:hover { background: var(--surface); }
.spec-grid .grid-row-empty .grid-cell { background: var(--surface); }

/* Spec chip */
.spec-tag {
  display: inline-block;
  padding: 2px 8px;
  background: rgba(37,99,235,0.08);
  border: 1px solid rgba(37,99,235,0.18);
  border-radius: 4px;
  font-family: ui-monospace, 'SF Mono', Consolas, monospace;
  font-size: 12px;
  color: var(--primary);
  max-width: 100%;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}

/* Range pill */
.range-min, .range-max {
  font-family: ui-monospace, monospace;
  font-variant-numeric: tabular-nums;
  font-size: 13px;
}
.range-min { color: var(--status-ok, #16a34a); }
.range-max { color: var(--status-alert, #ef4444); }
.range-sep { color: var(--text-3); margin: 0 4px; }

/* Province chip */
.province-chip {
  display: inline-block;
  padding: 2px 9px;
  background: rgba(99,102,241,0.1);
  border: 1px solid rgba(99,102,241,0.18);
  border-radius: 12px;
  font-size: 11px;
  font-weight: 600;
  color: #4338ca;
}

@media (max-width: 768px) {
  .breed-page { padding: 12px 14px; }
  .unit-head { flex-wrap: wrap; }
  .unit-specs-count { margin-left: 0; }
}
</style>
