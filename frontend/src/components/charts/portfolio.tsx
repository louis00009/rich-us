/**
 * 图表 · 组合分析（EfficientFrontierChart / CorrelationMatrix）
 *
 * 从 `components/charts.tsx` 拆出（铁律 9）。
 * 配色：涨红跌绿（中国习惯），可在设置中切换。
 */
import { memo } from 'react'
import {
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { AXIS, GRID } from './shared'

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

export const EfficientFrontierChart = memo(EfficientFrontierChartImpl)
export const CorrelationMatrix = memo(CorrelationMatrixImpl)
