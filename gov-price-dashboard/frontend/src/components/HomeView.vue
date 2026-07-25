<!--
  HomeView.vue (2026-07-25 重构)
  /home 公开 landing — 按"开源项目"角度重组
  · 3 个 section: Hero / Architecture(原 01 Workflow) / Showcase(原 02 Case)
  · 删除模块 03 Pricing / 04 FAQ / 05 Contact — 与开源定位不符
  · Hero tags 去掉"联系咨询"(联系模块已删),保留"案例展示" + "查看源码"
  · Hero 文案重写:项目名 / 简介 / 数据规模;CTA 改"看看架构 →"
  · Workflow → Architecture,内容改为源站 → ETL → 归一 → Dashboard 全链路

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
          <!-- 2026-07-25: 把"龙虾 饲养员"(AI agent 人设名)换成项目自身名"材价通 / cjt-skills"，
               与开源项目定位对齐 -->
          <span class="hero-title-main">材价通</span>
          <span class="hero-title-sub">cjt-skills</span>
        </h1>
        <p class="subtitle fade-in">开源工程造价数据基础设施</p>
        <p class="tagline fade-in">20 城住建局 · 9,931 跨城归一品种 · 1 人 + AI 全程</p>
        <a href="#workflow" class="cta-button fade-in" @click.prevent="scrollTo('workflow')">看看架构 →</a>
        <div class="hero-footer fade-in">
          cjt-skills · MIT License · GitHub pengfit/cjt-skills
        </div>

        <!-- 2026-07-22 信任标签排 — 填补下半屏空白 -->
        <!-- 2026-07-25 重构:去掉"联系咨询"(Contact 模块已删),保留核心入口 -->
        <div class="hero-tags fade-in">
          <router-link to="/market" class="hero-tag-chip hero-tag-cta">
            材价通 →
          </router-link>
          <a href="https://github.com/pengfit/cjt-skills" target="_blank" rel="noopener" class="hero-tag-chip hero-tag-cta">
            <svg class="github-icon" viewBox="0 0 16 16" width="14" height="14" fill="currentColor" aria-hidden="true">
              <path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0 0 16 8c0-4.42-3.58-8-8-8z"/>
            </svg>
            查看源码 ↗
          </a>
          <a href="https://github.com/pengfit/cjt-skills/blob/main/README.md" target="_blank" rel="noopener" class="hero-tag-chip hero-tag-cta">
            📖 快速开始
          </a>
        </div>
      </div>
    </section>

    <!-- 架构原理（原 01 工作模式 → 2026-07-25 按开源项目视角重写） -->
    <section class="workflow" id="workflow">
      <div class="section-marker">
        <span class="section-num">01</span>
        <span class="section-divider"></span>
        <span class="section-tagline">ARCHITECTURE</span>
      </div>
      <div class="container">
        <h2>架构原理</h2>
        <p class="section-subtitle">源数据 → ETL Pipeline → 跨城归一 → 公开 Dashboard,全链路开源可复用。</p>

        <div class="workflow-diagram">
          <div class="workflow-steps">
            <div class="workflow-step">
              <h4>📡 源数据</h4>
              <p>20 个省/市住建局官方造价信息期刊</p>
            </div>
            <div class="workflow-arrow">↓</div>
            <div class="workflow-step highlight">
              <h4>⚙️ ETL Pipeline</h4>
              <p>gov-price-etl · 17 个城市技能包 · 三段式 ODS→DWD→DWS</p>
            </div>
            <div class="workflow-arrow">↓</div>
            <div class="workflow-step">
              <h4>🌐 跨城归一</h4>
              <p>L1~L4 四层规范化 · 9,931 个品种统一口径</p>
            </div>
            <div class="workflow-arrow">↓</div>
            <div class="workflow-step highlight">
              <h4>📊 Dashboard</h4>
              <p>FastAPI + Vue3 + ECharts · 公开访问 /market</p>
            </div>
          </div>
        </div>

        <div class="workflow-bottom">
          <p>每个环节独立成包、可独立部署、可被 fork。</p>
          <p>数据流透明 · 索引命名规范 · 进度文件断点续传。</p>
          <p><strong style="color: #00d9ff;">不只是个网站,是一套可复用的工程造价数据 ETL 工具链。</strong></p>
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
        <h2>它能做什么</h2>
        <p class="section-subtitle">
          部署示例：
          <router-link to="/market" class="case-link">材价通 Dashboard</router-link>
          · https://pengfit.cn · 工程造价行业的数据中台
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
          1 人 + AI 全程,覆盖数据采集 → 清洗 → 归一 → 展示全生命周期。
        </p>
        <div class="case-cta-wrap">
          <router-link to="/market" class="case-cta">
            查看实时市场行情 →
          </router-link>
        </div>
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
/* 2026-07-24 P2: 三档断点 — 768(平板) / 640(手机) / 480(小屏) */
@media (max-width: 768px) {
  .hero-title-main {
    font-size: clamp(48px, 14vw, 72px);
  }
  .hero-title-sub {
    font-size: clamp(14px, 4vw, 20px);
  }
  .hero .subtitle { font-size: 1.2rem; }
  .container { padding: 0 18px; }
  section { padding: 60px 0; }
  .section-marker { padding: 0 18px; }
  h2 { font-size: 2rem; }
  h3 { font-size: 1.6rem; }
  .section-subtitle { font-size: 1.05rem; margin-bottom: 32px; }
  .stats-grid {
    grid-template-columns: repeat(2, 1fr);
    gap: 16px;
  }
  .stat-card { padding: 24px 16px; }
  .stat-number { font-size: 2.2rem; }
  .pricing-grid {
    grid-template-columns: 1fr;
  }
  .pricing-card.featured { transform: scale(1); }
  .pricing-card.featured:hover { transform: scale(1) translateY(-8px); }
  .pricing-card { padding: 28px 24px; }
  .case-cta {
    padding: 12px 24px;
    font-size: 0.95rem;
  }
  .contact-email {
    font-size: 1.1rem;
    padding: 12px 20px;
  }
  .workflow-diagram { padding: 32px 24px; }
  .workflow-step { padding: 20px 24px; }
}

