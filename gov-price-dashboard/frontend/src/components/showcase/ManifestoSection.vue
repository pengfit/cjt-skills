<!--
  ManifestoSection.vue (2026-07-21 /home 新增)
  OPC 宣言 — Hero 后紧跟的"为什么选 OPC"短段
-->
<script setup>
import { useInView } from '../../composables/useInView'
const { target, inView } = useInView()
</script>

<template>
  <section ref="target" class="manifesto" :class="{ 'in-view': inView }">
    <div class="manifesto-inner">
      <h2 class="manifesto-title">OPC 不是营销话术，是真交付方式。</h2>
      <div class="manifesto-bodies">
        <p class="manifesto-body">
          在 Pengfit，对接人是交付人，交付人是对接人。需求、报价、实现、上线、运维——没有中间商，一个人闭环跑完。
        </p>
        <p class="manifesto-body">
          你省下的不是钱，是沟通损耗和责任真空。
        </p>
      </div>
    </div>
  </section>
</template>

<style scoped>
.manifesto {
  padding: 80px 0;
  background: var(--surface-2);
}
.manifesto-inner {
  max-width: 760px;
  margin: 0 auto;
  padding: 0 32px;
}
.manifesto-title {
  font-size: 32px;
  font-weight: 700;
  color: var(--text);
  text-align: center;
  letter-spacing: -0.01em;
  margin: 0 0 32px;
  line-height: 1.35;
}
.manifesto-bodies { display: block; }
.manifesto-body {
  font-size: 17px;
  line-height: 1.85;
  color: var(--text-2);
  margin: 0 0 18px;
}
.manifesto-body:last-child { margin-bottom: 0; }

/* enter animation */
.manifesto-title,
.manifesto-body {
  opacity: 0;
  transform: translateY(12px);
  transition: opacity 0.6s ease-out, transform 0.6s ease-out;
}
.manifesto.in-view .manifesto-title { opacity: 1; transform: translateY(0); transition-delay: 0s; }
.manifesto.in-view .manifesto-body:nth-of-type(1) { opacity: 1; transform: translateY(0); transition-delay: 0.12s; }
.manifesto.in-view .manifesto-body:nth-of-type(2) { opacity: 1; transform: translateY(0); transition-delay: 0.22s; }

@media (max-width: 640px) {
  .manifesto { padding: 56px 0; }
  .manifesto-inner { padding: 0 20px; }
  .manifesto-title { font-size: 24px; }
  .manifesto-body { font-size: 15px; }
}
</style>
