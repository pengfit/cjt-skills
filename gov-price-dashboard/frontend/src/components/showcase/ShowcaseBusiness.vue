<!--
  ShowcaseBusiness.vue (2026-07-20 v3 - 删成本对比 + 卡片 UI 调整)

  调整:
  - 删 .biz-cost 块(template + data + CSS 全部移除)
  - 3 张卡 UI 调整:加 "传统 vs OPC" 对比行(metric 仍是主视觉大数字)

  3 主题: 快速产出 MVP / 高效迭代 / 流程闭环
-->
<template>
  <section class="business" id="business">
    <!-- 独立 section 标题, 跟 OPC · 怎么运作 / 案例 / 架构 三个 section 视觉一致 -->
    <header class="section-head">
      <h2 class="section-title">OPC · AI 增益</h2>
      <p class="section-sub">快速产出 MVP · 高效迭代 · 流程闭环</p>
    </header>

    <!-- 大卡样式与 ShowcaseWorkspace 的 .ws-ai-flow 同构: primary 边框 + 渐变背景 + 头部标题 (修改 10) -->
    <div class="biz-card">
      <div class="biz-card-head">
        <span class="biz-card-icon">⚡</span>
        <span class="biz-card-tag">3 大场景</span>
      </div>

      <!-- 3 个 AI 增益场景卡(UI 调整:加传统 vs OPC 对比) -->
      <div class="biz-gains">
        <article v-for="(g, i) in gains" :key="i" class="biz-gain">
          <div class="biz-gain-icon">{{ g.icon }}</div>
          <h3 class="biz-gain-scenario">{{ g.scenario }}</h3>
          <div class="biz-gain-metric">{{ g.metric }}</div>
          <div class="biz-gain-compare">
            <span class="biz-gain-old">{{ g.traditional }}</span>
            <span class="biz-gain-arrow">→</span>
            <span class="biz-gain-new">{{ g.opc }}</span>
          </div>
          <div class="biz-gain-tag">{{ g.tag }}</div>
        </article>
      </div>
    </div>
  </section>
</template>

<script setup>
const gains = [
  {
    icon: '🚀',
    scenario: '快速产出 MVP',
    metric: '1天',
    traditional: '传统 3 月',
    opc: 'OPC 1 天',
    tag: '需求 → 设计 → 开发 → 部署 · Agent 串起',
  },
  {
    icon: '🔄',
    scenario: '高效迭代',
    metric: '10+倍',
    traditional: '1 周 1 次',
    opc: '1 天 10+次',
    tag: '飞书说一声 · AI 立即响应 · 秒级反馈',
  },
  {
    icon: '🔁',
    scenario: '流程闭环',
    metric: '24h',
    traditional: '传统 2 周+',
    opc: 'OPC 24 小时',
    tag: '需求 → 上线 → 反馈 → 迭代 · 任意 MVP 完整闭环',
  },
]
</script>

<style scoped>
.business {
  padding: 80px 0 48px;
  border-top: 1px solid var(--border-light);
}

/* 独立 section 标题, 与其他 section 一致 (修复道友反馈: 缺独立标题) */
.section-head {
  margin-bottom: 24px;
}

.section-title {
  font-size: 28px;
  font-weight: 700;
  color: var(--text);
  letter-spacing: -0.02em;
  margin: 0 0 8px;
}

.section-sub {
  font-size: 14px;
  color: var(--text-2);
  margin: 0;
}

/* 大卡样式 (与 .ws-ai-flow 同构, 满足修改 10) */
.biz-card {
  background: linear-gradient(135deg, var(--primary-dim, rgba(37, 99, 235, 0.06)) 0%, var(--surface) 100%);
  border: 1px solid var(--primary);
  border-radius: var(--radius-lg);
  padding: 28px 32px;
}

.biz-card-head {
  display: flex;
  align-items: center;
  gap: 12px;
  padding-bottom: 16px;
  margin-bottom: 16px;
  border-bottom: 1px solid var(--border-light);
}

.biz-card-icon {
  font-size: 20px;
}

.biz-card-tag {
  font-size: 11px;
  font-weight: 600;
  color: var(--primary);
  background: var(--primary-dim, rgba(37, 99, 235, 0.08));
  padding: 4px 10px;
  border-radius: 999px;
  letter-spacing: 0.02em;
  margin-left: auto;
}

/* ── 3 个 AI 增益场景卡(UI 调整:加 vs 传统对比) ── */
.biz-gains {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 16px;
}

.biz-gain {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  padding: 24px 22px;
  display: flex;
  flex-direction: column;
  align-items: center;
  text-align: center;
  gap: 8px;
  transition: all 0.2s ease;
  position: relative;
  overflow: hidden;
}

.biz-gain::before {
  content: '';
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  height: 3px;
  background: linear-gradient(90deg, var(--primary) 0%, rgba(37, 99, 235, 0.3) 100%);
}

.biz-gain:hover {
  border-color: var(--primary);
  box-shadow: var(--shadow-md, 0 4px 12px rgba(0, 0, 0, 0.06));
  transform: translateY(-2px);
}

.biz-gain-icon {
  font-size: 32px;
  line-height: 1;
  margin-bottom: 2px;
}

.biz-gain-scenario {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-2);
  margin: 0;
  letter-spacing: 0.02em;
}

.biz-gain-metric {
  font-size: 48px;
  font-weight: 800;
  color: var(--primary);
  font-family: var(--font-mono-num);
  font-variant-numeric: tabular-nums;
  letter-spacing: -0.03em;
  line-height: 1;
  margin: 4px 0;
  white-space: nowrap;
}

.biz-gain-compare {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  font-size: 12px;
  font-family: var(--font-mono-num);
  padding: 4px 0;
  flex-wrap: wrap;
}

.biz-gain-old {
  color: var(--text-3);
  text-decoration: line-through;
  text-decoration-color: var(--text-3);
  text-decoration-thickness: 1px;
}

.biz-gain-arrow {
  color: var(--primary);
  font-weight: 700;
  font-size: 14px;
}

.biz-gain-new {
  color: var(--primary);
  font-weight: 600;
  background: var(--primary-dim, rgba(37, 99, 235, 0.08));
  padding: 2px 8px;
  border-radius: 3px;
}

.biz-gain-tag {
  margin-top: 4px;
  font-size: 10px;
  font-weight: 600;
  color: var(--text-2);
  background: var(--surface-2);
  padding: 3px 10px;
  border-radius: 999px;
  letter-spacing: 0.02em;
}

@media (max-width: 1024px) {
  .biz-gains { grid-template-columns: repeat(3, 1fr); }
}

@media (max-width: 640px) {
  .biz-gains { grid-template-columns: 1fr; }
  .biz-gain-metric { font-size: 40px; }
}
</style>