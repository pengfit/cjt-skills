<!--
  HomeView.vue (2026-07-22 完整替换)
  /home 公开 landing — 直接采用 pengfit-redesign.html 的内容
  · 深色赛博朋克风 + 渐变标题 + 霓虹青/珊瑚红双色系
  · 6 个 section: Hero / Workflow / Case / Pricing / FAQ / Contact
  · 数字滚动动画 + FAQ 折叠 + 平滑滚动

  旧 9 个子组件不再引用(ShowcaseNav/Hero/Manifesto/Workspace/Pricing/Case/Faq/Contact/Footer)
-->
<template>
  <div class="showcase home-dark">
    <!-- 阅读进度条 -->
    <div class="read-progress" :style="{ width: readProgress + '%' }"></div>

    <!-- 首屏 Hero -->
    <section class="hero">
      <div class="hero-content">
        <h1 class="fade-in">
          <span class="hero-title-main">龙虾</span>
          <span class="hero-title-sub">饲养员</span>
        </h1>
        <p class="subtitle fade-in">你提需求，它长出新能力。</p>
        <p class="tagline fade-in">不是外包，是共同养育。</p>
        <a href="#workflow" class="cta-button fade-in" @click.prevent="scrollTo('workflow')">看看怎么养 →</a>
        <div class="hero-footer fade-in">
          OpenClaw · 多模型协作 · Dify Workflow · Docker
        </div>

        <!-- 2026-07-22 信任标签排 — 填补下半屏空白 -->
        <div class="hero-tags fade-in">
          <a href="https://github.com/pengfit/cjt-skills" target="_blank" rel="noopener" class="hero-tag-chip hero-tag-cta">
            <svg class="github-icon" viewBox="0 0 16 16" width="14" height="14" fill="currentColor" aria-hidden="true">
              <path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0 0 16 8c0-4.42-3.58-8-8-8z"/>
            </svg>
            查看源码 ↗
          </a>
          <a href="#contact" class="hero-tag-chip hero-tag-cta" @click.prevent="scrollTo('contact')">
            联系咨询 →
          </a>
        </div>
      </div>
    </section>

    <!-- 工作模式 -->
    <section class="workflow" id="workflow">
      <div class="section-marker">
        <span class="section-num">01</span>
        <span class="section-divider"></span>
        <span class="section-tagline">WORKFLOW</span>
      </div>
      <div class="container">
        <h2>怎么"养"</h2>
        <p class="section-subtitle">6个AI部门，1台电脑，全程飞书协作。</p>

        <div class="workflow-diagram">
          <div class="workflow-steps">
            <div class="workflow-step">
              <h4>👤 你（飞书说一声）</h4>
              <p>提出需求，下达指令</p>
            </div>
            <div class="workflow-arrow">↓</div>
            <div class="workflow-step highlight">
              <h4>🤖 AI团队协作</h4>
              <p>需求分析 → 架构设计 → 开发 → 测试 → 运维 → 监控</p>
            </div>
            <div class="workflow-arrow">↓</div>
            <div class="workflow-step">
              <h4>📦 交付物（会生长的系统）</h4>
              <p>持续迭代，越用越强</p>
            </div>
          </div>
        </div>

        <div class="workflow-bottom">
          <p>传统公司需要6人团队多年磨合，</p>
          <p>你只需要1台电脑 + OpenClaw + 行业know-how。</p>
          <p><strong style="color: #00d9ff;">它提供每天在长的算力，你提供日常照料。</strong></p>
        </div>
      </div>
    </section>

    <!-- 案例 -->
    <section class="case-study" id="case">
      <div class="section-marker">
        <span class="section-num">02</span>
        <span class="section-divider"></span>
        <span class="section-tagline">CASE STUDY</span>
      </div>
      <div class="container">
        <h2>养出来什么</h2>
        <p class="section-subtitle">
          案例：
          <router-link to="/market" class="case-link">材价通</router-link>
          · 工程造价行业的数据中台
        </p>

        <h3>以前 vs 现在</h3>
        <table class="comparison-table">
          <thead>
            <tr>
              <th>🕐 以前</th>
              <th>⚡ 现在</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td class="before">人工汇总20数据源</td>
              <td class="after">凌晨自动抓取，0干预</td>
            </tr>
            <tr>
              <td class="before">跨城口径不一</td>
              <td class="after">9,931品种统一归一</td>
            </tr>
            <tr>
              <td class="before">期刊滞后查询</td>
              <td class="after">秒级跨城检索</td>
            </tr>
            <tr>
              <td class="before">历史趋势缺失</td>
              <td class="after">时序趋势可追溯</td>
            </tr>
            <tr>
              <td class="before">需要登录查数据</td>
              <td class="after">公开数据，鉴权API可对接</td>
            </tr>
          </tbody>
        </table>

        <p style="text-align: center; color: #a0a0a0; margin-top: 32px;">
          1人公司 + AI全程无需干预，覆盖数据业务全生命周期。
        </p>
        <div class="case-cta-wrap">
          <router-link to="/market" class="case-cta">
            查看实时市场行情 →
          </router-link>
        </div>
      </div>
    </section>

    <!-- 合作模式 -->
    <section class="pricing" id="pricing">
      <div class="section-marker">
        <span class="section-num">03</span>
        <span class="section-divider"></span>
        <span class="section-tagline">PRICING</span>
      </div>
      <div class="container">
        <h2>三种模式，按项目选</h2>
        <p class="section-subtitle">项目大小、持续性、调用量 —— 三种需求形态，对应三种合作深度。</p>

        <div class="pricing-grid">
          <div class="pricing-card">
            <h3>🥉 项目制</h3>
            <p class="suitable">适合：一次性数据基建</p>
            <p class="price-type">一次性报价</p>
            <ul>
              <li>需求诊断</li>
              <li>方案报价</li>
              <li>签约交付</li>
            </ul>
            <span class="cta-button is-disabled" aria-disabled="true">约需求诊断</span>
          </div>

          <div class="pricing-card featured">
            <h3>🥈 长期顾问</h3>
            <p class="suitable">适合：持续运维 / 增量迭代</p>
            <p class="price-type">月费，单独报价</p>
            <ul>
              <li>月度合作</li>
              <li>按需迭代</li>
              <li>随时调整</li>
              <li style="color: #e94560;">AI升级，项目自动升级</li>
            </ul>
            <span class="cta-button is-disabled" aria-disabled="true">约月度合作</span>
          </div>

          <div class="pricing-card">
            <h3>🥇 数据接入</h3>
            <p class="suitable">适合：直接调用已采集的20城数据</p>
            <p class="price-type">按调用量计费</p>
            <ul>
              <li>申请API试用</li>
              <li>评估用量</li>
              <li>开通服务</li>
            </ul>
            <span class="cta-button is-disabled" aria-disabled="true">申请API试用</span>
          </div>
        </div>
      </div>
    </section>

    <!-- FAQ -->
    <section class="faq" id="faq">
      <div class="section-marker">
        <span class="section-num">04</span>
        <span class="section-divider"></span>
        <span class="section-tagline">FAQ</span>
      </div>
      <div class="container">
        <h2>常见问题</h2>
        <p class="section-subtitle">合作前最常被问到的几件事</p>

        <div class="faq-list">
          <div
            v-for="(f, i) in faqs"
            :key="i"
            class="faq-item"
            :class="{ active: activeFaq === i }"
          >
            <div class="faq-question" @click="toggleFaq(i)">{{ f.q }}</div>
            <div class="faq-answer">{{ f.a }}</div>
          </div>
        </div>
      </div>
    </section>

    <!-- 联系 -->
    <section class="contact" id="contact">
      <div class="section-marker">
        <span class="section-num">05</span>
        <span class="section-divider"></span>
        <span class="section-tagline">CONTACT</span>
      </div>
      <div class="container">
        <h2>聊聊你的项目</h2>
        <p class="section-subtitle">发邮件，平均12小时内回复。</p>
        <p style="color: #a0a0a0; margin-bottom: 32px;">
          复杂需求附上：<strong>数据源</strong> / <strong>期望产出</strong> / <strong>时间线</strong>，三项即可。
        </p>
        <span class="contact-email is-disabled" aria-disabled="true">
          📧 hello@pengfit.cn
        </span>
      </div>
    </section>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted, nextTick } from 'vue'

