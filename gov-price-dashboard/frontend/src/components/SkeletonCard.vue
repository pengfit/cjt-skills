<template>
  <div class="skeleton-card" :class="{ 'is-row': row }">
    <div v-if="!hideHeader" class="skel skel-line" style="width: 30%; height: 14px; margin-bottom: 14px;" />
    <div v-if="!hideHeader" class="skel skel-line" style="width: 50%; height: 22px; margin-bottom: 20px;" />
    <div v-for="i in lines" :key="i" class="skel skel-line"
      :style="{
        width: (60 + Math.random() * 35) + '%',
        height: (10 + Math.random() * 6) + 'px',
        marginBottom: '10px',
      }" />
    <div v-if="!hideFooter" class="skel skel-block" style="width: 100%; height: 80px; margin-top: 14px;" />
  </div>
</template>

<script setup>
defineProps({
  lines: { type: Number, default: 4 },
  hideHeader: { type: Boolean, default: false },
  hideFooter: { type: Boolean, default: false },
  row: { type: Boolean, default: false },
})
</script>

<style scoped>
.skeleton-card {
  background: #f8fafc;
  border: 1px solid #e2e8f0;
  border-radius: 10px;
  padding: 16px;
}

.skel {
  background: linear-gradient(
    90deg,
    #e2e8f0 0%,
    #f1f5f9 50%,
    #e2e8f0 100%
  );
  background-size: 200% 100%;
  animation: skel-shimmer 1.4s linear infinite;
  border-radius: 4px;
  display: block;
}

@keyframes skel-shimmer {
  0%   { background-position: 200% 0; }
  100% { background-position: -200% 0; }
}

.is-row {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 16px;
}
.is-row .skel-line { margin-bottom: 0 !important; }
</style>
