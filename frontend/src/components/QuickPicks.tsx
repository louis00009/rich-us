import { PlusCircle, Star } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { api } from '../lib/api'
import { rtSubscribe } from '../lib/realtime'
import { onWatchlistChanged } from '../lib/watchlistBus'
import { downColor, upColor } from '../lib/format'

/**
 * 快速选择标签：关注列表 + 当前持仓 + 主流 ETF。
 * 解决「行情分析里不能快速选中已订阅股票」的问题 —— 一点即切，不用搜索。
 */
export default function QuickPicks({ current, onPick }: { current: string; onPick: (symbol: string) => void }) {
  const [watch, setWatch] = useState<{ symbol: string; price: number; change_pct: number; held: boolean; name_cn?: string }[]>([])
  const [extra, setExtra] = useState<string[]>([])   // 持仓里不在关注列表的

  const load = useCallback(async () => {
    try {
      const r = await api.get<{ items: { symbol: string; price: number; change_pct: number; held: boolean }[] }>('/watchlist')
      setWatch(r.items)
      const watched = new Set(r.items.map((i) => i.symbol))
      const pos = await api.get<{ items?: any[]; positions?: any[] }>('/trading/positions')
      const items: any[] = pos.items ?? pos.positions ?? []
      const heldSyms = items
        .filter((p) => (p.quantity ?? 0) > 0)
        .map((p) => String(p.symbol || '').toUpperCase())
        .filter((s) => s && !watched.has(s))
      setExtra(heldSyms)
    } catch {
      /* 静默 */
    }
  }, [])

  useEffect(() => {
    load()
    const t = setInterval(load, 60_000)   // 降级轮询（主链路已走 WebSocket）
    // 收藏/取关即时同步：行情页收藏、榜单页关注、看板移除后立即重载，不等 60s 轮询
    const off = onWatchlistChanged(load)
    return () => {
      clearInterval(t)
      off()
    }
  }, [load])

  // WebSocket 实时涨跌（T-106b）
  const symKey = watch.map((w) => w.symbol).join(',')
  useEffect(() => {
    if (!symKey) return
    return rtSubscribe([`quotes:${symKey}`], (m) => {
      const rows = m.data || []
      setWatch((prev) =>
        prev.map((w) => {
          const q = rows.find((r: any) => r.symbol === w.symbol)
          return q ? { ...w, price: q.price, change_pct: q.change_pct } : w
        }),
      )
    })
  }, [symKey])

  const chip = (sym: string, price?: number, chg?: number, key?: string, held?: boolean, nameCn?: string) => (
    <button
      key={key || sym}
      onClick={() => onPick(sym)}
      title={nameCn || sym}
      className={`flex max-w-[190px] items-center gap-1.5 rounded-lg border px-2 py-1 text-xs transition-colors ${
        sym === current
          ? 'border-brand-400 bg-brand-50 font-semibold text-brand-700'
          : 'border-slate-200 text-slate-600 hover:border-brand-300 hover:bg-slate-50'
      }`}
    >
      {held && <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-emerald-500" title="当前持仓" />}
      <Star className={`h-3 w-3 shrink-0 ${watch.some((w) => w.symbol === sym) ? 'fill-amber-400 text-amber-400' : 'text-slate-300'}`} />
      <span className="shrink-0 font-medium">{sym}</span>
      {nameCn && <span className="truncate text-[10px] text-slate-400">{nameCn}</span>}
      {typeof chg === 'number' && Number.isFinite(chg) && (
        <span className="shrink-0" style={{ color: chg >= 0 ? upColor() : downColor() }}>
          {chg >= 0 ? '+' : ''}
          {chg.toFixed(2)}%
        </span>
      )}
    </button>
  )

  return (
    <div className="flex flex-wrap items-center gap-1.5">
      <span className="mr-1 flex items-center gap-1 text-[10px] font-medium uppercase tracking-wide text-slate-400">
        <PlusCircle className="h-3 w-3" />
        快速选择
      </span>
      {watch.map((w) => chip(w.symbol, w.price, w.change_pct, `w-${w.symbol}`, w.held, (w as any).name_cn))}
      {extra.map((s) => chip(s, undefined, undefined, `p-${s}`, true))}
    </div>
  )
}
