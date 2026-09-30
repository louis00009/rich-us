/**
 * 图表 · 月度分布（MonthlyHeatmap / MonthlyBars）
 *
 * 从 `components/charts.tsx` 拆出（铁律 9）。
 * 配色：涨红跌绿（中国习惯），可在设置中切换。
 */
import { memo } from 'react'
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { downColor, signClass, upColor } from '../../lib/format'
import { AXIS, GRID, TipBox } from './shared'

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

export const MonthlyHeatmap = memo(MonthlyHeatmapImpl)
export const MonthlyBars = memo(MonthlyBarsImpl)
