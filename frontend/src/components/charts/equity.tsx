/**
 * 图表 · 资金曲线类（EquityChart / MultiEquityChart）
 *
 * 从 `components/charts.tsx` 拆出（铁律 9）。
 * 配色：涨红跌绿（中国习惯），可在设置中切换。
 */
import { memo } from 'react'
import {
  Area,
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { fmtCompact, fmtDate, fmtMoney } from '../../lib/format'
import type { CurvePoint } from '../../lib/types'
import { AXIS, GRID, TipBox } from './shared'

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

export const EquityChart = memo(EquityChartImpl)
export const MultiEquityChart = memo(MultiEquityChartImpl)
