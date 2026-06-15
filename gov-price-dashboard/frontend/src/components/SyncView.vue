<template>
  <div class="sync-page">
    <div class="sync-subtabs">
      <button class="sync-subtab" :class="{ active: subTab === 'scrape' }" @click="subTab = 'scrape'">
        <span class="sync-subtab-dot"></span>
        抓取任务
        <span class="sync-subtab-hint">各城市 ODS 抓取进度</span>
      </button>
      <button class="sync-subtab" :class="{ active: subTab === 'clean' }" @click="subTab = 'clean'">
        <span class="sync-subtab-dot"></span>
        数据清洗
        <span class="sync-subtab-hint">ODS → DWD → DWS 链路</span>
      </button>
    </div>

    <ScrapeView v-if="subTab === 'scrape'" />
    <DataProvenanceView v-else-if="subTab === 'clean'" />
  </div>
</template>

<script setup>
import { ref } from 'vue'
import ScrapeView from './ScrapeView.vue'
import DataProvenanceView from './DataProvenanceView.vue'

const subTab = ref('scrape')
</script>

<style scoped>
.sync-page {
  padding: 0;
  min-height: 100vh;
  color: var(--text);
}

.sync-subtabs {
  display: flex;
  gap: 4px;
  padding: 14px 20px 0;
  border-bottom: 1px solid var(--border);
}

.sync-subtab {
  position: relative;
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 9px 18px;
  border: 1px solid transparent;
  border-bottom: none;
  border-radius: 8px 8px 0 0;
  background: transparent;
  color: var(--text-2);
  cursor: pointer;
  font-size: 13px;
  font-weight: 600;
  transition: all 0.18s;
}

.sync-subtab:hover {
  color: var(--text);
  background: var(--surface-2);
  border-color: var(--border);
}

.sync-subtab.active {
  color: var(--primary);
  background: var(--surface);
  border-color: var(--border);
  border-bottom-color: var(--surface);
  margin-bottom: -1px;
}

.sync-subtab-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--text-3);
  transition: all 0.2s;
}
.sync-subtab.active .sync-subtab-dot {
  background: var(--primary);
  box-shadow: 0 0 0 3px rgba(37,99,235,0.18);
}

.sync-subtab-hint {
  font-size: 11px;
  color: var(--text-3);
  font-weight: 400;
  margin-left: 4px;
}
.sync-subtab.active .sync-subtab-hint {
  color: var(--primary-light, var(--primary));
}
</style>
