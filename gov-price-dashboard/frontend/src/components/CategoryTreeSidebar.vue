<template>
  <div class="cts-wrap">
    <!-- 树搜索 -->
    <div class="cts-search">
      <input v-model="filterText" placeholder="🔍 搜索品类（建筑工程 / 装饰工程 / C20 / 商品砼…）" class="cts-search-input" title="按 L1/L2/L3 分类或品种名匹配,跨层级过滤" />
    </div>

    <div v-if="loading" class="cts-loading">
      <div class="loading-spinner"></div>
    </div>
    <div v-else-if="error" class="cts-error">
      <span>⚠️ {{ error }}</span>
      <button class="cts-retry" @click="$emit('retry')">重试</button>
    </div>
    <div v-else class="cts-scroll">
      <div v-if="filterText.trim() && filteredTree.length === 0" class="cts-empty">
        ⚡ 未找到匹配的分类
      </div>
      <TreeNode
        v-for="l1 in filteredTree"
        :key="l1.l1"
        :node="l1"
        :depth="0"
        :active-l3="activeL3"
        :filter-mode="!!filterText.trim()"
        :parent-path="[]"
        @select="(n) => $emit('select', n)"
      />
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import axios from 'axios'
import TreeNode from './TreeNode.vue'

const API = import.meta.env.VITE_API_URL || '/api'

defineProps({
  activeL3: { type: String, default: '' },
})

defineEmits(['select', 'retry'])

const tree = ref([])
const loading = ref(true)
const error = ref('')
const filterText = ref('')

// 过滤后的树：匹配 name 或 code（大小写不敏感）
const filteredTree = computed(() => {
  const q = filterText.value.trim().toLowerCase()
  if (!q) return tree.value

  function matchNode(n) {
    const nameMatch = n.name && n.name.toLowerCase().includes(q)
    const codeMatch = n.l1 && n.l1.toLowerCase().includes(q)
    return nameMatch || codeMatch
  }

  function filterChildren(nodes) {
    return nodes.reduce((acc, n) => {
      const selfMatch = matchNode(n)
      const filteredKids = n.children ? filterChildren(n.children) : []
      if (selfMatch || filteredKids.length > 0) {
        acc.push({ ...n, children: selfMatch ? (n.children || []) : filteredKids })
      }
      return acc
    }, [])
  }

  return filterChildren(tree.value)
})

async function load() {
  loading.value = true
  error.value = ''
  try {
    const { data } = await axios.get(`${API}/taxonomy/v3/tree`)
    if (data.ok) tree.value = data.tree
    else error.value = data.error || '加载失败'
  } catch (e) {
    error.value = e.message || '网络错误'
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.cts-wrap {
  height: 100%;
  display: flex;
  flex-direction: column;
  background: var(--surface);
}

.cts-search {
  padding: 16px 8px 6px;
  border-bottom: 1px solid var(--border);
}

.cts-search-input {
  width: 100%;
  padding: 8px 14px;
  border: 1px solid rgba(241,245,249,0.6);
  border-radius: var(--radius-sm);
  font-size: 14px;
  font-family: inherit;
  background: #ffffff;
  color: #1e293b;
  outline: none;
  box-sizing: border-box;
  transition: border-color 0.2s, box-shadow 0.2s;
}

.cts-search-input:focus {
  border-color: #2563eb;
  box-shadow: 0 0 0 3px rgba(37,99,235,0.4);
}

.cts-search-input::placeholder {
  color: #475569;
}

.cts-scroll {
  flex: 1;
  overflow-y: auto;
  padding: 4px 0;
}

.cts-loading,
.cts-empty {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 6px;
  color: var(--text-3);
  font-size: 12px;
}

.cts-empty {
  padding: 20px 10px;
  font-size: 13px;
  color: var(--text-3);
}

.loading-spinner {
  width: 20px;
  height: 20px;
  border: 2px solid var(--border);
  border-top-color: var(--primary);
  border-radius: 50%;
  animation: spin 0.6s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}
</style>
