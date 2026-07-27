<template>
  <div class="canon-page">
    <div v-if="stats" class="canon-stats">
      <div class="canon-stat">
        <div class="canon-stat-label">总映射数</div>
        <div class="canon-stat-value">{{ stats.total_mappings.toLocaleString() }}</div>
      </div>
      <div class="canon-stat">
        <div class="canon-stat-label">distinct normalized_breed</div>
        <div class="canon-stat-value">{{ stats.distinct_normalized_breed.toLocaleString() }}</div>
        <div class="canon-stat-sub">合并率 {{ (stats.merge_ratio * 100).toFixed(1) }}%</div>
      </div>
      <div class="canon-stat" :class="{ warn: stats.null_l3 > 0 }">
        <div class="canon-stat-label">NULL l3</div>
        <div class="canon-stat-value">{{ stats.null_l3.toLocaleString() }}</div>
      </div>
      <div class="canon-stat">
        <div class="canon-stat-label">reject</div>
        <div class="canon-stat-value">{{ stats.reject_count.toLocaleString() }}</div>
      </div>
    </div>

    <div class="canon-toolbar">
      <input v-model="search" type="text" class="canon-search" placeholder="搜索 breed_clean / normalized_breed" @keydown.enter="reload(1)" />
      <select v-model="source" class="canon-select" @change="reload(1)">
        <option value="">全部 source</option>
        <option v-for="s in (stats?.by_source || [])" :key="s[0]" :value="s[0]">{{ s[0] }} ({{ s[1] }})</option>
      </select>
      <select v-model="l3" class="canon-select" @change="reload(1)">
        <option value="">全部 l3_code</option>
        <option v-for="lc in (stats?.top10_l3 || [])" :key="lc[0]" :value="lc[0]">{{ lc[0] }} ({{ lc[1] }})</option>
      </select>
      <label class="canon-toggle">
        <input v-model="nullL3" type="checkbox" @change="reload(1)" />只看 NULL l3
      </label>
      <button class="canon-btn canon-btn-primary" :disabled="loading" @click="reload(1)">
        {{ loading ? '加载中...' : '查询' }}
      </button>
    </div>

    <div class="canon-table-wrap">
      <table class="canon-table">
        <thead>
          <tr>
            <th>breed_clean</th>
            <th>normalized_breed</th>
            <th>l3_code</th>
            <th>confidence</th>
            <th>source</th>
            <th>note</th>
            <th>updated_at</th>
          </tr>
        </thead>
        <tbody>
          <tr v-if="rows.length === 0 && !loading">
            <td colspan="7" class="canon-empty">无数据(可调整筛选或清空搜索)</td>
          </tr>
          <tr v-for="row in rows" :key="row.breed_clean" class="canon-row">
            <td class="canon-cell-mono canon-cell-strong">{{ row.breed_clean }}</td>
            <td class="canon-cell-mono">{{ row.normalized_breed }}</td>
            <td>
              <span v-if="row.l3_code" class="canon-pill">{{ row.l3_code }}</span>
              <span v-else class="canon-pill canon-pill-warn">UNCLASSIFIED</span>
            </td>
            <td>
              <span class="canon-conf" :class="confClass(row.confidence)">{{ row.confidence.toFixed(2) }}</span>
            </td>
            <td><span class="canon-source">{{ row.source }}</span></td>
            <td class="canon-note">{{ row.note || '-' }}</td>
            <td class="canon-time">{{ row.updated_at }}</td>
          </tr>
        </tbody>
      </table>
    </div>

    <div v-if="total > 0" class="canon-pagination">
      <span class="canon-pagination-info">共 {{ total.toLocaleString() }} 条 · 第 {{ page }} / {{ Math.ceil(total / size) }} 页</span>
      <button class="canon-btn" :disabled="page === 1 || loading" @click="reload(page - 1)">上一页</button>
      <button class="canon-btn" :disabled="page * size >= total || loading" @click="reload(page + 1)">下一页</button>
      <select v-model.number="size" class="canon-select" @change="reload(1)">
        <option :value="20">20 / 页</option>
        <option :value="50">50 / 页</option>
        <option :value="100">100 / 页</option>
      </select>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'

const search = ref('')
const source = ref('')
const l3 = ref('')
const nullL3 = ref(false)
const page = ref(1)
const size = ref(20)
const total = ref(0)
const rows = ref([])
const stats = ref(null)
const loading = ref(false)

function confClass(c) {
  if (c >= 0.95) return 'high'
  if (c >= 0.85) return 'mid'
  if (c >= 0.5) return 'low'
  return 'bad'
}

async function loadStats() {
  try {
    const r = await fetch('/api/canon/breeds/stats')
    if (r.ok) stats.value = await r.json()
  } catch (e) { console.error('[canon] stats load failed', e) }
}

