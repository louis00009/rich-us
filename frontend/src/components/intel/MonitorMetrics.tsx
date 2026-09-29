/**
 * 监控总控 · 展示单元
 *
 * 从 `MonitorBar.tsx` 抽出（加「指定标的」后该文件 432 行，超组件软上限 400）。
 * 这两个都是**纯展示**、无任何业务状态 —— 抽出来零风险，且 MonitorBar 只剩编排。
 */
import type { ReactNode } from 'react'

/** 指标单元：数值 + 标签 + 可选副说明。刻意让数值字号最大，形成视觉重心。 */
export function Metric({
  label,
  value,
  hint,
  tone = 'default',
  title,
}: {
  label: string
  value: ReactNode
  hint?: ReactNode
  tone?: 'default' | 'brand' | 'warn' | 'muted'
  title?: string
}) {
  const color =
    tone === 'brand' ? 'text-brand-700' : tone === 'warn' ? 'text-amber-600' : tone === 'muted' ? 'text-slate-400' : 'text-slate-800'
  return (
    <div className="min-w-0 rounded-lg bg-slate-50 px-3 py-2" title={title}>
      <div className="truncate text-[11px] text-slate-500">{label}</div>
      <div className={`num mt-0.5 truncate text-base font-semibold leading-tight ${color}`}>{value}</div>
      {hint && <div className="mt-0.5 truncate text-[11px] text-slate-400">{hint}</div>}
    </div>
  )
}

/** 近 7 日事件量迷你柱状图（纯 CSS，不引图表库） */
export function DailyBars({ daily }: { daily: { date: string; count: number }[] }) {
  if (!daily.length) return null
  const max = Math.max(1, ...daily.map((d) => d.count))
  return (
    <div className="flex items-end gap-1.5" title="近 7 日入库事件数（按事件发生日）">
      {daily.map((d) => {
        const h = Math.max(3, Math.round((d.count / max) * 34))
        const isToday = d.date === daily[daily.length - 1].date
        return (
          <div key={d.date} className="flex w-8 flex-col items-center gap-1" title={`${d.date} · ${d.count} 条`}>
            <span className="num text-[10px] text-slate-400">{d.count}</span>
            <div className={`w-full rounded-sm ${isToday ? 'bg-brand-500' : 'bg-slate-300'}`} style={{ height: `${h}px` }} />
            <span className="num text-[10px] text-slate-400">{d.date.slice(5)}</span>
          </div>
        )
      })}
    </div>
  )
}
