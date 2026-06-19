<template>
  <div class="ctb-wrap" :class="{ 'ctb-expanded': showTree }">
    <!-- 标题行：选择器 -->
    <div v-if="!selectedNode" class="ctb-l1-row">
      <span
        v-for="l1 in tree"
        :key="l1.l1"
        class="ctb-chip ctb-l1-chip"
        @click="selectL1(l1)"
      >
        {{ l1.name_l1 }}
      </span>
    </div>

    <!-- L2 选择器 -->
    <div v-else-if="selectedNode && !selectedL2" class="ctb-l2-row">
      <button class="ctb-back" @click="goBack">‹ 返回</button>
      <span class="ctb-current">{{ selectedNode.name_l1 }}</span>
      <div class="ctb-chips">
        <span
          v-for="l2 in selectedNode.children"
          :key="l2.l2"
          class="ctb-chip ctb-l2-chip"
          @click="selectL2(l2)"
        >
          {{ l2.name_l2 }}
        </span>
      </div>
    </div>

    <!-- L3 选择器 -->
    <div v-else-if="selectedL2" class="ctb-l3-row">
      <button class="ctb-back" @click="goBack">‹ 返回</button>
      <span class="ctb-current">
        {{ selectedNode.name_l1 }} › {{ selectedL2.name_l2 }}
      </span>
      <div class="ctb-chips">
        <span
          v-for="l3 in selectedL2.children"
          :key="l3.l3"
          class="ctb-chip ctb-l3-chip"
          :class="{ 'ctb-selected': selectedL3 === l3.l3 }"
          @click="selectL3(l3)"
        >
          {{ l3.name_l3 }}
          <span class="ctb-l3-code">{{ l3.l3 }}</span>
        </span>
      </div>
    </div>

    <!-- 已选中的分类标签（L3 已选状态下显示） -->
    <div v-if="selectedL3 && selectedNode" class="ctb-selected-bar">
      <span class="ctb-path">{{ selectedNode.name_l1 }} › {{ selectedL2?.name_l2 }} › {{ selectedL3Name }}</span>
      <button class="ctb-clear" @click="clearSelection">✕ 清除筛选</button>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, watch } from 'vue'
import axios from 'axios'

const API = import.meta.env.VITE_API_URL || '/api'

const props = defineProps({
  show: { type: Boolean, default: false },
})

const emit = defineEmits(['select', 'clear', 'toggle'])

const tree = ref([])
const loading = ref(false)

// 选择状态
const selectedNode = ref(null)      // L1 node
const selectedL2 = ref(null)        // L2 node
const selectedL3 = ref(null)        // l3 code
const selectedL3Name = ref('')      // l3 name
const showTree = ref(false)

watch(() => props.show, (v) => {
  showTree.value = v
})

watch(showTree, (v) => {
  emit('toggle', v)
})

async function loadTree() {
  if (tree.value.length) return
  loading.value = true
  try {
    const { data } = await axios.get(`${API}/taxonomy/v3/tree`)
    if (data.ok) tree.value = data.tree
  } catch (e) {
    console.error('加载分类树失败', e)
  } finally {
    loading.value = false
  }
}

function selectL1(l1) {
  selectedNode.value = l1
  selectedL2.value = null
  selectedL3.value = null
  selectedL3Name.value = ''
}

function selectL2(l2) {
  selectedL2.value = l2
  selectedL3.value = null
  selectedL3Name.value = ''
}

function selectL3(l3) {
  selectedL3.value = l3.l3
  selectedL3Name.value = l3.name_l3
  showTree.value = false
  emit('select', l3.l3)
}

function goBack() {
  if (selectedL2.value) {
    selectedL2.value = null
    selectedL3.value = null
    selectedL3Name.value = ''
  } else if (selectedNode.value) {
    selectedNode.value = null
    selectedL3.value = null
    selectedL3Name.value = ''
  }
}

function clearSelection() {
  selectedNode.value = null
  selectedL2.value = null
  selectedL3.value = null
  selectedL3Name.value = ''
  emit('clear')
}

onMounted(loadTree)
</script>

<style scoped>
.ctb-wrap {
  margin: 0 0 8px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  overflow: hidden;
  transition: all 0.2s;
}

.ctb-l1-row,
.ctb-l2-row,
.ctb-l3-row {
  padding: 10px 14px;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
}

.ctb-back {
  background: none;
  border: 1px solid var(--border);
  border-radius: 5px;
  padding: 2px 10px;
  font-size: 12px;
  cursor: pointer;
  color: var(--text-2);
  flex-shrink: 0;
}

.ctb-back:hover {
  background: var(--surface-2);
  color: var(--primary);
}

.ctb-current {
  font-size: 11px;
  color: var(--text-3);
  white-space: nowrap;
  padding: 0 6px;
  flex-shrink: 0;
}

.ctb-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 5px;
  flex: 1;
}

.ctb-chip {
  padding: 4px 11px;
  border: 1px solid var(--border);
  border-radius: 14px;
  font-size: 12px;
  cursor: pointer;
  white-space: nowrap;
  transition: all 0.12s;
  user-select: none;
}

.ctb-chip:hover {
  background: var(--primary-dim);
  border-color: var(--primary);
  color: var(--primary);
}

.ctb-l1-chip {
  font-weight: 500;
  font-size: 13px;
}

.ctb-l2-chip {
  font-size: 12px;
}

.ctb-l3-chip {
  font-size: 12px;
}

.ctb-selected {
  background: var(--primary-dim) !important;
  border-color: var(--primary) !important;
  color: var(--primary) !important;
  font-weight: 600;
}

.ctb-l3-code {
  font-family: 'SF Mono', monospace;
  font-size: 9px;
  color: var(--text-3);
  background: var(--surface-2);
  padding: 0 4px;
  border-radius: 3px;
  margin-left: 4px;
}

.ctb-selected .ctb-l3-code {
  background: var(--surface);
  color: var(--primary);
}

.ctb-selected-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 6px 14px 10px;
  border-top: 1px solid var(--border);
  gap: 8px;
}

.ctb-path {
  font-size: 12px;
  color: var(--primary);
  font-weight: 600;
}

.ctb-clear {
  background: none;
  border: 1px solid var(--danger);
  color: var(--danger);
  border-radius: 4px;
  padding: 2px 8px;
  font-size: 11px;
  cursor: pointer;
  flex-shrink: 0;
}

.ctb-clear:hover {
  background: rgba(var(--danger-rgb), 0.08);
}
</style>
