import { Lightbulb, ShieldAlert } from 'lucide-react'
import { useInfoTip } from './InfoTip'

/**
 * 选股中心的信号展示层。
 *
 * 两个入口：
 *  · `SignalBadges` —— 表格行内：紧凑 badge + 悬停气泡（触发数值 + 规则说明 + 局限）。
 *  · `SignalCatalog` —— 折叠目录：全部信号的定义（数据来自后端 /signal-catalog）。
 *
 * 颜色约定：机会 = rose（红系，与「涨」同色系，符合中国习惯：红 = 好）；
 * 风险 = amber（橙）。刻意不用红绿对比 —— 风险不是「跌」，用绿色会与行情语义打架。
 */

export interface RowSignal {
  key: string
  kind: 'opportunity' | 'warning'
  label: string
  reason: string
}

/** 后端 /signal-catalog 返回的单个信号定义。 */
export interface SignalDef {
  key: string
  label: string
  kind: 'opportunity' | 'warning'
  brief: string
  condition: string
  logic: string
  limitation: string
}

const KIND_STYLE: Record<RowSignal['kind'], { badge: string; icon: JSX.Element }> = {
  opportunity: {
    badge: 'bg-rose-50 text-rose-700 hover:bg-rose-100',
    icon: <Lightbulb className="h-2.5 w-2.5" />,
  },
  warning: {
    badge: 'bg-amber-50 text-amber-700 hover:bg-amber-100',
    icon: <ShieldAlert className="h-2.5 w-2.5" />,
  },
}

function SignalBadge({
  sig,
  def,
  onClick,
}: {
  sig: RowSignal
  def?: SignalDef
  onClick?: (key: string) => void
}) {
  const style = KIND_STYLE[sig.kind] ?? KIND_STYLE.warning
  const { ref, handlers, layer } = useInfoTip<HTMLButtonElement>(
    sig.label,
    <div className="space-y-1.5">
      <p>
        <span className="mr-1 rounded bg-slate-100 px-1 py-px text-[10px] text-slate-500">触发</span>
        {sig.reason}
      </p>
      {def && (
        <>
          <p>
            <span className="mr-1 rounded bg-brand-50 px-1 py-px text-[10px] text-brand-600">条件</span>
            {def.condition}
          </p>
          <p>{def.logic}</p>
          {def.limitation && (
            <p className="rounded bg-amber-50 p-1.5 text-amber-800">
              <span className="mr-1 text-[10px]">局限</span>
              {def.limitation}
            </p>
          )}
        </>
      )}
    </div>,
  )
  return (
    <>
      <button
        ref={ref}
        {...handlers}
        onClick={(e) => {
          e.stopPropagation()
          onClick?.(sig.key)
        }}
        title={sig.reason}
        className={`inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] leading-4 font-medium transition-colors ${style.badge}`}
      >
        {style.icon}
        {sig.label}
      </button>
      {layer}
    </>
  )
}

/** 行内信号 badge 组：无信号时给一个安静的「—」，避免用户以为功能没生效。 */
export function SignalBadges({
  signals,
  catalog,
  onClick,
}: {
  signals?: RowSignal[] | null
  catalog?: Record<string, SignalDef>
  onClick?: (key: string) => void
}) {
  if (!signals || signals.length === 0) return <span className="text-slate-300">—</span>
  return (
    <div className="flex max-w-[170px] flex-wrap gap-1">
      {signals.map((s) => (
        <SignalBadge key={s.key} sig={s} def={catalog?.[s.key]} onClick={onClick} />
      ))}
    </div>
  )
}

const KIND_TAG: Record<RowSignal['kind'], { text: string; cls: string }> = {
  opportunity: { text: '机会', cls: 'bg-rose-50 text-rose-700' },
  warning: { text: '风险', cls: 'bg-amber-50 text-amber-700' },
}

/** 信号说明目录：折叠面板，每个信号完整展示「是什么 / 什么时候亮 / 逻辑 / 局限」。 */
export function SignalCatalog({ defs }: { defs: SignalDef[] }) {
  return (
    <details className="rounded-xl border border-slate-200 bg-white">
      <summary className="cursor-pointer select-none list-none px-3 py-2.5 text-xs font-medium text-slate-600 hover:text-brand-700">
        信号说明（{defs.length} 条规则 · 点开看每条什么时候亮 / 什么时候会骗人）
      </summary>
      <div className="grid gap-2 border-t border-slate-100 p-3 md:grid-cols-2">
        {defs.map((d) => {
          const tag = KIND_TAG[d.kind] ?? KIND_TAG.warning
          return (
            <div key={d.key} className="rounded-lg border border-slate-100 bg-slate-50/40 p-2.5">
              <div className="mb-1 flex items-center gap-1.5">
                <span className={`rounded px-1 py-px text-[10px] font-medium ${tag.cls}`}>{tag.text}</span>
                <span className="text-xs font-semibold text-slate-800">{d.label}</span>
                <span className="truncate text-[11px] text-slate-400">{d.brief}</span>
              </div>
              <p className="text-[11px] leading-5 text-slate-500">
                <span className="mr-1 rounded bg-white px-1 py-px text-[10px] text-slate-400">条件</span>
                {d.condition}
              </p>
              <p className="mt-1 text-[11px] leading-5 text-slate-500">
                <span className="mr-1 rounded bg-white px-1 py-px text-[10px] text-slate-400">逻辑</span>
                {d.logic}
              </p>
              <p className="mt-1 rounded bg-amber-50/70 p-1.5 text-[11px] leading-5 text-amber-800">
                <span className="mr-1 text-[10px]">局限</span>
                {d.limitation}
              </p>
            </div>
          )
        })}
      </div>
    </details>
  )
}
