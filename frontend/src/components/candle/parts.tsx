// 蜡烛图展示子块（HTML 层）：浮动 tooltip、悬停信息条、缩放条、图例
// SVG 层子块见 svgParts.tsx，纯几何计算见 overlays.ts。
import { Fragment } from 'react'
import { downClass, fmtCompact, fmtDate, fmtNum, upClass } from '../../lib/format'
import { PAD_T, MIN_BARS } from './overlays'
import type { CandleOverlay } from './types'

/** 浮动 tooltip：跟随光标，显示日期 + OHLC + 量 + 叠加线数值。 */
export function ChartTooltip({
  hov, hovX, tipLeft, dates, open, high, low, close, volume, overlays, hovUp,
}: {
  hov: number
  hovX: number
  tipLeft: number
  dates: string[]
  open: number[]
  high: number[]
  low: number[]
  close: number[]
  volume?: number[]
  overlays: CandleOverlay[]
  hovUp: boolean
}) {
  return (
    <div
      className="pointer-events-none absolute z-20 w-44 rounded-lg border border-slate-200 bg-white/95 px-3 py-2 text-[11px] shadow-pop"
      style={{ top: PAD_T + 4, left: tipLeft }}
    >
      <div className="mb-1 border-b border-dashed border-slate-100 pb-1 font-semibold text-slate-700 num">
        {fmtDate(dates[hov])}
      </div>
      <div className="grid grid-cols-2 gap-x-2 gap-y-0.5 num">
        <span className="text-slate-400">开</span>
        <b className={hovUp ? upClass() : downClass()}>{fmtNum(open[hov], 2)}</b>
        <span className="text-slate-400">高</span>
        <b className="text-slate-800">{fmtNum(high[hov], 2)}</b>
        <span className="text-slate-400">低</span>
        <b className="text-slate-800">{fmtNum(low[hov], 2)}</b>
        <span className="text-slate-400">收</span>
        <b className={hovUp ? upClass() : downClass()}>{fmtNum(close[hov], 2)}</b>
        {volume && Number.isFinite(volume[hov]) && (
          <>
            <span className="text-slate-400">量</span>
            <b className="text-slate-600">{fmtCompact(volume[hov])}</b>
          </>
        )}
        {overlays.map((o) => {
          const v = o.data[hov]
          if (v === null || v === undefined || !Number.isFinite(v)) return null
          return (
            <Fragment key={o.name}>
              <span className="flex items-center gap-1 text-slate-400">
                <span className="inline-block h-0.5 w-2.5 rounded" style={{ background: o.color }} />
                {o.name}
              </span>
              <b className="text-slate-800">{fmtNum(v, 2)}</b>
            </Fragment>
          )
        })}
      </div>
    </div>
  )
}

/** 悬停信息条：hover 时显示逐根 OHLC，否则显示区间统计。 */
export function HoverInfoBar({
  hov, n, span, changePct, dates, open, high, low, close, volume, hovUp,
}: {
  hov: number | null
  n: number
  span: number
  changePct: number
  dates: string[]
  open: number[]
  high: number[]
  low: number[]
  close: number[]
  volume?: number[]
  hovUp: boolean
}) {
  return (
    <div className="mb-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs">
      {hov !== null ? (
        <>
          <span className="num text-slate-400">{fmtDate(dates[hov])}</span>
          <span className="num text-slate-600">
            开 <b className={hovUp ? upClass() : downClass()}>{fmtNum(open[hov], 2)}</b>
          </span>
          <span className="num text-slate-600">
            高 <b className="text-slate-800">{fmtNum(high[hov], 2)}</b>
          </span>
          <span className="num text-slate-600">
            低 <b className="text-slate-800">{fmtNum(low[hov], 2)}</b>
          </span>
          <span className="num text-slate-600">
            收 <b className={hovUp ? upClass() : downClass()}>{fmtNum(close[hov], 2)}</b>
          </span>
          {volume && <span className="num text-slate-500">量 {fmtCompact(volume[hov])}</span>}
        </>
      ) : (
        <span className="text-slate-400">
          共 {n} 根 K 线 ｜ 可视 {span} 根 ｜ 区间涨跌{' '}
          <b className={changePct >= 0 ? upClass() : downClass()}>
            {changePct >= 0 ? '+' : ''}
            {changePct.toFixed(2)}%
          </b>
        </span>
      )}
    </div>
  )
}

