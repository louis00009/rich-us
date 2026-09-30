// 实盘页右栏（FILE_SIZE_DEBT Batch C-4 拆分）：券商通道 + 券商挂单 + 风控占用 + 订单流水
import { Ban, Server } from 'lucide-react'
import { Link } from 'react-router-dom'
import OrderAiDiagnose from '../OrderAiDiagnose'
import { Alert, Badge, Card, DataTable, Empty, Loading, Progress, useToast } from '../ui'
import { api } from '../../lib/api'
import { fmtAgo, fmtMoney, fmtNum } from '../../lib/format'
import type { AccountSnapshot, BrokerStatus, OrderRow, PositionItem } from '../../lib/types'

/** 券商挂单（/api/trading/open-orders 的 items，字段随券商而异） */
export interface OpenOrder {
  order_id: string
  symbol: string
  action: string
  type: string
  quantity: number
  lmt_price?: number
  aux_price?: number
  status: string
}

export interface RiskLimitsView {
  max_position_pct: number
  max_gross_exposure_pct: number
  max_open_positions: number
}

interface RightRailProps {
  brokerSt: BrokerStatus | null
  openOrders: OpenOrder[]
  loading: boolean
  riskLimits: RiskLimitsView | null
  acc: AccountSnapshot | null
  positions: PositionItem[]
  orders: OrderRow[]
  onReload: () => void
}

