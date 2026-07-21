<!--
  NotFoundView.vue (2026-07-20 #19)
  友好 404 页面: 任何未匹配的 URL 显示这个
  - 大字号 404
  - 说明 + 返回首页按钮
  - 主题色 + 动效
-->
<template>
  <div class="not-found">
    <div class="not-found-inner">
      <div class="not-found-code">
        <span>4</span>
        <span class="oops">0</span>
        <span>4</span>
      </div>
      <h1 class="not-found-title">页面不存在</h1>
      <p class="not-found-desc">
        你访问的 URL <code>{{ route.path }}</code> 没有匹配到任何页面。
        <br />可能是链接拼错,或者页面已迁移。
      </p>
      <div class="not-found-actions">
        <router-link to="/home" class="nf-btn nf-btn-primary">
          ← 返回 Pengfit 落地页
        </router-link>
        <a href="javascript:history.back()" class="nf-btn nf-btn-ghost">
          ← 返回上一页
        </a>
      </div>
    </div>
  </div>
</template>

<script setup>
import { useRoute } from 'vue-router'
const route = useRoute()
</script>

<style scoped>
.not-found {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 80px 20px;
  background: var(--bg);
  color: var(--text);
}

.not-found-inner {
  max-width: 520px;
  text-align: center;
}

.not-found-code {
  display: flex;
  justify-content: center;
  gap: 4px;
  font-size: 96px;
  font-weight: 800;
  font-family: var(--font-mono-num);
  line-height: 1;
  margin-bottom: 24px;
  color: var(--primary);
  letter-spacing: -0.04em;
}
.not-found-code .oops {
  color: var(--text-3);
  position: relative;
  animation: nf-spin 4s ease-in-out infinite;
}
@keyframes nf-spin {
  0%, 100% { transform: rotate(0deg); }
  25% { transform: rotate(-15deg); }
  75% { transform: rotate(15deg); }
}

.not-found-title {
  font-size: 28px;
  font-weight: 700;
  color: var(--text);
  margin: 0 0 12px;
  letter-spacing: -0.01em;
}

.not-found-desc {
  font-size: 14px;
  color: var(--text-2);
  line-height: 1.7;
  margin: 0 0 32px;
}
.not-found-desc code {
  background: var(--surface-2);
  padding: 2px 6px;
  border-radius: 4px;
  font-family: var(--font-mono-num);
  font-size: 12px;
  color: var(--primary);
  border: 1px solid var(--border);
}

.not-found-actions {
  display: flex;
  gap: 12px;
  justify-content: center;
  flex-wrap: wrap;
}

.nf-btn {
  display: inline-flex;
  align-items: center;
  padding: 12px 24px;
  font-size: 14px;
  font-weight: 600;
  border-radius: 10px;
  text-decoration: none;
  transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
  cursor: pointer;
  font-family: inherit;
}
.nf-btn-primary {
  background: var(--primary-grad);
  color: #ffffff;
  border: 1px solid var(--primary);
  box-shadow: var(--shadow-primary);
}
.nf-btn-primary:hover {
  background: var(--primary-grad-hover);
  transform: translateY(-2px);
  box-shadow: 0 8px 20px rgba(30, 64, 175, 0.25);
}
.nf-btn-ghost {
  background: var(--surface);
  color: var(--text-2);
  border: 1px solid var(--border);
}
.nf-btn-ghost:hover {
  background: var(--surface-2);
  color: var(--text);
  border-color: var(--border-strong);
}

@media (max-width: 480px) {
  .not-found-code { font-size: 72px; }
  .not-found-title { font-size: 22px; }
  .not-found-actions { flex-direction: column; align-items: stretch; }
  .nf-btn { justify-content: center; }
}
</style>
