<template>
  <div class="ss-panel">
    <!-- Header -->
    <div class="ss-hdr">
      <div class="ss-hdr-left">
        <span class="dot-cyan"></span>
        <span class="hdr-title">抽样详情</span>
        <span class="ss-badge">{{ samples.length }}</span>
        <span class="ss-cat">{{ activeCat }}</span>
        <span v-if="sampleMsg" class="ss-tip">{{ sampleMsg }}</span>
      </div>
      <button class="btn-close" @click="$emit('close')">✕</button>
    </div>

    <!-- Loading skeleton -->
    <div v-if="loading" class="ss-grid">
      <div v-for="i in 8" :key="i" class="ss-card sk-card">
        <div class="sk-line sk-spec"></div>
        <div class="sk-line sk-meta"></div>
      </div>
    </div>

    <!-- Sample cards -->
    <div v-else class="ss-grid">
      <div
        v-for="s in samples"
        :key="s.spec + s.breed"
        class="ss-card"
        :class="s.has_attr ? 'ss-ok' : 'ss-empty'"
        style="cursor:pointer"
        @click="$emit('fix', s)"
      >
        <div class="ss-top">
          <span class="ss-spec" :title="s.spec">{{ s.spec }}</span>
          <span v-if="s.has_attr" class="ss-status s-ok">✓</span>
        </div>
        <div class="ss-meta">
          <span class="ss-breed">{{ s.breed || s.category }}</span>
          <span v-if="s.attr_keys?.length" class="ss-attrs">
            <span v-for="k in s.attr_keys.slice(0,4)" :key="k" class="ss-attr">{{ k }}</span>
          </span>
        </div>
      </div>
    </div>

    <!-- Empty -->
    <div v-if="!loading && !samples.length" class="ss-empty">暂无抽样数据</div>
  </div>
</template>

<script setup>
defineProps({
  samples: { type: Array, default: () => [] },
  activeCat: { type: String, default: '' },
  loading: { type: Boolean, default: false },
  sampleMsg: { type: String, default: '' },
})
defineEmits(['close', 'fix'])
</script>

<style scoped>
.ss-panel {
  background: rgba(15,23,42,0.82);
  border: 1px solid rgba(255,255,255,0.07);
  border-radius: 12px;
  padding: 14px;
  position: relative;
  overflow: hidden;
}

/* Header */
.ss-hdr {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 14px;
  gap: 10px;
}
.ss-hdr-left { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.dot-cyan { width: 8px; height: 8px; border-radius: 50%; background: #38bdf8; flex-shrink: 0; }
.hdr-title { font-size: 14px; font-weight: 700; color: #f1f5f9; }
.ss-badge {
  font-size: 11px;
  background: rgba(56,189,248,0.12);
  color: #38bdf8;
  border-radius: 8px;
  padding: 1px 8px;
  font-weight: 600;
}
.ss-cat { font-size: 13px; font-weight: 700; color: #38bdf8; }
.ss-tip { font-size: 11px; color: #475569; }

.btn-close {
  background: transparent;
  border: none;
  color: #475569;
  font-size: 14px;
  cursor: pointer;
  padding: 2px 8px;
  border-radius: 4px;
  transition: color 0.12s;
  flex-shrink: 0;
}
.btn-close:hover { color: #94a3b8; }

/* Grid */
.ss-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(160px, 1fr));
  gap: 8px;
}

/* Card */
.ss-card {
  background: rgba(255,255,255,0.04);
  border: 1px solid rgba(255,255,255,0.08);
  border-radius: 8px;
  padding: 11px 13px;
  display: flex;
  flex-direction: column;
  gap: 6px;
  transition: background 0.12s;
}
.ss-card:hover { background: rgba(255,255,255,0.07); }
.ss-card.ss-ok { border-left: 3px solid #22c55e; }
.ss-card.ss-empty { border-left: 3px solid rgba(248,113,113,0.5); }

.ss-top { display: flex; align-items: flex-start; justify-content: space-between; gap: 5px; }
.ss-spec {
  font-family: 'Courier New', monospace;
  font-size: 13px;
  color: #e2e8f0;
  word-break: break-all;
  flex: 1;
  line-height: 1.45;
}
.ss-status { font-size: 10px; font-weight: 700; padding: 1px 6px; border-radius: 3px; flex-shrink: 0; }
.s-ok { background: rgba(34,197,94,0.15); color: #22c55e; }
.s-empty { background: rgba(248,113,113,0.12); color: #f87171; }

.ss-meta {
  font-size: 11px;
  color: #64748b;
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}
.ss-breed { color: #94a3b8; flex-shrink: 0; }
.ss-attrs { display: flex; gap: 3px; flex-wrap: wrap; }
.ss-attr {
  background: rgba(56,189,248,0.08);
  color: #7dd3fc;
  border: 1px solid rgba(56,189,248,0.15);
  border-radius: 3px;
  padding: 0 5px;
  font-size: 10px;
}


/* Skeleton */
.ss-card.sk-card { pointer-events: none; }
.sk-line { background: rgba(255,255,255,0.05); border-radius: 3px; }
.sk-spec { height: 12px; width: 70%; margin-bottom: 6px; }
.sk-meta { height: 10px; width: 40%; }

/* Empty */
.ss-empty { font-size: 12px; color: #334155; text-align: center; padding: 16px; }
</style>