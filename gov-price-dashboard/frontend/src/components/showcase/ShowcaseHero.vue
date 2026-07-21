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
      <span class="hero-tag">Pengfit</span>
      <h1 class="hero-title">"龙虾"饲养员</h1>
      <p class="hero-sub">OpenClaw · 多模型协作 · Dify Workflow · Docker<br/>不是个人工具，是 饲养员场地 的工作范式</p>
      <a href="#case" class="hero-cta">
        查看案例 <span class="arrow">↓</span>
      </a>
    </div>
  </section>
</template>

<script setup>
// 无状态、无注入:标题是静态文本
</script>

<style scoped>
.hero {
  padding: 96px 0 40px;  /* 2026-07-20 #3 间距统一 (上 96px) */
}

.hero-inner {
  max-width: 880px;
}

.hero-tag {
  /* 2026-07-20 #8 呼吸灯: box-shadow 慢脉冲 2.4s */
  display: inline-block;
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.08em;
  color: var(--primary);
  padding: 4px 10px;
  border: 1px solid var(--primary);
  border-radius: 999px;  /* 2026-07-20 #4 圆角统一: badge 用 round */
  margin-bottom: 24px;
  font-family: var(--font-mono-num);
  background: var(--primary-dim, rgba(37, 99, 235, 0.06));
  animation: hero-tag-breath 2.4s ease-in-out infinite;
}

@keyframes hero-tag-breath {
  0%, 100% { box-shadow: 0 0 0 0 rgba(30, 64, 175, 0); }
  50%      { box-shadow: 0 0 0 6px rgba(30, 64, 175, 0.15); }
}

.hero-gt {
  color: var(--primary);
  font-weight: 800;
  margin: 0 4px;
  letter-spacing: -0.05em;
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
  /* 2026-07-20 #6 升级: 渐变 + 强阴影 + hover scale + 高光扫过 */
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 14px 32px;
  font-size: 15px;
  font-weight: 600;
  color: #ffffff;
  text-decoration: none;
  border: 1px solid var(--primary);
  border-radius: 10px;  /* 2026-07-20 #4 圆角统一: 按钮用 10px */
  background: var(--primary-grad);
  box-shadow: var(--shadow-primary);
  transition: all 0.25s cubic-bezier(0.4, 0, 0.2, 1);
  position: relative;
  overflow: hidden;
}

.hero-cta::before {
  content: '';
  position: absolute;
  top: 0;
  left: -100%;
  width: 100%;
  height: 100%;
  background: linear-gradient(90deg, transparent 0%, rgba(255,255,255,0.18) 50%, transparent 100%);
  transition: left 0.6s ease;
}
.hero-cta:hover::before { left: 100%; }
.hero-cta:hover {
  background: var(--primary-grad-hover);
  transform: translateY(-2px) scale(1.02);
  box-shadow: 0 8px 20px rgba(30,64,175,0.25);
}
.hero-cta:active { transform: translateY(0) scale(0.99); }

.hero-cta:hover {
  /* hover 效果已合并到主块 */
  border-color: var(--primary);
}

.hero-cta .arrow {
  /* 2026-07-20 #6 SVG + 弹跳 */
  display: inline-block;
  flex-shrink: 0;
  transition: transform 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.hero-cta:hover .arrow {
  transform: translateY(4px);
  animation: hero-arrow-bounce 0.6s ease-in-out infinite;
}

@keyframes hero-arrow-bounce {
  0%, 100% { transform: translateY(4px); }
  50% { transform: translateY(9px); }
}

/* 弹跳 keyframe 已合并到 .hero-cta .arrow 块 */

@media (max-width: 640px) {
  .hero { padding: 64px 0 48px; }
}

/* 2026-07-20 #22 向下滚动提示 */
.scroll-hint {
  display: inline-flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
  margin-top: 32px;
  color: var(--text-3);
  font-size: 11px;
  font-weight: 500;
  letter-spacing: 0.5px;
  text-transform: uppercase;
  animation: scroll-hint-bounce 2s ease-in-out infinite;
  transition: opacity 0.4s ease;
}
.scroll-hint-arrow {
  opacity: 0.7;
}

@keyframes scroll-hint-bounce {
  0%, 100% { transform: translateY(0); }
  50% { transform: translateY(6px); }
}
</style>
