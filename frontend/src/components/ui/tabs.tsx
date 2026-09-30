/**
 * UI 零件 · 标签页
 *
 * 从 `components/ui.tsx` 拆出（铁律 9）。
 * `./ui` 解析到 `ui/index.ts`，故所有使用方 import 路径不变。
 */
import clsx from 'clsx'
import type { ReactNode } from 'react'

/* ================================================================
 * Tabs
 * ================================================================ */
export function Tabs({
  tabs,
  value,
  onChange,
  className,
}: {
  tabs: { key: string; label: ReactNode; badge?: ReactNode }[]
  value: string
  onChange: (k: string) => void
  className?: string
}) {
  return (
    <div className={clsx('flex flex-wrap gap-1 rounded-lg bg-slate-100 p-1', className)}>
      {tabs.map((t) => (
        <button
          key={t.key}
          onClick={() => onChange(t.key)}
          className={clsx(
            'inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-medium transition-all',
            value === t.key ? 'bg-white text-slate-900 shadow-sm' : 'text-slate-500 hover:text-slate-700',
          )}
        >
          {t.label}
          {t.badge !== undefined && (
            <span className="rounded bg-slate-200/80 px-1 text-[10px] text-slate-600">{t.badge}</span>
          )}
        </button>
      ))}
    </div>
  )
}
