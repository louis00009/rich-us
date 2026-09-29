/**
 * 单条必读：重要度 + 为什么重要 + 摘要（可展开）
 *
 * 从 DailyDigest.tsx 抽出（铁律 9 拆分，2026-09-29）。
 */
import { useState } from 'react'
import { Badge } from '../../ui'
import { type DigestItem, sentimentCn, sentimentColor, TIER_STYLE, type Tier, tierOf } from '../types'

export function TopItem({ it, rank }: { it: DigestItem; rank: number }) {
  const [open, setOpen] = useState(rank <= 3)
  const tier: Tier = it.tier ?? tierOf(it.importance, it.impact)
  const st = TIER_STYLE[tier]
  return (
    <li
      className={`rounded-lg border ${tier === 'critical' ? 'border-rose-200' : 'border-slate-200'} ${st.bg} p-2.5 pl-3`}
      style={{ borderLeft: `4px solid ${st.border}` }}
    >
      <div className="flex flex-wrap items-center gap-2">
        <span className="num w-5 shrink-0 text-center text-[11px] font-semibold text-slate-400">{rank}</span>
        <span className={`rounded px-1.5 py-0.5 text-[11px] font-semibold ring-1 ring-inset ${st.badge}`}>{st.label}</span>
        <span className="text-sm font-bold text-slate-900">{it.symbol}</span>
        <span className="text-[11px] font-medium" style={{ color: sentimentColor(it.sentiment) }}>
          {sentimentCn(it.sentiment)}
        </span>
        <span className="text-[11px] text-amber-500">{'★'.repeat(Math.max(1, Math.min(5, it.impact)))}</span>
        {it.stage_cn && <Badge tone="green">{it.stage_cn}</Badge>}
        <span className="ml-auto flex items-center gap-2">
          <span className={`num text-[11px] font-semibold ${st.text}`} title="确定性重要度">
            {it.importance}
          </span>
          <span
            className="num text-[11px] text-slate-400"
            title={`事件发生时间：${it.occurred_at || it.occurred_on || '未知'}`}
          >
            {it.occurred_at
              ? `${it.occurred_at.slice(0, 10)} ${it.occurred_at.slice(11, 16)}`
              : it.occurred_on || '日期未知'}
          </span>
        </span>
      </div>
      <button className="mt-1 block w-full text-left" onClick={() => setOpen((v) => !v)}>
        <p
          className={`${tier === 'critical' ? 'text-[14px] font-semibold' : 'text-[13px] font-medium'} leading-snug text-slate-800`}
        >
          {it.title}
        </p>
      </button>
      {(it.reasons?.length ?? 0) > 0 && (
        <div className="mt-1 flex flex-wrap items-center gap-1.5">
          <span className="text-[11px] font-medium text-slate-500">为什么重要：</span>
          {it.reasons.map((r) => (
            <span
              key={r}
              className="rounded bg-white/80 px-1.5 py-0.5 text-[11px] text-slate-600 ring-1 ring-inset ring-slate-200"
            >
              {r}
            </span>
          ))}
        </div>
      )}
      {open && it.summary && <p className="mt-1.5 text-xs leading-relaxed text-slate-600">{it.summary}</p>}
      <div className="mt-1 flex flex-wrap items-center gap-2 text-[11px] text-slate-400">
        <span>{it.category_cn || it.category}</span>
        <span className="text-slate-300">·</span>
        {it.source_url ? (
          <a href={it.source_url} target="_blank" rel="noreferrer" className="truncate text-brand-600 hover:underline">
            {it.source_name || it.source_url}
          </a>
        ) : (
          <span>{it.source_name || '来源未提供'}</span>
        )}
        <span className="ml-auto">{it.agent || 'unknown'}</span>
      </div>
    </li>
  )
}
