import { spawn } from 'child_process'
import { setTimeout as sleep } from 'timers/promises'
const CHROME = 'C:/Program Files/Google/Chrome/Application/chrome.exe'
const BASE = 'http://127.0.0.1:8787'
const chrome = spawn(CHROME, ['--headless=new', '--remote-debugging-port=9334', '--no-first-run', '--user-data-dir=C:/Users/Louis/Desktop/IBKR/frontend/.cdp-profile', 'about:blank'], { stdio: 'ignore' })
try {
  let target = null
  for (let i = 0; i < 20; i++) {
    await sleep(500)
    try { target = (await (await fetch('http://127.0.0.1:9334/json')).json()).find(t => t.type === 'page'); if (target) break } catch {}
  }
  const ws = new WebSocket(target.webSocketDebuggerUrl)
  await new Promise((res, rej) => { ws.onopen = res; ws.onerror = rej })
  let id = 0; const pending = new Map(); const events = []
  ws.onmessage = (ev) => {
    const m = JSON.parse(ev.data)
    if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id) }
    if (m.method === 'Runtime.exceptionThrown') events.push('EXC: ' + (m.params.exceptionDetails.exception?.description || m.params.exceptionDetails.text).split('\n')[0])
  }
  const send = (method, params = {}) => new Promise((res) => { const mid = ++id; pending.set(mid, res); ws.send(JSON.stringify({ id: mid, method, params })) })
  const evalJs = async (expr) => (await send('Runtime.evaluate', { expression: expr, awaitPromise: true, returnByValue: true })).result?.result?.value
  await send('Runtime.enable'); await send('Page.enable')
  await send('Page.navigate', { url: BASE + '/login' }); await sleep(2500)
  await evalJs(`fetch('${BASE}/api/auth/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username:'trader',password:'QuantDesk#2026'})}).then(r=>r.json()).then(j=>{localStorage.setItem('qd_token',j.access_token);localStorage.setItem('qd_user','trader');return 1})`)
  await send('Page.navigate', { url: BASE + '/dashboard' }); await sleep(5000)
  const diag = await evalJs(`(() => {
    const syncBtn = [...document.querySelectorAll('button')].find(b => b.textContent.includes('同步持仓'))
    const chips = [...document.querySelectorAll('button')].filter(b => /0700|AAPL/.test(b.textContent)).map(b => b.textContent.trim().slice(0, 24))
    const watchText = document.body.innerText.includes('暂无关注')
    return JSON.stringify({ syncBtn: !!syncBtn, chips: chips.slice(0, 6), watchText, totalBtns: document.querySelectorAll('button').length })
  })()`)
  console.log('diag:', diag)
  // 模拟点击第一个 chip（客户端路由）
  const clicked = await evalJs(`(() => {
    const syncBtn = [...document.querySelectorAll('button')].find(b => b.textContent.includes('同步持仓'))
    const bar = syncBtn ? syncBtn.closest('div.flex') : null
    const chip = bar ? [...bar.querySelectorAll('button')].find(b => !b.textContent.includes('同步持仓') && b.textContent.trim().length > 2) : null
    if (chip) { chip.click(); return 'clicked ' + chip.textContent.trim().slice(0, 20) + ' | url=' + location.pathname + location.search }
    return 'no chip'
  })()`)
  console.log('click:', clicked)
  await sleep(5000)
  const after = await evalJs(`JSON.stringify({ path: location.pathname + location.search, rootLen: (document.getElementById('root')?.innerHTML || '').length, hasChart: !!document.querySelector('svg'), body: document.body.innerText.slice(0, 60).replace(/\\n/g, '|') })`)
  console.log('after:', after)
  console.log('events:', events.length ? events.slice(0, 8) : '(none)')
} finally { chrome.kill(); process.exit(0) }
