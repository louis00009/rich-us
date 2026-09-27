import { Bell, CheckCheck, RefreshCw, X } from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../lib/api'
import { rtSubscribe } from '../lib/realtime'
import { Badge, useToast } from './ui'

export interface AlertEvent {
  id: number
  ts: string
  kind: string
  level: 'info' | 'hot' | 'warn'
  symbol: string
  market: string
  title: string
  detail: string
  payload: Record<string, any>
  is_read: boolean
}

const LEVEL_STYLE: Record<string, { badge: 'red' | 'amber' | 'slate'; label: string }> = {
  hot: { badge: 'red', label: '重要' },
  warn: { badge: 'amber', label: '风险' },
  info: { badge: 'slate', label: '动态' },
}

/**
 * 智能提示铃铛（Layout 顶栏）。
 * 交互设计：
 *  · 每 30s 轮询未读数；每 2min 触发一次后端扫描（服务端有 90s 冷却，重复触发无害）。
 *  · 有新事件 → 右下角 toast 弹出（标题 + 详情摘要），并累计未读角标。
 *  · 点铃铛 → 下拉面板：最近 50 条，按级别着色，可单条已读 / 全部已读。
 */
export default function AlertsBell() {
  const [unread, setUnread] = useState(0)
  const [open, setOpen] = useState(false)
  const [items, setItems] = useState<AlertEvent[]>([])
  const [loading, setLoading] = useState(false)
  const [scanning, setScanning] = useState(false)
  const [filter, setFilter] = useState<'all' | 'unread' | 'hot'>('all')
  const lastSeenId = useRef<number>(0)
  const toast = useToast()

  const loadUnread = useCallback(async () => {
    try {
      const r = await api.get<{ unread: number }>('/alerts/unread-count')
      setUnread(r.unread)
    } catch {
      /* 静默 */
    }
  }, [])

  const loadItems = useCallback(async () => {
    setLoading(true)
    try {
      const r = await api.get<{ items: AlertEvent[]; unread: number }>('/alerts?limit=50')
      setItems(r.items)
      setUnread(r.unread)
      // 新事件 → toast + 桌面通知（T-120）
      const fresh = r.items.filter((i) => i.id > lastSeenId.current && !i.is_read)
      if (lastSeenId.current > 0) {
        for (const ev of fresh.slice(0, 4)) {
          toast(ev.level === 'warn' ? 'warning' : ev.level === 'hot' ? 'info' : 'info',
            `【${ev.symbol}】${ev.title}${ev.detail ? `\n${ev.detail}` : ''}`)
          if (typeof Notification !== 'undefined' && Notification.permission === 'granted' && (ev.level === 'hot' || ev.level === 'warn')) {
            try {
              new Notification(`QuantDesk · ${ev.symbol}`, { body: `${ev.title}\n${(ev.detail || '').slice(0, 120)}`, tag: `qd-${ev.id}` })
            } catch {
              /* 通知失败静默 */
            }
          }
        }
        if (fresh.length > 4) toast('info', `还有 ${fresh.length - 4} 条新提示，点开铃铛查看`)
      }
      lastSeenId.current = Math.max(lastSeenId.current, ...r.items.map((i) => i.id), 0)
    } catch {
      /* 静默 */
    } finally {
      setLoading(false)
    }
  }, [toast])

  // 轮询未读数 + 定期扫描（轮询保留作降级）
  useEffect(() => {
    loadUnread()
    const t1 = setInterval(loadUnread, 30_000)
    const t2 = setInterval(() => {
      api.post('/alerts/scan').catch(() => {})
    }, 120_000)
    api.post('/alerts/scan').catch(() => {})
    return () => {
      clearInterval(t1)
      clearInterval(t2)
    }
  }, [loadUnread])

  // WebSocket 实时告警（T-106）：新事件秒级到达 → 立即刷新并弹 toast
  useEffect(() => {
    return rtSubscribe(['alerts'], () => {
      loadUnread()
      loadItems()
    })
  }, [loadUnread, loadItems])

  // 面板打开时刷新列表
  useEffect(() => {
    if (open) loadItems()
  }, [open, loadItems])

  const markAll = async () => {
    await api.post('/alerts/read', { ids: [] }).catch(() => {})
    loadItems()
  }

  const markOne = async (id: number) => {
    await api.post('/alerts/read', { ids: [id] }).catch(() => {})
    loadItems()
  }

  const rescan = async () => {
    setScanning(true)
    try {
      const r = await api.post<{ created: number; scanned: number; skipped?: boolean }>('/alerts/scan', { force: true })
      toast('info', r.skipped ? '扫描冷却中，请稍候' : `扫描完成：${r.scanned} 个标的，新增 ${r.created} 条提示`)
      if (!r.skipped) loadItems()
    } finally {
      setScanning(false)
    }
  }

  return (
    <div className="relative">
      <button
        onClick={() => setOpen((v) => !v)}
        title="智能提示（关注与持仓的信号 / 新闻）"
        className="relative rounded-md p-1.5 text-slate-500 hover:bg-slate-100"
      >
        <Bell className="h-4.5 w-4.5" style={{ height: 18, width: 18 }} />
        {unread > 0 && (
          <span className="absolute -right-0.5 -top-0.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-rose-500 px-1 text-[10px] font-semibold text-white">
            {unread > 99 ? '99+' : unread}
          </span>
        )}
      </button>

      {open && (
        <>
          <div className="fixed inset-0 z-30" onClick={() => setOpen(false)} />
          <div className="absolute right-0 z-40 mt-2 flex max-h-[70vh] w-[calc(100vw-24px)] max-w-[400px] flex-col rounded-xl border border-slate-200 bg-white shadow-pop">
            <div className="flex items-center justify-between border-b border-slate-100 px-4 py-2.5">
              <div className="flex items-center gap-1">
                {([['all', '全部'], ['unread', '未读'], ['hot', '高危']] as const).map(([k, label]) => (
                  <button
                    key={k}
                    onClick={() => setFilter(k)}
                    className={`rounded-md px-2 py-0.5 text-[11px] transition-colors ${
                      filter === k ? 'bg-brand-50 font-semibold text-brand-700' : 'text-slate-400 hover:bg-slate-50'
                    }`}
                  >
                    {label}
                  </button>
                ))}
              </div>
              <div className="flex items-center gap-1">
                {typeof Notification !== 'undefined' && Notification.permission === 'default' && (
                  <button
                    onClick={() => Notification.requestPermission()}
                    title="开启桌面通知（高危/警告事件弹出系统通知）"
                    className="rounded px-1.5 py-0.5 text-[10px] text-brand-600 hover:bg-brand-50"
                  >
                    桌面通知
                  </button>
                )}
                <button
                  onClick={rescan}
                  title="立即扫描"
                  className="rounded p-1.5 text-slate-400 hover:bg-slate-100 hover:text-slate-600"
                >
                  <RefreshCw className={`h-3.5 w-3.5 ${scanning ? 'animate-spin' : ''}`} />
                </button>
                <button
                  onClick={markAll}
                  title="全部已读"
                  className="rounded p-1.5 text-slate-400 hover:bg-slate-100 hover:text-slate-600"
                >
                  <CheckCheck className="h-3.5 w-3.5" />
                </button>
                <button onClick={() => setOpen(false)} className="rounded p-1.5 text-slate-400 hover:bg-slate-100">
                  <X className="h-3.5 w-3.5" />
                </button>
              </div>
            </div>
            <div className="min-h-0 flex-1 overflow-y-auto p-2">
              {loading && items.length === 0 && (
                <div className="px-3 py-8 text-center text-xs text-slate-400">加载中…</div>
              )}
              {!loading && items.length === 0 && (
                <div className="px-3 py-8 text-center text-xs leading-5 text-slate-400">
                  暂无提示。
                  <br />
                  在关注列表或持仓中的标的触发技术信号 / 新闻关键词时，会出现在这里。
                </div>
              )}
              {items.filter((ev) => (filter === 'unread' ? !ev.is_read : filter === 'hot' ? ev.level === 'hot' || ev.level === 'warn' : true)).map((ev) => {
                const st = LEVEL_STYLE[ev.level] ?? LEVEL_STYLE.info
                return (
                  <div
                    key={ev.id}
                    className={`group rounded-lg px-3 py-2.5 transition-colors hover:bg-slate-50 ${
                      ev.is_read ? 'opacity-60' : ''
                    }`}
                  >
                    <div className="flex items-center gap-2">
                      <Badge tone={st.badge}>{st.label}</Badge>
                      <a
                        href={`/market?symbol=${encodeURIComponent(ev.symbol)}`}
                        className="text-xs font-semibold text-brand-700 hover:underline"
                        onClick={() => setOpen(false)}
                      >
                        {ev.symbol}
                      </a>
                      <span className="ml-auto text-[10px] text-slate-400">
                        {new Date(ev.ts + 'Z').toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })}
                      </span>
                    </div>
                    <p className="mt-1 text-[13px] font-medium text-slate-700">{ev.title}</p>
                    {ev.detail && <p className="mt-0.5 line-clamp-2 text-[11px] text-slate-400">{ev.detail}</p>}
                    {!ev.is_read && (
                      <button
                        onClick={() => markOne(ev.id)}
                        className="mt-1 text-[10px] text-slate-300 opacity-0 transition-opacity hover:text-brand-600 group-hover:opacity-100"
                      >
                        标为已读
                      </button>
                    )}
                  </div>
                )
              })}
            </div>
          </div>
        </>
      )}
    </div>
  )
}
