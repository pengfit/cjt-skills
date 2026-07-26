import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { readFileSync, writeFileSync, mkdirSync, existsSync } from 'node:fs'
import { resolve, dirname } from 'node:path'
import { fileURLToPath } from 'node:url'

// 2026-07-26 #SEO: build 期抓 ES + GitHub,产出 build-meta.json + 各路由静态 HTML
//   不依赖 Python/Puppeteer,Docker Node 20-alpine 原生 fetch 即可
const __dirname = dirname(fileURLToPath(import.meta.url))
const FRONTEND = __dirname
const PROJECT_ROOT = resolve(FRONTEND, '..', '..')
const PUBLIC_DIR = resolve(FRONTEND, 'public')
const BUILD_META_PATH = resolve(PUBLIC_DIR, 'build-meta.json')
const ES_HOST = process.env.ES_HOST || 'http://localhost:59200'
const SITE_URL = process.env.SITE_URL || 'https://pengfit.cn'
const GH_REPO = process.env.SEO_GH_REPO || 'pengfit/cjt-skills'
const FETCH_TIMEOUT_MS = 8000

const FALLBACK_META = {
  total_records: 0,
  breeds_count: 0,
  cities_count: 0,
  latest_period_end: '2026-06-30',
  github_stars: 'N/A',
  github_url: `https://github.com/${GH_REPO}`,
  cities_count_label: '17 城',
  breeds_count_label: '9,900+ 跨城归一品类',
  total_records_label: '80 万+ 条材料数据',
}

// —— fetch helpers ——
async function _fetchJson(url, opts = {}) {
  const ctrl = new AbortController()
  const t = setTimeout(() => ctrl.abort(), FETCH_TIMEOUT_MS)
  try {
    const r = await fetch(url, { ...opts, signal: ctrl.signal, headers: { 'User-Agent': 'cjt-build-seo/1.0', ...(opts.headers || {}) } })
    if (!r.ok) return null
    return await r.json()
  } catch (e) {
    console.warn(`[seo] fetch ${url} failed:`, e.message)
    return null
  } finally {
    clearTimeout(t)
  }
}

async function fetchNormStats() {
  const cat = await _fetchJson(`${ES_HOST}/_cat/indices/norm_*_price?format=json`)
  const normList = (cat || []).map((r) => r.index).filter(Boolean)
  if (!normList.length) return {}

  let total = 0
  for (const idx of normList) {
    const c = await _fetchJson(`${ES_HOST}/${idx}/_count`)
    if (c && typeof c.count === 'number') total += c.count
  }
  if (!total) return {}

  const agg = await _fetchJson(`${ES_HOST}/${normList.join(',')}/_search`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      size: 0,
      aggs: {
        cities: { cardinality: { field: 'city' } },
        breeds: { cardinality: { field: 'normalized_breed.keyword' } },
        max_period: { max: { field: 'period_end' } },
      },
    }),
  })
  const aggs = (agg || {}).aggregations || {}
  return {
    total_records: total,
    cities_count: Math.round(aggs.cities?.value || 0),
    breeds_count: Math.round(aggs.breeds?.value || 0),
    latest_period_end_ms: Math.round(aggs.max_period?.value || 0),
  }
}

async function fetchGhStars() {
  const info = await _fetchJson(`https://api.github.com/repos/${GH_REPO}`)
  if (!info) return { github_stars: 'N/A', github_url: `https://github.com/${GH_REPO}` }
  return {
    github_stars: info.stargazers_count ?? 'N/A',
    github_url: info.html_url || `https://github.com/${GH_REPO}`,
    github_forks: info.forks_count || 0,
    github_description: info.description || '',
  }
}

function msToIsoDate(ms) {
  if (!ms) return ''
  try { return new Date(ms).toISOString().slice(0, 10) } catch { return '' }
}

