/**
 * 表单排版零件（全平台共享）
 * ==========================
 * 原在 `components/backtest/parts.tsx`，做组合优化页时提升到 `components/form/` ——
 * 优化页也要用「可点选胶囊 / 带序号小标题 / 可折叠区块」这三样，去 import
 * 一个 `backtest/` 下的零件属于反向依赖。
 *
 * 都是纯展示、无状态的小组件，搬动不影响任何业务逻辑。
 */
import clsx from 'clsx'
import type { ReactNode } from 'react'
import { TermIcon } from '../terms/TermTip'

/** 可点选的胶囊标签（快捷标的 / 基准 / 时长预设共用）。 */
export function Chip({
  active,
  onClick,
  title,
  children,
}: {
  active?: boolean
  onClick: () => void
  title?: string
  children: ReactNode
}) {
  return (
    <button
      type="button"
      title={title}
      onClick={onClick}
      className={clsx(
        'rounded-full border px-2.5 py-1 text-[11px] font-medium transition-colors',
        active
          ? 'border-brand-300 bg-brand-50 text-brand-700'
          : 'border-slate-200 bg-white text-slate-500 hover:border-brand-200 hover:text-brand-600',
      )}
    >
      {children}
    </button>
  )
}

/** 带序号的小标题 —— 让「从哪开始」这件事在视觉上成立。 */
export function Step({ n, title, tip, children }: { n: number; title: string; tip?: string; children: ReactNode }) {
  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2">
        <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-brand-600 text-[11px] font-semibold text-white">
          {n}
        </span>
        <span className="text-xs font-semibold text-slate-700">{title}</span>
        {tip && <TermIcon id={tip} />}
        <div className="h-px flex-1 bg-slate-100" />
      </div>
      {children}
    </div>
  )
}

/**
 * 高级区块：新手模式下折起来（`<details>`），专业模式下平铺。
 * ⚠️ 用 `<details>` 而不是「条件渲染」：内容始终在 DOM 里（SSR 断言才验得到），
 *    只是浏览器默认折叠 —— 这样「功能没被删掉」是客观事实，而不是靠代码 review。
 */
export function Section({
  title,
  tip,
  collapsed,
  children,
}: {
  title: string
  tip?: string
  collapsed: boolean
  children: ReactNode
}) {
  if (collapsed) {
    return (
      <details className="rounded-lg border border-slate-200 px-3 py-2">
        <summary className="cursor-pointer select-none py-1 text-xs font-semibold text-slate-600">{title}</summary>
        <div className="space-y-3 pt-2">{children}</div>
      </details>
    )
  }
  return (
    <div className="border-t border-slate-100 pt-3">
      <div className="mb-2 flex items-center gap-2">
        <span className="text-xs font-semibold uppercase tracking-wide text-slate-400">{title}</span>
        {tip && <TermIcon id={tip} />}
        <div className="h-px flex-1 bg-slate-100" />
      </div>
      <div className="space-y-3">{children}</div>
    </div>
  )
}
