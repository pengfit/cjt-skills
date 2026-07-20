<!--
  ShowcaseArchitecture.vue (2026-07-20 v3)

  OPC 运行时架构 - 主题:**系统怎么搭(技术架构 · 流程图视角)**
  - 5 box 横向流程图 + 实线/虚线关系
  - 5 张卡片讲每层架构职责
  - 不讲 AI 协作理念(那个在 ShowcaseWorkspace 讲)

  v3 与上一版区别:
  - 移除"AI 协作横切色带"(Workspace 章节讲)
  - 移除每个 box 的 AI 角标(Workspace 讲)
  - ④ 改成"飞书沟通"独立 box(架构层面是 IM 接口,不是 AI 协作层)
-->
<template>
  <section class="arch" id="arch">
    <header class="section-head">
      <h2 class="section-title">OPC 运行时架构</h2>
      <p class="section-sub">
        系统怎么搭 · 3 层应用 + AI 底座 + Docker 基础设施
      </p>
    </header>

    <!-- 上方:3 box 应用层 + AI 底座 + Docker 大虚线框 -->
    <div class="arch-flow">
      <svg class="arch-flow-svg" viewBox="0 0 1200 340" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="OPC 运行时架构图(AI 为底座能力)">
        <defs>
          <marker id="arch-arr" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" orient="auto">
            <path d="M0,0 L10,5 L0,10 z" class="arr"/>
          </marker>
        </defs>

        <!-- ⑤ Docker 部署层:大虚线框包裹所有应用层 + AI 底座 -->
        <rect x="20" y="20" width="1160" height="300" rx="12" class="box box-deploy-layer"/>
        <text x="40" y="42" class="lbl-deploy">⑤ Docker 部署层</text>
        <text x="180" y="42" class="caption">一键 release · 自包含 · 镜像 325 MB · ACR 托管</text>

        <!-- ① 数据源层 -->
        <g class="layer-source">
          <rect x="60" y="70" width="320" height="80" rx="8" class="box"/>
          <text x="80" y="96" class="lbl">① 数据源层</text>
          <text x="80" y="120" class="sub">17 城住建局 / 造价站 · HTML / PDF / xlsx / API</text>
          <text x="80" y="138" class="caption">原始数据入口, 为上面所有层供料</text>
        </g>
        <!-- ① → ② -->
        <line x1="380" y1="110" x2="418" y2="110" class="line" marker-end="url(#arch-arr)"/>

        <!-- ② 入仓 ETL -->
        <g class="layer-etl">
          <rect x="420" y="70" width="320" height="80" rx="8" class="box"/>
          <text x="440" y="96" class="lbl">② 入仓 ETL</text>
          <text x="440" y="120" class="sub">ODS · DWD · DWS · norm 四层</text>
          <text x="440" y="138" class="caption">规格归一 · 分类推断 · 跨城映射</text>
        </g>
        <!-- ② → ③ -->
        <line x1="740" y1="110" x2="778" y2="110" class="line" marker-end="url(#arch-arr)"/>

        <!-- ③ 服务层(highlight) -->
        <g class="layer-serving">
          <rect x="780" y="70" width="320" height="80" rx="8" class="box box-accent"/>
          <text x="800" y="96" class="lbl lbl-accent">③ 服务层</text>
          <text x="800" y="120" class="sub">FastAPI · Vue 3 · ECharts · ES 8.x</text>
          <text x="800" y="138" class="caption">面向用户 · 9 Tab 驾驶舱 · 公开 / 鉴权分流</text>
        </g>

        <!-- AI 协作底座虚线反镇(需求对话驱动 ETL) -->
        <path d="M 580 150 C 580 175, 580 195, 580 200" class="line-dashed-thin" fill="none"/>

        <!-- ④ AI 协作层 · 底座能力(独立大色块,跑在最底部) -->
        <rect x="60" y="200" width="1040" height="90" rx="10" class="box box-ai-base"/>
        <text x="84" y="228" class="lbl-ai-base">④ AI 协作层 · 底座能力</text>
        <text x="84" y="248" class="caption-ai-base">
          OpenClaw Agent · Dify Chatflow · DeepSeek · MiniMax · Claude · 飞书直连
        </text>
        <text x="84" y="270" class="caption-ai-base">
          跑在所有层之下,作为整个系统的基础能力 — 没有这层,系统不会跑
        </text>

        <!-- 3 个应用层 → AI 底座的小虚线箭头(表示"依赖底座") -->
        <line x1="220" y1="150" x2="220" y2="200" class="line-dashed-thin" marker-end="url(#arch-arr)"/>
        <line x1="580" y1="150" x2="580" y2="200" class="line-dashed-thin" marker-end="url(#arch-arr)"/>
        <line x1="940" y1="150" x2="940" y2="200" class="line-dashed-thin" marker-end="url(#arch-arr)"/>
        <text x="600" y="316" class="caption-bottom" text-anchor="middle">
          三个应用层都依赖 AI 底座运行
        </text>
      </svg>
    </div>

    <!-- 下方:5 张详细卡片 -->
    <div class="arch-cards">
      <article v-for="(layer, i) in layers" :key="i" class="arch-card" :class="`arch-card-${i+1}`">
        <div class="arch-card-head">
          <span class="arch-card-num">0{{ i+1 }}</span>
          <h3 class="arch-card-title">{{ layer.title }}</h3>
        </div>
        <p class="arch-card-desc">{{ layer.desc }}</p>
        <ul class="arch-card-points">
          <li v-for="p in layer.points" :key="p">{{ p }}</li>
        </ul>
        <div class="arch-card-tag">{{ layer.tag }}</div>
      </article>
    </div>
  </section>
