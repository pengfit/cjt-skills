<template>
  <div class="sq-panel">
    <!-- Header -->
    <div class="sq-hdr">
      <div class="sq-hdr-left">
        <span class="dot-green"></span>
        <span class="hdr-title">规格解析质量</span>
        <div v-if="coverageLoaded && !loading" class="hdr-stats">
          <span class="stat-item stat-ok">{{ greenCount }} ≥80%</span>
          <span class="stat-item stat-warn">{{ redCount }} &lt;30%</span>
        </div>
      </div>
      <button class="btn-refresh" :disabled="loading" @click="$emit('refresh')">
        <span v-if="loading" class="spinner"></span>
        {{ loading ? '刷新中' : '刷新' }}
      </button>
    </div>

    <!-- Coverage grid -->
    <div v-if="sortedCoverage.length" class="sq-grid">
      <div
        v-for="c in sortedCoverage"
        :key="c.category"
        class="sq-card"
        :class="{
          'card-good': c.rate >= 80,
          'card-warn': c.rate >= 30 && c.rate < 80,
          'card-bad': c.rate < 30,
          'card-active': activeCat === c.category
        }"
        :style="{ borderLeftColor: catColor(c.category) }"
      >
        <div class="card-top">
          <span class="card-cat">{{ c.category }}</span>
          <span class="card-pct" :class="c.rate < 50 ? 'pct-warn' : ''">{{ c.rate }}%</span>
        </div>
        <div class="card-bar">
          <div class="bar-fill" :style="{ width: c.rate + '%' }"></div>
        </div>
        <div class="card-btm">
          <span class="card-count">{{ c.with_attr }}/{{ c.total }}</span>
          <div class="card-actions">
            <button
              class="btn-icon btn-sample"
              :class="{ active: activeCat === c.category }"
              :disabled="loading && activeCat !== c.category"
              title="抽样"
              @click="$emit('sample', c.category)"
            >
              <span v-if="loading && activeCat === c.category" class="sp-xs"></span>
              <span v-else>抽</span>
            </button>
            <button
              class="btn-icon btn-clean"
              :class="{ done: cleanDoneCat === c.category }"
              :disabled="cleaningCat === c.category"
              title="清洗"
              @click.stop="$emit('clean', c.category)"
            >
              <span v-if="cleaningCat === c.category" class="sp-xs"></span>
              <span v-else-if="cleanDoneCat === c.category">{{ cleanDoneOk ? '✓' : '✗' }}</span>
              <span v-else>洗</span>
            </button>
          </div>
        </div>
      </div>
    </div>

    <!-- Skeleton -->
    <div v-else-if="loading" class="sq-grid">
      <div v-for="i in 6" :key="i" class="sq-card sk-card">
        <div class="sk-line sk-title"></div>
        <div class="sk-bar"></div>
        <div class="sk-line sk-count"></div>
      </div>
    </div>

    <!-- Empty -->
    <div v-else class="sq-empty">暂无数据</div>

    <!-- Toast -->
    <Transition name="fade">
      <div v-if="toastMsg" class="sq-toast">{{ toastMsg }}</div>
    </Transition>

    <!-- Confirm modal -->
    <Transition name="fade">
      <div v-if="confirmMsg" class="sq-overlay" @click.self="$emit('confirm-clean-cancel')">
        <div class="sq-confirm">
          <span class="confirm-icon">⚠️</span>
          <div class="confirm-body">
            <div class="confirm-title">确认清洗</div>
            <div class="confirm-msg">{{ confirmMsg }}</div>
          </div>
          <div class="confirm-btns">
            <button class="btn-cancel" @click="$emit('confirm-clean-cancel')">取消</button>
            <button class="btn-ok" @click="$emit('confirm-clean-ok')">确认</button>
          </div>
        </div>
      </div>
    </Transition>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  coverage: { type: Array, default: () => [] },
  activeCat: { type: String, default: '' },
  loading: { type: Boolean, default: false },
  cleaningCat: { type: String, default: '' },
  cleanDoneCat: { type: String, default: '' },
  cleanDoneOk: { type: Boolean, default: true },
  toastMsg: { type: String, default: '' },
  confirmMsg: { type: String, default: '' },
  coverageLoaded: { type: Boolean, default: false },
})

