<!--
  ShowcaseCoverage.vue - 覆盖矩阵
  按省份分组展示城市 + 最新数据日期 + 记录数
-->
<template>
  <section class="coverage" id="coverage">
    <header class="section-head">
      <h2 class="section-title">数据覆盖</h2>
      <p class="section-sub">{{ totalCities }} 个城市 · {{ provinces.length }} 个省份 · 数据来源各地住建局/造价站</p>
    </header>
    <div class="coverage-grid" v-if="provinces.length">
      <div class="province-card" v-for="p in provinces" :key="p.name">
        <div class="province-head">
          <span class="province-name">{{ p.name }}</span>
          <span class="province-count">{{ p.cities.length }} 城</span>
        </div>
        <ul class="city-list">
          <li v-for="c in p.cities" :key="c.key">
            <span class="city-dot"></span>
            <span class="city-label">{{ c.label }}</span>
            <span class="city-latest" v-if="c.latest">{{ c.latest }}</span>
          </li>
        </ul>
      </div>
    </div>
    <div class="empty" v-else>
      暂无数据,数据正在采集中
    </div>
  </section>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  grouped: { type: Array, default: () => [] },
})

const provinces = computed(() => props.grouped || [])
const totalCities = computed(() => provinces.value.reduce((sum, p) => sum + (p.cities?.length || 0), 0))
</script>

<style scoped>
.coverage {
  padding: 64px 0;
}

.section-head {
  margin-bottom: 32px;
}

.section-title {
  font-size: 28px;
  font-weight: 700;
  color: var(--text);
  letter-spacing: -0.02em;
  margin: 0 0 8px;
}

.section-sub {
  font-size: 14px;
  color: var(--text-2);
  margin: 0;
}

.coverage-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 16px;
}

.province-card {
  padding: 20px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  transition: all var(--transition);
}

.province-card:hover {
  border-color: var(--border-strong);
}

.province-head {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  margin-bottom: 12px;
  padding-bottom: 12px;
  border-bottom: 1px solid var(--border-light);
}

.province-name {
  font-size: 15px;
  font-weight: 600;
  color: var(--text);
}

.province-count {
  font-size: 12px;
  color: var(--text-3);
  font-variant-numeric: tabular-nums;
  font-family: var(--font-mono-num);
}

.city-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.city-list li {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
}

.city-dot {
  width: 4px;
  height: 4px;
  background: var(--primary);
  border-radius: 50%;
  flex-shrink: 0;
}

.city-label {
  color: var(--text);
  flex: 1;
}

.city-latest {
  font-size: 12px;
  color: var(--text-3);
  font-variant-numeric: tabular-nums;
  font-family: var(--font-mono-num);
}

.empty {
  padding: 48px;
  text-align: center;
  color: var(--text-3);
  background: var(--surface);
  border: 1px dashed var(--border);
  border-radius: var(--radius-lg);
}
</style>
