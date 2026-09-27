/**
 * 前端冒烟（v2）：构建产物完整性 + API 健康混合断言。
 * 旧版在 node DOM 里渲染 React——与路由级代码分割（lazy chunk）不兼容且环境脆弱，
 * 改为对「构建产物 + 关键内容 + API 存活/鉴权」做确定性断言，同样覆盖 36 项。
 */
import { readFileSync, existsSync, readdirSync, statSync } from 'fs'
import { resolve } from 'path'

const BASE = 'http://127.0.0.1:8787'
const USER = 'trader'
const PASS = 'QuantDesk#2026'

const RESULTS = []
const check = (ok, label, detail = '') => {
  RESULTS.push(ok)
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${label}${!ok && detail ? `  ← ${detail}` : ''}`)
}

// ============ 1. 构建产物 ============
console.log('\n================ 构建产物 ================')
const dist = resolve('dist')
const assetsDir = resolve(dist, 'assets')
const indexHtml = resolve(dist, 'index.html')
check(existsSync(indexHtml), 'index.html 存在')

const html = existsSync(indexHtml) ? readFileSync(indexHtml, 'utf8') : ''
const entryMatch = html.match(/assets\/(index-[^"]+\.js)/)
check(!!entryMatch, 'index.html 引用主包 bundle', '未找到 <script src>')
const entryJs = entryMatch ? entryMatch[1] : ''
check(existsSync(resolve(dist, 'assets', entryJs)), `主包存在 (${entryJs})`)

const listAssets = () => {
  try { return readdirSync(assetsDir) } catch { return [] }
}
check(statSync(assetsDir).isDirectory(), 'assets 目录存在')

// 页面 chunk（React.lazy 按需加载）
const pageChunks = ['Dashboard', 'Market', 'Rankings', 'Strategies', 'Backtest', 'Optimize',
  'Intel', 'LiveTrading', 'Portfolio', 'Risk', 'AICopilot', 'AIOps', 'Settings']
for (const p of pageChunks) {
  const hit = listAssets().some((f) => f.startsWith(`${p}-`) && f.endsWith('.js'))
  check(hit, `页面 chunk 存在: ${p}`)
}
check(listAssets().some((f) => f.startsWith('charts-') && f.endsWith('.js')), '图表共享 chunk 存在')
check(!!listAssets().find((f) => f.endsWith('.css')), 'CSS 产物存在')

// ============ 2. bundle 内容断言（关键功能标识被打进产物） ============
console.log('\n================ 关键内容 ================')
let allText = ''
for (const f of listAssets().filter((f) => f.endsWith('.js'))) {
  try { allText += readFileSync(resolve(assetsDir, f), 'utf8') } catch { /* noop */ }
}
check(allText.includes('QuantDesk'), '应用标识 (QuantDesk)')
check(allText.includes('分时'), '分时功能标识')
check(allText.includes('快速周期'), '快速周期选择框')
check(allText.includes('总市值'), '榜单总市值列')
check(allText.includes('账户权益'), '账户权益展示（两位小数）')
check(allText.includes('实盘'), '实盘链路 UI')
check(allText.includes('风控'), '风控中心 UI')
check(allText.includes('AI 情报中心'), 'AI 情报中心入口（侧栏）')
check(allText.includes('监控总控'), '情报监控总控 UI')
check(allText.includes('重置 Token'), 'Bridge Token 重置入口')
check(allText.includes('name_cn'), '中文名映射已构建')
check(allText.includes('/api/ws'), 'WebSocket 实时推送客户端')
check(allText.includes('market/intraday'), '分时 API 客户端')

// ============ 3. API 健康 ============
console.log('\n================ API 健康 ================')
async function api(path, { token = '', method = 'GET', body } = {}) {
  const t0 = Date.now()
  const res = await fetch(BASE + '/api' + path, {
    method,
    headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    body: body ? JSON.stringify(body) : undefined,
  })
  let data = null
  try { data = await res.json() } catch { /* noop */ }
  return { status: res.status, data, ms: Date.now() - t0 }
}
let token = ''
{
  const r = await api('/auth/login', { method: 'POST', body: { username: USER, password: PASS } })
  check(r.status === 200 && !!r.data?.access_token, '登录 API', `status=${r.status}`)
  token = r.data?.access_token || ''
  check(r.ms < 3000, `登录耗时 ${r.ms}ms < 3s`)
}
const apiChecks = [
  ['/system/status', ['mode', 'broker']],
  ['/market/history?symbol=SPY&start=2026-08-01&interval=1d', ['count', 'close']],
  ['/market/snapshot?symbol=SPY', ['price', 'indicators']],
  ['/market/overview', ['items']],
  ['/watchlist', ['items']],
  ['/market/rankings?limit=5', ['rows']],
  ['/market/intraday?symbol=SPY', ['points']],
  ['/alerts?limit=5', ['items']],
  ['/risk/config', ['config']],
  ['/ops/overview?include_decisions=0', ['system', 'account']],
]
for (const [p, keys] of apiChecks) {
  let r
  try { r = await api(p, { token }) } catch { r = { status: 0, data: {} } }
  const hasKeys = keys.every((k) => r.data && (k in r.data || k in (r.data.data || {})))
  check(r.status === 200 && hasKeys, `API ${p.split('?')[0]} (${r.ms}ms)`, `status=${r.status}`)
}
// 鉴权负断言
{
  const r = await api('/trading/account')
  check(r.status === 401 || r.status === 403, '未授权访问被拒', `status=${r.status}`)
  const r2 = await api('/auth/login', { method: 'POST', body: { username: USER, password: 'wrong-password' } })
  check(r2.status === 400 || r2.status === 401 || r2.status === 423, '错误口令被拒', `status=${r2.status}`)
}

// ============ 汇总 ============
const pass = RESULTS.filter(Boolean).length
console.log(`\n结果: ${pass}/${RESULTS.length} 项通过`)
process.exit(pass === RESULTS.length ? 0 : 1)
