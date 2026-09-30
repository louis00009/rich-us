import {
  Activity,
  Ban,
  CircleDot,
  Gauge,
  Lock,
  RefreshCw,
  Send,
  ShieldCheck,
  Unlock,
  Zap,
} from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import EngineTab from '../components/live/EngineTab'
import OrderConfirmModal from '../components/live/OrderConfirmModal'
import PositionsTable from '../components/live/PositionsTable'
import QuoteStrip, { WATCH } from '../components/live/QuoteStrip'
import RightRail from '../components/live/RightRail'
import UnlockModal from '../components/live/UnlockModal'
import type { OpenOrder, RiskLimitsView } from '../components/live/RightRail'
import type { EngineRun } from '../components/live/EngineTab'
import {
  Alert,
  Badge,
  Button,
  Card,
  Field,
  Input,
  Select,
  Stat,
  Tabs,
  useToast,
} from '../components/ui'
import { api, openStream } from '../lib/api'
import { fmtMoney, fmtNum, fmtPct } from '../lib/format'
import type {
  AccountSnapshot,
  BrokerStatus,
  OrderRow,
  PositionItem,
  Quote,
  StrategyConfig,
} from '../lib/types'


/* P3-11：把这几个原本是 `any` 的接口响应补上类型（只列前端实际用到的字段）。
   好处不只是"类型好看" —— 后端改字段名时 tsc 会立刻报错，而不是在运行时
   变成 undefined 静默渲染空白。 */
interface ModeInfo {
  mode: 'paper' | 'live'
  ui_mode?: string
  broker?: string
  port?: number
  live_env_gate?: boolean
  live_unlocked?: boolean
  live_ready?: boolean
  live_reason?: string
  confirm_phrase?: string
}

interface EngineStatusView {
  runs: EngineRun[]
  active?: Record<string, unknown>
}

