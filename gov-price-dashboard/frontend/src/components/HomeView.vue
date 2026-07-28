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
          <!-- 2026-07-28: 重心从项目名(ChinaJT)转向主题领域 + 方法
               ChinaJT 现在只是 cjt-skills 一个案例实现,不是 hero 主标题 -->
          <span class="hero-title-main">工程造价材料价格</span>
          <span class="hero-title-sub">跨城归一聚合 · 开放数据</span>
        </h1>
        <p class="subtitle fade-in">20 城住建局官方造价期刊 · 钢筋/水泥/给水管/电缆 · 跨城归一价</p>
        <p class="tagline fade-in">8,845 个跨城归一品类 · 81.7 万条记录 · 1 人 + OpenClaw + AI 全程运维 · 全部 MIT 开源</p>
        <!-- 2026-07-28 15:43:道友变 看看架构 → 查看数据 →(→ /market) -->
        <router-link to="/market" class="cta-button fade-in">
          查看数据 →
        </router-link>
        <div class="hero-footer fade-in">
          案例: ChinaJT (cjt-skills) · MIT License · GitHub pengfit/cjt-skills
        </div>

        <!-- 2026-07-22 信任标签排 — 填补下半屏空白 -->
        <!-- 2026-07-25 重构:去掉"联系咨询"(Contact 模块已删),保留核心入口 -->
        <!-- 2026-07-28: "ChinaJT →" 改"查看数据 →",ChinaJT 名字不再占 CTA 位 -->
        <div class="hero-tags fade-in">
          <!-- 2026-07-28 15:43:hero-tag-chip 里重复的「查看数据 →」删除(主 CTA 已改成同名) -->
          <a class="hero-tag-chip hero-tag-cta" style="display:none;" /> <!-- 占位防布局崩坏 -->
          <router-link to="/market" class="hero-tag-chip hero-tag-cta" style="display:none;" />
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

    <!-- 2026-07-28 15:38 道友报:PENGFIT MODE + CASE STUDY 轮播删,Hero 保留作唯一内容 -->


  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted, nextTick } from 'vue'
import { useHead } from '@unhead/vue'

