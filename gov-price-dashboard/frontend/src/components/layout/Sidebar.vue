<template>
  <!-- 移动端 backdrop（桌面端不渲染） -->
  <div v-if="open" class="mobile-sidebar-backdrop" @click="$emit('close')"></div>

  <aside
    class="sidebar"
    :class="{ 'mobile-open': open }"
    role="navigation"
    aria-label="主导航"
  >
    <div
      v-for="group in groups"
      :key="group.key"
      class="sidebar-group"
      :data-module="group.key"
    >
      <div class="sidebar-group-label">{{ group.label }}</div>
      <RouterLink
        v-for="item in group.items"
        :key="item.key"
        :to="item.path"
        class="sidebar-item"
        :class="{ active: currentTab === item.key }"
        :aria-keyshortcuts="item.shortcut ? item.shortcut : undefined"
        @click="$emit('navigate')"
      >
        <span class="sidebar-item-icon" aria-hidden="true">{{ item.icon }}</span>
        <span class="sidebar-item-label">{{ item.label }}</span>
        <span v-if="item.shortcut" class="sidebar-item-key" aria-hidden="true">{{ item.shortcut }}</span>
      </RouterLink>
    </div>
  </aside>
</template>

<script setup>
/**
 * 侧栏导航（统一组件）
 * 由父级传入 `groups`(完整路由+元信息),内部用 RouterLink 渲染。
 * `open` 控制移动端 drawer 状态,父级监听 `close` / `navigate`。
 *
 * @example
 *   const groups = computed(() => [
 *     { key: 'view',    label: '数据浏览',   items: [...] },
 *     { key: 'collect', label: '数据采集',   items: [...] },
 *   ])
 *   <Sidebar
 *     :groups="groups"
 *     :current-tab="route.name"
 *     :open="mobileSidebarOpen"
 *     @close="mobileSidebarOpen = false"
 *     @navigate="mobileSidebarOpen = false"
 *   />
 */
defineProps({
  groups:      { type: Array,  required: true },  // [{ key, label, items: [{key, label, path, icon, shortcut?}] }]
  currentTab:  { type: String, required: true },  // 当前路由 name
  open:        { type: Boolean, default: false }, // 移动端 drawer 开关
})

defineEmits(['close', 'navigate'])
</script>

<style scoped>
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
@keyframes backdrop-fade-in {
  to { opacity: 1; }
}

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
}

/* ── 模块分组 ── */
.sidebar-group {
  margin-bottom: 14px;
  position: relative;
}

/* 第二个及之后分组:顶部细线分隔 */
.sidebar-group + .sidebar-group {
  border-top: 1px solid var(--border);
  margin-top: 6px;
  padding-top: 4px;
}

.sidebar-group-label {
  font-size: 12px;
  font-weight: 700;
  color: var(--text-2);
  letter-spacing: 0.3px;
  padding: 14px 16px 8px 22px;
  position: relative;
  display: flex;
  align-items: center;
  gap: 6px;
}

/* 左侧色条标识 */
.sidebar-group-label::before {
  content: '';
  position: absolute;
  left: 10px;
  top: 50%;
  transform: translateY(-50%);
  width: 3px;
  height: 12px;
  border-radius: 2px;
  background: var(--text-3);
}

/* 4 模块色条 */
.sidebar-group[data-module="view"]    .sidebar-group-label::before { background: var(--primary); }
.sidebar-group[data-module="collect"] .sidebar-group-label::before { background: var(--warning); }
.sidebar-group[data-module="govern"]  .sidebar-group-label::before { background: #7c3aed; }
.sidebar-group[data-module="viz"]     .sidebar-group-label::before { background: var(--success); }

/* 第一个分组(数据浏览)label 顶部紧凑些 */
.sidebar-group[data-module="view"] .sidebar-group-label {
  padding-top: 10px;
}

/* ── 单项 ── */
.sidebar-item {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  text-align: left;
  padding: 8px 16px;
  border: none;
  background: transparent;
  color: var(--text-2);
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  transition: all var(--transition-fast);
  font-family: inherit;
  border-radius: 0;
  text-decoration: none;
}

.sidebar-item-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  border-radius: 6px;
  font-size: 14px;
  flex-shrink: 0;
  background: transparent;
  transition: all var(--transition-fast);
}

.sidebar-item-label {
  flex: 1;
  min-width: 0;
}

.sidebar-item-key {
  font-size: 10px;
  font-family: var(--font-mono-num);
  color: var(--text-3);
  padding: 1px 5px;
  border: 1px solid var(--border);
  border-radius: 3px;
  background: var(--surface-2);
  font-weight: 600;
  opacity: 0.6;
}

.sidebar-item:hover {
  color: var(--text);
  background: var(--primary-light);
}

.sidebar-item:hover .sidebar-item-icon {
  background: var(--primary-dim);
}

.sidebar-item.active {
  color: var(--primary);
  background: rgba(var(--primary-rgb), 0.08);
  font-weight: 600;
  border-left: 3px solid var(--primary);
  padding-left: 13px;
}

.sidebar-item.active .sidebar-item-icon {
  background: rgba(var(--primary-rgb), 0.12);
}

.sidebar-item.active .sidebar-item-key {
  color: var(--primary);
  border-color: rgba(var(--primary-rgb), 0.3);
  background: var(--surface);
  opacity: 1;
}

/* ── 移动端 drawer ── */
@media (max-width: 768px) {
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
  .sidebar.mobile-open {
    transform: translateX(0);
  }
  /* 抽屉打开时锁住 body 滚动,避免双滚动条 */
  .dashboard.mobile-sidebar-open {
    overflow: hidden;
  }
}

/* ── 平板:收起为图标列 ── */
@media (min-width: 769px) and (max-width: 1100px) {
  .sidebar {
    width: 64px;
    flex: 0 0 64px;
    padding: 12px 0;
  }
  .sidebar-group-label {
    display: none;
  }
  .sidebar-item {
    padding: 10px 20px;
    justify-content: center;
  }
  .sidebar-item-label,
  .sidebar-item-key {
    display: none;
  }
  .sidebar-item.active {
    border-left: none;
    border-bottom: 3px solid var(--primary);
    padding-left: 16px;
  }
  .sidebar-item.active .sidebar-item-icon {
    background: var(--primary);
    color: #fff;
  }
  /* 模块色条在折叠态变为整行左侧 */
  .sidebar-group-label::before {
    display: block;
    width: 60%;
    height: 2px;
    left: 20%;
    top: 0;
    transform: none;
    margin: 0 auto;
  }
}
</style>