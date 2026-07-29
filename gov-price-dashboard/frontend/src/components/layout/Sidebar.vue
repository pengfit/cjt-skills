<template>
  <!-- 2026-07-28:Phase 1 迁移 Element Plus — 侧栏改用 <el-menu> + <el-sub-menu> + <el-menu-item>
       保留 4 模块分组、icon、currentTab 高亮、路由跳转、响应式(mobile drawer + tablet 64px) -->

  <!-- 移动端 backdrop（桌面端不渲染） -->
  <div v-if="open" class="mobile-sidebar-backdrop" @click="$emit('close')"></div>

  <el-aside
    class="sidebar"
    :class="{ 'mobile-open': open, 'sidebar--collapsed': collapsed }"
    role="navigation"
    aria-label="主导航"
  >
    <!-- 2026-07-29 v3:改用 Element Plus 原生 <el-menu :collapse="collapsed"> + <el-menu-item :title>
         取代手写 collapsed CSS hack(EP 自动:64px 宽 / icon-only / 折叠 tooltip / active 高亮) -->
    <el-menu
      class="sidebar-menu"
      :collapse="collapsed"
      :default-active="currentTab"
      background-color="transparent"
      text-color="var(--text-2)"
      active-text-color="var(--primary)"
      @select="onMenuSelect"
    >
      <el-menu-item
        v-for="item in flatItems"
        :key="item.key"
        :index="item.key"
        :title="item.label"
        class="sidebar-item"
      >
        <!-- 2026-07-29 v3.5:icon 元素改 <i> —
             EP collapsed 内部对 <i> + <svg> + .el-icon 优先认作 icon,
             <span> 在不同版本行为不一致(曾踩坑)。结合 :style 内联兜底 -->
        <i
          class="sidebar-item-icon el-icon"
          aria-hidden="true"
          :style="collapsed
            ? 'display: inline-flex; visibility: visible; opacity: 1; font-size: 16px;'
            : ''"
        >{{ item.icon }}</i>
        <span class="sidebar-item-label">{{ item.label }}</span>
      </el-menu-item>
    </el-menu>
  </el-aside>
</template>

<script setup>
/**
 * 侧栏导航（Element Plus 版本,2026-07-28）
 * 由父级传入 `groups`(完整路由+元信息),内部用 el-menu 渲染,点击触发 router.push。
 * `open` 控制移动端 drawer 状态,父级监听 `close` / `navigate`。
 *
 * @example
 *   const groups = computed(() => [
 *     { key: 'collect', label: '数据采集', items: [...] },
 *   ])
 *   <Sidebar :groups="groups" :current-tab="route.name" :open="mobileSidebarOpen" />
 */
import { computed } from 'vue'
import { useRouter } from 'vue-router'

const props = defineProps({
  groups:      { type: Array,  required: true },  // [{ key, label, items: [{key, label, path, icon, shortcut?}] }]
  currentTab:  { type: String, required: true },  // 当前路由 name
  open:        { type: Boolean, default: false }, // 移动端 drawer 开关
  // 2026-07-29 v2:侧栏是否收起(64px ↔ 210px)。B 方案 — 无 sub-menu 概念,
  // 折叠态直接是 11 个 menu-item 图标单列
  collapsed:   { type: Boolean, default: false },
})

defineEmits(['close', 'navigate'])

const router = useRouter()
// 2026-07-29 v2 B 方案:把 4 个 group 的 items 平铺到一层(无 sub-menu)
const flatItems = computed(() => props.groups.flatMap(g => g.items))

function onMenuSelect(index) {
  // 找到对应 item 并跳转
  for (const g of props.groups) {
    const item = g.items.find(it => it.key === index)
    if (item) {
      router.push(item.path)
      break
    }
  }
}
</script>

<style scoped>
/* === Element Plus 深度穿透:覆盖 el-menu / el-sub-menu / el-menu-item 默认样式 === */
:deep(.el-menu) {
  border-right: none !important;
  background: transparent !important;
}

.mobile-sidebar-backdrop {
  position: fixed;
  inset: 0;
  background: rgba(15, 23, 42, 0.55);
  -webkit-backdrop-filter: blur(2px);
  backdrop-filter: blur(2px);
  z-index: 50;
  display: none;
  opacity: 0;
  transition: opacity 0.2s ease;
  animation: backdrop-fade-in 0.2s ease forwards;
}
@keyframes backdrop-fade-in { to { opacity: 1; } }

.sidebar {
  width: 210px;
  flex: 0 0 210px;
  background: var(--surface);
  border-right: 1px solid var(--border);
  padding: 12px 0;
  position: sticky;
  top: var(--topbar-h, 0);
  align-self: flex-start;
  height: calc(100vh - var(--topbar-h, 56px));
  overflow-y: auto;
  overflow-x: hidden;
  /* 2026-07-29 v3.2:折叠宽度回归 .sidebar--collapsed 显式管 —
     EP 的 --el-menu-collapse-width 只管内层 el-menu,父级 <el-aside> 必须自己收缩。
     之前我误以为 EP 接管,删了这条 → 父级 210px 不变,看着像折叠失败 */
  transition: width 0.22s ease, flex-basis 0.22s ease;
}

