/**
 * 公司情报面板：选中标的 → 过去半年事件时间线 + 经营前瞻管道。
 *
 * 理念：财报是滞后指标——用「已敲定合同 / 在谈订单 / 传闻」的管道
 * 前瞻未来 3-6 个月经营状况（数据来自 AI 情报中心 /intel 事件库）。
 */
import { useEffect, useState } from 'react'
import { api } from '../lib/api'
import { Badge, Button, Card, Empty, Loading, Stat, Tabs } from './ui'

type Ev = {
  id: number
  occurred_on: string
  category: string
  category_cn: string
  title: string
  summary: string
  impact: number
  sentiment: string
  stage: string
  stage_cn: string
  source_name: string
  source_url: string
  agent: string
}

type Timeline = {
  symbol: string
  name: string
  days: number
  events: Ev[]
  counts: Record<string, number>
  pipeline: Record<string, number>
  visibility_score: number
  latest_analysis: {
    recommendation: string
    recommendation_cn: string
    confidence: number
    thesis: string
    catalysts: string
    risks: string
    position_pct: number
    horizon?: string
    event_score?: number | null
    agent: string
  } | null
  quote: { price?: number; name?: string; change_pct?: number }
}

const SENT_TONE: Record<string, { border: string; dot: string; text: string }> = {
  positive: { border: 'border-l-rose-400', dot: 'bg-rose-500', text: 'text-rose-600' },
  negative: { border: 'border-l-emerald-400', dot: 'bg-emerald-500', text: 'text-emerald-600' },
  neutral: { border: 'border-l-slate-300', dot: 'bg-slate-400', text: 'text-slate-500' },
}

const STAGE_BADGE: Record<string, { tone: 'green' | 'blue' | 'slate'; label: string }> = {
  confirmed: { tone: 'green', label: '✅ 已敲定' },
  negotiating: { tone: 'blue', label: '🔄 在谈' },
  rumor: { tone: 'slate', label: '❓ 传闻' },
}

