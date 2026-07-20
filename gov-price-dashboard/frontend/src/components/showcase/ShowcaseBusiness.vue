<!--
  ShowcaseBusiness.vue (2026-07-20 v2 - 简化:AI 增益主题)

  原 6 张能力卡太全面(像产品手册),"目前阶段不太合适"。
  改成"AI 增益"主题:
  - 3 个具体场景(数据中台/内容运营/客户支持)的 传统 vs OPC 对比
  - 大数字表达(30x / 15x / 7×24)
  - 保留底部成本对比

  位置:Workspace (范式) 和 Case (具体案例) 之间
  位置理由:讲"AI 增益"(价值) → 讲"具体案例"(实例)
-->
<template>
  <section class="business" id="business">
    <header class="section-head">
      <h2 class="section-title">OPC 一人公司 · AI 增益</h2>
      <p class="section-sub">
        1 人 + AI · 快速产出 MVP · 高效迭代 · 流程闭环
      </p>
    </header>

    <!-- 3 个 AI 增益场景(大数字 + 简短场景) -->
    <div class="biz-gains">
      <article v-for="(g, i) in gains" :key="i" class="biz-gain">
        <div class="biz-gain-icon">{{ g.icon }}</div>
        <h3 class="biz-gain-scenario">{{ g.scenario }}</h3>
        <div class="biz-gain-metric">
          <span class="biz-gain-num">{{ g.metric }}</span>
          <span class="biz-gain-x">{{ g.unit }}</span>
        </div>
        <p class="biz-gain-desc">{{ g.desc }}</p>
        <div class="biz-gain-tag">{{ g.tag }}</div>
      </article>
    </div>

    <!-- 成本对比(保留:这是 AI 增益的最强数字证明) -->
    <div class="biz-cost">
      <h3 class="biz-cost-head">成本对比</h3>
      <div class="biz-cost-compare">
        <div class="biz-cost-old">
          <div class="biz-cost-label">传统公司</div>
          <div class="biz-cost-num">
            6 人 × 30 万 = <span class="biz-cost-big">180 万/年</span>
          </div>
          <div class="biz-cost-detail">产品 + 技术 + 销售 + 运营 + 客户 + 财务</div>
        </div>
        <div class="biz-cost-arrow">→</div>
        <div class="biz-cost-new">
          <div class="biz-cost-label">OPC 一人公司</div>
          <div class="biz-cost-num">
            1 人 + <span class="biz-cost-big">4 万/年</span>
          </div>
          <div class="biz-cost-detail">Mac mini + 服务器 + AI 订阅</div>
        </div>
      </div>
      <div class="biz-cost-saving">
        节省 ≈ <span class="biz-cost-save-num">97.7%</span> · 1 人 ≈ 1 家公司
      </div>
    </div>
  </section>
</template>

<script setup>
const gains = [
  {
    icon: '🚀',
    scenario: '快速产出 MVP',
    metric: '1',
    unit: '天',
    desc: '从想法到可验证原型  ·  传统 3 人月  →  1 人 + AI 1 天',
    tag: '需求 → 设计 → 开发 → 部署 · Agent 串起',
  },
  {
    icon: '🔄',
    scenario: '高效迭代',
    metric: '10',
    unit: '×',
    desc: '迭代频率提升 10 倍  ·  传统 1 周 1 次  →  1 天 10 次微调',
    tag: '飞书说一声 · AI 立即响应 · 秒级反馈',
  },
  {
    icon: '🔁',
    scenario: '流程闭环',
    metric: '7×24',
    unit: '',
    desc: '全程 1 人跑通  ·  传统 6 部门协调交接  →  采集→ETL→服务→告警·0 介入',
    tag: 'cron 自跑 + 飞书告警 · 0 人工值班',
  },
]
</script>

