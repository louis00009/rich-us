/**
 * 真实浏览器视觉回归 —— Settings「数据与缓存」页（含 TwelveData 多 Key 池）
 * ==========================================================================
 * 与 visual-check.mjs 同源（CDP 驱动真实 Chrome，零依赖），但**专测设置页**：
 * SSR（renderToString）只能证明「不白屏 + 文案进了 DOM」，看不见：
 *   1) 控件宽度是否被 `.inp { @apply w-full }` 吃掉（本项目踩过两次的坑）；
 *   2) 密钥列表是否真的渲染出掩码/额度条；
 *   3) 浏览器控制台有没有报错。
 *
 * 用法：
 *   node scripts/visual-check-settings.mjs http://127.0.0.1:8787/settings <token> [截图目录]
 * 退出码 0 = 全部通过。
 */
import { spawn } from 'node:child_process'
import { existsSync, mkdirSync, writeFileSync } from 'node:fs'
import { join } from 'node:path'

import { resolveDebugPort } from './cdp-port.mjs'

const [, , URL_ARG, TOKEN, OUTDIR = 'node_modules/.cache/qd-visual'] = process.argv
if (!URL_ARG || !TOKEN) {
  console.error('用法: node scripts/visual-check-settings.mjs <url> <token> [截图目录]')
  process.exit(2)
}

const DEBUG_PORT = await resolveDebugPort()
const CDP_BASE = `http://127.0.0.1:${DEBUG_PORT}`
const PROFILE = join(process.cwd(), 'node_modules/.cache/qd-visual-profile-settings')
const sleep = (ms) => new Promise((r) => setTimeout(r, ms))

const CHROME_CANDIDATES = [
  process.env.QD_CHROME,
  'C:/Program Files/Google/Chrome/Application/chrome.exe',
  'C:/Program Files (x86)/Google/Chrome/Application/chrome.exe',
  'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
  'C:/Program Files/Microsoft/Edge/Application/msedge.exe',
].filter(Boolean)
const chromePath = CHROME_CANDIDATES.find((p) => existsSync(p))
if (!chromePath) {
  console.error('找不到 Chrome/Edge，可用 QD_CHROME 指定可执行文件路径')
  process.exit(2)
}