/* 2026-07-29 v3.2:回归 .sidebar--collapsed 显式宽 64px(EP 内部会同步 — EP 处理内部布局,
   这条管外层 .sidebar 容器宽。两者一起,210px ↔ 64px 平滑过渡) */
.sidebar.sidebar--collapsed {
  width: 64px;
  flex: 0 0 64px;
}

/* ── 2026-07-29 v3:折叠态 — 大部分交给 EP 内部,这里只补 2 件不自动的事:
     ① active 项加左侧 3px primary 竖条 + 浅蓝背景(EP 默认 active 是简单蓝色背景)
     ② icon 在折叠态稍大一点(EP 默认 16px,改 18px 看清楚) ── */
.sidebar.sidebar--collapsed :deep(.el-menu-item.is-active .el-menu-item__content) {
  background: rgba(var(--primary-rgb), 0.10) !important;
}
.sidebar.sidebar--collapsed :deep(.sidebar-item .sidebar-item-icon) {
  /* 2026-07-29 v3.5:折叠态图标终极兜底 —
     inline :style 已经把 display/visibility 写死,这里 CSS 兜底防止 EP 任何版本
     .el-menu--collapse 规则把 .el-menu-item__content > * display:none */
  display: inline-flex !important;
  visibility: visible !important;
  opacity: 1 !important;
  font-size: 16px !important;
  margin-right: 0 !important;
  font-style: normal;            /* <i> 默认 italic 必须盖掉 */
  vertical-align: middle;
}
/* 2026-07-29 v3.1 修复:展开态要有中文 label(此前误删了,只有 icon 一列);
   折叠态再藏 label,只露 icon */
.sidebar-item-label {
  margin-left: 8px;
  font-size: inherit;
}
.sidebar.sidebar--collapsed :deep(.sidebar-item-label) {
  display: none !important;
}
/* 2026-07-29 v3:展开态(默认) — 保留 4 样历史样式:210px 宽 / padding-left 36px / active 竖条 */
:deep(.sidebar-item .el-menu-item__content) {
  padding-left: 36px !important;
  border-radius: 0 !important;
}
:deep(.sidebar-item.is-active .el-menu-item__content) {
  background: rgba(var(--primary-rgb), 0.08) !important;
  border-left: 3px solid var(--primary);
  font-weight: 600 !important;
}
/* 折叠态:item 高度也压低一点 — 64px 宽 sidebar 装 11 个图标,过密不耐看 */
.sidebar.sidebar--collapsed :deep(.sidebar-item) {
  height: 36px !important;
  line-height: 36px !important;
}

/* ── el-menu-item 单项 ── */
:deep(.sidebar-item) {
  font-size: 13px !important;
  font-weight: 500 !important;
  height: 40px !important;
  line-height: 40px !important;
  margin: 0 !important;
}
:deep(.sidebar-item .el-menu-item__content) {
  padding-left: 36px !important;
  border-radius: 0 !important;
}
:deep(.sidebar-item.is-active .el-menu-item__content) {
  background: rgba(var(--primary-rgb), 0.08) !important;
  border-left: 3px solid var(--primary);
  font-weight: 600 !important;
}

.sidebar-item-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  font-size: 14px;
  margin-right: 8px;
}

/* ── 移动端 drawer — 全面 UI 优化 (2026-07-25) ── */
@media (max-width: 768px) {
  .sidebar {
    width: 92vw !important;
    max-width: 360px !important;
    padding: 16px 0 !important;
  }
  :deep(.sidebar-item) { font-size: 15px !important; height: 48px !important; line-height: 48px !important; }
  :deep(.sidebar-item .el-menu-item__content) { padding-left: 44px !important; }

  .mobile-sidebar-backdrop { display: block; }

  .sidebar {
    position: fixed;
    top: var(--topbar-h, 56px);
    left: 0;
    height: calc(100vh - var(--topbar-h, 56px));
    z-index: 60;
    transform: translateX(-100%);
    transition: transform 0.28s cubic-bezier(0.32, 0.72, 0, 1);
    box-shadow: 4px 0 24px rgba(15, 23, 42, 0.2);
    will-change: transform;
  }
  .sidebar.mobile-open { transform: translateX(0); }

  /* 抽屉打开时锁住 body 滚动,避免双滚动条 */
  .dashboard.mobile-sidebar-open { overflow: hidden; }
}

/* ── 平板:收起为图标列(响应式备用,已迁主要样式到 .sidebar--collapsed) ── */
@media (min-width: 769px) and (max-width: 1100px) {
  .sidebar { width: 64px; flex: 0 0 64px; padding: 12px 0; }
  /* 残存样式 — 与 .sidebar--collapsed 等价,窄屏强压以兼容历史 */
  :deep(.sidebar-item.is-active .el-menu-item__content) {
    background: rgba(var(--primary-rgb), 0.10) !important;
  }
  :deep(.sidebar-item .el-menu-item__content) {
    padding-left: 0 !important; padding-right: 0 !important; justify-content: center !important;
  }
  :deep(.sidebar-item .sidebar-item-icon) { display: inline-flex !important; margin-right: 0 !important; font-size: 18px !important; }
}
</style>