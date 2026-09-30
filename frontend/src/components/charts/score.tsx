/**
 * 图表 · 评分可视化（ScoreGauge / HBar）
 *
 * 从 `components/charts.tsx` 拆出（铁律 9）。
 * 配色：涨红跌绿（中国习惯），可在设置中切换。
 */
import { memo } from 'react'
import {
  Bar,
  BarChart,
  CartesianGrid,
  PolarAngleAxis,
  RadialBar,
  RadialBarChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { downColor, fmtNum, upColor } from '../../lib/format'
import { AXIS, GRID, TipBox } from './shared'

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

export const ScoreGauge = memo(ScoreGaugeImpl)
export const HBar = memo(HBarImpl)