// 2026-07-26 #SEO: /home 页面级 head 覆盖 — 业务关键词 / OG / Twitter Card / JSON-LD
//   默认 meta 在 index.html 已就位(Baidu 等不执行 JS 的爬虫靠它),
//   @unhead/vue 在 mount 时覆盖 → Google / Bing / 社媒分享卡实时拿到正确元数据
const SITE_URL = 'https://pengfit.cn'
useHead({
  title: '工程造价材料价格 · 跨城归一聚合 · 住建局官方期刊 · 开放数据',
  meta: [
    { name: 'description', content: '20 城住建局官方造价信息期刊 · 钢筋 / 水泥 / 给水管 / 电缆 等工程造价材料价格 · 跨城归一聚合 · 开放公开 · 即开即用 · 1 人 + OpenClaw + AI 全程运维 · 案例实现 ChinaJT (cjt-skills) MIT 开源' },
    { name: 'keywords', content: '工程造价, 材料价格, 跨城归一, 住建局, 政府数据, 钢筋价格, 水泥价格, 给水管价格, 电缆价格, 数据聚合, 数据可视化, 一人公司, OPC, AI, 开放, 公开, 即开即用, FastAPI, Vue, 案例, ChinaJT, cjt-skills, OpenClaw' },
    { property: 'og:title', content: '工程造价材料价格 · 跨城归一聚合 · 住建局官方期刊 · 开放数据' },
    { property: 'og:description', content: '20 城住建局官方造价信息期刊 · 钢筋/水泥/给水管/电缆等材料价格 · 跨城归一聚合 · 开放公开 · 即开即用 · 1 人 + OpenClaw + AI 全程运维 · 案例实现 ChinaJT (cjt-skills) MIT 开源' },
    { property: 'og:url', content: `${SITE_URL}/home` },
    { property: 'og:type', content: 'website' },
    { property: 'og:image', content: `${SITE_URL}/og-image.png` },
    { name: 'twitter:title', content: '工程造价材料价格 · 跨城归一聚合 · 开放数据' },
    { name: 'twitter:description', content: '20 城住建局官方造价信息期刊 · 钢筋/水泥/给水管/电缆等材料价格 · 跨城归一聚合 · 开放公开 · 即开即用 · 1 人 + OpenClaw + AI 全程运维 · 案例实现 ChinaJT (cjt-skills) MIT 开源' },
    { name: 'twitter:image', content: `${SITE_URL}/og-image.png` },
  ],
  link: [
    { rel: 'canonical', href: `${SITE_URL}/home` },
  ],
  script: [
    // JSON-LD: Organization + WebSite + SoftwareApplication(三合一,Google 富媒体片段用)
    {
      type: 'application/ld+json',
      innerHTML: JSON.stringify({
        '@context': 'https://schema.org',
        '@graph': [
          {
            '@type': 'Organization',
            '@id': `${SITE_URL}/#organization`,
            name: 'Pengfit',
            url: 'https://github.com/pengfit/cjt-skills',
            logo: `${SITE_URL}/favicon.svg`,
            sameAs: [
              'https://github.com/pengfit/cjt-skills',
            ],
          },
          {
            '@type': 'WebSite',
            '@id': `${SITE_URL}/#website`,
            url: `${SITE_URL}/`,
            name: '工程造价材料价格 · 跨城归一聚合 · 开放数据',
            alternateName: 'ChinaJT · cjt-skills Dashboard',
            inLanguage: 'zh-CN',
            description: '20 城住建局官方造价信息期刊 · 跨城数据聚合 · 开放公开 · 即开即用 · 1 人 + OpenClaw + AI 全程运维',
            publisher: { '@id': `${SITE_URL}/#organization` },
            potentialAction: {
              '@type': 'SearchAction',
              target: {
                '@type': 'EntryPoint',
                urlTemplate: `${SITE_URL}/market?q={search_term_string}`,
              },
              'query-input': 'required name=search_term_string',
            },
          },
          {
            '@type': 'SoftwareApplication',
            name: 'ChinaJT · cjt-skills',
            applicationCategory: 'BusinessApplication',
            applicationSubCategory: '工程材料价格数据聚合(案例实现)',
            operatingSystem: 'Web',
            url: `${SITE_URL}/`,
            description: '20 城住建局官方造价信息期刊 · 跨城数据聚合 · 开放公开 · 即开即用 · 1 人 + OpenClaw + AI 全程运维 · 本页为该方向的一个案例实现',
            offers: {
              '@type': 'Offer',
              price: '0',
              priceCurrency: 'CNY',
              availability: 'https://schema.org/InStock',
            },
            publisher: { '@id': `${SITE_URL}/#organization` },
            inLanguage: 'zh-CN',
            featureList: [
              '20 城住建局官方造价信息期刊',
              '8,845 个跨城数据聚合品种',
              '钢筋/水泥/给水管/电缆 价格行情',
              '1 人 + OpenClaw + AI 全程运维',
              '开放公开 · 即开即用 · 鉴权 API 可对接',
            ],
          },
        ],
      }),
    },
  ],
})

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
  align-items: center;  /* 2026-07-27 改: baseline → center, 主副标题字号悬殊(96px vs 22px)时 baseline 视觉偏左下,center 更稳 */
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
  /* 副标题 — 点缀,瘦体、偏色、间距拉开 */
  font-family: 'HarmonyOS Sans SC', 'OPPO Sans', 'Mi Sans',
               'PingFang SC', 'Noto Sans SC', -apple-system,
               BlinkMacSystemFont, sans-serif;
  font-size: clamp(18px, 2.2vw, 26px);
  font-weight: 300;
  line-height: 1;  /* 2026-07-27 加:与 .hero-title-main line-height: 1 对齐,避免 baseline 视觉漂移 */
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

/* === 2026-07-28 15:38:轮播图样式已删,HomeView 仅保留 Hero 区块 === */
/* 配套 CSS 全部清理(.home-carousel / .slide-* / .mode-* / .pillar* / .mode-flow / .flow-* / .case-* / .comparison-table 等) */

/* === 全局可访问性:焦点环(青色光晕) === */
/* 2026-07-27 删:Pricing/FAQ/Contact 三个模块的 CSS 死代码(模板 2026-07-25 重构已删) */
/* 2026-07-28 删:case-cta / case-link 也随 02 案例段一并清理 */
.cta-button:focus-visible,
.case-cta:focus-visible,
.case-link:focus-visible {
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

  /* Case CTA */
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
}
</style>