/**
 * 图表组件（基于 recharts）
 * 配色：涨红跌绿（中国习惯），可在设置中切换
 */
import { memo } from 'react'
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ComposedChart,
  Legend,
  Line,
  LineChart,
  PolarAngleAxis,
  RadialBar,
  RadialBarChart,
  ReferenceDot,
  ReferenceLine,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { downColor, fmtCompact, fmtDate, fmtMoney, fmtNum, signClass, upColor } from '../lib/format'
import type { CurvePoint } from '../lib/types'

const AXIS = { fontSize: 10, fill: '#94a3b8' }
const GRID = '#eef2f7'

function TipBox({ active, payload, label, formatter }: any) {
  if (!active || !payload?.length) return null
  return (
    <div className="rounded-lg border border-slate-200 bg-white/95 px-3 py-2 text-xs shadow-pop backdrop-blur">
      <div className="mb-1 font-medium text-slate-600">{fmtDate(label)}</div>
      {payload.map((p: any, i: number) => (
        <div key={i} className="flex items-center justify-between gap-4">
          <span className="flex items-center gap-1.5 text-slate-500">
            <span className="h-2 w-2 rounded-sm" style={{ background: p.color || p.fill }} />
            {p.name}
          </span>
          <span className="num font-medium text-slate-800">
            {formatter ? formatter(p.value, p.dataKey) : fmtNum(p.value, 2)}
          </span>
        </div>
      ))}
    </div>
  )
}

/* ================================================================
 * 权益曲线 + 回撤
 * ================================================================ */
function EquityChartImpl({
  data,
  height = 320,
  showBenchmark = true,
  showDrawdown = true,
}: {
  data: CurvePoint[]
  height?: number
  showBenchmark?: boolean
  showDrawdown?: boolean
}) {
  if (!data.length) return <div className="py-16 text-center text-sm text-slate-400">暂无净值数据</div>
  return (
    <ResponsiveContainer width="100%" height={height}>
      <ComposedChart data={data} margin={{ top: 8, right: 12, bottom: 0, left: 0 }}>
        <defs>
          <linearGradient id="eqFill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#6366f1" stopOpacity={0.22} />
            <stop offset="100%" stopColor="#6366f1" stopOpacity={0.01} />
          </linearGradient>
          <linearGradient id="ddFill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#f43f5e" stopOpacity={0.05} />
            <stop offset="100%" stopColor="#f43f5e" stopOpacity={0.3} />
          </linearGradient>
        </defs>
        <CartesianGrid stroke={GRID} vertical={false} />
        <XAxis dataKey="date" tick={AXIS} tickLine={false} axisLine={false} minTickGap={60} tickFormatter={fmtDate} />
        <YAxis
          yAxisId="eq"
          tick={AXIS}
          tickLine={false}
          axisLine={false}
          width={62}
          tickFormatter={(v) => `$${fmtCompact(v)}`}
          domain={['auto', 'auto']}
        />
        {showDrawdown && (
          <YAxis
            yAxisId="dd"
            orientation="right"
            tick={AXIS}
            tickLine={false}
            axisLine={false}
            width={44}
            tickFormatter={(v) => `${(v * 100).toFixed(0)}%`}
            domain={[-1, 0]}
          />
        )}
        <Tooltip
          content={
            <TipBox
              formatter={(v: number, k: string) =>
                k === 'drawdown' ? `${(v * 100).toFixed(2)}%` : fmtMoney(v, 0)
              }
            />
          }
        />
        <Legend wrapperStyle={{ fontSize: 11, color: '#64748b' }} iconType="plainline" />
        {showBenchmark && (
          <Line
            yAxisId="eq"
            type="monotone"
            dataKey="benchmark"
            name="基准(买入持有)"
            stroke="#94a3b8"
            strokeWidth={1.3}
            strokeDasharray="4 3"
            dot={false}
          />
        )}
        <Area
          yAxisId="eq"
          type="monotone"
          dataKey="equity"
          name="策略净值"
          stroke="#4f46e5"
          strokeWidth={1.8}
          fill="url(#eqFill)"
          dot={false}
        />
        {showDrawdown && (
          <Area
            yAxisId="dd"
            type="monotone"
            dataKey="drawdown"
            name="回撤"
            stroke="none"
            fill="url(#ddFill)"
            dot={false}
            legendType="none"
          />
        )}
      </ComposedChart>
    </ResponsiveContainer>
  )
}

