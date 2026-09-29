/**
 * 榜单多选工具条 + 一键 AI 分析
 * ==============================
 * 用户在榜单里勾选 1 只 → 「AI 深度分析」；勾选多只 → 「AI 对比分析」。
 * 两者走同一个后端任务 `stock_batch_review`（N=1 时自动切换成单股深度结构）。
 *
 * 为什么单独成文件：`pages/Rankings.tsx` 已贴 600 行软上限（铁律 9），
 * 所以勾选状态与工具条都封装在这里，页面只留 `useRowSelection` 一行 +
 * 一个 `<SelectionToolbar />` 挂载。
 */
import { useCallback, useEffect, useState } from 'react'
import { CheckSquare, FlaskConical, MessageSquare, Star, Trash2 } from 'lucide-react'
import { Badge, Button } from '../ui'
import AIAssist from '../AIAssist'
import type { RankRow } from './RankingsTable'

/**
 * 勾选状态。`rows` 变化（筛选/排序/翻页）后自动剔除已不在列表里的代码 ——
 * 否则用户切了筛选，工具条还挂着看不见的标的，「分析 5 只」实际只算出 2 只。
 */
export function useRowSelection(rows: { symbol: string }[]) {
  const [selected, setSelected] = useState<string[]>([])
  const key = rows.map((r) => r.symbol).join(',')

  useEffect(() => {
    setSelected((prev) => {
      const alive = new Set(key ? key.split(',') : [])
      const next = prev.filter((s) => alive.has(s))
      return next.length === prev.length ? prev : next
    })
  }, [key])

  const toggle = useCallback((s: string) => {
    setSelected((p) => (p.includes(s) ? p.filter((x) => x !== s) : [...p, s]))
  }, [])
  const toggleAll = useCallback(() => {
    setSelected((p) => (p.length === rows.length && rows.length > 0 ? [] : rows.map((r) => r.symbol)))
  }, [rows])
  const clear = useCallback(() => setSelected([]), [])

  return {
    selected,
    toggle,
    toggleAll,
    clear,
    allSelected: rows.length > 0 && selected.length === rows.length,
  }
}

/** 榜单行 → AI 任务的字段口径（后端 ai_tasks_screen._slim_row 期望的 key）。 */
function toAiRow(r: RankRow) {
  return {
    symbol: r.symbol,
    name: r.name,
    name_cn: r.name_cn,
    sector: r.sector,
    price: r.price,
    change_pct: r.change_pct,
    pe: r.pe_ttm,
    pb: r.pb,
    roe_pct: r.roe,
    div_yield: r.div_yield,
    market_cap: r.market_cap,
    score: r.score,
    dimensions: r.score_dims,
    rsi14: r.rsi14,
    ma200_rel: r.ma200_rel,
    r1y_pct: r.r1y,
    vol_ann: r.vol_ann,
    beta: r.beta,
  }
}

export default function SelectionToolbar({
  rows,
  selected,
  onClear,
  onToggleWatch,
  context,
  onOpenChat,
  onBacktest,
}: {
  rows: RankRow[]
  selected: string[]
  onClear: () => void
  /** 复用页面既有的关注切换（它已负责更新行状态），避免另写一套批量逻辑 */
  onToggleWatch: (row: RankRow) => void
  context?: string
  /** 打开多轮 AI 对话弹窗（勾选的标的作为上下文带入） */
  onOpenChat?: (symbols: string[]) => void
  /** 批量回测：把勾选标的（截断到 10 只）作为初始标的跳转回测中心 */
  onBacktest?: (symbols: string[]) => void
}) {
  // 注意：本组件**没有**任何 hook，所以这里的 early return 是安全的（不违反 hooks 规则）。
  if (selected.length === 0) return null

  const picked = rows.filter((r) => selected.includes(r.symbol))
  if (picked.length === 0) return null

  const one = picked.length === 1
  const unwatched = picked.filter((r) => !r.watched)
  const payload = { rows: picked.map(toAiRow), context: context || '榜单筛选结果' }

  return (
    <div className="sticky top-0 z-20 flex flex-wrap items-center gap-2 rounded-xl border border-brand-200 bg-brand-50/70 px-3 py-2 backdrop-blur">
      <CheckSquare className="h-4 w-4 text-brand-600" />
      <span className="text-xs font-medium text-brand-800">
        已选 {picked.length} 只
      </span>
      <span className="hidden max-w-[380px] truncate text-[11px] text-brand-700/70 sm:inline">
        {picked.map((r) => r.symbol).join('、')}
      </span>
      <div className="ml-auto flex flex-wrap items-center gap-2">
        {unwatched.length > 0 && (
          <Button
            size="sm"
            icon={<Star className="h-3.5 w-3.5" />}
            onClick={() => unwatched.forEach((r) => onToggleWatch(r))}
            title={`把选中的 ${unwatched.length} 只加入关注列表`}
          >
            加入关注（{unwatched.length}）
          </Button>
        )}
        {/* 多轮 AI 对话：勾选的标的作为上下文，弹窗内可连续追问 */}
        {onOpenChat && (
          <Button
            size="sm"
            icon={<MessageSquare className="h-3.5 w-3.5" />}
            onClick={() => onOpenChat(picked.map((r) => r.symbol))}
            title="打开 AI 对话弹窗：围绕选中的标的连续追问（模型可选）"
          >
            AI 问答
          </Button>
        )}
        {/* 批量回测：勾选标的作为初始标的跳转回测中心（走 prefill，最多 10 只） */}
        {onBacktest && (
          <Button
            size="sm"
            icon={<FlaskConical className="h-3.5 w-3.5" />}
            onClick={() => onBacktest(picked.map((r) => r.symbol).slice(0, 10))}
            title={`把选中的 ${Math.min(picked.length, 10)} 只带入回测中心`}
          >
            批量回测
          </Button>
        )}
        {/* 关键动作：1 只 = 深度分析；多只 = 横向对比。结果放在弹窗里，不挤占表格空间。 */}
        <AIAssist
          mode="modal"
          task="stock_batch_review"
          title={one ? `AI 个股深度分析 · ${picked[0].symbol}` : `AI 对比分析 · ${picked.length} 只`}
          desc={
            one
              ? '基于该标的的估值 / 质量 / 位置 / 趋势与综合评分做深度解读'
              : '横向对比这批标的的共同特征、关键差异、优先关注与风险'
          }
          label={one ? 'AI 深度分析' : `AI 对比分析（${picked.length} 只）`}
          payload={payload}
          runKey={selected.join(',')}
          emptyHint="AI 会逐只给出强弱差异，并挑出优先深挖的标的（只给研究优先级，不是买入建议）。"
        />
        <Button size="sm" icon={<Trash2 className="h-3.5 w-3.5" />} onClick={onClear} title="清空选择">
          清空
        </Button>
      </div>
      {picked.length > 1 && (
        <Badge tone="slate" className="order-first sm:order-none">
          对比模式
        </Badge>
      )}
    </div>
  )
}