defineEmits(['refresh', 'sample', 'clean', 'confirm-clean-cancel', 'confirm-clean-ok'])

const PALETTE = [
  '#6dd5ed','#4facfe','#6a85f5','#9b59b6','#7c3aed',
  '#b45309','#f97316','#dc2626','#e11d48','#06b6d4',
]

function catColor(name) {
  let h = 0
  for (const c of String(name)) { h = (h * 31 + c.charCodeAt(0)) & 0xffffffff }
  return PALETTE[Math.abs(h) % PALETTE.length]
}

// Sort coverage desc by rate (安装完成率 高→低)
const sortedCoverage = computed(() =>
  [...props.coverage].sort((a, b) => b.rate - a.rate)
)


const greenCount = computed(() => props.coverage.filter(c => c.rate >= 80).length)
const redCount = computed(() => props.coverage.filter(c => c.rate < 30).length)
</script>

<style scoped>
.sq-panel {
  background: rgba(15,23,42,0.82);
  border: 1px solid rgba(15,23,42,0.07);
  border-radius: 12px;
  padding: 14px;
  position: relative;
  overflow: hidden;
}

/* Header */
.sq-hdr {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
  gap: 12px;
}
.sq-hdr-left { display: flex; align-items: center; gap: 10px; }
.dot-green { width: 8px; height: 8px; border-radius: 50%; background: var(--status-ok); flex-shrink: 0; }
.hdr-title { font-size: 13px; font-weight: 700; color: #1e293b; }
.hdr-stats { display: flex; gap: 8px; }
.stat-item { font-size: 11px; font-weight: 600; padding: 2px 8px; border-radius: 10px; }
.stat-ok { background: rgba(52,211,153,0.12); color: var(--status-ok); }
.stat-warn { background: rgba(248,113,113,0.12); color: var(--status-alert); }

.btn-refresh {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  background: rgba(37,99,235,0.08);
  border: 1px solid rgba(37,99,235,0.2);
  border-radius: 6px;
  color: var(--primary);
  font-size: 12px;
  padding: 5px 12px;
  cursor: pointer;
  transition: all 0.15s;
}
.btn-refresh:hover:not(:disabled) { background: rgba(37,99,235,0.15); border-color: rgba(37,99,235,0.4); }
.btn-refresh:disabled { opacity: 0.4; cursor: not-allowed; }

/* Grid */
.sq-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
  gap: 8px;
}

