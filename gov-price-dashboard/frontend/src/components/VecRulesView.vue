<template>
  <div class="vec-page">
    <div class="vec-header">
      <span class="vec-title">📦 规格规则库</span>
      <span class="vec-total-badge">{{ vecRules.total }} 条规则</span>
    </div>

    <div class="vec-toolbar">
      <input
        class="vec-search"
        v-model="vecSearch"
        placeholder="搜索 pattern / note / 代码..."
        @input="loadVecRules(1)"
      />
      <select class="vec-attr-select" v-model="vecAttrFilter" @change="loadVecRules(1)">
        <option value="">全部属性</option>
        <option v-for="opt in vecAttrOptions" :key="opt.key" :value="opt.key">
          {{ opt.key }} ({{ opt.count }})
        </option>
      </select>
      <button class="vec-help-btn" @click="showHelp = !showHelp">
        {{ showHelp ? '🔼 收起说明' : '🔽 使用说明' }}
      </button>
    </div>

    <!-- 使用说明 -->
    <div class="vec-help" v-if="showHelp">
      <div class="vec-help-title">📖 规格规则库说明</div>
      <div class="vec-help-grid">
        <div class="vec-help-item">
          <span class="vec-help-key">用途</span>
          <span class="vec-help-val">从 ODS 原始规格字符串中提取结构化属性（如厚度、宽度、材质等）的正则规则集。</span>
        </div>
        <div class="vec-help-item">
          <span class="vec-help-key">字段说明</span>
          <span class="vec-help-val">
            <code>attr</code> — 解析出的属性名（如 thickness、width、material）<br/>
            <code>pattern</code> — 正则表达式，用于匹配规格字符串<br/>
            <code>note</code> — 规则注释，说明该规则的用途<br/>
            <code>code</code> — Python 提取代码，通过 <code>re.search</code> 从字符串中提取对应值<br/>
            <code>category</code> — 适用的商品分类（空=通用）<br/>
            <code>breed</code> — 适用的商品品种/系列
          </span>
        </div>
        <div class="vec-help-item">
          <span class="vec-help-key">过滤方式</span>
          <span class="vec-help-val">
            · <strong>搜索框</strong>：模糊匹配 pattern / note / code 内容<br/>
            · <strong>属性下拉</strong>：按 attr 字段精确筛选（如只看 thickness 规则）
          </span>
        </div>
        <div class="vec-help-item">
          <span class="vec-help-key">规则来源</span>
          <span class="vec-help-val">存储在 <code>rules_vec.db</code> 中，由 etl/parse_spec 模块管理。ETL 流水线（transform_doc）调用这些规则将 raw spec 解析为结构化 attr。</span>
        </div>
      </div>
    </div>

    <div class="vec-table-wrap">
      <table class="vec-table">
        <thead>
          <tr>
            <th>ID</th>
            <th>attr</th>
            <th>分类</th>
            <th>pattern</th>
            <th>note</th>
            <th>code</th>
            <th>创建时间</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="r in vecRules.items" :key="r.id">
            <td class="vec-id">{{ r.id }}</td>
            <td><span class="vec-attr-tag">{{ r.attr }}</span></td>
            <td class="vec-cat">{{ r.category || '—' }}</td>
            <td><code class="vec-pattern">{{ r.pattern }}</code></td>
            <td class="vec-note">{{ r.note || '—' }}</td>
            <td><pre class="vec-code">{{ r.code }}</pre></td>
            <td class="vec-date">{{ r.created_at ? r.created_at.slice(0, 19) : '—' }}</td>
          </tr>
          <tr v-if="!vecRules.items?.length">
            <td colspan="7" class="vec-empty">暂无数据</td>
          </tr>
        </tbody>
      </table>
    </div>

    <div class="vec-pagination">
      <button class="page-btn nav" :disabled="vecRules.page <= 1" @click="loadVecRules(vecRules.page - 1)">‹</button>
      <span class="vec-page-info">{{ vecRules.page }} / {{ vecRules.pages }}</span>
      <button class="page-btn nav" :disabled="vecRules.page >= vecRules.pages" @click="loadVecRules(vecRules.page + 1)">›</button>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import axios from 'axios'

const API = import.meta.env.VITE_API_URL || '/api'

const vecRules = ref({ total: 0, page: 1, pages: 1, items: [], attr_options: [] })
const vecSearch = ref('')
const vecAttrFilter = ref('')
const vecAttrOptions = ref([])
const vecLoading = ref(false)
const showHelp = ref(false)

