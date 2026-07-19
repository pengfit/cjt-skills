<!--
  ShowcaseHero.vue (2026-07-19 标题改名 + 简化)

  极简工程风:
  - 单行大标题:中国材料价格中台(8 字)
  - 一句话副标题:动作链
  - 1 个 CTA(了解更多)
  - 无 stats strip(数字挪到 Metrics inline)

  不再注入 stats(标题不再用数字),保持组件纯净。
-->
<template>
  <section class="hero">
    <div class="hero-inner">
      <h1 class="hero-title">材料价格中台</h1>
      <p class="hero-sub">自动采集 · 智能归一 · 可视化分析</p>
      <a href="#capabilities" class="hero-cta">
        了解更多 <span class="arrow">↓</span>
      </a>
    </div>
  </section>
</template>

<script setup>
// 无状态、无注入:标题是静态文本
</script>

<style scoped>
.hero {
  padding: 120px 0 80px;
}

.hero-inner {
  max-width: 880px;
}

.hero-title {
  font-size: clamp(40px, 5vw, 60px);
  font-weight: 700;
  line-height: 1.15;
  letter-spacing: -0.03em;
  color: var(--text);
  margin: 0 0 20px;
}

.hero-sub {
  font-size: 17px;
  line-height: 1.6;
  color: var(--text-2);
  margin: 0 0 32px;
  font-weight: 400;
}

.hero-cta {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 10px 18px;
  font-size: 14px;
  font-weight: 500;
  color: var(--text);
  text-decoration: none;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--surface);
  transition: all var(--transition);
}

.hero-cta:hover {
  border-color: var(--text);
  background: var(--surface-2);
}

.hero-cta .arrow {
  font-size: 13px;
  transition: transform var(--transition);
}

.hero-cta:hover .arrow {
  transform: translateY(2px);
}

@media (max-width: 640px) {
  .hero { padding: 64px 0 48px; }
}
</style>
