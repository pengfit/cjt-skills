<!--
  ContactSection.vue (2026-07-21 /home 新增)
  联系入口 — 唤起本机邮件客户端（与 NotFoundView / LoginView 兜底风格一致）
-->
<script setup>
import { ref } from 'vue'
import { useInView } from '../../composables/useInView'
const { target, inView } = useInView()

const form = ref({ email: '', body: '', wechat: '' })
const sent = ref(false)

const submit = (e) => {
  // mailto 兜底:Phase A 仅唤起本机邮件客户端
  // Phase B 可接入 Formspree / Resend / 自建后端
  e.preventDefault()
  const subject = encodeURIComponent(`[Pengfit 咨询] 来自 ${form.value.email}`)
  const bodyText =
    `项目简介：\n${form.value.body}\n\n联系方式：${form.value.wechat || '(无)'}\n\n— 来自 Pengfit /home 联系表单`
  const full = `mailto:hello@pengfit.cn?subject=${subject}&body=${encodeURIComponent(bodyText)}`
  window.location.href = full
  sent.value = true
  setTimeout(() => { sent.value = false }, 3000)
}
</script>

<template>
  <section ref="target" id="home-contact" class="contact" :class="{ 'in-view': inView }">
    <div class="contact-inner">
      <h2 class="contact-title">聊聊你的项目</h2>
      <p class="contact-sub">
        发邮件平均 12 小时内回复。复杂需求附上：数据源 / 期望产出 / 时间线，三项即可。
      </p>

      <form class="contact-form" @submit="submit">
        <label class="contact-field">
          <span class="contact-label">邮箱</span>
          <input
            v-model="form.email"
            type="email"
            required
            placeholder="you@company.com"
            class="contact-input"
          />
        </label>
        <label class="contact-field">
          <span class="contact-label">项目简介（数据源 / 期望产出 / 时间线）</span>
          <textarea
            v-model="form.body"
            rows="5"
            required
            placeholder="例：每周抓取 XX 省 12 个地市的建材指导价，做成 API 调用，8 月底上线。"
            class="contact-input contact-textarea"
          ></textarea>
        </label>
        <label class="contact-field">
          <span class="contact-label">微信 / 其他联系方式（可选）</span>
          <input
            v-model="form.wechat"
            type="text"
            placeholder="微信号 / 手机号"
            class="contact-input"
          />
        </label>
        <div class="contact-actions">
          <button type="submit" class="contact-submit" :disabled="sent">
            {{ sent ? '已唤起邮件客户端' : '发送' }}
          </button>
          <span v-if="sent" class="contact-hint contact-hint-ok">
            已唤起本机邮件；如未弹出,请直发 hello@pengfit.cn
          </span>
          <span v-else class="contact-hint">
            点击后唤起本机邮件客户端
          </span>
        </div>
      </form>

      <div class="contact-alts">
        <a href="mailto:hello@pengfit.cn" class="contact-alt">📧 hello@pengfit.cn</a>
      </div>
    </div>
  </section>
</template>

<style scoped>
.contact { padding: 80px 0; background: var(--surface-2); }
.contact-inner { max-width: 640px; margin: 0 auto; padding: 0 32px; }
.contact-title {
  font-size: 30px;
  font-weight: 700;
  color: var(--text);
  text-align: center;
  margin: 0;
  letter-spacing: -0.01em;
}
.contact-sub {
  font-size: 15px;
  color: var(--text-2);
  text-align: center;
  margin: 14px 0 0;
  line-height: 1.7;
}
.contact-form {
  margin-top: 40px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  padding: 32px;
  display: flex;
  flex-direction: column;
  gap: 18px;
}
.contact-field { display: flex; flex-direction: column; }
.contact-label { font-size: 13px; color: var(--text-2); font-weight: 500; margin-bottom: 6px; }
.contact-input {
  font-family: inherit;
  font-size: 14px;
  color: var(--text);
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 10px 14px;
  outline: none;
  transition: border-color 0.12s cubic-bezier(0.4, 0, 0.2, 1), box-shadow 0.12s cubic-bezier(0.4, 0, 0.2, 1);
}
.contact-input:focus {
  border-color: var(--primary);
  box-shadow: 0 0 0 3px rgba(var(--primary-rgb), 0.12);
}
.contact-textarea { resize: vertical; min-height: 100px; line-height: 1.6; }
.contact-actions {
  display: flex;
  align-items: center;
  gap: 16px;
  margin-top: 6px;
  flex-wrap: wrap;
}
.contact-submit {
  background: var(--primary);
  color: var(--text-inverse);
  border: 1px solid var(--primary);
  font-family: inherit;
  font-size: 14px;
  font-weight: 500;
  padding: 10px 22px;
  border-radius: var(--radius);
  cursor: pointer;
  transition: background 0.12s cubic-bezier(0.4, 0, 0.2, 1), transform 0.12s cubic-bezier(0.4, 0, 0.2, 1), box-shadow 0.12s cubic-bezier(0.4, 0, 0.2, 1);
}
.contact-submit:hover:not(:disabled) {
  background: var(--primary-soft);
  transform: translateY(-1px);
  box-shadow: var(--shadow-primary);
}
.contact-submit:active:not(:disabled) { transform: translateY(0); }
.contact-submit:disabled { opacity: 0.55; cursor: not-allowed; }
.contact-hint { font-size: 12px; color: var(--text-3); }
.contact-hint-ok { color: var(--success); }
.contact-alts {
  margin-top: 32px;
  display: flex;
  justify-content: center;
  gap: 24px;
  flex-wrap: wrap;
}
.contact-alt {
  font-size: 14px;
  color: var(--text-2);
  text-decoration: none;
  transition: color 0.12s cubic-bezier(0.4, 0, 0.2, 1);
}
.contact-alt:hover { color: var(--primary); }

/* enter animation */
.contact-title, .contact-sub, .contact-form, .contact-alts {
  opacity: 0;
  transform: translateY(8px);
  transition: opacity 0.5s ease-out, transform 0.5s ease-out;
}
.contact.in-view .contact-title { opacity: 1; transform: translateY(0); transition-delay: 0s; }
.contact.in-view .contact-sub { opacity: 1; transform: translateY(0); transition-delay: 0.08s; }
.contact.in-view .contact-form { opacity: 1; transform: translateY(0); transition-delay: 0.16s; }
.contact.in-view .contact-alts { opacity: 1; transform: translateY(0); transition-delay: 0.24s; }

@media (max-width: 560px) {
  .contact { padding: 56px 0; }
  .contact-inner { padding: 0 20px; }
  .contact-title { font-size: 26px; }
  .contact-form { padding: 24px; }
}
</style>