/* Card */
.sq-card {
  background: rgba(15, 23, 42, 0.04);
  border: 1px solid rgba(15,23,42,0.07);
  border-radius: 8px;
  padding: 10px 12px;
  transition: all 0.15s;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.sq-card:hover { background: #e2e8f0; border-color: rgba(15,23,42,0.13); }
.sq-card.card-active { border-color: rgba(37,99,235,0.4); background: rgba(37,99,235,0.06); }
.sq-card.card-good { border-left: 3px solid currentColor; }
.sq-card.card-warn { border-left: 3px solid currentColor; }
.sq-card.card-bad { border-left: 3px solid currentColor; }
.sq-card { color: var(--cat-clr, var(--primary)); }

.card-top { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.card-cat { font-size: 12px; font-weight: 600; color: var(--text-3); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.card-pct { font-size: 14px; font-weight: 800; color: var(--text-3); font-family: ui-monospace, 'SF Mono', Consolas, 'Liberation Mono', monospace; flex-shrink: 0; }
.card-pct.pct-warn { color: var(--status-alert); }

.card-bar { height: 4px; background: rgba(15,23,42,0.07); border-radius: 2px; overflow: hidden; }
.bar-fill { height: 100%; border-radius: 2px; background: var(--status-ok); transition: width 0.5s ease; }
.card-warn .bar-fill { background: var(--status-warn); }
.card-bad .bar-fill { background: var(--status-alert); }

.card-btm { display: flex; align-items: center; justify-content: space-between; }
.card-count { font-size: 11px; color: var(--text-2, #475569); font-family: ui-monospace, 'SF Mono', Consolas, 'Liberation Mono', monospace; }
.card-actions { display: flex; gap: 4px; }

.btn-icon {
  width: 26px;
  height: 22px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 5px;
  font-size: 10px;
  font-weight: 700;
  cursor: pointer;
  transition: all 0.12s;
  border: 1px solid transparent;
}
.btn-sample {
  background: rgba(37,99,235,0.07);
  border-color: rgba(37,99,235,0.15);
  color: var(--primary);
}
.btn-sample:hover:not(:disabled) { background: rgba(37,99,235,0.16); }
.btn-sample.active { background: rgba(37,99,235,0.2); border-color: rgba(37,99,235,0.5); }
.btn-sample:disabled { opacity: 0.4; }
.btn-clean {
  background: rgba(52,211,153,0.06);
  border-color: rgba(52,211,153,0.15);
  color: var(--status-ok);
}
.btn-clean:hover:not(:disabled) { background: rgba(52,211,153,0.16); }
.btn-clean.done { color: var(--status-ok); }
.btn-clean:disabled { opacity: 0.4; }

/* Spinners */
.spinner { display: inline-block; width: 11px; height: 11px; border: 1.5px solid rgba(37,99,235,0.3); border-top-color: var(--primary); border-radius: 50%; animation: spin 0.65s linear infinite; }
.sp-xs { display: inline-block; width: 8px; height: 8px; border: 1.5px solid rgba(15,23,42,0.25); border-top-color: #fff; border-radius: 50%; animation: spin 0.65s linear infinite; }
@keyframes spin { to { transform: rotate(360deg); } }

/* Empty / Skeleton */
.sq-empty { font-size: 12px; color: var(--text-3, #94a3b8); text-align: center; padding: 16px; }
.sq-card.sk-card { pointer-events: none; }
.sk-line { background: #e2e8f0; border-radius: 3px; }
.sk-title { height: 14px; width: 55%; margin-bottom: 6px; }
.sk-count { height: 10px; width: 35%; }
.sk-bar { height: 4px; background: #e2e8f0; border-radius: 2px; margin-bottom: 6px; }

/* Toast */
.sq-toast { margin-top: 10px; padding: 8px 12px; background: rgba(37,99,235,0.08); border: 1px solid rgba(37,99,235,0.2); border-radius: 6px; color: var(--primary); font-size: 12px; }
.fade-enter-active, .fade-leave-active { transition: all 0.18s ease; }
.fade-enter-from, .fade-leave-to { opacity: 0; transform: translateY(-3px); }

/* Modal */
.sq-overlay { position: fixed; inset: 0; background: rgba(15,23,42,0.1); display: flex; align-items: center; justify-content: center; z-index: 200; }
.sq-confirm { display: flex; align-items: center; gap: 12px; background: var(--surface, #ffffff); border: 1px solid var(--surface-3, #e2e8f0); border-radius: 12px; padding: 20px 22px; max-width: 400px; box-shadow: var(--shadow-md, 0 2px 4px rgba(15,23,42,0.05)); }
.confirm-icon { font-size: 26px; flex-shrink: 0; }
.confirm-body { flex: 1; }
.confirm-title { font-size: 15px; font-weight: 700; color: #0f172a; margin-bottom: 6px; }
.confirm-msg { font-size: 12px; color: var(--text-3); line-height: 1.6; }
.confirm-btns { display: flex; gap: 8px; flex-shrink: 0; }
.btn-cancel { background: transparent; color: #475569; border: 1px solid var(--surface-3, #e2e8f0); border-radius: 7px; padding: 7px 16px; font-size: 12px; cursor: pointer; transition: all 0.12s; }
.btn-cancel:hover { background: var(--surface-2, #f1f5f9); color: var(--text-3); }
.btn-ok { background: linear-gradient(135deg, var(--primary), var(--primary-dark)); color: #fff; border: none; border-radius: 7px; padding: 7px 20px; font-size: 12px; font-weight: 600; cursor: pointer; box-shadow: 0 2px 8px rgba(37,99,235,0.3); transition: opacity 0.12s; }
.btn-ok:hover { opacity: 0.88; }
</style>