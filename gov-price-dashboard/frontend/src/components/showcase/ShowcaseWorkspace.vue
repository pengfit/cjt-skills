<!--
  ShowcaseWorkspace.vue (2026-07-20 v3)

  OPC 工作站空间 - 主题:**怎么工作(AI 协作的全新工作范式)**
  - 顶部:AI 协作 · 贯穿全链路(最显眼位置,核心叙事)
  - 底部:5 列简洁数字(无描述,避免与 Architecture 卡片重复)

  分工:
  - Architecture:系统怎么搭(技术架构)
  - Workspace:怎么工作(AI 协作范式) ← 本 section
  - Gallery:跑通了什么(工作流成果)
-->
<template>
  <section class="workspace" id="workspace">
    <header class="section-head">
      <h2 class="section-title">OPC 工作站空间</h2>
      <p class="section-sub">
        一个人 + AI · 撑起整套软件工程 · 飞书说一声就开干
      </p>
    </header>

    <!-- 顶部:AI 协作 · 贯穿全链路(最显眼位置) -->
    <div class="ws-ai-flow">
      <div class="ws-ai-flow-head">
        <span class="ws-ai-icon">🤖</span>
        <h3>AI 协作 · 贯穿全链路</h3>
        <span class="ws-ai-tag">新工作模式</span>
      </div>

      <div class="ws-ai-flow-body">
        <!-- 传统 vs OPC 对比 -->
        <div class="ws-compare">
          <div class="ws-compare-old">
            <div class="ws-compare-label">传统软件工程</div>
            <div class="ws-compare-flow">
              <span>需求</span><span>→</span>
              <span>设计</span><span>→</span>
              <span>开发</span><span>→</span>
              <span>测试</span><span>→</span>
              <span>运维</span>
            </div>
            <div class="ws-compare-meta">产品 + 设计 + 开发 + 测试 + 运维 + DBA · 多人多周</div>
          </div>
          <div class="ws-compare-arrow">→</div>
          <div class="ws-compare-new">
            <div class="ws-compare-label">OPC 工作站</div>
            <div class="ws-compare-flow ws-compare-flow-new">
              <span>人</span><span>+</span>
              <span>Maxmin</span><span>+</span>
              <span>OpenClaw</span><span>+</span>
              <span>大模型</span>
            </div>
            <div class="ws-compare-meta">一人 · 一天 · AI 协作全程</div>
          </div>
        </div>

        <!-- 7 个环节 -->
        <div class="ws-stages">
          <div v-for="(s, i) in stages" :key="i" class="ws-stage">
            <div class="ws-stage-num">{{ s.num }}</div>
            <div class="ws-stage-name">{{ s.name }}</div>
            <div class="ws-stage-role">{{ s.role }}</div>
          </div>
        </div>
      </div>
    </div>

  </section>
</template>

<script setup>
const stages = [
  { num: '1', name: '需求', role: '人在飞书说 → Agent 接收' },
  { num: '2', name: '设计', role: 'Claude 画架构 → Agent 校对' },
  { num: '3', name: '开发', role: '模型生成代码 → Agent 集成' },
  { num: '4', name: '测试', role: 'AI 写用例 → Agent 跑 CI' },
  { num: '5', name: 'AI 运维', role: 'DeepSeek 攒批 · 异常 → 飞书 DM' },
  { num: '6', name: '监控', role: 'Agent 看日志 → AI 分析' },
]
</script>

<style scoped>
.workspace {
  padding: 80px 0 48px;
}

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

/* ── 顶部:AI 协作 · 贯穿全链路(最显眼) ── */
.ws-ai-flow {
  background: linear-gradient(135deg, var(--primary-dim, rgba(37, 99, 235, 0.06)) 0%, var(--surface) 100%);
  border: 1px solid var(--primary);
  border-radius: var(--radius-lg);
  padding: 28px 32px;
  margin-bottom: 32px;
}

.ws-ai-flow-head {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 20px;
  padding-bottom: 16px;
  border-bottom: 1px solid var(--border-light);
}

.ws-ai-icon {
  font-size: 24px;
}

.ws-ai-flow-head h3 {
  font-size: 20px;
  font-weight: 700;
  color: var(--text);
  margin: 0;
  letter-spacing: -0.01em;
  flex: 1;
}

.ws-ai-tag {
  font-size: 11px;
  font-weight: 600;
  color: white;
  background: var(--primary);
  padding: 4px 10px;
  border-radius: 999px;
  letter-spacing: 0.02em;
}

.ws-ai-flow-body {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

/* 传统 vs OPC 对比 */
.ws-compare {
  display: grid;
  grid-template-columns: 1fr 60px 1fr;
  gap: 12px;
  align-items: center;
}

.ws-compare-old,
.ws-compare-new {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 12px 16px;
}

.ws-compare-new {
  border-color: var(--primary);
  background: var(--primary-dim, rgba(37, 99, 235, 0.04));
}

.ws-compare-label {
  font-size: 11px;
  font-weight: 600;
  color: var(--text-3);
  letter-spacing: 0.04em;
  margin-bottom: 8px;
}

.ws-compare-new .ws-compare-label {
  color: var(--primary);
}

.ws-compare-flow {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  font-size: 12px;
  color: var(--text-2);
  font-family: var(--font-mono-num);
}

.ws-compare-flow-new {
  color: var(--primary);
  font-weight: 600;
}

.ws-compare-flow span:nth-child(even) {
  color: var(--border-strong);
  margin: 0 2px;
}

.ws-compare-meta {
  font-size: 11px;
  color: var(--text-3);
  margin-top: 8px;
}

.ws-compare-arrow {
  font-size: 28px;
  color: var(--primary);
  text-align: center;
  font-weight: 700;
}

/* 6 个环节 */
.ws-stages {
  display: grid;
  grid-template-columns: repeat(6, 1fr);
  gap: 8px;
}

.ws-stage {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 12px 10px;
  text-align: center;
}

.ws-stage-num {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 20px;
  height: 20px;
  background: var(--primary);
  color: white;
  border-radius: 50%;
  font-size: 10px;
  font-weight: 700;
  font-family: var(--font-mono-num);
  margin-bottom: 6px;
}

.ws-stage-name {
  font-size: 12px;
  font-weight: 600;
  color: var(--text);
  margin-bottom: 4px;
}

.ws-stage-role {
  font-size: 10px;
  color: var(--text-3);
  line-height: 1.4;
}

/* ── 底部数值块已删除:数字跟 Metrics / Architecture 卡片重复,Workspace 只留 AI 协作叙事 ── */

@media (max-width: 1024px) {
  .ws-stages { grid-template-columns: repeat(3, 1fr); }
  .ws-compare { grid-template-columns: 1fr; }
  .ws-compare-arrow { transform: rotate(90deg); }
}

@media (max-width: 640px) {
  .ws-stages { grid-template-columns: repeat(2, 1fr); }
}
</style>