/**
 * 轻量 UI 组件库（无第三方依赖，除 lucide 图标）
 * 统一浅色主题 + 品牌靛蓝主色
 */
import clsx from 'clsx'
import { AlertTriangle, CheckCircle2, Info, Loader2, X, XCircle } from 'lucide-react'
import { downClass, upClass } from '../lib/format'
import {
  cloneElement,
  createContext,
  isValidElement,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useId,
  useRef,
  useState,
  type ButtonHTMLAttributes,
  type InputHTMLAttributes,
  type ReactNode,
  type SelectHTMLAttributes,
} from 'react'

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

/* ================================================================
 * Badge
 * ================================================================ */
type Tone = 'slate' | 'brand' | 'green' | 'red' | 'amber' | 'blue' | 'violet'
const T: Record<Tone, string> = {
  slate: 'bg-slate-100 text-slate-700 ring-slate-200',
  brand: 'bg-brand-50 text-brand-700 ring-brand-200',
  green: 'bg-emerald-50 text-emerald-700 ring-emerald-200',
  red: 'bg-rose-50 text-rose-700 ring-rose-200',
  amber: 'bg-amber-50 text-amber-700 ring-amber-200',
  blue: 'bg-sky-50 text-sky-700 ring-sky-200',
  violet: 'bg-violet-50 text-violet-700 ring-violet-200',
}

export function Badge({
  tone = 'slate',
  children,
  className,
  dot,
}: {
  tone?: Tone
  children: ReactNode
  className?: string
  dot?: boolean
}) {
  return (
    <span
      className={clsx(
        'inline-flex items-center gap-1.5 rounded-md px-2 py-0.5 text-xs font-medium ring-1 ring-inset',
        T[tone],
        className,
      )}
    >
      {dot && <span className="h-1.5 w-1.5 rounded-full bg-current" />}
      {children}
    </span>
  )
}

/* ================================================================
 * 表单
 * ================================================================ */
export function Field({
  label,
  hint,
  error,
  children,
  className,
}: {
  label?: ReactNode
  hint?: ReactNode
  error?: ReactNode
  children: ReactNode
  className?: string
}) {
  // 无障碍：给唯一的 Input/Select 子元素自动注入 id 并绑定 htmlFor ——
  // 点击标签可聚焦输入框，读屏软件能播报标签文本
  const autoId = useId()
  let control: ReactNode = children
  let controlId: string | undefined
  if (isValidElement(children) && (children.type === Input || children.type === Select)) {
    controlId = ((children.props as any)?.id as string | undefined) ?? autoId
    control = cloneElement(children as any, { id: controlId })
  }
  return (
    <div className={className}>
      {label && (
        <label className="lbl" htmlFor={controlId}>
          {label}
        </label>
      )}
      {control}
      {error ? (
        <p className="mt-1 text-xs text-rose-600" role="alert">
          {error}
        </p>
      ) : hint ? (
        <p className="mt-1 text-xs text-slate-400">{hint}</p>
      ) : null}
    </div>
  )
}

export function Input({ className, ...rest }: InputHTMLAttributes<HTMLInputElement>) {
  return <input {...rest} className={clsx('inp', className)} />
}

export function Select({
  className,
  children,
  ...rest
}: SelectHTMLAttributes<HTMLSelectElement> & { children: ReactNode }) {
  return (
    <select {...rest} className={clsx('inp cursor-pointer appearance-none pr-8', className)}>
      {children}
    </select>
  )
}

export function Switch({
  checked,
  onChange,
  label,
  hint,
  disabled,
}: {
  checked: boolean
  onChange: (v: boolean) => void
  label?: ReactNode
  hint?: ReactNode
  disabled?: boolean
}) {
  return (
    <label className={clsx('flex items-start gap-3', disabled ? 'opacity-60' : 'cursor-pointer')}>
      <button
        type="button"
        disabled={disabled}
        onClick={() => onChange(!checked)}
        className={clsx(
          'relative mt-0.5 h-5 w-9 shrink-0 rounded-full transition-colors',
          checked ? 'bg-brand-600' : 'bg-slate-300',
        )}
        role="switch"
        aria-checked={checked}
      >
        <span
          className="absolute top-0.5 h-4 w-4 rounded-full bg-white shadow transition-all"
          style={{ left: checked ? 18 : 2 }}
        />
      </button>
      {(label || hint) && (
        <span className="min-w-0">
          {label && <span className="block text-sm text-slate-700">{label}</span>}
          {hint && <span className="mt-0.5 block text-xs text-slate-400">{hint}</span>}
        </span>
      )}
    </label>
  )
}

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

