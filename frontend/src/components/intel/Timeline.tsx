/**
 * 公司专属时间线 + 价格叠加层
 *
 * 从 `pages/Intel.tsx` 原样迁出（该页面超硬上限），行为不变：
 *   · PriceOverlay —— 日线收盘曲线，事件按发生日钉在对应价位上
 *   · TimelineView —— 最新事件在上，AI 判定作为特殊节点嵌在时间轴顶端
 */
import { useEffect, useState } from 'react'
import { Badge, Tabs } from '../ui'
import { api } from '../../lib/api'
import { fmtAgo, fmtNum } from '../../lib/format'
import {
  clampImpact,
  eventAgeDays,
  type Analysis,
  type EventItem,
  type PriceSeries,
  REC_LABEL,
  recBg,
  sentimentColor,
} from './types'

export const EVENT_FACE_DAYS = 90

/**
 * 价格叠加层：日线收盘曲线，事件按发生日钉在对应价位上
 * （利好=红 / 利空=绿 / 中性=灰，圆点大小=影响度），事件对股价的影响一眼可见。
 */
export function PriceOverlay({ symbol, events, big = false }: { symbol: string; events: EventItem[]; big?: boolean }) {
  const [days, setDays] = useState(30)
  const [tip, setTip] = useState<{ e: EventItem; x: number; y: number; px: number } | null>(null)
  const [data, setData] = useState<PriceSeries | null>(null)
  const [err, setErr] = useState('')

  useEffect(() => {
    setData(null)
    setErr('')
    api.get<PriceSeries>(`/intel/history/${symbol}?days=${days}`).then(setData).catch((e) => setErr(e.message))
  }, [symbol, days])

  if (err) return <div className="mb-3 rounded-lg bg-slate-50 px-3 py-2 text-[11px] text-slate-400">价格曲线不可用（{err}）</div>
  if (!data || data.close.length < 2) return null

  const W = 640
  const H = 110
  const PAD = 10
  const n = data.close.length
  const min = Math.min(...data.close)
  const max = Math.max(...data.close)
  const span = max - min || 1
  const xs = (i: number) => PAD + (i * (W - 2 * PAD)) / (n - 1)
  const ys = (v: number) => H - PAD - ((v - min) / span) * (H - 2 * PAD)
  const line = data.close.map((v, i) => `${i ? 'L' : 'M'}${xs(i).toFixed(1)},${ys(v).toFixed(1)}`).join(' ')
  const area = `${line} L${xs(n - 1).toFixed(1)},${H - PAD} L${xs(0).toFixed(1)},${H - PAD} Z`

  // 事件钉点：occurred_on → 数据中 ≤ 该日的最近交易日
  const dots = events
    .filter((e) => /^\d{4}-\d{2}-\d{2}$/.test(e.occurred_on || ''))
    .map((e) => {
      let idx = -1
      for (let i = n - 1; i >= 0; i--) {
        if (data.dates[i] <= e.occurred_on) {
          idx = i
          break
        }
      }
      if (idx < 0) return null
      return { e, x: xs(idx), y: ys(data.close[idx]), px: data.close[idx] }
    })
    .filter(Boolean) as { e: EventItem; x: number; y: number; px: number }[]

  const first = data.dates[0]
  const last = data.dates[n - 1]

  return (
    <div className="mb-4 rounded-lg border border-slate-100 bg-slate-50/60 p-2">
      <div className="mb-1 flex flex-wrap items-center gap-2 px-1 text-[11px] text-slate-400">
        <span className="font-medium text-slate-600">
          {symbol} 股价 · 近 {days} 天
        </span>
        <span>
          最低 {fmtNum(min)} / 最高 {fmtNum(max)}
        </span>
        <span className="ml-auto">
          来源 {data.source} · {first} ~ {last}
        </span>
        <Tabs
          value={String(days)}
          onChange={(k) => setDays(Number(k))}
          tabs={[
            { key: '7', label: '1 周' },
            { key: '30', label: '1 个月' },
            { key: '90', label: '3M' },
            { key: '180', label: '6M' },
            { key: '365', label: '1Y' },
          ]}
        />
      </div>
      <div className="relative">
        <svg viewBox={`0 0 ${W} ${H}`} className={big ? 'h-52 w-full' : 'h-28 w-full'} preserveAspectRatio="none">
          <defs>
            <linearGradient id="pxfill" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#6366f1" stopOpacity="0.18" />
              <stop offset="100%" stopColor="#6366f1" stopOpacity="0.01" />
            </linearGradient>
          </defs>
          <path d={area} fill="url(#pxfill)" />
          <path d={line} fill="none" stroke="#6366f1" strokeWidth="1.8" />
          {dots.map(({ e, x, y, px }) => {
            const c = sentimentColor(e.sentiment)
            const r = 3 + clampImpact(e.impact) * 0.7
            return (
              <g key={e.id}>
                <line x1={x} y1={y} x2={x} y2={H - PAD} stroke={c} strokeOpacity="0.25" strokeDasharray="2 3" />
                <circle
                  cx={x}
                  cy={y}
                  r={tip && tip.e.id === e.id ? r + 2 : r}
                  fill={c}
                  stroke="#fff"
                  strokeWidth="1.2"
                  opacity="0.9"
                  className="cursor-pointer"
                  onMouseEnter={() => setTip({ e, x, y, px })}
                  onMouseLeave={() => setTip(null)}
                />
              </g>
            )
          })}
        </svg>
        {tip && (
          <div
            className="pointer-events-none absolute z-30 w-64 rounded-lg border border-slate-300 bg-white p-3 shadow-xl"
            style={{ left: `${Math.min(78, Math.max(2, (tip.x / W) * 100))}%`, top: 6 }}
          >
            <div className="flex items-center gap-1.5 text-[11px]">
              <span className="num font-semibold text-slate-700">
                {tip.e.occurred_on || '日期未知'}
                {tip.e.occurred_at ? ` ${tip.e.occurred_at.slice(11)}` : ''}
              </span>
              <span
                className={`font-medium ${
                  tip.e.sentiment === 'positive' ? 'text-rose-600' : tip.e.sentiment === 'negative' ? 'text-emerald-600' : 'text-slate-500'
                }`}
              >
                {tip.e.sentiment === 'positive' ? '利多' : tip.e.sentiment === 'negative' ? '利空' : '中性'} {clampImpact(tip.e.impact)}★
              </span>
              <span className="num ml-auto text-slate-500">收盘 {fmtNum(tip.px)}</span>
            </div>
            <div className="mt-1 text-xs font-medium leading-snug text-slate-800">{tip.e.title}</div>
            {tip.e.summary && <p className="mt-1 line-clamp-3 text-[11px] leading-relaxed text-slate-500">{tip.e.summary}</p>}
            {tip.e.source_url && <div className="mt-1 truncate text-[10px] text-brand-600">来源：{tip.e.source_name || tip.e.source_url}</div>}
          </div>
        )}
        {dots.length > 0 && (
          <div className="px-1 pt-1 text-[10px] text-slate-400">
            图上圆点 = 事件（悬停查看详情）：颜色=利好/利空，大小=影响度，位置=当日收盘价
          </div>
        )}
      </div>
    </div>
  )
}

