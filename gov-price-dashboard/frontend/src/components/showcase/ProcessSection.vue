<!--
  ProcessSection.vue (2026-07-21 /home 新增)
  合作流程 — 4 步时间轴
-->
<script setup>
import { useInView } from '../../composables/useInView'
const { target, inView } = useInView()

const steps = [
  { n: '01', t: '需求诊断', d: '30 分钟视频通话 / 文字异步', out: '1 页需求确认单' },
  { n: '02', t: '方案报价', d: '7 个工作日内', out: '范围 / 工时 / 费用 / 时间线 四要素' },
  { n: '03', t: '开发交付', d: '周报 + 中期 demo', out: '可演示 Demo + 部署文档' },
  { n: '04', t: '上线运维', d: '按套餐灵活调整', out: '生产部署 + 监控 + 30 天质保' }
]
</script>

<template>
  <section ref="target" id="home-process" class="process" :class="{ 'in-view': inView }">
    <div class="process-inner">
      <div class="process-head">
        <h2 class="process-title">怎么合作</h2>
        <p class="process-sub">四步，节奏透明</p>
      </div>
      <div class="process-grid">
        <div v-for="s in steps" :key="s.n" class="process-card">
          <div class="process-num">{{ s.n }}</div>
          <h3 class="process-name">{{ s.t }}</h3>
          <p class="process-desc">{{ s.d }}</p>
          <div class="process-out">
            <span class="process-out-label">交付物</span>
            <p class="process-out-text">{{ s.out }}</p>
          </div>
        </div>
      </div>
    </div>
  </section>
</template>

<style scoped>
.process { padding: 80px 0; background: var(--bg); }
.process-inner { max-width: 1200px; margin: 0 auto; padding: 0 32px; }
.process-head { max-width: 640px; margin-bottom: 48px; }
.process-title {
  font-size: 30px;
  font-weight: 700;
  color: var(--text);
  margin: 0;
  letter-spacing: -0.01em;
}
.process-sub { font-size: 16px; color: var(--text-2); margin: 12px 0 0; }
.process-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 20px;
}
.process-card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  padding: 24px;
  transition: transform 0.2s cubic-bezier(0.4, 0, 0.2, 1), box-shadow 0.2s cubic-bezier(0.4, 0, 0.2, 1), border-color 0.2s cubic-bezier(0.4, 0, 0.2, 1), opacity 0.55s ease-out;
  opacity: 0;
  transform: translateY(12px);
}
.process-card:hover {
  transform: translateY(-2px);
  box-shadow: var(--shadow-md);
  border-color: rgba(var(--primary-rgb), 0.3);
}
.process-num {
  font-family: var(--font-mono-num);
  font-size: 13px;
  font-weight: 600;
  color: var(--primary);
  letter-spacing: 0.05em;
}
.process-name {
  font-size: 18px;
  font-weight: 600;
  color: var(--text);
  margin: 14px 0 12px;
}
.process-desc { font-size: 14px; color: var(--text-2); line-height: 1.6; margin: 0; }
.process-out {
  margin-top: 16px;
  padding-top: 16px;
  border-top: 1px solid var(--border-light);
}
.process-out-label {
  font-size: 11px;
  color: var(--text-3);
  text-transform: uppercase;
  letter-spacing: 0.05em;
  font-weight: 500;
}
.process-out-text {
  font-size: 13px;
  color: var(--text);
  margin: 6px 0 0;
  font-weight: 500;
  line-height: 1.5;
}

/* enter animation */
.process-head > * { opacity: 0; transform: translateY(8px); transition: opacity 0.55s ease-out, transform 0.55s ease-out; }
.process.in-view .process-head > * { opacity: 1; transform: translateY(0); }
.process.in-view .process-card { opacity: 1; transform: translateY(0); }
.process.in-view .process-card:nth-child(1) { transition-delay: 0s; }
.process.in-view .process-card:nth-child(2) { transition-delay: 0.08s; }
.process.in-view .process-card:nth-child(3) { transition-delay: 0.16s; }
.process.in-view .process-card:nth-child(4) { transition-delay: 0.24s; }

@media (max-width: 960px) {
  .process-grid { grid-template-columns: repeat(2, 1fr); }
}
@media (max-width: 560px) {
  .process { padding: 56px 0; }
  .process-inner { padding: 0 20px; }
  .process-grid { grid-template-columns: 1fr; }
  .process-title { font-size: 26px; }
}
</style>
