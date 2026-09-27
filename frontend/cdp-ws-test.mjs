// WebSocket 秒级推送真机测试：登录 → /api/ws → sub quotes:0700.HK（腾讯秒级源）
import { setTimeout as sleep } from 'timers/promises'

const BASE = 'http://127.0.0.1:8787'
const login = await (await fetch(`${BASE}/api/auth/login`, {
  method: 'POST', headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ username: 'trader', password: 'QuantDesk#2026' }),
})).json()
const token = login.access_token

const ws = new WebSocket(`ws://127.0.0.1:8787/api/ws?token=${encodeURIComponent(token)}`)
let count = 0
const t0 = Date.now()
ws.onopen = () => {
  console.log('connected')
  ws.send(JSON.stringify({ action: 'sub', topics: ['quotes:0700.HK,AAPL'] }))
}
ws.onmessage = (ev) => {
  const m = JSON.parse(ev.data)
  if (m.topic === 'ack') { console.log('ack:', JSON.stringify(m.data)); return }
  const q = m.data?.[0]
  console.log(`#${++count} +${((Date.now() - t0) / 1000).toFixed(1)}s topic=${m.topic} ${q?.symbol} price=${q?.price} rt_t=${q?.rt_t} delayed=${q?.rt_delayed} src=${q?.source}`)
  if (count >= 4) { ws.close(); process.exit(0) }
}
ws.onerror = (e) => { console.log('error', e.message ?? ''); process.exit(1) }
await sleep(30000)
console.log('timeout — 只收到', count, '条')
process.exit(count > 0 ? 0 : 1)
