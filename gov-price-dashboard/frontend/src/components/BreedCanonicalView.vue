<template>
  <div class="ctx-page">
    <!-- PageHeader (与 /taxonomy 同样的 flat 风格) -->
    <PageHeader
      variant="flat"
      title="品种归一后台"
      subtitle="品种→L3 映射 + normalized_breed（多对一合并名）。数据源 <code>skills/data/breed_canonical.db</code> · 表 <code>breed_canonical</code>(DWS→NORM 阶段 build_norm_index.py 写入)。"
      :stats="stats ? [
        { label: '总映射',         value: stats.total_mappings.toLocaleString() },
        { label: 'distinct',       value: stats.distinct_normalized_breed.toLocaleString() },
        { label: 'distinct L3',    value: stats.top10_l3 ? Object.keys(stats.top10_l3).length : 0 },
        { label: 'reject',         value: stats.reject_count.toLocaleString() },
      ] : []"
    />

    <!-- 唯一子组件：品种归一表 -->
    <BreedCanonicalTab />
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import PageHeader from './PageHeader.vue'
import BreedCanonicalTab from './BreedCanonicalTab.vue'

const stats = ref(null)

async function loadStats() {
  try {
    const r = await fetch('/api/canon/breeds/stats')
    if (r.ok) stats.value = await r.json()
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

@media (max-width: 768px) {
  .ctx-page { padding: 0 12px 40px; }
}
</style>