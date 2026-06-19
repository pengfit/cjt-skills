<template>
  <div class="pagination" v-if="total > 0">
    <button class="page-btn nav" :disabled="current <= 1" @click="$emit('change', current - 1)" title="上一页">‹</button>

    <template v-for="(item, i) in pageList" :key="i">
      <span v-if="item === '...'" class="page-btn ellipsis">···</span>
      <button
        v-else
        class="page-btn"
        :class="{ active: item === current }"
        :disabled="item === current"
        @click="$emit('change', item)"
      >{{ item }}</button>
    </template>

    <button class="page-btn nav" :disabled="current >= totalPages" @click="$emit('change', current + 1)" title="下一页">›</button>

    <div class="page-jump-wrap">
      <span>跳至</span>
      <input class="page-jump" v-model.number="jumpPage" @keyup.enter="goToPage" type="number" min="1" :max="totalPages" />
      <span>页</span>
    </div>

    <div class="page-size-wrap" v-if="showSizeChanger">
      <span>每页</span>
      <select class="page-size-select" :value="pageSize" @change="$emit('update:pageSize', Number($event.target.value))">
        <option v-for="s in pageSizeOptions" :key="s" :value="s">{{ s }}</option>
      </select>
      <span>条</span>
    </div>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'

const props = defineProps({
  current: { type: Number, required: true },
  total: { type: Number, required: true },
  pageSize: { type: Number, default: 20 },
  showSizeChanger: { type: Boolean, default: false },
  pageSizeOptions: { type: Array, default: () => [10, 20, 50, 100] },
})

const emit = defineEmits(['change', 'update:pageSize'])

const jumpPage = ref(1)

const totalPages = computed(() => Math.max(1, Math.ceil(props.total / props.pageSize)))

const pageList = computed(() => {
  const tp = totalPages.value
  const cur = props.current
  if (tp <= 7) return Array.from({ length: tp }, (_, i) => i + 1)
  const set = new Set([1, tp, cur, cur - 1, cur + 1])
  const list = [...set].filter(n => n >= 1 && n <= tp).sort((a, b) => a - b)
  const out = []
  for (let i = 0; i < list.length; i++) {
    if (i > 0 && list[i] - list[i - 1] > 1) out.push('...')
    out.push(list[i])
  }
  return out
})

function goToPage() {
  const p = Number(jumpPage.value)
  if (p >= 1 && p <= totalPages.value && p !== props.current) {
    emit('change', p)
  }
}
</script>

<style scoped>
/* 使用跟 style.css 全局 .pagination 一致的样式名称，
   但因 scoped 隔离需要重写相关样式，风格与全局相同 */
.pagination {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 5px;
  padding: 14px 18px;
  border-top: 1px solid rgba(15,23,42,0.08);
  background: rgba(241,245,249,0.8);
  flex-shrink: 0;
}

.page-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 34px;
  height: 32px;
  background: #ffffff;
  border: 1px solid rgba(241,245,249,0.6);
  color: #475569;
  border-radius: 6px;
  padding: 0 8px;
  font-size: 13px;
  cursor: pointer;
  transition: all 0.15s;
  font-family: inherit;
}
.page-btn:hover:not(:disabled):not(.active):not(.nav) {
  background: rgba(37,99,235,0.08);
  color: #2563eb;
  border-color: rgba(37,99,235,0.3);
}
.page-btn:disabled { opacity: 0.35; cursor: not-allowed; }
.page-btn.active {
  background: rgba(37,99,235,0.2);
  color: #2563eb;
  border-color: rgba(37,99,235,0.5);
  font-weight: 700;
  box-shadow: 0 0 8px rgba(37,99,235,0.12);
}
.page-btn.nav { font-size: 14px; padding: 0 10px; }
.page-btn.nav:hover:not(:disabled) {
  background: rgba(37,99,235,0.08);
  color: #2563eb;
  border-color: rgba(37,99,235,0.3);
}
.page-btn.ellipsis { cursor: default; color: #475569; }
.page-btn.ellipsis:hover { background: transparent; border-color: rgba(241,245,249,0.6); }

.page-jump-wrap {
  display: flex;
  align-items: center;
  gap: 5px;
  font-size: 12px;
  color: var(--text-3);
  margin-left: 6px;
}
.page-jump {
  width: 50px;
  background: #ffffff;
  border: 1px solid rgba(241,245,249,0.6);
  color: #1e293b;
  border-radius: 6px;
  padding: 4px 7px;
  font-size: 13px;
  text-align: center;
  outline: none;
  font-family: inherit;
  transition: border-color 0.2s;
  height: 32px;
  -moz-appearance: textfield;
}
.page-jump::-webkit-outer-spin-button,
.page-jump::-webkit-inner-spin-button { -webkit-appearance: none; margin: 0; }
.page-jump:focus { border-color: #2563eb; box-shadow: 0 0 0 3px rgba(37,99,235,0.15); }

.page-size-wrap {
  display: flex;
  align-items: center;
  gap: 5px;
  font-size: 12px;
  color: var(--text-3);
  margin-left: 10px;
}
.page-size-select {
  background: #ffffff;
  border: 1px solid rgba(241,245,249,0.6);
  color: #1e293b;
  border-radius: 6px;
  padding: 4px 8px;
  font-size: 13px;
  outline: none;
  cursor: pointer;
  font-family: inherit;
  height: 32px;
}
.page-size-select:focus { border-color: #2563eb; box-shadow: 0 0 0 3px rgba(37,99,235,0.15); }
</style>