/* ================================================================
 * 价格图（含均线 + 支撑阻力）
 * ================================================================ */
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

/* ================================================================
 * 迷你走势图
 * ================================================================ */
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

/* ================================================================
 * 月度收益热力图
 * ================================================================ */
function MonthlyHeatmapImpl({ monthly }: { monthly: Record<string, number> }) {
  const entries = Object.entries(monthly).sort(([a], [b]) => a.localeCompare(b))
  if (!entries.length) return <div className="py-10 text-center text-sm text-slate-400">暂无月度数据</div>

  const years = Array.from(new Set(entries.map(([k]) => k.slice(0, 4)))).sort()
  const lookup = new Map(entries)
  const vals = entries.map(([, v]) => v)
  const maxAbs = Math.max(...vals.map((v) => Math.abs(v)), 0.01)

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs">
        <thead>
          <tr>
            <th className="px-2 py-1 text-left font-medium text-slate-500">年份</th>
            {Array.from({ length: 12 }).map((_, i) => (
              <th key={i} className="px-1 py-1 text-center font-medium text-slate-400">
                {i + 1}月
              </th>
            ))}
            <th className="px-2 py-1 text-right font-medium text-slate-500">年度</th>
          </tr>
        </thead>
        <tbody>
          {years.map((y) => {
            let acc = 1
            let has = false
            const cells = Array.from({ length: 12 }).map((_, i) => {
              const key = `${y}-${String(i + 1).padStart(2, '0')}`
              const v = lookup.get(key)
              if (v === undefined) return null
              has = true
              acc *= 1 + v
              return v
            })
            return (
              <tr key={y}>
                <td className="px-2 py-1 font-medium text-slate-600">{y}</td>
                {cells.map((v, i) => {
                  if (v === null || v === undefined)
                    return <td key={i} className="px-1 py-1 text-center text-slate-200">·</td>
                  const intensity = Math.min(Math.abs(v) / maxAbs, 1)
                  const bg =
                    v >= 0
                      ? `rgba(225,29,72,${0.10 + intensity * 0.55})`
                      : `rgba(5,150,105,${0.10 + intensity * 0.55})`
                  return (
                    <td key={i} className="px-1 py-1 text-center">
                      <div
                        className="num rounded px-1 py-1 font-medium"
                        style={{ background: bg, color: intensity > 0.5 ? '#fff' : '#334155' }}
                        title={`${y}年${i + 1}月 ${(v * 100).toFixed(2)}%`}
                      >
                        {(v * 100).toFixed(1)}
                      </div>
                    </td>
                  )
                })}
                <td className={`num px-2 py-1 text-right font-semibold ${has ? signClass(acc - 1) : 'text-slate-300'}`}>
                  {has ? `${((acc - 1) * 100).toFixed(1)}%` : '—'}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

/* ================================================================
 * 多策略净值叠加对比
 * ================================================================ */
function MultiEquityChartImpl({
  data,
  labels,
  height = 340,
  colors,
}: {
  data: Record<string, any>[]
  labels: string[]
  height?: number
  colors?: string[]
}) {
  if (!data.length || !labels.length) return <div className="py-16 text-center text-sm text-slate-400">暂无对比数据</div>
  const palette = colors?.length
    ? colors
    : ['#4f46e5', '#e11d48', '#059669', '#f59e0b', '#0ea5e9', '#a855f7', '#14b8a6', '#f43f5e']
  return (
    <ResponsiveContainer width="100%" height={height}>
      <LineChart data={data} margin={{ top: 8, right: 14, bottom: 0, left: 0 }}>
        <CartesianGrid stroke={GRID} vertical={false} />
        <XAxis dataKey="date" tick={AXIS} tickLine={false} axisLine={false} minTickGap={60} tickFormatter={fmtDate} />
        <YAxis
          tick={AXIS}
          tickLine={false}
          axisLine={false}
          width={64}
          tickFormatter={(v) => `$${fmtCompact(v)}`}
          domain={['auto', 'auto']}
        />
        <Tooltip content={<TipBox formatter={(v: number) => fmtMoney(v, 0)} />} />
        <Legend wrapperStyle={{ fontSize: 11, color: '#64748b' }} iconType="plainline" />
        {labels.map((lb, i) => (
          <Line
            key={lb}
            type="monotone"
            dataKey={lb}
            name={lb}
            stroke={palette[i % palette.length]}
            strokeWidth={1.8}
            dot={false}
            connectNulls
          />
        ))}
      </LineChart>
    </ResponsiveContainer>
  )
}

/* ================================================================
 * 月度收益柱状图
 * ================================================================ */
function MonthlyBarsImpl({ monthly, height = 200 }: { monthly: Record<string, number>; height?: number }) {
  const rows = Object.entries(monthly)
    .sort(([a], [b]) => a.localeCompare(b))
    .slice(-36)
    .map(([k, v]) => ({ date: k, ret: v * 100 }))
  if (!rows.length) return <div className="py-12 text-center text-sm text-slate-400">暂无数据</div>
  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={rows} margin={{ top: 8, right: 12, bottom: 0, left: 0 }}>
        <CartesianGrid stroke={GRID} vertical={false} />
        <XAxis dataKey="date" tick={AXIS} tickLine={false} axisLine={false} minTickGap={30} />
        <YAxis tick={AXIS} tickLine={false} axisLine={false} width={44} tickFormatter={(v) => `${v.toFixed(0)}%`} />
        <Tooltip content={<TipBox formatter={(v: number) => `${v.toFixed(2)}%`} />} />
        <ReferenceLine y={0} stroke="#cbd5e1" />
        <Bar dataKey="ret" name="月度收益" radius={[3, 3, 0, 0]}>
          {rows.map((r, i) => (
            <Cell key={i} fill={r.ret >= 0 ? upColor() : downColor()} />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  )
}

/* ================================================================
 * 综合评分表盘
 * ================================================================ */
function ScoreGaugeImpl({ score, size = 140 }: { score: number; size?: number }) {
  const pct = Math.max(0, Math.min(100, (score + 100) / 2))
  const color = score > 15 ? upColor() : score < -15 ? downColor() : '#94a3b8'
  const data = [{ name: 'score', value: pct, fill: color }]
  return (
    <div className="relative" style={{ width: size, height: size }}>
      <ResponsiveContainer width="100%" height="100%">
        <RadialBarChart
          data={data}
          innerRadius="72%"
          outerRadius="100%"
          startAngle={210}
          endAngle={-30}
          barSize={10}
        >
          <PolarAngleAxis type="number" domain={[0, 100]} tick={false} />
          <RadialBar dataKey="value" cornerRadius={6} background={{ fill: '#f1f5f9' }} />
        </RadialBarChart>
      </ResponsiveContainer>
      <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center">
        <span className="num text-2xl font-semibold" style={{ color }}>
          {score > 0 ? '+' : ''}
          {score.toFixed(1)}
        </span>
        <span className="text-[10px] uppercase tracking-wide text-slate-400">综合评分</span>
      </div>
    </div>
  )
}

/* ================================================================
 * 横向柱状（参数重要性 / 维度对比）
 * ================================================================ */
function HBarImpl({
  data,
  height = 200,
  color = '#6366f1',
  valueFormatter = (v: number) => fmtNum(v, 2),
}: {
  data: { name: string; value: number }[]
  height?: number
  color?: string
  valueFormatter?: (v: number) => string
}) {
  if (!data.length) return <div className="py-12 text-center text-sm text-slate-400">暂无数据</div>
  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={data} layout="vertical" margin={{ top: 4, right: 40, bottom: 4, left: 8 }}>
        <CartesianGrid stroke={GRID} horizontal={false} />
        <XAxis type="number" tick={AXIS} tickLine={false} axisLine={false} />
        <YAxis type="category" dataKey="name" tick={{ ...AXIS, fontSize: 11 }} tickLine={false} axisLine={false} width={88} />
        <Tooltip content={<TipBox formatter={valueFormatter} />} />
        <Bar dataKey="value" radius={[0, 4, 4, 0]} fill={color} label={{ position: 'right', fontSize: 10, fill: '#64748b', formatter: (v: any) => valueFormatter(Number(v)) }} />
      </BarChart>
    </ResponsiveContainer>
  )
}

/* ================================================================
 * 有效前沿散点图（组合优化）
 * ================================================================ */
function EfficientFrontierChartImpl({
  points,
  current,
  equalWeight,
  assets = [],
  height = 340,
}: {
  points: { ret: number; vol: number; sharpe?: number }[]
  current?: { ret: number; vol: number } | null
  equalWeight?: { ret: number; vol: number } | null
  assets?: { symbol: string; ann_return: number; ann_vol: number }[]
  height?: number
}) {
  if (!points.length) return <div className="py-14 text-center text-sm text-slate-400">暂无前沿数据</div>
  // 三点叠加在一张散点图：前沿曲线 + 最优组合 + 等权基准（+ 单标的）
  const rows: Record<string, any>[] = points.map((p) => ({
    x: p.vol * 100,
    frontier: p.ret * 100,
    name: '有效前沿',
  }))
  if (current) rows.push({ x: current.vol * 100, optimal: current.ret * 100, name: '最优组合' })
  if (equalWeight) rows.push({ x: equalWeight.vol * 100, equal: equalWeight.ret * 100, name: '等权基准' })
  assets.forEach((a) =>
    rows.push({ x: a.ann_vol * 100, asset: a.ann_return * 100, name: a.symbol }),
  )

  const xs = rows.map((r) => Number(r.x)).filter(Number.isFinite)
  const ys = rows.flatMap((r) => [r.frontier, r.optimal, r.equal, r.asset]).filter((v) => Number.isFinite(v))
  const padX = (Math.max(...xs) - Math.min(...xs)) * 0.08 || 1
  const padY = (Math.max(...ys) - Math.min(...ys)) * 0.12 || 1

  const fmt = (v: number) => `${v.toFixed(1)}%`
  return (
    <ResponsiveContainer width="100%" height={height}>
      <ScatterChart margin={{ top: 10, right: 18, bottom: 6, left: 0 }}>
        <CartesianGrid stroke={GRID} />
        <XAxis
          type="number"
          dataKey="x"
          name="年化波动"
          tick={AXIS}
          tickLine={false}
          axisLine={false}
          domain={[Math.min(...xs) - padX, Math.max(...xs) + padX]}
          tickFormatter={fmt}
          label={{ value: '年化波动', position: 'insideBottom', offset: -2, fontSize: 10, fill: '#94a3b8' }}
        />
        <YAxis
          type="number"
          dataKey="frontier"
          name="年化收益"
          tick={AXIS}
          tickLine={false}
          axisLine={false}
          width={52}
          domain={[Math.min(...ys) - padY, Math.max(...ys) + padY]}
          tickFormatter={fmt}
        />
        <Tooltip
          cursor={{ strokeDasharray: '3 3' }}
          content={({ active, payload }: any) => {
            if (!active || !payload?.length) return null
            const p = payload[0].payload
            return (
              <div className="rounded-lg border border-slate-200 bg-white/95 px-3 py-2 text-xs shadow-pop backdrop-blur">
                <div className="mb-1 font-medium text-slate-600">{p.name}</div>
                <div className="num text-slate-700">
                  波动 {fmt(Number(p.x))} · 收益 {fmt(Number(p.frontier ?? p.optimal ?? p.equal ?? p.asset))}
                </div>
              </div>
            )
          }}
        />
        <Legend wrapperStyle={{ fontSize: 11, color: '#64748b' }} />
        {/* 前沿按波动排序后连线呈现「曲线感」 */}
        <Scatter
          name="有效前沿"
          data={rows.filter((r) => r.frontier !== undefined).sort((a, b) => a.x - b.x)}
          dataKey="frontier"
          fill="#a5b4fc"
          line={{ stroke: '#818cf8', strokeWidth: 1.6 }}
          shape="circle"
          legendType="line"
        />
        <Scatter name="最优组合" data={rows.filter((r) => r.optimal !== undefined)} dataKey="optimal" fill="#4f46e5" shape="star" />
        <Scatter name="等权基准" data={rows.filter((r) => r.equal !== undefined)} dataKey="equal" fill="#f59e0b" shape="triangle" />
        <Scatter name="单标的" data={rows.filter((r) => r.asset !== undefined)} dataKey="asset" fill="#94a3b8" />
      </ScatterChart>
    </ResponsiveContainer>
  )
}

/* ================================================================
 * 相关性矩阵
 * ================================================================ */
function CorrelationMatrixImpl({ corr }: { corr: Record<string, Record<string, number | null>> }) {
  const syms = Object.keys(corr)
  if (syms.length < 2) return <div className="py-10 text-center text-sm text-slate-400">标的需要 ≥ 2 个</div>
  return (
    <div className="overflow-x-auto">
      <table className="text-xs">
        <thead>
          <tr>
            <th />
            {syms.map((s) => (
              <th key={s} className="px-2 py-1 font-medium text-slate-500">{s}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {syms.map((a) => (
            <tr key={a}>
              <td className="px-2 py-1 font-medium text-slate-600">{a}</td>
              {syms.map((b) => {
                const v = corr[a]?.[b]
                if (v === null || v === undefined)
                  return <td key={b} className="px-2 py-1 text-center text-slate-300">—</td>
                const intensity = Math.abs(v)
                const bg = v >= 0 ? `rgba(99,102,241,${0.08 + intensity * 0.6})` : `rgba(245,158,11,${0.08 + intensity * 0.6})`
                return (
                  <td key={b} className="px-1 py-1 text-center">
                    <div
                      className="num rounded px-2 py-1"
                      style={{ background: bg, color: intensity > 0.55 ? '#fff' : '#334155' }}
                    >
                      {v.toFixed(2)}
                    </div>
                  </td>
                )
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}


/* P2-8：memo 化导出。
   行情经 WebSocket 2 秒一拍推送，会触发页面级重渲染，而 recharts 图表重绘成本高。
   memo 后只要 props 引用不变就跳过重渲染。内部实现重命名为 XImpl 以避免与导出名冲突。 */
export const EquityChart = memo(EquityChartImpl)
export const PriceChart = memo(PriceChartImpl)
export const MiniSpark = memo(MiniSparkImpl)
export const MonthlyHeatmap = memo(MonthlyHeatmapImpl)
export const MultiEquityChart = memo(MultiEquityChartImpl)
export const MonthlyBars = memo(MonthlyBarsImpl)
export const ScoreGauge = memo(ScoreGaugeImpl)
export const HBar = memo(HBarImpl)
export const EfficientFrontierChart = memo(EfficientFrontierChartImpl)
export const CorrelationMatrix = memo(CorrelationMatrixImpl)
