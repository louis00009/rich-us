import {
  Activity,
  AlertTriangle,
  Ban,
  CircleDot,
  Gauge,
  Layers,
  Lock,
  Play,
  Power,
  Radar,
  RefreshCw,
  Send,
  Server,
  ShieldCheck,
  Square,
  Unlock,
  Zap,
} from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { MiniSpark } from '../components/charts'
import {
  Alert,
  Badge,
  Button,
  Card,
  DataTable,
  Empty,
  Field,
  Input,
  Loading,
  Modal,
  Progress,
  Select,
  Stat,
  Switch,
  Tabs,
  useToast,
} from '../components/ui'
import { api, openStream } from '../lib/api'
import { fmtMoney, fmtNum, fmtPct, fmtAgo, signClass } from '../lib/format'
import type {
  AccountSnapshot,
  BrokerStatus,
  OrderRow,
  PositionItem,
  Quote,
  StrategyConfig,
} from '../lib/types'

const WATCH = ['SPY', 'QQQ', 'NVDA', 'AAPL', 'TSLA', 'MSFT', 'AMD', 'META']

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

interface RiskLimitsView {
  max_position_pct: number
  max_gross_exposure_pct: number
  max_open_positions: number
}

interface EngineStatusView {
  runs: OrderRow[]
  active?: Record<string, unknown>
}

/** 券商挂单（/api/trading/open-orders 的 items，字段随券商而异） */
interface OpenOrder {
  order_id: string
  symbol: string
  action: string
  type: string
  quantity: number
  lmt_price?: number
  aux_price?: number
  status: string
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

  // 引擎
  const [engineStrategy, setEngineStrategy] = useState<number | ''>('')
  const [engineInterval, setEngineInterval] = useState(60)
  const [engineMode, setEngineMode] = useState<'paper' | 'live'>('paper')
  const [placeProtective, setPlaceProtective] = useState(true)
  const [dryRun, setDryRun] = useState<any>(null)
  const [engineBusy, setEngineBusy] = useState(false)

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

  const startEngine = async () => {
    if (!engineStrategy) {
      toast('warning', '请先选择要运行的策略')
      return
    }
    if (engineMode === 'live' && !liveOn) {
      toast('warning', '请先把交易模式切换到实盘，或改用模拟盘运行引擎')
      return
    }
    if (
      engineMode === 'live' &&
      !confirm(
        '⚠️ 即将以【实盘】模式启动策略引擎。\n\n' +
          '引擎会自动下单，真实资金将发生变动。\n' +
          '请确认：\n' +
          '1) 风控限额已复核\n' +
          '2) 熔断开关未启用\n' +
          '3) 策略已在模拟盘充分验证\n\n' +
          '确定继续？',
      )
    )
      return
    setEngineBusy(true)
    try {
      const r = await api.post<any>('/trading/engine/start', {
        strategy_id: engineStrategy,
        mode: engineMode,
        interval_sec: engineInterval,
        place_protective: placeProtective,
      })
      toast(engineMode === 'live' ? 'warning' : 'success', r.message)
      load()
    } catch (e: any) {
      toast('error', e?.message || '启动失败')
    } finally {
      setEngineBusy(false)
    }
  }

  const stopAllEngines = async () => {
    if (!confirm('确认一键停止全部运行中的策略引擎？已有持仓不会被自动平仓。')) return
    try {
      const r = await api.post<any>('/trading/engine/stop-all')
      toast('success', r.message)
      load()
    } catch (e: any) {
      toast('error', e?.message || '操作失败')
    }
  }

  const cancelAllOrders = async () => {
    if (!confirm('确认撤销当前券商连接下的全部挂单？')) return
    try {
      const r = await api.post<any>('/trading/cancel-all')
      toast('success', r.message)
      load()
    } catch (e: any) {
      toast('error', e?.message || '撤单失败')
    }
  }

  const stopEngine = async (sid: number) => {
    try {
      await api.post(`/trading/engine/stop/${sid}`)
      toast('success', '引擎已停止')
      load()
    } catch (e: any) {
      toast('error', e?.message || '停止失败')
    }
  }

