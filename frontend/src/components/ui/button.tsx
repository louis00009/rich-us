/**
 * UI 零件 · 按钮
 *
 * 从 `components/ui.tsx` 拆出（铁律 9）。
 * `./ui` 解析到 `ui/index.ts`，故所有使用方 import 路径不变。
 */
import clsx from 'clsx'
import { Loader2 } from 'lucide-react'
import type { ButtonHTMLAttributes, ReactNode } from 'react'

/* ================================================================
 * Button
 * ================================================================ */
type Variant = 'primary' | 'secondary' | 'ghost' | 'danger' | 'success' | 'warning'
type Size = 'sm' | 'md' | 'lg'

const V: Record<Variant, string> = {
  primary: 'bg-brand-600 text-white hover:bg-brand-700 active:bg-brand-800 shadow-sm disabled:bg-brand-300',
  secondary: 'bg-white text-slate-700 border border-slate-300 hover:bg-slate-50 active:bg-slate-100 disabled:text-slate-400',
  ghost: 'text-slate-600 hover:bg-slate-100 active:bg-slate-200 disabled:text-slate-300',
  danger: 'bg-rose-600 text-white hover:bg-rose-700 active:bg-rose-800 shadow-sm disabled:bg-rose-300',
  success: 'bg-emerald-600 text-white hover:bg-emerald-700 active:bg-emerald-800 shadow-sm disabled:bg-emerald-300',
  warning: 'bg-amber-500 text-white hover:bg-amber-600 active:bg-amber-700 shadow-sm disabled:bg-amber-300',
}
const S: Record<Size, string> = {
  sm: 'h-8 px-3 text-xs gap-1.5',
  md: 'h-9.5 px-4 text-sm gap-2',
  lg: 'h-11 px-5 text-sm gap-2',
}

export function Button({
  variant = 'secondary',
  size = 'md',
  loading,
  icon,
  className,
  children,
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: Variant
  size?: Size
  loading?: boolean
  icon?: ReactNode
}) {
  return (
    <button
      {...rest}
      disabled={rest.disabled || loading}
      className={clsx(
        'inline-flex select-none items-center justify-center rounded-lg font-medium transition-colors',
        'focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500/40 disabled:cursor-not-allowed',
        V[variant],
        S[size],
        size === 'md' && 'h-9',
        className,
      )}
    >
      {loading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : icon}
      {children}
    </button>
  )
}
