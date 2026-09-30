/**
 * UI 零件 · 数据展示（Stat / Progress / DataTable / KV / ScoreBar）
 *
 * 从 `components/ui.tsx` 拆出（铁律 9）。
 * `./ui` 解析到 `ui/index.ts`，故所有使用方 import 路径不变。
 */
import clsx from 'clsx'
import { downClass, upClass } from '../../lib/format'
import type { ReactNode } from 'react'
import { Empty } from './feedback'

/* ================================================================
 * 数据展示
 * ================================================================ */
export function Stat({
  label,
  value,
  sub,
  tone,
  icon,
  className,
}: {
  label: ReactNode
  value: ReactNode
  sub?: ReactNode
  tone?: 'up' | 'down' | 'neutral'
  icon?: ReactNode
  className?: string
}) {
  return (
    <div className={clsx('rounded-xl border border-slate-200 bg-white p-4 shadow-card', className)}>
      <div className="flex items-center justify-between">
        <span className="text-xs font-medium uppercase tracking-wide text-slate-500">{label}</span>
        {icon && <span className="text-slate-300">{icon}</span>}
      </div>
      <div
        className={clsx(
          'num mt-2 text-2xl font-semibold',
          tone === 'up' ? upClass() : tone === 'down' ? downClass() : 'text-slate-900',
        )}
        style={
          tone === 'up'
            ? { color: 'var(--qd-up)' }
            : tone === 'down'
              ? { color: 'var(--qd-down)' }
              : undefined
        }
      >
        {value}
      </div>
      {sub && <div className="mt-1 text-xs text-slate-500">{sub}</div>}
    </div>
  )
}

export function Progress({
  value,
  max = 100,
  tone = 'brand',
  height = 'h-1.5',
  label,
}: {
  value: number
  max?: number
  tone?: 'brand' | 'green' | 'red' | 'amber'
  height?: string
  label?: ReactNode
}) {
  const pct = Math.max(0, Math.min(100, (value / (max || 1)) * 100))
  const colors = {
    brand: 'bg-brand-500',
    green: 'bg-emerald-500',
    red: 'bg-rose-500',
    amber: 'bg-amber-500',
  }
  return (
    <div>
      <div className={clsx('w-full overflow-hidden rounded-full bg-slate-100', height)}>
        <div className={clsx('h-full rounded-full transition-all', colors[tone])} style={{ width: `${pct}%` }} />
      </div>
      {label && <div className="mt-1 flex justify-between text-xs text-slate-500">{label}</div>}
    </div>
  )
}

/* ================================================================
 * 表格
 * ================================================================ */
export function DataTable<T>({
  columns,
  rows,
  empty,
  rowKey,
  maxHeight,
  onRowClick,
}: {
  columns: { key: string; label: ReactNode; align?: 'left' | 'right' | 'center'; width?: string; render: (r: T, i: number) => ReactNode }[]
  rows: T[]
  empty?: ReactNode
  rowKey?: (r: T, i: number) => string | number
  maxHeight?: string
  onRowClick?: (r: T) => void
}) {
  if (!rows.length) {
    return <>{empty ?? <Empty title="暂无数据" />}</>
  }
  return (
    <div className="overflow-auto" style={{ maxHeight }}>
      <table className="tbl">
        <thead className="sticky top-0 z-10">
          <tr>
            {columns.map((c) => (
              <th
                key={c.key}
                style={{ width: c.width }}
                className={clsx(
                  c.align === 'right' && 'text-right',
                  c.align === 'center' && 'text-center',
                )}
              >
                {c.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr
              key={rowKey ? rowKey(r, i) : i}
              onClick={onRowClick ? () => onRowClick(r) : undefined}
              className={onRowClick ? 'cursor-pointer' : undefined}
            >
              {columns.map((c) => (
                <td
                  key={c.key}
                  className={clsx(
                    c.align === 'right' && 'text-right',
                    c.align === 'center' && 'text-center',
                  )}
                >
                  {c.render(r, i)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

/** 简易 key-value 展示 */
export function KV({ items, cols = 2 }: { items: { k: ReactNode; v: ReactNode }[]; cols?: number }) {
  return (
    <dl
      className={clsx('grid gap-x-6 gap-y-2.5')}
      style={{ gridTemplateColumns: `repeat(${cols}, minmax(0, 1fr))` }}
    >
      {items.map((it, i) => (
        <div key={i} className="flex items-baseline justify-between gap-3 border-b border-dashed border-slate-100 pb-1.5">
          <dt className="shrink-0 text-xs text-slate-500">{it.k}</dt>
          <dd className="num truncate text-sm font-medium text-slate-800">{it.v}</dd>
        </div>
      ))}
    </dl>
  )
}

/** 水平条（用于维度评分可视化） */
export function ScoreBar({ label, value, min = -100, max = 100 }: { label: string; value: number; min?: number; max?: number }) {
  const pct = ((value - min) / (max - min)) * 100
  const pos = value >= 0
  return (
    <div className="flex items-center gap-3">
      <span className="w-16 shrink-0 text-xs text-slate-500">{label}</span>
      <div className="relative h-2 flex-1 rounded-full bg-slate-100">
        <div className="absolute left-1/2 top-0 h-full w-px bg-slate-300" />
        <div
          className={clsx('absolute top-0 h-full rounded-full', pos ? upClass() : downClass())}
          style={{
            left: pos ? '50%' : `${pct}%`,
            width: `${Math.abs(pct - 50)}%`,
          }}
        />
      </div>
      <span className={clsx('num w-12 shrink-0 text-right text-xs font-medium', pos ? upClass() : downClass())}>
        {value.toFixed(1)}
      </span>
    </div>
  )
}