/**
 * 公司专属时间线：最新事件在上，AI 判定作为特殊节点嵌在时间轴顶端，
 * 把「新闻串联 → 结论」做成一条可视化的因果链。
 */
export function TimelineView({
  symbol,
  events,
  analysis,
  big = false,
}: {
  symbol: string
  events: EventItem[]
  analysis: Analysis | null
  big?: boolean
}) {
  const sorted = [...events].sort((a, b) => {
    const da = a.occurred_on || ''
    const db = b.occurred_on || ''
    // 日期未知的事件排最后，避免占据时间轴顶端
    if (da !== db) {
      if (!da) return 1
      if (!db) return -1
      return db.localeCompare(da)
    }
    // 同日：先按发生时刻倒序，无时刻则退回创建时间
    const ta = a.occurred_at || ''
    const tb = b.occurred_at || ''
    if (ta !== tb) return tb.localeCompare(ta)
    return String(b.created_at).localeCompare(String(a.created_at))
  })
  const pos = events.filter((e) => e.sentiment === 'positive').length
  const neg = events.filter((e) => e.sentiment === 'negative').length
  const neu = events.length - pos - neg
  const recent = events.filter((e) => (eventAgeDays(e) ?? EVENT_FACE_DAYS + 1) <= EVENT_FACE_DAYS).length

  return (
    <div>
      <PriceOverlay symbol={symbol} events={events} big={big} />

      <div className="mb-3 flex flex-wrap items-center gap-2 text-[11px]">
        <Badge tone="brand">
          近 {EVENT_FACE_DAYS} 天 {recent} 条
        </Badge>
        <span className="font-medium" style={{ color: sentimentColor('positive') }}>
          利好 {pos}
        </span>
        <span className="font-medium" style={{ color: sentimentColor('negative') }}>
          利空 {neg}
        </span>
        <span className="text-slate-400">中性 {neu}</span>
        <span className="ml-auto text-slate-400">按事件发生日排序 · 越靠上越新</span>
      </div>

      <div className="relative">
        <div className="absolute bottom-3 left-[86px] top-3 w-px bg-slate-200" />
        <ol className="space-y-3">
          {analysis && (
            <li className="flex gap-3">
              <div className="w-[74px] shrink-0 pt-1.5 text-right text-[11px] font-semibold text-amber-600">AI 判定</div>
              <div className="relative z-10 mt-1.5 h-4 w-4 shrink-0 rounded-full border-[3px] border-amber-400 bg-white" />
              <div className="min-w-0 flex-1 rounded-lg border border-amber-200 bg-amber-50/60 p-3">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="rounded px-2 py-0.5 text-[11px] font-semibold text-white" style={{ background: recBg(analysis.recommendation) }}>
                    {REC_LABEL[analysis.recommendation]}
                  </span>
                  <span className="text-[11px] text-slate-500">
                    置信度 {analysis.confidence.toFixed(0)}% · 仓位 {analysis.position_pct}%
                    {analysis.event_score != null && ` · 事件面 ${analysis.event_score > 0 ? '+' : ''}${analysis.event_score}`}
                  </span>
                  <span className="ml-auto text-[11px] text-slate-400">
                    基于 {analysis.based_on_events?.length ?? 0} 条事件 · {fmtAgo(analysis.created_at)}
                  </span>
                </div>
                {analysis.thesis && <p className="mt-1.5 text-xs leading-relaxed text-slate-600">{analysis.thesis}</p>}
              </div>
            </li>
          )}

          {sorted.map((e) => {
            const dot = sentimentColor(e.sentiment)
            return (
              <li key={e.id} className="flex gap-3">
                <div className="w-[74px] shrink-0 pt-2 text-right">
                  <div className="text-[11px] font-medium text-slate-600">{e.occurred_on || '—'}</div>
                  <div className="num text-[10px] text-slate-400">
                    {e.occurred_at ? `${e.occurred_at.slice(11)} UTC` : e.occurred_on ? '时刻未知' : '日期未知'}
                  </div>
                </div>
                <div className="relative z-10 mt-2 h-3.5 w-3.5 shrink-0 rounded-full border-[3px] bg-white" style={{ borderColor: dot }} />
                <div className="min-w-0 flex-1 rounded-lg border border-slate-100 bg-white p-2.5" style={{ borderLeft: `3px solid ${dot}` }}>
                  <div className="flex flex-wrap items-center gap-1.5">
                    <Badge tone="blue">{e.category_cn || e.category}</Badge>
                    {e.stage_cn && <Badge tone="green">{e.stage_cn}</Badge>}
                    <span className="text-[11px] text-amber-500" title={`影响度 ${clampImpact(e.impact)}/5`}>
                      {'★'.repeat(clampImpact(e.impact))}
                    </span>
                    <Badge tone="violet">{e.agent || 'unknown'}</Badge>
                    <span className="ml-auto text-[10px] text-slate-400">
                      {eventAgeDays(e) != null ? `${eventAgeDays(e)} 天前` : ''}
                    </span>
                  </div>
                  <p className="mt-1 text-sm font-medium text-slate-700">{e.title}</p>
                  {e.summary && <p className="mt-0.5 line-clamp-2 text-xs leading-relaxed text-slate-500">{e.summary}</p>}
                  <div className="mt-1 flex items-center gap-2 text-[11px]">
                    {e.source_url ? (
                      <a href={e.source_url} target="_blank" rel="noreferrer" className="truncate text-brand-600 hover:underline">
                        {e.source_name || e.source_url}
                      </a>
                    ) : (
                      <span className="truncate text-slate-400">{e.source_name || '来源未提供'}</span>
                    )}
                  </div>
                </div>
              </li>
            )
          })}
        </ol>
      </div>
    </div>
  )
}
