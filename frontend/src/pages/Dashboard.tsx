import {
  Activity,
  AlertTriangle,
  ArrowUpRight,
  Bot,
  CircleDollarSign,
  Layers,
  RefreshCw,
  ShieldAlert,
  TrendingDown,
  TrendingUp,
} from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'

import { Alert, Badge, Button, Card, DataTable, Empty, Loading, Progress, Stat, useToast } from '../components/ui'
import WatchBar from '../components/WatchBar'
import { api } from '../lib/api'
import { rtSubscribe } from '../lib/realtime'
import { fmtAgo, fmtCompact, fmtMoney, fmtNum, fmtRatioPct, signClass } from '../lib/format'
import type { AIResult, AccountSnapshot, OrderRow, PositionItem, Quote, SystemStatus } from '../lib/types'

export default function Dashboard() {
  const toast = useToast()
  const [acc, setAcc] = useState<AccountSnapshot | null>(null)
  const [accErr, setAccErr] = useState('')   // P1-13：账户读取失败必须可见，防「权益 $0.00」误导
  const [positions, setPositions] = useState<PositionItem[]>([])
  const [orders, setOrders] = useState<OrderRow[]>([])
  const [quotes, setQuotes] = useState<Quote[]>([])
  const [status, setStatus] = useState<SystemStatus | null>(null)
  const [ai, setAi] = useState<AIResult[]>([])
  const [limits, setLimits] = useState<{ max_position_pct: number; max_gross_exposure_pct: number; max_open_positions: number } | null>(null)
  const [ds, setDs] = useState<{ preferred: string; chain: string[] } | null>(null)
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [aiLoading, setAiLoading] = useState(false)

  const load = useCallback(
    async (silent = false) => {
      if (!silent) setLoading(true)
      else setRefreshing(true)
      // 各请求独立渲染（不再 allSettled 等全部完成）：
      // /market/overview 首次要订阅 12 标的行情（IBKR 5~15s），合并等会把整个首屏拖住
      const done = () => {
        setLoading(false)
        setRefreshing(false)
      }
      api.get<AccountSnapshot>('/trading/account').then(
        (v) => { setAcc(v); setAccErr(''); done() },
        (e) => { setAccErr(e?.message || '账户数据读取失败'); done() },
      )
      api.get<{ items: PositionItem[] }>('/trading/positions').then((v) => setPositions(v.items), () => {})
      api.get<{ items: OrderRow[] }>('/trading/orders?limit=8').then((v) => setOrders(v.items), () => {})
      api.get<{ items: Quote[] }>('/market/overview').then((v) => setQuotes(v.items), () => {})
      api.get<SystemStatus>('/system/status').then(setStatus, () => {})
      api.get<{ config: any }>('/risk/config').then((v) => setLimits(v.config), () => {})
      api.get<{ preferred: string; chain: string[] }>('/market/data-source').then((v) => setDs(v), () => {})
    },
    [],
  )

  useEffect(() => {
    load()
    const t = setInterval(() => load(true), 60000)   // 降级轮询（行情主链路已走 WebSocket）
    return () => clearInterval(t)
  }, [load])

  // WebSocket 实时报价（T-106b）：市场快照区秒级跳动
  const MAJORS_KEY = 'SPY,QQQ,IWM,DIA,^VIX,TLT,GLD,USO,^TNX,SMH,FXI,EEM'
  useEffect(() => rtSubscribe([`quotes:${MAJORS_KEY}`], (m) => {
    const rows = m.data || []
    setQuotes((prev) =>
      prev.map((q) => {
        const r = rows.find((x: any) => x.symbol === q.symbol)
        return r ? { ...q, ...r } : q
      }),
    )
  }), [])

  const runAI = async () => {
    setAiLoading(true)
    try {
      const r = await api.post<{ results: AIResult[] }>('/ai/analyze', {
        symbols: ['SPY', 'QQQ', 'NVDA'],
        horizon: 'swing',
      })
      setAi(r.results)
    } catch (e: any) {
      toast('error', e?.message || 'AI 分析失败')
    } finally {
      setAiLoading(false)
    }
  }

  useEffect(() => {
    runAI()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  if (loading && !acc) return <Loading label="正在加载账户与行情…" />

  const equity = acc?.equity ?? 0
  const posPct = equity ? (positions.reduce((s, p) => s + Math.abs(p.market_value), 0) / equity) * 100 : 0
  // 风控上限取自 /risk/config（后端真实值），不再硬编码
  const grossCap = limits?.max_gross_exposure_pct ?? 100
  const posCap = limits?.max_position_pct ?? 20
  const maxPosPct = equity
    ? Math.max(...positions.map((p) => (Math.abs(p.market_value) / equity) * 100), 0)
    : 0
  const posLimit = limits?.max_open_positions ?? 10

  return (
    <div className="space-y-5">
      <WatchBar />

      {/* 顶部操作 */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-2">
          <Badge tone={status?.mode === 'live' ? 'red' : 'brand'} dot>
            {status?.mode === 'live' ? '实盘模式' : '模拟盘模式'}
          </Badge>
          <Badge tone={acc?.connected ? 'green' : 'amber'} dot>
            {acc?.connected ? '券商已连接' : '券商未连接'}
          </Badge>
          {status?.kill_switch && <Badge tone="red">熔断已启用</Badge>}
          {status?.live_env_gate && <Badge tone="amber">实盘环境开关已开</Badge>}
        </div>
        <Button icon={<RefreshCw className={`h-3.5 w-3.5 ${refreshing ? 'animate-spin' : ''}`} />} onClick={() => load(true)}>
          刷新
        </Button>
      </div>

      {status?.kill_switch && (
        <Alert tone="danger" title="熔断开关已启用">
          所有新订单（含实时引擎）均被拒绝。已有持仓不会自动平仓，请前往风控中心决定处理方式。
        </Alert>
      )}
      {acc && !acc.connected && (
        <Alert tone="warn" title="券商未连接">
          {acc.message || '请前往「系统设置」检查券商连接配置。'}
        </Alert>
      )}
      {accErr && (
        <Alert tone="danger" title="账户数据读取失败">
          {accErr} —— 下方「账户权益 / 现金」为占位 $0.00，**不是真实账户值**。
        </Alert>
      )}

      {/* 核心指标 */}
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-5">
        <Stat
          label="账户权益"
          value={fmtMoney(equity, 2)}
          sub={`现金 ${fmtMoney(acc?.cash ?? 0, 2)}`}
          icon={<CircleDollarSign className="h-4 w-4" />}
        />
        <Stat
          label="当日盈亏"
          value={fmtMoney(acc?.day_pnl ?? 0, 2)}
          sub={fmtRatioPct(acc?.day_pnl_pct ? acc.day_pnl_pct / 100 : 0, 2, true)}
          tone={(acc?.day_pnl ?? 0) > 0 ? 'up' : (acc?.day_pnl ?? 0) < 0 ? 'down' : 'neutral'}
          icon={(acc?.day_pnl ?? 0) >= 0 ? <TrendingUp className="h-4 w-4" /> : <TrendingDown className="h-4 w-4" />}
        />
        <Stat
          label="未实现盈亏"
          value={fmtMoney(acc?.unrealized_pnl ?? 0, 2)}
          sub={`已实现 ${fmtMoney(acc?.realized_pnl ?? 0, 2)}`}
          tone={(acc?.unrealized_pnl ?? 0) > 0 ? 'up' : (acc?.unrealized_pnl ?? 0) < 0 ? 'down' : 'neutral'}
        />
        <Stat
          label="持仓市值"
          value={fmtMoney(acc?.gross_position_value ?? 0, 2)}
          sub={`${positions.length} 个持仓`}
          icon={<Layers className="h-4 w-4" />}
        />
        <Stat
          label="总敞口"
          value={`${posPct.toFixed(1)}%`}
          sub={`风控上限 ${grossCap.toFixed(0)}%`}
          icon={<Activity className="h-4 w-4" />}
        />
      </div>

      <div className="grid gap-5 xl:grid-cols-3">
        {/* 市场概览 */}
        <Card
          className="xl:col-span-2"
          title="市场概览"
          subtitle="主要指数与资产类别实时快照（点击进入行情分析）"
          actions={<Badge tone="slate">{quotes.length} 个标的</Badge>}
        >
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-4">
            {quotes.map((q) => (
              <Link
                key={q.symbol}
                to={`/market?symbol=${encodeURIComponent(q.symbol)}`}
                className="group rounded-lg border border-slate-200 p-3 transition-colors hover:border-brand-300 hover:bg-brand-50/40"
              >
                <div className="flex items-center justify-between">
                  <span className="text-xs font-semibold text-slate-700">{q.symbol}</span>
                  <span className={`num text-[11px] font-medium ${signClass(q.change_pct)}`}>
                    {q.change_pct > 0 ? '+' : ''}
                    {q.change_pct.toFixed(2)}%
                  </span>
                </div>
                <div className="num mt-1 text-base font-semibold text-slate-900">{fmtNum(q.price, 2)}</div>
                <div className="mt-1 flex items-center justify-between">
                  <span className={`num text-[11px] ${signClass(q.change)}`}>
                    {q.change > 0 ? '+' : ''}
                    {fmtNum(q.change, 2)}
                  </span>
                  <span className="text-[10px] text-slate-400">{fmtCompact(q.volume)}</span>
                </div>
              </Link>
            ))}
            {!quotes.length && <div className="col-span-full py-8 text-center text-sm text-slate-400">暂无行情</div>}
          </div>
        </Card>

        {/* AI 简报 */}
        <Card
          title="AI 量化研判"
          subtitle="本地引擎实时计算，非生成式文本"
          actions={
            <Button size="sm" loading={aiLoading} onClick={runAI} icon={<Bot className="h-3.5 w-3.5" />}>
              重新分析
            </Button>
          }
        >
          {aiLoading && !ai.length ? (
            <Loading label="正在计算…" />
          ) : !ai.length ? (
            <Empty icon={<Bot className="h-8 w-8" />} title="暂无分析" desc="点击「重新分析」生成市场研判" />
          ) : (
            <div className="space-y-3">
              {ai.map((r) => (
                <div key={r.symbol} className="rounded-lg border border-slate-200 p-3">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-semibold text-slate-800">{r.symbol}</span>
                      <Badge tone={r.bias === '多头' ? 'red' : r.bias === '空头' ? 'green' : 'slate'}>{r.bias}</Badge>
                    </div>
                    <span className={`num text-sm font-semibold ${signClass(r.composite_score)}`}>
                      {r.composite_score > 0 ? '+' : ''}
                      {r.composite_score.toFixed(1)}
                    </span>
                  </div>
                  <div className="mt-2 flex items-center gap-2 text-xs text-slate-500">
                    <Badge tone="blue">{r.regime}</Badge>
                    <span>建议仓位 {r.suggested_position_pct}%</span>
                  </div>
                  {r.warnings?.[0] && (
                    <p className="mt-2 flex items-start gap-1.5 text-[11px] text-amber-700">
                      <AlertTriangle className="mt-0.5 h-3 w-3 shrink-0" />
                      {r.warnings[0]}
                    </p>
                  )}
                  {r.strategy_matches?.[0] && (
                    <p className="mt-1.5 text-[11px] text-slate-400">
                      匹配策略：{r.strategy_matches[0].name}
                    </p>
                  )}
                </div>
              ))}
              <Link to="/ai" className="block text-center text-xs text-brand-600 hover:underline">
                查看完整研判与组合建议 →
              </Link>
            </div>
          )}
        </Card>
      </div>

      <div className="grid gap-5 xl:grid-cols-3">
        {/* 持仓 */}
        <Card
          className="xl:col-span-2"
          title="当前持仓"
          subtitle="含实时浮盈与占比"
          actions={
            <Link to="/portfolio">
              <Button size="sm" icon={<ArrowUpRight className="h-3.5 w-3.5" />}>
                持仓明细
              </Button>
            </Link>
          }
          dense
        >
          <DataTable<PositionItem>
            rows={positions}
            rowKey={(r) => r.symbol}
            maxHeight="320px"
            empty={
              <Empty
                icon={<Layers className="h-8 w-8" />}
                title="当前无持仓"
                desc="可以前往「策略实验室」做回测，或在「实盘交易」页手动下单"
                action={
                  <Link to="/strategies">
                    <Button size="sm" variant="primary">
                      去挑选策略
                    </Button>
                  </Link>
                }
              />
            }
            columns={[
              { key: 'symbol', label: '标的', render: (r) => <span className="font-medium text-slate-800">{r.symbol}</span> },
              { key: 'qty', label: '数量', align: 'right', render: (r) => <span className="num">{fmtNum(r.quantity, 2)}</span> },
              { key: 'cost', label: '成本', align: 'right', render: (r) => <span className="num">{fmtNum(r.avg_cost, 2)}</span> },
              { key: 'last', label: '现价', align: 'right', render: (r) => <span className="num">{fmtNum(r.last_price, 2)}</span> },
              { key: 'mv', label: '市值', align: 'right', render: (r) => <span className="num">{fmtMoney(r.market_value, 0)}</span> },
              {
                key: 'pnl',
                label: '浮动盈亏',
                align: 'right',
                render: (r) => (
                  <span className={`num ${signClass(r.unrealized_pnl)}`}>
                    {fmtMoney(r.unrealized_pnl, 0)}
                    <span className="ml-1 text-[11px]">({r.unrealized_pct.toFixed(2)}%)</span>
                  </span>
                ),
              },
              {
                key: 'w',
                label: '占比',
                align: 'right',
                render: (r) => <span className="num text-slate-500">{r.weight.toFixed(1)}%</span>,
              },
            ]}
          />
        </Card>

        {/* 最近订单 */}
        <Card title="最近订单" subtitle="来自手动下单与实时引擎" actions={<Link to="/portfolio"><Button size="sm">全部</Button></Link>} dense>
          <DataTable<OrderRow>
            rows={orders}
            rowKey={(r) => r.id}
            maxHeight="320px"
            empty={<Empty title="暂无订单记录" />}
            columns={[
              {
                key: 'sym',
                label: '标的',
                render: (r) => (
                  <div>
                    <div className="font-medium text-slate-800">{r.symbol}</div>
                    <div className="text-[10px] text-slate-400">{fmtAgo(r.created_at)}</div>
                  </div>
                ),
              },
              {
                key: 'side',
                label: '方向',
                render: (r) => <Badge tone={r.side === 'BUY' ? 'red' : 'green'}>{r.side === 'BUY' ? '买入' : '卖出'}</Badge>,
              },
              { key: 'qty', label: '数量', align: 'right', render: (r) => <span className="num">{fmtNum(r.quantity, 0)}</span> },
              { key: 'px', label: '均价', align: 'right', render: (r) => <span className="num">{fmtNum(r.avg_fill_price, 2)}</span> },
              {
                key: 'st',
                label: '状态',
                render: (r) => (
                  <Badge tone={r.status === 'FILLED' ? 'green' : r.status === 'REJECTED' ? 'red' : 'amber'}>
                    {r.status}
                  </Badge>
                ),
              },
            ]}
          />
        </Card>
      </div>

      {/* 系统概览 */}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Card>
          <div className="flex items-center gap-3">
            <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-brand-50 text-brand-600">
              <Bot className="h-4 w-4" />
            </div>
            <div>
              <div className="text-xs text-slate-500">内置策略</div>
              <div className="num text-lg font-semibold text-slate-800">{status?.strategies ?? '—'}</div>
            </div>
          </div>
        </Card>
        <Card>
          <div className="flex items-center gap-3">
            <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-emerald-50 text-emerald-600">
              <Activity className="h-4 w-4" />
            </div>
            <div className="min-w-0">
              <div className="text-xs text-slate-500">数据源</div>
              <div className="truncate text-sm font-medium text-slate-800">
                {ds ? (ds.preferred === 'auto' ? '自动降级：' + (ds.chain?.slice(0, 3).join(' → ') ?? '') : `优先 ${ds.preferred}`) : '加载中…'}
              </div>
            </div>
          </div>
        </Card>
        <Card>
          <div className="flex items-center gap-3">
            <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-amber-50 text-amber-600">
              <ShieldAlert className="h-4 w-4" />
            </div>
            <div className="min-w-0">
              <div className="text-xs text-slate-500">实盘通道</div>
              <div className="truncate text-sm font-medium text-slate-800">
                {status?.live_ready ? '已就绪 ⚠️' : '已锁定'}
              </div>
            </div>
          </div>
        </Card>
        <Card>
          <div className="flex items-center gap-3">
            <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-sky-50 text-sky-600">
              <Bot className="h-4 w-4" />
            </div>
            <div className="min-w-0">
              <div className="text-xs text-slate-500">AI 引擎</div>
              <div className="truncate text-sm font-medium text-slate-800">
                {status?.ai_configured ? 'LLM + 本地双引擎' : '本地量化引擎'}
              </div>
            </div>
          </div>
        </Card>
      </div>

      <Card title="敞口使用率" subtitle="风控护栏实时占用情况">
        <div className="grid gap-5 sm:grid-cols-3">
          <div>
            <Progress
              value={posPct}
              max={grossCap}
              tone={posPct / grossCap > 0.9 ? 'red' : posPct / grossCap > 0.7 ? 'amber' : 'brand'}
              label={
                <>
                  <span>总敞口</span>
                  <span className="num">
                    {posPct.toFixed(1)}% / {grossCap.toFixed(0)}%
                  </span>
                </>
              }
            />
          </div>
          <div>
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
          </div>
          <div>
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
          </div>
        </div>
      </Card>
    </div>
  )
}
