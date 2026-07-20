<!--
  ShowcaseCapabilities.vue (2026-07-19 业务视角重设计)

  从「技术架构描述」改成「业务价值描述」:

  旧(技术视角):
    ① 自动采集 → ODS
    ② 智能归一 → DWD/DWS/norm
    ③ 可视化分析 → 消费 DWS

  新(业务视角):
    ① 数据采集 — 让数据「全」(覆盖广)
    ② 跨城统一 — 让数据「可比」(口径齐)
    ③ 价格洞察 — 让数据「可用」(能决策)

  每个节点保留数据层 chip(ODS/DWS 等),但语言全面业务化。
-->
<template>
  <section class="cap" id="capabilities">
    <header class="section-head">
      <h2 class="section-title">OPC 三层架构</h2>
      <p class="section-sub">Agent 自动调度 → 多模型协作 → 容器编排,三件套一个都不能少</p>
    </header>
    <div class="timeline">
      <div class="tl-line">
        <span class="tl-arrow tl-arrow-1">→</span>
        <span class="tl-arrow tl-arrow-2">→</span>
      </div>
      <article class="tl-node" v-for="(c, i) in items" :key="c.title">
        <div class="tl-num">0{{ i + 1 }}</div>
        <h3 class="tl-title">{{ c.title }}</h3>
        <div class="tl-tagline">{{ c.tagline }}</div>
        <div class="tl-layers">
          <span v-for="(l, k) in c.layers" :key="k" class="tl-layer" :class="{ accent: l.accent }">
            {{ l.name }}
          </span>
        </div>
        <p class="tl-desc">{{ c.desc }}</p>
        <ul class="tl-points">
          <li v-for="p in c.points" :key="p">{{ p }}</li>
        </ul>
      </article>
    </div>
  </section>
</template>

<script setup>
const items = [
  {
    title: 'Agent 调度层',
    tagline: '让系统「自己跑」',
    layers: [
      { name: 'OpenClaw Agent' },
      { name: 'cron · SKILL', accent: true },
    ],
    desc: 'OpenClaw Agent 读 SKILL.md、自己调度 cron、自己写状态文件、自己汇总告警。凌晨 01:00–02:25 你可以睡觉,系统在跑。',
    points: [
      '18 个城市检测 cron,isolated 隔离',
      '02:30 汇总推送飞书 DM',
      '状态文件写 /tmp,前端只读,零耦合',
    ],
  },
  {
    title: '模型协作层',
    tagline: '让系统「会思考」',
    layers: [
      { name: 'DeepSeek · 归一' },
      { name: 'MiniMax · 分类', accent: true },
      { name: 'Claude · 复核' },
    ],
    desc: '不锁定单一模型,按任务选。DeepSeek-chat 处理大批量归一、MiniMax-M3 处理分类推断、Claude 复核边缘 case,走 Dify workflow 可观测。',
    points: [
      'Dify chatflow 封装 AI 调用',
      'AI 攒批 + 正则规则库双轨',
      '同类任务并发拉满,差异化走不同模型',
    ],
  },
  {
    title: '容器编排层',
    tagline: '让系统「可复制」',
    layers: [{ name: 'Docker · multi-stage' }],
    desc: '前端 Node 20 构建 + Python 3.11 运行时,镜像 325 MB 自包含,一条 ./deploy.sh release 完成 build → tag → push → restart。',
    points: [
      'docker-compose 一键起 ES + Dify + Dashboard',
      '阿里云 ACR 托管,一连接发多机器',
      '失败 rollback 到上一个 tag',
    ],
  },
]
</script>

<style scoped>
.cap {
  padding: 64px 0 48px;
}

.section-head {
  margin-bottom: 40px;
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

.timeline {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  position: relative;
  gap: 0;
}

/* 连接线:横跨三栏,从第一个节点中心到最后一个节点中心 */
.tl-line {
  position: absolute;
  top: 18px;
  left: calc(16.67% + 18px);
  right: calc(16.67% + 18px);
  height: 1px;
  background: var(--border);
  z-index: 0;
}

.tl-arrow {
  position: absolute;
  top: -7px;
  font-size: 14px;
  color: var(--border-strong);
  font-family: var(--font-mono-num);
  line-height: 1;
}

.tl-arrow-1 { left: calc(50% - 26px); }
.tl-arrow-2 { left: calc(50% + 26px); }

.tl-node {
  position: relative;
  padding: 0 24px;
  z-index: 1;
}

.tl-num {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 36px;
  height: 36px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 50%;
  font-size: 13px;
  font-weight: 600;
  color: var(--primary);
  font-family: var(--font-mono-num);
  margin-bottom: 16px;
  font-variant-numeric: tabular-nums;
}

.tl-title {
  font-size: 18px;
  font-weight: 600;
  color: var(--text);
  margin: 0 0 4px;
  letter-spacing: -0.01em;
}

/* 业务视角一句话,例如 "让数据「全」" */
.tl-tagline {
  font-size: 12px;
  color: var(--text-3);
  margin-bottom: 12px;
  font-weight: 500;
}

/* 数据层标识 */
.tl-layers {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-bottom: 14px;
}

.tl-layer {
  display: inline-flex;
  align-items: center;
  font-family: var(--font-mono-num);
  font-size: 11px;
  font-weight: 500;
  padding: 3px 8px;
  border-radius: 4px;
  background: var(--surface-2);
  color: var(--text-2);
  border: 1px solid var(--border-light);
  letter-spacing: 0.04em;
  line-height: 1;
}

.tl-layer.accent {
  background: var(--primary-dim);
  color: var(--primary);
  border-color: transparent;
  font-weight: 600;
}

.tl-desc {
  font-size: 14px;
  line-height: 1.7;
  color: var(--text-2);
  margin: 0 0 16px;
}

.tl-points {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.tl-points li {
  font-size: 12px;
  color: var(--text-3);
  padding-left: 12px;
  position: relative;
  line-height: 1.6;
}

.tl-points li::before {
  content: '';
  position: absolute;
  left: 0;
  top: 9px;
  width: 4px;
  height: 4px;
  background: var(--border-strong);
  border-radius: 50%;
}

@media (max-width: 768px) {
  .timeline {
    grid-template-columns: 1fr;
    gap: 32px;
  }
  .tl-line { display: none; }
  .tl-num { margin-bottom: 12px; }
}
</style>
