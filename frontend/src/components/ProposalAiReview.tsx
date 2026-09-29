/**
 * ProposalAiReview —— AI 提案复核（批准前反方质询）
 * ==================================================
 * 这是全平台**唯一真正动钱**的环节：人点「批准执行」→ 立即走完整下单链。
 * 因此这里让 AI 固定扮演**反方**，在批准前把「与持仓/风控的冲突、提案自身的
 * 弱点、最坏情况」摆到台面上。
 *
 * 为什么自包含：`AIOps.tsx` 只提供提案本身，而复核还需要当前持仓、账户权益与
 * 风控上限（`/ops/overview` 的 positions 不含 weight）。这些取数全部封装在这里，
 * 页面只留一行 `<ProposalAiReview proposal={p} mode={...} />`，零逻辑侵入。
 */
import { useCallback, useEffect, useState } from 'react'
import { api } from '../lib/api'
import AIAssist from './AIAssist'

interface ProposalLite {
  id: number
  symbol: string
  action: string
  size_pct: number
  entry?: number
  stop?: number | null
  take_profit?: number | null
  rationale?: string
  factors?: any
  created_by?: string
  status?: string
}

interface Ctx {
  limits?: Record<string, any>
  positions: any[]
  account?: Record<string, any>
}

export default function ProposalAiReview({
  proposal,
  mode,
  className,
}: {
  proposal: ProposalLite
  /** paper / live —— 让 AI 知道批准后的后果严重程度 */
  mode?: string
  className?: string
}) {
  const [ctx, setCtx] = useState<Ctx>({ positions: [] })
  const [loaded, setLoaded] = useState(false)

  const load = useCallback(async () => {
    const [lim, pos, acc] = await Promise.allSettled([
      api.get<{ config: Record<string, any> }>('/risk/config'),
      api.get<{ items: any[] }>('/trading/positions'),
      api.get<Record<string, any>>('/trading/account'),
    ])
    setCtx({
      limits: lim.status === 'fulfilled' ? lim.value.config : undefined,
      positions: pos.status === 'fulfilled' ? pos.value.items || [] : [],
      account: acc.status === 'fulfilled' ? acc.value : undefined,
    })
    setLoaded(true)
  }, [])

  useEffect(() => {
    load()
  }, [load])

  // 提案状态一变（例如已被批准），视为新上下文重新复核
  const runKey = `${proposal.id}:${proposal.status ?? ''}`

  return (
    <span className={className} onMouseEnter={() => load()}>
      <AIAssist
        mode="modal"
        task="proposal_review"
        title="AI 提案复核（反方质询）"
        desc="让 AI 站在反方立场，尽力找出这笔提案与持仓/风控的冲突、自身的弱点与最坏情况"
        label="AI 复核"
        payload={{
          // 顶层 symbol 供后端 decision_logs 归属（它只读 payload.symbol）
          symbol: proposal.symbol,
          proposal,
          limits: ctx.limits,
          positions: ctx.positions,
          account: ctx.account,
          mode,
        }}
        runKey={runKey}
        disabled={!loaded}
        disabledHint="正在读取持仓与风控上限…"
        emptyHint="点击「AI 复核」，让 AI 在批准前做一次反方质询。"
      />
    </span>
  )
}
