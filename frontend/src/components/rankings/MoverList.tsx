import { downClass, fmtCompact, fmtNum, signClass, upClass } from '../../lib/format'
import type { MoverRow } from './moverTypes'

/** 双榜单侧列表：行组件（涨跌色、徽章、量比）纯展示，无自有状态。 */
export function MoverList({
  rows,
  side,
  threshold,
  onOpenProfile,
}: {
  rows: MoverRow[]
  side: 'up' | 'down'
  threshold: number
  onOpenProfile: (sym: string) => void
}) {
  const colorCls = side === 'up' ? upClass() : downClass()
  const label = side === 'up' ? `暴涨 ≥ +${threshold}%` : `暴跌 ≤ -${threshold}%`
  return (
    <div className="min-w-0">
      <div className={`mb-1.5 flex items-center justify-between text-[11px] font-semibold ${colorCls}`}>
        <span>{label}</span>
        <span className="num font-normal text-slate-400">{rows.length} 只</span>
      </div>
      {rows.length === 0 ? (
        <p className="py-3 text-center text-[11px] text-slate-300">暂无触发</p>
      ) : (
        <div className="divide-y divide-slate-50">
          {rows.map((r) => (
            <button
              key={`${r.symbol}-${r.src ?? 'pool'}`}
              onClick={() => onOpenProfile(r.symbol)}
              className="flex w-full items-center gap-2 rounded px-1 py-1.5 text-left transition-colors hover:bg-slate-50"
              title={`查看 ${r.symbol}${r.first_seen ? ` · 首次上榜 ${(r.first_seen || '').slice(11, 19)}` : ''}`}
            >
              <div className="min-w-0 flex-1">
                <div className="flex items-baseline gap-1.5">
                  <span className="text-xs font-semibold text-slate-800">{r.symbol}</span>
                  <span className="truncate text-[10px] text-slate-400">{r.name_cn || r.name}</span>
                  {r.src === 'market' && (
                    <span className="shrink-0 rounded bg-sky-50 px-1 text-[9px] font-medium text-sky-700" title="来自全市场涨跌幅榜（不在本地池内）">
                      全市场
                    </span>
                  )}
                  {!!r.hits && r.hits > 1 && (
                    <span className="num rounded bg-amber-50 px-1 text-[9px] font-medium text-amber-700" title={`今日第 ${r.hits} 次上榜`}>
                      ×{r.hits}
                    </span>
                  )}
                </div>
                <div className="mt-0.5 flex items-center gap-2 text-[10px] text-slate-400">
                  <span className="num">${fmtNum(r.price)}</span>
                  {!!r.vol_ratio && r.vol_ratio >= 1 && (
                    <span className="num text-slate-500" title="量比 = 今日成交量 ÷ 近期日均量（盘中小于 1 属正常）">
                      量比 {r.vol_ratio.toFixed(1)}
                    </span>
                  )}
                  {r.amount ? <span className="num">{fmtCompact(r.amount)}</span> : null}
                </div>
              </div>
              <span className={`num shrink-0 text-sm font-semibold ${signClass(r.change_pct)}`}>
                {r.change_pct != null ? `${r.change_pct > 0 ? '+' : ''}${r.change_pct.toFixed(2)}%` : '—'}
              </span>
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
