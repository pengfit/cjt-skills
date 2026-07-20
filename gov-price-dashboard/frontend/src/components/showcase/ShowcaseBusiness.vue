<!--
  ShowcaseBusiness.vue (2026-07-20 v3 - 删成本对比 + 卡片 UI 调整)

  调整:
  - 删 .biz-cost 块(template + data + CSS 全部移除)
  - 3 张卡 UI 调整:加 "传统 vs OPC" 对比行(metric 仍是主视觉大数字)

  3 主题: 快速产出 MVP / 高效迭代 / 流程闭环
-->
<template>
  <section class="business" id="business">
    <!-- 独立 section 标题, 跟 OPC · 怎么运作 / 案例 / 架构 三个 section 视觉一致 -->
    <header class="section-head">
      <h2 class="section-title">OPC · AI 增益</h2>
      <p class="section-sub">快速产出 MVP · 高效迭代 · 流程闭环</p>
    </header>

    <!-- 大卡样式与 ShowcaseWorkspace 的 .ws-ai-flow 同构: primary 边框 + 渐变背景 + 头部标题 (修改 10) -->
    <div class="biz-card">
      <div class="biz-card-head">
        <span class="biz-card-icon">⚡</span>
        <span class="biz-card-tag">3 大场景</span>
      </div>

      <!-- 3 个 AI 增益场景卡(UI 调整:加传统 vs OPC 对比) -->
      <div class="biz-gains">
        <article
          v-for="(g, i) in gains"
          :key="i"
          class="biz-gain"
          :ref="setCardRef(i)"
        >
          <div class="biz-gain-icon">{{ g.icon }}</div>
          <h3 class="biz-gain-scenario">{{ g.scenario }}</h3>
          <div
          class="biz-gain-metric"
          :ref="setMetricRef(i)"
        >{{ g.metric }}</div>
          <div class="biz-gain-compare">
            <span class="biz-gain-old">{{ g.traditional }}</span>
            <span class="biz-gain-arrow">→</span>
            <span class="biz-gain-new">{{ g.opc }}</span>
          </div>
        </article>
      </div>
    </div>
  </section>
</template>

<script setup>
import { ref, onMounted, onUnmounted, onBeforeUnmount } from 'vue'
import { parseMetric } from '../../composables/useCountUp.js'

// 2026-07-20 #10 hover 光斑跟随鼠标
function onCardMouseMove(e) {
  const card = e.currentTarget
  const rect = card.getBoundingClientRect()
  const x = ((e.clientX - rect.left) / rect.width * 100).toFixed(1)
  const y = ((e.clientY - rect.top) / rect.height * 100).toFixed(1)
  card.style.setProperty('--mx', x + '%')
  card.style.setProperty('--my', y + '%')
}

const gains = [
  {
    icon: '🚀',
    scenario: '快速产出 MVP',
    metric: '1天',
    traditional: '传统团队数月',
    opc: 'OPC 1 人 1 天',
  },
  {
    icon: '🔄',
    scenario: '高效迭代',
    metric: '每天',
    traditional: '传统团队 1 周 1 次',
    opc: 'OPC 每天自动',
  },
  {
    icon: '🔁',
    scenario: '流程闭环',
    metric: '0 人工',
    traditional: '传统跨部门协作',
    opc: 'OPC 1 人闭环',
  },
]

// 2026-07-20 #9: 预解析 metric 字符串, 元素入视口时 count-up
const metricParts = gains.map(g => parseMetric(g.metric))

// 2026-07-20 [BUGFIX]: cardRefs 和 cardObserver 必须声明!
// 之前模板 ref handler 里直接写 _ctx.cardRefs[i] = ...
// 因 cardRefs 未声明 → _ctx.cardRefs 是 undefined → TypeError: Cannot set properties of undefined
// 导致 ShowcaseView 整个挂掉, /showcase 页面只显示一行注释
const cardRefs = ref([])  // 存储每张卡片的 article DOM(用于 mousemove 清理)
const metricRefs = ref([]) // 存储每张卡片的 metric 子元素(给 IntersectionObserver observe)
let cardObserver = null

