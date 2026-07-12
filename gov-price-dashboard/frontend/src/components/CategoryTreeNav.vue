<template>
  <div class="ctn-page">
    <!-- 树面板（左侧） -->
    <aside class="ctn-tree-panel">
      <div class="ctn-tree-header">
        <span class="ctn-tree-title">分类导航</span>
        <span class="ctn-tree-subtitle">L1 → L2 → L3</span>
      </div>

      <!-- 树搜索过滤 -->
      <div class="ctn-tree-search">
        <input
          v-model="filterText"
          class="ctn-search-input"
          placeholder="🔍 搜索分类..."
          @input="onFilterInput"
        />
      </div>

      <div v-if="loading" class="ctn-loading">
        <div class="loading-spinner"></div>
        <span>加载分类树...</span>
      </div>

      <ErrorState v-else-if="treeError" :title="'分类树加载失败'" :message="treeError" compact :on-retry="loadTree" />

      <div v-else class="ctn-tree-scroll">
        <TreeNode
          v-for="l1 in treeData"
          :key="l1.l1"
          :node="l1"
          :depth="0"
          :active-l3="activeL3"
          :highlight="!!filterText"
          @select="onNodeSelect"
        />
      </div>

      <div class="ctn-tree-footer">
        <span>{{ treeNodeCount }} 个分类节点</span>
      </div>
    </aside>

    <!-- 产品面板（右侧） -->
    <main class="ctn-product-panel">
      <!-- 未选择分类 -->
      <div v-if="!activeL3" class="ctn-welcome">
        <div class="ctn-welcome-icon">📂</div>
        <div class="ctn-welcome-title">请在左侧分类树中选择一个分类</div>
        <div class="ctn-welcome-hint">
          展开 L1 → L2 → L3，点击叶子节点查看产品数据
        </div>
        <div class="ctn-welcome-examples">
          <div class="ctn-welcome-label">热门分类：</div>
          <span
            v-for="s in suggestedCategories"
            :key="s.l3"
            class="ctn-chip"
            @click="onNodeSelect(s)"
          >
            {{ s.name_l3 }}
          </span>
        </div>
      </div>

      <!-- 产品列表 -->
      <template v-else>
        <!-- 面包屑 + 工具栏 -->
        <div class="ctn-toolbar">
          <div class="ctn-breadcrumb">
            <span class="ctn-bread-item" @click="clearCategory">📁 全部分类</span>
            <span class="ctn-bread-sep">›</span>
            <span class="ctn-bread-item">{{ activeBreadcrumb }}</span>
          </div>
          <div class="ctn-toolbar-right">
            <input
              class="ctn-inline-search"
              v-model="productKeyword"
              placeholder="🔍 在此分类中搜索..."
              @keyup.enter="doProductSearch(1)"
              @input="onProductKeywordInput"
            />
          </div>
        </div>

        <!-- 加载中 -->
        <div v-if="productLoading" class="ctn-loading">
          <div class="loading-spinner"></div>
          <span>加载产品数据...</span>
        </div>

        <!-- 错误 -->
        <ErrorState v-else-if="productError" :title="'产品数据加载失败'" :message="productError" compact />
        <EmptyState v-else-if="!productResult.data || !productResult.data.length" icon="🗺️" title="该分类暂无数据" message="可能该城市尚未覆盖此分类的产品价格" />

        <!-- 产品表格 -->
        <div v-else class="ctn-table-wrap">
          <div class="ctn-table-scroll">
            <table class="data-table ctn-table">
              <thead>
                <tr>
                  <th style="width:180px;min-width:180px">产品名称</th>
                  <th style="width:80px;min-width:80px">规格</th>
                  <th style="width:50px;min-width:50px">单位</th>
                  <th style="width:100px;min-width:100px">不含税价</th>
                  <th style="width:100px;min-width:100px">含税价</th>
                  <th style="width:80px;min-width:80px">城市</th>
                  <th style="width:90px;min-width:90px">日期</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="(item, idx) in productResult.data" :key="item.id || idx" class="data-row">
                  <td style="width:180px;min-width:180px">
                    <div class="breed-cell">
                      <span class="breed-name">{{ item.breed }}</span>
                      <span class="meta-tag" v-if="item.county">{{ item.county }}</span>
                    </div>
                  </td>
                  <td style="width:80px;min-width:80px" class="td-spec">{{ item.spec || '—' }}</td>
                  <td style="width:50px;min-width:50px" class="unit-cell">{{ item.unit || '—' }}</td>
                  <td style="width:100px;min-width:100px" class="price-cell">{{ fmtPrice(item.price) }}</td>
                  <td style="width:100px;min-width:100px" class="tax-price-cell">{{ fmtPrice(item.tax_price) }}</td>
                  <td style="width:80px;min-width:80px">{{ item.city || '—' }}</td>
                  <td style="width:90px;min-width:90px" class="date-cell">{{ item.date || '—' }}</td>
                </tr>
              </tbody>
            </table>
          </div>

          <!-- 分页 -->
          <div class="pagination" v-if="productResult.pages && productResult.pages > 1">
            <button class="page-btn nav" :disabled="productPage <= 1" @click="doProductSearch(productPage - 1)">‹</button>
            <button
              v-for="p in productPageRange"
              :key="p"
              class="page-btn"
              :class="{ active: String(p) === String(productPage), ellipsis: p === '...' }"
              :disabled="p === '...'"
              @click="p !== '...' && doProductSearch(Number(p))"
            >{{ p }}</button>
            <button class="page-btn nav" :disabled="productPage >= productResult.pages" @click="doProductSearch(productPage + 1)">›</button>
            <div class="page-size-wrap">
              <span>每页</span>
              <select class="page-size-select" v-model.number="productPageSize" @change="doProductSearch(1)">
                <option v-for="s in [20, 50, 100]" :key="s" :value="s">{{ s }}</option>
              </select>
              <span>条</span>
            </div>
            <span class="page-total">共 {{ fmt.int(productResult.total || 0) }} 条</span>
          </div>
        </div>
      </template>
    </main>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import axios from 'axios'
