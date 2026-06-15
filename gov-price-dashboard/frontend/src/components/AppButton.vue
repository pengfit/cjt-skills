<template>
  <button
    class="app-btn"
    :class="[
      `app-btn--${variant}`,
      `app-btn--${size}`,
      { 'app-btn--block': block, 'app-btn--loading': loading },
    ]"
    :disabled="disabled || loading"
    :type="type"
    @click="$emit('click', $event)"
  >
    <span v-if="loading" class="app-btn__spinner" />
    <span v-else-if="icon || $slots.icon" class="app-btn__icon">
      <slot name="icon">{{ icon }}</slot>
    </span>
    <span class="app-btn__label">
      <slot />
    </span>
  </button>
</template>

<script setup>
defineProps({
  /** 视觉变体：primary / ghost / analyze / success / danger / plain / icon */
  variant: { type: String, default: 'primary' },
  /** 尺寸：sm / md / lg */
  size: { type: String, default: 'md' },
  type: { type: String, default: 'button' },
  disabled: { type: Boolean, default: false },
  loading: { type: Boolean, default: false },
  block: { type: Boolean, default: false },
  icon: { type: String, default: '' },
})
defineEmits(['click'])
</script>

<style scoped>
.app-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  border-radius: 8px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.15s;
  white-space: nowrap;
  user-select: none;
  border: 1px solid transparent;
}
.app-btn:disabled, .app-btn--loading {
  opacity: 0.5;
  cursor: not-allowed;
}

/* 尺寸 */
.app-btn--sm { height: 28px; padding: 0 10px; font-size: 12px; }
.app-btn--md { height: 36px; padding: 0 16px; font-size: 13px; }
.app-btn--lg { height: 42px; padding: 0 22px; font-size: 14px; }

.app-btn--block { width: 100%; }

/* 主按钮 */
.app-btn--primary {
  background: var(--primary);
  color: #fff;
  box-shadow: var(--shadow);
}
.app-btn--primary:not(:disabled):hover {
  background: var(--primary-dark);
  box-shadow: var(--shadow-md);
}
.app-btn--primary:not(:disabled):active { transform: scale(0.98); }

/* Ghost（描边按钮） */
.app-btn--ghost {
  background: var(--surface);
  color: var(--text);
  border-color: var(--border);
}
.app-btn--ghost:not(:disabled):hover {
  border-color: var(--primary);
  color: var(--primary);
  background: var(--primary-dim);
}

/* Analyze（带渐变光晕） */
.app-btn--analyze {
  background: linear-gradient(135deg, var(--primary), #6366f1);
  color: #fff;
  box-shadow: 0 2px 8px rgba(37,99,235,0.3);
}
.app-btn--analyze:not(:disabled):hover {
  box-shadow: 0 4px 14px rgba(37,99,235,0.4);
  transform: translateY(-1px);
}

/* Success */
.app-btn--success {
  background: var(--success);
  color: #fff;
}
.app-btn--success:not(:disabled):hover { background: #15803d; }

/* Danger */
.app-btn--danger {
  background: var(--danger);
  color: #fff;
}
.app-btn--danger:not(:disabled):hover { background: #b91c1c; }

/* Plain（透明背景，常用于页内操作） */
.app-btn--plain {
  background: transparent;
  color: var(--text-2);
}
.app-btn--plain:not(:disabled):hover {
  background: var(--surface-2);
  color: var(--text);
}

/* Icon（仅图标方块） */
.app-btn--icon {
  background: var(--surface);
  color: var(--text-2);
  border-color: var(--border);
  padding: 0;
  width: 32px;
  height: 32px;
  border-radius: 6px;
}
.app-btn--icon.app-btn--sm { width: 26px; height: 26px; }
.app-btn--icon:not(:disabled):hover {
  background: var(--primary-dim);
  border-color: var(--primary);
  color: var(--primary);
}

/* Loading spinner */
.app-btn__spinner {
  width: 14px;
  height: 14px;
  border: 2px solid currentColor;
  border-top-color: transparent;
  border-radius: 50%;
  animation: app-btn-spin 0.8s linear infinite;
}
@keyframes app-btn-spin { to { transform: rotate(360deg); } }

.app-btn__icon {
  display: inline-flex;
  align-items: center;
  font-size: 14px;
}
</style>
