<!--
  NumbersSection.vue (2026-07-21 /home 新增)
  信任数字 — 接 ShowcaseView 提供的真实 stats（非占位）
-->
<script setup>
import { useInView } from '../../composables/useInView'
const { target, inView } = useInView()

// 真实数据:由 HomeView 通过 inject('stats') 注入
// 缺失个别字段时回落到 dashboard 最近快照 (2026-07-19 / 2026-07-31)
import { inject } from 'vue'

const injected = inject('stats', null)
const stats = injected || {
  cities_count: 20,
  provinces_count: 15,
  breeds_count: 9931,
  dws_total: 788525,
  storage_mb: 573.1,
  latest_update: '2026-07-31'
}

const fmtInt = (n) => Number(n || 0).toLocaleString('en-US')
</script>

<template>
  <section ref="target" class="numbers" :class="{ 'in-view': inView }">
    <div class="numbers-inner">
      <h2 class="numbers-title">数据说话</h2>
      <p class="numbers-sub">
        截至 {{ stats.latest_update || '2026-07-31' }}，来自 Dashboard 的真实运行快照
      </p>
      <div class="numbers-grid">
        <div class="numbers-cell">
          <div class="numbers-value">{{ stats.cities_count }}</div>
          <div class="numbers-label">覆盖城市</div>
        </div>
        <div class="numbers-cell">
          <div class="numbers-value">{{ stats.provinces_count }}</div>
          <div class="numbers-label">覆盖省份</div>
        </div>
        <div class="numbers-cell">
          <div class="numbers-value">{{ fmtInt(stats.breeds_count) }}</div>
          <div class="numbers-label">采集品种</div>
        </div>
        <div class="numbers-cell">
          <div class="numbers-value">{{ fmtInt(stats.dws_total) }}</div>
          <div class="numbers-label">DWS 记录（条）</div>
        </div>
        <div class="numbers-cell numbers-cell-wide">
          <div class="numbers-value numbers-value-mid">
            {{ (stats.storage_mb || 573.1).toFixed(1) }}<span class="numbers-unit">MB</span>
          </div>
          <div class="numbers-label">存储占用</div>
        </div>
        <div class="numbers-cell numbers-cell-cta">
          <a href="/home#home-case" class="numbers-link">看案例 →</a>
        </div>
      </div>
    </div>
  </section>
</template>

<style scoped>
.numbers {
  padding: 80px 0;
  background: var(--text);
  color: var(--text-inverse);
}
.numbers-inner {
  max-width: 1200px;
  margin: 0 auto;
  padding: 0 32px;
}
.numbers-title {
  font-size: 30px;
  font-weight: 700;
  color: var(--text-inverse);
  text-align: center;
  margin: 0;
  letter-spacing: -0.01em;
}
.numbers-sub {
  font-size: 14px;
  color: rgba(255, 255, 255, 0.55);
  text-align: center;
  margin: 12px 0 0;
}
.numbers-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 24px;
  margin-top: 56px;
}
.numbers-cell {
  text-align: center;
  padding: 16px;
}
.numbers-cell-wide { grid-column: span 2; }
.numbers-value {
  font-family: var(--font-mono-num);
  font-size: 48px;
  font-weight: 700;
  color: var(--primary-soft);
  font-variant-numeric: tabular-nums;
  letter-spacing: -0.02em;
  line-height: 1.1;
}
.numbers-value-mid { font-size: 36px; }
.numbers-unit {
  font-size: 20px;
  color: rgba(255, 255, 255, 0.55);
  font-weight: 500;
  margin-left: 4px;
}
.numbers-label {
  font-size: 13px;
  color: rgba(255, 255, 255, 0.65);
  margin-top: 10px;
}
.numbers-link {
  display: inline-flex;
  align-items: center;
  padding: 12px 22px;
  font-size: 13px;
  font-weight: 500;
  color: var(--text);
  background: var(--text-inverse);
  border-radius: var(--radius);
  text-decoration: none;
  transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
  font-family: inherit;
}
.numbers-link:hover {
  background: var(--primary-soft);
  color: var(--text-inverse);
  transform: translateY(-2px);
  box-shadow: 0 8px 20px rgba(30, 64, 175, 0.25);
}

/* enter animation */
.numbers-title,
.numbers-sub,
.numbers-cell {
  opacity: 0;
  transform: translateY(12px);
  transition: opacity 0.5s ease-out, transform 0.5s ease-out;
}
.numbers.in-view .numbers-title { opacity: 1; transform: translateY(0); transition-delay: 0s; }
.numbers.in-view .numbers-sub { opacity: 1; transform: translateY(0); transition-delay: 0.08s; }
.numbers.in-view .numbers-cell { opacity: 1; transform: translateY(0); }
.numbers.in-view .numbers-cell:nth-child(1) { transition-delay: 0.16s; }
.numbers.in-view .numbers-cell:nth-child(2) { transition-delay: 0.22s; }
.numbers.in-view .numbers-cell:nth-child(3) { transition-delay: 0.28s; }
.numbers.in-view .numbers-cell:nth-child(4) { transition-delay: 0.34s; }
.numbers.in-view .numbers-cell:nth-child(5) { transition-delay: 0.40s; }
.numbers.in-view .numbers-cell:nth-child(6) { transition-delay: 0.46s; }

@media (max-width: 900px) {
  .numbers-grid { grid-template-columns: repeat(2, 1fr); }
  .numbers-cell-wide { grid-column: span 2; }
}
@media (max-width: 560px) {
  .numbers { padding: 56px 0; }
  .numbers-inner { padding: 0 20px; }
  .numbers-grid { grid-template-columns: 1fr; gap: 18px; }
  .numbers-cell-wide { grid-column: span 1; }
  .numbers-value { font-size: 40px; }
  .numbers-value-mid { font-size: 30px; }
  .numbers-cell-cta { padding-top: 8px; }
}
</style>
