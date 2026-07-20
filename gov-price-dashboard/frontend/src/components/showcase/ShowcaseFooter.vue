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
          <span class="s-footer-mark">OPC</span>
          <span class="s-footer-tag">个人 AI 工作站</span>
        </div>
        <div class="s-footer-meta">
          © 2026 · 运行于 Mac mini · 7×24 自跑
          · <a href="https://github.com/pengfit/cjt-skills" target="_blank" rel="noopener" class="s-footer-link">源码 ↗</a>
        </div>
      </div>
      <div class="s-footer-stack s-footer-stack-ai">
        <span class="stack-label">AI 协作栈</span>
        <span class="stack-item">OpenClaw</span>
        <span class="stack-sep">·</span>
        <span class="stack-item">Docker</span>
        <span class="stack-sep">·</span>
        <span class="stack-item">Dify</span>
        <span class="stack-sep">·</span>
        <span class="stack-item">DeepSeek</span>
        <span class="stack-sep">·</span>
        <span class="stack-item">Claude</span>
        <span class="stack-sep">·</span>
        <span class="stack-item">MiniMax</span>
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

.s-footer-mark {
  font-size: 14px;
  font-weight: 700;
  color: var(--primary);
  font-family: var(--font-mono-num);
  letter-spacing: -0.02em;
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

.s-footer-link {
  color: var(--primary);
  text-decoration: none;
  font-weight: 500;
  margin-left: 4px;
  transition: opacity 0.2s ease;
}

.s-footer-link:hover {
  opacity: 0.7;
  text-decoration: underline;
}

.s-footer-stack {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  font-size: 12px;
  color: var(--text-3);
}

.s-footer-stack-ai {
  /* AI 协作栈与 Case 完整栈互补:这里只显示 OPC 独有的 AI 能力 */
}

.s-footer-stack-ai .stack-label {
  font-weight: 600;
  color: var(--primary);
  letter-spacing: 0.04em;
}

.s-footer-stack-ai .stack-item {
  font-family: var(--font-mono-num);
  color: var(--text-2);
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
