<template>
  <Teleport to="body">
    <Transition name="cmd-fade">
      <div v-if="show" class="cmd-mask" @click.self="$emit('close')">
        <div class="cmd-panel" role="dialog" aria-label="命令面板">
          <div class="cmd-input-wrap">
            <span class="cmd-icon">🔍</span>
            <input
              ref="inputRef"
              v-model="query"
              class="cmd-input"
              :placeholder="placeholder"
              @keydown="onKeyDown"
            />
            <span class="cmd-hint">esc</span>
          </div>

          <div class="cmd-results">
            <div v-if="filtered.length === 0" class="cmd-empty">
              <span class="cmd-empty-icon">🪺</span>
              <span>无匹配项</span>
            </div>
            <!-- 按 group 分组（P3-batch2）：页面跳转 / 动作 / 数据查询 -->
            <template v-for="group in grouped" :key="group.key">
              <div class="cmd-group-title">{{ group.label }}</div>
              <button
                v-for="(item, gi) in group.items"
                :key="item.id || item.label"
                class="cmd-item"
                :class="{ 'is-active': activeIndex === globalIndex(group.key, gi) }"
                @mouseenter="activeIndex = globalIndex(group.key, gi)"
                @click="select(item)"
              >
                <span class="cmd-item-icon">{{ item.icon || '·' }}</span>
                <div class="cmd-item-main">
                  <div class="cmd-item-label">{{ item.label }}</div>
                  <div v-if="item.hint" class="cmd-item-hint">{{ item.hint }}</div>
                </div>
                <span v-if="item.shortcut" class="cmd-item-shortcut">{{ item.shortcut }}</span>
              </button>
            </template>
          </div>

          <div class="cmd-footer">
            <span><kbd>↑</kbd><kbd>↓</kbd> 切换</span>
            <span><kbd>↵</kbd> 打开</span>
            <span><kbd>esc</kbd> 关闭</span>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup>
import { ref, computed, watch, nextTick } from 'vue'

const props = defineProps({
  show: { type: Boolean, default: false },
  placeholder: { type: String, default: '搜索页面、命令…' },
  /** 候选项：{ id, label, hint?, icon?, shortcut?, action? } */
  items: { type: Array, default: () => [] },
})

const emit = defineEmits(['close', 'select'])

const query = ref('')
const activeIndex = ref(0)
const inputRef = ref(null)

const filtered = computed(() => {
  const q = query.value.trim().toLowerCase()
  if (!q) return props.items.slice(0, 50)
  return props.items.filter(it =>
    (it.label || '').toLowerCase().includes(q) ||
    (it.hint || '').toLowerCase().includes(q) ||
    (it.group || '').toLowerCase().includes(q)
  ).slice(0, 50)
})

// 按 group 分组（P3-batch2）：保留 group 顺序，未设 group 的放到底部「其他」
const grouped = computed(() => {
  const order = ['页面跳转', '动作', '数据查询']
  const buckets = new Map()
  filtered.value.forEach(it => {
    const g = it.group || '其他'
    if (!buckets.has(g)) buckets.set(g, [])
    buckets.get(g).push(it)
  })
  const result = []
  for (const g of order) {
    if (buckets.has(g)) result.push({ key: g, label: g, items: buckets.get(g) })
  }
  for (const [k, v] of buckets) {
    if (!order.includes(k)) result.push({ key: k, label: k, items: v })
  }
  return result
})

// 计算当前 active 项在扁平 filtered 列表中的索引（用于键盘上下导航）
function globalIndex(groupKey, itemIndexInGroup) {
  let idx = 0
  for (const g of grouped.value) {
    if (g.key === groupKey) return idx + itemIndexInGroup
    idx += g.items.length
  }
  return idx
}

// 键盘上下时按整体顺序跳（fix 2026-07-12 P3-batch2）
const totalCount = computed(() => filtered.value.length)

watch(() => props.show, async (v) => {
  if (v) {
    query.value = ''
    activeIndex.value = 0
    await nextTick()
    inputRef.value?.focus()
  }
})

watch(query, () => { activeIndex.value = 0 })

function onKeyDown(e) {
  if (e.key === 'ArrowDown') {
    e.preventDefault()
    activeIndex.value = Math.min(activeIndex.value + 1, filtered.value.length - 1)
  } else if (e.key === 'ArrowUp') {
    e.preventDefault()
    activeIndex.value = Math.max(activeIndex.value - 1, 0)
  } else if (e.key === 'Enter') {
    e.preventDefault()
    const item = filtered.value[activeIndex.value]
    if (item) select(item)
  } else if (e.key === 'Escape') {
    e.preventDefault()
    emit('close')
  }
}

