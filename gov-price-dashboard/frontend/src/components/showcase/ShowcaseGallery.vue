<!--
  ShowcaseGallery.vue (2026-07-19 A 风格改造)

  横滑 carousel(代替 3 栏卡片网格):
  - 用 scroll-snap,横向滚动
  - 每张大图 + 标题 + 描述
  - 无箭头 / 无圆点指示器(纯滚动,极简)
-->
<template>
  <section class="gallery">
    <header class="section-head">
      <h2 class="section-title">作品展示</h2>
      <p class="section-sub">Dashboard 实际界面 · 左右滑动浏览</p>
    </header>
    <div class="rail">
      <article class="shot" v-for="s in shots" :key="s.title">
        <a :href="s.href" target="_blank" rel="noopener">
          <div class="shot-frame">
            <img :src="s.src" :alt="s.title" loading="lazy" />
          </div>
        </a>
        <div class="shot-meta">
          <div class="shot-title">{{ s.title }}</div>
          <div class="shot-desc">{{ s.desc }}</div>
        </div>
      </article>
    </div>
  </section>
</template>

<script setup>
const shots = [
  {
    title: '全部数据',
    desc: '跨城全量浏览 · 关键词搜索 · 多维筛选',
    src: '/screenshots/01-list.png',
    href: '/cockpit?tab=list',
  },
  {
    title: '价格分布',
    desc: '分品类 · 分省份的价格区间分布',
    src: '/screenshots/02-dist.png',
    href: '/cockpit?tab=distribution',
  },
  {
    title: '数据来源追踪',
    desc: '规格解析透明度 · 数据来源审计',
    src: '/screenshots/03-provenance.png',
    href: '/cockpit?tab=provenance',
  },
  {
    title: '价格趋势',
    desc: '品类聚合趋势 · 全国跨城归一',
    src: '/screenshots/04-trend.png',
    href: '/cockpit?tab=trend',
  },
]
</script>

<style scoped>
.gallery {
  padding: 64px 0 48px;
}

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

.rail {
  display: flex;
  gap: 16px;
  overflow-x: auto;
  scroll-snap-type: x mandatory;
  scroll-padding-left: 0;
  padding-bottom: 8px;
  /* 隐藏滚动条但保留功能 */
  scrollbar-width: thin;
  scrollbar-color: var(--border-strong) transparent;
}

.rail::-webkit-scrollbar {
  height: 6px;
}

.rail::-webkit-scrollbar-track {
  background: transparent;
}

.rail::-webkit-scrollbar-thumb {
  background: var(--border-strong);
  border-radius: 3px;
}

.shot {
  flex: 0 0 calc(70% - 8px);
  min-width: 360px;
  margin: 0;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  overflow: hidden;
  scroll-snap-align: start;
  transition: all var(--transition);
}

.shot:hover {
  border-color: var(--border-strong);
  box-shadow: var(--shadow-md);
}

.shot a {
  display: block;
}

.shot-frame {
  aspect-ratio: 1280 / 900;
  background: var(--surface-2);
  overflow: hidden;
}

.shot-frame img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  object-position: top;
  display: block;
  transition: transform 0.4s ease;
}

.shot:hover .shot-frame img {
  transform: scale(1.02);
}

.shot-meta {
  padding: 14px 18px;
  border-top: 1px solid var(--border-light);
}

.shot-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--text);
  margin-bottom: 2px;
}

.shot-desc {
  font-size: 13px;
  color: var(--text-2);
}

@media (max-width: 640px) {
  .shot {
    flex: 0 0 88%;
    min-width: 0;
  }
}
</style>
