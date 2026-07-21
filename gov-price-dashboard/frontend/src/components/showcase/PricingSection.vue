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
    <h2 class="section-title">如何合作</h2>
    <p class="section-sub">三种模式，按项目特征选。具体报价不在页面公开——聊完需求后发 PDF。</p>

      <div class="pricing-flow">
        <div class="pricing-flow-head">
          <span class="pricing-flow-icon">🐉</span>
          <h3 class="pricing-flow-title">为什么 3 档</h3>
        </div>
        <p class="pricing-flow-body">项目大小、持续性、调用量 —— 三种需求形态，对应三种合作深度。挑一档，不合适随时切换。AI 性能每升一代，这套项目自动升一代。</p>
      </div>

      <div class="pricing-grid">
        <div v-for="(p, i) in plans" :key="p.name" class="pricing-card">
          <div class="pricing-num">{{ String(i + 1).padStart(2, '0') }}</div>
          <h3 class="pricing-name">{{ p.name }}</h3>
          <p class="pricing-desc">{{ p.desc }}</p>
          <div class="pricing-fee">
            <span class="pricing-fee-label">计费</span>
            <div class="pricing-fee-value">{{ p.fee }}</div>
          </div>
          <button type="button" class="pricing-cta" disabled>{{ p.cta }}</button>
        </div>
      </div>
  </section>
</template>

<style scoped>
/* 横向 padding 由 HomeView 的 .showcase-main 统一提供,这里只管纵向 */
.pricing { padding: 96px 0 56px; }
.section-title {
  font-size: 28px;
  font-weight: 700;
  color: var(--text);
  margin: 0 0 8px;
  letter-spacing: -0.02em;
}
.section-sub { font-size: 14px; color: var(--text-2); margin: 0; }

/* 主色提示块 (对齐 .ws-ai-flow 视觉) */
.pricing-flow {
  margin-top: 24px;
  background: linear-gradient(135deg, var(--primary-dim, rgba(37, 99, 235, 0.06)) 0%, var(--surface) 100%);
  border: 1px solid var(--primary);
  border-radius: var(--radius-lg);
  padding: 28px 32px;
  margin-bottom: 32px;
  opacity: 0;
  transform: translateY(8px);
  transition: opacity 0.55s ease-out 0.10s, transform 0.55s ease-out 0.10s;
}
.pricing-flow-head {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 16px;
  padding-bottom: 14px;
  border-bottom: 1px solid var(--border-light);
}
.pricing-flow-icon {
  font-size: 24px;
}
.pricing-flow-title {
  font-size: 18px;
  font-weight: 700;
  color: var(--text);
  margin: 0;
  letter-spacing: -0.01em;
  flex: 1;
}
.pricing-flow-tag {
  font-size: 11px;
  font-weight: 600;
  color: white;
  background: var(--primary);
  padding: 4px 10px;
  border-radius: 999px;
  letter-spacing: 0.02em;
}
.pricing-flow-body {
  font-size: 14px;
  color: var(--text-2);
  line-height: 1.7;
  margin: 0;
}

.pricing-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 20px;
}
.pricing-card {
  background: linear-gradient(135deg, var(--primary-dim, rgba(37, 99, 235, 0.06)) 0%, var(--surface) 100%);
  border: 1px solid var(--primary);
  border-radius: var(--radius-lg);
  padding: 28px 24px;
  display: flex;
  flex-direction: column;
  transition: transform 0.2s cubic-bezier(0.4, 0, 0.2, 1), box-shadow 0.2s cubic-bezier(0.4, 0, 0.2, 1), opacity 0.55s ease-out;
  opacity: 0;
  transform: translateY(12px);
}
.pricing-num {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  background: var(--primary);
  color: white;
  border-radius: 50%;
  font-size: 11px;
  font-weight: 700;
  font-family: var(--font-mono-num);
  margin-bottom: 14px;
  margin-left: 2px;  /* 微调让数字圆点视觉居中,不贴边 */
  align-self: flex-start;
}
.pricing-card:hover {
  transform: translateY(-2px);
  box-shadow: 0 8px 24px rgba(30, 64, 175, 0.18);
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
.pricing-cta:hover:not(:disabled) {
  background: var(--primary);
  color: var(--text-inverse);
  border-color: var(--primary);
  transform: translateY(-1px);
}
.pricing-cta:disabled {
  opacity: 0.55;
  cursor: not-allowed;
  background: var(--surface);
  color: var(--text-3);
  border-color: var(--border);
}

/* enter animation (opacity-only,不动 Y 位,免与 workspace 标题错位) */
.section-title, .section-sub { opacity: 0; transition: opacity 0.55s ease-out; }
.pricing.in-view .section-title, .pricing.in-view .section-sub { opacity: 1; }
.pricing.in-view .pricing-flow { opacity: 1; transform: translateY(0); }
.pricing.in-view .pricing-card { opacity: 1; transform: translateY(0); }
.pricing.in-view .pricing-card:nth-child(1) { transition-delay: 0.18s; }
.pricing.in-view .pricing-card:nth-child(2) { transition-delay: 0.26s; }
.pricing.in-view .pricing-card:nth-child(3) { transition-delay: 0.34s; }

@media (max-width: 900px) {
  .pricing-grid { grid-template-columns: 1fr; }
  .pricing-flow { padding: 24px; }
}
@media (max-width: 560px) {
  .pricing { padding: 56px 20px; }
  .section-title { font-size: 26px; }
  .pricing-flow-head { flex-wrap: wrap; }
  .pricing-flow-title { font-size: 16px; }
}
</style>