// 阅读进度条
const readProgress = ref(0)

function onScroll() {
  const h = document.documentElement
  const max = h.scrollHeight - h.clientHeight
  readProgress.value = max > 0 ? Math.min(100, (window.scrollY / max) * 100) : 0
}

// 平滑滚动
function scrollTo(id) {
  const el = document.getElementById(id)
  if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

// FAQ 折叠(单开)
const activeFaq = ref(0)  // 2026-07-22: 默认展开第一条,减少空白感
const faqs = [
  { q: '你一个人能扛大项目吗？', a: '能。规模在 OpenClaw 边界内。超过此规模我会提前告知并建议扩队或外包分包，不暗中降质。' },
  { q: '工期和报价会变吗？', a: '报价单签前锁定。需求变更走书面补充协议，不口头承诺。' },
  { q: '数据从哪来？合规吗？', a: '全部来自政府/协会公开站点，严格遵守 robots.txt 与访问频次。' },
  { q: '能不能用我的私有数据源？', a: '能。采集、清洗、接入全链路都支持私有源定制。' },
  { q: '售后响应多久？', a: '工作日4小时内首响应，紧急工单24h内出修复方案。' },
  { q: '可以签合同/NDA吗？', a: '可以。私有部署场景常规配合签NDA。' },
]
function toggleFaq(i) {
  activeFaq.value = activeFaq.value === i ? -1 : i
}

// 数字滚动动画
const statsRef = ref(null)
let statsObserver = null
let statsAnimated = false

function animateNumber(el, target) {
  // 2026-07-22: 改用 requestAnimationFrame + ease-out cubic,更平滑更省电
  const duration = 2000
  let start = null
  function step(ts) {
    if (!start) start = ts
    const progress = Math.min((ts - start) / duration, 1)
    const eased = 1 - Math.pow(1 - progress, 3)
    el.textContent = Math.floor(eased * target).toLocaleString()
    if (progress < 1) requestAnimationFrame(step)
    else el.textContent = target.toLocaleString()
  }
  requestAnimationFrame(step)
}

onMounted(async () => {
  // 2026-07-22 强制顶部:防止从其他页面 / 浏览器恢复位置带来的滚动
  // nextTick 等 DOM 就绪 + 使用 instant(同步),避免动画/过渡中跳变
  await nextTick()
  window.scrollTo({ top: 0, left: 0, behavior: 'instant' })

  window.addEventListener('scroll', onScroll, { passive: true })
  onScroll()

  // 数字动画 — IntersectionObserver,首次进入视口触发
  if (statsRef.value) {
    statsObserver = new IntersectionObserver((entries) => {
      entries.forEach(entry => {
        if (entry.isIntersecting && !statsAnimated) {
          statsAnimated = true
          const els = entry.target.querySelectorAll('.stat-number[data-target]')
          els.forEach(el => {
            const target = parseInt(el.getAttribute('data-target'))
            if (!isNaN(target)) animateNumber(el, target)
          })
          statsObserver.disconnect()
        }
      })
    }, { threshold: 0.5 })
    statsObserver.observe(statsRef.value)
  }
})

onUnmounted(() => {
  window.removeEventListener('scroll', onScroll)
  if (statsObserver) statsObserver.disconnect()
})
</script>

<style scoped>
/* === Reset (pengfit-redesign 原样) === */
.showcase {
  margin: 0;
  padding: 0;
  box-sizing: border-box;
}
.showcase *,
.showcase *::before,
.showcase *::after {
  box-sizing: border-box;
}

.showcase {
  font-family: 'Inter', 'PingFang SC', 'Noto Sans SC', sans-serif;
  background: #0f0f0f;
  color: #f7f7f7;
  line-height: 1.6;
  overflow-x: hidden;
  min-height: 100vh;
}

/* === 阅读进度条(青色光晕) === */
.read-progress {
  position: fixed;
  top: 0;
  left: 0;
  height: 2px;
  background: linear-gradient(90deg, #00d9ff 0%, #e94560 100%);
  z-index: 1000;
  transition: width 0.1s linear;
  box-shadow: 0 0 8px rgba(0, 217, 255, 0.5);
  pointer-events: none;
}

/* === 容器 === */
.container {
  max-width: 1200px;
  margin: 0 auto;
  padding: 0 24px;
}

section {
  padding: 80px 0;
  position: relative;
  /* 锚点跳转留出顶部空间(顶部固定进度条 + 预留 nav 高度) */
  scroll-margin-top: 80px;
}

/* === 首屏 Hero === */
.hero {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  text-align: center;
  position: relative;
  background: linear-gradient(135deg, #0f0f0f 0%, #1a1a2e 100%);
}

.hero-content {
  position: relative;
  z-index: 2;
}

.hero h1 {
  display: flex;
  align-items: baseline;
  justify-content: center;
  gap: 20px;
  margin-bottom: 24px;
  flex-wrap: wrap;
}

.hero-title-main {
  /* 龙虾 — 主体,炫青一色、夸张体量 */
  font-size: clamp(56px, 8vw, 96px);
  font-weight: 900;
  line-height: 1;
  letter-spacing: -0.04em;
  background: linear-gradient(135deg, #00d9ff 0%, #e94560 100%);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
  text-shadow: 0 0 40px rgba(0, 217, 255, 0.3);
}

.hero-title-sub {
  /* 饲养员 — 点缀,瘦体、偏色、间距拉开 */
  font-family: 'HarmonyOS Sans SC', 'OPPO Sans', 'Mi Sans',
               'PingFang SC', 'Noto Sans SC', -apple-system,
               BlinkMacSystemFont, sans-serif;
  font-size: clamp(18px, 2.2vw, 26px);
  font-weight: 300;
  color: #a0a0a0;
  letter-spacing: 0.2em;
  white-space: nowrap;
  -webkit-font-smoothing: antialiased;
}

.hero .subtitle {
  font-size: 1.5rem;
  color: #a0a0a0;
  margin-bottom: 32px;
}

.hero .tagline {
  font-size: 1.2rem;
  color: #888;
  margin-bottom: 48px;
}

.cta-button {
  display: inline-block;
  padding: 16px 40px;
  background: linear-gradient(135deg, #00d9ff 0%, #0099cc 100%);
  color: #fff;
  text-decoration: none;
  border-radius: 8px;
  font-weight: 600;
  font-size: 1.1rem;
  transition: transform 0.3s ease, box-shadow 0.3s ease;
  cursor: pointer;
  border: none;
  font-family: inherit;
}
.cta-button:hover {
  transform: translateY(-2px);
  box-shadow: 0 10px 30px rgba(0, 217, 255, 0.3);
}

.hero-footer {
  margin-top: 60px;
  font-size: 0.9rem;
  color: #666;
}

/* === Hero 信任标签排 2026-07-22 === */
.hero-tags {
  display: flex;
  gap: 12px;
  justify-content: center;
  flex-wrap: wrap;
  margin-top: 40px;
}

.hero-tag-chip {
  display: inline-flex;
  align-items: center;
  padding: 8px 16px;
  background: rgba(0, 217, 255, 0.06);
  border: 1px solid rgba(0, 217, 255, 0.25);
  border-radius: 999px;
  color: #f7f7f7;
  font-size: 13px;
  text-decoration: none;
  transition: all 0.25s ease;
  cursor: pointer;
}

.hero-tag-chip:hover {
  background: rgba(0, 217, 255, 0.14);
  border-color: #00d9ff;
  transform: translateY(-2px);
  box-shadow: 0 8px 20px rgba(0, 217, 255, 0.18);
}

.hero-tag-num {
  font-family: 'JetBrains Mono', 'Fira Code', monospace;
  font-weight: 700;
  color: #00d9ff;
  margin-right: 4px;
  letter-spacing: -0.02em;
}

.hero-tag-cta {
  background: linear-gradient(135deg, rgba(0, 217, 255, 0.18) 0%, rgba(0, 153, 204, 0.12) 100%);
  border-color: rgba(0, 217, 255, 0.4);
  font-weight: 600;
}

/* === 标题 === */
h2 {
  font-size: 3rem;
  font-weight: 700;
  margin-bottom: 16px;
  color: #fff;
}
h3 {
  font-size: 2rem;
  font-weight: 600;
  margin-bottom: 12px;
  color: #fff;
}
.section-subtitle {
  font-size: 1.2rem;
  color: #a0a0a0;
  margin-bottom: 48px;
}

/* === 工作模式 === */
.workflow {
  background: #1a1a1a;
}

.workflow-diagram {
  background: #0f0f0f;
  border-radius: 16px;
  padding: 48px;
  margin: 40px 0;
  border: 1px solid #2a2a2a;
}

.workflow-steps {
  display: flex;
  flex-direction: column;
  gap: 24px;
  align-items: center;
}

.workflow-step {
  background: linear-gradient(135deg, #1a1a2e 0%, #0f0f0f 100%);
  padding: 24px 32px;
  border-radius: 12px;
  border: 1px solid #2a2a2a;
  width: 100%;
  max-width: 600px;
  text-align: center;
}

.workflow-step.highlight {
  border-color: #00d9ff;
  box-shadow: 0 0 20px rgba(0, 217, 255, 0.2);
}

.workflow-step h4 {
  color: #00d9ff;
  margin-bottom: 8px;
  font-size: 1.2rem;
}

.workflow-step p {
  color: #a0a0a0;
  font-size: 0.95rem;
}

.workflow-arrow {
  font-size: 2rem;
  color: #00d9ff;
}

.workflow-bottom {
  text-align: center;
  margin-top: 48px;
  color: #a0a0a0;
  line-height: 1.8;
}

/* === 案例 === */
.case-study {
  background: #0f0f0f;
}

.stats-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: 32px;
  margin: 48px 0;
}

.stat-card {
  text-align: center;
  padding: 32px;
  background: #1a1a1a;
  border-radius: 12px;
  border: 1px solid #2a2a2a;
}

.stat-number {
  font-size: 3rem;
  font-weight: 800;
  color: #00d9ff;
  margin-bottom: 8px;
  font-family: 'JetBrains Mono', 'Fira Code', monospace;
}

.stat-label {
  color: #a0a0a0;
  font-size: 0.95rem;
}

.comparison-table {
  width: 100%;
  margin: 48px 0;
  border-collapse: collapse;
}

.comparison-table th {
  background: #1a1a2e;
  padding: 16px;
  text-align: left;
  font-weight: 600;
  color: #00d9ff;
}

.comparison-table td {
  padding: 16px;
  border-bottom: 1px solid #2a2a2a;
  color: #f7f7f7;
}

.comparison-table tr:nth-child(even) {
  background: #1a1a1a;
}

.comparison-table .before {
  color: #e94560;
}
.comparison-table .after {
  color: #00d9ff;
}

/* === 案例 → Market 跳转 === */
.case-link {
  color: #00d9ff;
  text-decoration: none;
  border-bottom: 1px dashed rgba(0, 217, 255, 0.4);
  transition: all 0.2s ease;
  font-weight: 600;
}
.case-link:hover {
  color: #e94560;
  border-bottom-color: #e94560;
  border-bottom-style: solid;
}

.case-cta-wrap {
  text-align: center;
  margin-top: 32px;
}
.case-cta {
  display: inline-block;
  padding: 14px 32px;
  background: linear-gradient(135deg, #00d9ff 0%, #0099cc 100%);
  color: #fff;
  text-decoration: none;
  border-radius: 8px;
  font-weight: 600;
  font-size: 1.05rem;
  transition: transform 0.3s ease, box-shadow 0.3s ease;
}
.case-cta:hover {
  transform: translateY(-2px);
  box-shadow: 0 10px 30px rgba(0, 217, 255, 0.3);
}

/* === 合作模式 === */
.pricing {
  background: #1a1a1a;
}

.pricing-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
  gap: 32px;
  margin: 48px 0;
}

.pricing-card {
  background: #0f0f0f;
  border-radius: 16px;
  padding: 40px;
  border: 2px solid #2a2a2a;
  transition: transform 0.3s ease, border-color 0.3s ease;
  position: relative;
}

.pricing-card:hover {
  transform: translateY(-8px);
  border-color: #00d9ff;
}

.pricing-card.featured {
  border-color: #e94560;
  transform: scale(1.05);
}
/* featured hover: 保留缩放 + 抬升(覆盖基类 translateY) */
.pricing-card.featured:hover {
  transform: scale(1.05) translateY(-8px);
  border-color: #e94560;
}

.pricing-card.featured::before {
  content: '⭐ 推荐';
  position: absolute;
  top: -12px;
  left: 50%;
  transform: translateX(-50%);
  background: #e94560;
  color: #fff;
  padding: 4px 16px;
  border-radius: 20px;
  font-size: 0.9rem;
  font-weight: 600;
}

.pricing-card h3 {
  margin-bottom: 16px;
}

.pricing-card .price-type {
  color: #a0a0a0;
  margin-bottom: 24px;
}

.pricing-card .suitable {
  color: #888;
  font-size: 0.9rem;
  margin-bottom: 16px;
}

.pricing-card ul {
  list-style: none;
  margin: 24px 0;
  padding: 0;
}

.pricing-card ul li {
  padding: 8px 0;
  color: #a0a0a0;
  position: relative;
  padding-left: 24px;
}

.pricing-card ul li::before {
  content: '✓';
  position: absolute;
  left: 0;
  color: #00d9ff;
  font-weight: bold;
}

.pricing-card .cta-button {
  width: 100%;
  text-align: center;
  margin-top: 24px;
}

/* === FAQ === */
.faq {
  background: #0f0f0f;
}

.faq-list {
  max-width: 800px;
  margin: 0 auto;
}

.faq-item {
  background: #1a1a1a;
  border-radius: 12px;
  margin-bottom: 16px;
  border: 1px solid #2a2a2a;
  overflow: hidden;
}

.faq-question {
  padding: 24px;
  cursor: pointer;
  font-weight: 600;
  color: #fff;
  display: flex;
  justify-content: space-between;
  align-items: center;
  transition: background 0.3s ease;
  user-select: none;
}
.faq-question:hover {
  background: #222;
}
.faq-question::after {
  content: '+';
  font-size: 1.5rem;
  color: #00d9ff;
  transition: transform 0.3s ease;
}
.faq-item.active .faq-question::after {
  transform: rotate(45deg);
}

.faq-answer {
  padding: 0 24px;
  max-height: 0;
  opacity: 0;
  overflow: hidden;
  transition: max-height 0.3s ease, padding 0.3s ease, opacity 0.25s ease;
  color: #a0a0a0;
  line-height: 1.8;
}
.faq-item.active .faq-answer {
  padding: 0 24px 24px;
  max-height: 500px;
  opacity: 1;
  transition: max-height 0.3s ease, padding 0.3s ease, opacity 0.3s ease 0.05s;
}

/* === 联系 === */
.contact {
  background: #1a1a1a;
  text-align: center;
}

.contact-email {
  font-size: 1.5rem;
  color: #00d9ff;
  text-decoration: none;
  display: inline-block;
  margin-top: 24px;
  padding: 16px 32px;
  background: #0f0f0f;
  border-radius: 12px;
  border: 2px solid #00d9ff;
  transition: all 0.3s ease;
}
.contact-email:hover {
  background: #00d9ff;
  color: #fff;
  box-shadow: 0 10px 30px rgba(0, 217, 255, 0.3);
}

/* === 禁用态(三档按钮 / 联系邮箱,2026-07-22 道友要求暂未开放) === */
.cta-button.is-disabled,
.contact-email.is-disabled {
  opacity: 0.45;
  cursor: not-allowed;
  pointer-events: none;
  filter: grayscale(0.4);
  transform: none !important;
  box-shadow: none !important;
}
.cta-button.is-disabled::after,
.contact-email.is-disabled::after {
  content: '（暂未开放）';
  margin-left: 6px;
  font-size: 0.85em;
  opacity: 0.8;
}

/* === 全局可访问性:焦点环(青色光晕) === */
.cta-button:focus-visible,
.case-cta:focus-visible,
.case-link:focus-visible,
.faq-question:focus-visible,
.contact-email:focus-visible {
  outline: 2px solid #00d9ff;
  outline-offset: 3px;
}

/* === 动画 === */
@keyframes fadeInUp {
  from {
    opacity: 0;
    transform: translateY(30px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}
.fade-in {
  animation: fadeInUp 0.8s ease forwards;
}

/* === 段间分隔标记 2026-07-22(01/06 + 细青色分隔) === */
.section-marker {
  display: flex;
  align-items: center;
  gap: 16px;
  max-width: 1200px;
  margin: 0 auto 24px;
  padding: 0 24px;
}

.section-num {
  font-family: 'JetBrains Mono', 'Fira Code', monospace;
  font-size: 13px;
  font-weight: 700;
  color: #00d9ff;
  letter-spacing: 0.1em;
  flex-shrink: 0;
}

.section-divider {
  flex: 1;
  height: 1px;
  background: linear-gradient(90deg, rgba(0, 217, 255, 0.4) 0%, transparent 100%);
}

.section-tagline {
  font-family: 'JetBrains Mono', 'Fira Code', monospace;
  font-size: 11px;
  font-weight: 500;
  color: #888;
  letter-spacing: 0.3em;
  flex-shrink: 0;
}

@media (max-width: 640px) {
  .section-tagline { display: none; }  /* 移动端隐藏英文标签,只留编号 */
}

/* === 响应式 === */
@media (max-width: 768px) {
  .hero h1 {
    flex-direction: column;
    gap: 8px;
  }
  .hero-title-main {
    font-size: clamp(48px, 14vw, 72px);
  }
  .hero-title-sub {
    font-size: clamp(14px, 4vw, 20px);
  }
  .hero .subtitle {
    font-size: 1.2rem;
  }
  h2 {
    font-size: 2rem;
  }
  .stats-grid {
    grid-template-columns: repeat(2, 1fr);
    gap: 16px;
  }
  .stat-card { padding: 24px 16px; }
  .stat-number { font-size: 2.2rem; }
  .pricing-grid {
    grid-template-columns: 1fr;
  }
  .pricing-card.featured {
    transform: scale(1);
  }
  /* 案例 CTA 移动端更紧凑 */
  .case-cta {
    padding: 12px 24px;
    font-size: 0.95rem;
  }
  /* 联系邮箱移动端缩小 */
  .contact-email {
    font-size: 1.1rem;
    padding: 12px 20px;
  }
}
</style>