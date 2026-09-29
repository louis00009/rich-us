import { ArrowDown, ArrowUp, Star, StarOff } from 'lucide-react'
import { ReactNode } from 'react'
import { RankingColumn, RANKING_COLUMNS, COLUMN_MAP } from '../../lib/rankingColumns'
import { cell } from './cells'
import { useInfoTip, MetricTip, TipIcon } from './InfoTip'
import { ScoreInfo } from './ScoreCell'
import { RowSignal } from './SignalCell'

export interface RankRow extends ScoreInfo {
  symbol: string
  name: string
  name_cn?: string
  sector: string
  watched: boolean
  price: number
  prev_close: number
  change_pct: number
  volume: number
  amount: number
  market_cap?: number | null
  market_cap_float?: number | null
  pe_ttm?: number | null
  pe_state?: 'ok' | 'loss' | 'na'
  pe_pct?: number | null
  eps_ttm?: number | null
  pb?: number | null
  roe?: number | null
  div_yield?: number | null
  turnover?: number | null
  amplitude?: number | null
  w52_high?: number | null
  w52_low?: number | null
  pct_from_high?: number | null
  /* ---- 技术指标（1 年日线派生，可能为 null 表示数据未就绪） ---- */
  ma20_rel?: number | null
  ma60_rel?: number | null
  ma200_rel?: number | null
  ma_bull?: boolean | null
  ma_bear?: boolean | null
  r1m?: number | null
  r3m?: number | null
  r6m?: number | null
  r1y?: number | null
  excess_1y?: number | null
  rsi14?: number | null
  vol_ann?: number | null
  atr_pct?: number | null
  beta?: number | null
  /* ---- 选股中心信号（backend/app/signals.py 注入） ---- */
  signals?: RowSignal[] | null
  signal_count?: number
  risk_count?: number
}


/** 行内交互回调。导出以便 `cells.tsx` 复用同一份类型（`import type`，运行时无环）。 */
export interface Handlers {
  onToggleWatch: (row: RankRow) => void
  onOpenProfile: (sym: string) => void
  onAnalyze: (sym: string) => void
  /** 跳转回测中心并预填该标的（可选：不传则不显示「回测」按钮）。 */
  onBacktest?: (sym: string) => void
  /* ---- 选股中心扩展（可选：不传时信号 badge 只显示不联动） ---- */
  catalog?: Record<string, import('./SignalCell').SignalDef>
  onPickSignal?: (key: string) => void
}

/**
 * 表头单元格：**整个单元格**都是说明气泡的悬停触发区 —— 用户要求的是
 * 「鼠标移动到列的名字的时候需要提示」，只让那个 12px 问号图标可悬停等于没做。
 * 点击仍然用于排序（气泡没有 onClick，不抢事件）。
 *
 * 必须做成独立组件而不是在 map 里调 hook：循环里调 hook 违反 hooks 规则。
 */
function HeadCell({
  col,
  sort,
  dir,
  onSort,
}: {
  col: RankingColumn
  sort: string
  dir: 'asc' | 'desc'
  onSort: (key: string) => void
}) {
  const { ref, handlers, layer } = useInfoTip<HTMLTableCellElement>(col.label, <MetricTip {...col.tip} />)
  const active = sort === col.key

  return (
    <th
      ref={ref}
      {...handlers}
      onClick={col.sortable ? () => onSort(col.key) : undefined}
      className={`px-2 py-2 font-normal ${col.align === 'right' ? 'text-right' : ''} ${
        col.sortable ? 'cursor-pointer select-none hover:text-slate-600' : ''
      } ${active ? 'font-semibold text-brand-700' : ''}`}
    >
      <span className="inline-flex items-center gap-1 whitespace-nowrap align-middle">
        {col.label}
        {col.sortable && active ? (
          <span className="text-brand-500">
            {dir === 'desc' ? <ArrowDown className="h-3 w-3" /> : <ArrowUp className="h-3 w-3" />}
          </span>
        ) : null}
        <TipIcon label={col.label} />
      </span>
      {layer}
    </th>
  )
}

