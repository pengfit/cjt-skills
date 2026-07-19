<template>
  <div class="login-page">
    <div class="login-card">
      <form @submit.prevent="onSubmit" class="login-form">
        <label class="field">
          <span>用户名</span>
          <input
            v-model.trim="username"
            type="text"
            autocomplete="off"
            placeholder="admin"
            required
            :disabled="loading"
          />
        </label>
        <label class="field">
          <span>密码</span>
          <input
            v-model="password"
            type="password"
            autocomplete="new-password"
            placeholder="••••••"
            required
            :disabled="loading"
          />
        </label>
        <button type="submit" class="btn-primary" :disabled="loading || !username || !password">
          {{ loading ? '登录中…' : '登 录' }}
        </button>
        <p v-if="errMsg" class="err">{{ errMsg }}</p>
      </form>
      <p class="hint">admin 单用户登录 · JWT 24h</p>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useAuth } from '../composables/useAuth.js'

const router = useRouter()
const route = useRoute()
const { login, isAuthed } = useAuth()

const username = ref('')
const password = ref('')
const loading = ref(false)
const errMsg = ref('')

onMounted(() => {
  // 已登录直接跳走
  if (isAuthed.value) {
    const next = route.query.next || '/cockpit'
    router.replace(next)
  }
})

async function onSubmit() {
  if (loading.value) return
  errMsg.value = ''
  loading.value = true
  try {
    await login(username.value, password.value)
    const next = route.query.next || '/cockpit'
    router.replace(next)
  } catch (e) {
    errMsg.value = e.message || '登录失败'
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.login-page {
  position: fixed;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, #0f172a 0%, #1e293b 50%, #334155 100%);
  z-index: 9999;
}
.login-card {
  width: 360px;
  padding: 36px 32px 28px;
  background: rgba(255, 255, 255, 0.98);
  border-radius: 14px;
  box-shadow: 0 20px 50px rgba(0, 0, 0, 0.3);
  color: #0f172a;
}
.brand { text-align: center; margin-bottom: 24px; }
.brand-logo { font-size: 40px; }
.brand-title { font-size: 20px; margin: 8px 0 2px; font-weight: 600; }
.brand-sub { font-size: 12px; color: #64748b; margin: 0; }
.login-form { display: flex; flex-direction: column; gap: 14px; }
.field { display: flex; flex-direction: column; gap: 6px; }
.field > span { font-size: 12px; color: #475569; }
.field input {
  padding: 10px 12px;
  border: 1px solid #cbd5e1;
  border-radius: 8px;
  font-size: 14px;
  outline: none;
  transition: border-color 0.15s;
}
.field input:focus { border-color: #3b82f6; box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.15); }
.btn-primary {
  margin-top: 6px;
  padding: 11px;
  background: #2563eb;
  color: #fff;
  border: none;
  border-radius: 8px;
  font-size: 14px;
  font-weight: 500;
  cursor: pointer;
  transition: background 0.15s;
}
.btn-primary:hover:not(:disabled) { background: #1d4ed8; }
.btn-primary:disabled { background: #94a3b8; cursor: not-allowed; }
.err {
  margin: 4px 0 0;
  padding: 8px 10px;
  background: #fef2f2;
  color: #b91c1c;
  border: 1px solid #fecaca;
  border-radius: 6px;
  font-size: 12px;
}
.hint { text-align: center; font-size: 11px; color: #94a3b8; margin: 18px 0 0; }
</style>