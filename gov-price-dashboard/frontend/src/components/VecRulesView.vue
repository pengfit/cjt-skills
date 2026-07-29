<template>
  <div class="admin-page">
    <!-- PageHeader (matching /taxonomy flat variant) -->
    <PageHeader
      variant="flat"
      title="规格规则库"
      subtitle="存储在 <code>breed_spec_rules.db</code>（SQLite + Blob），ETL DWD→DWS 阶段 3 AI 自动回写；本页支持 <code>pattern+attr+code</code> 多维检索"
      :stats="[
        { label: '规则总数', value: fmt.int(vecRules.total) },
        { label: '当前页', value: `${vecRules.page} / ${vecRules.pages || 1}` },
      ]"
    />

    <!-- Toolbar(2026-07-29 彻底统一:与 /taxonomy 同款 .ctx-search-wrap,删 chips / 📖 / × 输入清空按钮) -->
    <div class="ctx-toolbar">
      <div class="ctx-search-wrap">
        <span class="ctx-search-icon">🔍</span>
        <input
          class="ctx-input"
          v-model="vecSearch"
          placeholder="搜索 pattern / note / code..."
          @input="loadVecRules(1)"
        />
      </div>
    </div>

    <!-- 2026-07-28:Phase 2 — 自研 CSS Grid 改 Element Plus <el-table> -->
    <div class="vec-table-wrap">
      <el-table
        v-loading="vecLoading"
        :data="vecRules.items || []"
        stripe
        class="vec-el-table"
        empty-text="暂无规则"
        :row-key="(r) => r.id"
      >
        <el-table-column type="index" :index="(i) => (vecRules.page - 1) * vecPageSize + i + 1" label="#" width="60" align="center" />
        <el-table-column prop="breed" label="breed" min-width="160" show-overflow-tooltip>
          <template #default="{ row }">
            <span :title="row.breed">{{ row.breed || '—' }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="attr" label="属性" width="120" align="center">
          <template #default="{ row }">
            <span class="vec-attr-tag">{{ row.attr || '—' }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="l3" label="L3 分项" width="120" align="center">
          <template #default="{ row }">{{ row.l3 || '—' }}</template>
        </el-table-column>
        <el-table-column prop="pattern" label="pattern" min-width="180">
          <template #default="{ row }">
            <code class="vec-pattern" :title="row.pattern">{{ row.pattern }}</code>
          </template>
        </el-table-column>
        <el-table-column label="code" min-width="220">
          <template #default="{ row }">
            <pre class="vec-code-block" v-html="highlightPy(row.code || '')"></pre>
          </template>
        </el-table-column>
        <el-table-column prop="note" label="note" min-width="160" show-overflow-tooltip>
          <template #default="{ row }">{{ row.note || '—' }}</template>
        </el-table-column>
        <el-table-column label="创建时间" width="180">
          <template #default="{ row }">
            {{ row.created_at ? row.created_at.slice(0, 19) : '—' }}
          </template>
        </el-table-column>
      </el-table>
    </div>

    <!-- 分页(2026-07-29 彻底统一:换 <AppPagination> 与 /taxonomy 一致;pageSize 默认 20,options [20,50,100]) -->
    <AppPagination
      :current="vecRules.page"
      :total="vecRules.total"
      :page-size="vecPageSize"
      :page-size-options="vecPageSizeOptions"
      show-size-changer
      info-template="第 {from}-{to} 条 / 共 {total} 条"
      @change="loadVecRules"
      @update:page-size="vecPageSize = $event; loadVecRules(1)"
    />
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'

import PageHeader from './PageHeader.vue'
import AppPagination from './AppPagination.vue'
import { useFormatNumber } from '../composables/useFormatNumber.js'
import { useFetch } from '../composables/useFetch.js'  // 2026-07-28: 统一 fetch composable (Step 2)

const fmt = useFormatNumber()
// 2026-07-28: 用 useFetch 取代手写 loading/axios.get/catch/finally 模板
//   vecLoading 由 composable 自动管理,vecFetch() 内部带 abort 防止 stale 覆盖
const { loading: vecLoading, fetch: vecFetch } = useFetch()

// ── 表格 CSS Grid 列模板 (fr 比例，等宽分布) ──
const GRID_COLS = '52px minmax(110px, 1.4fr) minmax(90px, 1fr) minmax(110px, 1.1fr) minmax(150px, 1.6fr) minmax(260px, 2.4fr) minmax(120px, 1fr) minmax(150px, 1fr)'

// ── 响应式状态 ──
const vecRules = ref({ total: 0, page: 1, pages: 1, items: [] })
const vecPageSize = ref(20)
const vecPageSizeOptions = [20, 50, 100]

const vecSearch = ref('')
const vecOrder = ref('desc')

// ── 网络(2026-07-28 Step 2:用 useFetch 统一) ──
async function loadVecRules(page = 1) {
  const params = { page, page_size: vecPageSize.value, order: vecOrder.value }
  if (vecSearch.value) params.search = vecSearch.value
  const result = await vecFetch('/stats/rules-vector', { params })
  vecRules.value = result || { total: 0, page: 1, pages: 1, items: [] }
}

// ── Python 代码染色 (高亮注释/字符串/关键字/数字) ──
function escapeHtml(s) {
  return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
}
function highlightPy(code) {
  if (!code) return ''
  return code
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/(#[^\n]*)/g, '<span class="cm-comment">$1</span>')
    .replace(/(\'[^\n]*\'|"[^\n]*")/g, '<span class="cm-string">$1</span>')
    .replace(/\b(re|match|search|find|group|compile|sub|exec|print|if|else|elif|for|while|return|in|not|and|or|True|False|None)\b/g, '<span class="cm-keyword">$1</span>')
    .replace(/\b(\d+\.?\d*)\b/g, '<span class="cm-number">$1</span>')
}

onMounted(() => loadVecRules())
</script>

<style scoped>
/* 2026-07-29 彻底统一(与 /taxonomy 一致):
   删: .vec-chips* / .vec-chips-label / .vec-chips-clear-all /
       .vec-toolbar* / .vec-input / .vec-clear-btn / .vec-help-btn / .vec-help* (5 block) /
       .slide-down-* / .vec-pagination / .page-btn* / .page-jump* / .page-size*。
   .ctx-toolbar 改成 /taxonomy 裸版(无 padding/bg/border-radius,只保留 flex+margin-bottom) — 4 页彻底统一。
   保留: .admin-page / .vec-table-wrap / .vec-attr-tag / .vec-pattern / .vec-code-block(.cm-*) 等列内容样式。 */

/* ── 页面容器 ── */
.admin-page {
  padding: 0 28px 64px;
  color: var(--text, #1e293b);
  font-size: 13px;
}

/* ── Toolbar(与 /taxonomy 同款,仅留搜索) ── */
.ctx-toolbar {
  display: flex; justify-content: space-between; align-items: center;
  margin-bottom: 14px; gap: 12px;
}
.ctx-search-wrap { position: relative; }
.ctx-search-icon {
  position: absolute; left: 10px; top: 50%; transform: translateY(-50%);
  font-size: 13px; pointer-events: none; opacity: 0.8;
}
.ctx-input {
  background: var(--surface, #ffffff);
  border: 1px solid var(--surface-3, #e2e8f0);
  border-radius: 8px;
  padding: 0 12px;
  font-size: 13px;
  color: var(--text, #0f172a);
  outline: none;
  font-family: inherit;
  transition: border-color 0.15s, box-shadow 0.15s, background 0.15s;
  height: 36px;
}
.ctx-input::placeholder { color: var(--text-3, #94a3b8); }
.ctx-input:hover { border-color: #cbd5e1; }
.ctx-input:focus {
  border-color: var(--primary, #2563eb);
  background: rgba(37,99,235,0.03);
  box-shadow: 0 0 0 3px rgba(37,99,235,0.1);
}
.ctx-search-wrap .ctx-input { padding-left: 32px; width: 240px; }

/* ── 主表格(el-table 容器外壳) ── */
.vec-table-wrap {
  background: var(--surface, #ffffff);
  border: 1px solid var(--border, rgba(15,23,42,0.06));
  border-radius: 10px;
  /* 2026-07-29 跟 /taxonomy 对齐:overflow 留给 el-table 内部处理 */
  overflow: visible;
  box-shadow: 0 1px 3px rgba(15,23,42,0.04);
}
.vec-table-wrap :deep(.pagination) {
  position: sticky;
  bottom: 0;
  background: rgba(255,255,255,0.95);
  backdrop-filter: blur(8px);
  border-top: 1px solid rgba(15,23,42,0.06);
  border-radius: 0 0 10px 10px;
  padding: 12px 18px;
  z-index: 5;
}

/* el-table 列内容排版 */
.vec-attr-tag {
  display: inline-block;
  background: rgba(37,99,235,0.1);
  color: var(--primary);
  border: 1px solid rgba(37,99,235,0.18);
  border-radius: 5px;
  padding: 2px 8px;
  font-size: 11px;
  font-weight: 600;
}
.vec-pattern {
  font-family: 'Courier New', monospace;
  font-size: 11.5px;
  background: rgba(37,99,235,0.06);
  color: var(--primary);
  border: 1px solid rgba(37,99,235,0.12);
  border-radius: 4px;
  padding: 2px 6px;
  font-weight: 600;
  word-break: break-all;
  white-space: normal;
  display: inline-block;
  max-width: 100%;
}
.vec-code-block {
  background: #0d1117;
  border: 1px solid #30363d;
  border-radius: 5px;
  padding: 6px 8px;
  font-family: 'Courier New', monospace;
  font-size: 11px;
  color: #c9d1d9;
  white-space: pre-wrap;
  word-break: break-all;
  line-height: 1.4;
  max-height: 100px;
  overflow-y: auto;
  width: 100%;
}
.vec-code-block .cm-comment { color: #8b949e; font-style: italic; }
.vec-code-block .cm-string { color: #a5d6ff; }
.vec-code-block .cm-keyword { color: #ff7b72; font-weight: 600; }
.vec-code-block .cm-number { color: #79c0ff; }

/* ── 响应式 ── */
@media (max-width: 768px) {
  /* 无 vec-toolbar-main(已合并) */
}
</style>
