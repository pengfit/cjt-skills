<template>
  <div class="vec-page">
    <!-- Header -->
    <PageHeader
      variant="flat"
      title="规格规则库"
      subtitle="存储在 rules_vec.db 中的规格解析正则规则，支持 attr / pattern / note / code 多维检索"
      :stats="[{ label: '规则总数', value: fmtInt(vecRules.total) }]"
    />

    <!-- Toolbar -->
    <div class="vec-toolbar">
      <div class="vec-toolbar-left">
        <input class="vec-input" v-model="vecSearch" placeholder="搜索 pattern / note / code..." @input="loadVecRules(1)" />
        <CustomSelect
          v-model="vecAttrFilter"
          :options="vecAttrOptions.map(o => ({ key: o.key, label: o.key, count: o.count }))"
          placeholder="全部属性"
          :searchable="false"
          :count-suffix="true"
          @change="loadVecRules(1)"
        />
        <CustomSelect
          v-model="vecCatFilter"
          :options="vecCatOptions.map(o => ({ key: o.key, label: o.key === '（空）' ? '（空）' : o.key, count: o.count }))"
          placeholder="全部分类"
          :searchable="false"
          :count-suffix="true"
          @change="loadVecRules(1)"
        />
      </div>
      <div class="vec-toolbar-right">
        <button class="vec-order-btn" @click="toggleOrder" title="切换升序/降序">
          {{ vecOrder === 'desc' ? '🔽 最新优先' : '🔼 最早优先' }}
        </button>
        <!-- v0.7.1 起：仅查询/查看，隐藏新增入口。后端 POST 端点保留备查。 -->
        <button class="vec-help-btn" :class="{ active: showHelp }" @click="showHelp = !showHelp">
          {{ showHelp ? '🔼 收起' : '📖 使用说明' }}
        </button>
      </div>
    </div>

    <!-- 使用说明 -->
    <Transition name="slide-down">
      <div class="vec-help" v-if="showHelp">
        <div class="vec-help-title">📖 规格规则库说明</div>
        <div class="vec-help-grid">
          <div class="vec-help-item">
            <span class="vec-help-key">是什么</span>
            <span class="vec-help-val">
              规格解析用的 <strong>规则向量库</strong>，存于 <code>skills/data/breed_spec_rules.db</code>（SQLite）<br/>
              ETL 阶段 2（DWD→DWS）依赖它把 <code>spec</code> 拆成 <code>length/width/height</code> 等 attr<br/>
              详见仓库根目录 <code>gov-price-etl/SPEC_RULES.md</code>
            </span>
          </div>
          <div class="vec-help-item">
            <span class="vec-help-key">本页能做什么</span>
            <span class="vec-help-val">
              <strong>只读查询</strong>：搜索 · attr 筛选 · 分类筛选 · 升降序 · 分页<br/>
              新增 / 编辑 / 删除 <strong>不在本页</strong>，统一走后端 API 或 SQL（见「补充规则」）
            </span>
          </div>
          <div class="vec-help-item">
            <span class="vec-help-key">怎么召回</span>
            <span class="vec-help-val">
              <code>spec</code> 与规则都生成 <strong>结构语义标签</strong>（三段/LWW/长宽高/数字 等）<br/>
              按 <strong>Jaccard</strong> = <code>|A∩B| / |A∪B|</code> 打分，score ≥ <code>0.001</code> 入选<br/>
              按 attr 槽位独立竞争，同 attr+pattern 去重保留最高分
            </span>
          </div>
          <div class="vec-help-item">
            <span class="vec-help-key">一行记录</span>
            <span class="vec-help-val">
              <code>pattern</code> 正则（不含 r 前缀）→ 命中 spec 某段<br/>
              <code>attr</code> 该段落到哪个属性 · <code>code</code> 提取代码（可空）<br/>
              <code>breed / category</code> 适用范围（空=通用）· <code>tokens</code> 结构标签（自动生成）
            </span>
          </div>
          <div class="vec-help-item">
            <span class="vec-help-key">补充规则</span>
            <span class="vec-help-val">
              <strong>① API</strong>：<code>POST/PUT/DELETE /api/stats/rules-vector</code><br/>
              <strong>② CLI</strong>：<code>python3 commands/parse_spec/rules/vector_store.py</code>（ETL 内部）<br/>
              <strong>③ SQL</strong>：<code>sqlite3 skills/data/breed_spec_rules.db</code>
            </span>
          </div>
          <div class="vec-help-item">
            <span class="vec-help-key">解析兜底</span>
            <span class="vec-help-val">
              所有 attr 槽位都没命中 → 返回空 <strong>不降级</strong><br/>
              走 <code>POST /api/stats/spec-quality/fix-case</code>，AI 给 <code>expected</code> 后回写规则库
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

      <table class="data-table no-row-hover" v-else>
        <thead>
          <tr>
            <th style="width:40px" class="no-sort">#</th>
            <th style="width:120px" class="no-sort">breed</th>
            <th style="width:90px" class="no-sort">attr</th>
            <th style="width:80px" class="no-sort">分类</th>
            <th style="width:160px" class="no-sort">pattern</th>
            <th style="width:350px" class="text-left no-sort">code</th>
            <th style="width:140px" class="no-sort">note</th>
            <th style="width:130px" class="no-sort">创建时间</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(r, idx) in vecRules.items" :key="r.id">
            <td class="vec-id">
              <div class="vec-row-id-wrap">
                <!-- v0.7 起仅显示序号，编辑/删除入口隐藏（按需可恢复后端端点）。
                     表內变更统一走 “修改 · 查 · 网" 表 (rules_vec.db / ParseSpec 端) —— -->
                <span>{{ (vecRules.page - 1) * 50 + idx + 1 }}</span>
              </div>
            </td>
            <td class="vec-breed" :title="r.breed">{{ r.breed || '—' }}</td>
            <td><span class="vec-attr-tag">{{ r.attr }}</span></td>
            <td>{{ r.category || '—' }}</td>
            <td class="vec-pattern-cell"><code class="vec-pattern" :title="r.pattern">{{ r.pattern }}</code></td>
            <td class="vec-code-cell text-left no-ellipsis"><pre class="vec-code-block" v-html="highlightPy(r.code || '')"></pre></td>
            <td class="vec-note-cell">{{ r.note || '—' }}</td>
            <td class="vec-date">{{ r.created_at ? r.created_at.slice(0, 19) : '—' }}</td>
          </tr>
          <tr v-if="!vecRules.items?.length">
            <td colspan="8">
              <EmptyState compact
                :title="vecSearch || vecAttrFilter ? `没有匹配「${vecSearch || vecAttrFilter}」的规则` : '暂无规则'"
                message="点击右上角【使用说明】了解如何添加规则" />
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- Pagination -->
    <div class="vec-pagination" v-if="vecRules.pages > 1">
      <button class="page-btn nav" :disabled="vecRules.page <= 1" @click="loadVecRules(vecRules.page - 1)">‹</button>
      <button
        v-for="p in vecPageRange" :key="p"
        class="page-btn"
        :class="{ active: Number(p) === Number(vecRules.page), ellipsis: p === '...' }"
        :disabled="p === '...'"
        @click="p !== '...' && loadVecRules(Number(p))"
      >{{ p }}</button>
      <button class="page-btn nav" :disabled="vecRules.page >= vecRules.pages" @click="loadVecRules(vecRules.page + 1)">›</button>
      <div class="page-jump-wrap">
        <span>跳至</span>
        <input class="page-jump" v-model.number="vecJumpPage" @keyup.enter="goToVecPage" type="number" min="1" :max="vecRules.pages" />
        <span>页</span>
      </div>
      <div class="page-size-wrap">
        <span>每页</span>
        <select class="page-size-select" v-model.number="vecPageSize" @change="loadVecRules(1)">
          <option v-for="s in vecPageSizeOptions" :key="s" :value="s">{{ s }}</option>
        </select>
        <span>条</span>
      </div>
    </div>

    <!-- v0.7.1 起：新增/编辑对话框入口隐藏(只读视图)。相关 state + 函数保留为注释备查。 -->
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import axios from 'axios'

