/**
 * 单条事件卡：三档视觉分级
 *
 * 这是「突出重点」的核心 —— 重大（粗红边 + 大字号 + 为什么重要）与
 * 低影响（折叠成一行紧凑条目）两种形态差异极大，所以单独成组件。
 *
 * 从 EventFeed.tsx 抽出（铁律 9 拆分，2026-09-29）。
 */
import { useState } from 'react'
import { ChevronDown, ChevronRight, Trash2 } from 'lucide-react'
import { Badge } from '../ui'
import { fmtAgo } from '../../lib/format'
import { clampImpact, type EventItem, sentimentCn, sentimentColor, STAGE_TONE, TIER_STYLE, type Tier, tierOf } from './types'

export function EventCard({
  e,
  onDelete,
  defaultOpen,
}: {
  e: EventItem
  onDelete: (id: number) => void
  defaultOpen: boolean
}) {
  const [open, setOpen] = useState(defaultOpen)
  const tier: Tier = e.tier ?? tierOf(e.importance, e.impact)
  const st = TIER_STYLE[tier]
  const big = tier === 'critical' || tier === 'high'
  const reasons = e.importance_reasons ?? []

  // 低影响：折叠成一行紧凑条目，不占版面
  if (!big) {
    return (
      <li className="rounded-lg border border-slate-100 bg-white">
        <button
          onClick={() => setOpen((v) => !v)}
          className="flex w-full items-center gap-2 px-3 py-2 text-left hover:bg-slate-50/70"
        >
          {open ? (
            <ChevronDown className="h-3.5 w-3.5 shrink-0 text-slate-400" />
          ) : (
            <ChevronRight className="h-3.5 w-3.5 shrink-0 text-slate-400" />
          )}
          <span className="w-14 shrink-0 text-xs font-semibold text-slate-700">{e.symbol}</span>
          <span className="shrink-0 text-[11px] text-amber-500">{'★'.repeat(clampImpact(e.impact))}</span>
          {e.commentary && (
            <span
              className="shrink-0 rounded bg-slate-100 px-1.5 py-0.5 text-[10px] font-medium text-slate-500 ring-1 ring-inset ring-slate-200"
              title="媒体评论 / 行情播报，非公司自身事件 —— 重要度已封顶，不参与「必读」判定"
            >
              媒体
            </span>
          )}
          <span className="min-w-0 flex-1 truncate text-xs text-slate-500">{e.title}</span>
          <span className="num shrink-0 text-[11px] text-slate-400">{e.occurred_on || '—'}</span>
        </button>
        {open && (
          <div className="border-t border-slate-100 px-3 py-2 pl-9">
            {e.summary && <p className="text-xs leading-relaxed text-slate-500">{e.summary}</p>}
            <div className="mt-1 flex flex-wrap items-center gap-2 text-[11px] text-slate-400">
              <Badge tone="blue">{e.category_cn || e.category}</Badge>
              {e.source_url ? (
                <a
                  href={e.source_url}
                  target="_blank"
                  rel="noreferrer"
                  className="truncate text-brand-600 hover:underline"
                >
                  {e.source_name || e.source_url}
                </a>
              ) : (
                <span>{e.source_name || '来源未提供'}</span>
              )}
              <button
                title="删除该节点"
                className="ml-auto rounded p-1 text-slate-300 hover:bg-rose-50 hover:text-rose-600"
                onClick={() => onDelete(e.id)}
              >
                <Trash2 className="h-3 w-3" />
              </button>
            </div>
          </div>
        )}
      </li>
    )
  }

  return (
    <li
      className={`relative rounded-lg border ${tier === 'critical' ? 'border-rose-200' : 'border-amber-100'} ${st.bg} p-3 pl-4`}
      style={{ borderLeft: `4px solid ${st.border}` }}
    >
      <div className="flex flex-wrap items-center gap-2">
        <span className={`rounded px-1.5 py-0.5 text-[11px] font-semibold ring-1 ring-inset ${st.badge}`}>{st.label}</span>
        <span className="text-base font-bold text-slate-900">{e.symbol}</span>
        <Badge tone="blue">{e.category_cn || e.category}</Badge>
        {e.stage_cn && (
          <span
            className={`rounded-md px-2 py-0.5 text-[11px] font-medium ring-1 ring-inset ${STAGE_TONE[e.stage ?? ''] ?? 'bg-slate-100 text-slate-500 ring-slate-200'}`}
          >
            {e.stage_cn}
          </span>
        )}
        <span className="text-[11px] font-medium" style={{ color: sentimentColor(e.sentiment) }}>
          {sentimentCn(e.sentiment)} {clampImpact(e.impact)}★
        </span>
        <span className="ml-auto flex items-center gap-2">
          {e.importance != null && (
            <span
              className={`num text-xs font-semibold ${st.text}`}
              title="确定性重要度（影响度×新鲜度×类别×阶段×来源）"
            >
              重要度 {e.importance}
            </span>
          )}
          <span className="num text-[11px] text-slate-400">{e.occurred_on || '日期未知'}</span>
          <button
            title="删除该节点"
            className="rounded p-1 text-slate-300 hover:bg-rose-50 hover:text-rose-600"
            onClick={() => onDelete(e.id)}
          >
            <Trash2 className="h-3 w-3" />
          </button>
        </span>
      </div>

      <p
        className={`mt-1.5 ${tier === 'critical' ? 'text-[15px] font-semibold' : 'text-sm font-medium'} leading-snug text-slate-800`}
      >
        {e.title}
      </p>
      {e.summary && <p className="mt-1 text-xs leading-relaxed text-slate-600">{e.summary}</p>}

      {reasons.length > 0 && (
        <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
          <span className="text-[11px] font-medium text-slate-500">为什么重要：</span>
          {reasons.map((r) => (
            <span
              key={r}
              className="rounded bg-white/80 px-1.5 py-0.5 text-[11px] text-slate-600 ring-1 ring-inset ring-slate-200"
            >
              {r}
            </span>
          ))}
        </div>
      )}

      <div className="mt-1.5 flex flex-wrap items-center gap-2 text-[11px] text-slate-400">
        <Badge tone="violet">{e.agent || 'unknown'}</Badge>
        {e.source_url ? (
          <a href={e.source_url} target="_blank" rel="noreferrer" className="truncate text-brand-600 hover:underline">
            {e.source_name || e.source_url}
          </a>
        ) : (
          <span>{e.source_name || '来源未提供'}</span>
        )}
        <span className="ml-auto">提交 {fmtAgo(e.created_at)}</span>
      </div>
    </li>
  )
}
