<template>
  <div class="bcr-page">
    <!-- Header -->
    <div class="bcr-header">
      <div class="bcr-header-left">
        <div class="bcr-title">🏷️ 分类规则库</div>
        <div class="bcr-subtitle">品种 → 分类映射规则库，Jaccard 召回 + AI 推断，写入 rules_vec.db 持久化</div>
      </div>
      <div class="bcr-header-stats">
        <div class="bcr-stat">
          <span class="bcr-stat-val">{{ total.toLocaleString() }}</span>
          <span class="bcr-stat-key">规则总数</span>
        </div>
      </div>
    </div>

    <!-- Toolbar -->
    <div class="bcr-toolbar">
      <div class="bcr-toolbar-left">
        <div class="bcr-search-wrap">
          <span class="bcr-search-icon">🔍</span>
          <input
            class="bcr-input"
            v-model="keyword"
            placeholder="搜索品种名..."
            @input="debounceLoad(1)"
          />
        </div>
        <CustomSelect
          v-model="categoryFilter"
          :options="categoryOptions.map(c => ({ key: c, label: c }))"
          placeholder="全部分类"
          :searchable="false"
          @change="loadRules(1)"
        />
      </div>
      <div class="bcr-toolbar-right">
        <button class="bcr-btn bcr-btn-red" @click="clearFilters" :disabled="loading">
          🗑️ 清空筛选
        </button>
        <button class="bcr-btn bcr-btn-cyan" @click="testMode = !testMode">
          {{ testMode ? '关闭测试' : '🔬 测试召回' }}
        </button>
        <button class="bcr-btn bcr-btn-cyan" @click="showHelp = !showHelp">
          {{ showHelp ? '🔼 收起' : '📖 使用说明' }}
        </button>
      </div>
    </div>

    <!-- 使用说明 -->
    <Transition name="bcr-slide">
      <div class="bcr-help" v-if="showHelp">
        <div class="bcr-help-title">📖 分类规则库说明</div>
        <div class="bcr-help-grid">
          <div class="bcr-help-item">
            <span class="bcr-help-key">数据源</span>
            <span class="bcr-help-val">
              <strong>唯一来源</strong>：<code>rules_vec.db</code>（SQLite，616 条规则）<br/>
              品种分类由 AI 批量分类后写入，静态规则文件已废弃
            </span>
          </div>
          <div class="bcr-help-item">
            <span class="bcr-help-key">分类流程</span>
            <span class="bcr-help-val">
              <strong>① Jaccard 召回</strong>（精确包含 + 加权 Jaccard + char Jaccard，阈值 0.45）<br/>
              <strong>② 未命中 → AI 批量分类</strong> → 写入 DB 持久化
            </span>
          </div>
          <div class="bcr-help-item">
            <span class="bcr-help-key">Jaccard 召回</span>
            <span class="bcr-help-val">
              从 DB 加载全部 breed→category 规则，综合分 ≥ 0.45 即召回<br/>
              例：大理石台板（单孔）↔（双孔）综合分 0.499 ≥ 0.45 可直接命中
            </span>
          </div>
          <div class="bcr-help-item">
            <span class="bcr-help-key">AI 批量分类</span>
            <span class="bcr-help-val">
              ETL 增量模式下，未分类品种自动批量调用 AI 接口<br/>
              结果写入 <code>breed_category_rules</code> 表供下次直接命中
            </span>
          </div>
          <div class="bcr-help-item">
            <span class="bcr-help-key">来源说明</span>
            <span class="bcr-help-val">
              <code>ai</code> — AI 批量分类结果<br/>
              <code>rules_migrated</code> — 规则迁移<br/>
              <code>manual</code> — 手动添加
            </span>
          </div>
        </div>
      </div>
    </Transition>

    <!-- Test panel -->
    <Transition name="bcr-slide">
      <div class="bcr-panel bcr-panel-test" v-if="testMode">
        <div class="bcr-panel-title">🔬 Jaccard 召回测试</div>
        <div class="bcr-test-row">
          <input class="bcr-input" v-model="testBreed" placeholder="输入品种名，按回车测试" @keyup.enter="doTest" />
          <button class="bcr-btn bcr-btn-cyan" @click="doTest">测试</button>
        </div>
        <div v-if="testResult" class="bcr-test-result" :class="testResult.hit ? 'test-hit' : 'test-miss'">
          <template v-if="testResult.hit">
            <span class="test-icon">✅</span>
            <span>召回结果：<strong>{{ testResult.category }}</strong></span>
          </template>
          <template v-else>
            <span class="test-icon">❌</span>
            <span>未命中（无相似规则）</span>
          </template>
        </div>
      </div>
    </Transition>

    <!-- Table -->
    <div class="bcr-card">
      <div class="table-scroll">
        <table class="bcr-table">
          <thead>
            <tr>
              <th>品种</th>
              <th>分类</th>
              <th>置信度</th>
              <th>来源</th>
              <th>添加时间</th>
              <th>备注</th>
            </tr>
          </thead>
          <tbody>
            <tr v-if="loading">
              <td colspan="6" class="bcr-empty">加载中...</td>
            </tr>
            <tr v-else-if="!rules.length">
              <td colspan="6" class="bcr-empty">暂无规则</td>
            </tr>
            <tr v-else v-for="r in rules" :key="r.id" class="bcr-row">
              <td><span class="bcr-breed">{{ r.breed }}</span></td>
              <td><span class="bcr-cat">{{ r.category }}</span></td>
              <td><span class="bcr-conf" :class="confClass(r.confidence)">{{ (r.confidence ?? 1).toFixed(2) }}</span></td>
              <td>
                <span class="bcr-src" :class="`src-${r.source}`">{{ srcLabel(r.source) }}</span>
              </td>
              <td class="bcr-date">{{ formatDate(r.created_at) }}</td>
              <td class="bcr-note" :title="r.note">{{ r.note || '—' }}</td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- Pagination -->
      <div class="bcr-pagination" v-if="pages > 1">
        <button class="bcr-page-btn" :disabled="page <= 1" @click="loadRules(page - 1)">‹</button>
        <button
          v-for="p in pageRange"
          :key="p"
          class="bcr-page-btn"
          :class="{ active: Number(p) === Number(page), ellipsis: p === '...' }"
          :disabled="p === '...'"
          @click="p !== '...' && loadRules(Number(p))"
        >{{ p }}</button>
        <button class="bcr-page-btn" :disabled="page >= pages" @click="loadRules(page + 1)">›</button>
        <span class="bcr-page-info">{{ page }}/{{ pages }} 页 · {{ total }} 条</span>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import axios from 'axios'
