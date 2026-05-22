<template>
  <div class="cs-wrapper" ref="wrapperRef">
    <div class="cs-trigger" :class="{ open: isOpen, disabled }" @click="toggle" @keydown.down.prevent="openAndFocus" @keydown.up.prevent="openAndFocusLast" @keydown.enter.prevent="toggle" tabindex="0">
      <span class="cs-value" :class="{ placeholder: !modelValue }">
        {{ displayText }}
      </span>
      <span class="cs-arrow">▾</span>
    </div>
    <Transition name="cs-drop">
      <div v-if="isOpen" class="cs-dropdown" ref="dropdownRef">
        <div class="cs-search-wrap" v-if=" searchable">
          <input class="cs-search" v-model="searchText" :placeholder="'搜索...'" @keydown.escape="close" @keydown.down.prevent="moveFocus(1)" @keydown.up.prevent="moveFocus(-1)" @keydown.enter.prevent="selectFocused" ref="searchInput" />
        </div>
        <div class="cs-options" ref="optionsRef">
          <div
            v-for="(opt, idx) in filteredOptions"
            :key="opt.key"
            class="cs-option"
            :class="{ selected: opt.key === modelValue, focused: focusedIdx === idx }"
            @click="select(opt)"
            @mouseenter="focusedIdx = idx"
          >
            <span class="cs-opt-label">{{ opt.label || opt.key }}</span>
            <span v-if="opt.count != null" class="cs-opt-count">{{ Number(opt.count).toLocaleString() }}</span>
          </div>
          <div v-if="!filteredOptions.length" class="cs-empty">无结果</div>
        </div>
      </div>
    </Transition>
  </div>
</template>

<script setup>
import { ref, computed, watch, nextTick, onMounted, onUnmounted } from 'vue'

const props = defineProps({
  modelValue: { type: String, default: '' },
  options: { type: Array, default: () => [] }, // [{key, label?, count?}]
  placeholder: { type: String, default: '请选择' },
  disabled: { type: Boolean, default: false },
  searchable: { type: Boolean, default: false },
  countSuffix: { type: Boolean, default: false },  // show (count) after label
})
const emit = defineEmits(['update:modelValue', 'change'])

const isOpen = ref(false)
const searchText = ref('')
const focusedIdx = ref(-1)
const wrapperRef = ref(null)
const dropdownRef = ref(null)
const optionsRef = ref(null)
const searchInput = ref(null)

const displayText = computed(() => {
  if (!props.modelValue) return props.placeholder
  const found = props.options.find(o => o.key === props.modelValue)
  return found ? (found.label || found.key) : props.modelValue
})

const filteredOptions = computed(() => {
  if (!searchText.value) return props.options
  const q = searchText.value.toLowerCase()
  return props.options.filter(o => (o.key || '').toLowerCase().includes(q) || (o.label || '').toLowerCase().includes(q))
})

function toggle() {
  if (props.disabled) return
  isOpen.value ? close() : open()
}

function open() {
  isOpen.value = true
  searchText.value = ''
  focusedIdx.value = -1
  nextTick(() => {
    if (props.searchable) {
      searchInput.value?.focus()
    } else {
      // Scroll to current selection
      const idx = filteredOptions.value.findIndex(o => o.key === props.modelValue)
      if (idx >= 0) scrollToIdx(idx)
    }
  })
}

function close() {
  isOpen.value = false
  searchText.value = ''
  focusedIdx.value = -1
}

function select(opt) {
  emit('update:modelValue', opt.key)
  emit('change', opt.key)
  close()
}

function openAndFocus() {
  if (!isOpen.value) open()
  nextTick(() => moveFocus(1))
}

function openAndFocusLast() {
  if (!isOpen.value) open()
  nextTick(() => moveFocus(filteredOptions.value.length - 1 - filteredOptions.value.findIndex(o => o.key === modelValue)))
}