export default function LiveTrading() {
  const toast = useToast()
  const [acc, setAcc] = useState<AccountSnapshot | null>(null)
  const [positions, setPositions] = useState<PositionItem[]>([])
  const [orders, setOrders] = useState<OrderRow[]>([])
  const [mode, setMode] = useState<ModeInfo | null>(null)
  const [strategyList, setStrategyList] = useState<StrategyConfig[]>([])
  const [engine, setEngine] = useState<EngineStatusView | null>(null)
  const [riskLimits, setRiskLimits] = useState<RiskLimitsView | null>(null)
  const [brokerSt, setBrokerSt] = useState<BrokerStatus | null>(null)
  const [openOrders, setOpenOrders] = useState<OpenOrder[]>([])
  const [quotes, setQuotes] = useState<Record<string, Quote>>({})
  const [sparks, setSparks] = useState<Record<string, number[]>>({})
  const [loading, setLoading] = useState(true)
  const [accError, setAccError] = useState('')
  const [wsStatus, setWsStatus] = useState<'open' | 'closed' | 'error' | 'connecting'>('connecting')
  const tabRef = useRef<'order' | 'engine'>('order')
  const [tab, setTab] = useState('order')

  // 下单表单
  const [symbol, setSymbol] = useState('SPY')
  const [side, setSide] = useState<'BUY' | 'SELL'>('BUY')
  const [qty, setQty] = useState(10)
  const [orderType, setOrderType] = useState<'MKT' | 'LMT' | 'STP' | 'STP_LMT'>('MKT')
  const [limitPrice, setLimitPrice] = useState<number | ''>('')
  const [stopPrice, setStopPrice] = useState<number | ''>('')
  const [tif, setTif] = useState('DAY')
  const [preview, setPreview] = useState<any>(null)
  const [placing, setPlacing] = useState(false)
  const [confirmOpen, setConfirmOpen] = useState(false)

  // 实盘解锁
  const [unlockOpen, setUnlockOpen] = useState(false)
  const [unlockPhrase, setUnlockPhrase] = useState('')
  const [unlockPwd, setUnlockPwd] = useState('')
  const [unlockBusy, setUnlockBusy] = useState(false)

  const load = useCallback(async () => {
    const rs = await Promise.allSettled([
      api.get<AccountSnapshot>('/trading/account'),
      api.get<{ items: PositionItem[] }>('/trading/positions'),
      api.get<{ items: OrderRow[] }>('/trading/orders?limit=40'),
      api.get<any>('/trading/mode'),
      api.get<{ items: StrategyConfig[] }>('/strategies/custom'),
      api.get<any>('/trading/engine'),
      api.get<BrokerStatus>('/trading/broker-status'),
      api.get<{ items: any[] }>('/trading/open-orders'),
      api.get<{ config: any }>('/risk/config'),
    ])
    // P1-13：账户读取失败必须可见 —— 旧实现吞掉异常后界面显示「权益 $0.00 / 现金 $0.00」
    // 且无任何告警，极易误导判断。
    if (rs[0].status === 'fulfilled') {
      setAcc(rs[0].value)
      setAccError('')
    } else {
      setAccError(rs[0].reason?.message || '账户数据读取失败（权益/现金非真实值）')
    }
    if (rs[1].status === 'fulfilled') setPositions(rs[1].value.items)
    if (rs[2].status === 'fulfilled') setOrders(rs[2].value.items)
    if (rs[3].status === 'fulfilled') setMode(rs[3].value)
    if (rs[4].status === 'fulfilled') setStrategyList(rs[4].value.items)
    if (rs[5].status === 'fulfilled') setEngine(rs[5].value)
    if (rs[6].status === 'fulfilled') setBrokerSt(rs[6].value)
    if (rs[7].status === 'fulfilled') setOpenOrders(rs[7].value.items || [])
    if (rs[8].status === 'fulfilled') setRiskLimits(rs[8].value.config)
    setLoading(false)
  }, [])

  useEffect(() => {
    load()
    const t = setInterval(load, 15000)
    return () => clearInterval(t)
  }, [load])

  // WebSocket 实时行情
  useEffect(() => {
    const close = openStream(
      WATCH,
      8,
      (msg) => {
        if (msg.type === 'tick') {
          const map: Record<string, Quote> = {}
          msg.quotes.forEach((q: Quote) => {
            map[q.symbol] = q
          })
          setQuotes((s) => ({ ...s, ...map }))
          setSparks((s) => {
            const next = { ...s }
            msg.quotes.forEach((q: Quote) => {
              // 不可变更新：旧实现 arr.push 直接改旧数组 —— StrictMode 下
              // updater 双调用会导致每 tick 追加两个点（迷你走势越来越密）
              next[q.symbol] = [...(next[q.symbol] || []), q.price].slice(-40)
            })
            return next
          })
        }
      },
      (st) => setWsStatus(st),
    )
    return close
  }, [])

  useEffect(() => {
    tabRef.current = tab as any
  }, [tab])

  const doPreview = async () => {
    try {
      const r = await api.post<any>('/trading/preview', {
        symbol,
        side,
        quantity: qty,
        order_type: orderType,
        limit_price: limitPrice === '' ? null : limitPrice,
        stop_price: stopPrice === '' ? null : stopPrice,
      })
      setPreview(r)
      return r
    } catch (e: any) {
      toast('error', e?.message || '预检失败')
      return null
    }
  }

  const submitOrder = async () => {
    setPlacing(true)
    try {
      const r = await api.post<any>('/trading/order', {
        symbol,
        side,
        quantity: qty,
        order_type: orderType,
        limit_price: limitPrice === '' ? null : limitPrice,
        stop_price: stopPrice === '' ? null : stopPrice,
        tif,
        reason: '手动下单',
        confirm: true,
      })
      if (r.ok) {
        // IBKR 下单是异步的：未成交时不要伪造成交价
        const px =
          r.avg_price > 0
            ? `成交均价 ${fmtNum(r.avg_price, 2)}`
            : r.filled_qty > 0
              ? `已成交 ${fmtNum(r.filled_qty, 2)} 股`
              : `状态 ${r.status}（成交回报将异步回填）`
        toast('success', `${r.message} ｜ ${px}`)
      } else {
        toast('error', r.message || '下单失败')
      }
      setConfirmOpen(false)
      setPreview(null)
      load()
    } catch (e: any) {
      toast('error', e?.message || '下单失败')
    } finally {
      setPlacing(false)
    }
  }

  const switchMode = async (m: 'paper' | 'live') => {
    try {
      const r = await api.post<any>('/trading/mode', { mode: m })
      toast('success', r.message)
      load()
    } catch (e: any) {
      toast('error', e?.message || '切换失败')
    }
  }

  const doUnlock = async (enable: boolean) => {
    setUnlockBusy(true)
    try {
      const r = await api.post<any>('/trading/live-unlock', {
        confirm_phrase: enable ? unlockPhrase : mode?.confirm_phrase,
        password: unlockPwd,
        enable,
      })
      toast(enable ? 'warning' : 'success', r.message)
      setUnlockOpen(false)
      setUnlockPhrase('')
      setUnlockPwd('')
      load()
    } catch (e: any) {
      toast('error', e?.message || '操作失败')
    } finally {
      setUnlockBusy(false)
    }
  }

  const activeRuns = engine?.runs?.filter((r: any) => r.status === 'RUNNING') || []
  const liveOn = mode?.mode === 'live'

  return (
    <div className="space-y-5">
      {/* 模式条 */}
      <Card>
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div className="flex flex-wrap items-center gap-3">
            <div
              className={`flex items-center gap-2 rounded-lg px-3 py-2 ${
                liveOn ? 'bg-rose-50 ring-1 ring-rose-200' : 'bg-brand-50 ring-1 ring-brand-200'
              }`}
            >
              <CircleDot className={`h-4 w-4 ${liveOn ? 'text-rose-600' : 'text-brand-600'}`} />
              <div>
                <div className={`text-sm font-semibold ${liveOn ? 'text-rose-700' : 'text-brand-700'}`}>
                  {liveOn ? '实盘模式' : '模拟盘模式'}
                </div>
                <div className="text-[11px] text-slate-500">{acc?.message || '—'}</div>
              </div>
            </div>

            <div className="flex items-center gap-2">
              <Badge tone={mode?.live_env_gate ? 'green' : 'slate'}>
                {mode?.live_env_gate ? '① 环境开关已开' : '① 环境开关已关'}
              </Badge>
              <Badge tone={mode?.live_unlocked ? 'amber' : 'slate'}>
                {mode?.live_unlocked ? '② 已解锁' : '② 未解锁'}
              </Badge>
              <Badge tone="slate">③ 逐笔护栏</Badge>
            </div>
          </div>

          <div className="flex flex-wrap gap-2">
            <Button
              variant={liveOn ? 'secondary' : 'primary'}
              onClick={() => switchMode('paper')}
              disabled={!liveOn}
              icon={<ShieldCheck className="h-3.5 w-3.5" />}
            >
              切回模拟盘
            </Button>
            {mode?.live_unlocked ? (
              <Button variant="danger" onClick={() => setUnlockOpen(true)} icon={<Lock className="h-3.5 w-3.5" />}>
                锁定实盘
              </Button>
            ) : (
              <Button onClick={() => setUnlockOpen(true)} icon={<Unlock className="h-3.5 w-3.5" />}>
                解锁实盘
              </Button>
            )}
            {mode?.live_ready && !liveOn && (
              <Button variant="danger" onClick={() => switchMode('live')} icon={<Zap className="h-3.5 w-3.5" />}>
                切换到实盘
              </Button>
            )}
            <Button icon={<RefreshCw className="h-3.5 w-3.5" />} onClick={load}>
              刷新
            </Button>
          </div>
        </div>

        {!mode?.live_ready && (
          <Alert tone="info" className="mt-4" title="当前无法进行实盘交易">
            {mode?.live_reason}。
            <Link to="/settings" className="ml-1 font-medium underline">
              前往系统设置
            </Link>
          </Alert>
        )}
        {liveOn && (
          <Alert tone="danger" className="mt-4" title="⚠️ 实盘模式已激活">
            所有下单请求会直接进入真实券商。请确认：端口指向实盘账户、风控参数已复核、熔断开关未被误关。
          </Alert>
        )}
      </Card>

      {/* 账户速览 */}
      {accError && (
        <Alert tone="danger" className="mb-4" title="账户数据读取失败">
          {accError} —— 下方「权益 / 现金」显示的是占位 0，**不是真实账户值**。请检查券商连接后等待自动重试。
        </Alert>
      )}
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-5">
        <Stat label="账户权益" value={fmtMoney(acc?.equity ?? 0, 2)} sub={`现金 ${fmtMoney(acc?.cash ?? 0, 2)}`} />
        <Stat
          label="当日盈亏"
          value={fmtMoney(acc?.day_pnl ?? 0, 2)}
          tone={(acc?.day_pnl ?? 0) > 0 ? 'up' : (acc?.day_pnl ?? 0) < 0 ? 'down' : 'neutral'}
          sub={fmtPct(acc?.day_pnl_pct ?? 0, 2, true)}
        />
        <Stat label="未实现" value={fmtMoney(acc?.unrealized_pnl ?? 0, 2)} tone={(acc?.unrealized_pnl ?? 0) >= 0 ? 'up' : 'down'} />
        <Stat label="已实现" value={fmtMoney(acc?.realized_pnl ?? 0, 2)} />
        <Stat
          label="实时行情通道"
          value={wsStatus === 'open' ? '已连接' : wsStatus === 'connecting' ? '连接中' : '已断开'}
          sub={`${Object.keys(quotes).length} 个标的推送中`}
          icon={<Activity className="h-4 w-4" />}
        />
      </div>

      {/* 实时行情条（拆至 components/live/QuoteStrip.tsx） */}
      <QuoteStrip
        quotes={quotes}
        sparks={sparks}
        wsStatus={wsStatus}
        onPick={(s, price) => {
          setSymbol(s)
          if (price) setLimitPrice(Math.round(price * 100) / 100)
        }}
      />

      <div className="grid gap-5 xl:grid-cols-3">
        {/* 下单 / 引擎 */}
        <div className="space-y-5 xl:col-span-2">
          <Card>
            <Tabs
              value={tab}
              onChange={setTab}
              className="w-fit"
              tabs={[
                { key: 'order', label: '手动下单' },
                { key: 'engine', label: '策略实时引擎', badge: activeRuns.length || undefined },
              ]}
            />

            {tab === 'order' && (
              <div className="mt-4 space-y-4">
                <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                  <Field label="标的">
                    <Input
                      value={symbol}
                      onChange={(e) => setSymbol(e.target.value.toUpperCase())}
                      onBlur={() => {
                        const q = quotes[symbol]
                        if (q && limitPrice === '') setLimitPrice(Math.round(q.price * 100) / 100)
                      }}
                    />
                  </Field>
                  <Field label="方向">
                    <Select value={side} onChange={(e) => setSide(e.target.value as any)}>
                      <option value="BUY">买入 BUY</option>
                      <option value="SELL">卖出 SELL</option>
                    </Select>
                  </Field>
                  <Field label="数量（股）">
                    <Input type="number" min="1" step="1" value={qty} onChange={(e) => setQty(parseFloat(e.target.value || '0'))} />
                  </Field>
                  <Field label="订单类型">
                    <Select value={orderType} onChange={(e) => setOrderType(e.target.value as any)}>
                      <option value="MKT">市价 MKT</option>
                      <option value="LMT">限价 LMT</option>
                      <option value="STP">止损 STP</option>
                      <option value="STP_LMT">止损限价 STP_LMT</option>
                    </Select>
                  </Field>
                </div>

                <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                  {(orderType === 'LMT' || orderType === 'STP_LMT') && (
                    <Field label="限价">
                      <Input
                        type="number"
                        step="0.01"
                        value={limitPrice}
                        onChange={(e) => setLimitPrice(e.target.value === '' ? '' : parseFloat(e.target.value))}
                      />
                    </Field>
                  )}
                  {(orderType === 'STP' || orderType === 'STP_LMT') && (
                    <Field label="触发价">
                      <Input
                        type="number"
                        step="0.01"
                        value={stopPrice}
                        onChange={(e) => setStopPrice(e.target.value === '' ? '' : parseFloat(e.target.value))}
                      />
                    </Field>
                  )}
                  <Field label="有效期">
                    <Select value={tif} onChange={(e) => setTif(e.target.value)}>
                      <option value="DAY">当日有效</option>
                      <option value="GTC">撤销前有效</option>
                    </Select>
                  </Field>
                  <div className="flex items-end gap-2">
                    <Button className="flex-1" onClick={doPreview} icon={<Gauge className="h-3.5 w-3.5" />}>
                      预检
                    </Button>
                    <Button
                      className="flex-1"
                      variant={side === 'BUY' ? 'danger' : 'success'}
                      onClick={async () => {
                        // T-115：下单前强制预检 —— 护栏拒绝则直接终止（拒绝原因已在面板渲染），
                        // 通过则把预检结果带进确认弹窗（缩减后数量 / 佣金 / 占权益）。
                        const p = await doPreview()
                        if (!p || !p.ok) return
                        setConfirmOpen(true)
                      }}
                      icon={<Send className="h-3.5 w-3.5" />}
                    >
                      下单
                    </Button>
                  </div>
                </div>

                {preview && (
                  <div className={`rounded-lg border p-3.5 ${preview.ok ? 'border-emerald-200 bg-emerald-50' : 'border-rose-200 bg-rose-50'}`}>
                    <div className="flex items-center gap-2">
                      {preview.ok ? (
                        <ShieldCheck className="h-4 w-4 text-emerald-600" />
                      ) : (
                        <Ban className="h-4 w-4 text-rose-600" />
                      )}
                      <span className={`text-sm font-medium ${preview.ok ? 'text-emerald-800' : 'text-rose-800'}`}>
                        {preview.ok ? '护栏校验通过' : `护栏拒绝：${preview.reason}`}
                        {preview.code && preview.code !== 'OK' && <span className="ml-1 text-xs">（{preview.code}）</span>}
                      </span>
                    </div>
                    <div className="mt-2 grid grid-cols-2 gap-x-4 gap-y-1 text-xs text-slate-600 sm:grid-cols-4">
                      <span>参考价 <b className="num">{fmtNum(preview.estimated?.reference_price, 2)}</b></span>
                      <span>名义金额 <b className="num">{fmtMoney(preview.estimated?.notional, 0)}</b></span>
                      <span>预估佣金 <b className="num">{fmtMoney(preview.estimated?.commission_estimate, 2)}</b></span>
                      <span>占权益 <b className="num">{preview.estimated?.pct_of_equity}%</b></span>
                    </div>
                    {preview.warnings?.length > 0 && (
                      <ul className="mt-2 space-y-1 text-xs text-amber-700">
                        {preview.warnings.map((w: string, i: number) => (
                          <li key={i}>⚠ {w}</li>
                        ))}
                      </ul>
                    )}
                  </div>
                )}
              </div>
            )}

            {tab === 'engine' && (
              <EngineTab
                strategyList={strategyList}
                mode={mode}
                runs={engine?.runs || []}
                openOrderCount={openOrders.length}
                onReload={load}
              />
            )}
          </Card>

          {/* 持仓（拆至 components/live/PositionsTable.tsx） */}
          <PositionsTable
            positions={positions}
            onClose={(r) => {
              setSymbol(r.symbol)
              setSide(r.quantity > 0 ? 'SELL' : 'BUY')
              setQty(Math.abs(r.quantity))
              setOrderType('MKT')
              setTab('order')
            }}
          />
        </div>

        {/* 右栏：券商状态 + 风控占用 + 订单流（拆至 RightRail.tsx） */}
        <RightRail
          brokerSt={brokerSt}
          openOrders={openOrders}
          loading={loading}
          riskLimits={riskLimits}
          acc={acc}
          positions={positions}
          orders={orders}
          onReload={load}
        />
      </div>

      {/* 下单确认（拆至 components/live/OrderConfirmModal.tsx） */}
      <OrderConfirmModal
        open={confirmOpen}
        onClose={() => setConfirmOpen(false)}
        onSubmit={submitOrder}
        placing={placing}
        liveOn={liveOn}
        side={side}
        symbol={symbol}
        qty={qty}
        orderType={orderType}
        tif={tif}
        quotes={quotes}
        preview={preview}
      />

      {/* 实盘解锁（拆至 components/live/UnlockModal.tsx） */}
      <UnlockModal
        open={unlockOpen}
        onClose={() => setUnlockOpen(false)}
        mode={mode}
        busy={unlockBusy}
        phrase={unlockPhrase}
        setPhrase={setUnlockPhrase}
        pwd={unlockPwd}
        setPwd={setUnlockPwd}
        onUnlock={doUnlock}
      />
    </div>
  )
}
