<!--
  ShowcaseFooter.vue - 底部
  技术栈 + 数据来源 + 版权
  2026-07-19:删除 cjt 标记
  2026-07-20: OPC 文字 mark 替换成 OPC Icon (修改 9)
-->
<template>
  <footer class="s-footer">
    <div class="s-footer-inner">
      <div class="s-footer-row">
        <div class="s-footer-brand">
          <svg class="opc-icon" viewBox="0 0 32 32" width="18" height="18" aria-label="Pengfit" role="img">
            <circle cx="16" cy="16" r="14.5" fill="none" stroke="currentColor" stroke-width="1.2" opacity="0.55" stroke-dasharray="2 2"/>
            <circle cx="16" cy="12" r="3" fill="currentColor"/>
            <path d="M 10 22 Q 10 17 16 17 Q 22 17 22 22 Z" fill="currentColor"/>
            <line x1="13" y1="13.5" x2="7.5" y2="9" stroke="currentColor" stroke-width="1" opacity="0.5"/>
            <line x1="19" y1="13.5" x2="24.5" y2="9" stroke="currentColor" stroke-width="1" opacity="0.5"/>
            <line x1="16" y1="19" x2="16" y2="26" stroke="currentColor" stroke-width="1" opacity="0.5"/>
            <circle cx="6.5" cy="8.5" r="2" fill="currentColor"/>
            <circle cx="25.5" cy="8.5" r="2" fill="currentColor"/>
            <circle cx="16" cy="27.5" r="2" fill="currentColor"/>
          </svg>
          <span class="s-footer-tag">Pengfit</span>
        </div>
        <div class="s-footer-meta">
          © 2026 · 运行于一台电脑 · 0 人工值班
          · <a href="https://github.com/pengfit/cjt-skills" target="_blank" rel="noopener" class="s-footer-link">源码 ↗</a>
        </div>
      </div>
      <!-- 2026-07-21 移除 AI 协作栈 -->
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
  align-items: center;
  gap: 10px;
}

.opc-icon {
  color: var(--primary);
  flex-shrink: 0;
  display: block;
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
