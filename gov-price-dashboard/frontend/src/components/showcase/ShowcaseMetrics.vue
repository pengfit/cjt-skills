<!--
  ShowcaseMetrics.vue (2026-07-19 A 风格 + 删 存储 tile)

  Inline strip 风格(Linear pricing 页):
  - 3 项并排:城市 / 价格记录 / 归一品种
  - 细分隔线,无卡片无 hover 阴影
  - 2026-07-19 删掉「存储」tile(道友要求),grid 从 4 列变 3 列
-->
<template>
  <section class="metrics">
    <div class="metrics-strip">
      <div class="metric" v-for="m in items" :key="m.label">
        <div class="metric-value">
          <span class="num">{{ m.value }}</span>
          <span class="unit" v-if="m.unit">{{ m.unit }}</span>
        </div>
        <div class="metric-label">{{ m.label }}</div>
      </div>
    </div>
  </section>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  stats: { type: Object, required: true },
})

function fmt(n) {
  if (!n) return '—'
  if (n >= 1e4) return (n / 1e4).toFixed(1)
  if (n >= 1e3) return (n / 1e3).toFixed(1)
  return String(n)
}

const items = computed(() => {
  const s = props.stats || {}
  return [
    { label: '城市', value: s.cities_count || '—', unit: '城' },
    { label: '价格记录', value: fmt(s.total_records), unit: s.total_records >= 1e4 ? '万' : '' },
    { label: '归一品种', value: fmt(s.breeds_count), unit: s.breeds_count >= 1e4 ? '万' : '' },
  ]
})
</script>

<style scoped>
.metrics {
  padding: 32px 0;
  border-top: 1px solid var(--border-light);
  border-bottom: 1px solid var(--border-light);
}

.metrics-strip {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
}

.metric {
  padding: 8px 16px;
  text-align: center;
  border-right: 1px solid var(--border-light);
}

.metric:last-child {
  border-right: none;
}

.metric-value {
  display: flex;
  align-items: baseline;
  justify-content: center;
  gap: 4px;
  margin-bottom: 6px;
}

.metric-value .num {
  font-size: 30px;
  font-weight: 700;
  color: var(--text);
  letter-spacing: -0.02em;
  font-variant-numeric: tabular-nums;
  font-family: var(--font-mono-num);
  line-height: 1;
}

.metric-value .unit {
  font-size: 14px;
  color: var(--text-2);
  font-weight: 500;
}

.metric-label {
  font-size: 12px;
  color: var(--text-3);
  letter-spacing: 0.02em;
}

@media (max-width: 640px) {
  .metrics-strip { grid-template-columns: 1fr; }
  .metric {
    border-right: none;
    border-bottom: 1px solid var(--border-light);
    padding: 16px;
  }
  .metric:last-child { border-bottom: none; }
}
</style>
