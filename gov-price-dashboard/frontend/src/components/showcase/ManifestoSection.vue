<!--
  ManifestoSection.vue (2026-07-21 14:54 第四版 · 道友修真版)
  OPC 宣言 · 单句逗号断句 8 行共养式叙事
  line 5 微调:OpenClaw 自己"养"出来(单方主语,把"我们"具体化)
-->
<script setup>
import { useInView } from '../../composables/useInView'
const { target, inView } = useInView()
</script>

<template>
  <section ref="target" class="manifesto" :class="{ 'in-view': inView }">
    <div class="manifesto-inner">
      <h2 class="manifesto-title">我们一起养"龙虾"。</h2>
      <div class="manifesto-bodies">
        <p class="manifesto-body">这里不是"一个人啥都干"。</p>
        <p class="manifesto-body">OpenClaw 提供养育场 —— 边界、节奏、习惯,沉淀。</p>
        <p class="manifesto-body">AI 提供每天在长的算力;</p>
        <p class="manifesto-body">人提供行业 know-how 与日常照料。</p>
        <p class="manifesto-body">OpenClaw 不是我"会"的工具,是 OpenClaw 自己"养"出来的工作场。</p>
        <p class="manifesto-body">所以交付出来的不是"商品",是会生长的有机体。</p>
        <p class="manifesto-body">你提需求,它长出新能力;你照料一天,它的边界扩一点。</p>
        <p class="manifesto-body">这就是"龙虾"饲养员 —— 你照料一日,它长出一支队伍的输出。</p>
      </div>
    </div>
  </section>
</template>

<style scoped>
.manifesto {
  padding: 96px 0 80px;
  background: var(--surface-2);
}
.manifesto-inner {
  max-width: 720px;
  margin: 0 auto;
  padding: 0 32px;
}
.manifesto-title {
  font-size: 28px;
  font-weight: 700;
  color: var(--text);
  text-align: center;
  letter-spacing: -0.01em;
  margin: 0 0 40px;
  line-height: 1.4;
}
.manifesto-bodies { display: block; }
.manifesto-body {
  font-size: 17px;
  line-height: 2;
  color: var(--text-2);
  margin: 0 0 28px;
  letter-spacing: 0.01em;
}
.manifesto-body:last-child { margin-bottom: 0; }
.manifesto-body strong {
  color: var(--text);
  font-weight: 700;
}

/* enter animation */
.manifesto-title,
.manifesto-body {
  opacity: 0;
  transform: translateY(16px);
  transition: opacity 1.6s ease-out, transform 1.6s ease-out;
}
.manifesto.in-view .manifesto-title { opacity: 1; transform: translateY(0); transition-delay: 0s; }
.manifesto.in-view .manifesto-body:nth-of-type(1) { opacity: 1; transform: translateY(0); transition-delay: 0.32s; }
.manifesto.in-view .manifesto-body:nth-of-type(2) { opacity: 1; transform: translateY(0); transition-delay: 0.50s; }
.manifesto.in-view .manifesto-body:nth-of-type(3) { opacity: 1; transform: translateY(0); transition-delay: 0.68s; }
.manifesto.in-view .manifesto-body:nth-of-type(4) { opacity: 1; transform: translateY(0); transition-delay: 0.86s; }
.manifesto.in-view .manifesto-body:nth-of-type(5) { opacity: 1; transform: translateY(0); transition-delay: 1.04s; }
.manifesto.in-view .manifesto-body:nth-of-type(6) { opacity: 1; transform: translateY(0); transition-delay: 1.22s; }
.manifesto.in-view .manifesto-body:nth-of-type(7) { opacity: 1; transform: translateY(0); transition-delay: 1.40s; }
.manifesto.in-view .manifesto-body:nth-of-type(8) { opacity: 1; transform: translateY(0); transition-delay: 1.58s; }

@media (max-width: 640px) {
  .manifesto { padding: 64px 0 56px; }
  .manifesto-inner { padding: 0 20px; max-width: 100%; }
  .manifesto-title { font-size: 22px; margin-bottom: 28px; }
  .manifesto-body { font-size: 15px; line-height: 1.9; margin-bottom: 22px; }
  .manifesto.in-view .manifesto-body { transition-duration: 1.2s; }
}
</style>