async function loadVecRules(page = 1) {
  vecLoading.value = true
  try {
    const params = { page, page_size: 50 }
    if (vecSearch.value) params.search = vecSearch.value
    if (vecAttrFilter.value) params.attr = vecAttrFilter.value
    const res = await axios.get(`${API}/stats/rules-vector`, { params })
    vecRules.value = res.data || {}
    vecAttrOptions.value = res.data.attr_options || []
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
.vec-header {
  display: flex;
  align-items: center;
  gap: 16px;
  margin-bottom: 16px;
}
.vec-title {
  font-size: 16px;
  font-weight: 700;
  color: #f1f5f9;
}
.vec-total-badge {
  font-size: 11px;
  background: rgba(56,189,248,0.12);
  color: #38bdf8;
  border-radius: 10px;
  padding: 2px 8px;
}
.vec-toolbar {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 14px;
}
.vec-search {
  background: rgba(255,255,255,0.05);
  border: 1px solid rgba(255,255,255,0.1);
  border-radius: 6px;
  color: #e2e8f0;
  font-size: 12px;
  padding: 6px 12px;
  width: 200px;
  outline: none;
}
.vec-search:focus { border-color: #38bdf8; }
.vec-attr-select {
  background: rgba(255,255,255,0.05);
  border: 1px solid rgba(255,255,255,0.1);
  border-radius: 6px;
  color: #e2e8f0;
  font-size: 12px;
  padding: 6px 10px;
  outline: none;
  cursor: pointer;
}
.vec-attr-select option { background: #1e293b; }
.vec-help-btn {
  margin-left: auto;
  background: rgba(255,255,255,0.04);
  border: 1px solid rgba(255,255,255,0.08);
  border-radius: 6px;
  color: #64748b;
  font-size: 11px;
  padding: 4px 10px;
  cursor: pointer;
  transition: all 0.15s;
}
.vec-help-btn:hover { background: rgba(255,255,255,0.08); color: #94a3b8; }
.vec-help {
  background: rgba(255,255,255,0.03);
  border: 1px solid rgba(255,255,255,0.07);
  border-radius: 8px;
  padding: 14px 16px;
  margin-bottom: 14px;
}
.vec-help-title {
  font-size: 12px;
  font-weight: 600;
  color: #94a3b8;
  margin-bottom: 10px;
}
.vec-help-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px 20px;
}
.vec-help-item { display: flex; gap: 10px; font-size: 11px; line-height: 1.6; }
.vec-help-key { color: #38bdf8; font-weight: 600; white-space: nowrap; min-width: 60px; }
.vec-help-val { color: #94a3b8; }
.vec-help-val code {
  font-family: 'Courier New', monospace;
  font-size: 10px;
  color: #a5f3fc;
  background: rgba(56,189,248,0.07);
  border-radius: 3px;
  padding: 1px 4px;
}
.vec-table-wrap { overflow-x: auto; border-radius: 8px; border: 1px solid rgba(255,255,255,0.06); }
.vec-table { width: 100%; border-collapse: collapse; font-size: 12px; }
.vec-table th {
  background: rgba(255,255,255,0.04);
  color: #64748b;
  font-weight: 600;
  padding: 8px 12px;
  text-align: left;
  white-space: nowrap;
  border-bottom: 1px solid rgba(255,255,255,0.06);
  position: sticky;
  top: 0;
}
.vec-table td {
  padding: 7px 12px;
  border-bottom: 1px solid rgba(255,255,255,0.04);
  vertical-align: top;
}
.vec-table tr:hover td { background: rgba(255,255,255,0.02); }
.vec-id { color: #475569; font-family: monospace; width: 40px; }
.vec-attr-tag {
  display: inline-block;
  background: rgba(56,189,248,0.1);
  color: #38bdf8;
  border-radius: 4px;
  padding: 2px 7px;
  font-size: 11px;
  font-weight: 600;
}
.vec-cat { color: #94a3b8; font-size: 11px; }
.vec-pattern {
  font-family: 'Courier New', monospace;
  font-size: 11px;
  color: #a5f3fc;
  background: rgba(56,189,248,0.06);
  border-radius: 3px;
  padding: 2px 5px;
  word-break: break-all;
  max-width: 200px;
  display: inline-block;
}
.vec-note { color: #94a3b8; max-width: 150px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.vec-code {
  font-family: 'Courier New', monospace;
  font-size: 10px;
  color: #86efac;
  background: rgba(16,185,129,0.06);
  border-radius: 3px;
  padding: 3px 6px;
  white-space: pre;
  max-width: 300px;
  overflow: hidden;
  text-overflow: ellipsis;
  max-height: 42px;
  display: block;
}
.vec-date { color: #475569; white-space: nowrap; font-size: 11px; }
.vec-empty { text-align: center; color: #334155; padding: 24px; }
.vec-pagination { display: flex; align-items: center; justify-content: center; gap: 12px; margin-top: 14px; }
.vec-page-info { font-size: 12px; color: #64748b; }
.page-btn {
  background: rgba(255,255,255,0.05);
  border: 1px solid rgba(255,255,255,0.1);
  border-radius: 6px;
  color: #94a3b8;
  padding: 4px 12px;
  cursor: pointer;
  font-size: 13px;
  transition: all 0.15s;
}
.page-btn:hover:not(:disabled) { background: rgba(56,189,248,0.1); border-color: #38bdf8; color: #38bdf8; }
.page-btn:disabled { opacity: 0.35; cursor: not-allowed; }
</style>