  const runDry = async () => {
    if (!engineStrategy) {
      toast('warning', '请先选择策略')
      return
    }
    setEngineBusy(true)
    try {
      const r = await api.post<any>(`/trading/engine/dry-run/${engineStrategy}`)
      setDryRun(r)
      toast('info', `演练完成：计划 ${r.planned_orders.length} 笔，拦截 ${r.blocked.length} 笔`)
    } catch (e: any) {
      toast('error', e?.message || '演练失败')
    } finally {
      setEngineBusy(false)
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

      {/* 实时行情条 */}
      <Card title="实时行情" subtitle="通过 WebSocket 推送，8 秒刷新一次" actions={<Badge tone={wsStatus === 'open' ? 'green' : 'amber'} dot>{wsStatus === 'open' ? 'LIVE' : 'OFFLINE'}</Badge>}>
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4 lg:grid-cols-8">
          {WATCH.map((s) => {
            const q = quotes[s]
            const spark = sparks[s] || []
            const up = (q?.change ?? 0) >= 0
            return (
              <button
                key={s}
                onClick={() => {
                  setSymbol(s)
                  if (q) setLimitPrice(Math.round(q.price * 100) / 100)
                }}
                className="rounded-lg border border-slate-200 p-2.5 text-left transition-colors hover:border-brand-300 hover:bg-brand-50/40"
              >
                <div className="flex items-center justify-between">
                  <span className="text-xs font-semibold text-slate-700">{s}</span>
                  <span className={`num text-[10px] font-medium ${signClass(q?.change_pct)}`}>
                    {q ? `${q.change_pct > 0 ? '+' : ''}${q.change_pct.toFixed(2)}%` : '—'}
                  </span>
                </div>
                <div className="num mt-0.5 text-sm font-semibold text-slate-900">{q ? fmtNum(q.price, 2) : '—'}</div>
                <div className="mt-1">
                  {spark.length > 2 ? <MiniSpark data={spark} positive={up} height={22} width={80} /> : <div className="h-[22px]" />}
                </div>
              </button>
            )
          })}
        </div>
      </Card>

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
              <div className="mt-4 space-y-4">
                <Alert tone={mode?.live_ready ? 'danger' : 'info'} title={mode?.live_ready ? '实盘通道已就绪，可启动实盘引擎' : '实时引擎 · 当前可用：模拟盘'}>
                  引擎按设定间隔执行：拉取行情 → 跑策略 → 与当前持仓差分 → 通过风控护栏 → 下单。
                  每笔调仓都会写入审计日志。
                  {!mode?.live_ready && (
                    <>
                      <br />
                      实盘模式尚未解锁（{mode?.live_reason}）。完成三重锁的前两道后即可在此启动实盘引擎。
                    </>
                  )}
                </Alert>

                <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                  <Field label="选择策略" hint="来自「我的策略」">
                    <Select value={engineStrategy} onChange={(e) => setEngineStrategy(e.target.value ? parseInt(e.target.value, 10) : '')}>
                      <option value="">— 请选择 —</option>
                      {strategyList.map((s) => (
                        <option key={s.id} value={s.id}>
                          {s.name}（{s.kind}）
                        </option>
                      ))}
                    </Select>
                  </Field>
                  <Field label="运行模式">
                    <Select value={engineMode} onChange={(e) => setEngineMode(e.target.value as 'paper' | 'live')}>
                      <option value="paper">模拟盘（零风险）</option>
                      <option value="live" disabled={!mode?.live_ready}>
                        {mode?.live_ready ? '实盘 ⚠️（真实资金）' : '实盘（未解锁）'}
                      </option>
                    </Select>
                  </Field>
                  <Field label="运行间隔（秒）" hint="最小 10 秒">
                    <Input type="number" min="10" max="3600" value={engineInterval} onChange={(e) => setEngineInterval(parseInt(e.target.value || '60', 10))} />
                  </Field>
                  <div className="flex items-end gap-2">
                    <Button className="flex-1" onClick={runDry} loading={engineBusy} icon={<Gauge className="h-3.5 w-3.5" />}>
                      演练（不下单）
                    </Button>
                    <Button
                      className="flex-1"
                      variant={engineMode === 'live' ? 'danger' : 'primary'}
                      onClick={startEngine}
                      loading={engineBusy}
                      icon={<Zap className="h-3.5 w-3.5" />}
                    >
                      {engineMode === 'live' ? '启动实盘引擎' : '启动引擎'}
                    </Button>
                  </div>
                </div>

                <Switch
                  checked={placeProtective}
                  onChange={setPlaceProtective}
                  label="实盘持仓自动挂交易所侧保护单（强烈建议开启）"
                  hint="建仓后立即在 IBKR 侧挂 GTC 止损单（必要时含止盈单），平仓时自动撤销。这样即使引擎进程掉线，持仓依然有保护。"
                />

                <div className="flex flex-wrap gap-2">
                  <Button variant="secondary" onClick={stopAllEngines} icon={<Square className="h-3.5 w-3.5" />}>
                    一键停止全部引擎（{activeRuns.length}）
                  </Button>
                  <Button variant="secondary" onClick={cancelAllOrders} icon={<Ban className="h-3.5 w-3.5" />}>
                    撤销全部挂单（{openOrders.length}）
                  </Button>
                  <Button variant="secondary" onClick={load} icon={<RefreshCw className="h-3.5 w-3.5" />}>
                    刷新
                  </Button>
                </div>

                {strategyList.length === 0 && (
                  <Alert tone="warn">
                    尚未创建自定义策略。请先前往
                    <Link to="/strategies" className="mx-1 font-medium underline">
                      策略实验室
                    </Link>
                    创建规则或代码策略。
                  </Alert>
                )}

                {dryRun && (
                  <div className="rounded-lg border border-slate-200 p-3.5">
                    <div className="flex items-center gap-2 text-sm font-medium text-slate-700">
                      <Gauge className="h-4 w-4" />演练结果（未真实下单）
                    </div>
                    <div className="mt-2 space-y-2 text-xs">
                      <div className="text-slate-500">
                        账户权益 {fmtMoney(dryRun.account_equity, 2)} · 目标权重：
                        <span className="num ml-1">{JSON.stringify(dryRun.target_weights)}</span>
                      </div>
                      {dryRun.planned_orders?.length ? (
                        dryRun.planned_orders.map((o: any, i: number) => (
                          <div key={i} className="flex items-center gap-2">
                            <Badge tone={o.side === 'BUY' ? 'red' : 'green'}>{o.side}</Badge>
                            <span className="font-medium">{o.symbol}</span>
                            <span className="num">{fmtNum(o.quantity, 2)} 股</span>
                            <span className="text-slate-400">目标名义 {fmtMoney(o.target_notional, 0)}</span>
                          </div>
                        ))
                      ) : (
                        <p className="text-slate-400">本次无调仓需求（目标权重与当前持仓差异小于 0.5% 权益）</p>
                      )}
                      {dryRun.blocked?.map((b: any, i: number) => (
                        <div key={i} className="flex items-center gap-2 text-amber-700">
                          <Ban className="h-3.5 w-3.5" />
                          {b.symbol} {b.side} 被拦截：{b.reason}（{b.code}）
                        </div>
                      ))}
                      {dryRun.errors?.map((e: string, i: number) => (
                        <div key={i} className="text-rose-600">
                          {e}
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                <DataTable<any>
                  rows={engine?.runs || []}
                  rowKey={(r) => r.id}
                  empty={<Empty title="引擎尚未运行过" desc="选择一个策略并点击「启动引擎」" />}
                  columns={[
                    { key: 'id', label: '运行 ID', render: (r) => <span className="num text-slate-500">#{r.id}</span> },
                    { key: 'm', label: '模式', render: (r) => <Badge tone={r.mode === 'live' ? 'red' : 'brand'}>{r.mode}</Badge> },
                    {
                      key: 'st',
                      label: '状态',
                      render: (r) => (
                        <Badge tone={r.status === 'RUNNING' ? 'green' : r.status === 'ERROR' ? 'red' : 'slate'} dot={r.status === 'RUNNING'}>
                          {r.status}
                        </Badge>
                      ),
                    },
                    { key: 't', label: 'tick 数', align: 'right', render: (r) => <span className="num">{r.tick_count}</span> },
                    { key: 'lt', label: '最近 tick', render: (r) => <span className="text-xs text-slate-500">{r.last_tick ? fmtAgo(r.last_tick) : '—'}</span> },
                    {
                      key: 'a',
                      label: '',
                      align: 'right',
                      render: (r) =>
                        r.status === 'RUNNING' ? (
                          <Button size="sm" variant="danger" icon={<Square className="h-3 w-3" />} onClick={() => stopEngine(r.strategy_id)}>
                            停止
                          </Button>
                        ) : null,
                    },
                  ]}
                />
              </div>
            )}
          </Card>

          {/* 持仓 */}
          <Card title="当前持仓" subtitle="含浮盈与占比" dense>
            <DataTable<PositionItem>
              rows={positions}
              rowKey={(r) => r.symbol}
              maxHeight="300px"
              empty={<Empty title="无持仓" />}
              columns={[
                { key: 's', label: '标的', render: (r) => <span className="font-medium">{r.symbol}</span> },
                { key: 'q', label: '数量', align: 'right', render: (r) => <span className="num">{fmtNum(r.quantity, 2)}</span> },
                { key: 'c', label: '成本', align: 'right', render: (r) => <span className="num">{fmtNum(r.avg_cost, 2)}</span> },
                { key: 'l', label: '现价', align: 'right', render: (r) => <span className="num">{fmtNum(r.last_price, 2)}</span> },
                { key: 'm', label: '市值', align: 'right', render: (r) => <span className="num">{fmtMoney(r.market_value, 0)}</span> },
                {
                  key: 'p',
                  label: '盈亏',
                  align: 'right',
                  render: (r) => <span className={`num ${signClass(r.unrealized_pnl)}`}>{fmtMoney(r.unrealized_pnl, 0)}</span>,
                },
                {
                  key: 'w',
                  label: '占比',
                  align: 'right',
                  render: (r) => <span className="num text-slate-500">{r.weight.toFixed(1)}%</span>,
                },
                {
                  key: 'a',
                  label: '',
                  align: 'right',
                  render: (r) => (
                    <Button
                      size="sm"
                      onClick={() => {
                        setSymbol(r.symbol)
                        setSide(r.quantity > 0 ? 'SELL' : 'BUY')
                        setQty(Math.abs(r.quantity))
                        setOrderType('MKT')
                        setTab('order')
                      }}
                    >
                      平仓
                    </Button>
                  ),
                },
              ]}
            />
          </Card>
        </div>

        {/* 右栏：券商状态 + 风控占用 + 订单流 */}
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
                            load()
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

          <Card title="订单流水" dense actions={<Badge tone="slate">{orders.length}</Badge>}>
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
      </div>

      {/* 下单确认 */}
      <Modal
        open={confirmOpen}
        onClose={() => setConfirmOpen(false)}
        title="确认下单"
        footer={
          <>
            <Button onClick={() => setConfirmOpen(false)}>取消</Button>
            <Button variant={side === 'BUY' ? 'danger' : 'success'} loading={placing} onClick={submitOrder} icon={<Send className="h-3.5 w-3.5" />}>
              确认提交
            </Button>
          </>
        }
      >
        <div className="space-y-3">
          {liveOn && (
            <Alert tone="danger" title="⚠️ 实盘订单">
              这笔订单将直接提交到真实券商账户，产生真实资金变动。
            </Alert>
          )}
          <div className="rounded-lg bg-slate-50 p-3.5 text-sm">
            <div className="flex items-center justify-between">
              <span className="text-slate-500">标的</span>
              <span className="font-semibold">{symbol}</span>
            </div>
            <div className="mt-2 flex items-center justify-between">
              <span className="text-slate-500">方向</span>
              <Badge tone={side === 'BUY' ? 'red' : 'green'}>{side}</Badge>
            </div>
            <div className="mt-2 flex items-center justify-between">
              <span className="text-slate-500">数量</span>
              <span className="num font-semibold">
                {preview?.adjusted_qty != null && preview.adjusted_qty !== qty
                  ? `${fmtNum(preview.adjusted_qty, 2)} 股（护栏缩减，原 ${fmtNum(qty, 2)}）`
                  : `${fmtNum(qty, 2)} 股`}
              </span>
            </div>
            <div className="mt-2 flex items-center justify-between">
              <span className="text-slate-500">类型 / 有效期</span>
              <span>
                {orderType} / {tif}
              </span>
            </div>
            {quotes[symbol] && (
              <div className="mt-2 flex items-center justify-between border-t border-slate-200 pt-2">
                <span className="text-slate-500">预估名义金额</span>
                <span className="num font-semibold">{fmtMoney(qty * quotes[symbol].price, 0)}</span>
              </div>
            )}
          </div>
          {/* T-115：确认弹窗内渲染预检结果（护栏 / 参考 / 成本） */}
          {preview && (
            <div
              className={`rounded-lg border p-3 text-xs ${
                preview.ok ? 'border-emerald-200 bg-emerald-50 text-emerald-800' : 'border-rose-200 bg-rose-50 text-rose-800'
              }`}
            >
              <div className="font-medium">
                护栏校验{preview.ok ? '通过' : '拒绝'}
                {preview.code && preview.code !== 'OK' ? `（${preview.code}）` : ''}
              </div>
              <div className="mt-1 flex flex-wrap gap-x-4 gap-y-1 text-slate-600">
                <span>参考价 {fmtNum(preview.estimated?.reference_price, 2)}</span>
                <span>名义 {fmtMoney(preview.estimated?.notional, 0)}</span>
                <span>佣金 ≈ {fmtMoney(preview.estimated?.commission_estimate, 2)}</span>
                <span>占权益 {preview.estimated?.pct_of_equity}%</span>
              </div>
              {preview.warnings?.length > 0 && (
                <ul className="mt-1.5 list-disc pl-4 text-amber-700">
                  {preview.warnings.map((w: string, i: number) => (
                    <li key={i}>{w}</li>
                  ))}
                </ul>
              )}
            </div>
          )}
        </div>
      </Modal>

      {/* 实盘解锁 */}
      <Modal
        open={unlockOpen}
        onClose={() => setUnlockOpen(false)}
        title={mode?.live_unlocked ? '锁定实盘通道' : '解锁实盘通道'}
        footer={
          <>
            <Button onClick={() => setUnlockOpen(false)}>取消</Button>
            {mode?.live_unlocked ? (
              <Button variant="primary" loading={unlockBusy} onClick={() => doUnlock(false)}>
                确认锁定
              </Button>
            ) : (
              <Button
                variant="danger"
                loading={unlockBusy}
                disabled={unlockPhrase.trim() !== (mode?.confirm_phrase || '') || !unlockPwd}
                onClick={() => doUnlock(true)}
              >
                确认解锁
              </Button>
            )}
          </>
        }
      >
        {mode?.live_unlocked ? (
          <Alert tone="info" title="当前实盘已解锁">
            锁定后将无法再进行实盘下单，可随时重新解锁。是否确认锁定？
          </Alert>
        ) : (
          <div className="space-y-4">
            <Alert tone="danger" title="⚠️ 高风险操作">
              解锁实盘后，在实盘模式下的每一笔订单都会真实成交。请确认你理解并接受全部资金风险。
            </Alert>
            {!mode?.live_env_gate && (
              <Alert tone="warn" title="第一道锁尚未开启">
                需要先设置环境变量 <code className="rounded bg-slate-200 px-1">QD_ALLOW_LIVE_TRADING=true</code> 并重启服务，
                才可能解锁实盘。这是刻意设计的安全门槛。
              </Alert>
            )}
            <Field label={`逐字输入确认短语：${mode?.confirm_phrase || ''}`}>
              <Input
                value={unlockPhrase}
                onChange={(e) => setUnlockPhrase(e.target.value)}
                placeholder={mode?.confirm_phrase}
                className="num"
              />
            </Field>
            <Field label="账户口令">
              <Input type="password" value={unlockPwd} onChange={(e) => setUnlockPwd(e.target.value)} autoComplete="current-password" />
            </Field>
          </div>
        )}
      </Modal>
    </div>
  )
}