export default function RankingsTable({
  rows,
  visible,
  sort,
  dir,
  onSort,
  loading,
  empty,
  selected,
  onToggleSelect,
  onToggleAll,
  allSelected,
  ...handlers
}: {
  rows: RankRow[]
  visible: string[]
  sort: string
  dir: 'asc' | 'desc'
  onSort: (key: string) => void
  loading: boolean
  empty: ReactNode
  /** 已勾选的代码（用于「一键分析单只/多只」）。不传则不显示勾选列。 */
  selected?: string[]
  onToggleSelect?: (symbol: string) => void
  onToggleAll?: () => void
  allSelected?: boolean
} & Handlers) {
  const cols = visible.map((k) => COLUMN_MAP[k]).filter(Boolean)
  const pickable = !!onToggleSelect
  const backtestable = !!handlers.onBacktest
  const span = cols.length + 2 + (pickable ? 1 : 0) + (backtestable ? 1 : 0)
  const isSel = (s: string) => !!selected?.includes(s)

  return (
    <div className="overflow-x-auto rounded-xl border border-slate-200 bg-white">
      <table className="w-full text-sm" style={{ minWidth: 320 + cols.reduce((s, c) => s + c.width, 0) }}>
        <colgroup>
          {pickable && <col style={{ width: 30 }} />}
          <col style={{ width: 34 }} />
          {cols.map((c) => (
            <col key={c.key} style={{ width: c.width }} />
          ))}
          <col style={{ width: 78 }} />
          {handlers.onBacktest ? <col style={{ width: 56 }} /> : null}
        </colgroup>
        <thead>
          <tr className="border-b border-slate-100 text-left text-[11px] uppercase tracking-wide text-slate-400">
            {pickable && (
              <th className="px-2 py-2">
                <input
                  type="checkbox"
                  checked={!!allSelected}
                  onChange={() => onToggleAll?.()}
                  title={allSelected ? '取消全选' : '全选当前列表'}
                  aria-label="全选"
                  className="h-3.5 w-3.5 cursor-pointer rounded border-slate-300 text-brand-600"
                />
              </th>
            )}
            <th className="px-2 py-2" />
            {cols.map((c) => (
              <HeadCell key={c.key} col={c} sort={sort} dir={dir} onSort={onSort} />
            ))}
            <th className="px-2 py-2" />
            {backtestable && <th className="px-2 py-2" />}
          </tr>
        </thead>
        <tbody>
          {loading && rows.length === 0 && (
            <tr>
              <td colSpan={span} className="px-3 py-10 text-center text-xs text-slate-400">
                {empty}
              </td>
            </tr>
          )}
          {!loading && rows.length === 0 && (
            <tr>
              <td colSpan={span} className="px-3 py-10 text-center text-xs text-slate-400">
                {empty}
              </td>
            </tr>
          )}
          {rows.map((r) => (
            <tr
              key={r.symbol}
              className={`border-b border-slate-50 transition-colors ${
                isSel(r.symbol) ? 'bg-brand-50/50' : 'hover:bg-slate-50/60'
              }`}
            >
              {pickable && (
                <td className="px-2 py-2">
                  <input
                    type="checkbox"
                    checked={isSel(r.symbol)}
                    onChange={() => onToggleSelect?.(r.symbol)}
                    title={isSel(r.symbol) ? '取消选择' : '选择该标的'}
                    aria-label={`选择 ${r.symbol}`}
                    className="h-3.5 w-3.5 cursor-pointer rounded border-slate-300 text-brand-600"
                  />
                </td>
              )}
              <td className="px-2 py-2">
                <button
                  onClick={() => handlers.onToggleWatch(r)}
                  className="rounded p-0.5 text-slate-300 transition-colors hover:text-amber-500"
                  title={r.watched ? '取消关注' : '加入关注'}
                >
                  {r.watched ? (
                    <Star className="h-3.5 w-3.5 fill-amber-400 text-amber-400" />
                  ) : (
                    <StarOff className="h-3.5 w-3.5" />
                  )}
                </button>
              </td>
              {cols.map((c) => (
                <td
                  key={c.key}
                  className={`px-2 py-2 ${c.align === 'right' ? 'text-right' : ''} ${
                    c.key === 'symbol' ? 'max-w-[150px]' : ''
                  }`}
                >
                  {cell(c, r, handlers)}
                </td>
              ))}
              <td className="px-2 py-2 text-right">
                <div className="flex items-center justify-end gap-1">
                  {handlers.onBacktest && (
                    <button
                      onClick={() => handlers.onBacktest!(r.symbol)}
                      className="rounded-lg border border-slate-200 px-2 py-0.5 text-[11px] text-slate-500 transition-colors hover:border-brand-300 hover:text-brand-700"
                      title="以此标的跳转回测中心"
                    >
                      回测
                    </button>
                  )}
                  <button
                    onClick={() => handlers.onAnalyze(r.symbol)}
                    className="rounded-lg border border-slate-200 px-2 py-0.5 text-[11px] text-slate-500 transition-colors hover:border-brand-300 hover:text-brand-700"
                  >
                    分析
                  </button>
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

/** 列可见性菜单：勾选要显示的指标。 */
export function ColumnPicker({
  visible,
  onToggle,
  onReset,
}: {
  visible: string[]
  onToggle: (key: string) => void
  onReset: () => void
}) {
  return (
    <details className="relative">
      <summary className="cursor-pointer list-none rounded-lg border border-slate-200 px-2.5 py-1 text-xs text-slate-500 transition-colors hover:border-brand-300 hover:text-brand-700">
        列（{visible.length}/{RANKING_COLUMNS.length}）
      </summary>
      <div className="absolute right-0 z-40 mt-1 max-h-80 w-56 overflow-y-auto rounded-xl border border-slate-200 bg-white p-2 shadow-pop">
        {RANKING_COLUMNS.map((c) => (
          <label
            key={c.key}
            className="flex cursor-pointer items-center gap-2 rounded-lg px-2 py-1.5 text-xs text-slate-600 hover:bg-slate-50"
          >
            <input
              type="checkbox"
              checked={visible.includes(c.key)}
              onChange={() => onToggle(c.key)}
              className="h-3.5 w-3.5 rounded border-slate-300 text-brand-600"
            />
            {c.label}
          </label>
        ))}
        <button
          onClick={onReset}
          className="mt-1 w-full rounded-lg border-t border-slate-100 px-2 py-1.5 text-left text-xs text-slate-400 hover:text-brand-700"
        >
          恢复默认列
        </button>
      </div>
    </details>
  )
}
