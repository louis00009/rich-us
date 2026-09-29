import { HelpCircle } from 'lucide-react'
import { ReactNode, useCallback, useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'

/**
 * 列头指标说明气泡。
 *
 * 两个必须这样做的理由：
 *  ① **触发区必须是整个表头单元格**（而不是那个 12px 的问号图标）——
 *     用户的原话是「鼠标移动到列的名字的时候需要提示」，只让图标可悬停等于没做。
 *  ② **必须 portal 到 body + fixed 定位**：表格外层有 `overflow-x-auto`（窄屏横向滚动
 *     必需），而 `overflow-x: auto` 会把 `overflow-y` 一并算成 auto —— 写在 `<th>` 里的
 *     绝对定位气泡会被**裁掉**，表头下面什么都看不到。
 *
 * 用 hook 形式是为了能把事件绑在 `<th>` 本身；同时保留 aria-label 的问号图标作为
 * 可见的「这里能悬停」提示与无障碍标签。
 */
interface Pos {
  top: number
  left: number
  above: boolean
}

export function useInfoTip<T extends HTMLElement>(label: string, content: ReactNode) {
  const ref = useRef<T>(null)
  const [pos, setPos] = useState<Pos | null>(null)

  const show = useCallback(() => {
    const el = ref.current
    if (!el) return
    const r = el.getBoundingClientRect()
    // 气泡宽 288px(w-72)：左右各留 144px 余量，避免贴边被视口裁掉
    const half = 144
    const left = Math.min(Math.max(r.left + r.width / 2, half + 8), window.innerWidth - half - 8)
    const above = r.bottom + 200 > window.innerHeight
    setPos({ top: above ? r.top - 8 : r.bottom + 8, left, above })
  }, [])

  const hide = useCallback(() => setPos(null), [])

  // 滚动/缩放时立即收起：气泡是 fixed 定位，不跟着表格滚，留着会错位
  useEffect(() => {
    if (!pos) return
    const onMove = () => setPos(null)
    window.addEventListener('scroll', onMove, true)
    window.addEventListener('resize', onMove)
    return () => {
      window.removeEventListener('scroll', onMove, true)
      window.removeEventListener('resize', onMove)
    }
  }, [pos])

  const layer = pos
    ? createPortal(
        <div
          role="tooltip"
          style={{
            position: 'fixed',
            top: pos.top,
            left: pos.left,
            transform: pos.above ? 'translate(-50%, -100%)' : 'translate(-50%, 0)',
          }}
          className="pointer-events-none z-[999] w-72 max-w-[calc(100vw-16px)] break-words rounded-lg border border-slate-200 bg-white p-3 text-left text-[11px] font-normal normal-case leading-5 tracking-normal text-slate-600 shadow-pop"
        >
          <div className="mb-1.5 text-[12px] font-semibold text-slate-800">{label}</div>
          {content}
        </div>,
        document.body,
      )
    : null

  return {
    ref,
    layer,
    handlers: {
      onMouseEnter: show,
      onMouseLeave: hide,
      onFocus: show,
      onBlur: hide,
    },
  }
}

/** 表头里那个小小的问号 —— 只作视觉提示与无障碍标签，悬停判定在 `<th>` 上。 */
export function TipIcon({ label }: { label: string }) {
  return (
    <span aria-label={`${label} 指标说明`} className="inline-flex shrink-0 text-slate-300">
      <HelpCircle className="h-3 w-3" />
    </span>
  )
}

/** 统一的「是什么 / 怎么看 / 注意」三段式说明。 */
export function MetricTip({ title, what, how, warn }: { title: string; what: string; how: string; warn?: string }) {
  return (
    <>
      <p className="mb-1.5">
        <span className="mr-1 rounded bg-slate-100 px-1 py-px text-[10px] text-slate-500">是什么</span>
        {what}
      </p>
      <p className={warn ? 'mb-1.5' : ''}>
        <span className="mr-1 rounded bg-brand-50 px-1 py-px text-[10px] text-brand-600">怎么看</span>
        {how}
      </p>
      {warn && (
        <p className="rounded bg-amber-50 p-1.5 text-amber-800">
          <span className="mr-1 text-[10px]">注意</span>
          {warn}
        </p>
      )}
    </>
  )
}
