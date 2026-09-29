import { Crosshair, Info } from 'lucide-react'
import { SignalBadges, SignalCatalog, SignalDef, RowSignal } from './SignalCell'
import { Spinner } from '../ui'

/**
 * 选股中心面板 —— 三个区块：
 *  1. 今日关注：全池（筛选前）按「机会信号数 → 综合评分」挑出的前 8 只，直接回答
 *     「哪些股票值得关注」；每只带触发信号与具体数值理由。
 *  2. 信号统计：当前筛选结果里各信号触发了多少只，点击 → 按该信号筛选。
 *  3. 信号说明：完整目录（何时亮灯 / 逻辑 / 局限）。
 *
 * ⚠️ 免责声明必须在这里重复一次（与页脚一致）：规则提示是筛选辅助，不是买入信号。
 */

export interface FocusRow {
  symbol: string
  name?: string
  name_cn?: string
  sector?: string
  price?: number | null
  change_pct?: number | null
  score?: number | null
  signal_count?: number
  signals?: RowSignal[] | null
}

export default function PickCenter({
  focus,
  stats,
  catalog,
  activeSignal,
  onPickSignal,
  onOpenProfile,
  loading,
}: {
  focus: FocusRow[]
  stats: Record<string, number>
  catalog: SignalDef[]
  activeSignal: string | ''
  onPickSignal: (key: string) => void
  onOpenProfile: (sym: string) => void
  loading?: boolean
}) {
  const byKey = Object.fromEntries(catalog.map((d) => [d.key, d]))
  const activeDef = activeSignal ? byKey[activeSignal] : undefined
  // 统计条按「机会在前、数量降序」排
  const statEntries = Object.entries(stats).sort(([a], [b]) => {
    const ka = byKey[a]?.kind ?? ''
    const kb = byKey[b]?.kind ?? ''
    if (ka !== kb) return ka === 'opportunity' ? -1 : 1
    return (stats[b] ?? 0) - (stats[a] ?? 0)
  })

  return (
    <div className="space-y-3">
      {/* ---- 今日关注 ---- */}
      <div className="rounded-xl border border-slate-200 bg-white p-3">
        <div className="mb-2 flex flex-wrap items-center gap-2">
          <Crosshair className="h-3.5 w-3.5 text-brand-600" />
          <span className="text-xs font-semibold text-slate-700">今日关注</span>
          <span className="text-[11px] text-slate-400">
            全池 2200+ 只中按「机会信号数 → 综合评分」挑出前 12 只，机会信号需要多个独立条件同时满足
          </span>
          {loading && <Spinner />}
        </div>
        {focus.length === 0 ? (
          <p className="py-2 text-[11px] text-slate-400">
            暂无符合条件的标的 —— 机会信号要求至少两条独立证据（如「行业里便宜」+「盈利强」），
            行情 / 估值 / 技术指标数据补齐后会自动出现。
          </p>
        ) : (
          <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-4">
            {focus.map((f) => (
              <button
                key={f.symbol}
                onClick={() => onOpenProfile(f.symbol)}
                className="rounded-lg border border-slate-100 bg-slate-50/50 p-2.5 text-left transition-colors hover:border-brand-300 hover:bg-brand-50/40"
                title="查看公司档案"
              >
                <div className="mb-1 flex items-baseline gap-1.5">
                  <span className="text-sm font-semibold text-slate-800">{f.symbol}</span>
                  <span className="truncate text-[11px] text-slate-400">{f.name_cn || f.name}</span>
                  {typeof f.score === 'number' && (
                    <span className="num ml-auto text-[11px] font-medium text-brand-700">{f.score.toFixed(0)}分</span>
                  )}
                </div>
                <SignalBadges signals={f.signals} catalog={byKey} />
                {f.signals && f.signals.length > 0 && (
                  <p className="mt-1.5 line-clamp-2 text-[10px] leading-4 text-slate-400">{f.signals[0].reason}</p>
                )}
              </button>
            ))}
          </div>
        )}
        <p className="mt-2 flex items-start gap-1 text-[10px] leading-4 text-slate-400">
          <Info className="mt-px h-3 w-3 shrink-0" />
          关注 ≠ 买入信号：本项目复盘结论是规则化策略在收益上打不过买入持有，真实价值在回撤控制。
          请点开公司档案确认每个信号的触发原因后再做判断。
        </p>
      </div>

      {/* ---- 信号统计条（当前筛选结果内）---- */}
      {statEntries.length > 0 && (
        <div className="flex flex-wrap items-center gap-1.5 rounded-xl border border-slate-200 bg-white px-3 py-2">
          <span className="text-[11px] text-slate-400">当前结果中的信号</span>
          <button
            onClick={() => onPickSignal('')}
            className={`rounded px-1.5 py-0.5 text-[10px] transition-colors ${
              activeSignal === ''
                ? 'bg-brand-50 font-semibold text-brand-700'
                : 'text-slate-400 hover:text-brand-700'
            }`}
            title="显示全部（清除信号筛选）"
          >
            全部
          </button>
          {statEntries.map(([key, n]) => {
            const d = byKey[key]
            const active = activeSignal === key
            const opp = d?.kind !== 'warning'
            return (
              <button
                key={key}
                onClick={() => onPickSignal(active ? '' : key)}
                title={d ? `${d.brief} —— 点击${active ? '取消' : '只看'}该信号` : key}
                className={`inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] transition-colors ${
                  active
                    ? opp
                      ? 'bg-rose-600 font-semibold text-white'
                      : 'bg-amber-500 font-semibold text-white'
                    : opp
                      ? 'bg-rose-50 text-rose-700 hover:bg-rose-100'
                      : 'bg-amber-50 text-amber-700 hover:bg-amber-100'
                }`}
              >
                {d?.label ?? key}
                <span className={`num text-[9px] ${active ? 'text-white/80' : 'text-slate-400'}`}>{n}</span>
              </button>
            )
          })}
        </div>
      )}

      {/* ---- 信号说明目录 ---- */}
      {catalog.length > 0 && <SignalCatalog defs={catalog} />}

      {/* ---- 激活中的信号筛选提示 ---- */}
      {activeDef && (
        <div className="rounded-xl border border-rose-200 bg-rose-50/60 px-3 py-2 text-[11px] leading-5 text-rose-900">
          已按信号「{activeDef.label}」筛选 —— {activeDef.condition}。
          <button onClick={() => onPickSignal('')} className="ml-1 font-medium underline hover:no-underline">
            清除
          </button>
        </div>
      )}
    </div>
  )
}
