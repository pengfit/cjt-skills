<template>
  <div class="mobile-sidebar-backdrop" v-if="open" @click="$emit('close')"></div>
  <aside class="sidebar" :class="{ 'mobile-open': open }" role="navigation" aria-label="主导航">
    <div v-for="(group, gi) in groupedTabs" :key="group.label" class="sidebar-group">
      <div class="sidebar-group-label">{{ group.label }}</div>
      <button
        v-for="tab in group.tabs"
        :key="tab.key"
        class="sidebar-item"
        :class="{ active: curTab === tab.key }"
        @click="$emit('select', tab.key)"
      >
        <span class="sidebar-item-icon" aria-hidden="true">{{ tab.icon }}</span>
        <span class="sidebar-item-label">{{ tab.label }}</span>
        <span class="sidebar-item-key" aria-hidden="true">{{ tab.num }}</span>
      </button>
    </div>
  </aside>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  curTab: { type: String, required: true },
  open: { type: Boolean, default: false },
})

defineEmits(['select', 'close'])

const TAB_GROUPS = [
  { label: '总览',     items: [
    { key: 'cockpit',  label: '驾驶舱',   icon: '🛩️' },
  ]},
  { label: '业务查价', items: [
    { key: 'list',     label: '全部数据', icon: '📋' },
    { key: 'category', label: '全部类别', icon: '🏷️' },
    { key: 'dist',     label: '价格分布', icon: '📈' },
  ]},
  { label: '系统监控', items: [
    { key: 'sync',     label: '数据同步', icon: '🔄' },
    { key: 'health',   label: '数据健康', icon: '💚' },
  ]},
  { label: '规则管理', items: [
    { key: 'breedcat', label: '品种分类', icon: '🧬' },
    { key: 'rules',    label: '规格解析', icon: '🧩' },
  ]},
]

const TAB_KEY_ORDER = ['cockpit', 'list', 'category', 'dist', 'sync', 'health', 'breedcat', 'rules']

const groupedTabs = computed(() => {
  let num = 0
  return TAB_GROUPS.map(g => ({
    label: g.label,
    tabs: g.items.map(t => {
      num++
      return { ...t, num: String(num) }
    }),
  }))
})

// 暴露：每个 tab 在 TAB_KEY_ORDER 里的下标（即快捷键 1-8）
const SHORTCUT_KEYS = TAB_KEY_ORDER
defineExpose({ SHORTCUT_KEYS })
</script>

<style scoped>
.mobile-sidebar-backdrop {
  position: fixed;
  inset: 0;
  background: rgba(15, 23, 42, 0.4);
  z-index: 50;
  display: none;
}

.sidebar {
  width: 200px;
  flex-shrink: 0;
  background: var(--surface);
  border-right: 1px solid var(--border);
  padding: 16px 12px;
  display: flex;
  flex-direction: column;
  gap: 16px;
  height: calc(100vh - var(--topbar-h));
  position: sticky;
  top: var(--topbar-h);
  overflow-y: auto;
}

.sidebar-group {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.sidebar-group-label {
  font-size: 11px;
  color: var(--text-3);
  letter-spacing: 2px;
  font-weight: 700;
  padding: 4px 10px 6px;
  text-transform: uppercase;
}

.sidebar-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 10px;
  border: 1px solid transparent;
  border-radius: 6px;
  background: transparent;
  color: var(--text-2);
  font-size: 13px;
  font-weight: 500;
  cursor: pointer;
  text-align: left;
  transition: all 0.15s;
  font-family: var(--font-sans);
}

.sidebar-item:hover {
  background: var(--surface-2);
  color: var(--text);
}

.sidebar-item.active {
  background: var(--primary-dim);
  color: var(--primary);
  font-weight: 700;
  border-color: rgba(var(--primary-rgb), 0.18);
}

.sidebar-item-icon {
  font-size: 14px;
  width: 18px;
  text-align: center;
  flex-shrink: 0;
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

.sidebar-item.active .sidebar-item-key {
  color: var(--primary);
  border-color: rgba(var(--primary-rgb), 0.3);
  background: var(--surface);
  opacity: 1;
}

@media (max-width: 768px) {
  .sidebar {
    position: fixed;
    top: var(--topbar-h);
    left: 0;
    bottom: 0;
    z-index: 60;
    transform: translateX(-100%);
    transition: transform 0.25s cubic-bezier(0.4, 0, 0.2, 1);
    box-shadow: 2px 0 12px rgba(15, 23, 42, 0.12);
  }
  .sidebar.mobile-open {
    transform: translateX(0);
  }
  .mobile-sidebar-backdrop {
    display: block;
  }
}
</style>
