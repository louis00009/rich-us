/**
 * UI 零件 · 轻提示（ToastProvider / useToast）
 *
 * 从 `components/ui.tsx` 拆出（铁律 9）。
 * `./ui` 解析到 `ui/index.ts`，故所有使用方 import 路径不变。
 */
import { AlertTriangle, CheckCircle2, Info, X, XCircle } from 'lucide-react'
import { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'

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
