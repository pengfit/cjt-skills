<template>
  <div class="app-pagination" v-if="total > 0">
    <div class="app-pagination__info">
      <span>{{ infoText }}</span>
      <select
        v-if="showSizeChanger"
        class="app-pagination__size"
        :value="pageSize"
        @change="$emit('update:pageSize', Number($event.target.value))"
      >
        <option v-for="opt in pageSizeOptions" :key="opt" :value="opt">{{ opt }} / 页</option>
      </select>
    </div>

    <div class="app-pagination__nav">
      <button
        class="app-pagination__btn"
        :disabled="current <= 1"
        @click="$emit('change', current - 1)"
        title="上一页"
      >‹</button>

      <template v-for="(item, i) in pageList" :key="i">
        <span v-if="item === '...'" class="app-pagination__ellipsis">···</span>
        <button
          v-else
          class="app-pagination__btn"
          :class="{ 'is-active': item === current }"
          @click="$emit('change', item)"
        >{{ item }}</button>
      </template>

      <button
        class="app-pagination__btn"
        :disabled="current >= totalPages"
        @click="$emit('change', current + 1)"
        title="下一页"
      >›</button>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  current: { type: Number, required: true },
  total: { type: Number, required: true },
  pageSize: { type: Number, default: 20 },
  showSizeChanger: { type: Boolean, default: false },
  pageSizeOptions: { type: Array, default: () => [10, 20, 50, 100] },
  /** 显示在 info 里的文案模板，变量：total, from, to */
  infoTemplate: { type: String, default: '共 {total} 条' },
})

defineEmits(['change', 'update:pageSize'])

const totalPages = computed(() => Math.max(1, Math.ceil(props.total / props.pageSize)))

const pageList = computed(() => {
  const tp = totalPages.value
  const cur = props.current
  if (tp <= 7) return Array.from({ length: tp }, (_, i) => i + 1)
  // 头尾省略：1 ... [cur-1 cur cur+1] ... tp
  const set = new Set([1, tp, cur, cur - 1, cur + 1])
  const list = [...set].filter(n => n >= 1 && n <= tp).sort((a, b) => a - b)
  const out = []
  for (let i = 0; i < list.length; i++) {
    if (i > 0 && list[i] - list[i - 1] > 1) out.push('...')
    out.push(list[i])
  }
  return out
})

const infoText = computed(() => {
  const from = (props.current - 1) * props.pageSize + 1
  const to = Math.min(props.current * props.pageSize, props.total)
  return props.infoTemplate
    .replace('{total}', props.total.toLocaleString())
    .replace('{from}', from.toLocaleString())
    .replace('{to}', to.toLocaleString())
})
</script>

<style scoped>
.app-pagination {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 12px 16px;
}

.app-pagination__info {
  display: flex;
  align-items: center;
  gap: 12px;
  font-size: 12px;
  color: var(--text-2);
}

.app-pagination__size {
  height: 28px;
  border: 1px solid var(--border);
  border-radius: 6px;
  background: var(--surface);
  color: var(--text);
  font-size: 12px;
  padding: 0 8px;
  cursor: pointer;
}

.app-pagination__nav {
  display: flex;
  gap: 4px;
  align-items: center;
}

.app-pagination__btn {
  min-width: 32px;
  height: 32px;
  padding: 0 8px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 6px;
  font-size: 12px;
  color: var(--text);
  cursor: pointer;
  transition: all 0.15s;
  font-weight: 500;
}
.app-pagination__btn:hover:not(:disabled):not(.is-active) {
  border-color: var(--primary);
  color: var(--primary);
  background: var(--primary-dim);
}
.app-pagination__btn.is-active {
  background: var(--primary);
  color: #fff;
  border-color: var(--primary);
}
.app-pagination__btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.app-pagination__ellipsis {
  padding: 0 4px;
  color: var(--text-3);
  font-size: 12px;
}
</style>
