import { Layers, PieChart, RefreshCw, Wallet } from 'lucide-react'
import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { HBar } from '../components/charts'
import {
  Badge,
  Button,
  Card,
  DataTable,
  Empty,
  Input,
  Loading,
  Progress,
  Select,
  Stat,
  Tabs,
  useToast,
} from '../components/ui'
import { api } from '../lib/api'
import { fmtAgo, fmtDateTime, fmtMoney, fmtNum, signClass } from '../lib/format'
import type { AccountSnapshot, OrderRow, PositionItem } from '../lib/types'

export default function Portfolio() {
  const toast = useToast()
  const [acc, setAcc] = useState<AccountSnapshot | null>(null)
  const [accErr, setAccErr] = useState('')   // P1-13：账户读取失败必须可见
  const [limits, setLimits] = useState<{ max_position_pct: number } | null>(null)
  const [positions, setPositions] = useState<PositionItem[]>([])
  const [orders, setOrders] = useState<OrderRow[]>([])
  const [expo, setExpo] = useState<any>(null)
  const [loading, setLoading] = useState(true)
  const [tab, setTab] = useState('positions')
  const [filter, setFilter] = useState('')
  const [sideFilter, setSideFilter] = useState('')

  const load = useCallback(async () => {
    setLoading(true)
    const rs = await Promise.allSettled([
      api.get<AccountSnapshot>('/trading/account'),
      api.get<{ items: PositionItem[] }>('/trading/positions'),
      api.get<{ items: OrderRow[] }>('/trading/orders?limit=200'),
      api.get<any>('/risk/exposure'),
      api.get<{ config: { max_position_pct: number } }>('/risk/config'),
    ])
    if (rs[0].status === 'fulfilled') { setAcc(rs[0].value); setAccErr('') }
    else setAccErr(rs[0].reason?.message || '账户数据读取失败（权益/现金为占位值）')
    if (rs[1].status === 'fulfilled') setPositions(rs[1].value.items)
    if (rs[2].status === 'fulfilled') setOrders(rs[2].value.items)
    if (rs[3].status === 'fulfilled') setExpo(rs[3].value)
    if (rs[4].status === 'fulfilled') setLimits(rs[4].value.config)
    setLoading(false)
  }, [])

  useEffect(() => {
    load()
  }, [load])

  const totalUnreal = positions.reduce((s, p) => s + p.unrealized_pnl, 0)
  const totalReal = acc?.realized_pnl ?? 0
  const gross = positions.reduce((s, p) => s + Math.abs(p.market_value), 0)

  const alloc = useMemo(
    () =>
      positions
        .filter((p) => Math.abs(p.market_value) > 0)
        .sort((a, b) => Math.abs(b.market_value) - Math.abs(a.market_value))
        .map((p) => ({ name: p.symbol, value: Math.abs(p.market_value) })),
    [positions],
  )

  const filteredOrders = useMemo(
    () =>
      orders.filter(
        (o) =>
          (!filter || o.symbol.includes(filter.toUpperCase()) || o.reason.includes(filter)) &&
          (!sideFilter || o.side === sideFilter),
      ),
    [orders, filter, sideFilter],
  )

  const buyCount = orders.filter((o) => o.side === 'BUY').length
  const sellCount = orders.filter((o) => o.side === 'SELL').length
  const totalCommission = orders.reduce((s, o) => s + (o.commission || 0), 0)

  if (loading && !acc) return <Loading label="加载持仓与订单…" />

  return (
    <div className="space-y-5">
      {accErr && (
        <div className="rounded-lg border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
          ⚠️ {accErr}
        </div>
      )}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <Badge tone={acc?.connected ? 'green' : 'amber'} dot>
            {acc?.connected ? `已连接 ${acc.broker}` : '未连接'}
          </Badge>
          <Badge tone={acc?.mode === 'live' ? 'red' : 'brand'}>{acc?.mode === 'live' ? '实盘' : '模拟盘'}</Badge>
          <span className="text-xs text-slate-400">{acc?.account_id}</span>
        </div>
        <div className="flex gap-2">
          <Button icon={<RefreshCw className="h-3.5 w-3.5" />} onClick={load}>
            刷新
          </Button>
          <Link to="/trading">
            <Button variant="primary">去交易</Button>
          </Link>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <Stat label="账户权益" value={fmtMoney(acc?.equity ?? 0, 2)} sub={`现金 ${fmtMoney(acc?.cash ?? 0, 2)}`} />
        <Stat
          label="持仓浮动盈亏"
          value={fmtMoney(totalUnreal, 2)}
          tone={totalUnreal > 0 ? 'up' : totalUnreal < 0 ? 'down' : 'neutral'}
          sub={`${positions.length} 个持仓`}
        />
        <Stat label="已实现盈亏" value={fmtMoney(totalReal, 2)} tone={totalReal > 0 ? 'up' : totalReal < 0 ? 'down' : 'neutral'} />
        <Stat label="累计佣金" value={fmtMoney(totalCommission, 2)} sub={`共 ${orders.length} 笔订单`} />
      </div>

      <div className="grid gap-5 xl:grid-cols-3">
        <Card
          className="xl:col-span-2"
          title={
            <span className="flex items-center gap-2">
              <Wallet className="h-4 w-4" />持仓明细
            </span>
          }
          actions={<Badge tone="slate">{positions.length} 个</Badge>}
          dense
        >
          <Tabs
            className="mx-4 mt-3 w-fit"
            value={tab}
            onChange={setTab}
            tabs={[
              { key: 'positions', label: '持仓' },
              { key: 'orders', label: '订单流水', badge: orders.length },
            ]}
          />

          {tab === 'positions' ? (
            <DataTable<PositionItem>
              rows={positions}
              rowKey={(r) => r.symbol}
              maxHeight="560px"
              empty={
                <Empty
                  icon={<Layers className="h-8 w-8" />}
                  title="当前没有持仓"
                  desc="下单或被实时引擎建仓后会显示在这里"
                  action={
                    <Link to="/trading">
                      <Button size="sm" variant="primary">
                        去下单
                      </Button>
                    </Link>
                  }
                />
              }
              columns={[
                { key: 's', label: '标的', render: (r) => <span className="font-medium text-slate-800">{r.symbol}</span> },
                { key: 'q', label: '数量', align: 'right', render: (r) => <span className="num">{fmtNum(r.quantity, 2)}</span> },
                { key: 'c', label: '成本', align: 'right', render: (r) => <span className="num">{fmtNum(r.avg_cost, 2)}</span> },
                { key: 'l', label: '现价', align: 'right', render: (r) => <span className="num">{fmtNum(r.last_price, 2)}</span> },
                { key: 'm', label: '市值', align: 'right', render: (r) => (
                  <span className="num">
                    {/* T-112：非 USD 持仓标注原币市值 + 折算值（market_value_base 由后端 fx 折算） */}
                    {r.currency && r.currency !== 'USD' ? (
                      <span title={`折算 USD ≈ ${fmtMoney(r.market_value_base ?? r.market_value, 0)}`}>
                        {fmtMoney(r.market_value, 0)} <span className="text-[11px] text-slate-400">{r.currency}</span>
                      </span>
                    ) : (
                      fmtMoney(r.market_value, 0)
                    )}
                  </span>
                ) },
                {
                  key: 'p',
                  label: '浮动盈亏',
                  align: 'right',
                  render: (r) => (
                    <span className={`num ${signClass(r.unrealized_pnl)}`}>
                      {fmtMoney(r.unrealized_pnl, 0)}
                      <span className="ml-1 text-[11px]">({r.unrealized_pct == null ? '—' : `${r.unrealized_pct.toFixed(2)}%`})</span>
                    </span>
                  ),
                },
                {
                  key: 'w',
                  label: '占比',
                  width: '140px',
                  render: (r) => (
                    <div className="flex items-center gap-2">
                      <div className="w-16">
                        {/* P2：max 由风控配置驱动（旧实现硬编码 20，改了单标的上限就失真） */}
                        <Progress
                          value={Number(r.weight) || 0}
                          max={Math.max(5, Number(limits?.max_position_pct) || 20)}
                          tone={(Number(r.weight) || 0) > (Number(limits?.max_position_pct) || 20) * 0.9 ? 'red' : 'brand'}
                          height="h-1"
                        />
                      </div>
                      <span className="num text-xs text-slate-500">{r.weight == null ? '—' : `${Number(r.weight).toFixed(1)}%`}</span>
                    </div>
                  ),
                },
              ]}
            />
          ) : (
            <>
              <div className="flex flex-wrap items-center gap-3 px-4 py-3">
                <Input
                  className="max-w-[200px]"
                  placeholder="筛选标的或原因"
                  value={filter}
                  onChange={(e) => setFilter(e.target.value)}
                />
                <Select className="max-w-[150px]" value={sideFilter} onChange={(e) => setSideFilter(e.target.value)}>
                  <option value="">全部方向</option>
                  <option value="BUY">仅买入</option>
                  <option value="SELL">仅卖出</option>
                </Select>
                <span className="text-xs text-slate-400">
                  买入 {buyCount} · 卖出 {sellCount}
                </span>
              </div>
              <DataTable<OrderRow>
                rows={filteredOrders}
                rowKey={(r) => r.id}
                maxHeight="480px"
                empty={<Empty title="暂无订单" />}
                columns={[
                  { key: 'id', label: '#', render: (r) => <span className="num text-xs text-slate-400">{r.id}</span> },
                  { key: 's', label: '标的', render: (r) => <span className="font-medium">{r.symbol}</span> },
                  {
                    key: 'sd',
                    label: '方向',
                    render: (r) => <Badge tone={r.side === 'BUY' ? 'red' : 'green'}>{r.side === 'BUY' ? '买入' : '卖出'}</Badge>,
                  },
                  { key: 'ty', label: '类型', render: (r) => <span className="text-xs text-slate-500">{r.order_type}</span> },
                  { key: 'q', label: '数量', align: 'right', render: (r) => <span className="num">{fmtNum(r.quantity, 2)}</span> },
                  { key: 'p', label: '成交价', align: 'right', render: (r) => <span className="num">{fmtNum(r.avg_fill_price, 2)}</span> },
                  { key: 'n', label: '金额', align: 'right', render: (r) => <span className="num">{fmtMoney(r.quantity * r.avg_fill_price, 0)}</span> },
                  { key: 'c', label: '佣金', align: 'right', render: (r) => <span className="num text-slate-500">{fmtNum(r.commission, 2)}</span> },
                  {
                    key: 'st',
                    label: '状态',
                    render: (r) => (
                      <Badge tone={r.status === 'FILLED' ? 'green' : r.status === 'REJECTED' ? 'red' : 'amber'}>{r.status}</Badge>
                    ),
                  },
                  { key: 'md', label: '模式', render: (r) => <Badge tone={r.mode === 'live' ? 'red' : 'slate'}>{r.mode}</Badge> },
                  { key: 'r', label: '备注', render: (r) => <span className="text-xs text-slate-500">{r.reason}</span> },
                  { key: 't', label: '时间', render: (r) => <span className="text-[11px] text-slate-400" title={fmtDateTime(r.created_at)}>{fmtAgo(r.created_at)}</span> },
                ]}
              />
            </>
          )}
        </Card>

        <div className="space-y-5">
          <Card
            title={
              <span className="flex items-center gap-2">
                <PieChart className="h-4 w-4" />持仓分布
              </span>
            }
            subtitle={`总敞口 ${fmtMoney(gross, 0)}`}
          >
            {alloc.length ? (
              <HBar
                data={alloc.map((a) => ({ name: a.name, value: Math.round(a.value) }))}
                height={Math.max(140, alloc.length * 34)}
                color="#6366f1"
                valueFormatter={(v) => fmtMoney(v, 0)}
              />
            ) : (
              <Empty title="无持仓分布" />
            )}
          </Card>

          <Card title="敞口结构">
            {expo ? (
              <div className="space-y-3">
                {[
                  ['多头市值', fmtMoney(expo.long_value, 2), 'text-rose-600'],
                  ['空头市值', fmtMoney(expo.short_value, 2), 'text-emerald-600'],
                  ['净敞口', `${fmtMoney(expo.net_exposure, 2)}（${expo.net_pct}%）`, ''],
                  ['总敞口', `${fmtMoney(expo.gross_exposure, 2)}（${expo.gross_pct}%）`, ''],
                  ['现金', fmtMoney(expo.cash, 2), ''],
                ].map(([k, v, c]) => (
                  <div key={k as string} className="flex items-center justify-between border-b border-dashed border-slate-100 pb-2">
                    <span className="text-xs text-slate-500">{k}</span>
                    <span className={`num text-sm font-medium ${c || 'text-slate-700'}`}>{v}</span>
                  </div>
                ))}

                <div className="space-y-3 pt-2">
                  <Progress
                    value={expo.usage?.gross_pct_used ?? 0}
                    max={expo.usage?.gross_pct_limit ?? 100}
                    tone={(expo.usage?.gross_pct_used ?? 0) > 90 ? 'red' : 'brand'}
                    label={
                      <>
                        <span>总敞口占用</span>
                        <span className="num">
                          {expo.usage?.gross_pct_used}% / {expo.usage?.gross_pct_limit}%
                        </span>
                      </>
                    }
                  />
                  <Progress
                    value={expo.usage?.open_positions ?? 0}
                    max={expo.usage?.positions_limit ?? 10}
                    tone={(expo.usage?.open_positions ?? 0) >= (expo.usage?.positions_limit ?? 10) ? 'red' : 'brand'}
                    label={
                      <>
                        <span>持仓数量</span>
                        <span className="num">
                          {expo.usage?.open_positions} / {expo.usage?.positions_limit}
                        </span>
                      </>
                    }
                  />
                </div>

                {expo.gross_pct > 100 && (
                  <div className="rounded-lg border border-amber-200 bg-amber-50 p-2.5 text-xs text-amber-800">
                    当前总敞口已超过权益 100%，说明使用了融资。请注意维持保证金与强平风险。
                  </div>
                )}
              </div>
            ) : (
              <Loading />
            )}
          </Card>

          <Card title="交易统计" subtitle="基于账户内全部订单">
            <div className="space-y-2">
              {[
                ['订单总数', String(orders.length)],
                ['买入订单', String(buyCount)],
                ['卖出订单', String(sellCount)],
                ['累计佣金', fmtMoney(totalCommission, 2)],
                ['平均单笔佣金', fmtMoney(orders.length ? totalCommission / orders.length : 0, 2)],
                ['盈利持仓', String(positions.filter((p) => p.unrealized_pnl > 0).length)],
                ['亏损持仓', String(positions.filter((p) => p.unrealized_pnl < 0).length)],
              ].map(([k, v]) => (
                <div key={k} className="flex items-center justify-between border-b border-dashed border-slate-100 pb-1.5">
                  <span className="text-xs text-slate-500">{k}</span>
                  <span className="num text-sm font-medium text-slate-700">{v}</span>
                </div>
              ))}
            </div>
          </Card>
        </div>
      </div>
    </div>
  )
}
