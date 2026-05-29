<template>
  <span class="attr-tags">
    <span
      v-for="(val, key) in flatAttrs"
      :key="key"
      class="attr-tag"
      :class="valTagClass(val)"
    >{{ val }}</span>
  </span>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  attr: { type: Object, default: () => ({}) },
  limit: { type: Number, default: 0 }  // 0 = no limit
})

// 将嵌套对象拍平为 key:value 字符串数组
const flatAttrs = computed(() => {
  const result = []
  for (const [k, v] of Object.entries(props.attr)) {
    if (v === null || v === undefined || v === '') continue
    if (typeof v === 'object') {
      for (const [sk, sv] of Object.entries(v)) {
        if (sv === null || sv === undefined || sv === '') continue
        result.push(`${k}${sk}:${sv}`)
      }
    } else {
      result.push(`${k}:${v}`)
    }
  }
  const list = result.map(s => {
    const idx = s.indexOf(':')
    return { key: s.slice(0, idx), val: s.slice(idx + 1) }
  })
  if (props.limit > 0 && list.length > props.limit) {
    return list.slice(0, props.limit)
  }
  return list
})

function valTagClass(val) {
  if (val === '是' || val === '有') return 'tag-green'
  if (val === '否' || val === '无') return 'tag-red'
  return ''
}
</script>

<style scoped>
.attr-tags { display: flex; flex-wrap: wrap; gap: 2px; }
.attr-tag {
  font-size: 10px;
  padding: 0 3px;
  border-radius: 3px;
  background: var(--border);
  color: var(--text-2);
  white-space: nowrap;
}
.tag-green { background: #1a3a1a; color: #5f8; }
.tag-red   { background: #3a1a1a; color: #f85; }
</style>
