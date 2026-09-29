/**
 * TermTip —— 术语悬浮解释
 * ========================
 * 用户原话：「针对一些词汇都有鼠标悬浮的解释」。所以这里把 glossary 里的词条
 * 包成**可悬停的行内元素**，而不是只放一个 12px 的问号图标 —— 只让图标可悬停
 * 等于没做（这是榜单页 InfoTip 已经踩过的结论）。
 *
 * ⚠️ 本文件原在 `components/backtest/TermTip.tsx`，做组合优化页时提升为**全平台唯一**
 *    的术语悬浮实现（回测页与优化页共用）。查词走 `./index` 的合并注册表 ——
 *    词条分布在 `glossary.ts`（通用+回测）与 `optimize.ts`（组合优化）两处。
 *
 * ⚠️ 复用 `components/rankings/InfoTip.tsx` 的 `useInfoTip`，**不要另写一份**：
 *    那份实现里有两个必须保留的修法 ——
 *      ① 气泡必须 `createPortal` 到 body + `position: fixed`。回测页的卡片/表格外层
 *         有 `overflow-auto`（`overflow-x:auto` 会把 `overflow-y` 一并算成 auto），
 *         写在里面的绝对定位气泡会被直接裁掉，悬停了什么都看不到；
 *      ② 滚动 / 缩放时必须立即收起，否则 fixed 气泡不跟着滚，会停在原地错位。
 *    单独复制一份实现 = 这两个坑会各自漂移一次。
 *
 * ⚠️ SSR（render-check 的 renderToString）下 `document` 不存在：`useInfoTip` 只在
 *    hover 后才 setState 并 portal，所以初始渲染是安全的，不会白屏。
 */
import { HelpCircle } from 'lucide-react'
import type { ReactNode } from 'react'
import { MetricTip, useInfoTip } from '../rankings/InfoTip'
import { term } from './index'

/**
 * 把任意文字变成「有悬浮解释」的文字。
 * 视觉上是虚线下划线 + cursor:help，这是业界通用的「这里可以悬停」提示。
 */
export function TermTip({
  id,
  children,
  className = '',
  dotted = true,
}: {
  id: string
  children?: ReactNode
  className?: string
  /** 关掉虚线（用于本身就带下划线/在按钮里等场景，避免视觉噪音） */
  dotted?: boolean
}) {
  const t = term(id)
  const { ref, layer, handlers } = useInfoTip<HTMLSpanElement>(
    t.title,
    <MetricTip title={t.title} what={t.what} how={t.how} warn={t.warn} />,
  )
  return (
    <>
      <span
        ref={ref}
        {...handlers}
        tabIndex={0}
        className={`cursor-help outline-none ${
          dotted ? 'border-b border-dotted border-slate-400/70' : ''
        } ${className}`}
      >
        {children ?? t.title}
      </span>
      {layer}
    </>
  )
}

/**
 * 小小的问号 —— 放在表单标签 / 区块标题后面，与文字本身各占一个悬停区。
 * 给 aria-label 是为了让 render-check 能断言「这个词真的挂上了说明」
 * （气泡正文只在 hover 时才进 DOM，断言不到）。
 */
export function TermIcon({ id, className = '' }: { id: string; className?: string }) {
  const t = term(id)
  const { ref, layer, handlers } = useInfoTip<HTMLSpanElement>(
    t.title,
    <MetricTip title={t.title} what={t.what} how={t.how} warn={t.warn} />,
  )
  return (
    <>
      <span
        ref={ref}
        {...handlers}
        tabIndex={0}
        role="button"
        aria-label={`${t.title} 说明`}
        className={`inline-flex shrink-0 cursor-help items-center text-slate-300 outline-none hover:text-brand-500 ${className}`}
      >
        <HelpCircle className="h-3.5 w-3.5" />
      </span>
      {layer}
    </>
  )
}

/** 表单标签：文字 + 问号。`Field` 的 label 接受 ReactNode，直接传它即可。 */
export function TermLabel({ id, children }: { id: string; children: ReactNode }) {
  return (
    <span className="inline-flex items-center gap-1.5">
      {children}
      <TermIcon id={id} />
    </span>
  )
}