// 2026-07-20 [BUGFIX] v-for + 函数 ref 工厂
// Vue 3 函数 ref 在 v-for 里签名只接收 el, 拿不到外层索引 i
// 所以这里用工厂闭包, 模板里 :ref="setCardRef(i)" → 每个 i 生成独立 callback
const setCardRef = (i) => (el) => {
  if (el) {
    cardRefs.value[i] = el
    el.addEventListener('mousemove', onCardMouseMove)
  } else {
    // unmount 时 Vue 会传 null, 顺便清理监听器
    const prev = cardRefs.value[i]
    if (prev) prev.removeEventListener('mousemove', onCardMouseMove)
    cardRefs.value[i] = null
  }
}

const setMetricRef = (i) => (el) => {
  if (el && metricParts[i] && metricParts[i].isCountable) {
    metricRefs.value[i] = el
    // 初始化显示 0(等 observer 触发后开始 count-up)
    el.textContent = metricParts[i].prefix + '0' + metricParts[i].suffix
    el.dataset.countPrefix = metricParts[i].prefix
    el.dataset.countSuffix = metricParts[i].suffix
    el.dataset.countTarget = String(metricParts[i].num)
  } else {
    metricRefs.value[i] = null
  }
}

onMounted(() => {
  cardObserver = new IntersectionObserver((entries) => {
    entries.forEach((e) => {
      if (e.isIntersecting && e.target && !e.target.dataset.counted) {
        e.target.dataset.counted = '1'
        const target = parseFloat(e.target.dataset.countTarget)
        if (isNaN(target)) return
        const prefix = e.target.dataset.countPrefix || ''
        const suffix = e.target.dataset.countSuffix || ''
        const t0 = performance.now()
        const dur = 1400
        const step = (now) => {
          const p = Math.min((now - t0) / dur, 1)
          // ease-out cubic
          const eased = 1 - Math.pow(1 - p, 3)
          const v = p < 1 ? Math.round(target * eased) : target
          e.target.textContent = prefix + (target >= 1000 ? v.toLocaleString() : v) + suffix
          if (p < 1) requestAnimationFrame(step)
        }
        requestAnimationFrame(step)
      }
    })
  }, { threshold: 0.3 })
  // 用 metricRefs(子元素)喂 observer, observer 数到 target 时只改子元素 textContent
  metricRefs.value.forEach((el) => {
    if (el) cardObserver.observe(el)
  })
})

onUnmounted(() => {
  if (cardObserver) cardObserver.disconnect()
})

// 2026-07-20 [BUGFIX] #10 mousemove 清理:
// 之前遍历 cardRefs (装的是 .biz-gain-metric 子元素) 上 removeEventListener
// 但监听器绑在 article 上 → 永远删不到, 内存泄漏
// 现在 cardRefs 装 article, metricRefs 装 metric 子元素, 各司其职
onBeforeUnmount(() => {
  cardRefs.value.forEach((el) => {
    if (el) el.removeEventListener('mousemove', onCardMouseMove)
  })
})
</script>

<style scoped>
.business {
  padding: 96px 0 56px;  /* 2026-07-20 #3 间距统一 */
  border-top: 1px solid var(--border-light);
}

/* 独立 section 标题, 与其他 section 一致 (修复道友反馈: 缺独立标题) */
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

/* 大卡样式 (与 .ws-ai-flow 同构, 满足修改 10) */
.biz-card {
  background: linear-gradient(135deg, var(--primary-dim, rgba(37, 99, 235, 0.06)) 0%, var(--surface) 100%);
  border: 1px solid var(--primary);
  border-radius: var(--radius-lg);
  padding: 28px 32px;
}

.biz-card-head {
  display: flex;
  align-items: center;
  gap: 12px;
  padding-bottom: 16px;
  margin-bottom: 16px;
  border-bottom: 1px solid var(--border-light);
}

