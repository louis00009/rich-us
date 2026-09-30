/**
 * UI 零件 · 表单零件（Field / Input / Select / Switch）
 *
 * 从 `components/ui.tsx` 拆出（铁律 9）。
 * `./ui` 解析到 `ui/index.ts`，故所有使用方 import 路径不变。
 */
import clsx from 'clsx'
import { cloneElement, isValidElement, useId } from 'react'
import type { InputHTMLAttributes, ReactNode, SelectHTMLAttributes } from 'react'

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