</template>

<script setup>
const layers = [
  {
    title: '数据源层',
    desc: '17 个城市的住建局、造价站官方价格信息源,统一抽象为"原始数据"。',
    points: [
      'HTML 网页、PDF 期刊、xlsx、REST API',
      'PDF 用 pdfplumber + 自定义版式解析',
      '数据落到 ODS 层,可审计可追溯',
    ],
    tag: '数据归己',
  },
  {
    title: '入仓 ETL',
    desc: '4 层数据架构:ODS 原始、DWD 清洗、DWS 标准、norm 跨城映射。',
    points: [
      'cron 凌晨 01:00–02:25,isolated 隔离',
      '单城失败不影响其他城市',
      '规则库 + AI 双轨归一',
    ],
    tag: '可观测可审计',
  },
  {
    title: '服务层',
    desc: 'FastAPI + Vue 3 + ECharts + Elasticsearch,Docker 自包含镜像 325 MB。',
    points: [
      'FastAPI 路由按业务切分,公开/鉴权分清楚',
      'Vue SPA + 9 个驾驶舱 Tab',
      '前端 build 产物 COPY 进镜像',
    ],
    tag: '自包含部署',
  },
  {
    title: 'AI 协作层 · 底座',
    desc: 'OpenClaw Agent + Dify + 多模型 + 飞书直连,作为整个系统的底座能力。跑在 ①②③ 层之下,所有应用层都依赖它才能运行——没有这层,系统不会跑。',
    points: [
      'OpenClaw Agent:读 SKILL、跑 cron、写状态',
      'Dify Chatflow:封装 AI 调用、可观测',
      '模型分工:DeepSeek 归一、Claude 复核',
      '飞书直连:需求入口 + 告警出口',
    ],
    tag: '底座能力',
  },
  {
    title: 'Docker 部署层',
    desc: 'docker-compose 多服务编排,docker multi-stage 构建,阿里云 ACR 托管镜像。',
    points: [
      './deploy.sh release 一条龙:build → tag → push → restart',
      '镜像 325 MB 压缩后,自包含 17 城规则库',
      '失败回滚 ./deploy.sh rollback <tag>',
    ],
    tag: '一键发布可回滚',
  },
]
</script>

