/**
 * UI 零件 · 卡片
 *
 * 从 `components/ui.tsx` 拆出（铁律 9）。
 * `./ui` 解析到 `ui/index.ts`，故所有使用方 import 路径不变。
 */
import clsx from 'clsx'
import type { ReactNode } from 'react'

/* ================================================================
 * Card
 * ================================================================ */
export function Card({
  title,
  subtitle,
  actions,
  children,
  className,
  bodyClass,
  dense,
}: {
  title?: ReactNode
  subtitle?: ReactNode
  actions?: ReactNode
  children?: ReactNode
  className?: string
  bodyClass?: string
  dense?: boolean
}) {
  return (
    <section className={clsx('card', className)}>
      {(title || actions) && (
        <header className="card-hd">
          <div className="min-w-0">
            {title && <h3 className="truncate text-sm font-semibold text-slate-800">{title}</h3>}
            {subtitle && <p className="mt-0.5 text-xs text-slate-500">{subtitle}</p>}
          </div>
          {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
        </header>
      )}
      <div className={clsx(dense ? '' : 'card-bd', bodyClass)}>{children}</div>
    </section>
  )
}
