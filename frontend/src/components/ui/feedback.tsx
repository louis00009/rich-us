/**
 * UI 零件 · 反馈态（Alert / Spinner / Loading / Empty / SkeletonRows）
 *
 * 从 `components/ui.tsx` 拆出（铁律 9）。
 * `./ui` 解析到 `ui/index.ts`，故所有使用方 import 路径不变。
 */
import clsx from 'clsx'
import { AlertTriangle, CheckCircle2, Info, Loader2, XCircle } from 'lucide-react'
import type { ReactNode } from 'react'

/* ================================================================
 * 提示条
 * ================================================================ */
export function Alert({
  tone = 'info',
  title,
  children,
  icon,
  className,
  action,
}: {
  tone?: 'info' | 'warn' | 'danger' | 'success'
  title?: ReactNode
  children?: ReactNode
  icon?: ReactNode
  className?: string
  action?: ReactNode
}) {
  const map = {
    info: 'border-sky-200 bg-sky-50 text-sky-900',
    warn: 'border-amber-200 bg-amber-50 text-amber-900',
    danger: 'border-rose-200 bg-rose-50 text-rose-900',
    success: 'border-emerald-200 bg-emerald-50 text-emerald-900',
  }
  const defIcon = {
    info: <Info className="h-4 w-4 text-sky-500" />,
    warn: <AlertTriangle className="h-4 w-4 text-amber-500" />,
    danger: <XCircle className="h-4 w-4 text-rose-500" />,
    success: <CheckCircle2 className="h-4 w-4 text-emerald-500" />,
  }
  return (
    <div className={clsx('flex items-start gap-2.5 rounded-lg border px-3.5 py-3', map[tone], className)}>
      <span className="mt-0.5 shrink-0">{icon ?? defIcon[tone]}</span>
      <div className="min-w-0 flex-1 text-sm">
        {title && <div className="font-medium">{title}</div>}
        {children && <div className={clsx('whitespace-pre-wrap', title && 'mt-0.5 opacity-90')}>{children}</div>}
      </div>
      {action}
    </div>
  )
}

export function Spinner({ className }: { className?: string }) {
  return <Loader2 className={clsx('h-4 w-4 animate-spin text-brand-500', className)} />
}

export function Loading({ label = '加载中…', className }: { label?: string; className?: string }) {
  return (
    <div className={clsx('flex items-center justify-center gap-2 py-10 text-sm text-slate-400', className)}>
      <Spinner />
      {label}
    </div>
  )
}

export function Empty({
  icon,
  title,
  desc,
  action,
  className,
}: {
  icon?: ReactNode
  title: string
  desc?: ReactNode
  action?: ReactNode
  className?: string
}) {
  return (
    <div className={clsx('flex flex-col items-center justify-center px-4 py-12 text-center', className)}>
      {icon && <div className="mb-3 text-slate-300">{icon}</div>}
      <p className="text-sm font-medium text-slate-600">{title}</p>
      {desc && <p className="mt-1 max-w-md text-xs text-slate-400">{desc}</p>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  )
}

export function SkeletonRows({ rows = 5, cols = 4 }: { rows?: number; cols?: number }) {
  return (
    <div className="space-y-2 p-4">
      {Array.from({ length: rows }).map((_, r) => (
        <div key={r} className="flex gap-3">
          {Array.from({ length: cols }).map((_, c) => (
            <div key={c} className="skeleton h-7 flex-1 rounded" />
          ))}
        </div>
      ))}
    </div>
  )
}