export default function CompanyIntel({ symbol }: { symbol: string }) {
  const [data, setData] = useState<Timeline | null>(null)
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState('')
  const [days, setDays] = useState(180)

  useEffect(() => {
    let dead = false
    setLoading(true)
    setErr('')
    api
      .get<Timeline>(`/intel/timeline/${encodeURIComponent(symbol)}?days=${days}`, 45_000)
      .then((d) => {
        if (!dead) setData(d)
      })
      .catch((e: any) => {
        if (!dead) setErr(e?.message || '加载失败')
      })
      .finally(() => {
        if (!dead) setLoading(false)
      })
    return () => {
      dead = true
    }
  }, [symbol, days])

  if (loading) return <Loading label={`正在加载 ${symbol} 公司情报…`} className="h-64" />
  if (err) return <Empty title="加载失败" desc={`${err} —— 请确认 AI 情报中心已启动`} />

  const counts = data?.counts || {}
  const pipe = data?.pipeline || {}
  const vis = data?.visibility_score ?? 0
  const la = data?.latest_analysis
  const events = data?.events || []

  return (
    <div className="space-y-4">
      {/* 汇总卡 */}
      <Card
        title={`${symbol} 经营前瞻面板`}
        subtitle={`过去 ${data?.days ?? 180} 天 · 财报是滞后指标——用合同管道与事件流前瞻未来 3-6 个月经营状况`}
        actions={
          <Tabs
            value={String(days)}
            onChange={(k) => setDays(Number(k))}
            tabs={[
              { key: '90', label: '3 个月' },
              { key: '180', label: '半年' },
              { key: '365', label: '1 年' },
            ]}
          />
        }
      >
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-5">
          <Stat label="事件总数" value={String(counts.total ?? 0)} />
          <Stat label="正面 / 负面" value={`${counts.positive ?? 0} / ${counts.negative ?? 0}`} />
          <Stat
            label="✅ 已敲定"
            value={String(pipe.confirmed ?? 0)}
            tone={Number(pipe.confirmed ?? 0) > 0 ? 'up' : undefined}
          />
          <Stat label="🔄 在谈" value={String(pipe.negotiating ?? 0)} />
          <Stat
            label="经营可见性"
            value={String(vis)}
            tone={vis >= 8 ? 'up' : vis <= -4 ? 'down' : undefined}
            sub="已敲定×2 + 在谈×1 − 负面×2"
          />
        </div>
      </Card>

      {/* 最新 AI 建议 */}
      {la && (
        <Card
          title="最新 AI 建议（情报驱动）"
          actions={
            <span className="flex items-center gap-2">
              <Badge tone={la.recommendation.includes('buy') ? 'red' : la.recommendation.includes('sell') || la.recommendation === 'avoid' ? 'green' : 'slate'}>
                {la.recommendation_cn}
              </Badge>
              <Badge tone="slate">{la.agent || 'agent'}</Badge>
            </span>
          }
        >
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <Stat label="置信度" value={`${Math.round(la.confidence)}%`} />
            <Stat label="建议仓位" value={`${la.position_pct || 0}%`} />
            <Stat label="周期" value={la.horizon || 'swing'} />
            <Stat label="来源" value={la.agent || '—'} />
          </div>
          {la.thesis && <p className="mt-3 text-sm leading-relaxed text-slate-700">{la.thesis}</p>}
          {(la.catalysts || la.risks) && (
            <div className="mt-3 grid gap-2 text-xs sm:grid-cols-2">
              {la.catalysts && (
                <div className="rounded-lg border border-rose-100 bg-rose-50/60 p-2 text-rose-700">
                  <b>催化剂：</b>
                  {la.catalysts}
                </div>
              )}
              {la.risks && (
                <div className="rounded-lg border border-emerald-100 bg-emerald-50/60 p-2 text-emerald-700">
                  <b>风险：</b>
                  {la.risks}
                </div>
              )}
            </div>
          )}
        </Card>
      )}

      {/* 时间轴 */}
      <Card
        title="事件时间线"
        subtitle="按日期倒序 · 每条事件带来源链接可溯源 · ✅已敲定 / 🔄在谈 / ❓传闻 为经营前瞻管道"
      >
        {events.length === 0 ? (
          <Empty title="暂无已归档事件" desc={`在「AI 情报中心」添加 ${symbol} 并让外部 AI（WorkBuddy / Claude Code / Codex）跑一轮新闻检索，事件会自动出现在这里`} />
        ) : (
          <div className="relative ml-3 space-y-4 border-l-2 border-slate-100 pl-5">
            {events.map((e) => {
              const st = SENT_TONE[e.sentiment] || SENT_TONE.neutral
              const sb = STAGE_BADGE[e.stage]
              return (
                <div key={e.id} className={`relative rounded-lg border border-slate-100 border-l-[3px] ${st.border} bg-white p-3 shadow-xs`}>
                  <span className={`absolute -left-[27px] top-4 h-2.5 w-2.5 rounded-full ring-2 ring-white ${st.dot}`} />
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="num text-xs font-semibold text-slate-700">{e.occurred_on || '日期未知'}</span>
                    <Badge tone="blue">{e.category_cn}</Badge>
                    {sb && <Badge tone={sb.tone}>{sb.label}</Badge>}
                    <span className={`text-[10px] font-medium ${st.text}`}>
                      {e.sentiment === 'positive' ? '利多' : e.sentiment === 'negative' ? '利空' : '中性'}
                    </span>
                    <span className="ml-auto text-[10px] text-slate-300" title={`重要性 ${e.impact}/5 · 提交方 ${e.agent || '—'}`}>
                      {'★'.repeat(Math.max(1, Math.min(5, e.impact || 3)))}
                    </span>
                  </div>
                  <div className="mt-1.5 text-sm font-medium text-slate-800">{e.title}</div>
                  {e.summary && <p className="mt-1 text-xs leading-relaxed text-slate-500">{e.summary}</p>}
                  {e.source_url && (
                    <a
                      href={e.source_url}
                      target="_blank"
                      rel="noreferrer"
                      className="mt-1.5 inline-block text-[11px] text-brand-600 hover:underline"
                    >
                      来源：{e.source_name || e.source_url.slice(0, 60)}
                    </a>
                  )}
                </div>
              )
            })}
          </div>
        )}
      </Card>

      <Card>
        <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-slate-500">
          <span>
            💡 数据由外部 AI Agent（WorkBuddy / Claude Code / Codex）经 Bridge 协议检索提交 ·
            详见项目 <code>INTEL_BRIDGE_GUIDE.md</code>
          </span>
          <Button size="sm" onClick={() => window.open('http://127.0.0.1:8787/intel', '_blank')}>
            前往 AI 情报中心
          </Button>
        </div>
      </Card>
    </div>
  )
}