<style scoped>
.arch {
  padding: 80px 0 48px;
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

/* 上方流程图 */
.arch-flow {
  margin-bottom: 40px;
  padding: 16px 0;
  border-top: 1px solid var(--border-light);
  border-bottom: 1px solid var(--border-light);
}

.arch-flow-svg {
  width: 100%;
  height: auto;
  max-width: 100%;
  display: block;
}

.arch-flow-svg :deep(.box) {
  fill: var(--surface-2);
  stroke: var(--border);
  stroke-width: 1;
}

.arch-flow-svg :deep(.box-accent) {
  fill: var(--primary-dim, rgba(37, 99, 235, 0.08));
  stroke: var(--primary);
  stroke-width: 1.2;
}

.arch-flow-svg :deep(.box-feishu) {
  fill: var(--surface);
  stroke: var(--border-strong);
  stroke-width: 1;
}

.arch-flow-svg :deep(.box-deploy-layer) {
  fill: none;
  stroke: var(--border-strong);
  stroke-width: 1.5;
  stroke-dasharray: 8 4;
  opacity: 0.55;
}

.arch-flow-svg :deep(.lbl-deploy) {
  font-size: 12px;
  font-weight: 700;
  fill: var(--text-2);
  font-family: var(--font-sans);
  letter-spacing: 0.02em;
}

.arch-flow-svg :deep(.lbl) {
  font-size: 14px;
  font-weight: 700;
  fill: var(--text);
  font-family: var(--font-sans);
}

.arch-flow-svg :deep(.lbl-accent) {
  fill: var(--primary);
}

.arch-flow-svg :deep(.sub) {
  font-size: 12px;
  fill: var(--text-2);
  font-family: var(--font-mono-num);
}

.arch-flow-svg :deep(.caption) {
  font-size: 10px;
  fill: var(--text-3);
  font-family: var(--font-sans);
}

.arch-flow-svg :deep(.line) {
  stroke: var(--border-strong);
  stroke-width: 1.4;
  fill: none;
}

.arch-flow-svg :deep(.line-dashed) {
  stroke: var(--primary);
  stroke-width: 1.2;
  stroke-dasharray: 5 3;
  fill: none;
  opacity: 0.5;
}

.arch-flow-svg :deep(.arr) {
  fill: var(--border-strong);
}

/* 下方详细卡片 */
.arch-cards {
  display: grid;
  grid-template-columns: repeat(5, 1fr);
  gap: 16px;
}

.arch-card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  padding: 20px 16px;
  display: flex;
  flex-direction: column;
  gap: 10px;
  transition: all 0.2s ease;
}

.arch-card:hover {
  border-color: var(--border-strong);
  box-shadow: var(--shadow-md, 0 4px 12px rgba(0, 0, 0, 0.04));
  transform: translateY(-2px);
}

.arch-card-3 {
  border-color: var(--primary);
  background: var(--primary-dim, rgba(37, 99, 235, 0.04));
}

.arch-card-head {
  display: flex;
  align-items: center;
  gap: 8px;
  padding-bottom: 8px;
  border-bottom: 1px solid var(--border-light);
}

.arch-card-num {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-radius: 50%;
  font-size: 11px;
  font-weight: 700;
  color: var(--primary);
  font-family: var(--font-mono-num);
  flex-shrink: 0;
}

.arch-card-3 .arch-card-num {
  background: var(--primary);
  color: white;
  border-color: var(--primary);
}

.arch-card-title {
  font-size: 13px;
  font-weight: 700;
  color: var(--text);
  margin: 0;
  letter-spacing: -0.01em;
}

.arch-card-desc {
  font-size: 12px;
  line-height: 1.65;
  color: var(--text-2);
  margin: 0;
}

.arch-card-points {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
  flex: 1;
}

.arch-card-points li {
  font-size: 11px;
  line-height: 1.55;
  color: var(--text-3);
  padding-left: 10px;
  position: relative;
}

.arch-card-points li::before {
  content: '';
  position: absolute;
  left: 0;
  top: 7px;
  width: 3px;
  height: 3px;
  background: var(--border-strong);
  border-radius: 50%;
}

.arch-card-tag {
  font-size: 10px;
  font-weight: 600;
  color: var(--primary);
  padding: 3px 8px;
  background: var(--primary-dim, rgba(37, 99, 235, 0.08));
  border-radius: 3px;
  font-family: var(--font-mono-num);
  align-self: flex-start;
  margin-top: 4px;
}

.arch-card-3 .arch-card-tag {
  background: var(--primary);
  color: white;
}

@media (max-width: 1024px) {
  .arch-cards {
    grid-template-columns: repeat(2, 1fr);
  }
}

@media (max-width: 640px) {
  .arch-cards {
    grid-template-columns: 1fr;
  }
  .arch-flow-svg { display: none; }
}
</style>