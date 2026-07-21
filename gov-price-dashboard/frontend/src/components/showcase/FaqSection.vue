<!--
  FaqSection.vue (2026-07-21 /home 新增)
  FAQ — 6 条折叠问答
-->
<script setup>
import { ref } from 'vue'
import { useInView } from '../../composables/useInView'
const { target, inView } = useInView()
const open = ref(0)

const faqs = [
  { q: '你一个人能扛大项目吗？', a: '能。规模在 OPC 边界内。超过此规模我会提前告知并建议扩队或外包分包，不暗中降质。' },
  { q: '工期和报价会变吗？', a: '报价单签前锁定。需求变更走书面补充协议，不口头承诺。' },
  { q: '数据从哪来？合规吗？', a: '全部来自政府/协会公开站点，严格遵守 robots.txt 与访问频次。' },
  { q: '能不能用我的私有数据源？', a: '能。采集、清洗、接入全链路都支持私有源定制。' },
  { q: '售后响应多久？', a: '工作日 4 小时内首响应，紧急工单 24h 内出修复方案。' },
  { q: '可以签合同 / NDA 吗？', a: '可以。私有部署场景常规配合签 NDA。' }
]
</script>

<template>
  <section ref="target" id="home-faq" class="faq" :class="{ 'in-view': inView }">
    <div class="faq-inner">
      <h2 class="faq-title">常见问题</h2>
      <p class="faq-sub">合作前最常被问到的几件事</p>
      <div class="faq-list">
        <div
          v-for="(f, i) in faqs"
          :key="f.q"
          class="faq-item"
          :class="{ open: open === i }"
        >
          <button
            class="faq-q"
            @click="open = open === i ? -1 : i"
            :aria-expanded="open === i"
          >
            <span>{{ f.q }}</span>
            <svg class="faq-icon" viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
              <polyline points="6 9 12 15 18 9" />
            </svg>
          </button>
          <div v-show="open === i" class="faq-a">{{ f.a }}</div>
        </div>
      </div>
    </div>
  </section>
</template>

<style scoped>
.faq { padding: 80px 0; background: var(--bg); }
.faq-inner { max-width: 760px; margin: 0 auto; padding: 0 32px; }
.faq-title {
  font-size: 30px;
  font-weight: 700;
  color: var(--text);
  text-align: center;
  margin: 0;
  letter-spacing: -0.01em;
}
.faq-sub { font-size: 16px; color: var(--text-2); text-align: center; margin: 12px 0 0; }
.faq-list { margin-top: 40px; border-top: 1px solid var(--border); }
.faq-item { border-bottom: 1px solid var(--border); }
.faq-q {
  width: 100%;
  background: transparent;
  border: none;
  padding: 20px 0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  font-family: inherit;
  font-size: 16px;
  font-weight: 500;
  color: var(--text);
  text-align: left;
  cursor: pointer;
  transition: color 0.12s cubic-bezier(0.4, 0, 0.2, 1);
}
.faq-q:hover { color: var(--primary); }
.faq-icon {
  color: var(--text-3);
  flex-shrink: 0;
  transition: transform 0.2s cubic-bezier(0.4, 0, 0.2, 1);
}
.faq-item.open .faq-icon { transform: rotate(180deg); color: var(--primary); }
.faq-a { padding: 0 0 20px; font-size: 15px; color: var(--text-2); line-height: 1.7; }

/* enter animation */
.faq-title, .faq-sub { opacity: 0; transform: translateY(8px); transition: opacity 0.5s ease-out, transform 0.5s ease-out; }
.faq.in-view .faq-title, .faq.in-view .faq-sub { opacity: 1; transform: translateY(0); }
.faq-item { opacity: 0; transform: translateY(8px); transition: opacity 0.45s ease-out, transform 0.45s ease-out; }
.faq.in-view .faq-item { opacity: 1; transform: translateY(0); }
.faq.in-view .faq-item:nth-child(1) { transition-delay: 0.05s; }
.faq.in-view .faq-item:nth-child(2) { transition-delay: 0.10s; }
.faq.in-view .faq-item:nth-child(3) { transition-delay: 0.15s; }
.faq.in-view .faq-item:nth-child(4) { transition-delay: 0.20s; }
.faq.in-view .faq-item:nth-child(5) { transition-delay: 0.25s; }
.faq.in-view .faq-item:nth-child(6) { transition-delay: 0.30s; }

@media (max-width: 560px) {
  .faq { padding: 56px 0; }
  .faq-inner { padding: 0 20px; }
  .faq-title { font-size: 26px; }
  .faq-q { font-size: 15px; padding: 16px 0; }
}
</style>