const results = []
const check = (ok, label, detail = '') => {
  results.push(ok)
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${label}${!ok && detail ? `  ← ${detail}` : ''}`)
}
mkdirSync(OUTDIR, { recursive: true })

const chrome = spawn(
  chromePath,
  [
    '--headless=new',
    `--remote-debugging-port=${DEBUG_PORT}`,
    `--user-data-dir=${PROFILE}`,
    '--no-first-run',
    '--no-default-browser-check',
    '--disable-gpu',
    '--hide-scrollbars',
    '--window-size=1680,1400',
    'about:blank',
  ],
  { stdio: 'ignore', detached: false },
)

let ws
try {
  let target
  for (let i = 0; i < 40 && !target; i++) {
    await sleep(500)
    try {
      const list = await (await fetch(`${CDP_BASE}/json/list`)).json()
      target = list.find((t) => t.type === 'page')
    } catch {
      /* 还没起来 */
    }
  }
  if (!target) throw new Error('Chrome 调试端口未就绪')

  ws = new WebSocket(target.webSocketDebuggerUrl)
  await new Promise((res, rej) => {
    ws.addEventListener('open', res, { once: true })
    ws.addEventListener('error', rej, { once: true })
  })

  let msgId = 0
  const pending = new Map()
  const consoleErrors = []
  ws.addEventListener('message', (ev) => {
    const m = JSON.parse(ev.data)
    if (m.id && pending.has(m.id)) {
      const { resolve, reject } = pending.get(m.id)
      pending.delete(m.id)
      m.error ? reject(new Error(JSON.stringify(m.error))) : resolve(m.result)
    } else if (m.method === 'Runtime.exceptionThrown') {
      consoleErrors.push(m.params.exceptionDetails?.exception?.description || m.params.exceptionDetails?.text)
    } else if (m.method === 'Runtime.consoleAPICalled' && m.params.type === 'error') {
      consoleErrors.push(m.params.args.map((a) => a.value ?? a.description ?? '').join(' '))
    }
  })
  const cdp = (method, params = {}) =>
    new Promise((resolve, reject) => {
      const i = ++msgId
      pending.set(i, { resolve, reject })
      ws.send(JSON.stringify({ id: i, method, params }))
      setTimeout(() => {
        if (pending.has(i)) {
          pending.delete(i)
          reject(new Error(`CDP 超时: ${method}`))
        }
      }, 40000)
    })
  const evalJs = async (expr) => {
    const r = await cdp('Runtime.evaluate', { expression: expr, returnByValue: true, awaitPromise: true })
    if (r.exceptionDetails) throw new Error(r.exceptionDetails.text || 'eval 失败')
    return r.result.value
  }
  const shot = async (name) => {
    const s = await cdp('Page.captureScreenshot', { format: 'png' })
    const p = join(OUTDIR, name)
    writeFileSync(p, Buffer.from(s.data, 'base64'))
    return p
  }

  await cdp('Page.enable')
  await cdp('Runtime.enable')
  // 关缓存：`npm run build` 会换 chunk 哈希，持久化 profile 缓存的旧 index.html
  // 会去动态 import **已删除的旧 chunk** → 404 → 白屏（表现为「先跑通过、rebuild 后再跑就红」）。
  await cdp('Network.enable')
  await cdp('Network.setCacheDisabled', { cacheDisabled: true })

  // ---- 注入 token（localStorage 需**同源**）----
  // ⚠️ 不能只 sleep 固定时间：SPA 还没起来时页面停在 about:blank，
  //    访问 localStorage 会抛 SecurityError（表现为「脚本执行异常 ← Uncaught」）。
  //    改为轮询「已到目标 origin 且能写 localStorage」。
  const ORIGIN = new URL(URL_ARG).origin
  await cdp('Page.navigate', { url: new URL('/login', URL_ARG).href })
  let injected = false
  for (let i = 0; i < 25 && !injected; i++) {
    await sleep(600)
    try {
      injected =
        (await evalJs(`(() => {
          if (location.origin !== ${JSON.stringify(ORIGIN)}) return 'pending';
          try {
            localStorage.clear();
            localStorage.setItem('qd_token', ${JSON.stringify(TOKEN)});
            localStorage.setItem('qd_user', 'trader');
            return 'ok';
          } catch (e) { return 'denied'; }
        })()`)) === 'ok'
    } catch {
      /* 页面还没就绪（about:blank / 导航中）→ 重试 */
    }
  }
  check(injected, '注入登录态成功（localStorage 可写）')

  // ---- 进设置页，等「数据与缓存」tab 出现 ----
  await cdp('Page.navigate', { url: URL_ARG })
  let tabFound = false
  for (let i = 0; i < 20 && !tabFound; i++) {
    await sleep(1200)
    tabFound = await evalJs(
      `[...document.querySelectorAll('button')].some(b => b.innerText.trim() === '数据与缓存')`,
    )
  }
  check(tabFound, '设置页渲染出「数据与缓存」标签')

  // ---- 点击该 tab ----
  await evalJs(
    `[...document.querySelectorAll('button')].find(b => b.innerText.trim() === '数据与缓存')?.click(); 'ok'`,
  )
  // 等 TwelveData 卡片出现（它要发一次 GET /market/twelvedata）
  let hasCard = false
  for (let i = 0; i < 20 && !hasCard; i++) {
    await sleep(1200)
    hasCard = await evalJs(`document.body.innerText.includes('TwelveData')`)
  }
  check(hasCard, '「数据与缓存」里渲染出 TwelveData 多 Key 卡片')

  const info = JSON.parse(
    await evalJs(`JSON.stringify({
      text: document.body.innerText,
      // 卡片内的可见输入框宽度（.inp 的 w-full 会把它撑到整行）
      widths: [...document.querySelectorAll('input')]
        .filter(i => i.offsetParent !== null)
        .map(i => Math.round(i.getBoundingClientRect().width)),
      maskedCount: (document.body.innerText.match(/\\*{4}/g) || []).length,
      // 数据源偏好下拉的选项（后端 available 驱动，不能硬编码漏源）
      options: [...document.querySelectorAll('select option')].map(o => o.value),
    })`),
  )

  check(info.text.includes('合计额度'), '卡片显示合计额度（多 Key 叠加后的总配额）')
  check(info.text.includes('轮询'), '卡片说明轮询机制')
  check(info.maskedCount >= 1, '至少渲染出一条掩码密钥（如 81d0****c6c1）', `masked=${info.maskedCount}`)
  // 回归守卫：降级链与偏好下拉必须跟上后端（曾硬编码成 5 项、漏掉 TwelveData）
  check(info.text.includes('TwelveData'), '降级链里出现 TwelveData（不再硬编码漏源）')
  check(info.text.includes('合成行情'), '降级链里仍保留「合成行情」兜底')
  check(info.options.includes('twelvedata'), '数据源偏好可选 TwelveData', `options=${info.options.join(',')}`)
  check(info.options.includes('auto'), '数据源偏好保留 auto', `options=${info.options.join(',')}`)
  const wide = info.widths.filter((w) => w > 900)
  check(wide.length === 0, '控件未被 .inp 的 w-full 撑破（无宽度 > 900px 的输入框）',
        `widths=${info.widths.join(',')}`)
  check(info.widths.every((w) => w > 40), '控件没有被压成 0 宽', `widths=${info.widths.join(',')}`)
  check(consoleErrors.length === 0, '浏览器控制台无报错', consoleErrors.slice(0, 2).join(' | '))

  await shot('settings-data-cache.png')
  console.log(`截图: ${join(OUTDIR, 'settings-data-cache.png')}`)
} catch (err) {
  check(false, '脚本执行异常', String(err && err.message ? err.message : err))
} finally {
  try {
    ws?.close()
  } catch {
    /* ignore */
  }
  chrome.kill()
}

const failed = results.filter((r) => !r).length
console.log('\n' + '='.repeat(58))
console.log(`  设置页视觉回归：${results.length - failed}/${results.length} 项通过`)
console.log('='.repeat(58))
process.exit(failed ? 1 : 0)
