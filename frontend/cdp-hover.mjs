// CDP 复现：行情页 K 线悬停是否有 tooltip / 信息条
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
  const token = await evalJs(`fetch('${BASE}/api/auth/login', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({username:'trader', password:'QuantDesk#2026'})}).then(r=>r.json()).then(j => { localStorage.setItem('qd_token', j.access_token); localStorage.setItem('qd_user','trader'); return 'ok' })`)
  console.log('login:', token)

  await send('Page.navigate', { url: BASE + '/market?symbol=SPY' })
  await sleep(8000)

  const probe = await evalJs(`(() => {
    const svg = document.querySelector('svg')
    const svgCount = document.querySelectorAll('svg').length
    if (!svg) return { svgCount, svg: false }
    const r = svg.getBoundingClientRect()
    return { svgCount, svg: true, w: r.width, h: r.height, x: r.x, y: r.y, cursor: getComputedStyle(svg).cursor }
  })()`)
  console.log('probe:', JSON.stringify(probe))

  // 在 SVG 中央派发 mousemove
  const hover = await evalJs(`(() => {
    const svgs = [...document.querySelectorAll('svg')]
    const svg = svgs.sort((a,b) => b.getBoundingClientRect().width - a.getBoundingClientRect().width)[0]
    if (!svg) return 'no svg'
    const r = svg.getBoundingClientRect()
    const x = r.x + r.width * 0.5, y = r.y + r.height * 0.4
    for (const t of ['mousemove','mouseover','mouseenter']) {
      svg.dispatchEvent(new MouseEvent(t, { clientX: x, clientY: y, bubbles: true, cancelable: true, view: window }))
    }
    return 'dispatched at ' + Math.round(x) + ',' + Math.round(y)
  })()`)
  console.log('hover:', hover)
  await sleep(800)

  const after = await evalJs(`(() => {
    const text = document.body.innerText
    const hasOHLC = /开/.test(text) && /收/.test(text)
    const tooltip = [...document.querySelectorAll('div')].find(d => d.className && String(d.className).includes('pointer-events-none'))
    return {
      hasOHLC,
      tooltipFound: !!tooltip,
      tooltipText: tooltip ? tooltip.innerText.slice(0, 120) : null,
      hasHighLowLabel: /最高/.test(text) && /最低/.test(text),
      stripSnippet: text.slice(0, 0),
    }
  })()`)
  console.log('after hover:', JSON.stringify(after, null, 1))

  console.log('--- events ---')
  for (const e of events.slice(0, 10)) console.log(e)
  if (!events.length) console.log('(no console errors)')
} finally {
  chrome.kill()
  process.exit(0)
}
