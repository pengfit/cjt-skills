<template>
  <!-- 2026-07-28:Phase 1 迁移 Element Plus — 侧栏改用 <el-menu> + <el-sub-menu> + <el-menu-item>
       保留 4 模块分组、icon、currentTab 高亮、路由跳转、响应式(mobile drawer + tablet 64px) -->

  <!-- 移动端 backdrop（桌面端不渲染） -->
  <div v-if="open" class="mobile-sidebar-backdrop" @click="$emit('close')"></div>

  <el-aside
    class="sidebar"
    :class="{ 'mobile-open': open }"
    role="navigation"
    aria-label="主导航"
  >
    <el-menu
      class="sidebar-menu"
      :default-active="currentTab"
      background-color="transparent"
      text-color="var(--text-2)"
      active-text-color="var(--primary)"
      :unique-opened="true"
      @select="onMenuSelect"
    >
      <el-sub-menu
        v-for="group in groups"
        :key="group.key"
        :index="group.key"
        :data-module="group.key"
        class="sidebar-group"
      >
        <template #title>
          <span class="sidebar-group-label">{{ group.label }}</span>
        </template>
        <el-menu-item
          v-for="item in group.items"
          :key="item.key"
          :index="item.key"
          class="sidebar-item"
        >
          <span class="sidebar-item-icon" aria-hidden="true">{{ item.icon }}</span>
          <template #title>{{ item.label }}</template>
        </el-menu-item>
      </el-sub-menu>
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
import { useRouter } from 'vue-router'

const props = defineProps({
  groups:      { type: Array,  required: true },  // [{ key, label, items: [{key, label, path, icon, shortcut?}] }]
  currentTab:  { type: String, required: true },  // 当前路由 name
  open:        { type: Boolean, default: false }, // 移动端 drawer 开关
})

defineEmits(['close', 'navigate'])

const router = useRouter()

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
}

/* ── el-sub-menu 模块分组 ── */
.sidebar-group { margin-bottom: 6px !important; }

.sidebar-group-label {
  font-size: 12px;
  font-weight: 700;
  color: var(--text-2);
  letter-spacing: 0.3px;
}

/* 第二个及之后分组:顶部细线分隔 */
:deep(.sidebar-group + .sidebar-group .el-sub-menu__title) {
  border-top: 1px solid var(--border);
}

/* 4 模块色条:左侧 3px */
:deep(.sidebar-group[data-module="view"] .el-sub-menu__title::before)    { background: var(--primary); }
:deep(.sidebar-group[data-module="collect"] .el-sub-menu__title::before) { background: var(--warning); }
:deep(.sidebar-group[data-module="govern"] .el-sub-menu__title::before)  { background: #7c3aed; }
:deep(.sidebar-group[data-module="viz"] .el-sub-menu__title::before)     { background: var(--success); }
:deep(.sidebar-group .el-sub-menu__title::before) {
  content: '';
  display: inline-block;
  width: 3px;
  height: 12px;
  border-radius: 2px;
  margin-right: 8px;
  vertical-align: middle;
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

/* ── 平板:收起为图标列 ── */
@media (min-width: 769px) and (max-width: 1100px) {
  .sidebar { width: 64px; flex: 0 0 64px; padding: 12px 0; }
  :deep(.sidebar-item .el-menu-item__content) { padding-left: 20px !important; padding-right: 8px !important; }
  :deep(.sidebar-item.is-active .el-menu-item__content) {
    border-left: none;
    border-bottom: 3px solid var(--primary);
  }
  :deep(.sidebar-group .el-sub-menu__title) { padding-left: 16px !important; }
  :deep(.sidebar-group .el-sub-menu__title span:first-child) { display: none; }
  :deep(.sidebar-item .el-menu-item__content > *) { display: none; }
  :deep(.sidebar-item .sidebar-item-icon) { display: inline-flex !important; margin-right: 0 !important; font-size: 18px !important; }
}
</style>