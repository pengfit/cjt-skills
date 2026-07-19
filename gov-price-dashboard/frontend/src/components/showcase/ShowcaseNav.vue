<!--
  ShowcaseNav.vue - 顶部极简 nav
  公开访客用,只放 logo + "进入 Dashboard" CTA
-->
<template>
  <nav class="s-nav">
    <div class="s-nav-inner">
      <router-link to="/index" class="s-brand">
        <span class="s-brand-text">材料价格数据中台</span>
      </router-link>
      <a href="/cockpit" class="s-cta">
        进入 Dashboard <span class="arrow">→</span>
      </a>
    </div>
  </nav>
</template>

<script setup>
// 无状态
</script>

<style scoped>
.s-nav {
  position: sticky;
  top: 0;
  z-index: 100;
  background: rgba(248, 250, 252, 0.85);
  backdrop-filter: saturate(180%) blur(12px);
  -webkit-backdrop-filter: saturate(180%) blur(12px);
  border-bottom: 1px solid var(--border-light);
}

.s-nav-inner {
  max-width: 1200px;
  margin: 0 auto;
  padding: 0 32px;
  height: 64px;
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.s-brand {
  display: flex;
  align-items: baseline;
  gap: 12px;
  text-decoration: none;
  color: var(--text);
}

.s-brand-mark {
  font-size: 18px;
  font-weight: 700;
  letter-spacing: -0.02em;
  color: var(--primary);
}

.s-brand-text {
  font-size: 14px;
  color: var(--text-2);
}

.s-cta {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 8px 16px;
  font-size: 14px;
  font-weight: 500;
  color: var(--primary);
  text-decoration: none;
  border: 1px solid var(--border);
  border-radius: var(--radius);
  background: var(--surface);
  transition: all var(--transition);
}

.s-cta:hover {
  background: var(--primary);
  color: var(--text-inverse);
  border-color: var(--primary);
}

.s-cta .arrow {
  transition: transform var(--transition);
}

.s-cta:hover .arrow {
  transform: translateX(2px);
}

@media (max-width: 640px) {
  .s-brand-text { display: none; }
  .s-nav-inner { padding: 0 20px; }
}
</style>