import CustomSelect from './CustomSelect.vue'

const API = import.meta.env.VITE_API_URL || '/api'

const KEYWORD_KEY = 'bcr_keyword2'
const FILTER_KEY = 'bcr_filter2'
const PAGE_KEY = 'bcr_page2'

const keyword = ref(localStorage.getItem(KEYWORD_KEY) || '')
const categoryFilter = ref(localStorage.getItem(FILTER_KEY) || '')
const categoryOptions = ref([])
const rules = ref([])
const total = ref(0)
const page = ref(Number(localStorage.getItem(PAGE_KEY)) || 1)
const pageSize = ref(50)
const loading = ref(false)
const testMode = ref(false)
const testBreed = ref('')
const testResult = ref(null)
const showHelp = ref(false)

const srcLabels = { ai: 'AI', rules_migrated: '迁移', manual: '手动' }
function srcLabel(s) { return srcLabels[s] || s }
function confClass(c) {
  if (c == null || c >= 0.8) return 'conf-high'
  if (c >= 0.5) return 'conf-mid'
  return 'conf-low'
}

const pages = computed(() => Math.ceil(total.value / pageSize.value) || 1)

const pageRange = computed(() => {
  const t = pages.value, c = page.value
  if (t <= 7) return Array.from({ length: t }, (_, i) => i + 1)
  const r = []
  if (c <= 4) { for (let i = 1; i <= 5; i++) r.push(i); r.push('...'); r.push(t) }
  else if (c >= t - 3) { r.push(1); r.push('...'); for (let i = t - 4; i <= t; i++) r.push(i) }
  else { r.push(1); r.push('...'); for (let i = c - 1; i <= c + 1; i++) r.push(i); r.push('...'); r.push(t) }
  return r
})

function debounceLoad(p) {
  clearTimeout(window._bcr_debounce)
  window._bcr_debounce = setTimeout(() => {
    localStorage.setItem(PAGE_KEY, String(p))
    loadRules(p || 1)
  }, 300)
}

async function loadRules(p = 1) {
  loading.value = true
  try {
    const params = { page: p, page_size: pageSize.value }
    if (keyword.value.trim()) {
      params.keyword = keyword.value.trim()
      localStorage.setItem(KEYWORD_KEY, keyword.value.trim())
    } else {
      localStorage.removeItem(KEYWORD_KEY)
    }
    if (categoryFilter.value) {
      params.category_filter = categoryFilter.value
      localStorage.setItem(FILTER_KEY, categoryFilter.value)
    } else {
      localStorage.removeItem(FILTER_KEY)
    }
    const { data } = await axios.get(`${API}/stats/breed-category-rules`, { params })
    rules.value = data.rules || []
    total.value = data.total || 0
    page.value = p
    localStorage.setItem(PAGE_KEY, String(p))
  } catch (e) { console.error(e) }
  finally { loading.value = false }
}

