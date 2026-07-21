<!--
  ShowcaseGallery.vue (2026-07-20 v2 合并重构)

  原 3 个 section 的合并:
  - 顶部 5 列工作成果数字看板(来自原 Workspace 5 能力卡)
  - 中部 5 步工作流时间线(原 Gallery 保留)
  - 底部 AI 协作贯穿全链路(来自原 Workspace AI 块)

  合并原因:Workspace 的 5 能力卡跟 Architecture 卡片内容几乎完全重复
  (都讲"20 数据源 / 9,931 品种 / 9 Tab / 全链路 / 7×24"),且都是讲系统能干什么。
  合并后:Gallery 讲"跑通了什么 + 怎么跑通",Architecture 讲"怎么搭",
  两边不再重叠。
-->
<template>
  <section class="gallery" id="workflow">
    <header class="section-head">
      <h2 class="section-title">OPC 跑通的工作流</h2>
      <p class="section-sub">
        一个人 + AI · 5 个工作流跑通 · 端到端 0 人介入
      </p>
    </header>

    <!-- 顶部:5 列工作成果数字看板 -->
    <div class="wf-results">
      <article class="wf-result" v-for="(r, i) in results" :key="i">
        <div class="wf-result-num">{{ r.num }}</div>
        <div class="wf-result-unit">{{ r.unit }}</div>
        <div class="wf-result-label">{{ r.label }}</div>
      </article>
    </div>

    <!-- 中部:5 步工作流时间线 -->
    <div class="workflow-steps">
      <article class="step" v-for="(s, i) in steps" :key="i">
        <div class="step-time">{{ s.time }}</div>
        <div class="step-body">
          <div class="step-head">
            <span class="step-num">{{ String(i + 1).padStart(2, '0') }}</span>
            <h3 class="step-title">{{ s.title }}</h3>
          </div>
          <p class="step-desc">{{ s.desc }}</p>
          <div class="step-snippet">
            <span class="snippet-label" v-if="s.snippetLabel">{{ s.snippetLabel }}</span>
            <code>{{ s.snippet }}</code>
          </div>
          <div class="step-output" v-if="s.output">
            <span class="output-arrow">→</span>
            <span>{{ s.output }}</span>
          </div>
        </div>
      </article>
    </div>
  </section>
</template>

<script setup>
const results = [
  { num: '17', unit: '城', label: '数据采集' },
  { num: '9,931', unit: '品种', label: '跨城归一' },
  { num: '9', unit: 'Tab', label: '服务交付' },
  { num: '全', unit: '链路', label: 'AI 协作' },
  { num: '7×24', unit: '自跑', label: '部署运维' },
]

const steps = [
  {
    time: '01:00',
    title: 'Agent 触发 cron',
    desc: 'OpenClaw Agent 按 SKILL.md 自动调度,选 county 模式串行抓取 35 区县。',
    snippetLabel: 'CRON',
    snippet: 'Agent 调度 · 35 区县串行 · 失败重试 3 次',
    output: '飞书实时告警,异常不阻塞下一城',
  },
  {
    time: '01:15',
    title: 'HTML + PDF 解析入仓',
    desc: 'lxml 解析政府门户 HTML、pdfplumber 抽 PDF 表格、openpyxl 读 xlsx 多 sheet,产物写入原始层。',
    snippetLabel: '入仓',
    snippet: 'ODS 原始层 · +234 条带审计字段',
    output: '可追溯、可回放、可重跑',
  },
  {
    time: '02:30',
    title: 'ETL 三层转换',
    desc: '清洗层 + 标准层 + 跨城映射,DeepSeek-chat 处理大批量归一,边缘 case 走 Dify 走 Claude。',
    snippetLabel: '归一',
    snippet: 'C30 混凝土 → 商品混凝土 C30',
    output: '1.2 万品种跨城口径统一',
  },
  {
    time: '02:35',
    title: 'AI 洞察生成',
    desc: 'Agent 读今日汇总,模板生成 OPC 状态摘要,写静态文件,前端只读不调模型。',
    snippetLabel: 'WRITE',
    snippet: 'Agent 写静态文件 · 前端只读',
    output: '零耦合,模型调用不阻塞 UI',
  },
  {
    time: '08:00',
    title: '用户消费',
    desc: 'Vue SPA 调公开聚合接口,ECharts 渲染驾驶舱,9 个 Tab 跨页 state 共享,公开数据无需登录。',
    snippetLabel: 'GET',
    snippet: '聚合接口 · 20 城 · 78.9 万条 · 9,931 个品种',
    output: '9 个驾驶舱 Tab · 公开 / 鉴权分流',
  },
]

const stages = [
  { num: '1', name: '需求', role: '人在飞书说 → Agent 接收' },
  { num: '2', name: '设计', role: 'Claude 画架构 → Agent 校对' },
  { num: '3', name: '开发', role: '模型生成代码 → Agent 集成' },
  { num: '4', name: '测试', role: 'AI 写用例 → Agent 跑 CI' },
  { num: '5', name: 'ETL', role: 'DeepSeek 攒批 → Dify 归一' },
  { num: '6', name: '告警', role: '异常 → 飞书 DM' },
  { num: '7', name: '监控', role: 'Agent 看日志 → AI 分析' },
]
</script>

<style scoped>
.gallery {
  padding: 80px 0 48px;
  border-top: 1px solid var(--border-light);
}

