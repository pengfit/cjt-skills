<!--
  ShowcaseFooter.vue - 底部
  技术栈 + 数据来源 + 版权
  2026-07-19:删除 cjt 标记
-->
<template>
  <footer class="s-footer">
    <div class="s-footer-inner">
      <div class="s-footer-row">
        <div class="s-footer-brand">
          <span class="s-footer-tag">材料价格数据中台</span>
        </div>
        <div class="s-footer-meta">
          © 2026 · 数据来源各地住建局 / 造价站
        </div>
      </div>
      <div class="s-footer-stack">
        <span class="stack-label">技术栈</span>
        <span class="stack-item">Python 3</span>
        <span class="stack-sep">·</span>
        <span class="stack-item">Elasticsearch</span>
        <span class="stack-sep">·</span>
        <span class="stack-item">FastAPI</span>
        <span class="stack-sep">·</span>
        <span class="stack-item">Vue 3</span>
        <span class="stack-sep">·</span>
        <span class="stack-item">ECharts</span>
      </div>
    </div>
  </footer>
</template>

<script setup>
// 无状态
</script>

<style scoped>
.s-footer {
  margin-top: 64px;
  padding: 32px 0;
  background: var(--surface);
  border-top: 1px solid var(--border-light);
}

.s-footer-inner {
  max-width: 1200px;
  margin: 0 auto;
  padding: 0 32px;
}

.s-footer-row {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  margin-bottom: 16px;
  padding-bottom: 16px;
  border-bottom: 1px solid var(--border-light);
}

.s-footer-brand {
  display: flex;
  align-items: baseline;
  gap: 10px;
}

.s-footer-tag {
  font-size: 14px;
  font-weight: 500;
  color: var(--text);
}

.s-footer-meta {
  font-size: 12px;
  color: var(--text-3);
}

.s-footer-stack {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  font-size: 12px;
  color: var(--text-3);
}

.stack-label {
  font-weight: 500;
  color: var(--text-2);
}

.stack-item {
  font-family: var(--font-mono-num);
}

.stack-sep {
  color: var(--border-strong);
}

@media (max-width: 640px) {
  .s-footer-inner { padding: 0 20px; }
  .s-footer-row { flex-direction: column; align-items: flex-start; gap: 8px; }
}
</style>
