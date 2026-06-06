<template>
  <div class="chat-root">

    <!-- Header -->
    <div class="chat-header">
      <span class="chat-title">🏛️ 虚天殿 · 外门长老</span>
      <span class="chat-sub">基于政府造价数据，实时分析价格行情</span>
    </div>

    <!-- Messages -->
    <div class="messages" ref="msgEl">
      <div
        v-for="(msg, i) in messages"
        :key="i"
        class="msg"
        :class="msg.role"
      >
        <img v-if="msg.role === 'ai'" src="/avatar-owner.png" class="msg-avatar-img" />
        <img v-else src="/avatar-user.png" class="msg-avatar-img" />
        <div class="msg-content">
          <div class="msg-name">{{ msg.role === 'ai' ? '外门长老' : '您' }}</div>
          <div class="msg-bubble" v-for="(line, j) in msg.lines" :key="j" :class="line.type">
            <span>{{ line.text }}</span>
          </div>
          <div class="msg-summary" v-if="msg.summary">{{ msg.summary }}</div>
        </div>
      </div>

      <!-- Typing indicator -->
      <div class="msg ai" v-if="typing">
        <img src="/avatar-owner.png" class="msg-avatar-img" />
        <div class="msg-content">
          <div class="msg-name">外门长老</div>
          <div class="typing-row">
            <span class="dot">●</span><span class="dot">●</span><span class="dot">●</span>
          </div>
        </div>
      </div>
    </div>

    <!-- Input -->
    <div class="input-bar">
      <input
        class="chat-input"
        v-model="input"
        placeholder="问外门长老：钢材今日价格？水泥最低价？..."
        @keyup.enter="send()"
      />
      <button class="send-btn" :disabled="!input.trim() || typing" @click="send()">
        {{ typing ? '🤔' : '发送' }}
      </button>
    </div>

    <!-- Quick Questions -->
    <div class="quick-questions" v-if="!messages.length && !typing">
      <div class="q-label">试试这样问：</div>
      <button v-for="q in quickQuestions" :key="q" class="q-chip" @click="input = q; send()">{{ q }}</button>
    </div>
  </div>
</template>

<script setup>
import { ref, nextTick, onMounted } from 'vue'
import axios from 'axios'

const API = import.meta.env.VITE_API_URL || '/api'

const input = ref('')
const messages = ref([])
const typing = ref(false)
const msgEl = ref(null)

const quickQuestions = [
  '钢材今日价格行情',
  '水泥最低价是哪个城市',
  '保温材料各地价格对比',
  '重庆管材价格',
  '最近沥青价格走势',
]

function scrollBottom() {
  nextTick(() => {
    if (msgEl.value) msgEl.value.scrollTop = msgEl.value.scrollHeight
  })
}

async function typeLines(msgIdx, lines) {
  for (const line of lines) {
    await new Promise(r => setTimeout(r, 350))
    if (messages.value[msgIdx]) {
      messages.value[msgIdx].lines.push(line)
      scrollBottom()
    }
  }
}