async function doTest() {
  if (!testBreed.value.trim()) return
  try {
    const { data } = await axios.post(`${API}/stats/breed-category-rules/test`, { breed: testBreed.value.trim() })
    testResult.value = data
  } catch (e) { testResult.value = { hit: false } }
}

function formatDate(s) {
  if (!s) return '—'
  return s.slice(0, 16).replace('T', ' ')
}

async function loadCategoryOptions() {
  try {
    const { data } = await axios.get(`${API}/stats/breed-category-rules`, { params: { distinct_categories: 1 } })
    categoryOptions.value = data.categories || []
  } catch (e) { console.error(e) }
}

async function clearFilters() {
  keyword.value = ''
  categoryFilter.value = ''
  localStorage.removeItem(KEYWORD_KEY)
  localStorage.removeItem(FILTER_KEY)
  localStorage.removeItem(PAGE_KEY)
  page.value = 1
  loadRules(1)
}

onMounted(() => { if (page.value > 1) loadRules(page.value); else loadRules(1); loadCategoryOptions() })
</script>

<style scoped>
.bcr-page { padding: 0 28px 28px; }

/* Header */
.bcr-header {
  display: flex; justify-content: space-between; align-items: center;
  padding: 22px 0 16px;
  border-bottom: 1px solid rgba(255,255,255,0.06);
  margin-bottom: 16px;
}
.bcr-title { font-size: 18px; font-weight: 700; color: #e2e8f0; }
.bcr-subtitle { font-size: 12px; color: #64748b; margin-top: 3px; }
.bcr-header-stats { display: flex; gap: 20px; }
.bcr-stat { display: flex; flex-direction: column; align-items: center; gap: 2px; }
.bcr-stat-val { font-size: 18px; font-weight: 700; color: #38bdf8; }
.bcr-stat-key { font-size: 11px; color: #64748b; }

/* Toolbar */
.bcr-toolbar {
  display: flex; justify-content: space-between; align-items: center;
  margin-bottom: 14px; gap: 12px;
}
.bcr-toolbar-left { display: flex; gap: 10px; align-items: center; }
.bcr-toolbar-right { display: flex; gap: 8px; }
.bcr-search-wrap { position: relative; }
.bcr-search-icon { position: absolute; left: 10px; top: 50%; transform: translateY(-50%); font-size: 13px; }
.bcr-input {
  height: 36px; background: rgba(255,255,255,0.05); border: 1px solid rgba(255,255,255,0.1);
  border-radius: 8px; padding: 0 12px; font-size: 13px; color: #e2e8f0; outline: none;
}
.bcr-input::placeholder { color: #475569; }
.bcr-input:focus { border-color: rgba(56,189,248,0.5); background: rgba(56,189,248,0.05); }
.bcr-search-wrap .bcr-input { padding-left: 32px; }
.bcr-select {
  height: 36px; background: rgba(255,255,255,0.05); border: 1px solid rgba(255,255,255,0.1);
  border-radius: 8px; padding: 0 10px; font-size: 13px; color: #94a3b8; outline: none; cursor: pointer;
}
.bcr-select option { background: #1e293b; color: #e2e8f0; }

/* Buttons */
.bcr-btn {
  height: 36px; padding: 0 16px; border-radius: 8px; font-size: 13px;
  font-weight: 500; cursor: pointer; border: none; transition: all 0.15s;
}
.bcr-btn-cyan { background: rgba(56,189,248,0.1); color: #38bdf8; border: 1px solid rgba(56,189,248,0.2); }
.bcr-btn-cyan:hover { background: rgba(56,189,248,0.2); }
.bcr-btn-red { background: rgba(248,113,113,0.1); color: #f87171; border: 1px solid rgba(248,113,113,0.2); }
.bcr-btn-red:hover { background: rgba(248,113,113,0.2); }
.bcr-btn-red:disabled { opacity: 0.4; cursor: not-allowed; }

/* Help */
.bcr-help {
  background: rgba(15,23,42,0.6); border: 1px solid rgba(56,189,248,0.12);
  border-radius: 10px; padding: 16px 20px; margin-bottom: 12px;
}
.bcr-help-title { font-size: 13px; font-weight: 700; color: #38bdf8; margin-bottom: 14px; }
.bcr-help-grid {
  display: grid; grid-template-columns: 1fr 1fr 1fr;
  gap: 12px 24px;
}
.bcr-help-item { display: flex; gap: 10px; font-size: 11.5px; line-height: 1.7; }
.bcr-help-key { color: #38bdf8; font-weight: 600; white-space: nowrap; min-width: 70px; }
.bcr-help-val { color: #94a3b8; }
.bcr-help-val code {
  font-family: 'Courier New', monospace; font-size: 10px;
  color: #a5f3fc; background: rgba(56,189,248,0.06);
  border-radius: 3px; padding: 1px 4px;
}
.bcr-help-val strong { color: #e2e8f0; font-weight: 600; }

/* Panels */
.bcr-panel {
  background: rgba(255,255,255,0.03); border: 1px solid rgba(255,255,255,0.08);
  border-radius: 10px; padding: 16px; margin-bottom: 12px;
}
.bcr-panel-title { font-size: 13px; font-weight: 600; color: #94a3b8; margin-bottom: 12px; }
.bcr-test-row { display: flex; gap: 8px; align-items: center; }
.bcr-test-result { display: flex; align-items: center; gap: 8px; margin-top: 10px; font-size: 14px; }
.test-hit { color: #34d399; }
.test-miss { color: #94a3b8; }
.test-icon { font-size: 16px; }
.bcr-msg { margin-top: 8px; font-size: 12px; }
.msg-ok { color: #34d399; }
.msg-err { color: #f87171; }

/* Card / Table */
.bcr-card {
  background: rgba(255,255,255,0.02); border: 1px solid rgba(255,255,255,0.06);
  border-radius: 12px; overflow: hidden;
}
.table-scroll { overflow-x: auto; }
.bcr-table { width: 100%; border-collapse: collapse; font-size: 13px; }
.bcr-table th {
  padding: 11px 14px; text-align: left; font-weight: 600; font-size: 11px;
  color: #64748b; text-transform: uppercase; letter-spacing: 0.05em;
  background: rgba(255,255,255,0.03); border-bottom: 1px solid rgba(255,255,255,0.06);
  white-space: nowrap;
}
.bcr-table td { padding: 12px 14px; border-bottom: 1px solid rgba(255,255,255,0.04); vertical-align: middle; }
.bcr-row:hover td { background: rgba(56,189,248,0.03); }
.bcr-empty { text-align: center; color: #475569; padding: 36px !important; font-size: 13px; }

.bcr-breed { color: #e2e8f0; font-weight: 600; font-size: 13px; max-width: 70px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.bcr-cat {
  display: inline-block; background: rgba(56,189,248,0.1); color: #38bdf8;
  padding: 2px 9px; border-radius: 5px; font-size: 12px; font-weight: 500;
}
.bcr-src {
  display: inline-block; padding: 2px 9px; border-radius: 5px; font-size: 11px; font-weight: 600;
}
.src-ai { background: rgba(251,191,36,0.1); color: #fbbf24; }
.src-rules_migrated { background: rgba(56,189,248,0.1); color: #38bdf8; }
.src-manual { background: rgba(52,211,153,0.1); color: #34d399; }
.bcr-note { max-width: 160px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: #64748b; font-size: 12px; }
.bcr-date { color: #64748b; font-size: 12px; white-space: nowrap; }
.bcr-conf { font-weight: 700; font-size: 12px; }
.conf-high { color: #34d399; }
.conf-mid  { color: #fbbf24; }
.conf-low  { color: #f87171; }

/* Pagination */
.bcr-pagination { display: flex; align-items: center; gap: 4px; padding: 14px 16px; }
.bcr-page-btn {
  height: 32px; min-width: 32px; padding: 0 10px;
  background: rgba(255,255,255,0.04); border: 1px solid rgba(255,255,255,0.08);
  border-radius: 6px; color: #94a3b8; cursor: pointer; font-size: 13px;
  transition: all 0.15s;
}
.bcr-page-btn:hover:not(:disabled) { background: rgba(56,189,248,0.1); border-color: rgba(56,189,248,0.3); color: #38bdf8; }
.bcr-page-btn.active { background: rgba(56,189,248,0.15); border-color: rgba(56,189,248,0.4); color: #38bdf8; font-weight: 600; }
.bcr-page-btn:disabled { opacity: 0.3; cursor: not-allowed; }
.bcr-page-info { margin-left: 10px; font-size: 12px; color: #475569; white-space: nowrap; }

/* Transition */
.bcr-slide-enter-active, .bcr-slide-leave-active { transition: all 0.2s ease; overflow: hidden; }
.bcr-slide-enter-from, .bcr-slide-leave-to { opacity: 0; transform: translateY(-6px); }
</style>