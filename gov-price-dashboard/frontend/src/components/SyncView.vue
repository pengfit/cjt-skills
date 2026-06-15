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
  color: #e2e8f0;
}

.sync-subtabs {
  display: flex;
  gap: 6px;
  padding: 14px 20px 0;
  border-bottom: 1px solid rgba(255, 255, 255, 0.05);
}

.sync-subtab {
  position: relative;
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 8px 16px;
  border: 1px solid rgba(255, 255, 255, 0.06);
  border-bottom: none;
  border-radius: 8px 8px 0 0;
  background: rgba(15, 23, 42, 0.4);
  color: #94a3b8;
  cursor: pointer;
  font-size: 13px;
  font-weight: 600;
  transition: all 0.18s;
}

.sync-subtab:hover {
  color: #e2e8f0;
  background: rgba(56, 189, 248, 0.06);
  border-color: rgba(56, 189, 248, 0.15);
}

.sync-subtab.active {
  color: #38bdf8;
  background: rgba(56, 189, 248, 0.1);
  border-color: rgba(56, 189, 248, 0.35);
  border-bottom-color: rgba(56, 189, 248, 0.1);
}

.sync-subtab-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: #475569;
  transition: all 0.2s;
}
.sync-subtab.active .sync-subtab-dot {
  background: #38bdf8;
  box-shadow: 0 0 6px rgba(56, 189, 248, 0.7);
}

.sync-subtab-hint {
  font-size: 11px;
  color: #64748b;
  font-weight: 400;
  margin-left: 4px;
}
.sync-subtab.active .sync-subtab-hint {
  color: #7dd3fc;
}
</style>