async function send() {
  const text = input.value.trim()
  if (!text || typing.value) return
  input.value = ''

  // Add user message
  messages.value.push({ role: 'user', lines: [{ type: 'info', text }], summary: '' })
  scrollBottom()

  // Add AI placeholder
  const aiMsgIdx = messages.value.length
  messages.value.push({ role: 'ai', lines: [], summary: '' })
  typing.value = true
  scrollBottom()

  try {
    // Search data
    const params = { keyword: text, page_size: 50 }
    const { data: res } = await axios.get(`${API}/search`, { params })
    const items = res.data || []

    if (!items.length) {
      await typeLines(aiMsgIdx, [
        { type: 'tip', text: `暂未找到「${text}」相关商品` },
        { type: 'tip', text: `建议试试：钢材、水泥、管材、沥青 等关键词` },
      ])
      messages.value[aiMsgIdx].summary = `未找到「${text}」相关记录`
      typing.value = false
      scrollBottom()
      return
    }

    const prices = items.map(i => Number(i.price)).filter(Boolean)
    if (!prices.length) {
      await typeLines(aiMsgIdx, [{ type: 'info', text: `找到 ${items.length} 条，但暂无价格数据` }])
      typing.value = false
      scrollBottom()
      return
    }

    const avg = prices.reduce((a, b) => a + b, 0) / prices.length
    const min = Math.min(...prices)
    const max = Math.max(...prices)
    const unit = items[0]?.unit || '单位'
    const cities = [...new Set(items.map(i => i.city || i.province).filter(Boolean))]
    const breeds = [...new Set(items.map(i => i.breed).filter(Boolean))]

    await typeLines(aiMsgIdx, [
      { type: 'info', text: `找到 ${items.length} 条「${breeds[0]}」相关记录，涉 ${cities.length } 个城市` },
    ])

    await typeLines(aiMsgIdx, [
      { type: 'trend-up', text: `均价 ¥均价 ¥${fmt(avg)}/${unit}` },
      { type: 'trend-down', text: `最低 ¥${fmt(min)}/${unit}，最高 ¥${fmt(max)}/${unit}` },
    ])

    // Find best deal
    const best = items.reduce((b, item) => {
      const p = Number(item.price)
      return (!isNaN(p) && (!b.price || p < b.price)) ? { ...item, price: p } : b
    }, {})

    if (best.price) {
      await typeLines(aiMsgIdx, [
        { type: 'city', text: `最低价在「${best.city || best.province}」¥${fmt(best.price)}/${best.unit}（${best.date}）` },
      ])
    }

    // Price range warning
    const range = max / min
    if (range > 2) {
      await typeLines(aiMsgIdx, [
        { type: 'tip', text: `最高价是最低价的 ${range.toFixed(1)} 倍，下单前建议多方比价` },
      ])
    } else {
      await typeLines(aiMsgIdx, [
        { type: 'tip', text: `价格差异合理，市场行情稳定` },
      ])
    }

    messages.value[aiMsgIdx].summary = `共 ${items.length} 条，均价 ¥${fmt(avg)}，最低 ¥${fmt(min)}，最高 ¥${fmt(max)}`

  } catch (e) {
    await typeLines(aiMsgIdx, [
      { type: 'tip', text: `查询失败，请稍后重试` },
    ])
  }

  typing.value = false
  scrollBottom()
}

function fmt(v) {
  if (v === null || v === undefined) return '--'
  const n = Number(v)
  if (isNaN(n)) return v
  return n.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}
</script>

