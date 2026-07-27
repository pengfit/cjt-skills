<template>
  <div class="ctx-page">
    <!-- PageHeader (纯分类映射统计) -->
    <PageHeader
      variant="flat"
      title="分类映射"
      subtitle="品种→L3 映射规则表。数据源 <code>skills/data/category_v3_rules.db</code> · 表 <code>breed_l3_map_v3</code>(DWD→DWS ETL 第二轮 Dify 自动写入)。"
      :stats="stats ? [
        { label: '总映射',     value: stats.total_mappings.toLocaleString() },
        { label: 'distinct 品种', value: stats.distinct_breed.toLocaleString() },
        { label: 'distinct L3', value: stats.distinct_l3.toLocaleString() },
        { label: 'NULL l3',    value: stats.null_l3.toLocaleString() },
      ] : []"
    />

    <!-- 唯一子组件：分类映射表 -->
    <BreedL3MapTab />
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import PageHeader from './PageHeader.vue'
import BreedL3MapTab from './BreedL3MapTab.vue'

const stats = ref(null)

async function loadStats() {
  try {
    const r = await fetch('/api/stats/breed-l3-map/stats')
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