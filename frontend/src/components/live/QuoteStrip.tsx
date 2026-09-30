/**
 * 实时行情条（从 `pages/LiveTrading.tsx` 拆出，铁律 9，2026-09-30：该页 725 行，超页面软上限 600）。
 *
 * 8 个常用标的的推送价 + 迷你走势，点击即把该标的（及其现价）填进下单表单。
 * 纯展示 + 一个 onPick 回调，无任何业务状态。
 */
import { MiniSpark } from '../charts'
import { Badge, Card } from '../ui'
import { fmtNum, signClass } from '../../lib/format'
import type { Quote } from '../../lib/types'

/** 行情条与 WebSocket 订阅共用的标的清单（页面也从这里取，保证两处一致）。 */
export const WATCH = ['SPY', 'QQQ', 'NVDA', 'AAPL', 'TSLA', 'MSFT', 'AMD', 'META']

export default function QuoteStrip({
  quotes,
  sparks,
  wsStatus,
  onPick,
}: {
  quotes: Record<string, Quote>
  sparks: Record<string, number[]>
  wsStatus: 'open' | 'closed' | 'error' | 'connecting'
  /** 点击某标的：把 symbol（及可选现价）填进下单表单 */
  onPick: (symbol: string, price?: number) => void
}) {
  return (
    <Card title="实时行情" subtitle="通过 WebSocket 推送，8 秒刷新一次" actions={<Badge tone={wsStatus === 'open' ? 'green' : 'amber'} dot>{wsStatus === 'open' ? 'LIVE' : 'OFFLINE'}</Badge>}>
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4 lg:grid-cols-8">
        {WATCH.map((s) => {
          const q = quotes[s]
          const spark = sparks[s] || []
          const up = (q?.change ?? 0) >= 0
          return (
            <button
              key={s}
              onClick={() => onPick(s, q?.price)}
              className="rounded-lg border border-slate-200 p-2.5 text-left transition-colors hover:border-brand-300 hover:bg-brand-50/40"
            >
              <div className="flex items-center justify-between">
                <span className="text-xs font-semibold text-slate-700">{s}</span>
                <span className={`num text-[10px] font-medium ${signClass(q?.change_pct)}`}>
                  {q ? `${q.change_pct > 0 ? '+' : ''}${q.change_pct.toFixed(2)}%` : '—'}
                </span>
              </div>
              <div className="num mt-0.5 text-sm font-semibold text-slate-900">{q ? fmtNum(q.price, 2) : '—'}</div>
              <div className="mt-1">
                {spark.length > 2 ? <MiniSpark data={spark} positive={up} height={22} width={80} /> : <div className="h-[22px]" />}
              </div>
            </button>
          )
        })}
      </div>
    </Card>
  )
}
