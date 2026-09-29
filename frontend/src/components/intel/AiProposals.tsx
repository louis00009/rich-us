/**
 * AI 买入建议 + 建议验证
 *
 * 从 `pages/Intel.tsx` 抽出（页面超硬上限），行为与文案保持：
 *   · 建议卡：判定 / 置信度 / 仓位 / 事件面 / 依据事件（可溯源）/ 7 天对账结果
 *   · 验证卡：每个 Agent 的胜率与置信度校准（该信谁，数据说话）
 */
import { useCallback, useEffect, useState } from 'react'
import { Bot, Zap } from 'lucide-react'
import { Badge, Button, Card, Empty, Progress, useToast } from '../ui'
import { api } from '../../lib/api'
import { fmtAgo } from '../../lib/format'
import {
  type Analysis,
  type EventItem,
  fmtSince,
  fmtUtc,
  REC_LABEL,
  recBg,
  sentimentColor,
  type VerifyStats,
} from './types'

export function ProposalCard({ analyses, events }: { analyses: Analysis[]; events: EventItem[] }) {
  return (
    <Card
      className="flex shrink-0 flex-col"
      title="AI 买入建议"
      subtitle="事件面 + 量化快照 → 结构化建议（红=看多 绿=看空，跟随配色习惯）"
      bodyClass="min-h-0 flex-1 space-y-3 overflow-y-auto"
    >
      {analyses.length === 0 ? (
        <Empty icon={<Bot className="h-8 w-8" />} title="暂无建议" desc="开启监控或点击观察标的上方的 ⚡ 立即分析" />
      ) : (
        analyses.map((a) => (
          <div key={a.id} className="rounded-lg border border-slate-100 bg-white p-3">
            <div className="flex items-center gap-2">
              <span className="text-sm font-semibold text-slate-800">{a.symbol}</span>
              <span className="rounded px-2 py-0.5 text-[11px] font-semibold text-white" style={{ background: recBg(a.recommendation) }}>
                {REC_LABEL[a.recommendation]}
              </span>
              {/* 用户硬要求：具体日期优先，相对时间仅作辅助 */}
              <span className="ml-auto text-[11px] text-slate-400" title={`建议生成时间：${fmtUtc(a.created_at)}`}>
                {fmtUtc(a.created_at)}（{fmtAgo(a.created_at)}）
              </span>
            </div>
            <div className="mt-2">
              <div className="flex items-center justify-between text-[11px] text-slate-400">
                <span>置信度</span>
                <span>
                  {a.confidence.toFixed(0)}% · 建议仓位 {a.position_pct}% ·{' '}
                  {a.engine === 'agent' ? '外部 Agent' : a.engine === 'llm' ? 'LLM' : '本地引擎'}
                </span>
              </div>
              <div className="mt-1">
                <Progress value={a.confidence} max={100} />
              </div>
            </div>
            {(a.event_score != null || (a.based_on_events?.length ?? 0) > 0) && (
              <div className="mt-2 flex flex-wrap items-center gap-1.5 text-[11px]">
                {a.event_score != null && (
                  <span
                    className="rounded px-1.5 py-0.5 font-medium"
                    style={{
                      background: `${a.event_score >= 0 ? sentimentColor('positive') : sentimentColor('negative')}1A`,
                      color: a.event_score >= 0 ? sentimentColor('positive') : sentimentColor('negative'),
                    }}
                  >
                    事件面 {a.event_score > 0 ? '+' : ''}
                    {a.event_score}
                  </span>
                )}
                {(a.based_on_events?.length ?? 0) > 0 && <Badge tone="amber">依据 {a.based_on_events!.length} 条近期事件</Badge>}
              </div>
            )}
            {a.thesis && <p className="mt-2 text-xs leading-relaxed text-slate-600">{a.thesis}</p>}
            {a.based_on_events && a.based_on_events.length > 0 && (
              <details className="mt-1.5">
                <summary className="cursor-pointer text-[11px] text-brand-600 hover:underline">查看依据的事件节点</summary>
                <ul className="mt-1 space-y-0.5 border-l-2 border-slate-100 pl-2.5">
                  {a.based_on_events.map((id) => {
                    const ev = events.find((x) => x.id === id)
                    return (
                      <li key={id} className="truncate text-[11px] text-slate-500">
                        {ev ? (
                          <>
                            <span className="text-slate-400">
                              {ev.occurred_on || ''}
                              {ev.occurred_at ? ` ${ev.occurred_at.slice(11)}` : ''}{' '}
                            </span>
                            {ev.title}
                          </>
                        ) : (
                          `事件 #${id}（切换到该公司时间线可查看）`
                        )}
                      </li>
                    )
                  })}
                </ul>
              </details>
            )}
            {a.catalysts && (
              <p className="mt-1.5 text-[11px] text-slate-500">
                <b className="text-slate-600">催化剂：</b>
                {a.catalysts}
              </p>
            )}
            {a.risks && (
              <p className="mt-1 text-[11px] text-slate-500">
                <b className="text-slate-600">风险：</b>
                {a.risks}
              </p>
            )}
            {a.invalidation && (
              <p className="mt-1 text-[11px] text-rose-500/90">
                <b>失效条件：</b>
                {a.invalidation}
              </p>
            )}
            {a.outcome_checked_at && a.outcome_return != null && (
              <div className="mt-2 flex flex-wrap items-center gap-1.5 text-[11px]">
                <span
                  className="rounded px-1.5 py-0.5 font-semibold text-white"
                  style={{ background: a.outcome_hit ? sentimentColor('positive') : sentimentColor('negative') }}
                >
                  {a.outcome_window_days ?? 7} 天对账 {a.outcome_return > 0 ? '+' : ''}
                  {a.outcome_return}% {a.outcome_hit ? '✓ 命中' : a.outcome_hit === false ? '✗ 未中' : '— 平'}
                </span>
                {a.outcome_benchmark != null && (
                  <span className="text-slate-500">
                    同期基准 {a.outcome_benchmark > 0 ? '+' : ''}
                    {a.outcome_benchmark}% · 超额{' '}
                    {(a.outcome_return - a.outcome_benchmark) > 0 ? '+' : ''}
                    {(a.outcome_return - a.outcome_benchmark).toFixed(2)}%
                  </span>
                )}
                {a.outcome_price != null && <span className="text-slate-400">验证价 {a.outcome_price}</span>}
              </div>
            )}
            {a.price_at_analysis > 0 && (
              <p className="mt-1 text-[11px] text-slate-400">
                分析时价格 {a.price_at_analysis} · Agent {a.agent}
              </p>
            )}
          </div>
        ))
      )}
    </Card>
  )
}