<style scoped>
.business {
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

/* ── 3 个 AI 增益场景(大数字版) ── */
.biz-gains {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 16px;
  margin-bottom: 32px;
}

.biz-gain {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  padding: 28px 24px;
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
  margin-bottom: 4px;
}

.biz-gain-scenario {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-2);
  margin: 0;
  letter-spacing: 0.02em;
}

.biz-gain-metric {
  display: flex;
  align-items: baseline;
  gap: 2px;
  margin: 4px 0;
  flex-wrap: wrap;
  justify-content: center;
}

.biz-gain-num {
  font-size: 56px;
  font-weight: 800;
  color: var(--primary);
  font-family: var(--font-mono-num);
  font-variant-numeric: tabular-nums;
  letter-spacing: -0.03em;
  line-height: 1;
}

.biz-gain-x {
  font-size: 28px;
  font-weight: 700;
  color: var(--primary);
  font-family: var(--font-mono-num);
  margin-left: 2px;
}

.biz-gain-num {
  /* 7×24 之类的复合数字可以更长 */
  white-space: nowrap;
}

.biz-gain-desc {
  font-size: 12px;
  line-height: 1.6;
  color: var(--text-2);
  margin: 0;
  max-width: 280px;
}

.biz-gain-tag {
  margin-top: 8px;
  font-size: 10px;
  font-weight: 600;
  color: var(--primary);
  background: var(--primary-dim, rgba(37, 99, 235, 0.08));
  padding: 3px 10px;
  border-radius: 999px;
  letter-spacing: 0.04em;
}

/* ── 成本对比(保留) ── */
.biz-cost {
  background: linear-gradient(135deg, var(--primary-dim, rgba(37, 99, 235, 0.06)) 0%, var(--surface) 100%);
  border: 1px solid var(--primary);
  border-radius: var(--radius-lg);
  padding: 24px 28px;
}

.biz-cost-head {
  font-size: 18px;
  font-weight: 700;
  color: var(--text);
  margin: 0 0 16px;
  letter-spacing: -0.01em;
}

.biz-cost-compare {
  display: grid;
  grid-template-columns: 1fr 60px 1fr;
  gap: 12px;
  align-items: center;
  margin-bottom: 12px;
}

.biz-cost-old,
.biz-cost-new {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 14px 18px;
}

.biz-cost-new {
  border-color: var(--primary);
  background: var(--primary-dim, rgba(37, 99, 235, 0.04));
}

.biz-cost-label {
  font-size: 11px;
  font-weight: 600;
  color: var(--text-3);
  letter-spacing: 0.04em;
  margin-bottom: 6px;
}

.biz-cost-new .biz-cost-label {
  color: var(--primary);
}

.biz-cost-num {
  font-size: 16px;
  font-weight: 700;
  color: var(--text);
  font-family: var(--font-mono-num);
  line-height: 1.3;
  margin-bottom: 4px;
}

.biz-cost-new .biz-cost-num {
  color: var(--primary);
}

.biz-cost-big {
  font-size: 20px;
  font-weight: 800;
}

.biz-cost-detail {
  font-size: 11px;
  color: var(--text-3);
  line-height: 1.4;
}

.biz-cost-arrow {
  font-size: 24px;
  color: var(--primary);
  text-align: center;
  font-weight: 700;
}

.biz-cost-saving {
  text-align: center;
  font-size: 13px;
  color: var(--text-2);
  padding-top: 12px;
  border-top: 1px solid var(--border-light);
}

.biz-cost-save-num {
  font-size: 20px;
  font-weight: 800;
  color: var(--primary);
  font-family: var(--font-mono-num);
  margin: 0 4px;
}

@media (max-width: 1024px) {
  .biz-gains { grid-template-columns: repeat(3, 1fr); }
  .biz-cost-compare { grid-template-columns: 1fr; }
  .biz-cost-arrow { transform: rotate(90deg); }
}

@media (max-width: 640px) {
  .biz-gains { grid-template-columns: 1fr; }
  .biz-gain-num { font-size: 40px; }
  .biz-gain-x { font-size: 22px; }
}
</style>