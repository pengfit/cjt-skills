<!--
  ShowcaseView.vue (2026-07-19 改造)

  对外展示首页 - 数据可视化风
  路径:/index (公开访问,不鉴权)

  2026-07-19 改造为**静态页面**(道友要求):
    - 删除 fetch /api/showcase/stats,数据全部硬编码
    - 删除 loading / error 状态机(数据写死,不存在加载过程)
    - 不再调用 useApi / useAuth 等 composable

  数据来源:2026-07-19 19 时最后一次真实拉取,定稿。
  若数据过期,直接改下面的 STATS 对象即可,无需重启后端。
-->
<template>
  <div class="showcase">
    <ShowcaseNav />
    <main class="showcase-main">
      <ShowcaseHero />
      <ShowcaseInsight />
      <ShowcaseWorkspace />
      <ShowcaseArchitecture />
      <ShowcaseMap :grouped="stats.provinces_grouped" />
      <ShowcaseGallery />
    </main>
    <ShowcaseFooter />
  </div>
</template>

<script setup>
import { provide } from 'vue'
import ShowcaseNav from './showcase/ShowcaseNav.vue'
import ShowcaseHero from './showcase/ShowcaseHero.vue'
import ShowcaseInsight from './showcase/ShowcaseInsight.vue'
import ShowcaseMetrics from './showcase/ShowcaseMetrics.vue'
import ShowcaseWorkspace from './showcase/ShowcaseWorkspace.vue'
import ShowcaseArchitecture from './showcase/ShowcaseArchitecture.vue'
import ShowcaseGallery from './showcase/ShowcaseGallery.vue'
import ShowcaseFooter from './showcase/ShowcaseFooter.vue'
import ShowcaseMap from './showcase/ShowcaseMap.vue'

// ── 静态数据(写死)──
// 数据时间:2026-07-19,来源 /api/showcase/stats 最后一次快照
// breeds_count 改为从 breed_canonical.db 统计 normalized_breed 去重数(2026-07-19)
// 改这里就改首页,不动后端、不动容器
const stats = {
  cities_count: 20,
  provinces_count: 15,
  dws_total: 788525,
  dwd_total: 869441,
  ods_total: 907316,
  norm_total: 788525,
  total_records: 788525,
  breeds_count: 9931,
  categories_count: 9,
  storage_mb: 573.1,
  latest_update: '2026-07-31',
  provinces_grouped: [
    { name: '内蒙古', cities: [
      { key: 'huhehaote', label: '呼和浩特', latest: '2026-02-28', count: 1803 },
    ]},
    { name: '吉林', cities: [
      { key: 'jilin', label: '吉林', latest: '2026-07-31', count: 5124 },
    ]},
    { name: '四川', cities: [
      { key: 'sichuan', label: '四川', latest: '2026-05-31', count: 421345 },
    ]},
    { name: '宁夏', cities: [
      { key: 'ningxia', label: '宁夏', latest: '2026-06-30', count: 7747 },
    ]},
    { name: '山东', cities: [
      { key: 'weihai', label: '威海', latest: '2026-03-31', count: 818 },
      { key: 'rizhao', label: '日照', latest: '2026-05-31', count: 4973 },
      { key: 'jinan', label: '济南', latest: '2026-05-31', count: 24487 },
      { key: 'heze', label: '菏泽', latest: '2026-01-31', count: 868 },
      { key: 'qingdao', label: '青岛', latest: '2026-06-30', count: 1307 },
    ]},
    { name: '山西', cities: [
      { key: 'shanxi', label: '山西', latest: '2026-04-30', count: 11436 },
    ]},
    { name: '新疆', cities: [
      { key: 'xinjiang', label: '新疆', latest: '2026-05-31', count: 100990 },
    ]},
    { name: '江西', cities: [
      { key: 'jiangxi', label: '江西', latest: '2026-07-31', count: 45579 },
    ]},
    { name: '河南', cities: [
      { key: 'henan', label: '河南', latest: '2026-04-30', count: 8234 },
    ]},
    { name: '海南', cities: [
      { key: 'hainan', label: '海南', latest: '2026-04-30', count: 12278 },
    ]},
    { name: '湖南', cities: [
      { key: 'hunan', label: '湖南', latest: '2026-04-30', count: 2282 },
    ]},
    { name: '贵州', cities: [
      { key: 'guizhou', label: '贵州', latest: '2026-06-30', count: 17072 },
    ]},
    { name: '重庆', cities: [
      { key: 'chongqing', label: '重庆', latest: '2026-05-31', count: 8578 },
    ]},
    { name: '陕西', cities: [
      { key: 'xian', label: '西安', latest: '2026-06-30', count: 69654 },
      { key: 'shaanxi', label: '陕西', latest: '2026-06-30', count: 33475 },
    ]},
    { name: '青海', cities: [
      { key: 'qinghai', label: '青海', latest: '2026-06-30', count: 10475 },
    ]},
  ],
}

// 给 Hero 提供数据(它用 inject,而不是 props)
provide('stats', stats)
</script>

<style scoped>
.showcase {
  min-height: 100vh;
  background: var(--bg);
  color: var(--text);
  font-family: var(--font-sans);
  display: flex;
  flex-direction: column;
}

.showcase-main {
  flex: 1;
  width: 100%;
  max-width: 1200px;
  margin: 0 auto;
  padding: 0 32px;
}
</style>
