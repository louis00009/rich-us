import { ReactNode } from 'react'
import { fmtCompact, fmtPct, downColor, upColor } from '../../lib/format'
import { RankingColumn } from '../../lib/rankingColumns'
import { ScoreCell } from './ScoreCell'
import { SignalBadges } from './SignalCell'
import type { Handlers, RankRow } from './RankingsTable'

/**
 * 榜单表格的**单元格渲染层**。
 *
 * 从 `RankingsTable.tsx` 拆出来（铁律 9：组件 400 行软上限）—— 表格组件负责
 * 表头、排序交互、列可见性与骨架；「某个指标怎么画」是另一件事，单独放这里。
 * 加一个指标只需要在本文件补一个 case，不用碰表格逻辑。
 *
 * ⚠️ 这里对 `RankRow` / `Handlers` 只用 `import type` —— 类型导入在编译时被抹掉，
 * 因此运行时不产生循环依赖（RankingsTable → cells 是单向的）。
 */

/** PE 超过这个值单独打「异常」标：多为一次性损益造成的失真，参与排序会污染榜单。 */
export const PE_EXTREME = 200

export const DASH = <span className="text-slate-300">—</span>

/** 估值分位色条：**刻意不用涨红跌绿** —— 估值高低不是涨跌，用红绿会和行情语义打架。 */
export function PctBar({ pct }: { pct: number }) {
  const color = pct <= 33 ? '#3b82f6' : pct <= 66 ? '#94a3b8' : '#f59e0b'
  return (
    <span
      title={`PE 处于同行业第 ${pct} 分位（越靠左越便宜）`}
      className="inline-block h-1 w-8 shrink-0 overflow-hidden rounded-full bg-slate-100 align-middle"
    >
      <span className="block h-full rounded-full" style={{ width: `${Math.max(6, pct)}%`, background: color }} />
    </span>
  )
}

export function PeCell({ row }: { row: RankRow }) {
  if (row.pe_state === 'loss') {
    return <span className="rounded bg-slate-100 px-1.5 py-0.5 text-[10px] text-slate-400">亏损</span>
  }
  const pe = row.pe_ttm
  if (typeof pe !== 'number') return DASH
  const extreme = pe > PE_EXTREME
  return (
    <span className="inline-flex items-center justify-end gap-1.5">
      <span className={extreme ? 'font-medium text-amber-700' : ''}>{pe >= 100 ? pe.toFixed(0) : pe.toFixed(1)}</span>
      {extreme ? (
        <span
          title="PE > 200，多为一次性损益造成的失真，不参与估值排序"
          className="rounded bg-amber-50 px-1 py-px text-[10px] text-amber-700"
        >
          异常
        </span>
      ) : typeof row.pe_pct === 'number' ? (
        <PctBar pct={row.pe_pct} />
      ) : null}
    </span>
  )
}

/** 技术指标的通用「带符号百分比」渲染：正数用涨色、负数用跌色。 */
export function SignedPct({ v, digits = 1 }: { v?: number | null; digits?: number }) {
  if (typeof v !== 'number') return DASH
  return (
    <span className="tabular-nums" style={{ color: v >= 0 ? upColor() : downColor() }}>
      {v > 0 ? '+' : ''}
      {v.toFixed(digits)}%
    </span>
  )
}

/** RSI 着色：超买（>70）琥珀、超卖（<30）蓝 —— 同样不用红绿（不是涨跌）。 */
export function RsiCell({ v }: { v?: number | null }) {
  if (typeof v !== 'number') return DASH
  const cls = v > 70 ? 'text-amber-700' : v < 30 ? 'text-blue-600' : 'text-slate-600'
  return <span className={`tabular-nums ${cls}`}>{v.toFixed(1)}</span>
}

/** 均线排列标记：多头 / 空头 / 震荡 / 无数据。 */
export function MaCell({ row }: { row: RankRow }) {
  if (row.ma_bull === true) {
    return <span className="rounded bg-brand-50 px-1.5 py-0.5 text-[10px] text-brand-700">多头</span>
  }
  if (row.ma_bull === false && row.ma_bear === true) {
    return <span className="rounded bg-slate-100 px-1.5 py-0.5 text-[10px] text-slate-500">空头</span>
  }
  if (row.ma_bull === false) {
    return <span className="text-[10px] text-slate-400">震荡</span>
  }
  return DASH
}