import TreeNode from './TreeNode.vue'
import ErrorState from './ErrorState.vue'
import EmptyState from './EmptyState.vue'
import { useFormatNumber } from '../composables/useFormatNumber.js'

const API = import.meta.env.VITE_API_URL || '/api'
const fmt = useFormatNumber()

// ── 树状态 ──
const treeData = ref([])
const loading = ref(true)
const treeError = ref('')
const filterText = ref('')
const filterDebounce = ref(null)

// ── 产品列表状态 ──
const activeL3 = ref('')
const activeBreadcrumb = ref('')
const productKeyword = ref('')
const productResult = ref({})
const productPage = ref(1)
const productPageSize = ref(20)
const productLoading = ref(false)
const productError = ref('')

// ── 树节点数统计 ──
const treeNodeCount = computed(() => {
  let count = 0
  for (const l1 of treeData.value) {
    count++
    for (const l2 of l1.children || []) {
      count++
      count += (l2.children || []).length
    }
  }
  return count
})

// ── 热门分类建议（前 10 个 L3） ──
const suggestedCategories = computed(() => {
  const all = []
  for (const l1 of treeData.value) {
    for (const l2 of l1.children || []) {
      for (const l3 of l2.children || []) {
        all.push({ ...l3, name_l1: l1.name_l1, name_l2: l2.name_l2 })
      }
    }
  }
  return all.slice(0, 10)
})

// ── 分页范围 ──
const productPageRange = computed(() => {
  const total = productResult.value.pages || 1
  const cur = Number(productPage.value)
  if (total <= 7) return Array.from({ length: total }, (_, i) => i + 1)
  const r = []
  if (cur <= 4) {
    for (let i = 1; i <= 5; i++) r.push(i)
    r.push('...'); r.push(total)
  } else if (cur >= total - 3) {
    r.push(1); r.push('...')
    for (let i = total - 4; i <= total; i++) r.push(i)
  } else {
    r.push(1); r.push('...')
    for (let i = cur - 1; i <= cur + 1; i++) r.push(i)
    r.push('...'); r.push(total)
  }
  return r
})

// ── 加载分类树 ──
async function loadTree() {
  loading.value = true
  treeError.value = ''
  try {
    const { data } = await axios.get(`${API}/taxonomy/v3/tree`)
    if (data.ok) {
      treeData.value = data.tree
    } else {
      treeError.value = data.error || '加载分类树失败'
    }
  } catch (e) {
    treeError.value = e.message || '网络错误'
  } finally {
    loading.value = false
  }
}

// ── 树搜索过滤 ──
function onFilterInput() {
  if (filterDebounce.value) clearTimeout(filterDebounce.value)
  filterDebounce.value = setTimeout(() => {
    // 过滤由 TreeNode 内部 highlight 机制处理
  }, 200)
}

// ── 选择分类节点 ──
function onNodeSelect(node) {
  activeL3.value = node.l3
  productKeyword.value = ''
  productPage.value = 1
  // 构建面包屑
  for (const l1 of treeData.value) {
    for (const l2 of l1.children || []) {
      for (const l3 of l2.children || []) {
        if (l3.l3 === node.l3) {
          activeBreadcrumb.value = `${l1.name_l1} › ${l2.name_l2} › ${l3.name_l3}`
        }
      }
    }
  }
  doProductSearch(1)
}

// ── 清除分类筛选 ──
function clearCategory() {
  activeL3.value = ''
  activeBreadcrumb.value = ''
  productResult.value = {}
}

// ── 搜索产品 ──
async function doProductSearch(page) {
  productPage.value = page || 1
  productLoading.value = true
  productError.value = ''
  try {
    const params = { category_l3: activeL3.value, page: productPage.value, page_size: productPageSize.value }
    if (productKeyword.value.trim()) params.keyword = productKeyword.value.trim()
    const { data } = await axios.get(`${API}/search`, { params })
    productResult.value = data || {}
  } catch (e) {
    productError.value = e.message || '请求失败'
  } finally {
    productLoading.value = false
  }
}