import CustomSelect from './CustomSelect.vue'
import PageHeader from './PageHeader.vue'
import EmptyState from './EmptyState.vue'
import { fmtInt } from '../composables/useFormatNumber.js'

const API = import.meta.env.VITE_API_URL || '/api'

const vecRules = ref({ total: 0, page: 1, pages: 1, items: [], attr_options: [], category_options: [] })
const vecPageSize = ref(50)
const vecPageSizeOptions = [50, 100, 200]
const vecJumpPage = ref(1)

const vecPageRange = computed(() => {
  const tp = vecRules.value.pages
  const cur = vecRules.value.page
  if (!tp) return []
  if (tp <= 7) return Array.from({ length: tp }, (_, i) => i + 1)
  const set = new Set([1, tp, cur, cur - 1, cur + 1])
  const list = [...set].filter(n => n >= 1 && n <= tp).sort((a, b) => a - b)
  const out = []
  for (let i = 0; i < list.length; i++) {
    if (i > 0 && list[i] - list[i - 1] > 1) out.push('...')
    out.push(list[i])
  }
  return out
})

function goToVecPage() {
  const p = Number(vecJumpPage.value)
  if (p >= 1 && p <= vecRules.value.pages && p !== vecRules.value.page) {
    loadVecRules(p)
  }
}
const vecSearch = ref('')
const vecAttrFilter = ref('')
const vecCatFilter = ref('')
const vecOrder = ref('desc')
const vecAttrOptions = ref([])
const vecCatOptions = ref([])
const vecLoading = ref(false)
const showHelp = ref(false)