/** 区间缩放 / 平移控制条。onShift(dir) 平移；onRangeInput(s) 为滑条直接设根数（右端固定）；onZoom(factor) 锚点缩放；onReset 重置。 */
export function ZoomBar({
  span, n, onShift, onRangeInput, onZoom, onReset,
}: {
  span: number
  n: number
  onShift: (dir: -1 | 1) => void
  onRangeInput: (s: number) => void
  onZoom: (factor: number) => void
  onReset: () => void
}) {
  return (
    <div className="mt-3 flex items-center gap-2">
      <span className="shrink-0 text-[11px] text-slate-400">可视区间</span>
      <button
        type="button"
        onClick={() => onShift(-1)}
        className="h-6 w-6 shrink-0 rounded border border-slate-200 text-xs text-slate-500 hover:bg-slate-50"
        title="向左平移（更早）"
      >
        ‹
      </button>
      <input
        type="range"
        min={MIN_BARS}
        max={n}
        value={span}
        onChange={(e) => {
          const s = parseInt(e.target.value, 10)
          onRangeInput(s)
        }}
        className="h-1 flex-1 cursor-pointer appearance-none rounded bg-slate-200 accent-brand-600"
      />
      <button
        type="button"
        onClick={() => onShift(1)}
        className="h-6 w-6 shrink-0 rounded border border-slate-200 text-xs text-slate-500 hover:bg-slate-50"
        title="向右平移（更近）"
      >
        ›
      </button>
      <button
        type="button"
        onClick={() => onZoom(1 / 1.4)}
        className="h-6 shrink-0 rounded border border-slate-200 px-1.5 text-[11px] text-slate-500 hover:bg-slate-50"
        title="放大"
      >
        放大
      </button>
      <button
        type="button"
        onClick={() => onZoom(1.4)}
        className="h-6 shrink-0 rounded border border-slate-200 px-1.5 text-[11px] text-slate-500 hover:bg-slate-50"
        title="缩小"
      >
        缩小
      </button>
      <button
        type="button"
        onClick={onReset}
        className="h-6 shrink-0 rounded border border-slate-200 px-1.5 text-[11px] text-slate-500 hover:bg-slate-50"
        title="重置视图（双击图表亦可）"
      >
        重置
      </button>
      <span className="num shrink-0 text-[11px] text-slate-500">
        {span} / {n} 根
      </span>
    </div>
  )
}

/** 底部图例：叠加线 + 涨跌配色说明。 */
export function ChartLegend({
  overlays, up, down, colorMode,
}: {
  overlays: CandleOverlay[]
  up: string
  down: string
  colorMode: string
}) {
  return (
    <>
      {overlays.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-3">
          {overlays.map((o) => (
            <span key={o.name} className="flex items-center gap-1.5 text-[11px] text-slate-500">
              <span className="inline-block h-0.5 w-4 rounded" style={{ background: o.color }} />
              {o.name}
            </span>
          ))}
        </div>
      )}
      <div className="mt-1 flex flex-wrap gap-3 text-[11px] text-slate-400">
        <span className="flex items-center gap-1.5">
          <span className="inline-block h-2 w-2 rounded-sm" style={{ background: up }} />
          涨
        </span>
        <span className="flex items-center gap-1.5">
          <span className="inline-block h-2 w-2 rounded-sm" style={{ background: down }} />
          跌
        </span>
        <span>配色遵循{colorMode === 'cn' ? '中国习惯（红涨绿跌）' : '欧美习惯（绿涨红跌）'}</span>
      </div>
    </>
  )
}