// 重命名 active 计算为 getter，确保 group 变换时上下导航仍指向同一项目（按扁平 filtered）
// 重新计算 flat → 在 grouped 已变的情况下，保证 activeIndex 不会越界
watch(grouped, () => {
  if (activeIndex.value >= filtered.value.length) activeIndex.value = 0
})

function select(item) {
  emit('select', item)
  if (typeof item.action === 'function') {
    try { item.action() } catch (e) { console.warn(e) }
  }
  emit('close')
}
</script>

<style scoped>
.cmd-mask {
  position: fixed;
  inset: 0;
  background: rgba(15, 23, 42, 0.45);
  backdrop-filter: blur(4px);
  z-index: 9999;
  display: flex;
  justify-content: center;
  align-items: flex-start;
  padding-top: 12vh;
}

.cmd-panel {
  width: min(580px, 92vw);
  max-height: 70vh;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 14px;
  box-shadow: 0 24px 64px rgba(15,23,42,0.25), 0 4px 12px rgba(15,23,42,0.12);
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

.cmd-input-wrap {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 14px 18px;
  border-bottom: 1px solid var(--border);
}
.cmd-icon { font-size: 16px; }
.cmd-input {
  flex: 1;
  border: none;
  outline: none;
  background: transparent;
  font-size: 15px;
  color: var(--text);
  font-family: inherit;
}
.cmd-input::placeholder { color: var(--text-3); }
.cmd-hint {
  font-size: 11px;
  padding: 2px 8px;
  background: var(--surface-2);
  color: var(--text-3);
  border-radius: 4px;
  font-family: ui-monospace, monospace;
}

.cmd-results {
  flex: 1;
  overflow-y: auto;
  padding: 6px;
}

/* 分组标题（P3-batch2） */
.cmd-group-title {
  padding: 8px 12px 4px;
  font-size: 10px;
  font-weight: 600;
  color: var(--text-3);
  text-transform: uppercase;
  letter-spacing: 0.6px;
}

.cmd-empty {
  padding: 32px 16px;
  text-align: center;
  color: var(--text-3);
  font-size: 13px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
}
.cmd-empty-icon { font-size: 24px; opacity: 0.6; }

.cmd-item {
  display: flex;
  align-items: center;
  gap: 12px;
  width: 100%;
  padding: 10px 12px;
  background: transparent;
  border: none;
  border-radius: 8px;
  cursor: pointer;
  text-align: left;
  transition: background 0.1s;
}
.cmd-item.is-active {
  background: var(--primary-dim);
}
.cmd-item-icon {
  width: 28px;
  height: 28px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  background: var(--surface-2);
  border-radius: 6px;
  font-size: 14px;
  flex-shrink: 0;
}
.cmd-item-main { flex: 1; min-width: 0; }
.cmd-item-label {
  font-size: 13px;
  color: var(--text);
  font-weight: 500;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.cmd-item-hint {
  font-size: 11px;
  color: var(--text-3);
  margin-top: 2px;
}
.cmd-item-shortcut {
  font-size: 11px;
  padding: 2px 7px;
  background: var(--surface-2);
  color: var(--text-2);
  border-radius: 4px;
  font-family: ui-monospace, monospace;
  flex-shrink: 0;
}

.cmd-footer {
  display: flex;
  gap: 16px;
  padding: 10px 18px;
  border-top: 1px solid var(--border);
  font-size: 11px;
  color: var(--text-3);
  background: var(--surface-2);
}
.cmd-footer kbd {
  display: inline-block;
  padding: 1px 5px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 3px;
  font-family: ui-monospace, monospace;
  font-size: 10px;
  margin-right: 4px;
}

/* Transition */
.cmd-fade-enter-active, .cmd-fade-leave-active {
  transition: opacity 0.15s;
}
.cmd-fade-enter-from, .cmd-fade-leave-to { opacity: 0; }
.cmd-fade-enter-active .cmd-panel,
.cmd-fade-leave-active .cmd-panel {
  transition: transform 0.18s cubic-bezier(0.16, 1, 0.3, 1);
}
.cmd-fade-enter-from .cmd-panel,
.cmd-fade-leave-to .cmd-panel {
  transform: scale(0.96) translateY(-8px);
}
</style>
