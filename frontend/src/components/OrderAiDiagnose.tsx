/**
 * OrderAiDiagnose —— 订单 / 错误 AI 诊断入口
 * ==========================================
 * 自包含组件：自己拉最近订单，再用统一的 `AIAssist` 弹窗做诊断。
 *
 * 为什么要单独抽一个组件：`LiveTrading.tsx`（1170 行）与页面级冻结清单里的
 * 文件都已超硬上限，按铁律 9「新功能不得再往里加」。因此把取数与交互全部
 * 封装在这里，页面只留一行编排（`<OrderAiDiagnose />`），零逻辑侵入。
 */
import { useCallback, useEffect, useMemo, useState } from 'react'
import { api } from '../lib/api'
import AIAssist from './AIAssist'

interface OrderLite {
  id: number
  symbol: string
  side: string
  order_type?: string
  quantity: number
  status: string
  reason?: string
  created_at?: string
}

const ABNORMAL = new Set(['REJECTED', 'CANCELLED', 'INACTIVE', 'ERROR', 'FAILED'])

export default function OrderAiDiagnose({
  className,
  autoRefresh = false,
}: {
  className?: string
  /** 页面上订单可能变化（如下单后），置 true 时每次展开都重新拉一遍 */
  autoRefresh?: boolean
}) {
  const [orders, setOrders] = useState<OrderLite[]>([])
  const [loaded, setLoaded] = useState(false)

  const load = useCallback(async () => {
    try {
      const r = await api.get<{ items: OrderLite[] }>('/trading/orders?limit=40')
      setOrders(r.items || [])
    } catch {
      setOrders([])
    } finally {
      setLoaded(true)
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  const abnormal = useMemo(
    () => orders.filter((o) => ABNORMAL.has(String(o.status || '').toUpperCase()) || (o.reason || '').length > 0),
    [orders],
  )

  // 指纹：订单状态变化（例如刚被拒）即视为新数据，重新诊断
  const runKey = useMemo(
    () => orders.slice(0, 12).map((o) => `${o.id}:${o.status}`).join('|'),
    [orders],
  )

  const hint = !loaded
    ? '正在读取订单流水…'
    : orders.length === 0
      ? '暂无订单记录可诊断。'
      : abnormal.length === 0
        ? '当前没有异常订单；仍可让 AI 复核一遍订单流水的合规性。'
        : `检测到 ${abnormal.length} 笔异常订单（被拒 / 带原因），建议让 AI 逐笔解释。`

  return (
    <span className={className} onMouseEnter={autoRefresh ? () => load() : undefined}>
      <AIAssist
        mode="modal"
        task="order_diagnose"
        title="AI 订单与错误诊断"
        desc="逐笔解释被拒原因，归纳共性问题，并给出按优先级的修复步骤"
        label="AI 诊断订单"
        payload={{ orders }}
        runKey={runKey}
        disabled={loaded && orders.length === 0}
        disabledHint={hint}
        emptyHint={hint}
      />
    </span>
  )
}