export default function RightRail({ brokerSt, openOrders, loading, riskLimits, acc, positions, orders, onReload }: RightRailProps) {
  const toast = useToast()

  return (
    <div className="space-y-5">
      <Card
        title={
          <span className="flex items-center gap-2">
            <Server className="h-4 w-4" />券商通道
          </span>
        }
        subtitle={brokerSt?.connected ? '实时连接正常' : '未连接或非 IBKR'}
        actions={
          <Badge tone={brokerSt?.connected ? 'green' : 'amber'} dot>
            {brokerSt?.connected ? 'ONLINE' : 'OFFLINE'}
          </Badge>
        }
      >
        {brokerSt ? (
          <div className="space-y-2 text-xs">
            {[
              ['券商', brokerSt.broker === 'ibkr' ? 'Interactive Brokers' : '内置模拟券商'],
              ['地址', brokerSt.host ? `${brokerSt.host}:${brokerSt.port}` : '—'],
              ['账户', brokerSt.account_id || '—'],
              ['Client ID', brokerSt.client_id ?? '—'],
              ['只读模式', brokerSt.readonly ? '是（无法下单）' : '否（可下单）'],
              ['行情类型', brokerSt.market_data_label || '—'],
              ['仅常规时段', brokerSt.use_rth ? '是' : '否'],
              ['合约缓存', brokerSt.contracts_cached != null ? `${brokerSt.contracts_cached} 个` : '—'],
              ['历史请求', brokerSt.historical_requests != null ? `${brokerSt.historical_requests} 次` : '—'],
            ].map(([k, v]) => (
              <div key={k as string} className="flex items-center justify-between border-b border-dashed border-slate-100 pb-1.5">
                <span className="text-slate-500">{k}</span>
                <span className="num font-medium text-slate-700">{v}</span>
              </div>
            ))}
            {brokerSt.last_error && (
              <p className="pt-1 text-[11px] text-amber-700">⚠ {brokerSt.last_error.slice(0, 120)}</p>
            )}
            {brokerSt.broker === 'ibkr' && brokerSt.connected && brokerSt.market_data_label?.includes('延迟') && (
              <Alert tone="warn" className="mt-2">
                当前使用<span className="font-medium">延迟行情</span>（通常延迟 15 分钟）。若要做日内交易，
                请在 IBKR 订阅实时行情，并在「系统设置」把行情类型改为「实时」。
              </Alert>
            )}
          </div>
        ) : (
          <Loading />
        )}
      </Card>

      {openOrders.length > 0 && (
        <Card title="券商挂单" subtitle="含保护性止损/止盈单" dense actions={<Badge tone="brand">{openOrders.length}</Badge>}>
          <DataTable<OpenOrder>
            rows={openOrders}
            rowKey={(r) => r.order_id}
            maxHeight="240px"
            columns={[
              { key: 's', label: '标的', render: (r) => <span className="font-medium">{r.symbol}</span> },
              { key: 'a', label: '方向', render: (r) => <Badge tone={r.action === 'BUY' ? 'red' : 'green'}>{r.action === 'BUY' ? '买' : '卖'}</Badge> },
              { key: 't', label: '类型', render: (r) => <span className="text-xs text-slate-500">{r.type}</span> },
              { key: 'q', label: '数量', align: 'right', render: (r) => <span className="num">{fmtNum(r.quantity, 0)}</span> },
              {
                key: 'p',
                label: '价格',
                align: 'right',
                render: (r) => (
                  <span className="num">{fmtNum(r.lmt_price || r.aux_price || 0, 2)}</span>
                ),
              },
              { key: 'st', label: '状态', render: (r) => <Badge tone="amber">{r.status}</Badge> },
              {
                key: 'x',
                label: '',
                align: 'right',
                render: (r) => (
                  <button
                    className="rounded p-1 text-slate-300 hover:bg-rose-50 hover:text-rose-500"
                    onClick={async () => {
                      try {
                        await api.post(`/trading/cancel/${r.order_id}`)
                        toast('success', '撤单已提交')
                        onReload()
                      } catch (e: any) {
                        // P1-13：撤单失败必须可见 —— 旧实现 unhandled rejection 静默
                        toast('error', e?.message || `撤单失败（订单 ${r.order_id} 仍可能在成交，请到券商端确认）`)
                      }
                    }}
                  >
                    <Ban className="h-3.5 w-3.5" />
                  </button>
                ),
              },
            ]}
          />
        </Card>
      )}

      <Card title="风控占用" subtitle="护栏实时余量（取自当前风控配置）">
        {loading ? (
          <Loading />
        ) : (
          <div className="space-y-4">
            {(() => {
              const grossCap = Number(riskLimits?.max_gross_exposure_pct ?? 100)
              const posCap = Number(riskLimits?.max_position_pct ?? 20)
              const posLimit = Number(riskLimits?.max_open_positions ?? 10)
              const grossPct = acc?.equity
                ? (positions.reduce((s, p) => s + Math.abs(p.market_value), 0) / acc.equity) * 100
                : 0
              // P3-11：原先用 `acc!.equity` 非空断言 —— 箭头函数内部 TS 无法从
              // 外层的可选链收窄，断言一旦失效就是运行时崩溃。改用局部常量。
              const equity = acc?.equity ?? 0
              const maxPosPct = equity
                ? Math.max(...positions.map((p) => (Math.abs(p.market_value) / equity) * 100), 0)
                : 0
              return (
                <>
                  <Progress
                    value={grossPct}
                    max={grossCap}
                    tone={grossPct / grossCap > 0.9 ? 'red' : grossPct / grossCap > 0.7 ? 'amber' : 'brand'}
                    label={
                      <>
                        <span>总敞口</span>
                        <span className="num">
                          {grossPct.toFixed(1)}% / {grossCap.toFixed(0)}%
                        </span>
                      </>
                    }
                  />
                  <Progress
                    value={positions.length}
                    max={posLimit}
                    tone={positions.length >= posLimit ? 'red' : 'brand'}
                    label={
                      <>
                        <span>持仓数量</span>
                        <span className="num">
                          {positions.length} / {posLimit}
                        </span>
                      </>
                    }
                  />
                  <Progress
                    value={maxPosPct}
                    max={posCap}
                    tone={maxPosPct / posCap > 0.9 ? 'red' : 'brand'}
                    label={
                      <>
                        <span>单标的最大占比</span>
                        <span className="num">
                          {maxPosPct.toFixed(1)}% / {posCap.toFixed(0)}%
                        </span>
                      </>
                    }
                  />
                </>
              )
            })()}
            <div className="flex items-center justify-between border-t border-slate-100 pt-3 text-xs text-slate-500">
              <span>买入力</span>
              <span className="num font-medium text-slate-700">{fmtMoney(acc?.buying_power ?? 0, 2)}</span>
            </div>
            <Link to="/risk" className="block text-center text-xs text-brand-600 hover:underline">
              调整风控参数 →
            </Link>
          </div>
        )}
      </Card>

      <Card
        title="订单流水"
        dense
        actions={
          <>
            <OrderAiDiagnose />
            <Badge tone="slate">{orders.length}</Badge>
          </>
        }
      >
        <DataTable<OrderRow>
          rows={orders}
          rowKey={(r) => r.id}
          maxHeight="460px"
          empty={<Empty title="暂无订单" />}
          columns={[
            { key: 's', label: '标的', render: (r) => <span className="font-medium">{r.symbol}</span> },
            {
              key: 'sd',
              label: '方向',
              render: (r) => <Badge tone={r.side === 'BUY' ? 'red' : 'green'}>{r.side === 'BUY' ? '买' : '卖'}</Badge>,
            },
            { key: 'q', label: '数量', align: 'right', render: (r) => <span className="num">{fmtNum(r.quantity, 0)}</span> },
            { key: 'p', label: '均价', align: 'right', render: (r) => <span className="num">{fmtNum(r.avg_fill_price, 2)}</span> },
            {
              key: 'st',
              label: '状态',
              render: (r) => (
                <Badge tone={r.status === 'FILLED' ? 'green' : r.status === 'REJECTED' ? 'red' : 'amber'}>{r.status}</Badge>
              ),
            },
            { key: 't', label: '时间', render: (r) => <span className="text-[11px] text-slate-400">{fmtAgo(r.created_at)}</span> },
          ]}
        />
      </Card>
    </div>
  )
}
