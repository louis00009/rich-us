/**
 * 图表 · 价格与迷你走势（PriceChart / MiniSpark）
 *
 * 从 `components/charts.tsx` 拆出（铁律 9）。
 * 配色：涨红跌绿（中国习惯），可在设置中切换。
 */
import { memo } from 'react'
import {
  Area,
  AreaChart,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ReferenceDot,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { downColor, fmtDate, fmtNum, upColor } from '../../lib/format'
import { AXIS, GRID } from './shared'

function PriceChartImpl({
  dates,
  close,
  overlays = [],
  levels = [],
  height = 300,
  mini = false,
}: {
  dates: string[]
  close: number[]
  overlays?: { name: string; data: (number | null)[]; color: string; dashed?: boolean }[]
  levels?: { value: number; label: string; color?: string }[]
  height?: number
  mini?: boolean
}) {
  const rows = dates.map((d, i) => {
    const o: any = { date: d, close: close[i] }
    overlays.forEach((ov) => (o[ov.name] = ov.data[i]))
    return o
  })
  if (!rows.length) return <div className="py-16 text-center text-sm text-slate-400">暂无行情数据</div>
  const values = close.filter((c) => Number.isFinite(c))
  const lo = Math.min(...values)
  const hi = Math.max(...values)
  const pad = (hi - lo) * 0.06 || 1

  // 最高 / 最低点标注（含日期）
  const n = close.length
  let hiIdx = -1
  let loIdx = -1
  close.forEach((c, i) => {
    if (!Number.isFinite(c)) return
    if (hiIdx < 0 || c > close[hiIdx]) hiIdx = i
    if (loIdx < 0 || c < close[loIdx]) loIdx = i
  })
  const first = close.find(Number.isFinite)
  const firstIdx = close.findIndex(Number.isFinite)
  const last = values[values.length - 1]
  const rangeChg = first ? ((last / first - 1) * 100) : 0
  const UP = upColor()
  const DOWN = downColor()
  const TipLine = ({ payload }: any) => {
    if (!payload?.length) return null
    const d = payload[0]?.payload
    const prevIdx = dates.indexOf(d.date) - 1
    const prev = prevIdx >= 0 ? close[prevIdx] : first
    const chg = prev ? ((d.close / prev - 1) * 100) : 0
    return (
      <div className="rounded-lg border border-slate-200 bg-white/95 px-2.5 py-1.5 text-[11px] shadow-pop">
        <div className="mb-0.5 font-semibold text-slate-700">{fmtDate(d.date)}</div>
        <div className="num text-slate-800">
          收盘 <b>{fmtNum(d.close, 2)}</b>
          <span className="ml-2" style={{ color: chg >= 0 ? UP : DOWN }}>
            {chg >= 0 ? '+' : ''}{chg.toFixed(2)}%
          </span>
        </div>
        {overlays.map((ov) => (
          <div key={ov.name} className="num text-slate-500">
            {ov.name} {Number.isFinite(d[ov.name]) ? fmtNum(d[ov.name], 2) : '—'}
          </div>
        ))}
      </div>
    )
  }

  return (
    <ResponsiveContainer width="100%" height={height}>
      <LineChart data={rows} margin={{ top: 14, right: 12, bottom: 0, left: 0 }}
        onMouseMove={undefined}>
        <CartesianGrid stroke={GRID} vertical={false} />
        <XAxis dataKey="date" tick={AXIS} tickLine={false} axisLine={false} minTickGap={70} tickFormatter={fmtDate} />
        <YAxis
          tick={AXIS}
          tickLine={false}
          axisLine={false}
          width={58}
          domain={[lo - pad, hi + pad]}
          tickFormatter={(v) => fmtNum(v, v > 100 ? 0 : 2)}
        />
        {!mini && <Tooltip cursor={{ stroke: '#94a3b8', strokeDasharray: '3 3' }} content={<TipLine />} />}
        {!mini && <Legend wrapperStyle={{ fontSize: 11, color: '#64748b' }} iconType="plainline" />}
        {levels.map((l, i) => (
          <ReferenceLine
            key={i}
            y={l.value}
            stroke={l.color || '#cbd5e1'}
            strokeDasharray="3 3"
            label={{ value: l.label, position: 'insideTopRight', fontSize: 10, fill: l.color || '#94a3b8' }}
          />
        ))}
        {/* 区间涨跌幅（右上角） */}
        {!mini && (
          <text x="98%" y="12" textAnchor="end" fontSize={11} fill={rangeChg >= 0 ? UP : DOWN} className="num">
            区间 {rangeChg >= 0 ? '+' : ''}{rangeChg.toFixed(2)}%
          </text>
        )}
        {/* 最高 / 最低点标注 */}
        {!mini && hiIdx >= 0 && (
          <ReferenceDot
            x={dates[hiIdx]} y={close[hiIdx]} r={3.5}
            fill={UP} stroke="#fff" strokeWidth={1}
            isFront
            label={{ value: `▲高 ${fmtNum(close[hiIdx], 2)}`, position: 'top', fontSize: 10, fill: UP }}
          />
        )}
        {!mini && loIdx >= 0 && loIdx !== hiIdx && (
          <ReferenceDot
            x={dates[loIdx]} y={close[loIdx]} r={3.5}
            fill={DOWN} stroke="#fff" strokeWidth={1}
            isFront
            label={{ value: `▼低 ${fmtNum(close[loIdx], 2)}`, position: 'bottom', fontSize: 10, fill: DOWN }}
          />
        )}
        {/* 数据点数值标注：点少时全量标，点多多抽稀至 ~32 个；普通点黑色，最高/最低保持彩色 */}
        {!mini && n <= 64 && (
          <Line
            type="monotone" dataKey="close" name="收盘价" stroke="#0f172a" strokeWidth={1.6}
            dot={{ r: 2, fill: '#334155', strokeWidth: 0 }}
            label={n <= 64 ? ((props: any) => {
              const { x, y, value, index } = props
              const step = Math.ceil(n / 32)
              if (index % step !== 0 || index === hiIdx || index === loIdx) return null
              const above = index % 2 === 0
              return (
                <text x={x} y={above ? y - 7 : y + 15} textAnchor="middle" fontSize={9} fill="#334155">
                  {fmtNum(value, value > 100 ? 1 : 2)}
                </text>
              )
            }) as any : false}
            activeDot={{ r: 4 }}
          />
        )}
        {(!mini && n > 64) && (
          <Line type="monotone" dataKey="close" name="收盘价" stroke="#0f172a" strokeWidth={1.6} dot={false}
            activeDot={{ r: 4 }} />
        )}
        {overlays.map((ov) => (
          <Line
            key={ov.name}
            type="monotone"
            dataKey={ov.name}
            name={ov.name}
            stroke={ov.color}
            strokeWidth={1.2}
            strokeDasharray={ov.dashed ? '4 3' : undefined}
            dot={false}
            connectNulls
          />
        ))}
      </LineChart>
    </ResponsiveContainer>
  )
}

function MiniSparkImpl({
  data,
  positive,
  height = 36,
  width = 110,
}: {
  data: number[]
  positive: boolean
  height?: number
  width?: number
}) {
  if (!data || data.length < 2) return <div style={{ width, height }} />
  const rows = data.map((v, i) => ({ i, v }))
  const color = positive ? upColor() : downColor()
  const id = `sp${positive ? 'u' : 'd'}`
  return (
    <ResponsiveContainer width={width} height={height}>
      <AreaChart data={rows} margin={{ top: 2, right: 0, bottom: 2, left: 0 }}>
        <defs>
          <linearGradient id={id} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={color} stopOpacity={0.3} />
            <stop offset="100%" stopColor={color} stopOpacity={0} />
          </linearGradient>
        </defs>
        <Area type="monotone" dataKey="v" stroke={color} strokeWidth={1.4} fill={`url(#${id})`} dot={false} />
      </AreaChart>
    </ResponsiveContainer>
  )
}

export const PriceChart = memo(PriceChartImpl)
export const MiniSpark = memo(MiniSparkImpl)
