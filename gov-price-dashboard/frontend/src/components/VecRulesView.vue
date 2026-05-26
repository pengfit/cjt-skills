<template>
  <div class="vec-page">
    <!-- Header -->
    <div class="vec-header">
      <div>
        <div class="vec-title">📦 规格规则库</div>
        <div class="vec-subtitle">存储在 rules_vec.db 中的规格解析正则规则，支持 attr / pattern / note / code 多维检索</div>
      </div>
      <span class="vec-total-badge">{{ vecRules.total }} 条规则</span>
    </div>

    <!-- Toolbar -->
    <div class="vec-toolbar">
      <div class="vec-toolbar-left">
        <input
          class="vec-input"
          v-model="vecSearch"
          placeholder="搜索 pattern / note / code..."
          @input="loadVecRules(1)"
        />
        <select class="vec-select" v-model="vecAttrFilter" @change="loadVecRules(1)">
          <option value="">全部属性</option>
          <option v-for="opt in vecAttrOptions" :key="opt.key" :value="opt.key">
            {{ opt.key }} ({{ opt.count }})
          </option>
        </select>
        <select class="vec-select" v-model="vecCatFilter" @change="loadVecRules(1)">
          <option value="">全部分类</option>
          <option v-for="opt in vecCatOptions" :key="opt.key" :value="opt.key">
            {{ opt.key === '（空）' ? '（空）' : opt.key }} ({{ opt.count }})
          </option>
        </select>
      </div>
      <button class="vec-help-btn" :class="{ active: showHelp }" @click="showHelp = !showHelp">
        {{ showHelp ? '🔼 收起' : '📖 使用说明' }}
      </button>
    </div>

    <!-- 使用说明 -->
    <Transition name="slide-down">
      <div class="vec-help" v-if="showHelp">
        <div class="vec-help-title">📖 规格规则库说明</div>
        <div class="vec-help-grid">
          <div class="vec-help-item">
            <span class="vec-help-key">字段说明</span>
            <span class="vec-help-val">
              <code>attr</code> — 属性名（如 thickness、width、material）<br/>
              <code>pattern</code> — 正则表达式，匹配规格字符串<br/>
              <code>note</code> — 规则注释<br/>
              <code>code</code> — Python 提取代码，执行 <code>re.search</code><br/>
              <code>category</code> — 适用分类（空=通用）<br/>
              <code>breed</code> — 适用品种/系列
            </span>
          </div>
          <div class="vec-help-item">
            <span class="vec-help-key">关键思路</span>
            <span class="vec-help-val">
              <strong>① RAG 召回</strong>：按 spec 语义检索相关规则，避免线性遍历<br/>
              <strong>② 混合相似度</strong>：keyword-set Jaccard + embedding cosine<br/>
              <strong>③ 先召回再执行</strong>：先找候选规则，再逐条正则匹配<br/>
              <strong>④ AI 兜底</strong>：无规则时调用 LLM 补全 category
            </span>
          </div>
          <div class="vec-help-item">
            <span class="vec-help-key">规则来源</span>
            <span class="vec-help-val">
              存储在 <code>rules_vec.db</code>，由 <code>etl/parse_spec</code> 管理。<br/>
              <code>transform_doc</code> 调用这些规则将 raw spec 解析为结构化 attr。
            </span>
          </div>
        </div>
      </div>
    </Transition>

    <!-- Table -->
    <div class="vec-table-wrap">
      <!-- Loading -->
      <div class="vec-loading" v-if="vecLoading">
        <div class="vec-spinner"></div>
        <span>加载中...</span>
      </div>

      <table class="vec-table" v-else>
        <thead>
          <tr>
            <th style="width:48px">#</th>
            <th style="width:90px">attr</th>
            <th style="width:90px">分类</th>
            <th>pattern</th>
            <th>note</th>
            <th>code</th>
            <th style="width:130px">创建时间</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(r, idx) in vecRules.items" :key="r.id">
            <td class="vec-id">{{ (vecRules.page - 1) * 50 + idx + 1 }}</td>
            <td><span class="vec-attr-tag">{{ r.attr }}</span></td>
            <td class="vec-cat">{{ r.category || '—' }}</td>
            <td><code class="vec-pattern" :title="r.pattern">{{ r.pattern }}</code></td>
            <td class="vec-note" :title="r.note || ''">{{ r.note || '—' }}</td>
            <td><pre class="vec-code" :title="r.code">{{ r.code }}</pre></td>
            <td class="vec-date">{{ r.created_at ? r.created_at.slice(0, 19) : '—' }}</td>
          </tr>
          <tr v-if="!vecRules.items?.length">
            <td colspan="7" class="vec-empty">
              <span v-if="vecSearch || vecAttrFilter">没有匹配「{{ vecSearch || vecAttrFilter }}」的规则</span>
              <span v-else>暂无数据</span>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- Pagination -->
    <div class="vec-pagination" v-if="vecRules.pages > 1">
      <button class="page-btn nav" :disabled="vecRules.page <= 1" @click="loadVecRules(vecRules.page - 1)">‹</button>
      <div class="vec-page-info">
        <span class="vec-page-current">{{ vecRules.page }}</span>
        <span class="vec-page-sep">/</span>
        <span class="vec-page-total">{{ vecRules.pages }}</span>
      </div>
      <button class="page-btn nav" :disabled="vecRules.page >= vecRules.pages" @click="loadVecRules(vecRules.page + 1)">›</button>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import axios from 'axios'