async function buildBuildMeta() {
  const fallback = (() => {
    if (existsSync(BUILD_META_PATH)) {
      try { return JSON.parse(readFileSync(BUILD_META_PATH, 'utf-8')) } catch {}
    }
    return FALLBACK_META
  })()
  const [norm, gh] = await Promise.all([fetchNormStats().catch(() => ({})), fetchGhStars().catch(() => ({}))])
  const merged = { ...fallback, ...norm, ...gh }
  if (norm.latest_period_end_ms) merged.latest_period_end = msToIsoDate(norm.latest_period_end_ms)
  merged.generated_at = new Date().toISOString()
  merged.repo_url = merged.github_url || `https://github.com/${GH_REPO}`
  merged.cities_count_label = `${merged.cities_count || '17'} 城`
  merged.breeds_count_label = `${(merged.breeds_count || 0).toLocaleString()} 跨城归一品类`
  merged.total_records_label = `${(merged.total_records || 0).toLocaleString()} 条材料数据`
  mkdirSync(dirname(BUILD_META_PATH), { recursive: true })
  writeFileSync(BUILD_META_PATH, JSON.stringify(merged, null, 2), 'utf-8')
  console.log(`[seo] build-meta.json written: stars=${merged.github_stars} cities=${merged.cities_count} breeds=${merged.breeds_count} records=${merged.total_records}`)
  return merged
}

// —— route-specific meta patcher ——
const ROUTES = {
  '': {
    title: '材价通 · 工程造价材料价格数据 · 17 城住建局官方期刊 · cjt-skills',
    description: '材价通 (cjt-skills) · 17 城住建局官方造价信息期刊 · 钢筋 / 水泥 / 给水管 / 电缆 等工程造价材料价格数据 · 跨城归一 · 公开免费 · AI 协作的一人公司实践',
    keywords: '工程造价, 材料价格, 材价通, cjt-skills, 住建局, 钢筋价格, 水泥价格, 给水管价格, 电缆价格, 政府数据, 数据可视化, 一人公司, OPC, AI, 跨城归一, 公开数据, FastAPI, Vue',
    og_title: '材价通 · 工程造价材料价格数据 · 17 城住建局官方期刊',
    og_desc: '17 城住建局官方造价信息期刊 · 钢筋/水泥/给水管/电缆等材料价格 · 跨城归一 · 公开免费 · AI 协作',
    canonical: '/',
    ld_kind: 'home',
  },
  home: {
    title: '材价通 · 工程造价材料价格数据 · 17 城住建局官方期刊 · cjt-skills',
    description: '材价通 (cjt-skills) · 17 城住建局官方造价信息期刊 · 钢筋 / 水泥 / 给水管 / 电缆 等工程造价材料价格数据 · 跨城归一 · 公开免费 · AI 协作的一人公司实践',
    keywords: '工程造价, 材料价格, 材价通, cjt-skills, 住建局, 钢筋价格, 水泥价格, 给水管价格, 电缆价格, 政府数据, 数据可视化, 一人公司, OPC, AI, 跨城归一, 公开数据, FastAPI, Vue',
    og_title: '材价通 · 工程造价材料价格数据 · 17 城住建局官方期刊',
    og_desc: '17 城住建局官方造价信息期刊 · 钢筋/水泥/给水管/电缆等材料价格 · 跨城归一 · 公开免费 · AI 协作',
    canonical: '/home',
    ld_kind: 'home',
  },
  market: {
    title: '材料价格行情 · 钢筋/水泥/给水管/电缆 跨城实时价格 · 材价通',
    description: '全国 20 城建材市场行情 · 钢筋 / 水泥 / 给水管 / 电缆 等工程造价材料跨城归一价格 · 住建局官方期刊 · 涨跌幅追踪 · 公开免费 · 材价通 cjt-skills',
    keywords: '材料价格行情, 钢筋价格, 水泥价格, 给水管价格, 电缆价格, 建材市场, 工程造价, 跨城价格对比, 涨跌幅, 住建局, 材价通, cjt-skills',
    og_title: '材料价格行情 · 钢筋/水泥/给水管/电缆 跨城实时价格 · 材价通',
    og_desc: '全国 20 城住建局官方造价信息 · 钢筋/水泥/给水管/电缆跨城归一价格 · 涨跌幅追踪',
    canonical: '/market',
    ld_kind: 'market',
  },
}