/** 建议验证面板：每个 Agent 的 7 天胜率与置信度校准（该信谁，数据说话）。 */
export function VerifyCard() {
  const toast = useToast()
  const [st, setSt] = useState<VerifyStats | null>(null)
  const [busy, setBusy] = useState(false)

  const load = useCallback(() => {
    api.get<VerifyStats>('/intel/verify/stats').then(setSt).catch(() => {})
  }, [])
  useEffect(load, [load])

  const runVerify = async () => {
    setBusy(true)
    try {
      const d = await api.post<{ verified: number; stats: VerifyStats }>('/intel/verify/run')
      setSt(d.stats)
      const w = d.stats.window_days_by_horizon
      const wTxt = w ? `intraday ${w.intraday}/swing ${w.swing}/position ${w.position} 天` : '7 天'
      toast('success', d.verified > 0 ? `已对账 ${d.verified} 条到期建议` : `暂无到期（窗口 ${wTxt}）的建议需要对账`)
    } catch (e: any) {
      toast('error', e.message)
    } finally {
      setBusy(false)
    }
  }

  const wMap = st?.window_days_by_horizon
  const subtitle = wMap
    ? `窗口 intraday ${wMap.intraday}/swing ${wMap.swing}/position ${wMap.position} 天 · 基准 ${st?.benchmark ?? 'SPY'}（跑赢大盘才算看对） · ±${st?.tolerance_pct ?? 1}% 死区为平 · hold 横在 ±3% 内算对`
    : `窗口 ${st?.window_days ?? 7} 天 · ±${st?.tolerance_pct ?? 1}% 死区为平 · 看多涨算对、看空跌算对，hold 横在 ±3% 内算对`

  return (
    <Card
      className="shrink-0"
      title="建议验证 · 谁的建议靠谱"
      subtitle={subtitle}
      actions={
        <Button size="sm" variant="secondary" loading={busy} icon={<Zap className="h-3.5 w-3.5" />} onClick={runVerify}>
          立即对账
        </Button>
      }
    >
      {!st ? (
        <Empty title="加载中…" />
      ) : st.agents.length === 0 ? (
        <Empty
          title="还没有已对账的建议"
          desc={`建议满各自 horizon 窗口（intraday 2 / swing 7 / position 30 天）后自动结算（监控开启时每小时核对一次），也可点「立即对账」提前结算。已验证 ${st.verified_total} / ${st.analyses_total} 条，待对账 ${st.pending} 条`}
        />
      ) : (
        <>
          <div className="mb-2 flex flex-wrap gap-2 text-[11px] text-slate-500">
            <Badge tone="brand">全局胜率 {st.global_hit_rate ?? '—'}%</Badge>
            {st.global_avg_excess_return != null && (
              <Badge tone={st.global_avg_excess_return >= 0 ? 'green' : 'red'}>
                全局超额 {st.global_avg_excess_return > 0 ? '+' : ''}
                {st.global_avg_excess_return}%（vs {st.benchmark ?? 'SPY'}）
              </Badge>
            )}
            {st.global_brier != null && (
              <Badge tone={st.global_brier <= 0.25 ? 'green' : 'red'}>Brier {st.global_brier}</Badge>
            )}
            <span>
              已验证 {st.verified_total} 条 · 待对账 {st.pending} 条
            </span>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-slate-200 text-left text-slate-400">
                  <th className="py-2 pr-3 font-medium">Agent</th>
                  <th className="py-2 pr-3 font-medium">已验证 / 命中</th>
                  <th className="py-2 pr-3 font-medium">胜率</th>
                  <th className="py-2 pr-3 font-medium">平均实际收益</th>
                  <th className="py-2 pr-3 font-medium">平均超额</th>
                  <th className="py-2 pr-3 font-medium">平均置信度</th>
                  <th className="py-2 pr-3 font-medium">Brier</th>
                </tr>
              </thead>
              <tbody>
                {st.agents.map((a) => (
                  <tr key={a.agent} className="border-b border-slate-50 text-slate-600">
                    <td className="py-2 pr-3 font-semibold text-slate-700">{a.agent}</td>
                    <td className="py-2 pr-3">
                      {a.n} / {a.hits}
                    </td>
                    <td className="py-2 pr-3">
                      <div className="flex items-center gap-2">
                        <span className="w-12 font-medium">{a.hit_rate?.toFixed(0)}%</span>
                        <div className="w-20">
                          <Progress value={a.hit_rate ?? 0} max={100} tone={(a.hit_rate ?? 0) >= 50 ? 'green' : 'red'} />
                        </div>
                      </div>
                    </td>
                    <td className="py-2 pr-3 font-medium" style={{ color: (a.avg_return ?? 0) >= 0 ? sentimentColor('positive') : sentimentColor('negative') }}>
                      {a.avg_return != null ? `${a.avg_return > 0 ? '+' : ''}${a.avg_return}%` : '—'}
                    </td>
                    <td
                      className="py-2 pr-3 font-medium"
                      style={{ color: a.avg_excess_return == null ? undefined : a.avg_excess_return >= 0 ? sentimentColor('positive') : sentimentColor('negative') }}
                    >
                      {a.avg_excess_return != null ? `${a.avg_excess_return > 0 ? '+' : ''}${a.avg_excess_return}%` : '—'}
                    </td>
                    <td className="py-2 pr-3">{a.avg_confidence?.toFixed(0)}%</td>
                    <td className="py-2 pr-3" style={{ color: a.brier != null && a.brier > 0.25 ? sentimentColor('negative') : undefined }}>
                      {a.brier != null ? a.brier.toFixed(3) : '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {st.global_calibration && st.global_calibration.length > 0 && (
            <div className="mt-3">
              <p className="mb-1 text-[11px] font-medium text-slate-500">
                置信度校准（全部 Agent 合并）：桶内「平均置信度 ≈ 实际胜率」说明校准良好
              </p>
              <div className="flex flex-wrap gap-1.5 text-[11px]">
                {st.global_calibration.map((b) => {
                  const gap = b.avg_confidence != null && b.hit_rate != null ? b.avg_confidence - b.hit_rate : null
                  return (
                    <span
                      key={b.bucket}
                      className="rounded border border-slate-200 px-1.5 py-0.5 text-slate-600"
                      title={`n=${b.n}，命中 ${b.hits} 条`}
                    >
                      置信 {b.bucket}：实际 {b.hit_rate?.toFixed(0)}% / 自信 {b.avg_confidence?.toFixed(0)}%（n={b.n}）
                      {gap != null && (
                        <span className={Math.abs(gap) > 15 ? 'ml-1 font-semibold text-rose-500' : 'ml-1 text-emerald-600'}>
                          偏差 {gap > 0 ? '+' : ''}
                          {gap.toFixed(0)}
                        </span>
                      )}
                    </span>
                  )
                })}
              </div>
            </div>
          )}
          <p className="mt-2 text-[11px] text-slate-400">
            校准提示：若某 Agent 平均置信度 80% 但胜率只有 40%，说明它过度自信——降低其建议权重；Brier 分数 0.25 相当于瞎猜，越接近 0 越好；胜率高、超额为正且置信度与胜率接近的才是可依赖的信息源。
          </p>
        </>
      )}
    </Card>
  )
}

/** 最近一次建议的紧凑摘要（右栏顶部，回答「现在有什么可做的」） */
export function LatestHint({ analyses }: { analyses: Analysis[] }) {
  const a = analyses[0]
  if (!a) return null
  return (
    <div className="flex flex-wrap items-center gap-2 rounded-lg bg-slate-50 px-3 py-2 text-[11px] text-slate-500">
      最新建议
      <span className="text-xs font-semibold text-slate-800">{a.symbol}</span>
      <span className="rounded px-1.5 py-0.5 text-[11px] font-semibold text-white" style={{ background: recBg(a.recommendation) }}>
        {REC_LABEL[a.recommendation]}
      </span>
      <span>置信度 {a.confidence.toFixed(0)}%</span>
      <span className="ml-auto" title={`建议生成时间：${fmtUtc(a.created_at)}`}>
        {fmtUtc(a.created_at)}（{fmtSince(a.created_at)}）
      </span>
    </div>
  )
}