const API = import.meta.env.VITE_API_URL || '/api'

const vecRules = ref({ total: 0, page: 1, pages: 1, items: [], attr_options: [], category_options: [] })
const vecSearch = ref('')
const vecAttrFilter = ref('')
const vecCatFilter = ref('')
const vecAttrOptions = ref([])
const vecCatOptions = ref([])
const vecLoading = ref(false)
const showHelp = ref(false)

async function loadVecRules(page = 1) {
  vecLoading.value = true
  try {
    const params = { page, page_size: 50 }
    if (vecSearch.value) params.search = vecSearch.value
    if (vecAttrFilter.value) params.attr = vecAttrFilter.value
    if (vecCatFilter.value) params.category = vecCatFilter.value
    const res = await axios.get(`${API}/stats/rules-vector`, { params })
    vecRules.value = res.data || {}
    vecAttrOptions.value = res.data.attr_options || []
    vecCatOptions.value = res.data.category_options || []
  } catch(e) {
    console.warn('rules-vector failed', e)
  } finally {
    vecLoading.value = false
  }
}

onMounted(() => {
  loadVecRules()
})
</script>

<style scoped>
.vec-page {
  padding: 16px 20px 80px;
  min-height: 100vh;
  color: #e2e8f0;
  font-size: 13px;
}

/* Header */
.vec-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 16px;
}
.vec-title {
  font-size: 17px;
  font-weight: 700;
  color: #f1f5f9;
  letter-spacing: 0.3px;
}
.vec-subtitle {
  font-size: 11px;
  color: #475569;
  margin-top: 3px;
}
.vec-total-badge {
  font-size: 11px;
  background: rgba(56,189,248,0.1);
  color: #38bdf8;
  border: 1px solid rgba(56,189,248,0.2);
  border-radius: 10px;
  padding: 3px 10px;
  white-space: nowrap;
  margin-top: 2px;
}