function buildJsonLd(kind, meta) {
  const org = {
    '@type': 'Organization',
    '@id': `${SITE_URL}/#organization`,
    name: 'Pengfit',
    url: 'https://github.com/pengfit/cjt-skills',
    logo: `${SITE_URL}/favicon.svg`,
  }
  if (kind === 'market') {
    return JSON.stringify({
      '@context': 'https://schema.org',
      '@type': 'Dataset',
      name: '材价通 · 工程造价材料价格数据 · 17 城住建局官方期刊',
      description: `${meta.cities_count || 17} 城住建局官方造价信息 · 跨城归一品类 ${(meta.breeds_count || 9900).toLocaleString()} · 钢筋/水泥/给水管/电缆价格行情`,
      url: `${SITE_URL}/market`,
      inLanguage: 'zh-CN',
      license: 'https://opensource.org/licenses/MIT',
      isAccessibleForFree: true,
      keywords: ['工程造价', '材料价格', '钢筋价格', '水泥价格', '给水管价格', '电缆价格', '住建局', '政府数据', '跨城归一'],
      spatialCoverage: { '@type': 'Place', name: '中华人民共和国' },
      temporalCoverage: '2024-01-01/..',
      provider: { '@type': 'Organization', name: 'Pengfit', url: 'https://github.com/pengfit/cjt-skills' },
      distribution: {
        '@type': 'DataDownload',
        encodingFormat: 'application/json',
        contentUrl: `${SITE_URL}/api/market/overview`,
        license: 'https://opensource.org/licenses/MIT',
      },
    }, null, 0)
  }
  return JSON.stringify({
    '@context': 'https://schema.org',
    '@graph': [
      org,
      {
        '@type': 'WebSite',
        '@id': `${SITE_URL}/#website`,
        url: `${SITE_URL}/`,
        name: '材价通 · cjt-skills',
        alternateName: 'cjt-skills Dashboard',
        inLanguage: 'zh-CN',
        description: '17 城住建局官方造价信息期刊 · 跨城归一材料价格数据 · 公开免费 · AI 协作',
        publisher: { '@id': `${SITE_URL}/#organization` },
        potentialAction: {
          '@type': 'SearchAction',
          target: { '@type': 'EntryPoint', urlTemplate: `${SITE_URL}/market?q={search_term_string}` },
          'query-input': 'required name=search_term_string',
        },
      },
      {
        '@type': 'SoftwareApplication',
        name: '材价通 / cjt-skills',
        applicationCategory: 'BusinessApplication',
        applicationSubCategory: '工程材料价格数据可视化',
        operatingSystem: 'Web',
        url: `${SITE_URL}/`,
        description: `${meta.cities_count || 17} 城住建局官方造价信息期刊 · ${(meta.total_records || 0).toLocaleString()} 条材料数据 · 跨城归一品类 ${(meta.breeds_count || 9900).toLocaleString()}`,
        offers: { '@type': 'Offer', price: '0', priceCurrency: 'CNY', availability: 'https://schema.org/InStock' },
        publisher: { '@id': `${SITE_URL}/#organization` },
        inLanguage: 'zh-CN',
        featureList: [
          '17 城住建局官方造价信息期刊数据',
          '跨城归一品类 9,000+',
          '钢筋/水泥/给水管/电缆价格行情',
          'AI 协作规格解析',
          '公开免费',
        ],
      },
    ],
  }, null, 0)
}

