<template>
  <div class="tn-wrapper" :style="{ paddingLeft: depth * 16 + 'px' }">
    <!-- L1 / L2 可折叠节点 -->
    <template v-if="node.children">
      <div
        class="tn-row tn-branch"
        :class="{ 'tn-expanded': expanded, 'tn-highlight': highlight }"
        @click="onBranchClick"
      >
        <span class="tn-arrow" :class="{ 'tn-arrow-open': isOpen }">▸</span>
        <span class="tn-label">{{ node.name_l1 || node.name_l2 }}</span>
        <span class="tn-code">{{ node.l1 || node.l2 }}</span>
      </div>
      <Transition name="tn-slide">
        <div v-if="isOpen" class="tn-children">
          <TreeNode
            v-for="(child, i) in node.children"
            :key="child.l3 || child.l2 || i"
            :node="child"
            :depth="depth + 1"
            :active-l3="activeL3"
            :filter-mode="filterMode"
            :parent-path="[...parentPath, { code: node.l1 || node.l2, name: node.name_l1 || node.name_l2 }]"
            @select="(n) => $emit('select', n)"
          />
        </div>
      </Transition>
    </template>

    <!-- L3 叶子节点 -->
    <template v-else>
      <div
        class="tn-row tn-leaf"
        :class="{ 'tn-active': activeL3 === node.l3 }"
        @click="$emit('select', { ...node, parentPath })"
      >
        <span class="tn-arrow-placeholder"></span>
        <span class="tn-label">{{ node.name_l3 }}</span>
        <span class="tn-code">{{ node.l3 }}</span>
      </div>
    </template>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'

const props = defineProps({
  node: { type: Object, required: true },
  depth: { type: Number, default: 0 },
  activeL3: { type: String, default: '' },
  highlight: { type: Boolean, default: false },
  filterMode: { type: Boolean, default: false },
  parentPath: { type: Array, default: () => [] },
})

const emit = defineEmits(['select'])

const expanded = ref(false) // 默认全部折叠，点击展开

// 过滤模式下强制展开
const isOpen = computed(() => props.filterMode || expanded.value)

function toggle() {
  expanded.value = !expanded.value
}

function onBranchClick() {
  toggle()
  emit('select', { ...props.node, parentPath: props.parentPath })
}
</script>

<style scoped>
.tn-wrapper {
  user-select: none;
}

.tn-row {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 5px 8px;
  border-radius: 5px;
  cursor: pointer;
  font-size: 13px;
  transition: all 0.12s;
}

.tn-row:hover {
  background: var(--surface-2);
}

.tn-branch.tn-expanded {
  background: rgba(var(--primary-rgb), 0.05);
}

.tn-highlight {
  color: var(--primary);
  font-weight: 600;
}

.tn-leaf.tn-active {
  background: var(--primary-dim);
  color: var(--primary);
  font-weight: 700;
}

.tn-arrow {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 16px;
  height: 16px;
  font-size: 10px;
  color: var(--text-3);
  transition: transform 0.15s;
  flex-shrink: 0;
}

.tn-arrow-open {
  transform: rotate(90deg);
}

.tn-arrow-placeholder {
  width: 16px;
  flex-shrink: 0;
}

.tn-label {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.tn-code {
  font-family: var(--font-mono-num, 'SF Mono', monospace);
  font-size: 10px;
  color: var(--text-3);
  background: var(--surface-2);
  padding: 1px 5px;
  border-radius: 3px;
  flex-shrink: 0;
  opacity: 0.7;
}

.tn-active .tn-code {
  opacity: 1;
  background: var(--surface);
  color: var(--primary);
  border: 1px solid rgba(var(--primary-rgb), 0.2);
}

/* 展开动画 */
.tn-slide-enter-active,
.tn-slide-leave-active {
  transition: all 0.15s ease;
  overflow: hidden;
}

.tn-slide-enter-from,
.tn-slide-leave-to {
  opacity: 0;
  max-height: 0;
}

.tn-slide-enter-to,
.tn-slide-leave-from {
  opacity: 1;
  max-height: 500px;
}
</style>