/* Toolbar */
.vec-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  margin-bottom: 10px;
}
.vec-toolbar-left {
  display: flex;
  align-items: center;
  gap: 8px;
}
.vec-input {
  background: #1e293b;
  color: #e2e8f0;
  border: 1px solid rgba(255,255,255,0.12);
  border-radius: 6px;
  padding: 5px 12px;
  font-size: 12px;
  outline: none;
  transition: border-color 0.15s;
  width: 180px;
  box-sizing: border-box;
}
.vec-input:focus { border-color: #38bdf8; }
.vec-input::placeholder { color: #475569; }
.vec-select {
  background: #1e293b;
  color: #e2e8f0;
  border: 1px solid rgba(255,255,255,0.12);
  border-radius: 6px;
  padding: 5px 12px;
  font-size: 12px;
  cursor: pointer;
  outline: none;
  transition: border-color 0.15s;
  box-sizing: border-box;
  appearance: none;
  -webkit-appearance: none;
  background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 10 6'%3E%3Cpath d='M1 1l4 4 4-4' stroke='%2364748b' stroke-width='1.5' fill='none' stroke-linecap='round' stroke-linejoin='round'/%3E%3C/svg%3E");
  background-repeat: no-repeat;
  background-position: right 10px center;
  background-size: 10px;
  padding-right: 30px;
}
.vec-select:focus { border-color: #38bdf8; }
.vec-select option { background: #1e293b; color: #e2e8f0; }
.vec-help-btn {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  background: rgba(56,189,248,0.06);
  border: 1px solid rgba(56,189,248,0.15);
  border-radius: 20px;
  color: #38bdf8;
  font-size: 11.5px;
  font-weight: 500;
  padding: 5px 12px;
  cursor: pointer;
  transition: all 0.18s;
  white-space: nowrap;
}
.vec-help-btn:hover {
  background: rgba(56,189,248,0.12);
  border-color: rgba(56,189,248,0.3);
}
.vec-help-btn.active {
  background: rgba(56,189,248,0.15);
  border-color: rgba(56,189,248,0.35);
  box-shadow: 0 0 10px rgba(56,189,248,0.1);
}

/* Help */
.vec-help {
  background: rgba(255,255,255,0.025);
  border: 1px solid rgba(255,255,255,0.07);
  border-radius: 10px;
  padding: 14px 18px;
  margin-bottom: 12px;
}
.vec-help-title {
  font-size: 11px;
  font-weight: 600;
  color: #475569;
  text-transform: uppercase;
  letter-spacing: 0.8px;
  margin-bottom: 10px;
}
.vec-help-grid {
  display: grid;
  grid-template-columns: 1fr 1fr 1fr;
  gap: 12px 24px;
}
.vec-help-item { display: flex; gap: 10px; font-size: 11.5px; line-height: 1.7; }
.vec-help-key { color: #38bdf8; font-weight: 600; white-space: nowrap; min-width: 56px; }
.vec-help-val { color: #94a3b8; }
.vec-help-val code {
  font-family: 'Courier New', monospace;
  font-size: 10px;
  color: #a5f3fc;
  background: rgba(56,189,248,0.06);
  border-radius: 3px;
  padding: 1px 4px;
}
.vec-help-val strong { color: #e2e8f0; font-weight: 600; }

/* Slide transition */
.slide-down-enter-active, .slide-down-leave-active { transition: all 0.2s ease; overflow: hidden; }
.slide-down-enter-from, .slide-down-leave-to { opacity: 0; transform: translateY(-6px); }

/* Table */
.vec-table-wrap {
  border-radius: 10px;
  border: 1px solid rgba(255,255,255,0.07);
  overflow: hidden;
  background: rgba(15,23,42,0.6);
}
.vec-table { width: 100%; border-collapse: collapse; font-size: 12px; }
.vec-table th {
  background: rgba(255,255,255,0.03);
  color: #475569;
  font-size: 11px;
  font-weight: 600;
  padding: 9px 12px;
  text-align: left;
  white-space: nowrap;
  border-bottom: 1px solid rgba(255,255,255,0.07);
  letter-spacing: 0.3px;
}
.vec-table td {
  padding: 8px 12px;
  border-bottom: 1px solid rgba(255,255,255,0.04);
  vertical-align: top;
}
.vec-table tr:last-child td { border-bottom: none; }
.vec-table tr:hover td { background: rgba(255,255,255,0.025); }

/* Loading */
.vec-loading {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 10px;
  color: #475569;
  padding: 40px;
  font-size: 12px;
}
.vec-spinner {
  width: 18px;
  height: 18px;
  border: 2px solid rgba(255,255,255,0.08);
  border-top-color: rgba(56,189,248,0.6);
  border-radius: 50%;
  animation: spin 0.7s linear infinite;
}
@keyframes spin { to { transform: rotate(360deg); } }

/* Cells */
.vec-id { color: #334155; font-family: 'Courier New', monospace; font-size: 11px; }
.vec-attr-tag {
  display: inline-block;
  background: rgba(56,189,248,0.1);
  color: #38bdf8;
  border: 1px solid rgba(56,189,248,0.15);
  border-radius: 5px;
  padding: 2px 7px;
  font-size: 11px;
  font-weight: 600;
}
.vec-cat { color: #64748b; font-size: 11px; }
.vec-pattern {
  font-family: 'Courier New', monospace;
  font-size: 11px;
  color: #a5f3fc;
  background: rgba(56,189,248,0.05);
  border-radius: 4px;
  padding: 3px 6px;
  word-break: break-all;
  display: inline-block;
  max-width: 300px;
}
.vec-note {
  color: #6b7280;
  max-width: 180px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.vec-code {
  font-family: 'Courier New', monospace;
  font-size: 10px;
  color: #86efac;
  background: rgba(16,185,129,0.04);
  border-radius: 4px;
  padding: 3px 6px;
  white-space: pre;
  overflow: hidden;
  text-overflow: ellipsis;
  max-height: 38px;
  display: block;
}
.vec-date { color: #334155; white-space: nowrap; font-size: 11px; }
.vec-empty { text-align: center; color: #334155; padding: 32px; font-size: 12px; }

/* Pagination */
.vec-pagination {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 14px;
  margin-top: 14px;
}
.page-btn {
  background: rgba(255,255,255,0.05);
  border: 1px solid rgba(255,255,255,0.1);
  border-radius: 7px;
  color: #94a3b8;
  padding: 5px 14px;
  cursor: pointer;
  font-size: 14px;
  transition: all 0.15s;
}
.page-btn:hover:not(:disabled) { background: rgba(56,189,248,0.1); border-color: rgba(56,189,248,0.4); color: #38bdf8; }
.page-btn:disabled { opacity: 0.3; cursor: not-allowed; }
.vec-page-info { display: flex; align-items: center; gap: 4px; font-size: 12px; }
.vec-page-current { color: #e2e8f0; font-weight: 600; }
.vec-page-sep { color: #334155; }
.vec-page-total { color: #475569; }
</style>