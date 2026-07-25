<!--
  MobileBlockedView.vue (2026-07-25)
  移动端访问非驾驶舱 admin 页时,展示全屏拦截页:
  请前往电脑端浏览器查看。
  - 完全独立组件,无外部依赖(纯 Vue 模板 + scoped style)
  - router 守卫会在 mobile + admin-non-cockpit 时跳到 /mobile-blocked?from=<原路径>
  - 「前往驾驶舱」按钮兜底回 /cockpit;「查看源网站」备一个公开页链接
-->
<template>
  <div class="mobile-blocked">
    <div class="mb-card">
      <div class="mb-icon">
        <svg viewBox="0 0 24 24" width="64" height="64" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
          <rect x="2" y="3" width="20" height="14" rx="2" ry="2" />
          <line x1="8" y1="21" x2="16" y2="21" />
          <line x1="12" y1="17" x2="12" y2="21" />
          <!-- 禁用斜线 -->
          <line x1="3" y1="3" x2="21" y2="17" stroke="#ef4444" stroke-width="2" />
        </svg>
      </div>
      <h1 class="mb-title">请前往电脑端浏览器查看</h1>
      <p class="mb-subtitle">
        复杂的查询、筛选与数据治理界面，需要更宽的屏幕才能正常显示。
        手机端仅开放「驾驶舱」，提供整体概况。
      </p>

      <div v-if="fromPath" class="mb-from">
        您尝试访问: <code>{{ fromPath }}</code>
      </div>

      <div class="mb-actions">
        <button class="mb-btn mb-btn-primary" type="button" @click="goCockpit">
          🛸 前往驾驶舱
        </button>
        <router-link to="/market" class="mb-btn mb-btn-secondary">
          🌡️ 查看公开市场行情（移动端友好）
        </router-link>
      </div>

      <details class="mb-tip">
        <summary>为什么不能在手机上打开?</summary>
        <ul>
          <li>数据列表类（全部数据 / 价格分布 / 数据健康）需横向滚动 + 卡片式排列，操作体验差</li>
          <li>复杂表单（如筛选抽屉）按钮密度高，容易误触</li>
          <li>驾驶舱总览是唯一为手机端做过专项适配的页面</li>
        </ul>
      </details>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'

const route = useRoute()
const router = useRouter()

const fromPath = computed(() => {
  const f = route.query.from
  return typeof f === 'string' ? f : ''
})

function goCockpit() {
  router.push('/cockpit')
}
</script>

<style scoped>
.mobile-blocked {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px 18px;
  background:
    radial-gradient(ellipse at top, rgba(99, 102, 241, 0.08) 0%, transparent 60%),
    linear-gradient(180deg, #f8fafc 0%, #eef2f7 100%);
}

[data-theme="dark"] .mobile-blocked,
.dark .mobile-blocked {
  background:
    radial-gradient(ellipse at top, rgba(99, 102, 241, 0.12) 0%, transparent 60%),
    linear-gradient(180deg, #0f172a 0%, #020617 100%);
}

.mb-card {
  width: 100%;
  max-width: 460px;
  background: #ffffff;
  border-radius: 18px;
  padding: 32px 28px;
  box-shadow: 0 12px 40px rgba(15, 23, 42, 0.08), 0 2px 8px rgba(15, 23, 42, 0.04);
  text-align: center;
}

[data-theme="dark"] .mb-card,
.dark .mb-card {
  background: #1e293b;
  color: #e2e8f0;
}

.mb-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 88px;
  height: 88px;
  border-radius: 50%;
  background: rgba(239, 68, 68, 0.08);
  color: #ef4444;
  margin: 0 auto 20px;
}

.mb-title {
  font-size: 22px;
  font-weight: 700;
  margin: 0 0 12px;
  color: #0f172a;
  letter-spacing: -0.3px;
}

[data-theme="dark"] .mb-title,
.dark .mb-title {
  color: #f1f5f9;
}

.mb-subtitle {
  font-size: 14px;
  line-height: 1.6;
  color: #475569;
  margin: 0 0 20px;
}

[data-theme="dark"] .mb-subtitle,
.dark .mb-subtitle {
  color: #94a3b8;
}

.mb-from {
  font-size: 12px;
  color: #64748b;
  background: #f1f5f9;
  border-radius: 8px;
  padding: 8px 12px;
  margin-bottom: 20px;
  word-break: break-all;
}

[data-theme="dark"] .mb-from,
.dark .mb-from {
  background: #0f172a;
  color: #94a3b8;
}

.mb-from code {
  font-family: var(--font-mono);
  color: #0ea5e9;
}

.mb-actions {
  display: flex;
  flex-direction: column;
  gap: 10px;
  margin-bottom: 24px;
}

.mb-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 12px 20px;
  border-radius: 10px;
  font-size: 15px;
  font-weight: 600;
  text-decoration: none;
  cursor: pointer;
  transition: all 0.2s ease;
  border: 1px solid transparent;
}

.mb-btn-primary {
  background: linear-gradient(135deg, #3b82f6, #2563eb);
  color: #fff;
  box-shadow: 0 4px 12px rgba(37, 99, 235, 0.25);
}
.mb-btn-primary:hover {
  transform: translateY(-1px);
  box-shadow: 0 6px 18px rgba(37, 99, 235, 0.35);
}

.mb-btn-secondary {
  background: #f8fafc;
  color: #475569;
  border-color: #cbd5e1;
}
.mb-btn-secondary:hover {
  background: #e2e8f0;
}

[data-theme="dark"] .mb-btn-secondary,
.dark .mb-btn-secondary {
  background: #0f172a;
  color: #cbd5e1;
  border-color: #334155;
}

.mb-tip {
  text-align: left;
  font-size: 13px;
  color: #64748b;
  background: #f8fafc;
  border-radius: 10px;
  padding: 10px 14px;
}

[data-theme="dark"] .mb-tip,
.dark .mb-tip {
  background: #0f172a;
  color: #94a3b8;
}

.mb-tip summary {
  cursor: pointer;
  font-weight: 600;
  color: #334155;
  margin-bottom: 6px;
}

[data-theme="dark"] .mb-tip summary,
.dark .mb-tip summary {
  color: #cbd5e1;
}

.mb-tip ul {
  margin: 8px 0 0;
  padding-left: 18px;
  line-height: 1.7;
}

.mb-tip li {
  margin: 4px 0;
}

@media (max-width: 380px) {
  .mb-card { padding: 24px 18px; }
  .mb-title { font-size: 18px; }
  .mb-icon { width: 72px; height: 72px; }
  .mb-icon svg { width: 52px; height: 52px; }
}
</style>