// ── 产品关键词输入防抖 ──
let productKeywordTimer = null
function onProductKeywordInput() {
  if (productKeywordTimer) clearTimeout(productKeywordTimer)
  productKeywordTimer = setTimeout(() => doProductSearch(1), 300)
}

// ── 价格格式化(不带 ¥ 前缀,与表格列样式一致) ──
// 注:此函数保留本地实现,与 useFormatNumber().price() 行为不同(后者默认加 ¥)。
// 本表头未使用 ¥ 前缀,继续用本地版本以保持视觉一致。
function fmtPrice(v) {
  if (v === null || v === undefined || v === '') return '—'
  const n = Number(v)
  if (isNaN(n)) return v
  return n.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

onMounted(loadTree)
</script>

<style scoped>
/* ── 页面布局：左侧树 + 右侧产品 ── */
.ctn-page {
  display: flex;
  height: calc(100vh - var(--topbar-h, 60px) - 28px);
  gap: 0;
}

/* ── 左侧树面板 ── */
.ctn-tree-panel {
  width: 280px;
  flex-shrink: 0;
  border-right: 1px solid var(--border);
  display: flex;
  flex-direction: column;
  background: var(--surface);
}

.ctn-tree-header {
  padding: 16px 14px 8px;
  display: flex;
  align-items: baseline;
  gap: 8px;
}

.ctn-tree-title {
  font-size: 15px;
  font-weight: 700;
  color: var(--text);
}

.ctn-tree-subtitle {
  font-size: 11px;
  color: var(--text-3);
}

.ctn-tree-search {
  padding: 4px 14px 10px;
}

.ctn-search-input {
  width: 100%;
  padding: 7px 10px;
  border: 1px solid var(--border);
  border-radius: 6px;
  font-size: 13px;
  background: var(--bg);
  color: var(--text);
  outline: none;
  transition: border-color 0.15s;
  box-sizing: border-box;
}

.ctn-search-input:focus {
  border-color: var(--primary);
}

.ctn-tree-scroll {
  flex: 1;
  overflow-y: auto;
  padding: 0 6px 8px;
}

.ctn-tree-footer {
  padding: 8px 14px;
  font-size: 11px;
  color: var(--text-3);
  border-top: 1px solid var(--border);
}

/* ── 右侧产品面板 ── */
.ctn-product-panel {
  flex: 1;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  padding: 0 20px 20px;
}

/* ── 欢迎页 ── */
.ctn-welcome {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  color: var(--text-3);
}

.ctn-welcome-icon {
  font-size: 48px;
  opacity: 0.5;
}

.ctn-welcome-title {
  font-size: 16px;
  font-weight: 600;
  color: var(--text-2);
}

.ctn-welcome-hint {
  font-size: 13px;
  margin-bottom: 16px;
}

.ctn-welcome-examples {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  align-items: center;
}

.ctn-welcome-label {
  font-size: 12px;
  color: var(--text-3);
}

.ctn-chip {
  padding: 4px 10px;
  border: 1px solid var(--border);
  border-radius: 12px;
  font-size: 12px;
  cursor: pointer;
  color: var(--primary);
  background: rgba(var(--primary-rgb), 0.05);
  transition: all 0.12s;
}

.ctn-chip:hover {
  background: var(--primary-dim);
  border-color: var(--primary);
}

/* ── 工具栏 ── */
.ctn-toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 0;
  border-bottom: 1px solid var(--border);
  margin-bottom: 12px;
}

.ctn-breadcrumb {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 13px;
  flex: 1;
  min-width: 0;
}

.ctn-bread-item {
  color: var(--primary);
  cursor: pointer;
  white-space: nowrap;
}

.ctn-bread-item:first-child {
  color: var(--text-3);
}

.ctn-bread-item:first-child:hover {
  color: var(--primary);
}

.ctn-bread-sep {
  color: var(--text-3);
  font-size: 14px;
}

.ctn-inline-search {
  padding: 5px 10px;
  border: 1px solid var(--border);
  border-radius: 6px;
  font-size: 13px;
  background: var(--bg);
  color: var(--text);
  outline: none;
  width: 220px;
  transition: border-color 0.15s;
}

.ctn-inline-search:focus {
  border-color: var(--primary);
}

/* ── 产品表格 ── */
.ctn-table-wrap {
  flex: 1;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

.ctn-table-scroll {
  flex: 1;
  overflow: auto;
}

.ctn-table th,
.ctn-table td {
  padding: 6px 8px;
}

/* ── 状态 ── */
.ctn-loading,
.ctn-empty {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  color: var(--text-3);
  font-size: 14px;
}



.loading-spinner {
  width: 24px;
  height: 24px;
  border: 3px solid var(--border);
  border-top-color: var(--primary);
  border-radius: 50%;
  animation: spin 0.6s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}
</style>
