<template>
  <div class="ctx-page">
    <!-- Header -->
    <PageHeader
      variant="flat"
      title="分类体系"
      subtitle="3 级分类法（L1 / L2 / L3）+ 品种→L3 映射规则，数据源 <code>breed_canonical.db</code>（GB 50500 系列）"
      :stats="[
        { label: '一级', value: stats.taxonomy.l1 || 0 },
        { label: '三级分类', value: stats.taxonomy.l3 || 0 },
        { label: '品种映射', value: fmt.int(stats.map.total) },
        {
          label: 'L3 命中率',
          value: hitRate + '%',
          tone: 'ok',
          title: `L3 命中率：${stats.map.l3_in_taxonomy} / ${stats.map.l3_in_taxonomy + stats.map.l3_not_in_taxonomy}`,
        },
      ]"
    />

    <!-- Sub Tabs (对齐 SyncView 的 sync-subtabs 导航模式) -->
    <div class="ctx-subtabs">
      <button class="ctx-subtab" :class="{ active: subTab === 'map' }" @click="subTab = 'map'">
        <span class="ctx-subtab-dot"></span>
        品种映射
      </button>
      <button class="ctx-subtab" :class="{ active: subTab === 'taxonomy' }" @click="subTab = 'taxonomy'">
        <span class="ctx-subtab-dot"></span>
        分类法
      </button>
    </div>

    <!-- 子组件：调度器不持有 tab 内容 -->
    <CategoryTaxonomyTab
      v-if="subTab === 'taxonomy'"
      @jump-to-breed-map="handleJumpToBreedMap"
    />
    <BreedMapTab
      v-else-if="subTab === 'map'"
      :initial-l3-filter="mapInitialL3Filter"
    />
  </div>
</template>

<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import axios from 'axios'
import CategoryTaxonomyTab from './CategoryTaxonomyTab.vue'
import BreedMapTab from './BreedMapTab.vue'
import PageHeader from './PageHeader.vue'
import { useFormatNumber } from '../composables/useFormatNumber.js'

const API = import.meta.env.VITE_API_URL || '/api'
const fmt = useFormatNumber()

// ── 顶部统计（共享） ──
const stats = ref({
  taxonomy: { l1: 0, l2: 0, l3: 0 },
  map: { total: 0, l3_in_taxonomy: 0, l3_not_in_taxonomy: 0 },
})

const hitRate = computed(() => {
  const inT = stats.value.map.l3_in_taxonomy
  const out = stats.value.map.l3_not_in_taxonomy
  const tot = inT + out
  if (!tot) return '0.0'
  return fmt.pct((inT / tot) * 100)
})

// ── Tab 状态 ──
const subTab = ref('map')
const mapInitialL3Filter = ref('')  // 用于跨 tab 跳转时预填

async function loadStats() {
  try {
    const { data } = await axios.get(`${API}/stats/category-v2-stats`)
    if (data.ok) stats.value = data
  } catch (e) { console.error(e) }
}

// 跨 tab 跳转：分类法点 L3 → 切到品种映射 + 预填
function handleJumpToBreedMap(l3) {
  subTab.value = 'map'
  mapInitialL3Filter.value = l3
}

onMounted(() => {
  loadStats()
})
</script>

<style scoped>
.ctx-page { padding: 0 28px 64px; }

/* Header（已迁移至 PageHeader flat 变体） */
.ctx-subtitle code,
.ctx-page :deep(.page-header-subtitle code) {
  font-family: 'Courier New', monospace; font-size: 10px;
  color: var(--primary); background: rgba(37,99,235,0.08);
  border-radius: 3px; padding: 1px 4px; font-weight: 500;
}

/* Sub Tabs ── 对齐 SyncView 导航模式 ──
   视觉跟 .sync-subtab 完全一致（dot + 标题 + hint，active 蓝点 + 色条），
   这里只放 subtab 容器 + 按钮样式，每个 tab 的内容交给子组件 */
.ctx-subtabs {
  display: flex; gap: 4px;
  padding: 14px 0 0;
  border-bottom: 1px solid var(--border);
  background: var(--bg);
  z-index: 100;
  /* 让 border-bottom 与下方内容有间隙 */
  padding-bottom: 2px;
}
.ctx-subtab {
  position: relative;
  display: inline-flex; align-items: center; gap: 8px;
  padding: 9px 18px;
  border: 1px solid transparent;
  border-bottom: none;
  border-radius: 8px 8px 0 0;
  background: transparent;
  color: var(--text-2);
  cursor: pointer;
  font-size: 13px;
  font-weight: 600;
  transition: all 0.18s;
}
.ctx-subtab:hover { color: var(--text); background: var(--surface-2); border-color: var(--border); }
.ctx-subtab.active {
  color: var(--primary); background: var(--surface);
  border-color: var(--border); border-bottom-color: var(--surface);
  margin-bottom: -1px;
}
.ctx-subtab-dot {
  width: 6px; height: 6px; border-radius: 50%;
  background: var(--text-3); transition: all 0.2s;
}
.ctx-subtab.active .ctx-subtab-dot {
  background: var(--primary);
  box-shadow: 0 0 0 3px rgba(37,99,235,0.18);
}
.ctx-subtab-hint {
  font-size: 11px; font-weight: 400; color: var(--text-3);
  margin-left: 4px;
}
.ctx-subtab.active .ctx-subtab-hint { color: var(--primary); opacity: 0.85; }
</style>