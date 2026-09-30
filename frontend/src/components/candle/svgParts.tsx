// 蜡烛图 SVG 子组件：成交量副图、蜡烛、极值标注、十字光标（返回 <g>/<text> 等原生 SVG 片段）
import { fmtDate, fmtNum } from '../../lib/format'
import { PAD_B, PAD_L, PAD_T } from './overlays'

/** 成交量副图（SVG <g>）：按涨跌着色的量柱 + 20 日均量线。 */
export function VolumePane({
  volume, open, close, i0, span, xOf, yVol, bw, height, innerW, volH, up, down,
}: {
  volume: number[]
  open: number[]
  close: number[]
  i0: number
  span: number
  xOf: (i: number) => number
  yVol: (v: number) => number
  bw: number
  height: number
  innerW: number
  volH: number
  up: string
  down: string
}) {
  return (
    <>
      <text x={PAD_L + innerW + 6} y={height - PAD_B - volH / 2} fontSize={9} fill="#cbd5e1">
        量
      </text>
      {Array.from({ length: span }, (_, k) => {
        const i = i0 + k
        const v = volume[i]
        if (!Number.isFinite(v)) return null
        const isUp = close[i] >= open[i]
        const c = isUp ? up : down
        const y = yVol(v)
        return (
          <rect
            key={i}
            x={xOf(i) - Math.max(1, bw * 0.32)}
            y={y}
            width={Math.max(1, bw * 0.64)}
            height={Math.max(1, height - PAD_B - y)}
            fill={c}
            opacity={0.42}
          />
        )
      })}
      {/* 20 日均量线（放量/缩量一眼可辨） */}
      <VolumeMAPath volume={volume} i0={i0} i1={i0 + span - 1} xOf={xOf} yVol={yVol} />
    </>
  )
}

/** 20 日均量线 path 子组件。 */
function VolumeMAPath({
  volume, i0, i1, xOf, yVol,
}: {
  volume: number[]
  i0: number
  i1: number
  xOf: (i: number) => number
  yVol: (v: number) => number
}) {
  const pts: string[] = []
  for (let i = i0; i <= i1; i++) {
    if (i < 20 || !Number.isFinite(volume[i])) continue
    let s = 0
    for (let j = i - 19; j <= i; j++) s += Number(volume[j]) || 0
    const mv = s / 20
    if (!Number.isFinite(mv) || mv <= 0) continue
    pts.push(`${pts.length === 0 ? 'M' : 'L'}${xOf(i).toFixed(1)},${yVol(mv).toFixed(1)}`)
  }
  return (
    <path
      d={pts.join(' ')}
      fill="none"
      stroke="#f59e0b"
      strokeWidth={1}
      strokeDasharray="2 2"
      opacity={0.9}
    />
  )
}

/** 蜡烛实体 + 上下影线（SVG <g> 列表）。 */
export function Candles({
  open, high, low, close, i0, span, xOf, yOf, bw, up, down,
}: {
  open: number[]
  high: number[]
  low: number[]
  close: number[]
  i0: number
  span: number
  xOf: (i: number) => number
  yOf: (p: number) => number
  bw: number
  up: string
  down: string
}) {
  return (
    <>
      {Array.from({ length: span }, (_, k) => {
        const i = i0 + k
        const o = open[i]
        const c = close[i]
        const h = high[i]
        const l = low[i]
        if (![o, c, h, l].every(Number.isFinite)) return null
        const isUp = c >= o
        const col = isUp ? up : down
        const yO = yOf(o)
        const yC = yOf(c)
        const top = Math.min(yO, yC)
        const bodyH = Math.max(1, Math.abs(yC - yO))
        const w = Math.max(1.2, bw * 0.66)
        return (
          <g key={i}>
            <line x1={xOf(i)} y1={yOf(h)} x2={xOf(i)} y2={yOf(l)} stroke={col} strokeWidth={1} />
            <rect x={xOf(i) - w / 2} y={top} width={w} height={bodyH} fill={col} stroke={col} strokeWidth={0.5} />
          </g>
        )
      })}
    </>
  )
}

/** 区间最高 / 最低点标注（SVG <g>）：圆点 + 数值 + 日期（白描边保证可读性）。 */
export function ExtremesMarkers({
  extremes, dates, xOf, yOf, hiX, loX, hiY, loY, hiTextY, loTextY, up, down,
}: {
  extremes: { hiIdx: number; loIdx: number; hiVal: number; loVal: number }
  dates: string[]
  xOf: (i: number) => number
  yOf: (p: number) => number
  hiX: number
  loX: number
  hiY: number
  loY: number
  hiTextY: number
  loTextY: number
  up: string
  down: string
}) {
  return (
    <>
      <g>
        <circle cx={xOf(extremes.hiIdx)} cy={hiY} r={3} fill={up} stroke="#fff" strokeWidth={1} />
        <text
          x={hiX} y={hiTextY} fontSize={10.5} fontWeight={700} fill={up} textAnchor="middle"
          stroke="#fff" strokeWidth={3} paintOrder="stroke" className="num"
        >
          最高 {fmtNum(extremes.hiVal, 2)}
        </text>
        <text
          x={hiX} y={hiTextY + 11} fontSize={9} fill="#64748b" textAnchor="middle"
          stroke="#fff" strokeWidth={3} paintOrder="stroke" className="num"
        >
          {fmtDate(dates[extremes.hiIdx])}
        </text>
      </g>
      {extremes.loIdx !== extremes.hiIdx && (
        <g>
          <circle cx={xOf(extremes.loIdx)} cy={loY} r={3} fill={down} stroke="#fff" strokeWidth={1} />
          <text
            x={loX} y={loTextY} fontSize={10.5} fontWeight={700} fill={down} textAnchor="middle"
            stroke="#fff" strokeWidth={3} paintOrder="stroke" className="num"
          >
            最低 {fmtNum(extremes.loVal, 2)}
          </text>
          <text
            x={loX} y={loTextY + 11} fontSize={9} fill="#64748b" textAnchor="middle"
            stroke="#fff" strokeWidth={3} paintOrder="stroke" className="num"
          >
            {fmtDate(dates[extremes.loIdx])}
          </text>
        </g>
      )}
    </>
  )
}

/** 十字光标（SVG <g>）：竖线 + 收盘价横线 + 右侧价格标签。 */
export function Crosshair({
  hov, close, xOf, yOf, innerW, height, color,
}: {
  hov: number
  close: number[]
  xOf: (i: number) => number
  yOf: (p: number) => number
  innerW: number
  height: number
  color: string
}) {
  return (
    <>
      <line
        x1={xOf(hov)}
        y1={PAD_T}
        x2={xOf(hov)}
        y2={height - PAD_B}
        stroke="#94a3b8"
        strokeWidth={1}
        strokeDasharray="3 3"
      />
      <line
        x1={PAD_L}
        y1={yOf(close[hov])}
        x2={PAD_L + innerW}
        y2={yOf(close[hov])}
        stroke="#94a3b8"
        strokeWidth={1}
        strokeDasharray="3 3"
      />
      <rect x={PAD_L + innerW + 2} y={yOf(close[hov]) - 8} width={56} height={16} rx={3} fill={color} />
      <text x={PAD_L + innerW + 6} y={yOf(close[hov]) + 3.5} fontSize={10} fill="#fff" className="num">
        {fmtNum(close[hov], 2)}
      </text>
    </>
  )
}
