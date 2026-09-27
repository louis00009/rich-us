/**
 * 实时推送客户端（T-106）
 * ========================
 * 单例 WebSocket + 主题引用计数 + 指数退避重连。
 * 用法：
 *   useEffect(() => rtSubscribe([`quotes:${symbol}`, 'alerts'], (msg) => { ... }), [symbol])
 * 服务协议见 backend/app/realtime.py。连接断开时调用方应保留轮询作为降级。
 */

export interface RTMsg {
  topic: string
  ts?: string
  data: any
}
type Handler = (m: RTMsg) => void

let ws: WebSocket | null = null
let connecting = false
let retryDelay = 1000
let closedByUs = false
let lastTickAt = 0

/** 最近一次收到行情推送的时间戳（DataClock 用）。 */
export function lastRtTick(): number {
  return lastTickAt
}

const refCounts = new Map<string, number>()
const handlers = new Set<{ topics: string[]; fn: Handler }>()
const stateListeners = new Set<(online: boolean) => void>()

/** 订阅连接状态（在线/断线）——全局数据时钟等 UI 用。 */
export function onRtState(fn: (online: boolean) => void): () => void {
  stateListeners.add(fn)
  fn(!!ws && ws.readyState === WebSocket.OPEN)
  return () => {
    stateListeners.delete(fn)
  }
}

function notifyState(online: boolean) {
  for (const fn of stateListeners) {
    try {
      fn(online)
    } catch {
      /* noop */
    }
  }
}

function wsUrl(): string {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws'
  // P1-11：token **不再**放进查询串 —— 那会写进浏览器历史、反向代理访问日志、
  // Referer 头。改为连接建立后由首帧发送（见 connect() 的 onopen）。
  return `${proto}://${location.host}/api/ws`
}

function rawSend(obj: unknown): boolean {
  if (ws && ws.readyState === WebSocket.OPEN) {
    ws.send(JSON.stringify(obj))
    return true
  }
  return false
}

function resubscribeAll() {
  const topics = [...refCounts.keys()]
  if (topics.length) rawSend({ action: 'sub', topics })
}

/** P0-1：主题匹配谓词。
 *
 *  订阅端用带标的的主题（"quotes:SPY" / "intraday:AAPL"），服务端广播的是**裸主题**
 *  （backend/app/realtime.py:_broadcast_quotes 推 topic="quotes"）。
 *  旧实现用 `h.topics.includes(m.topic)` → ['quotes:SPY'].includes('quotes') === false，
 *  导致所有行情 handler 永不触发（行情秒级推送静默失效，只靠轮询兜底）。
 *  导出以便 scripts/topic-check.mjs 做回归测试。
 */
export function topicMatches(subscribed: string[], incoming: string): boolean {
  const base = incoming.split(':')[0]
  return subscribed.some((t) => t === incoming || t.split(':')[0] === base)
}

function connect() {
  if (ws || connecting) return
  connecting = true
  closedByUs = false
  const w = new WebSocket(wsUrl())
  w.onopen = () => {
    connecting = false
    retryDelay = 1000
    notifyState(true)
    // P1-11：token 走**首帧**（服务端优先按首帧鉴权，见 backend/app/api/ws.py）。
    // WebSocket 消息有序，所以「先 auth 再 sub」是安全的。
    const token = localStorage.getItem('qd_token') || ''
    if (token) {
      try {
        w.send(JSON.stringify({ action: 'auth', token }))
      } catch {
        /* 连接刚断则忽略，重连后会再发 */
      }
    }
    resubscribeAll()
  }
  w.onmessage = (ev) => {
    let m: RTMsg
    try {
      m = JSON.parse(ev.data)
    } catch {
      return
    }
    if (!m?.topic || m.topic === 'ack') return
    if (m.topic === 'quotes') lastTickAt = Date.now()
    for (const h of handlers) {
      if (topicMatches(h.topics, m.topic)) {
        try {
          h.fn(m)
        } catch {
          /* 单个 handler 异常不影响其他订阅者 */
        }
      }
    }
  }
  w.onclose = (e) => {
    ws = null
    connecting = false
    notifyState(false)
    if (closedByUs || refCounts.size === 0) return
    // 4401 = token 失效：放慢重连，等全局重新登录后拿到新 token
    const delay = e.code === 4401 ? 15000 : retryDelay
    setTimeout(connect, delay)
    if (e.code !== 4401) retryDelay = Math.min(retryDelay * 2, 15000)
  }
  w.onerror = () => {
    try {
      w.close()
    } catch {
      /* noop */
    }
  }
  ws = w
}

/** 订阅主题；返回取消函数。topics 变化请重建（放进 useEffect deps）。 */
export function rtSubscribe(topics: string[], fn: Handler): () => void {
  const entry = { topics, fn }
  handlers.add(entry)
  const fresh = topics.filter((t) => !refCounts.has(t))
  for (const t of topics) refCounts.set(t, (refCounts.get(t) || 0) + 1)
  if (!rawSend({ action: 'sub', topics: fresh })) connect()
  else if (fresh.length) rawSend({ action: 'sub', topics: fresh })

  return () => {
    handlers.delete(entry)
    for (const t of topics) {
      const n = (refCounts.get(t) || 1) - 1
      if (n <= 0) {
        refCounts.delete(t)
        rawSend({ action: 'unsub', topics: [t] })
      } else {
        refCounts.set(t, n)
      }
    }
  }
}