// ── 新增/编辑对话框状态（v0.7.1 起隐藏；保留备查） ─────────────────
// const showDialog = ref(false)
// const dialogMode = ref('add')  // 'add' | 'edit'
// const dialogSaving = ref(false)
// const dialogError = ref('')
// const dialogEditingId = ref(null)
// const dialogForm = ref({
//   pattern: '',
//   attr: '',
//   note: '',
//   breed: '',
//   category: '',
//   code: '',
// })

// function openAddDialog() {
//   dialogMode.value = 'add'
//   dialogEditingId.value = null
//   dialogForm.value = { pattern: '', attr: '', note: '', breed: '', category: '', code: '' }
//   dialogError.value = ''
//   showDialog.value = true
// }

// v0.7 起：编辑按钮隐藏，该函数不再被调用。保留备查。
// function openEditDialog(rule) {
//   dialogMode.value = 'edit'
//   dialogEditingId.value = rule.id
//   dialogForm.value = {
//     pattern: rule.pattern || '',
//     attr: rule.attr || '',
//     note: rule.note || '',
//     breed: rule.breed || '',
//     category: rule.category || '',
//     code: rule.code || '',
//   }
//   dialogError.value = ''
//   showDialog.value = true
// }

// v0.7.1 起：对话框提交函数隐藏。保留备查（后端 POST/PUT 端点仍可用）。
// async function submitDialog() {
//   dialogError.value = ''
//   if (!dialogForm.value.pattern.trim() || !dialogForm.value.attr.trim()) {
//     dialogError.value = 'pattern 和 attr 必填'
//     return
//   }
//   dialogSaving.value = true
//   try {
//     if (dialogMode.value === 'add') {
//       await axios.post(`${API}/stats/rules-vector`, dialogForm.value)
//     } else {
//       await axios.put(`${API}/stats/rules-vector/${dialogEditingId.value}`, dialogForm.value)
//     }
//     showDialog.value = false
//     await loadVecRules(vecRules.value.page)
//   } catch (e) {
//     dialogError.value = e?.response?.data?.detail || e.message
//   } finally {
//     dialogSaving.value = false
//   }
// }