function patchHtml(html, cfg, meta) {
  let out = html
  const canonical = `${SITE_URL}${cfg.canonical}`
  out = out.replace(/<title>[^<]*<\/title>/, `<title>${cfg.title}</title>`)
  out = out.replace(/<meta\s+name="description"\s+content="[^"]*"\s*\/>/, `<meta name="description" content="${cfg.description}" />`)
  out = out.replace(/<meta\s+name="keywords"\s+content="[^"]*"\s*\/>/, `<meta name="keywords" content="${cfg.keywords}" />`)
  out = out.replace(/<meta\s+property="og:title"\s+content="[^"]*"\s*\/>/, `<meta property="og:title" content="${cfg.og_title}" />`)
  out = out.replace(/<meta\s+property="og:description"\s+content="[^"]*"\s*\/>/, `<meta property="og:description" content="${cfg.og_desc}" />`)
  out = out.replace(/<meta\s+property="og:url"\s+content="[^"]*"\s*\/>/, `<meta property="og:url" content="${canonical}" />`)
  out = out.replace(/<meta\s+name="twitter:title"\s+content="[^"]*"\s*\/>/, `<meta name="twitter:title" content="${cfg.og_title}" />`)
  out = out.replace(/<meta\s+name="twitter:description"\s+content="[^"]*"\s*\/>/, `<meta name="twitter:description" content="${cfg.og_desc}" />`)
  out = out.replace(/<link\s+rel="canonical"\s+href="[^"]*"\s*\/>/, `<link rel="canonical" href="${canonical}" />`)
  // 替换默认 JSON-LD(第一个 script[type="application/ld+json"])
  const ld = buildJsonLd(cfg.ld_kind, meta)
  out = out.replace(/<script\s+type="application\/ld\+json">[\s\S]*?<\/script>/, `<script type="application/ld+json">\n${ld}\n    </script>`)
  return out
}

// —— Vite 插件:seo-build ——
function seoBuildPlugin() {
  let meta = FALLBACK_META
  return {
    name: 'cjt-seo-build',
    async buildStart() {
      meta = await buildBuildMeta()
    },
    transformIndexHtml: {
      order: 'pre',
      handler(html) {
        // 替换 index.html 里的占位符 {{...}} 让默认 HTML 也带真实数字
        return html
          .replace(/\{\{TOTAL_RECORDS_LABEL\}\}/g, meta.total_records_label)
          .replace(/\{\{BREEDS_COUNT_LABEL\}\}/g, meta.breeds_count_label)
          .replace(/\{\{CITIES_COUNT_LABEL\}\}/g, meta.cities_count_label)
          .replace(/\{\{LATEST_PERIOD_END\}\}/g, meta.latest_period_end || '')
          .replace(/\{\{GITHUB_STARS\}\}/g, String(meta.github_stars))
      },
    },
    // closeBundle 在所有资源写完后跑,生成各路由静态 HTML
    closeBundle() {
      const distIndex = resolve(FRONTEND, 'dist', 'index.html')
      if (!existsSync(distIndex)) {
        console.warn('[seo] dist/index.html 不存在,跳过路由化')
        return
      }
      const src = readFileSync(distIndex, 'utf-8')
      for (const [routeKey, cfg] of Object.entries(ROUTES)) {
        const target = routeKey === '' ? distIndex : resolve(FRONTEND, 'dist', routeKey, 'index.html')
        if (routeKey !== '') mkdirSync(dirname(target), { recursive: true })
        const patched = patchHtml(src, cfg, meta)
        writeFileSync(target, patched, 'utf-8')
        console.log(`[seo] wrote ${target.replace(FRONTEND + '/', '')}`)
      }
    },
  }
}

// https://vite.dev/config/
export default defineConfig({
  plugins: [vue(), seoBuildPlugin()],
  server: {
    host: true,  // 2026-07-20 19:21 修: 监听所有接口 (含 IPv4 127.0.0.1); 默认只监听 localhost (IPv6 ::1) 让 127.0.0.1 连不上
    port: 5300,
    allowedHosts: true,  // 2026-07-20 19:21 修: 白名单全开 (配合 host: true)
    proxy: {
      '/api': {
        target: 'http://localhost:5200',
        changeOrigin: true,
      },
    },
  },
  build: {
    sourcemap: false,
    chunkSizeWarningLimit: 1200,
  },
})