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
      <span class="hero-tag">OPC · Open Personal Computing</span>
      <h1 class="hero-title">一台 Mac mini,<br/>撑起的 AI 工作站</h1>
      <p class="hero-sub">OpenClaw · 多模型协作 · Dify Workflow · Docker<br/>不是产品宣传,是一个工作范式与每日自跑的系统</p>
      <a href="#arch" class="hero-cta">
        看怎么搭 <span class="arrow">↓</span>
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

.hero-tag {
  display: inline-block;
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.08em;
  color: var(--primary);
  padding: 4px 10px;
  border: 1px solid var(--primary);
  border-radius: 4px;
  margin-bottom: 24px;
  font-family: var(--font-mono-num);
  background: var(--primary-dim, rgba(37, 99, 235, 0.06));
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
  line-height: 1.7;
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
