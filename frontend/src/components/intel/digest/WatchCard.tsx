/**
 * 时机卡：关注区间 / 触发条件 / 失效条件
 *
 * 对应用户需求「什么时机是一个好的机会」。价位全部取自平台量化支撑阻力与 ATR，
 * 取不到就写「数据未覆盖」—— 不做估算，也不构成买入指令。
 *
 * 从 DailyDigest.tsx 抽出（铁律 9 拆分，2026-09-29）。
 */
import { fmtNum } from '../../../lib/format'
import { type Digest, REC_LABEL, recBg } from '../types'

export function WatchCard({ w }: { w: Digest['watch'][number] }) {
  const hasZone = w.zone_low != null && w.zone_high != null
  return (
    <li className="rounded-lg border border-slate-100 bg-white p-3">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-sm font-bold text-slate-900">{w.symbol}</span>
        <span className="min-w-0 max-w-[160px] truncate text-[11px] text-slate-400">{w.name || w.theme || '—'}</span>
        {(w.event_date || w.event_at) && (
          <span
            className="num shrink-0 rounded bg-slate-100 px-1.5 py-0.5 text-[11px] font-medium text-slate-500"
            title={`依据事件发生时间：${w.event_at || w.event_date || '未知'}`}
          >
            依据 {w.event_date || (w.event_at || '').slice(0, 10)}
            {w.event_at && w.event_at.length > 10 ? ` ${w.event_at.slice(11, 16)}` : ''}
          </span>
        )}
        {w.recommendation && (
          <span
            className="rounded px-1.5 py-0.5 text-[11px] font-semibold text-white"
            style={{ background: recBg(w.recommendation) }}
          >
            {REC_LABEL[w.recommendation]}
            {w.confidence != null ? ` ${w.confidence.toFixed(0)}%` : ''}
          </span>
        )}
        <span className="ml-auto text-[11px] text-slate-400">{w.reason}</span>
      </div>

      <div className="mt-2 grid grid-cols-2 gap-2 md:grid-cols-4">
        <div className="rounded bg-slate-50 px-2 py-1.5">
          <div className="text-[10px] text-slate-500">现价</div>
          <div className="num text-xs font-semibold text-slate-800">{w.price != null ? fmtNum(w.price) : '—'}</div>
        </div>
        <div className="rounded bg-slate-50 px-2 py-1.5">
          <div className="text-[10px] text-slate-500">关注区间（量化支撑）</div>
          <div className="num text-xs font-semibold text-brand-700">
            {hasZone ? `${fmtNum(w.zone_low)} ~ ${fmtNum(w.zone_high)}` : '数据未覆盖'}
          </div>
        </div>
        <div className="rounded bg-slate-50 px-2 py-1.5">
          <div className="text-[10px] text-slate-500">RSI14</div>
          <div className="num text-xs font-semibold text-slate-800">
            {w.rsi14 != null ? w.rsi14 : '—'}
            {w.rsi14 != null && w.rsi14 >= 70 && (
              <span className="ml-1 text-[10px] font-normal text-amber-600">超买</span>
            )}
          </div>
        </div>
        <div className="rounded bg-slate-50 px-2 py-1.5">
          <div className="text-[10px] text-slate-500">ATR14（日均波动）</div>
          <div className="num text-xs font-semibold text-slate-800">{w.atr14 != null ? fmtNum(w.atr14) : '—'}</div>
        </div>
      </div>

      {w.trigger && (
        <p className="mt-2 text-[11px] leading-relaxed text-slate-600">
          <b className="text-slate-700">触发条件：</b>
          {w.trigger}
        </p>
      )}
      {w.invalidation && (
        <p className="mt-1 text-[11px] leading-relaxed text-rose-600/90">
          <b>失效参考：</b>
          {w.invalidation}
        </p>
      )}
      {w.note && <p className="mt-1 text-[11px] text-slate-400">{w.note}</p>}
    </li>
  )
}
