/**
 * UI 零件 · 对话框（**必须 portal 到 body**，见文件内注释）
 *
 * 从 `components/ui.tsx` 拆出（铁律 9）。
 * `./ui` 解析到 `ui/index.ts`，故所有使用方 import 路径不变。
 */
import clsx from 'clsx'
import { X } from 'lucide-react'
import { useEffect } from 'react'
import { createPortal } from 'react-dom'
import type { ReactNode } from 'react'

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
  // ⚠️ **必须 portal 到 body**。Modal 若留在原来的 DOM 位置，只要**任一祖先**带
  //    `backdrop-filter` / `filter` / `transform` / `perspective` / `will-change` /
  //    `contain`，那个祖先就会成为 `position: fixed` 的**包含块** ——
  //    于是 `inset-0` 不再是视口，弹窗被压进祖先那一小块区域里。
  //    真实踩过：榜单多选工具条是 `sticky top-0 … backdrop-blur`，点「AI 深度分析」
  //    弹窗不居中、只显示成工具栏大小的一条（对话框 y=715 而不是视口顶部）。
  //    与 InfoTip 同一套修法（那里是 `overflow-x-auto` 裁掉气泡）。
  //    SSR 下 `document` 不存在：Modal 默认 `open=false` 已提前 return，
  //    这里再兜一层，避免有人在 SSR 里传 open=true 直接炸掉整页。
  if (typeof document === 'undefined') return null
  return createPortal(
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
    </div>,
    document.body,
  )
}
