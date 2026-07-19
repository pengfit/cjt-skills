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
      <h2 class="section-title">核心能力</h2>
      <p class="section-sub">从「数据全」到「口径齐」再到「决策有据」,覆盖工程造价数据的全生命周期</p>
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
    title: '数据采集',
    tagline: '让数据「全」',
    layers: [{ name: 'ODS · 原始价' }],
    desc: '全国 20 个城市住建局、造价站官方价格信息,凌晨自动同步,数据可追溯到原始来源。',
    points: [
      'Excel (.xlsx) · PDF · HTML 网页解析',
      '凌晨 01:00–02:25 自动同步',
      '失败重试 + 飞书汇总告警',
    ],
  },
  {
    title: '跨城统一',
    tagline: '让数据「可比」',
    layers: [
      { name: 'DWD · 清洗' },
      { name: 'DWS · 标准', accent: true },
      { name: 'norm · 跨城' },
    ],
    desc: '消除「同物异名」(如 C30 混凝土 = 商品混凝土 C30),1.2 万品种跨城口径归一,可直接对比。',
    points: [
      '12,286 个跨城统一官方品种',
      'GB 章节 4 层分类(8 / 42 / 145)',
      'AI 攒批 + 正则规则库双轨归一',
    ],
  },
  {
    title: '价格洞察',
    tagline: '让数据「可用」',
    layers: [{ name: '驾驶舱 · 决策视图' }],
    desc: '9 个驾驶舱 Tab,地图看分布、走势看趋势、规格审计看来源,辅助造价估算、采购决策、预算编制。',
    points: [
      '中国地图热力看价格分布',
      '时间走势辅助采购时机',
      '规格解析审计可追溯到源头',
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
