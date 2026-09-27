// 用 Chrome headless CDP 复现：登录 → /dashboard → 点击关注 chip → 抓异常
import { spawn } from 'child_process'
import { setTimeout as sleep } from 'timers/promises'

const CHROME = 'C:/Program Files/Google/Chrome/Application/chrome.exe'
const BASE = 'http://127.0.0.1:8787'
const chrome = spawn(CHROME, [
  '--headless=new', '--remote-debugging-port=9333', '--no-first-run',
  '--user-data-dir=C:/Users/Louis/Desktop/IBKR/frontend/.cdp-profile',
  '--window-size=1400,900', 'about:blank',
], { stdio: 'ignore' })

try {
  let target = null
  for (let i = 0; i < 20; i++) {
    await sleep(500)
    try {
      const list = await (await fetch('http://127.0.0.1:9333/json')).json()
      target = list.find(t => t.type === 'page')
      if (target) break
    } catch {}
  }
  if (!target) throw new Error('no debug target')

  const ws = new WebSocket(target.webSocketDebuggerUrl)
  await new Promise((res, rej) => { ws.onopen = res; ws.onerror = rej })
  let id = 0
  const pending = new Map()
  const events = []
  ws.onmessage = (ev) => {
    const m = JSON.parse(ev.data)
    if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id) }
    if (m.method === 'Runtime.exceptionThrown') {
      const d = m.params.exceptionDetails
      events.push('EXCEPTION: ' + (d.exception?.description || d.text).split('\n').slice(0, 6).join(' | '))
    }
    if (m.method === 'Runtime.consoleAPICalled' && m.params.type === 'error') {
      events.push('CONSOLE: ' + m.params.args.map(a => a.value ?? a.description ?? '').join(' ').split('\n').slice(0, 4).join(' | '))
    }
  }
  const send = (method, params = {}) => new Promise((res) => {
    const mid = ++id
    pending.set(mid, res)
    ws.send(JSON.stringify({ id: mid, method, params }))
  })
  const evalJs = async (expr) => {
    const r = await send('Runtime.evaluate', { expression: expr, awaitPromise: true, returnByValue: true })
    return r.result?.result?.value ?? r.result?.result?.description
  }

  await send('Runtime.enable')
  await send('Page.enable')
  await send('Page.navigate', { url: BASE + '/login' })
  await sleep(2500)

  // 注入 token（直接走 API 登录）
  const token = await evalJs(`fetch('${BASE}/api/auth/login', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({username:'trader', password:'QuantDesk#2026'})}).then(r=>r.json()).then(j => { localStorage.setItem('qd_token', j.access_token); localStorage.setItem('qd_user','trader'); return 'ok' })`)
  console.log('login:', token)

  // 直接跳到关注股票的行情页（复刻点击 WatchBar chip 的落点）
  await send('Page.navigate', { url: BASE + '/market?symbol=0700.HK' })
  await sleep(6000)
  const rootHtml = await evalJs(`(document.getElementById('root')?.innerHTML || '').length`)
  console.log('market 0700.HK root html length:', rootHtml)

  // 再模拟在 dashboard 点 chip 的客户端路由
  await send('Page.navigate', { url: BASE + '/dashboard' })
  await sleep(4000)
  const clicked = await evalJs(`(() => {
    const btns = [...document.querySelectorAll('button')].filter(b => b.textContent.includes('同步持仓') === false && b.closest('.flex.flex-wrap') && /[-+]?\\d+\\.\\d+%/.test(b.textContent))
    if (btns.length) { btns[0].click(); return 'clicked: ' + btns[0].textContent.trim().slice(0, 30) }
    return 'no chip found; buttons=' + document.querySelectorAll('button').length
  })()`)
  console.log('chip:', clicked)
  await sleep(4000)
  const html2 = await evalJs(`(document.getElementById('root')?.innerHTML || '').length`)
  console.log('after click root html length:', html2)

  console.log('--- events ---')
  for (const e of events.slice(0, 15)) console.log(e)
  if (!events.length) console.log('(no console errors)')
} finally {
  chrome.kill()
  process.exit(0)
}
