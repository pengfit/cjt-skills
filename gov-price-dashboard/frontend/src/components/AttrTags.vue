<template>
  <span class="attr-tags">
    <span
      v-for="item in flatAttrs"
      :key="item.key"
      class="attr-tag"
      :class="valTagClass(item.val)"
    >{{ item.val }}</span>
  </span>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  attr: { type: Object, default: () => ({}) },
  limit: { type: Number, default: 0 }  // 0 = no limit
})

// 将 attr（数组 [{k,v},...] 或对象 {key:value}）拍平为 [{key, val}, ...]
const flatAttrs = computed(() => {
  const result = []
  const attr = props.attr

  // 1) 数组格式：[{"k": "diameter", "v": "18mm"}, ...]
  if (Array.isArray(attr)) {
    for (const item of attr) {
      if (!item || typeof item !== 'object') continue
      const k = item.k ?? item.key ?? ''
      const v = item.v ?? item.val ?? item.value ?? ''
      if (!k || v === '' || v === null || v === undefined) continue
      result.push({ key: String(k), val: String(v) })
    }
  }
  // 2) 对象格式：{diameter: "18mm", grade: "HRB400E"}
  else if (attr && typeof attr === 'object') {
    for (const [k, v] of Object.entries(attr)) {
      if (v === null || v === undefined || v === '') continue
      if (typeof v === 'object') {
        for (const [sk, sv] of Object.entries(v)) {
          if (sv === null || sv === undefined || sv === '') continue
          result.push({ key: `${k}${sk}`, val: String(sv) })
        }
      } else {
        result.push({ key: String(k), val: String(v) })
      }
    }
  }

  if (props.limit > 0 && result.length > props.limit) {
    return result.slice(0, props.limit)
  }
  return result
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
