<template>
  <div class="admin-page">
    <!-- PageHeader (纯分类映射统计) -->
    <PageHeader
      variant="flat"
      title="分类映射"
      subtitle="品种→L3 映射规则表。数据源 <code>skills/data/category_v3_rules.db</code> · 表 <code>breed_l3_map_v3</code>(DWD→DWS ETL 第二轮 Dify 自动写入)。"
      :stats="stats ? [
        { label: '总映射',     value: fmt(stats.total_mappings) },
        { label: 'distinct 品种', value: fmt(stats.distinct_breed) },
        { label: 'distinct L3', value: fmt(stats.distinct_l3) },
        { label: 'NULL l3',    value: fmt(stats.null_l3) },
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

// 防御:API 可能返回 null/缺失字段,toLocaleString() 会炸
function fmt(v) { return (v ?? 0).toLocaleString() }
</script>

<style scoped>
.admin-page { padding: 0 28px 64px; }

.ctx-subtitle code,
.admin-page :deep(.page-header-subtitle code) {
  font-family: 'Courier New', monospace; font-size: 10px;
  color: var(--primary); background: rgba(37,99,235,0.08);
  border-radius: 3px; padding: 1px 4px; font-weight: 500;
}

@media (max-width: 768px) {
  .admin-page { padding: 0 12px 40px; }
}
</style>