<!--
  PricingSection.vue (2026-07-21 /home 新增)
  合作模式 — 3 档卡片（不挂价）
-->
<script setup>
import { useInView } from '../../composables/useInView'
const { target, inView } = useInView()

const plans = [
  {
    name: '项目制',
    desc: '一次性数据基建',
    fee: '一次性报价',
    cta: '约需求诊断'
  },
  {
    name: '长期顾问',
    desc: '持续运维 / 增量迭代',
    fee: '月费，单独报价',
    cta: '约月度合作'
  },
  {
    name: '数据接入',
    desc: '直接调用已采集的 20 城数据',
    fee: '按调用量计费',
    cta: '申请 API 试用'
  }
]
</script>

<template>
  <section ref="target" id="home-pricing" class="pricing" :class="{ 'in-view': inView }">
    <div class="pricing-inner">
      <div class="pricing-head">
        <h2 class="pricing-title">怎么收费</h2>
        <p class="pricing-sub">三种模式，按项目特征选。具体报价不在页面公开——聊完需求后发 PDF。</p>
      </div>
      <div class="pricing-grid">
        <div v-for="p in plans" :key="p.name" class="pricing-card">
          <h3 class="pricing-name">{{ p.name }}</h3>
          <p class="pricing-desc">{{ p.desc }}</p>
          <div class="pricing-fee">
            <span class="pricing-fee-label">计费</span>
            <div class="pricing-fee-value">{{ p.fee }}</div>
          </div>
          <a href="mailto:hello@pengfit.cn" class="pricing-cta">{{ p.cta }}</a>
        </div>
      </div>
    </div>
  </section>
</template>

<style scoped>
.pricing { padding: 80px 0; background: var(--surface-2); }
.pricing-inner { max-width: 1200px; margin: 0 auto; padding: 0 32px; }
.pricing-head { max-width: 640px; margin-bottom: 48px; }
.pricing-title {
  font-size: 30px;
  font-weight: 700;
  color: var(--text);
  margin: 0;
  letter-spacing: -0.01em;
}
.pricing-sub { font-size: 16px; color: var(--text-2); margin: 12px 0 0; line-height: 1.6; }
.pricing-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 20px;
}
.pricing-card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  padding: 28px;
  display: flex;
  flex-direction: column;
  transition: transform 0.2s cubic-bezier(0.4, 0, 0.2, 1), box-shadow 0.2s cubic-bezier(0.4, 0, 0.2, 1), border-color 0.2s cubic-bezier(0.4, 0, 0.2, 1), opacity 0.55s ease-out;
  opacity: 0;
  transform: translateY(12px);
}
.pricing-card:hover {
  transform: translateY(-2px);
  box-shadow: var(--shadow-md);
  border-color: rgba(var(--primary-rgb), 0.3);
}
.pricing-name { font-size: 19px; font-weight: 700; color: var(--text); margin: 0; }
.pricing-desc { font-size: 14px; color: var(--text-2); margin: 10px 0 0; line-height: 1.6; }
.pricing-fee {
  margin-top: 20px;
  padding: 16px 0;
  border-top: 1px solid var(--border-light);
  border-bottom: 1px solid var(--border-light);
}
.pricing-fee-label { font-size: 11px; color: var(--text-3); text-transform: uppercase; letter-spacing: 0.05em; }
.pricing-fee-value { font-size: 16px; font-weight: 600; color: var(--text); margin-top: 4px; }
.pricing-cta {
  margin-top: 20px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 10px 16px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  color: var(--text);
  font-size: 13px;
  font-weight: 500;
  text-decoration: none;
  font-family: inherit;
  transition: all 0.12s cubic-bezier(0.4, 0, 0.2, 1);
  align-self: flex-start;
}
.pricing-cta:hover {
  background: var(--primary);
  color: var(--text-inverse);
  border-color: var(--primary);
  transform: translateY(-1px);
}

/* enter animation */
.pricing-head > * { opacity: 0; transform: translateY(8px); transition: opacity 0.55s ease-out, transform 0.55s ease-out; }
.pricing.in-view .pricing-head > * { opacity: 1; transform: translateY(0); }
.pricing.in-view .pricing-card { opacity: 1; transform: translateY(0); }
.pricing.in-view .pricing-card:nth-child(1) { transition-delay: 0s; }
.pricing.in-view .pricing-card:nth-child(2) { transition-delay: 0.08s; }
.pricing.in-view .pricing-card:nth-child(3) { transition-delay: 0.16s; }

@media (max-width: 900px) {
  .pricing-grid { grid-template-columns: 1fr; }
}
@media (max-width: 560px) {
  .pricing { padding: 56px 0; }
  .pricing-inner { padding: 0 20px; }
  .pricing-title { font-size: 26px; }
}
</style>
