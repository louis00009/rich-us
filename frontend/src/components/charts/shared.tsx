/**
 * 图表公共件：坐标轴样式常量与自定义 Tooltip。
 * 从 `components/charts.tsx` 拆出（铁律 9）。
 */
import { fmtDate, fmtNum } from '../../lib/format'

export const AXIS = { fontSize: 10, fill: '#94a3b8' }
export const GRID = '#eef2f7'

export function TipBox({ active, payload, label, formatter }: any) {
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
