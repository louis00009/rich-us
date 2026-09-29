/**
 * PeriodReviewAi —— 交易复盘（周期复盘）
 * ======================================
 * 「组合点评」看的是**当下快照**（我现在持有什么、风险如何）；
 * 「交易复盘」看的是**一段时间的过程**（我做了什么、决策链条哪里断了）。
 * 两者互补，因此并列挂载。
 *
 * 订单 / 持仓 / 账户由页面传入（已加载，避免重复请求）；
 * 决策日志 Portfolio 页没有，由本组件自己取。
 */
import { useCallback, useEffect, useState } from 'react'
import { api } from '../lib/api'
import AIAssist from './AIAssist'

export default function PeriodReviewAi({
  orders,
  positions,
  account,
  period = '账户内全部订单（最近 200 笔）',
  className,
}: {
  orders: any[]
  positions: any[]
  account: any
  period?: string
  className?: string
}) {
  const [decisions, setDecisions] = useState<any[]>([])

  const load = useCallback(async () => {
    try {
      const r = await api.get<{ items: any[] }>('/ops/decisions?limit=100')
      setDecisions(r.items || [])
    } catch {
      setDecisions([])
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  // 订单数 / 持仓数 / 已实现盈亏变化即视为新数据
  const runKey = `${orders.length}:${positions.length}:${account?.realized_pnl ?? 0}`

  return (
    <AIAssist
      className={className}
      mode="panel"
      task="period_review"
      title="AI 交易复盘"
      desc="复盘这段交易的过程：盈亏归因、被拒原因是否反复出现、是否存在过度交易或缺止损"
      label="复盘我的交易"
      payload={{ period, orders, positions, account, decisions }}
      runKey={runKey}
      disabled={orders.length === 0 && positions.length === 0}
      disabledHint="还没有订单或持仓可供复盘。"
      emptyHint="AI 会分析交易频率、方向偏好、标的集中度、被风控反复拦下的原因，并给出可执行的改进项。"
    />
  )
}