// v0.7 起：删除按钮隐藏，该函数不再被调用。保留备查。
// async function confirmDelete(rule) {
//   if (!window.confirm(`确认删除规则 #${rule.id}？\npattern: ${rule.pattern}\nattr: ${rule.attr}`)) return
//   try {
//     await axios.delete(`${API}/stats/rules-vector/${rule.id}`)
//     await loadVecRules(vecRules.value.page)
//   } catch (e) {
//     alert('删除失败：' + (e?.response?.data?.detail || e.message))
//   }
// }

function escapeHtml(s) {
  return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')
}

function highlightPy(code) {
  if (!code) return ''
  return code
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/(#[^\n]*)/g, '<span class="cm-comment">$1</span>')
    .replace(/(\'[^\n]*\'|"[^\n]*")/g, '<span class="cm-string">$1</span>')
    .replace(/\b(re|match|search|find|group|compile|sub|exec|print|if|else|elif|for|while|return|in|not|and|or|True|False|None)\b/g, '<span class="cm-keyword">$1</span>')
    .replace(/\b(\d+\.?\d*)\b/g, '<span class="cm-number">$1</span>')
    .replace(/\b(r['"])/g, '<span class="cm-string">$1</span>')
}

async function loadVecRules(page = 1) {
  vecLoading.value = true
  try {
    const params = { page, page_size: vecPageSize.value, order: vecOrder.value }
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

function toggleOrder() {
  vecOrder.value = vecOrder.value === 'desc' ? 'asc' : 'desc'
  loadVecRules(1)
}

onMounted(() => {
  loadVecRules()
})


</script>

<style scoped>
.vec-page {
  display: block;
  padding: 16px 20px 0;
  color: #1e293b;
  font-size: 13px;
  padding-bottom: 64px;
}

/* Header（已迁移至 PageHeader flat 变体） */

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
  background: #ffffff;
  color: #1e293b;
  border: 1px solid rgba(241,245,249,0.6);
  border-radius: var(--radius-sm);
  padding: 8px 10px;
  font-size: 13px;
  outline: none;
  transition: border-color 0.15s, box-shadow 0.15s;
  width: 240px;
  box-sizing: border-box;
  font-family: inherit;
}
.vec-input:focus { border-color: var(--primary); box-shadow: 0 0 0 3px rgba(37,99,235,0.4); }
.vec-toolbar-right { display: flex; align-items: center; gap: 8px; }
.vec-order-btn {
  display: inline-flex; align-items: center; gap: 5px;
  background: rgba(37,99,235,0.08); border: 1px solid rgba(37,99,235,0.25);
  border-radius: 20px; color: var(--primary); font-size: 11.5px;
  font-weight: 500; padding: 5px 12px; cursor: pointer; transition: all 0.18s;
}
.vec-order-btn:hover { background: rgba(37,99,235,0.16); border-color: rgba(37,99,235,0.4); }
.vec-input::placeholder { color: #475569; }
.vec-help-btn {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  background: rgba(37,99,235,0.06);
  border: 1px solid rgba(37,99,235,0.15);
  border-radius: 20px;
  color: var(--primary);
  font-size: 11.5px;
  font-weight: 500;
  padding: 5px 12px;
  cursor: pointer;
  transition: all 0.18s;
  white-space: nowrap;
}
.vec-help-btn:hover {
  background: rgba(37,99,235,0.12);
  border-color: rgba(37,99,235,0.3);
}
.vec-help-btn.active {
  background: rgba(37,99,235,0.15);
  border-color: rgba(37,99,235,0.35);
  box-shadow: 0 0 10px rgba(37,99,235,0.1);
}

/* Help */
.vec-help {
  background: rgba(241,245,249,0.8); border: 1px solid rgba(37,99,235,0.12);
  border-radius: 10px; padding: 16px 20px; margin-bottom: 12px;
}
.vec-help-title {
  font-size: 13px; font-weight: 700; color: var(--primary); margin-bottom: 14px;
}
.vec-help-grid {
  display: grid;
  grid-template-columns: 1fr 1fr 1fr;
  gap: 12px 24px;
}
.vec-help-item { display: flex; gap: 10px; font-size: 11.5px; line-height: 1.7; }
.vec-help-key { color: var(--primary); font-weight: 600; white-space: nowrap; min-width: 56px; }
.vec-help-val { color: var(--text-3); }
.vec-help-val code {
  font-family: 'Courier New', monospace;
  font-size: 10px;
  color: var(--primary);
  background: rgba(37,99,235,0.08);
  border-radius: 3px;
  padding: 1px 4px;
  font-weight: 500;
}
.vec-help-val strong { color: #1e293b; font-weight: 600; }

/* Slide transition */
.slide-down-enter-active, .slide-down-leave-active { transition: all 0.2s ease; overflow: hidden; }
.slide-down-enter-from, .slide-down-leave-to { opacity: 0; transform: translateY(-6px); }

/* Table */
.vec-table-wrap {
  border-radius: 10px;
  border: 1px solid var(--border);
  background: var(--surface);
  box-shadow: var(--shadow);
  overflow-x: hidden;
}
/* vec-table 已迁移至全局 .data-table */
.vec-table td { padding: 8px 12px; }

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
  border: 2px solid rgba(15,23,42,0.08);
  border-top-color: rgba(37,99,235,0.6);
  border-radius: 50%;
  animation: spin 0.7s linear infinite;
}
@keyframes spin { to { transform: rotate(360deg); } }

/* Cells */
.vec-id { color: var(--text-2, #475569); font-family: 'Courier New', monospace; font-size: 11px; }
.vec-attr-tag {
  display: inline-block;
  background: rgba(37,99,235,0.1);
  color: var(--primary);
  border: 1px solid rgba(37,99,235,0.15);
  border-radius: 5px;
  padding: 2px 7px;
  font-size: 11px;
  font-weight: 600;
}
.vec-cat { color: var(--text-3); font-size: 11px; }
.vec-pattern, .vec-code {
  font-family: 'Courier New', monospace;
  font-size: 11px;
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-radius: 4px;
  padding: 3px 6px;
  word-break: break-all;
  display: inline-block;
  max-width: 300px;
}
.vec-pattern { color: var(--primary); font-weight: 600; }
.vec-code-block {
  background: #0d1117;
  border: 1px solid #30363d;
  border-radius: 4px;
  padding: 4px 6px;
  font-family: 'Courier New', monospace;
  font-size: 11px;
  color: #c9d1d9;
  white-space: pre-wrap;
  word-break: break-all;
  line-height: 1.4;
  overflow-x: auto;
}
.vec-code-block .cm-comment { color: #8b949e; }
.vec-code-block .cm-string { color: #a5d6ff; }
.vec-code-block .cm-keyword { color: #ff7b72; }
.vec-code-block .cm-number { color: #79c0ff; }
.vec-code-block .cm-func { color: #d2a8ff; }
.vec-code-cell { width: 350px; overflow: hidden; }
.vec-note-cell { color: #6b7288; font-size: 12px; width: 140px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.vec-pattern-cell { width: 160px; }
.vec-breed { color: var(--text-3); font-size: 11px; max-width: 100px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.vec-date { color: var(--text-3, #94a3b8); white-space: nowrap; font-size: 11px; }


/* Pagination — 沿用全局 `.pagination` / `.page-btn` 样式 */
.vec-pagination {
  position: sticky;
  bottom: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 5px;
  padding: 12px 18px;
  border-top: 1px solid rgba(15,23,42,0.08);
  background: rgba(241,245,249,0.95);
  backdrop-filter: blur(8px);
  flex-shrink: 0;
  margin-top: 12px;
  border-radius: 10px;
  z-index: 5;
}
</style>

/* ── 新增/编辑对话框样式（fix 2026-07-12） ───────────────── */
.vec-add-btn {
  padding: 6px 12px;
  background: var(--primary, #2563eb);
  color: white;
  border: none;
  border-radius: 6px;
  font-size: 13px;
  cursor: pointer;
}
.vec-add-btn:hover { background: #1d4ed8; }

.vec-row-id-wrap { display: flex; align-items: center; gap: 6px; }
.vec-row-actions { display: none; gap: 2px; }
.vec-row-id-wrap:hover .vec-row-actions { display: inline-flex; }
.vec-action-btn {
  background: transparent;
  border: none;
  cursor: pointer;
  font-size: 13px;
  padding: 2px 4px;
  border-radius: 4px;
}
.vec-action-btn:hover { background: rgba(15, 23, 42, 0.06); }
.vec-action-btn.danger:hover { background: rgba(239, 68, 68, 0.08); }

.vec-modal-mask {
  position: fixed; inset: 0;
  background: rgba(15, 23, 42, 0.4);
  z-index: 100;
  display: flex; align-items: center; justify-content: center;
  padding: 20px;
}
.vec-modal {
  background: white;
  border-radius: 12px;
  width: 100%;
  max-width: 560px;
  max-height: 90vh;
  display: flex; flex-direction: column;
  box-shadow: 0 20px 50px rgba(0,0,0,0.2);
}
.vec-modal-header {
  padding: 16px 20px;
  border-bottom: 1px solid rgba(15,23,42,0.08);
  display: flex; align-items: center; justify-content: space-between;
}
.vec-modal-title { font-size: 16px; font-weight: 600; }
.vec-modal-close {
  cursor: pointer; font-size: 18px; color: #94a3b8;
  padding: 4px 8px; border-radius: 4px;
}
.vec-modal-close:hover { background: rgba(15,23,42,0.06); }
.vec-modal-body { padding: 20px; overflow-y: auto; }
.vec-form-row { margin-bottom: 14px; display: flex; flex-direction: column; gap: 4px; }
.vec-form-label {
  font-size: 13px; font-weight: 500; color: #475569;
  display: flex; align-items: center; gap: 8px;
}
.vec-form-hint { font-size: 11px; color: #94a3b8; font-weight: 400; }
.vec-form-input, .vec-form-textarea {
  padding: 8px 12px;
  border: 1px solid rgba(15,23,42,0.12);
  border-radius: 6px;
  font-size: 13px;
  font-family: inherit;
  outline: none;
  transition: border-color 0.15s;
}
.vec-form-input:focus, .vec-form-textarea:focus {
  border-color: var(--primary, #2563eb);
}
.vec-form-textarea { font-family: ui-monospace, monospace; font-size: 12px; resize: vertical; }
.vec-form-error {
  color: #dc2626; font-size: 13px;
  padding: 8px 12px;
  background: rgba(239, 68, 68, 0.06);
  border-radius: 6px;
  margin-top: 8px;
}
.vec-modal-footer {
  padding: 14px 20px;
  border-top: 1px solid rgba(15,23,42,0.08);
  display: flex; justify-content: flex-end; gap: 8px;
}
.btn-ghost {
  padding: 8px 16px; border: 1px solid rgba(15,23,42,0.12);
  background: white; border-radius: 6px; cursor: pointer; font-size: 13px;
}
.btn-ghost:hover { background: rgba(15,23,42,0.04); }
.btn-primary {
  padding: 8px 16px; background: var(--primary, #2563eb);
  color: white; border: none; border-radius: 6px;
  cursor: pointer; font-size: 13px;
}
.btn-primary:hover:not(:disabled) { background: #1d4ed8; }
.btn-primary:disabled { opacity: 0.5; cursor: not-allowed; }