.biz-card-icon {
  font-size: 20px;
}

.biz-card-tag {
  font-size: 11px;
  font-weight: 600;
  color: var(--primary);
  background: var(--primary-dim, rgba(37, 99, 235, 0.08));
  padding: 4px 10px;
  border-radius: 999px;
  letter-spacing: 0.02em;
  margin-left: auto;
}

/* ── 3 个 AI 增益场景卡(UI 调整:加 vs 传统对比) ── */
.biz-gains {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 16px;
}

.biz-gain {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  padding: 24px 22px;
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

/* 2026-07-20 #10 卡片 hover 增强: icon 旋转 + metric 微缩放 + 渐变光斑 + 强阴影 */
.biz-gain:hover {
  border-color: var(--primary);
  box-shadow: 0 12px 28px rgba(30, 64, 175, 0.18), 0 4px 10px rgba(30, 64, 175, 0.08);
  transform: translateY(-6px);
}

/* hover 时 ::before 顶部条变高 */
.biz-gain:hover::before {
  height: 4px;
}

/* 卡片 hover 时 ::after 渐变光斑从中心扩散 (radial gradient 跟随) */
.biz-gain::after {
  content: '';
  position: absolute;
  inset: 0;
  border-radius: var(--radius-lg);
  background: radial-gradient(
    circle at var(--mx, 50%) var(--my, 0%),
    rgba(30, 64, 175, 0.10) 0%,
    rgba(30, 64, 175, 0) 50%
  );
  opacity: 0;
  transition: opacity 0.4s ease;
  pointer-events: none;
  z-index: 0;
}
.biz-gain:hover::after {
  opacity: 1;
}

.biz-gain-icon {
  font-size: 32px;
  line-height: 1;
  margin-bottom: 2px;
  position: relative;
  z-index: 1;
  transition: transform 0.4s cubic-bezier(0.34, 1.56, 0.64, 1);
}

.biz-gain:hover .biz-gain-icon {
  /* 旋转 8° + 放大 1.15, 弹性缓动 */
  transform: rotate(-8deg) scale(1.15);
}

.biz-gain-scenario {
  font-size: 14px;
  font-weight: 600;
  color: var(--text-2);
  margin: 0;
  letter-spacing: 0.02em;
}

.biz-gain-metric {
  font-size: 48px;
  font-weight: 800;
  color: var(--primary);
  font-family: var(--font-mono-num);
  font-variant-numeric: tabular-nums;
  letter-spacing: -0.03em;
  line-height: 1;
  margin: 4px 0;
  white-space: nowrap;
  position: relative;
  z-index: 1;
  transition: transform 0.3s cubic-bezier(0.34, 1.56, 0.64, 1), letter-spacing 0.3s ease;
}

.biz-gain:hover .biz-gain-metric {
  /* 数字微缩放 1.05, 字符间距加宽, 视觉跳动 */
  transform: scale(1.05);
  letter-spacing: -0.01em;
}

.biz-gain-compare {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  font-size: 12px;
  font-family: var(--font-mono-num);
  padding: 4px 0;
  flex-wrap: wrap;
}

.biz-gain-old {
  color: var(--text-3);
  text-decoration: line-through;
  text-decoration-color: var(--text-3);
  text-decoration-thickness: 1px;
}

.biz-gain-arrow {
  color: var(--primary);
  font-weight: 700;
  font-size: 14px;
}

.biz-gain-new {
  color: var(--primary);
  font-weight: 600;
  background: var(--primary-dim, rgba(37, 99, 235, 0.08));
  padding: 2px 8px;
  border-radius: 3px;
}


@media (max-width: 1024px) {
  .biz-gains { grid-template-columns: repeat(3, 1fr); }
}

@media (max-width: 640px) {
  .biz-gains { grid-template-columns: 1fr; }
  .biz-gain-metric { font-size: 40px; }
}
</style>