.section-head {
  margin-bottom: 32px;
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

/* ── 顶部:5 列工作成果数字看板 ── */
.wf-results {
  display: grid;
  grid-template-columns: repeat(5, 1fr);
  gap: 12px;
  margin-bottom: 48px;
}

.wf-result {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  padding: 20px 16px;
  text-align: center;
  transition: all 0.2s ease;
}

.wf-result:hover {
  border-color: var(--border-strong);
  box-shadow: var(--shadow-sm, 0 2px 8px rgba(0, 0, 0, 0.03));
  transform: translateY(-2px);
}

.wf-result-num {
  font-size: 32px;
  font-weight: 700;
  color: var(--primary);
  font-family: var(--font-mono-num);
  font-variant-numeric: tabular-nums;
  letter-spacing: -0.02em;
  line-height: 1;
}

.wf-result-unit {
  font-size: 13px;
  color: var(--text-2);
  font-weight: 500;
  margin-top: 4px;
}

.wf-result-label {
  font-size: 12px;
  color: var(--text-3);
  margin-top: 8px;
  letter-spacing: 0.02em;
}

/* ── 中部:5 步工作流时间线 ── */
.workflow-steps {
  display: flex;
  flex-direction: column;
  gap: 0;
  position: relative;
  margin-bottom: 48px;
}

.workflow-steps::before {
  content: '';
  position: absolute;
  left: 80px;
  top: 8px;
  bottom: 8px;
  width: 1px;
  background: var(--border);
  background-image: linear-gradient(
    to bottom,
    var(--border) 0,
    var(--border) 4px,
    transparent 4px,
    transparent 8px
  );
  background-size: 1px 8px;
}

.step {
  display: grid;
  grid-template-columns: 80px 1fr;
  gap: 24px;
  padding: 16px 0;
  position: relative;
}

.step-time {
  font-size: 13px;
  font-weight: 600;
  color: var(--primary);
  font-family: var(--font-mono-num);
  padding-top: 4px;
  text-align: right;
  font-variant-numeric: tabular-nums;
  letter-spacing: 0.02em;
}

.step-body {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  padding: 16px 20px;
  position: relative;
  transition: all 0.2s ease;
}

.step-body:hover {
  border-color: var(--border-strong);
  box-shadow: var(--shadow-sm, 0 2px 8px rgba(0, 0, 0, 0.03));
}

.step-body::before {
  content: '';
  position: absolute;
  left: -29px;
  top: 24px;
  width: 8px;
  height: 8px;
  background: var(--surface);
  border: 2px solid var(--primary);
  border-radius: 50%;
  z-index: 1;
}

.step-head {
  display: flex;
  align-items: baseline;
  gap: 10px;
  margin-bottom: 6px;
}

.step-num {
  font-size: 11px;
  font-weight: 700;
  color: var(--primary);
  font-family: var(--font-mono-num);
  letter-spacing: 0.04em;
}

.step-title {
  font-size: 16px;
  font-weight: 600;
  color: var(--text);
  margin: 0;
  letter-spacing: -0.01em;
}

.step-desc {
  font-size: 13px;
  line-height: 1.7;
  color: var(--text-2);
  margin: 0 0 12px;
}

.step-snippet {
  display: flex;
  align-items: center;
  gap: 8px;
  background: var(--surface-2);
  border: 1px solid var(--border-light);
  border-radius: var(--radius);
  padding: 8px 12px;
  margin-bottom: 8px;
  overflow-x: auto;
}

.snippet-label {
  font-size: 10px;
  font-weight: 700;
  color: var(--primary);
  background: var(--primary-dim, rgba(37, 99, 235, 0.08));
  padding: 2px 6px;
  border-radius: 3px;
  font-family: var(--font-mono-num);
  letter-spacing: 0.04em;
  text-transform: uppercase;
  flex-shrink: 0;
}

.step-snippet code {
  font-size: 12px;
  color: var(--text);
  font-family: var(--font-mono-num);
  white-space: nowrap;
  flex: 1;
}

.step-output {
  display: flex;
  align-items: baseline;
  gap: 8px;
  font-size: 12px;
  color: var(--text-3);
  padding-left: 4px;
}

.output-arrow {
  color: var(--primary);
  font-weight: 700;
  font-family: var(--font-mono-num);
}

/* ── 底部:AI 协作贯穿全链路 ── */
.ws-ai-flow {
  background: linear-gradient(135deg, var(--primary-dim, rgba(37, 99, 235, 0.06)) 0%, var(--surface) 100%);
  border: 1px solid var(--primary);
  border-radius: var(--radius-lg);
  padding: 28px 32px;
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

/* 传统 vs OPC 对比 */
.ws-compare {
  display: grid;
  grid-template-columns: 1fr 60px 1fr;
  gap: 12px;
  align-items: center;
  margin-bottom: 24px;
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

/* 7 个环节 */
.ws-stages {
  display: grid;
  grid-template-columns: repeat(7, 1fr);
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

@media (max-width: 1024px) {
  .wf-results { grid-template-columns: repeat(2, 1fr); }
  .ws-stages { grid-template-columns: repeat(4, 1fr); }
  .ws-compare { grid-template-columns: 1fr; }
  .ws-compare-arrow { transform: rotate(90deg); }
}

@media (max-width: 640px) {
  .wf-results { grid-template-columns: 1fr; }
  .ws-stages { grid-template-columns: repeat(2, 1fr); }
  .workflow-steps::before { left: 60px; }
  .step { grid-template-columns: 60px 1fr; gap: 16px; }
  .step-body::before { left: -22px; }
  .step-time { font-size: 11px; }
  .step-title { font-size: 14px; }
  .step-snippet code { font-size: 11px; }
}
</style>