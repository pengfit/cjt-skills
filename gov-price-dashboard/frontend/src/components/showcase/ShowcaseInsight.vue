<!--
  ShowcaseInsight.vue (2026-07-20 新增 - OPC P0)

  对外首页 AI 洞察段 — 由 agent cron 写 /data/showcase/insight.md,
  前端 mount 时 fetch /api/showcase/insight。

  OPC 范式:
    Agent cron → 写静态文件 → FastAPI 只读 → Vue 只读 API → 零耦合
    文件不存在时显示引导文案,不破坏对外展示。
-->
<template>
  <div class="insight" id="insight">
    <div class="insight-card">
      <div class="insight-head">
        <span class="insight-dot" :class="{ live: hasContent }"></span>
        <span class="insight-label">AI 洞察</span>
        <span class="insight-source" v-if="hasContent">Agent · 每日 02:35 自动生成</span>
        <span class="insight-time" v-if="updatedAt">{{ formatTime(updatedAt) }}</span>
      </div>
      <div class="insight-body" v-if="hasContent" v-html="rendered"></div>
      <div class="insight-body empty" v-else>
        <p><strong>OPC 工作站已就绪</strong> · 洞察正在生成中…</p>
        <p class="insight-hint">
          Agent 按日读汇总 → 模板生成 → 写静态文件 → 前端只读<br/>
          每日 02:35 cron 跑完后自动出现。
        </p>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, onBeforeUnmount, computed } from 'vue'

const markdown = ref('')
const updatedAt = ref('')
let refreshHandle = null

const hasContent = computed(() => {
  if (!markdown.value) return false
  // 兑底文案里带"暂未生成",判定为空
  return !markdown.value.includes('暂未生成')
})

const rendered = computed(() => {
  // 极简 markdown 渲染(段落 + **bold** + ⚠️ 高亮),不引第三方库
  return markdown.value
    .replace(/<!--[\s\S]*?-->/g, '')  // 去掉 HTML 注释(updated_at 行)
    .split(/\n\n+/)
    .filter(p => p.trim())
    .map(p => {
      let html = escape(p)
      html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
      html = html.replace(/⚠️/g, '<span class="warn">⚠️</span>')
      return `<p>${html.replace(/\n/g, '<br/>')}</p>`
    })
    .join('')
})

function escape(s) {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
}

function formatTime(iso) {
  // 2026-07-20T07:07:58Z → 07-20 07:07
  // 显示「X 分钟前」相对时间,文件不刷新也能看出新鲜度
  try {
    const d = new Date(iso)
    const now = new Date()
    const diffMs = now - d
    const diffMin = Math.floor(diffMs / 60000)
    if (diffMin < 1) return '刚刚'
    if (diffMin < 60) return `${diffMin} 分钟前`
    const diffHr = Math.floor(diffMin / 60)
    if (diffHr < 24) return `${diffHr} 小时前`
    const mm = String(d.getMonth() + 1).padStart(2, '0')
    const dd = String(d.getDate()).padStart(2, '0')
    const hh = String(d.getHours()).padStart(2, '0')
    const mi = String(d.getMinutes()).padStart(2, '0')
    return `${mm}-${dd} ${hh}:${mi}`
  } catch {
    return ''
  }
}

async function refreshInsight() {
  try {
    const r = await fetch('/api/showcase/insight')
    if (!r.ok) return
    const data = await r.json()
    markdown.value = data.markdown || ''
    updatedAt.value = data.updated_at || ''
  } catch (e) {
    // 网络失败静默,fallback 到"暂未生成"文案
    console.warn('[showcase-insight] fetch failed:', e)
  }
}

onMounted(() => {
  refreshInsight()
  // 每 60s 自动 refresh,让 updated_at 保持新鲜
  refreshHandle = setInterval(refreshInsight, 60_000)
})

onBeforeUnmount(() => {
  // 清理 interval,避免 HMR 累积
  if (refreshHandle) clearInterval(refreshHandle)
})
</script>

<style scoped>
.insight {
  padding: 24px 0 0;
  margin: 0 0 48px 0;
}

.insight-card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  padding: 20px 24px;
  position: relative;
}

.insight-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 12px;
  padding-bottom: 12px;
  border-bottom: 1px solid var(--border-light);
}

.insight-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--border-strong);
  flex-shrink: 0;
}

.insight-dot.live {
  background: #10b981;
  box-shadow: 0 0 0 4px rgba(16, 185, 129, 0.15);
  animation: pulse 2.4s ease-in-out infinite;
}

@keyframes pulse {
  0%, 100% { box-shadow: 0 0 0 4px rgba(16, 185, 129, 0.15); }
  50% { box-shadow: 0 0 0 7px rgba(16, 185, 129, 0.04); }
}

.insight-label {
  font-size: 12px;
  font-weight: 600;
  color: var(--text);
  letter-spacing: 0.02em;
}

.insight-source {
  font-size: 11px;
  color: var(--text-3);
  padding: 2px 8px;
  background: var(--surface-2);
  border-radius: 3px;
  font-family: var(--font-mono-num);
}

.insight-time {
  margin-left: auto;
  font-size: 11px;
  color: var(--text-3);
  font-family: var(--font-mono-num);
}

.insight-body {
  font-size: 14px;
  line-height: 1.85;
  color: var(--text);
}

.insight-body :deep(p) {
  margin: 0 0 10px;
}

.insight-body :deep(p:last-child) {
  margin-bottom: 0;
}

.insight-body :deep(strong) {
  color: var(--primary);
  font-weight: 600;
}

.insight-body :deep(.warn) {
  color: #d97706;
}

.insight-body.empty {
  color: var(--text-3);
  font-style: italic;
}

.insight-body.empty p {
  margin: 0 0 6px;
}

.insight-hint {
  font-size: 12px;
  color: var(--text-3);
  font-style: normal;
  margin-top: 8px;
  line-height: 1.6;
}

.insight-hint code {
  background: var(--surface-2);
  padding: 1px 5px;
  border-radius: 3px;
  font-size: 11px;
  color: var(--text-2);
}
</style>