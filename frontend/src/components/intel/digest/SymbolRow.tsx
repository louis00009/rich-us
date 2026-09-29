/**
 * 标的排序行：今天该盯哪几家
 *
 * 从 DailyDigest.tsx 抽出（铁律 9 拆分，2026-09-29）。
 */
import { type Digest, REC_LABEL, recBg, sentimentColor, TIER_STYLE, tierOf } from '../types'

export function SymbolRow({ s }: { s: Digest['by_symbol'][number] }) {
  const tier = tierOf(s.max_importance, 5)
  const st = TIER_STYLE[tier]
  const net = s.positive - s.negative
  return (
    <li className="flex flex-wrap items-center gap-2 rounded-lg border border-slate-100 bg-white px-3 py-2">
      <span className="w-14 shrink-0 text-sm font-semibold text-slate-800">{s.symbol}</span>
      <span className="min-w-0 max-w-[190px] truncate text-[11px] text-slate-400">{s.name || s.theme || '—'}</span>
      <span className={`num shrink-0 text-[11px] font-semibold ${st.text}`}>{s.max_importance.toFixed(0)}</span>
      <span className="shrink-0 text-[11px] text-slate-500">事件 {s.count}</span>
      {s.high_impact > 0 && (
        <span className="shrink-0 rounded bg-amber-50 px-1.5 py-0.5 text-[11px] text-amber-700">4★+ {s.high_impact}</span>
      )}
      <span
        className="shrink-0 text-[11px]"
        style={{ color: net >= 0 ? sentimentColor('positive') : sentimentColor('negative') }}
      >
        多 {s.positive} / 空 {s.negative}
      </span>
      {s.recommendation && (
        <span
          className="shrink-0 rounded px-1.5 py-0.5 text-[11px] font-semibold text-white"
          style={{ background: recBg(s.recommendation) }}
        >
          {REC_LABEL[s.recommendation]}
        </span>
      )}
      {/* 用户硬要求：所有信息必须能对上具体日期 —— top 事件的发生日 + 精确到分的时间 */}
      {(s.top_date || s.top_at) && (
        <span
          className="num shrink-0 rounded bg-slate-100 px-1.5 py-0.5 text-[11px] font-medium text-slate-500"
          title={`最重要事件发生时间：${s.top_at || s.top_date || '未知'}`}
        >
          {s.top_date || (s.top_at || '').slice(0, 10)}
          {s.top_at && s.top_at.length > 10 ? ` ${s.top_at.slice(11, 16)}` : ''}
        </span>
      )}
      <span className="min-w-0 flex-1 truncate text-right text-[11px] text-slate-400" title={s.top_title}>
        {s.top_title}
      </span>
    </li>
  )
}
