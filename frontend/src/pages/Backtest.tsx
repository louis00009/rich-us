import {
  BarChart3,
  Calendar,
  Download,
  GitCompare,
  History,
  LineChart,
  Play,
  Plus,
  RotateCcw,
  Settings2,
  Sparkles,
  Trash2,
  TrendingUp,
  X,
} from 'lucide-react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useLocation } from 'react-router-dom'
import { EquityChart, HBar, MonthlyBars, MonthlyHeatmap, MultiEquityChart } from '../components/charts'
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
  Tabs,
  useToast,
} from '../components/ui'
import { api, getToken, LONG_TIMEOUT } from '../lib/api'
import { METRIC_LABEL, fmtMoney, fmtNum, fmtPct, fmtRatioPct, fmtDate, signClass } from '../lib/format'
import type {
  BacktestResult,
  CompareResult,
  DataSourceInfo,
  StrategyConfig,
  StrategyInfo,
  TradeRow,
} from '../lib/types'

interface MetaResp {
  metrics: { key: string; label: string; fmt: string }[]
  stop_types: { key: string; label: string; desc: string }[]
  sizing_methods: { key: string; label: string; desc: string }[]
  objectives: { key: string; label: string }[]
}

const METRIC_GROUPS: { title: string; keys: string[] }[] = [
  { title: '收益', keys: ['total_return', 'cagr', 'excess_cagr', 'best_month', 'worst_month'] },
  { title: '风险', keys: ['volatility', 'max_drawdown', 'max_dd_days', 'var95_daily', 'cvar95_daily'] },
  { title: '风险调整', keys: ['sharpe', 'sortino', 'calmar', 'information_ratio', 'beta'] },
  { title: '交易行为', keys: ['trades', 'win_rate', 'profit_factor', 'payoff_ratio', 'expectancy', 'avg_bars_held', 'turnover', 'avg_exposure'] },
]

/**
 * 从净值曲线重算月度收益。
 * 历史回测记录未单独存月度数据，这里按「本月末净值 / 上月末净值 - 1」重算，
 * 避免改表结构，也让历史详情的月度分析与热力图可用（此前恒为空）。
 */
function monthlyFromCurve(curve: { date: string; equity: number }[] | undefined): Record<string, number> {
  if (!curve || curve.length < 2) return {}
  const monthEnd = new Map<string, number>()
  for (const p of curve) {
    const m = String(p?.date ?? '').slice(0, 7)
    const v = Number(p?.equity)
    if (m.length === 7 && Number.isFinite(v) && v > 0) monthEnd.set(m, v)
  }
  const months = [...monthEnd.keys()].sort()
  const out: Record<string, number> = {}
  for (let i = 1; i < months.length; i++) {
    const prev = monthEnd.get(months[i - 1]) as number
    const cur = monthEnd.get(months[i]) as number
    if (prev > 0) out[months[i]] = cur / prev - 1
  }
  return out
}

