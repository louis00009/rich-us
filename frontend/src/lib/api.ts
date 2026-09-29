/**
 * API 客户端
 * - Bearer Token 存于 localStorage（无 Cookie → 天然免 CSRF）
 * - 401 自动清理会话并跳回登录
 * - 统一错误提取
 */
const TOKEN_KEY = 'qd_token'
const USER_KEY = 'qd_user'

export const BASE = '/api'

export function getToken(): string {
  return localStorage.getItem(TOKEN_KEY) || ''
}
export function setToken(t: string, user?: string) {
  localStorage.setItem(TOKEN_KEY, t)
  if (user) localStorage.setItem(USER_KEY, user)
}
export function getUser(): string {
  return localStorage.getItem(USER_KEY) || ''
}
export function clearToken() {
  localStorage.removeItem(TOKEN_KEY)
  localStorage.removeItem(USER_KEY)
}

export class ApiError extends Error {
  status: number
  code?: string
  constructor(message: string, status: number, code?: string) {
    super(message)
    this.status = status
    this.code = code
  }
}

let onUnauthorized: (() => void) | null = null
export function setUnauthorizedHandler(fn: () => void) {
  onUnauthorized = fn
}

/** 默认超时：普通接口 30s；回测/寻优等长任务调用方需显式传更长值。 */
const DEFAULT_TIMEOUT = 30_000
export const LONG_TIMEOUT = 300_000

async function request<T>(path: string, init: RequestInit = {}, timeoutMs = DEFAULT_TIMEOUT): Promise<T> {
  const headers: Record<string, string> = {
    Accept: 'application/json',
    ...((init.headers as Record<string, string>) || {}),
  }
  const token = getToken()
  if (token) headers.Authorization = `Bearer ${token}`
  if (init.body && !headers['Content-Type']) headers['Content-Type'] = 'application/json'

  const ac = new AbortController()
  const timer = setTimeout(() => ac.abort(), timeoutMs)

  let res: Response
  try {
    res = await fetch(`${BASE}${path}`, { ...init, headers, signal: ac.signal })
  } catch (e: any) {
    if (e?.name === 'AbortError') {
      throw new ApiError(`请求超时（${Math.round(timeoutMs / 1000)}s），服务可能仍在计算，请稍后查看结果`, 0)
    }
    throw new ApiError('无法连接后端服务，请确认服务已启动', 0)
  } finally {
    clearTimeout(timer)
  }

  if (res.status === 401) {
    clearToken()
    onUnauthorized?.()
    throw new ApiError('登录已过期，请重新登录', 401)
  }

  const text = await res.text()
  // P3-11：JSON.parse 的返回值本质是 unknown —— 原先直接标 `any`，
  // 会让 `data.detail` 之类的字段名写错也无人报错。这里显式收窄后再取字段。
  let data: unknown = null
  if (text) {
    try {
      data = JSON.parse(text)
    } catch {
      data = { detail: text }
    }
  }

  if (!res.ok) {
    const errBody = (data ?? {}) as { detail?: unknown; code?: unknown }
    const detail = errBody.detail
    let msg = '请求失败'
    if (typeof detail === 'string') {
      msg = detail
    } else if (Array.isArray(detail)) {
      // FastAPI 校验错误：detail 是 [{loc, msg, type}, ...]
      msg = detail
        .map((d) => {
          const item = (d ?? {}) as { loc?: unknown[]; msg?: string }
          return `${(item.loc ?? []).join('.')}: ${item.msg ?? ''}`
        })
        .join('；')
    } else if (detail) {
      msg = JSON.stringify(detail)
    }
    throw new ApiError(msg, res.status, typeof errBody.code === 'string' ? errBody.code : undefined)
  }
  return data as T
}

export const api = {
  get: <T,>(p: string, timeoutMs?: number) => request<T>(p, {}, timeoutMs),
  post: <T,>(p: string, body?: any, timeoutMs?: number) =>
    request<T>(p, { method: 'POST', body: body ? JSON.stringify(body) : undefined }, timeoutMs),
  put: <T,>(p: string, body?: any, timeoutMs?: number) =>
    request<T>(p, { method: 'PUT', body: body ? JSON.stringify(body) : undefined }, timeoutMs),
  patch: <T,>(p: string, body?: any, timeoutMs?: number) =>
    request<T>(p, { method: 'PATCH', body: body ? JSON.stringify(body) : undefined }, timeoutMs),
  del: <T,>(p: string, timeoutMs?: number) => request<T>(p, { method: 'DELETE' }, timeoutMs),
}

/* ---------------- WebSocket ---------------- */
/**
 * 实时行情流，带指数退避自动重连。
 * 后端重启 / 网络抖动后无需手动刷新页面即可恢复；重连期间状态回调为 'closed'。
 */
export function openStream(
  symbols: string[],
  interval: number,
  onMessage: (msg: any) => void,
  onStatus?: (s: 'open' | 'closed' | 'error') => void,
): () => void {
  let ws: WebSocket | null = null
  let stopped = false
  let retry = 0
  let retryTimer: ReturnType<typeof setTimeout> | null = null

  const buildUrl = () => {
    const proto = location.protocol === 'https:' ? 'wss' : 'ws'
    const token = getToken()
    return `${proto}://${location.host}${BASE}/ws/stream?token=${encodeURIComponent(token)}&symbols=${encodeURIComponent(
      symbols.join(','),
    )}&interval=${interval}`
  }

  const schedule = () => {
    if (stopped) return
    const delay = Math.min(1000 * 2 ** retry, 30_000)
    retry += 1
    retryTimer = setTimeout(connect, delay)
  }

  function connect() {
    if (stopped) return
    try {
      ws = new WebSocket(buildUrl())
    } catch {
      onStatus?.('error')
      schedule()
      return
    }
    ws.onopen = () => {
      retry = 0
      onStatus?.('open')
    }
    ws.onmessage = (ev) => {
      try {
        onMessage(JSON.parse(ev.data))
      } catch {
        /* ignore */
      }
    }
    ws.onerror = () => onStatus?.('error')
    ws.onclose = () => {
      if (stopped) return
      onStatus?.('closed')
      schedule()
    }
  }

  connect()

  return () => {
    stopped = true
    if (retryTimer) clearTimeout(retryTimer)
    try {
      ws?.close()
    } catch {
      /* ignore */
    }
  }
}