function moveFocus(dir) {
  if (!filteredOptions.value.length) return
  const start = focusedIdx.value < 0 ? 0 : focusedIdx.value
  let next = start + dir
  if (next < 0) next = filteredOptions.value.length - 1
  if (next >= filteredOptions.value.length) next = 0
  focusedIdx.value = next
  scrollToIdx(next)
}

function selectFocused() {
  if (focusedIdx.value >= 0 && filteredOptions.value[focusedIdx.value]) {
    select(filteredOptions.value[focusedIdx.value])
  }
}

function scrollToIdx(idx) {
  nextTick(() => {
    const el = optionsRef.value?.children[idx]
    el?.scrollIntoView({ block: 'nearest' })
  })
}

// Click outside
function onDocClick(e) {
  if (!wrapperRef.value?.contains(e.target)) close()
}

onMounted(() => document.addEventListener('mousedown', onDocClick))
onUnmounted(() => document.removeEventListener('mousedown', onDocClick))

// Reset focused when options change
watch(() => props.options, () => { focusedIdx.value = -1 })
</script>

<style scoped>
.cs-wrapper { position: relative; width: 100%; }

.cs-trigger {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 26px 8px 10px;
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  cursor: pointer;
  user-select: none;
  min-height: 36px;
  box-sizing: border-box;
  transition: border-color 0.15s, box-shadow 0.15s;
}

.cs-trigger:focus { outline: none; border-color: var(--primary); box-shadow: 0 0 0 3px var(--primary-glow); }
.cs-trigger.open { border-color: var(--primary); box-shadow: 0 0 0 3px var(--primary-glow); }
.cs-trigger.disabled { opacity: 0.4; cursor: not-allowed; }

.cs-value { font-size: 13px; color: var(--text); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; flex: 1; }
.cs-value.placeholder { color: var(--text-3); }

.cs-arrow { font-size: 10px; color: var(--text-3); transition: transform 0.2s; flex-shrink: 0; margin-left: 4px; }
.cs-trigger.open .cs-arrow { transform: rotate(180deg); }

.cs-dropdown {
  position: absolute;
  top: calc(100% + 4px);
  left: 0; right: 0;
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  box-shadow: 0 8px 24px rgba(0,0,0,0.4);
  z-index: 1000;
  overflow: hidden;
  min-width: 100%;
}

.cs-search-wrap { padding: 6px; border-bottom: 1px solid var(--border); }
.cs-search {
  width: 100%; box-sizing: border-box;
  padding: 5px 8px;
  background: var(--surface-3);
  border: 1px solid var(--border);
  border-radius: 4px;
  color: var(--text);
  font-size: 12px;
  outline: none;
  font-family: inherit;
}
.cs-search:focus { border-color: var(--primary); }

.cs-options { max-height: 220px; overflow-y: auto; }
.cs-options::-webkit-scrollbar { width: 4px; }
.cs-options::-webkit-scrollbar-track { background: var(--surface-2); }
.cs-options::-webkit-scrollbar-thumb { background: var(--border-light); border-radius: 2px; }

.cs-option {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 7px 10px;
  cursor: pointer;
  font-size: 13px;
  color: var(--text);
  transition: background 0.1s;
  gap: 8px;
}
.cs-option:hover, .cs-option.focused { background: var(--primary-glow); }
.cs-option.selected { color: var(--primary); font-weight: 600; }

.cs-opt-label { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.cs-opt-count { font-size: 11px; color: var(--text-3); flex-shrink: 0; font-family: 'DIN Alternate', monospace; }

.cs-empty { padding: 12px; text-align: center; color: var(--text-3); font-size: 12px; }

/* Transition */
.cs-drop-enter-active, .cs-drop-leave-active { transition: opacity 0.15s, transform 0.15s; }
.cs-drop-enter-from, .cs-drop-leave-to { opacity: 0; transform: translateY(-4px); }
</style>