/** 单列取值渲染。加指标只需要在这里补一个 case。 */
export function cell(col: RankingColumn, row: RankRow, handlers: Handlers): ReactNode {
  switch (col.key) {
    case 'score':
      return <ScoreCell row={row} />
    case 'signals':
      return <SignalBadges signals={row.signals} catalog={handlers.catalog} onClick={handlers.onPickSignal} />
    case 'symbol':
      return (
        <div className="min-w-0">
          <button
            onClick={() => handlers.onOpenProfile(row.symbol)}
            className="block font-semibold text-slate-800 hover:text-brand-700 hover:underline"
            title="查看公司档案"
          >
            {row.symbol}
          </button>
          <div className="truncate text-[11px] text-slate-400" title={row.name_cn ? `${row.name_cn} · ${row.name}` : row.name}>
            {row.name_cn || row.name}
          </div>
        </div>
      )
    case 'price':
      return <span className="tabular-nums">{row.price != null ? Number(row.price).toFixed(2) : '—'}</span>
    case 'change_pct':
      return (
        <span className="tabular-nums" style={{ color: row.change_pct == null ? undefined : row.change_pct >= 0 ? upColor() : downColor() }}>
          {fmtPct(row.change_pct, 2, true)}
        </span>
      )
    case 'volume':
      return <span className="tabular-nums text-slate-500">{fmtCompact(row.volume)}</span>
    case 'amount':
      return <span className="tabular-nums text-slate-500">{fmtCompact(row.amount)}</span>
    case 'market_cap':
      return <span className="tabular-nums text-slate-500">{fmtCompact(row.market_cap)}</span>
    case 'market_cap_float':
      return <span className="tabular-nums text-slate-500">{fmtCompact(row.market_cap_float)}</span>
    case 'pe_ttm':
      return <PeCell row={row} />
    case 'eps_ttm':
      return typeof row.eps_ttm === 'number' ? (
        <span className="tabular-nums">{row.eps_ttm.toFixed(2)}</span>
      ) : (
        DASH
      )
    case 'pb':
      return typeof row.pb === 'number' ? <span className="tabular-nums">{row.pb.toFixed(2)}</span> : DASH
    case 'roe':
      return typeof row.roe === 'number' ? (
        <span className="tabular-nums" style={{ color: row.roe >= 15 ? '#0f766e' : undefined }}>
          {row.roe.toFixed(1)}%
        </span>
      ) : (
        DASH
      )
    case 'div_yield':
      return typeof row.div_yield === 'number' ? (
        <span className="tabular-nums text-slate-600">{row.div_yield.toFixed(2)}%</span>
      ) : (
        DASH
      )
    case 'turnover':
      return typeof row.turnover === 'number' ? (
        <span className="tabular-nums text-slate-500">{row.turnover.toFixed(2)}%</span>
      ) : (
        DASH
      )
    case 'amplitude':
      return typeof row.amplitude === 'number' ? (
        <span className="tabular-nums text-slate-500">{row.amplitude.toFixed(2)}%</span>
      ) : (
        DASH
      )
    case 'w52_high':
      return typeof row.w52_high === 'number' ? <span className="tabular-nums text-slate-500">{row.w52_high.toFixed(2)}</span> : DASH
    case 'w52_low':
      return typeof row.w52_low === 'number' ? <span className="tabular-nums text-slate-500">{row.w52_low.toFixed(2)}</span> : DASH
    case 'pct_from_high':
      return typeof row.pct_from_high === 'number' ? (
        <span className="tabular-nums text-slate-600">{row.pct_from_high.toFixed(1)}%</span>
      ) : (
        DASH
      )
    case 'sector':
      return <span className="text-xs text-slate-400">{row.sector}</span>
    /* ---- 技术指标 ---- */
    case 'ma200_rel':
    case 'ma20_rel':
    case 'ma60_rel':
      return <SignedPct v={row[col.key]} />
    case 'ma_bull':
      return <MaCell row={row} />
    case 'r1m':
    case 'r3m':
    case 'r6m':
    case 'r1y':
    case 'excess_1y':
      return <SignedPct v={row[col.key]} />
    case 'rsi14':
      return <RsiCell v={row.rsi14} />
    case 'vol_ann':
      return typeof row.vol_ann === 'number' ? (
        <span className={`tabular-nums ${row.vol_ann > 60 ? 'text-amber-700' : 'text-slate-500'}`}>
          {row.vol_ann.toFixed(0)}%
        </span>
      ) : (
        DASH
      )
    case 'atr_pct':
      return typeof row.atr_pct === 'number' ? (
        <span className="tabular-nums text-slate-500">{row.atr_pct.toFixed(2)}%</span>
      ) : (
        DASH
      )
    case 'beta':
      return typeof row.beta === 'number' ? (
        <span className={`tabular-nums ${row.beta > 1.5 ? 'text-amber-700' : 'text-slate-600'}`}>
          {row.beta.toFixed(2)}
        </span>
      ) : (
        DASH
      )
    default:
      return DASH
  }
}