<style scoped>
.chat-root {
  display: flex;
  flex-direction: column;
  height: calc(100vh - 110px);
  padding: 0 16px 16px;
  font-family: 'PingFang SC', 'Microsoft YaHei', sans-serif;
  background: linear-gradient(180deg, #1a0a00, #0a0400);
  color: #f5e6d0;
}

/* Header */
.chat-header {
  padding: 14px 0 10px;
  border-bottom: 1px solid #3d1f00;
  margin-bottom: 12px;
  display: flex;
  flex-direction: column;
  gap: 3px;
}

.chat-title { font-size: 18px; font-weight: 900; color: #ffd700; letter-spacing: 0.08em; }
.chat-sub { font-size: 12px; color: #8b6914; }

/* Messages */
.messages {
  flex: 1;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 16px;
  padding-bottom: 8px;
  scrollbar-width: thin;
  scrollbar-color: #8b4513 transparent;
}

.messages::-webkit-scrollbar { width: 4px; }
.messages::-webkit-scrollbar-thumb { background: #8b4513; border-radius: 2px; }

/* Message */
.msg { display: flex; gap: 10px; align-items: flex-start; }

.msg.user { flex-direction: row-reverse; }

.msg-avatar { font-size: 28px; flex-shrink: 0; line-height: 1; }
.msg-avatar-img { width: 36px; height: 36px; border-radius: 50%; object-fit: cover; flex-shrink: 0; border: 1px solid #8b4513; }

.msg-content { display: flex; flex-direction: column; gap: 4px; max-width: 80%; }

.msg-name { font-size: 11px; color: #8b6914; padding: 0 4px; }

.msg.user .msg-name { text-align: right; }

.msg-bubble {
  display: flex;
  gap: 7px;
  align-items: flex-start;
  padding: 9px 13px;
  border-radius: 12px;
  font-size: 13px;
  line-height: 1.5;
  animation: fadeIn 0.25s ease;
}

@keyframes fadeIn { from { opacity: 0; transform: translateY(5px); } to { opacity: 1; transform: translateY(0); } }

.msg.ai .msg-bubble {
  background: #1e0a00;
  border: 1px solid #8b4513;
  border-left: 3px solid #ffd700;
  color: #e8c080;
  border-radius: 4px 12px 12px 12px;
}

.msg.user .msg-bubble {
  background: linear-gradient(135deg, #7b2000, #c0392b);
  border: 1px solid #ffd700;
  color: #ffd700;
  border-radius: 12px 4px 12px 12px;
  text-align: right;
  justify-content: flex-end;
}

.msg-bubble.trend-up { color: #ff8888; }
.msg-bubble.trend-down { color: #88ff88; }
.msg-bubble.city { color: #88ccff; }
.msg-bubble.tip { color: #ffd700; font-weight: 600; }

.li { flex-shrink: 0; }

.msg-summary {
  font-size: 11px;
  color: #8b6914;
  padding: 5px 10px;
  background: #2a0800;
  border-radius: 6px;
  border-left: 2px solid #ffd700;
  margin-top: 2px;
}

/* Typing */
.typing-row { display: flex; gap: 5px; padding: 10px 14px; }

.dot {
  font-size: 14px;
  color: #ffd700;
  animation: dot 1.2s ease-in-out infinite;
}
.dot:nth-child(2) { animation-delay: -0.4s; }
.dot:nth-child(3) { animation-delay: -0.8s; }

@keyframes dot {
  0%, 80%, 100% { transform: scale(0.6); opacity: 0.4; }
  40%            { transform: scale(1); opacity: 1; }
}

/* Input */
.input-bar {
  display: flex;
  gap: 8px;
  padding-top: 10px;
  border-top: 1px solid #3d1f00;
  margin-top: 8px;
}

.chat-input {
  flex: 1;
  padding: 11px 15px;
  background: #1a0800;
  border: 1px solid #8b4513;
  border-radius: 12px;
  color: #f5e6d0;
  font-size: 14px;
  outline: none;
  transition: border-color 0.2s;
}

.chat-input:focus { border-color: #ffd700; }
.chat-input::placeholder { color: #8b6914; }

.send-btn {
  padding: 11px 20px;
  background: linear-gradient(135deg, #7b2000, #c0392b);
  border: 1px solid #ffd700;
  border-radius: 12px;
  color: #ffd700;
  font-size: 14px;
  font-weight: 700;
  cursor: pointer;
  transition: all 0.2s;
  white-space: nowrap;
}

.send-btn:hover:not(:disabled) { box-shadow: 0 0 14px rgba(255,215,0,0.3); }
.send-btn:disabled { opacity: 0.5; cursor: not-allowed; }

/* Quick Questions */
.quick-questions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  padding: 10px 0 4px;
}

.q-label { font-size: 12px; color: #8b6914; }

.q-chip {
  padding: 5px 12px;
  background: #1a0800;
  border: 1px solid #8b4513;
  border-radius: 16px;
  color: #c8a060;
  font-size: 12px;
  cursor: pointer;
  transition: all 0.2s;
}

.q-chip:hover { border-color: #ffd700; color: #ffd700; }
</style>