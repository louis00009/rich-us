import { PlusCircle, Star } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../lib/api'
import { rtSubscribe } from '../lib/realtime'
import { notifyWatchlistChanged, onWatchlistChanged } from '../lib/watchlistBus'
import { downColor, upColor } from '../lib/format'
import { useToast } from './ui'

interface WatchItem {
  symbol: string
  market: string
  note: string
  held: boolean
  price: number
  change_pct: number
  quote_source: string
  name_cn?: string
}

/**
 * 看板顶部关注条：关注（含一键同步的持仓）标的 chips，实时价格与涨跌。
 * 点击 chip → 跳转行情分析页；× 移除关注。
 */
export default function WatchBar() {
  const [items, setItems] = useState<WatchItem[]>([])
  const [loading, setLoading] = useState(true)
  const nav = useNavigate()
  const toast = useToast()

  const load = useCallback(async () => {
    try {
      const r = await api.get<{ items: WatchItem[] }>('/watchlist')
      setItems(r.items)
    } catch {
      /* 静默 */
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
    const t = setInterval(load, 60_000)   // 降级轮询（主链路已走 WebSocket）
    // 关注/收藏即时同步：行情页收藏、榜单页关注后立即重载
    const off = onWatchlistChanged(load)
    return () => {
      clearInterval(t)
      off()
    }
  }, [load])

  // WebSocket 实时价格（T-106b）：关注列表价格秒级跳动
  const symKey = items.map((i) => i.symbol).join(',')
  useEffect(() => {
    if (!symKey) return
    return rtSubscribe([`quotes:${symKey}`], (m) => {
      const rows = m.data || []
      setItems((prev) =>
        prev.map((it) => {
          const q = rows.find((r: any) => r.symbol === it.symbol)
          return q ? { ...it, price: q.price, change_pct: q.change_pct } : it
        }),
      )
    })
  }, [symKey])

  const syncPositions = async () => {
    try {
      const r = await api.post<{ added: string[]; kept: string[] }>('/watchlist/sync-positions')
      toast('success', `已同步持仓：新增关注 ${r.added.length} 个，保留 ${r.kept.length} 个`)
      notifyWatchlistChanged()
      load()
    } catch {
      toast('error', '同步持仓失败')
    }
  }

  const remove = async (sym: string) => {
    try {
      await api.del(`/watchlist/${encodeURIComponent(sym)}`)
      setItems((s) => s.filter((i) => i.symbol !== sym))
      notifyWatchlistChanged()
    } catch {
      toast('error', '移除失败')
    }
  }

  return (
    <div className="flex flex-wrap items-center gap-2 rounded-xl border border-slate-200 bg-white px-3 py-2.5">
      <span className="flex items-center gap-1 text-[11px] font-medium text-slate-400">
        <Star className="h-3 w-3" />
        关注
      </span>
      {loading && <span className="text-xs text-slate-300">加载中…</span>}
      {!loading && items.length === 0 && (
        <span className="text-xs text-slate-400">
          暂无关注 —— 在榜单页 / 行情页添加，或点击右侧同步全部持仓
        </span>
      )}
      {items.map((it) => (
        <span
          key={it.symbol}
          title={it.name_cn || it.symbol}
          className="group flex max-w-[190px] items-center gap-1.5 rounded-lg border border-slate-200 bg-slate-50 py-1 pl-2 pr-1 transition-colors hover:border-brand-300"
        >
          {it.held && <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-emerald-500" title="当前持仓" />}
          <button
            onClick={() => nav(`/market?symbol=${encodeURIComponent(it.symbol)}`)}
            className="shrink-0 text-xs font-semibold text-slate-700 hover:text-brand-700"
          >
            {it.symbol}
          </button>
          {it.name_cn && <span className="truncate text-[10px] text-slate-400">{it.name_cn}</span>}
          <span className="shrink-0 text-xs text-slate-500">{it.price ? it.price.toFixed(2) : '—'}</span>
          <span className="shrink-0 text-xs font-medium" style={{ color: it.change_pct == null ? undefined : (it.change_pct >= 0 ? upColor() : downColor()) }}>
            {it.change_pct == null ? '—' : `${it.change_pct >= 0 ? '+' : ''}${it.change_pct.toFixed(2)}%`}
          </span>
          <button
            onClick={() => remove(it.symbol)}
            className="rounded p-0.5 text-[10px] leading-none text-slate-300 opacity-0 transition-opacity hover:text-rose-500 group-hover:opacity-100"
            title="取消关注"
          >
            ×
          </button>
        </span>
      ))}
      <button
        onClick={syncPositions}
        title="把当前全部持仓加入关注"
        className="ml-auto flex items-center gap-1 rounded-lg border border-slate-200 px-2 py-1 text-[11px] text-slate-500 transition-colors hover:bg-slate-50"
      >
        <PlusCircle className="h-3 w-3" />
        同步持仓
      </button>
    </div>
  )
}