/* ================================================================
 * Modal
 * ================================================================ */
export function Modal({
  open,
  onClose,
  title,
  children,
  footer,
  width = 'max-w-lg',
  className,
  bodyClass,
}: {
  open: boolean
  onClose: () => void
  title: ReactNode
  children: ReactNode
  footer?: ReactNode
  width?: string
  className?: string
  bodyClass?: string
}) {
  useEffect(() => {
    if (!open) return
    const h = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', h)
    return () => window.removeEventListener('keydown', h)
  }, [open, onClose])

  if (!open) return null
  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-slate-900/40 p-4 py-12 backdrop-blur-sm">
      {/* 无障碍：dialog 语义 + 焦点落点（Esc 关闭已由上方键盘监听处理） */}
      <div
        role="dialog"
        aria-modal="true"
        tabIndex={-1}
        autoFocus
        className={clsx('w-full animate-fade-in rounded-xl bg-white shadow-pop outline-none', width, className)}
      >
        <div className="flex items-center justify-between border-b border-slate-100 px-5 py-3.5">
          <h3 className="text-sm font-semibold text-slate-800">{title}</h3>
          <button
            onClick={onClose}
            aria-label="关闭对话框"
            className="rounded-md p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-600"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className={clsx('card-bd px-5 py-4', bodyClass || 'max-h-[70vh] overflow-y-auto')}>{children}</div>
        {footer && <div className="flex justify-end gap-2 border-t border-slate-100 px-5 py-3">{footer}</div>}
      </div>
    </div>
  )
}

/* ================================================================
 * Toast
 * ================================================================ */
type ToastKind = 'success' | 'error' | 'info' | 'warning'
interface ToastItem {
  id: number
  kind: ToastKind
  msg: string
}
const ToastCtx = createContext<(kind: ToastKind, msg: string) => void>(() => {})

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([])
  const timers = useRef<Map<number, ReturnType<typeof setTimeout>>>(new Map())

  const push = useCallback((kind: ToastKind, msg: string) => {
    const id = Date.now() + Math.random()
    setItems((s) => [...s, { id, kind, msg }])
    const t = setTimeout(() => {
      setItems((s) => s.filter((i) => i.id !== id))
      timers.current.delete(id)
    }, kind === 'error' ? 7000 : 4000)
    timers.current.set(id, t)
  }, [])

  // 卸载时清理全部挂起的 toast 定时器（P2：旧实现泄漏）
  useEffect(() => {
    const m = timers.current
    return () => {
      m.forEach((t) => clearTimeout(t))
      m.clear()
    }
  }, [])

  const icons: Record<ToastKind, ReactNode> = {
    success: <CheckCircle2 className="h-4 w-4 text-emerald-500" />,
    error: <XCircle className="h-4 w-4 text-rose-500" />,
    info: <Info className="h-4 w-4 text-sky-500" />,
    warning: <AlertTriangle className="h-4 w-4 text-amber-500" />,
  }

  return (
    <ToastCtx.Provider value={push}>
      {children}
      {/* 无障碍：aria-live 让读屏软件播报 toast；宽度适配窄屏 */}
      <div
        role="status"
        aria-live="polite"
        className="pointer-events-none fixed bottom-4 right-4 z-[60] flex w-[calc(100vw-32px)] max-w-[360px] flex-col gap-2"
      >
        {items.map((t) => (
          <div
            key={t.id}
            className="pointer-events-auto flex animate-fade-in items-start gap-2.5 rounded-lg border border-slate-200 bg-white px-3.5 py-3 shadow-pop"
          >
            <span className="mt-0.5 shrink-0">{icons[t.kind]}</span>
            <p className="flex-1 whitespace-pre-wrap break-words text-sm text-slate-700">{t.msg}</p>
            <button
              onClick={() => setItems((s) => s.filter((i) => i.id !== t.id))}
              aria-label="关闭通知"
              className="shrink-0 rounded p-0.5 text-slate-300 hover:text-slate-500"
            >
              <X className="h-3.5 w-3.5" />
            </button>
          </div>
        ))}
      </div>
    </ToastCtx.Provider>
  )
}

export function useToast() {
  return useContext(ToastCtx)
}

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

/** 使用方可在应用中注入主题色 */
export function ThemeVars({ up, down }: { up: string; down: string }) {
  return <style>{`:root{--qd-up:${up};--qd-down:${down}}`}</style>
}