/* 2026-07-24 P2: 手机端(< 640) — 全面紧凑 */
@media (max-width: 640px) {
  .container { padding: 0 14px; }
  section { padding: 48px 0; scroll-margin-top: 64px; }
  .section-marker { padding: 0 14px; margin-bottom: 18px; gap: 12px; }
  .section-num { font-size: 12px; }

  /* Hero — 主标题更紧凑 */
  .hero { min-height: 90vh; }
  .hero h1 { gap: 6px; margin-bottom: 18px; }
  .hero-title-main { font-size: clamp(40px, 14vw, 56px); }
  .hero-title-sub { font-size: clamp(12px, 3.5vw, 16px); letter-spacing: 0.15em; }
  .hero .subtitle { font-size: 1.05rem; margin-bottom: 22px; }
  .hero .tagline { font-size: 1rem; margin-bottom: 32px; }
  .cta-button { padding: 13px 28px; font-size: 1rem; border-radius: 7px; }
  .hero-footer { margin-top: 36px; font-size: 0.8rem; padding: 0 8px; }
  .hero-tags { gap: 8px; margin-top: 28px; }
  .hero-tag-chip { padding: 6px 12px; font-size: 12px; }

  /* KPI / stats — 2 列维持,但紧凑 */
  .stats-grid { gap: 12px; margin: 32px 0; }
  .stat-card { padding: 20px 12px; }
  .stat-number { font-size: 1.9rem; }
  .stat-label { font-size: 0.85rem; }

  /* 案例 — 表格加横向滚动 */
  .comparison-table-wrap { overflow-x: auto; -webkit-overflow-scrolling: touch; margin: 32px 0; border-radius: 8px; }
  .comparison-table { min-width: 360px; margin: 0; font-size: 0.88rem; }
  .comparison-table th,
  .comparison-table td { padding: 10px 12px; }

  /* 工作流 — 紧凑 */
  .workflow-diagram { padding: 24px 16px; margin: 28px 0; border-radius: 12px; }
  .workflow-steps { gap: 16px; }
  .workflow-step { padding: 16px 18px; }
  .workflow-step h4 { font-size: 1.05rem; margin-bottom: 6px; }
  .workflow-step p { font-size: 0.88rem; line-height: 1.5; }
  .workflow-arrow { font-size: 1.4rem; }
  .workflow-bottom { margin-top: 28px; line-height: 1.7; font-size: 0.92rem; }

  /* Pricing — 更紧凑 */
  .pricing-grid { gap: 20px; margin: 28px 0; }
  .pricing-card { padding: 24px 18px; border-radius: 12px; }
  .pricing-card.featured::before { font-size: 0.8rem; padding: 3px 12px; }
  .pricing-card ul { margin: 18px 0; }
  .pricing-card ul li { padding: 6px 0 6px 20px; font-size: 0.88rem; }
  .pricing-card .cta-button { padding: 12px 20px; font-size: 0.95rem; }

  /* FAQ — 紧凑 + 可点击区域加大 */
  .faq-list { margin: 0 -4px; }
  .faq-item { margin-bottom: 12px; border-radius: 10px; }
  .faq-question { padding: 16px 18px; font-size: 0.95rem; }
  .faq-item.active .faq-answer { padding: 0 18px 18px; font-size: 0.88rem; line-height: 1.7; }

  /* Contact — 紧凑 */
  .contact-email { font-size: 0.95rem; padding: 12px 16px; border-radius: 10px; word-break: break-all; }
  .case-cta-wrap { margin-top: 20px; }
}

/* 2026-07-24 P2: 小屏(< 480, iPhone SE) — 极紧凑 */
@media (max-width: 480px) {
  .container { padding: 0 10px; }
  section { padding: 36px 0; }
  .section-marker { padding: 0 10px; margin-bottom: 14px; }
  .hero { min-height: 85vh; }
  .hero-title-main { font-size: 36px; }
  .hero .subtitle { font-size: 0.95rem; }
  .hero .tagline { font-size: 0.9rem; margin-bottom: 24px; }
  .cta-button { padding: 11px 22px; font-size: 0.92rem; }
  .hero-tag-chip { padding: 5px 10px; font-size: 11px; }
  h2 { font-size: 1.6rem; }
  h3 { font-size: 1.3rem; }
  .stat-number { font-size: 1.6rem; }
  .stat-card { padding: 16px 10px; }
  .workflow-diagram { padding: 18px 12px; }
  .pricing-card { padding: 20px 14px; }
  .faq-question { padding: 14px 14px; font-size: 0.88rem; }
  .faq-item.active .faq-answer { padding: 0 14px 14px; font-size: 0.82rem; }
  .contact-email { font-size: 0.85rem; padding: 10px 12px; }
}
</style>