async function reload(p) {
  if (p) page.value = p
  loading.value = true
  const params = new URLSearchParams({ page: page.value, size: size.value })
  if (search.value) params.set('search', search.value)
  if (source.value) params.set('source', source.value)
  if (l3.value) params.set('l3_code', l3.value)
  if (nullL3.value) params.set('null_l3', 'true')
  try {
    const r = await fetch('/api/canon/breeds?' + params)
    if (!r.ok) { rows.value = []; total.value = 0; return }
    const d = await r.json()
    rows.value = d.rows || []
    total.value = d.total || 0
  } catch (e) { console.error('[canon] breeds load failed', e) }
  finally { loading.value = false }
}

onMounted(() => { loadStats(); reload(1) })
</script>

<style scoped>
.canon-page { padding: 24px 28px; max-width: 1400px; margin: 0 auto; }

.canon-stats {
  display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 12px; margin-bottom: 20px;
}
.canon-stat { background: #fff; border: 1px solid #e5e7eb; border-radius: 8px; padding: 14px 16px; }
.canon-stat.warn { border-color: #f59e0b; background: #fffbeb; }
.canon-stat-label { font-size: 12px; color: #6b7280; }
.canon-stat-value { font-size: 22px; font-weight: 700; color: #111827; margin-top: 4px; }
.canon-stat-sub { font-size: 11px; color: #9ca3af; margin-top: 2px; }

.canon-toolbar {
  display: flex; gap: 10px; align-items: center; flex-wrap: wrap;
  background: #fff; border: 1px solid #e5e7eb; border-radius: 8px;
  padding: 12px 16px; margin-bottom: 16px;
}
.canon-search {
  flex: 1; min-width: 220px; padding: 6px 10px;
  border: 1px solid #d1d5db; border-radius: 6px; font-size: 13px;
  font-family: inherit; outline: none;
}
.canon-search:focus { border-color: #3b82f6; box-shadow: 0 0 0 2px #3b82f61a; }
.canon-select {
  padding: 6px 8px; border: 1px solid #d1d5db; border-radius: 6px;
  font-size: 13px; font-family: inherit; background: #fff;
  outline: none; cursor: pointer;
}
.canon-toggle { display: inline-flex; align-items: center; gap: 4px; font-size: 13px; color: #4b5563; }
.canon-btn {
  padding: 6px 14px; background: #fff; border: 1px solid #d1d5db;
  border-radius: 6px; font-size: 13px; font-family: inherit;
  color: #374151; cursor: pointer; white-space: nowrap;
}
.canon-btn:hover:not(:disabled) { background: #f9fafb; }
.canon-btn:disabled { opacity: 0.5; cursor: not-allowed; }
.canon-btn-primary { background: #2563eb; color: #fff; border-color: #2563eb; }
.canon-btn-primary:hover:not(:disabled) { background: #1d4ed8; }

.canon-table-wrap {
  background: #fff; border: 1px solid #e5e7eb; border-radius: 8px; overflow-x: auto;
}
.canon-table { width: 100%; border-collapse: collapse; font-size: 13px; }
.canon-table th {
  text-align: left; padding: 10px 12px; background: #f9fafb;
  border-bottom: 1px solid #e5e7eb; color: #4b5563; font-weight: 600; white-space: nowrap;
}
.canon-table td {
  padding: 8px 12px; border-bottom: 1px solid #f3f4f6; vertical-align: top; max-width: 320px;
}
.canon-row:hover td { background: #f9fafb; }
.canon-cell-mono { font-family: ui-monospace, "SF Mono", monospace; font-size: 12px; }
.canon-cell-strong { font-weight: 600; color: #111827; }
.canon-pill {
  display: inline-block; padding: 1px 8px; background: #dbeafe;
  color: #1d4ed8; border-radius: 4px; font-size: 12px;
  font-family: ui-monospace, "SF Mono", monospace; white-space: nowrap;
}
.canon-pill-warn { background: #fef3c7; color: #92400e; }
.canon-conf {
  display: inline-block; padding: 1px 8px; border-radius: 4px;
  font-size: 12px; font-family: ui-monospace, "SF Mono", monospace; font-weight: 600;
}
.canon-conf.high { background: #dcfce7; color: #166534; }
.canon-conf.mid { background: #dbeafe; color: #1d4ed8; }
.canon-conf.low { background: #fef3c7; color: #92400e; }
.canon-conf.bad { background: #fee2e2; color: #991b1b; }
.canon-source {
  font-size: 12px; color: #4b5563; background: #f3f4f6;
  padding: 1px 6px; border-radius: 3px;
  font-family: ui-monospace, "SF Mono", monospace; white-space: nowrap;
}
.canon-note { font-size: 12px; color: #6b7280; }
.canon-time { font-size: 11px; color: #9ca3af; font-family: ui-monospace, "SF Mono", monospace; }
.canon-empty { text-align: center; padding: 32px 12px; color: #9ca3af; }

.canon-pagination {
  display: flex; align-items: center; gap: 12px; margin-top: 16px; flex-wrap: wrap;
}
.canon-pagination-info { color: #6b7280; font-size: 13px; }
</style>
