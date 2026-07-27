<template>
  <div class="ctx-page">
    <!-- Header (纯分类骨架,完全不依赖 breed_canonical.db) -->
    <PageHeader
      variant="flat"
      title="分类体系"
      subtitle="3 级分类法(L1 / L2 / L3)+ GB 50500 国标 + IFC + Uniclass。数据源 <code>category_v3_rules.db</code>(DWD→DWS ETL live 写入,分类骨架变更立即可见)。"
      :stats="stats ? [
        { label: '一级',     value: stats.taxonomy.l1 || 0 },
        { label: '二级',     value: stats.taxonomy.l2 || 0 },
        { label: '三级分类', value: stats.taxonomy.l3 || 0 },
        { label: 'L4 分项',  value: stats.taxonomy.l4 || 0 },
      ] : []"
    />

    <!-- 唯一子组件:分类法(纯 category_v3 数据) -->
    <CategoryTaxonomyTab />
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import axios from 'axios'
import CategoryTaxonomyTab from './CategoryTaxonomyTab.vue'
import PageHeader from './PageHeader.vue'

const API = import.meta.env.VITE_API_URL || '/api'
const stats = ref(null)

async function loadStats() {
  try {
    const { data } = await axios.get(`${API}/stats/category-v2-stats`)
    if (data.ok) stats.value = data
  } catch (e) { console.error(e) }
}

onMounted(() => loadStats())
</script>

<style scoped>
.ctx-page { padding: 0 28px 64px; }

.ctx-subtitle code,
.ctx-page :deep(.page-header-subtitle code) {
  font-family: 'Courier New', monospace; font-size: 10px;
  color: var(--primary); background: rgba(37,99,235,0.08);
  border-radius: 3px; padding: 1px 4px; font-weight: 500;
}

/* ── 移动端 (2026-07-25 P0-fix,2026-07-27 进一步简化) ── */
@media (max-width: 768px) {
  .ctx-page { padding: 0 12px 40px; }
  .t-header, .taxonomy-header, .ctx-drawer-grid { grid-template-columns: 1fr !important; flex-direction: column !important; }
  .ctx-drawer { width: 92vw !important; max-width: 360px !important; }
  .tree-pane, .detail-pane { width: 100% !important; max-width: 100% !important; }
}
</style>