export default function Backtest() {
  const loc = useLocation()
  const toast = useToast()
  const prefill = (loc.state || {}) as any

  const [meta, setMeta] = useState<MetaResp | null>(null)
  const [builtin, setBuiltin] = useState<StrategyInfo[]>([])
  const [customs, setCustoms] = useState<StrategyConfig[]>([])

  const [strategyKey, setStrategyKey] = useState(prefill.strategy_key || 'dual_ma_trend')
  const [customId, setCustomId] = useState<number | ''>('')
  const [symbols, setSymbols] = useState<string>((prefill.symbols || ['SPY', 'QQQ']).join(','))
  const [start, setStart] = useState('2019-01-01')
  const [end, setEnd] = useState('')
  const [interval, setInterval_] = useState('1d')
  const [capital, setCapital] = useState(100000)
  const [commission, setCommission] = useState(1)
  const [slippage, setSlippage] = useState(2)
  const [benchmark, setBenchmark] = useState('SPY')
  const [stopType, setStopType] = useState('none')
  const [stopValue, setStopValue] = useState(3)
  const [takeProfitR, setTakeProfitR] = useState(0)
  const [timeStop, setTimeStop] = useState(0)
  const [sizing, setSizing] = useState('weight')
  const [riskPct, setRiskPct] = useState(1)
  const [dataSource, setDataSource] = useState('auto')
  const [dsInfo, setDsInfo] = useState<DataSourceInfo | null>(null)
  const [params, setParams] = useState<Record<string, any>>(prefill.params || {})
  const [rule, setRule] = useState<any>(prefill.rule || null)
  const [code, setCode] = useState<string>(prefill.code || '')

  const [running, setRunning] = useState(false)
  const [result, setResult] = useState<BacktestResult | null>(null)
  const [tab, setTab] = useState('metrics')

  const [optOpen, setOptOpen] = useState(false)
  const [optGrid, setOptGrid] = useState<Record<string, string>>({})
  const [optObjective, setOptObjective] = useState('sharpe')
  const [optResult, setOptResult] = useState<any>(null)
  const [optRunning, setOptRunning] = useState(false)

  const [history, setHistory] = useState<any[]>([])
  const [detailOpen, setDetailOpen] = useState(false)

  // 多策略对比
  const [cmpOpen, setCmpOpen] = useState(false)
  const [cmpItems, setCmpItems] = useState<{ label: string; strategy_key: string; symbols: string }[]>([
    { label: '策略 A', strategy_key: 'dual_ma_trend', symbols: 'SPY' },
    { label: '策略 B', strategy_key: 'vol_managed_momentum', symbols: 'SPY' },
  ])
  const [cmpRunning, setCmpRunning] = useState(false)
  const [cmpResult, setCmpResult] = useState<CompareResult | null>(null)

  useEffect(() => {
    Promise.all([
      api.get<MetaResp>('/backtest/meta'),
      api.get<{ builtin: StrategyInfo[] }>('/strategies'),
      api.get<{ items: StrategyConfig[] }>('/strategies/custom'),
      api.get<DataSourceInfo>('/market/data-source'),
    ])
      .then(([m, b, c, d]) => {
        setMeta(m)
        setBuiltin(b.builtin)
        setCustoms(c.items)
        setDsInfo(d)
      })
      .catch(() => toast('error', '加载回测元信息失败'))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const loadHistory = useCallback(() => {
    api.get<{ items: any[] }>('/backtest/history?limit=30').then((r) => setHistory(r.items)).catch(() => {})
  }, [])
  useEffect(() => {
    loadHistory()
  }, [loadHistory])

  const currentStrategy = useMemo(
    () => (strategyKey === '' ? null : builtin.find((s) => s.key === strategyKey) || null),
    [builtin, strategyKey],
  )

  // 切换策略时重置参数
  useEffect(() => {
    if (currentStrategy && !prefill.params) {
      setParams(Object.fromEntries(currentStrategy.params.map((p) => [p.key, p.default])))
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [strategyKey])

  const run = async () => {
    setRunning(true)
    setResult(null)
    try {
      const body: any = {
        strategy_key: strategyKey,
        params,
        symbols: symbols.split(',').map((s) => s.trim().toUpperCase()).filter(Boolean),
        start,
        end: end || null,
        interval,
        initial_capital: capital,
        commission_bps: commission,
        slippage_bps: slippage,
        benchmark,
        risk: {
          stop_type: stopType,
          stop_value: stopValue,
          take_profit_r: takeProfitR,
          time_stop_bars: timeStop,
          sizing_method: sizing,
          risk_per_trade_pct: riskPct,
        },
        label: '',
        data_source: dataSource,
      }
      if (strategyKey === 'custom_rule') body.rule = rule
      if (strategyKey === 'custom_code') body.code = code

      const r = await api.post<BacktestResult>('/backtest/run', body, LONG_TIMEOUT)
      setResult(r)
      setTab('metrics')
      if (r.data_warning) toast('warning', r.data_warning)
      else toast('success', `回测完成：${r.bars} 根 bar，${r.trade_count} 笔交易（数据源 ${r.data_source_used}）`)
      loadHistory()
    } catch (e: any) {
      toast('error', e?.message || '回测失败')
    } finally {
      setRunning(false)
    }
  }

  const runCompare = async () => {
    const items = cmpItems
      .filter((it) => it.strategy_key && it.symbols.trim())
      .map((it, i) => ({
        label: it.label || `策略 ${i + 1}`,
        strategy_key: it.strategy_key,
        symbols: it.symbols.split(',').map((s) => s.trim().toUpperCase()).filter(Boolean),
        risk: {
          stop_type: stopType, stop_value: stopValue,
          take_profit_r: takeProfitR, time_stop_bars: timeStop,
          sizing_method: sizing, risk_per_trade_pct: riskPct,
        },
      }))
    if (items.length < 2) {
      toast('warning', '至少需要 2 个策略才能对比')
      return
    }
    setCmpRunning(true)
    setCmpResult(null)
    try {
      const r = await api.post<CompareResult>('/backtest/compare', {
        items,
        start, end: end || null, interval,
        initial_capital: capital,
        commission_bps: commission, slippage_bps: slippage,
        benchmark,
        data_source: dataSource,
      }, LONG_TIMEOUT)
      setCmpResult(r)
      toast('success', `对比完成：${r.labels.length} 个策略`)
    } catch (e: any) {
      toast('error', e?.message || '对比失败')
    } finally {
      setCmpRunning(false)
    }
  }

  const download = async (kind: 'trades' | 'equity' | 'monthly') => {
    if (!result?.run_id) {
      toast('warning', '请先运行一次回测（结果会自动保存后再导出）')
      return
    }
    try {
      const res = await fetch(`/api/backtest/${result.run_id}/export?kind=${kind}`, {
        headers: { Authorization: `Bearer ${getToken()}` },
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const blob = await res.blob()
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `quantdesk_${result.strategy_name}_${kind}.csv`
      document.body.appendChild(a)
      a.click()
      a.remove()
      URL.revokeObjectURL(url)
      toast('success', `${kind} 已导出为 CSV`)
    } catch (e: any) {
      toast('error', `导出失败：${e?.message || e}`)
    }
  }

  const [optJobId, setOptJobId] = useState<string | null>(null)
  const [optProgress, setOptProgress] = useState<{ done: number; total: number } | null>(null)
  const optPollRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const optJobIdRef = useRef<string | null>(null)

  // 轮询后台寻优任务进度；完成/取消/失败时收尾
  const pollOptJob = useCallback((jobId: string) => {
    if (optPollRef.current) clearInterval(optPollRef.current)
    optPollRef.current = setInterval(async () => {
      try {
        const j = await api.get<any>(`/backtest/job/${jobId}`)
        if (j.status === 'running') {
          setOptProgress({ done: j.progress, total: j.total })
          return
        }
        if (optPollRef.current) clearInterval(optPollRef.current)
        optPollRef.current = null
        setOptProgress(null)
        setOptRunning(false)
        setOptJobId(null)
        optJobIdRef.current = null
        if (j.status === 'done' && j.result?.ok) {
          setOptResult(j.result)
          toast('success', `寻优完成，评估 ${j.result.evaluated} 组参数`)
        } else if (j.status === 'cancelled') {
          if (j.result?.ok) setOptResult(j.result)
          toast('warning', `寻优已取消（已评估 ${j.result?.evaluated ?? 0} 组，结果保留）`)
        } else {
          toast('error', j.error || '寻优失败')
        }
      } catch {
        // 404（重启后任务丢失）等：停止轮询，不弹错
        if (optPollRef.current) clearInterval(optPollRef.current)
        optPollRef.current = null
        setOptProgress(null)
        setOptRunning(false)
        setOptJobId(null)
      }
    }, 1200)
  }, [])

  // P1-10：卸载时清理寻优轮询定时器 —— 旧实现没有清理，寻优进行中切走页面
  // 会在已卸载组件上持续轮询并 setState（内存泄漏 + 无谓请求）。
  useEffect(
    () => () => {
      if (optPollRef.current) clearInterval(optPollRef.current)
      optPollRef.current = null
    },
    [],
  )

  const cancelOptimize = async () => {
    const id = optJobIdRef.current
    if (!id) return
    try {
      await api.post(`/backtest/job/${id}/cancel`)
      toast('info', '已请求取消，当前组合评估完成后停止')
    } catch (e: any) {
      toast('error', e?.message || '取消失败')
    }
  }

  const runOptimize = async () => {
    const grid: Record<string, number[]> = {}
    Object.entries(optGrid).forEach(([k, v]) => {
      const arr = v
        .split(',')
        .map((x) => parseFloat(x.trim()))
        .filter((x) => !Number.isNaN(x))
      if (arr.length) grid[k] = arr
    })
    if (!Object.keys(grid).length) {
      toast('warning', '请至少为一个参数填写候选值（逗号分隔）')
      return
    }
    setOptRunning(true)
    setOptResult(null)
    setOptProgress(null)
    try {
      // P1-14：改为后台任务 —— 同步端点最长要跑几分钟且不可取消
      const r = await api.post<any>('/backtest/optimize-async', {
        strategy_key: strategyKey,
        param_grid: grid,
        symbols: symbols.split(',').map((s) => s.trim().toUpperCase()).filter(Boolean).slice(0, 5),
        start,
        end: end || null,
        interval: interval === '1wk' ? '1wk' : '1d',
        initial_capital: capital,
        objective: optObjective,
        max_combos: 120,
      }, LONG_TIMEOUT)
      optJobIdRef.current = r.job_id
      setOptJobId(r.job_id)
      pollOptJob(r.job_id)
    } catch (e: any) {
      toast('error', e?.message || '寻优启动失败')
      setOptRunning(false)
    }
  }

  return (
    <div className="space-y-5">
      <div className="grid gap-5 xl:grid-cols-4">
        {/* 配置面板 */}
        <Card
          className="xl:col-span-1"
          title="回测配置"
          subtitle="第 t 根 bar 的信号在第 t+1 根开盘成交，无未来函数"
        >
          <div className="space-y-3">
            <Field label="策略来源">
              <Select
                value={customId === '' ? strategyKey : `custom:${customId}`}
                onChange={(e) => {
                  const v = e.target.value
                  if (v.startsWith('custom:')) {
                    const id = parseInt(v.split(':')[1], 10)
                    setCustomId(id)
                    const c = customs.find((x) => x.id === id)
                    if (c) {
                      setStrategyKey(c.strategy_key)
                      setParams(c.params || {})
                      setRule(c.rule || null)
                      setCode(c.code || '')
                      if (c.symbols?.length) setSymbols(c.symbols.join(','))
                    }
                  } else {
                    setCustomId('')
                    setStrategyKey(v)
                    setRule(null)
                    setCode('')
                  }
                }}
              >
                <optgroup label="内置策略">
                  {builtin.map((s) => (
                    <option key={s.key} value={s.key}>
                      [{s.category}] {s.name}
                    </option>
                  ))}
                </optgroup>
                {customs.length > 0 && (
                  <optgroup label="我的策略">
                    {customs.map((c) => (
                      <option key={`c${c.id}`} value={`custom:${c.id}`}>
                        {c.name}
                      </option>
                    ))}
                  </optgroup>
                )}
              </Select>
            </Field>

            {currentStrategy && (
              <div className="rounded-lg bg-slate-50 p-3">
                <p className="text-[11px] leading-relaxed text-slate-500">{currentStrategy.description}</p>
                <div className="mt-2 flex flex-wrap gap-1">
                  <Badge tone="slate">{currentStrategy.category}</Badge>
                  {currentStrategy.multi_symbol && <Badge tone="blue">支持多标的</Badge>}
                  <Badge tone="slate">≥{currentStrategy.min_bars} bar</Badge>
                </div>
              </div>
            )}

            <Field label="标的（逗号分隔）" hint="多标的策略会自动做横截面处理">
              <Input value={symbols} onChange={(e) => setSymbols(e.target.value.toUpperCase())} placeholder="SPY,QQQ" />
            </Field>

            <div className="grid grid-cols-2 gap-3">
              <Field label="开始日期">
                <Input type="date" value={start} onChange={(e) => setStart(e.target.value)} />
              </Field>
              <Field label="结束日期" hint="留空=今天">
                <Input type="date" value={end} onChange={(e) => setEnd(e.target.value)} />
              </Field>
            </div>

            <Field label="数据周期" hint="日内周期对数据源有要求：免费源只能回溯 60 天，IBKR 可达数年">
              <Select value={interval} onChange={(e) => setInterval_(e.target.value)}>
                <option value="1d">日线 (1d)</option>
                <option value="1wk">周线 (1wk)</option>
                <option value="1h">小时线 (1h) · 免费源约 180 天</option>
                <option value="30m">30 分钟 (30m) · 免费源约 60 天</option>
                <option value="15m">15 分钟 (15m) · 免费源约 60 天</option>
                <option value="5m">5 分钟 (5m) · 免费源约 60 天</option>
              </Select>
            </Field>

            <Field
              label="数据源"
              hint={
                dsInfo?.providers?.ibkr?.available
                  ? 'IBKR 已连接，日内数据可回溯数年'
                  : 'IBKR 未连接 —— 选「IBKR 优先」会自动降级到免费源'
              }
            >
              <Select value={dataSource} onChange={(e) => setDataSource(e.target.value)}>
                <option value="auto">自动（yfinance → Stooq → 合成）</option>
                <option value="ibkr">IBKR 优先（与实盘价格一致）</option>
              </Select>
            </Field>

            <Field label="初始资金 ($)">
              <Input type="number" value={capital} onChange={(e) => setCapital(parseFloat(e.target.value || '100000'))} />
            </Field>

            <div className="grid grid-cols-2 gap-3">
              <Field label="佣金 (bp)" hint="单边万分之">
                <Input type="number" step="0.5" value={commission} onChange={(e) => setCommission(parseFloat(e.target.value || '0'))} />
              </Field>
              <Field label="滑点 (bp)">
                <Input type="number" step="0.5" value={slippage} onChange={(e) => setSlippage(parseFloat(e.target.value || '0'))} />
              </Field>
            </div>

            <Field label="基准标的" hint="用于计算 Alpha / Beta / 超额收益">
              <Input value={benchmark} onChange={(e) => setBenchmark(e.target.value.toUpperCase())} />
            </Field>

            {/* 止损 */}
            <div className="border-t border-slate-100 pt-3">
              <div className="mb-2 flex items-center gap-2">
                <span className="text-xs font-semibold uppercase tracking-wide text-slate-400">止损 / 止盈</span>
                <div className="h-px flex-1 bg-slate-100" />
              </div>
              <div className="space-y-3">
                <Field label="止损方式">
                  <Select value={stopType} onChange={(e) => setStopType(e.target.value)}>
                    {meta?.stop_types.map((s) => (
                      <option key={s.key} value={s.key}>
                        {s.label}
                      </option>
                    ))}
                  </Select>
                </Field>
                {stopType !== 'none' && (
                  <>
                    <p className="text-[11px] text-slate-400">
                      {meta?.stop_types.find((s) => s.key === stopType)?.desc}
                    </p>
                    <div className="grid grid-cols-2 gap-3">
                      <Field label={stopType.startsWith('atr') || stopType === 'chandelier' || stopType === 'volatility' ? 'ATR 倍数' : stopType === 'time_stop' ? 'bar 数（忽略）' : '百分比 %'}>
                        <Input type="number" step="0.1" value={stopValue} onChange={(e) => setStopValue(parseFloat(e.target.value || '3'))} />
                      </Field>
                      <Field label="R 倍止盈" hint="0=关闭">
                        <Input type="number" step="0.5" value={takeProfitR} onChange={(e) => setTakeProfitR(parseFloat(e.target.value || '0'))} />
                      </Field>
                    </div>
                    <Field label="时间止损 (bar)" hint="0 = 关闭；持满 N 根无表现即离场">
                      <Input type="number" value={timeStop} onChange={(e) => setTimeStop(parseInt(e.target.value || '0', 10))} />
                    </Field>
                  </>
                )}
              </div>
            </div>

            {/* 仓位 */}
            <div className="border-t border-slate-100 pt-3">
              <div className="mb-2 flex items-center gap-2">
                <span className="text-xs font-semibold uppercase tracking-wide text-slate-400">仓位算法</span>
                <div className="h-px flex-1 bg-slate-100" />
              </div>
              <div className="space-y-3">
                <Field label="算法">
                  <Select value={sizing} onChange={(e) => setSizing(e.target.value)}>
                    {meta?.sizing_methods.map((s) => (
                      <option key={s.key} value={s.key}>
                        {s.label}
                      </option>
                    ))}
                  </Select>
                </Field>
                <p className="text-[11px] text-slate-400">{meta?.sizing_methods.find((s) => s.key === sizing)?.desc}</p>
                {(sizing === 'atr_risk' || sizing === 'kelly_capped') && (
                  <Field label="每笔风险 %">
                    <Input type="number" step="0.1" value={riskPct} onChange={(e) => setRiskPct(parseFloat(e.target.value || '1'))} />
                  </Field>
                )}
              </div>
            </div>

            <Button variant="primary" size="lg" className="w-full" loading={running} onClick={run} icon={<Play className="h-4 w-4" />}>
              开始回测
            </Button>
            <Button className="w-full" icon={<Settings2 className="h-3.5 w-3.5" />} onClick={() => setOptOpen(true)}>
              参数寻优（网格搜索）
            </Button>
            <Button className="w-full" icon={<GitCompare className="h-3.5 w-3.5" />} onClick={() => setCmpOpen(true)}>
              多策略对比
            </Button>
          </div>
        </Card>

        {/* 结果区 */}
        <div className="space-y-5 xl:col-span-3">
          {running && (
            <Card>
              <Loading label="正在拉取行情并逐 bar 撮合，标的越多耗时越长…" />
            </Card>
          )}

          {!running && !result && (
            <Card>
              <Empty
                icon={<BarChart3 className="h-10 w-10" />}
                title="配置左侧参数后点击「开始回测」"
                desc="回测引擎会加载历史行情、按策略生成目标权重、逐 bar 撮合（含滑点与佣金），并应用你选择的止损规则。全部指标在本地计算，不消耗任何外部额度。"
              />
            </Card>
          )}

          {result && !running && (
            <>
              <Card
                title={
                  <span className="flex items-center gap-2">
                    <BarChart3 className="h-4 w-4 text-brand-500" />
                    {result.strategy_name} · {result.symbols.join(' / ')}
                  </span>
                }
                subtitle={`${result.date_range[0]} ~ ${result.date_range[1]} ｜ ${result.bars} 根 bar ｜ ${result.trade_count} 笔交易 ｜ 数据源 ${
                  result.data_source_used || Object.values(result.data_sources)[0] || '-'
                }`}
                actions={
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge tone={result.metrics.total_return > 0 ? 'red' : 'green'}>
                      累计 {fmtRatioPct(result.metrics.total_return, 2, true)}
                    </Badge>
                    <Button size="sm" icon={<Download className="h-3.5 w-3.5" />} onClick={() => download('trades')}>
                      交易明细
                    </Button>
                    <Button size="sm" icon={<Download className="h-3.5 w-3.5" />} onClick={() => download('equity')}>
                      净值曲线
                    </Button>
                    <Button size="sm" icon={<Download className="h-3.5 w-3.5" />} onClick={() => download('monthly')}>
                      全部指标
                    </Button>
                  </div>
                }
              >
                <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                  <Stat label="累计收益" value={fmtRatioPct(result.metrics.total_return, 2, true)} tone={result.metrics.total_return > 0 ? 'up' : 'down'} />
                  <Stat label="年化收益" value={fmtRatioPct(result.metrics.cagr, 2, true)} tone={result.metrics.cagr > 0 ? 'up' : 'down'} sub={`基准 ${fmtRatioPct(result.metrics.benchmark_cagr, 2, true)}`} />
                  <Stat label="夏普比率" value={fmtNum(result.metrics.sharpe, 2)} sub={`索提诺 ${fmtNum(result.metrics.sortino, 2)}`} />
                  <Stat label="最大回撤" value={fmtRatioPct(result.metrics.max_drawdown, 2)} tone="down" sub={`基准 ${fmtRatioPct(result.metrics.benchmark_max_drawdown, 2)}`} />
                </div>
              </Card>

              {result.strategy_notes?.length > 0 && (
                <Alert tone="info" title="策略提示">
                  {result.strategy_notes.join('；')}
                </Alert>
              )}

              <Card
                title="净值曲线与回撤"
                actions={
                  <Tabs
                    value={tab}
                    onChange={setTab}
                    tabs={[
                      { key: 'metrics', label: '绩效指标' },
                      { key: 'monthly', label: '月度分析' },
                      { key: 'trades', label: '交易明细' },
                      { key: 'compare', label: '策略对比' },
                    ]}
                  />
                }
              >
                <EquityChart data={result.curve} height={340} />

                <div className="mt-5">
                  {tab === 'metrics' && (
                    <div className="grid gap-5 md:grid-cols-2">
                      {METRIC_GROUPS.map((g) => (
                        <div key={g.title}>
                          <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-400">{g.title}</h4>
                          <div className="space-y-1.5">
                            {g.keys.map((k) => {
                              const v = result.metrics[k]
                              const pctKeys = ['total_return', 'cagr', 'excess_cagr', 'volatility', 'max_drawdown', 'win_rate', 'avg_exposure', 'var95_daily', 'cvar95_daily', 'best_month', 'worst_month']
                              const isPct = pctKeys.includes(k)
                              const show = isPct ? fmtRatioPct(v, 2, true) : k === 'trades' || k === 'max_dd_days' ? String(Math.round(Number(v) || 0)) : k === 'expectancy' ? fmtMoney(v, 2) : fmtNum(v, 2)
                              const highlight = ['total_return', 'cagr', 'max_drawdown'].includes(k)
                              return (
                                <div key={k} className="flex items-center justify-between border-b border-dashed border-slate-100 pb-1.5">
                                  <span className="text-xs text-slate-500">{METRIC_LABEL[k] || k}</span>
                                  <span className={`num text-sm ${highlight ? 'font-semibold ' + signClass(v) : 'font-medium text-slate-700'}`}>
                                    {show}
                                  </span>
                                </div>
                              )
                            })}
                          </div>
                        </div>
                      ))}
                    </div>
                  )}

                  {tab === 'monthly' && (
                    <div className="space-y-6">
                      <div>
                        <h4 className="mb-3 text-xs font-semibold uppercase tracking-wide text-slate-400">
                          月度收益热力图（%）
                        </h4>
                        <MonthlyHeatmap monthly={result.monthly} />
                      </div>
                      <div>
                        <h4 className="mb-3 text-xs font-semibold uppercase tracking-wide text-slate-400">
                          近 36 个月收益
                        </h4>
                        <MonthlyBars monthly={result.monthly} height={220} />
                      </div>
                    </div>
                  )}

                  {tab === 'trades' && (
                    <DataTable<TradeRow>
                      rows={result.trades}
                      rowKey={(r, i) => `${r.symbol}-${r.entry_time}-${i}`}
                      maxHeight="520px"
                      empty={<Empty title="本次回测没有产生交易" desc="可能是信号条件过于严格，或未在有效区间触发" />}
                      columns={[
                        { key: 's', label: '标的', render: (r) => <span className="font-medium text-slate-800">{r.symbol}</span> },
                        {
                          key: 'side',
                          label: '方向',
                          render: (r) => <Badge tone={r.side === 'LONG' ? 'red' : 'green'}>{r.side === 'LONG' ? '多' : '空'}</Badge>,
                        },
                        { key: 'en', label: '入场', render: (r) => <span className="num text-slate-500">{r.entry_time}</span> },
                        { key: 'ex', label: '离场', render: (r) => <span className="num text-slate-500">{r.exit_time}</span> },
                        { key: 'ep', label: '入价', align: 'right', render: (r) => <span className="num">{fmtNum(r.entry_price, 2)}</span> },
                        { key: 'xp', label: '出价', align: 'right', render: (r) => <span className="num">{fmtNum(r.exit_price, 2)}</span> },
                        { key: 'q', label: '数量', align: 'right', render: (r) => <span className="num">{fmtNum(r.qty, 0)}</span> },
                        {
                          key: 'p',
                          label: '盈亏',
                          align: 'right',
                          render: (r) => <span className={`num ${signClass(r.pnl)}`}>{fmtMoney(r.pnl, 2)}</span>,
                        },
                        {
                          key: 'rp',
                          label: '收益率',
                          align: 'right',
                          render: (r) => <span className={`num ${signClass(r.return_pct)}`}>{fmtRatioPct(r.return_pct, 2, true)}</span>,
                        },
                        { key: 'bh', label: '持有', align: 'right', render: (r) => <span className="num text-slate-500">{r.bars_held}</span> },
                        { key: 'er', label: '离场原因', render: (r) => <span className="text-xs text-slate-500">{r.exit_reason}</span> },
                      ]}
                    />
                  )}

                  {tab === 'compare' && (
                    <div className="space-y-5">
                      <div className="grid gap-4 sm:grid-cols-3">
                        <Stat label="策略年化" value={fmtRatioPct(result.metrics.cagr, 2, true)} tone="up" />
                        <Stat label="基准年化" value={fmtRatioPct(result.metrics.benchmark_cagr, 2, true)} sub="买入持有" />
                        <Stat
                          label="超额年化"
                          value={fmtRatioPct(result.metrics.excess_cagr, 2, true)}
                          tone={result.metrics.excess_cagr > 0 ? 'up' : 'down'}
                        />
                      </div>
                      <div className="grid gap-4 sm:grid-cols-3">
                        <Stat label="Alpha（年化）" value={fmtRatioPct(result.metrics.alpha, 2, true)} />
                        <Stat label="Beta" value={fmtNum(result.metrics.beta, 2)} />
                        <Stat label="信息比率" value={fmtNum(result.metrics.information_ratio, 2)} />
                      </div>
                      <Alert tone="info" title="如何解读">
                        Alpha 为正说明策略收益无法被市场暴露（Beta）解释，是真正的超额能力；信息比率 &gt; 0.5
                        说明超额收益相对稳定。若 Alpha ≈ 0 而 Beta ≈ 1，则该策略本质上只是「加了杠杆的买入持有」。
                      </Alert>
                    </div>
                  )}
                </div>
              </Card>
            </>
          )}

          {/* 历史回测 */}
          <Card
            title={<span className="flex items-center gap-2"><History className="h-4 w-4" />历史回测记录</span>}
            subtitle="点击行可查看详情"
            actions={
              <Button size="sm" icon={<RotateCcw className="h-3.5 w-3.5" />} onClick={loadHistory}>
                刷新
              </Button>
            }
            dense
          >
            <DataTable<any>
              rows={history}
              rowKey={(r) => r.id}
              maxHeight="280px"
              empty={<Empty title="暂无回测记录" />}
              columns={[
                { key: 'l', label: '策略', render: (r) => <span className="font-medium text-slate-700">{r.label}</span> },
                { key: 's', label: '标的', render: (r) => <span className="text-xs text-slate-500">{r.symbols.join(', ')}</span> },
                {
                  key: 'r',
                  label: '累计收益',
                  align: 'right',
                  render: (r) => <span className={`num ${signClass(r.metrics.total_return)}`}>{fmtRatioPct(r.metrics.total_return, 1, true)}</span>,
                },
                { key: 'sh', label: '夏普', align: 'right', render: (r) => <span className="num">{fmtNum(r.metrics.sharpe, 2)}</span> },
                { key: 'dd', label: '最大回撤', align: 'right', render: (r) => <span className="num text-emerald-600">{fmtRatioPct(r.metrics.max_drawdown, 1)}</span> },
                { key: 't', label: '交易', align: 'right', render: (r) => <span className="num text-slate-500">{r.metrics.trades}</span> },
                { key: 'd', label: '时间', render: (r) => <span className="num text-xs text-slate-400">{r.created_at.slice(0, 16).replace('T', ' ')}</span> },
                {
                  key: 'act',
                  label: '',
                  align: 'right',
                  render: (r) => (
                    <button
                      className="rounded p-1 text-slate-300 hover:bg-rose-50 hover:text-rose-500"
                      onClick={async (ev) => {
                        ev.stopPropagation()
                        // P3：旧实现没有 try/catch —— 删除失败会产生 unhandled rejection，
                        // 且界面上毫无提示，用户会以为已经删掉了。
                        try {
                          await api.del(`/backtest/${r.id}`)
                          loadHistory()
                        } catch (e: any) {
                          toast('error', `删除失败：${e?.message || e}`)
                        }
                      }}
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </button>
                  ),
                },
              ]}
              onRowClick={async (r) => {
                try {
                  const d = await api.get<any>(`/backtest/${r.id}`)
                  setResult({
                    ok: true,
                    strategy_name: d.strategy_name,
                    metrics: d.metrics,
                    curve: d.curve,
                    trades: d.trades,
                    trade_count: d.trades.length,
                    monthly: monthlyFromCurve(d.curve),
                    symbols: d.symbols,
                    data_sources: {},
                    strategy_notes: [],
                    bars: d.curve.length,
                    date_range: [d.start, d.end],
                  })
                  setTab('metrics')
                  toast('info', `已加载历史回测「${d.label}」`)
                } catch (e: any) {
                  toast('error', e?.message || '加载失败')
                }
              }}
            />
          </Card>
        </div>
      </div>

      {/* 参数寻优弹窗 */}
      <Modal
        open={optOpen}
        onClose={() => setOptOpen(false)}
        title="参数寻优 · 网格搜索"
        width="max-w-3xl"
        footer={
          <>
            <Button onClick={() => setOptOpen(false)}>关闭</Button>
            <Button variant="primary" loading={optRunning} onClick={runOptimize} icon={<Sparkles className="h-3.5 w-3.5" />}>
              开始寻优
            </Button>
          </>
        }
      >
        <div className="space-y-4">
          <Alert tone="warn" title="关于过拟合">
            网格搜索容易选出「历史最优但未来失效」的参数。建议：<br />
            1）优先看参数平原（相邻参数表现相近）而非单点最优；<br />
            2）用不同时间区间复验；3）参数数量控制在 2–3 个。
          </Alert>

          <Field label="优化目标">
            <Select value={optObjective} onChange={(e) => setOptObjective(e.target.value)}>
              {meta?.objectives.map((o) => (
                <option key={o.key} value={o.key}>
                  {o.label}
                </option>
              ))}
            </Select>
          </Field>

          <div>
            <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-400">参数候选值（逗号分隔）</div>
            <div className="grid gap-3 sm:grid-cols-2">
              {(currentStrategy?.params || [])
                .filter((p) => p.type === 'int' || p.type === 'float')
                .slice(0, 8)
                .map((p) => (
                  <Field key={p.key} label={`${p.label}（${p.key}）`} hint={`默认 ${p.default}`}>
                    <Input
                      value={optGrid[p.key] ?? ''}
                      onChange={(e) => setOptGrid((s) => ({ ...s, [p.key]: e.target.value }))}
                      placeholder={`如 ${p.default}, ${Math.round(Number(p.default) * 1.5) || 10}, ${Math.round(Number(p.default) * 2) || 20}`}
                    />
                  </Field>
                ))}
            </div>
            <p className="mt-2 text-xs text-slate-400">
              最多评估 120 组组合；标的会限制为前 5 个以控制耗时。
            </p>
          </div>

          {optRunning && (
            <div className="flex items-center gap-3">
              <div className="flex-1">
                {optProgress && optProgress.total > 0 ? (
                  <>
                    <Progress
                      value={optProgress.done}
                      max={optProgress.total}
                      height="h-1.5"
                    />
                    <p className="mt-1 text-xs text-slate-500">
                      进度 {optProgress.done} / {optProgress.total} 组
                      {optProgress.total > 0 &&
                        `（约 ${Math.max(1, Math.ceil(((optProgress.total - optProgress.done) * 1.5) / 60))} 分钟）`}
                    </p>
                  </>
                ) : (
                  <Loading label="正在逐组回测…" />
                )}
              </div>
              {optJobId && (
                <Button variant="danger" size="sm" onClick={cancelOptimize}>
                  取消
                </Button>
              )}
            </div>
          )}

          {optResult && (
            <div className="space-y-3">
              <div className="flex flex-wrap gap-3">
                <Badge tone="brand">评估 {optResult.evaluated} 组</Badge>
                <Badge tone={optResult.failed ? 'amber' : 'green'}>失败 {optResult.failed} 组</Badge>
                <Badge tone="violet">目标：{optResult.objective}</Badge>
              </div>
              {optResult.best && (
                <Alert tone="success" title="最优参数组合">
                  {JSON.stringify(optResult.best.params)} → 夏普 {fmtNum(optResult.best.sharpe, 2)}，
                  累计收益 {fmtRatioPct(optResult.best.return, 1, true)}，最大回撤 {fmtRatioPct(optResult.best.max_drawdown, 1)}
                </Alert>
              )}
              <DataTable<any>
                rows={optResult.results || []}
                rowKey={(r, i) => i}
                maxHeight="380px"
                columns={[
                  { key: 'p', label: '参数', render: (r) => <span className="num text-xs">{JSON.stringify(r.params)}</span> },
                  { key: 'sh', label: '夏普', align: 'right', render: (r) => <span className="num font-medium">{fmtNum(r.sharpe, 2)}</span> },
                  { key: 'so', label: '索提诺', align: 'right', render: (r) => <span className="num">{fmtNum(r.sortino, 2)}</span> },
                  { key: 'ca', label: '卡玛', align: 'right', render: (r) => <span className="num">{fmtNum(r.calmar, 2)}</span> },
                  { key: 'r', label: '累计收益', align: 'right', render: (r) => <span className={`num ${signClass(r.return)}`}>{fmtRatioPct(r.return, 1, true)}</span> },
                  { key: 'dd', label: '回撤', align: 'right', render: (r) => <span className="num text-emerald-600">{fmtRatioPct(r.max_drawdown, 1)}</span> },
                  { key: 't', label: '交易', align: 'right', render: (r) => <span className="num text-slate-500">{r.trades}</span> },
                ]}
              />
            </div>
          )}
        </div>
      </Modal>

      {/* ================= 多策略对比 ================= */}
      <Modal
        open={cmpOpen}
        onClose={() => setCmpOpen(false)}
        title="多策略对比"
        width="max-w-5xl"
        footer={
          <>
            <Button onClick={() => setCmpOpen(false)}>关闭</Button>
            <Button variant="primary" loading={cmpRunning} onClick={runCompare} icon={<GitCompare className="h-3.5 w-3.5" />}>
              开始对比
            </Button>
          </>
        }
      >
        <div className="space-y-4">
          <Alert tone="info" title="对比说明">
            多个策略使用<span className="font-medium">相同的时间区间、初始资金、成本与止损设置</span>，
            只有策略与参数不同，因此结果可直接横向比较。曲线会统一归一化到初始资金，便于叠加观察。
          </Alert>

          <div className="space-y-2">
            {cmpItems.map((it, i) => (
              <div key={i} className="grid gap-2 rounded-lg border border-slate-200 bg-slate-50/60 p-3 lg:grid-cols-[1fr_2fr_2fr_auto]">
                <Field label={`名称 ${i + 1}`}>
                  <Input
                    value={it.label}
                    onChange={(e) => setCmpItems((s) => s.map((x, j) => (j === i ? { ...x, label: e.target.value } : x)))}
                  />
                </Field>
                <Field label="策略">
                  <Select
                    value={it.strategy_key}
                    onChange={(e) => setCmpItems((s) => s.map((x, j) => (j === i ? { ...x, strategy_key: e.target.value } : x)))}
                  >
                    <optgroup label="内置策略">
                      {builtin.map((b) => (
                        <option key={b.key} value={b.key}>
                          [{b.category}] {b.name}
                        </option>
                      ))}
                    </optgroup>
                  </Select>
                </Field>
                <Field label="标的（逗号分隔）">
                  <Input
                    value={it.symbols}
                    onChange={(e) => setCmpItems((s) => s.map((x, j) => (j === i ? { ...x, symbols: e.target.value.toUpperCase() } : x)))}
                  />
                </Field>
                <div className="flex items-end">
                  <Button
                    variant="ghost"
                    size="sm"
                    disabled={cmpItems.length <= 2}
                    onClick={() => setCmpItems((s) => s.filter((_, j) => j !== i))}
                    icon={<Trash2 className="h-3.5 w-3.5" />}
                  />
                </div>
              </div>
            ))}
            <Button
              size="sm"
              disabled={cmpItems.length >= 6}
              onClick={() =>
                setCmpItems((s) => [
                  ...s,
                  { label: `策略 ${String.fromCharCode(65 + s.length)}`, strategy_key: 'trend_composite', symbols: 'SPY' },
                ])
              }
              icon={<Plus className="h-3.5 w-3.5" />}
            >
              添加策略（最多 6 个）
            </Button>
          </div>

          {cmpRunning && <Loading label="正在依次回测各策略…" />}

          {cmpResult && !cmpRunning && (
            <div className="space-y-4">
              <div className="flex flex-wrap gap-2">
                <Badge tone="brand">{cmpResult.labels.length} 个成功</Badge>
                {cmpResult.results.filter((r) => !r.ok).length > 0 && (
                  <Badge tone="amber">{cmpResult.results.filter((r) => !r.ok).length} 个失败</Badge>
                )}
              </div>

              <MultiEquityChart data={cmpResult.aligned} labels={cmpResult.labels} height={320} />

              <DataTable<any>
                rows={cmpResult.results}
                rowKey={(r, i) => `${r.label}-${i}`}
                maxHeight="300px"
                columns={[
                  {
                    key: 'lb',
                    label: '策略',
                    render: (r) => (
                      <div>
                        <div className="font-medium text-slate-800">{r.label}</div>
                        {r.strategy_name && <div className="text-[10px] text-slate-400">{r.strategy_name}</div>}
                      </div>
                    ),
                  },
                  {
                    key: 'ret',
                    label: '累计收益',
                    align: 'right',
                    render: (r) => (r.ok ? <span className={`num ${signClass(r.metrics.total_return)}`}>{fmtRatioPct(r.metrics.total_return, 1, true)}</span> : <span className="text-xs text-rose-500">{r.error}</span>),
                  },
                  { key: 'cagr', label: '年化', align: 'right', render: (r) => (r.ok ? <span className={`num ${signClass(r.metrics.cagr)}`}>{fmtRatioPct(r.metrics.cagr, 1, true)}</span> : '—') },
                  { key: 'sh', label: '夏普', align: 'right', render: (r) => (r.ok ? <span className="num font-medium">{fmtNum(r.metrics.sharpe, 2)}</span> : '—') },
                  { key: 'so', label: '索提诺', align: 'right', render: (r) => (r.ok ? <span className="num">{fmtNum(r.metrics.sortino, 2)}</span> : '—') },
                  { key: 'ca', label: '卡玛', align: 'right', render: (r) => (r.ok ? <span className="num">{fmtNum(r.metrics.calmar, 2)}</span> : '—') },
                  { key: 'dd', label: '最大回撤', align: 'right', render: (r) => (r.ok ? <span className="num text-emerald-600">{fmtRatioPct(r.metrics.max_drawdown, 1)}</span> : '—') },
                  { key: 'wr', label: '胜率', align: 'right', render: (r) => (r.ok ? <span className="num">{fmtRatioPct(r.metrics.win_rate, 1)}</span> : '—') },
                  { key: 'pf', label: '盈亏比', align: 'right', render: (r) => (r.ok ? <span className="num">{fmtNum(r.metrics.profit_factor, 2)}</span> : '—') },
                  { key: 't', label: '交易', align: 'right', render: (r) => (r.ok ? <span className="num text-slate-500">{r.metrics.trades}</span> : '—') },
                  { key: 'to', label: '换手', align: 'right', render: (r) => (r.ok ? <span className="num text-slate-500">{fmtNum(r.metrics.turnover, 1)}x</span> : '—') },
                ]}
              />

              <Alert tone="warn" title="怎么看对比结果">
                不要只挑收益最高的。优先看三项组合：<span className="font-medium">夏普/卡玛（风险调整后收益）</span>、
                <span className="font-medium">最大回撤（你能否扛住）</span>、
                <span className="font-medium">换手率（成本侵蚀）</span>。若某策略曲线明显更平滑且回撤更浅，
                即便收益略低，通常也更适合真实资金。
              </Alert>
            </div>
          )}
        </div>
      </Modal>
    </div>
  )
}
