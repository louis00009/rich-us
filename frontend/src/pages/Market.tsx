import { LineChart as LineIcon, Search, Star, TrendingUp } from 'lucide-react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import CandleChart from '../components/CandleChart'
import IntradayChart, { type IntraPoint } from '../components/IntradayChart'
import { PriceChart } from '../components/charts'
import NewsPanel from '../components/NewsPanel'
import QuickPicks from '../components/QuickPicks'
import CompanyIntel from '../components/CompanyIntel'
import { Badge, Button, Card, DataTable, Empty, Field, Input, KV, Loading, Select, Tabs, useToast } from '../components/ui'
import { api } from '../lib/api'
import { rtSubscribe } from '../lib/realtime'
import { fmtCompact, fmtNum, fmtRatioPct, getColorMode, signClass } from '../lib/format'
import type { DataSourceInfo, Quote } from '../lib/types'

const MAJORS = ['SPY', 'QQQ', 'IWM', 'DIA', 'SMH', 'TLT', 'GLD', 'USO', '^VIX', 'FXI', 'EEM', 'IBIT']
const RANGES = [
  { key: '6M', days: 180 },
  { key: '1Y', days: 365 },
  { key: '2Y', days: 730 },
  { key: '5Y', days: 1825 },
]
// 快速周期（用户语义：24H 分时 / 一周 / 一月 / 3 月 / 半年），点击自动适配 K 线周期
const QUICK_RANGES: { key: string; label: string; days: number; interval: string }[] = [
  { key: '1W', label: '1 周', days: 8, interval: '1h' },
  { key: '1M', label: '1 月', days: 31, interval: '1d' },
  { key: '3M', label: '3 月', days: 92, interval: '1d' },
  { key: '6M', label: '半年', days: 183, interval: '1d' },
  { key: '1Y', label: '1 年', days: 366, interval: '1d' },
]
const ALL_RANGES = [...QUICK_RANGES, ...RANGES]
const INTERVALS = [
  { key: '1d', label: '日线' },
  { key: '1wk', label: '周线' },
  { key: '1h', label: '小时线（近 180 天）' },
  { key: '30m', label: '30 分钟（近 60 天）' },
  { key: '15m', label: '15 分钟（近 60 天）' },
  { key: '5m', label: '5 分钟（近 60 天）' },
]

interface HistoryResp {
  symbol: string
  source: string
  source_requested?: string
  warning?: string
  realtime?: boolean
  interval: string
  count: number
  dates: string[]
  open: number[]
  high: number[]
  low: number[]
  close: number[]
  volume: number[]
}

interface IndicatorResp {
  symbol: string
  source: string
  dates: string[]
  series: Record<string, (number | null)[]>
}

interface SnapResp {
  symbol: string
  last_date: string
  price: number
  source: string
  returns: Record<string, number | null>
  ma: Record<string, number | null>
  dist: Record<string, number | null>
  levels: Record<string, number | null>
  indicators: Record<string, number | null>
  realtime?: { realtime: boolean; quote_source?: string; quote_ts?: string; note?: string }
}

interface IntradayResp {
  symbol: string
  source: string
  interval: string
  trade_date?: string
  is_today?: boolean
  prev_close: number
  last_price: number
  change_pct: number
  delayed: boolean
  count: number
  points: IntraPoint[]
}

type OverlayKey = 'ma' | 'sma' | 'bb' | 'all' | 'none'

// 均线配色（周期越长越冷色，一眼区分短中期与长期趋势）
const MA_STYLE: { key: string; label: string; color: string }[] = [
  { key: 'sma5', label: 'MA5', color: '#f97316' },
  { key: 'sma10', label: 'MA10', color: '#eab308' },
  { key: 'sma20', label: 'MA20', color: '#a855f7' },
  { key: 'sma60', label: 'MA60', color: '#14b8a6' },
  { key: 'sma50', label: 'SMA50', color: '#f59e0b' },
  { key: 'sma200', label: 'SMA200', color: '#0ea5e9' },
]

export default function Market() {
  const [sp, setSp] = useSearchParams()
  const toast = useToast()

  const [symbol, setSymbol] = useState(sp.get('symbol') || 'SPY')
  const [query, setQuery] = useState('')
  const symbolRef = useRef(symbol)
  const aliveRef = useRef(true)   // P2：重试定时器的卸载守卫
  useEffect(() => {
    aliveRef.current = true
    return () => { aliveRef.current = false }
  }, [])
  const retryRef = useRef(0)
  useEffect(() => {
    symbolRef.current = symbol
  }, [symbol])
  const [suggest, setSuggest] = useState<{ symbol: string; name: string; kind: string }[]>([])
  const [suggestIdx, setSuggestIdx] = useState(-1)   // T-116：键盘高亮项
  const [range, setRange] = useState('2Y')
  const [interval, setInterval] = useState('1d')
  const [overlay, setOverlay] = useState<OverlayKey>('sma')
  const [subChart, setSubChart] = useState('rsi')
  // 默认分时（最近 24H/最近交易日）；用户切换后记忆在 localStorage
    const [view, setView] = useState<'chart' | 'intel'>('chart')
const [chartType, setChartTypeRaw] = useState<'candle' | 'line' | 'intraday'>(() => {
    const saved = localStorage.getItem('qd_chart_type')
    return saved === 'candle' || saved === 'line' ? (saved as 'candle' | 'line') : 'intraday'
  })
  const setChartType = (v: 'candle' | 'line' | 'intraday') => {
    setChartTypeRaw(v)
    try {
      localStorage.setItem('qd_chart_type', v)
    } catch {
      /* noop */
    }
  }
  const [source, setSource] = useState('auto')
  const [dsInfo, setDsInfo] = useState<DataSourceInfo | null>(null)
  const [intra, setIntra] = useState<IntradayResp | null>(null)
  const [intraError, setIntraError] = useState('')
  const [hist, setHist] = useState<HistoryResp | null>(null)
  const [ind, setInd] = useState<IndicatorResp | null>(null)
  const [snap, setSnap] = useState<SnapResp | null>(null)
  const [watch, setWatch] = useState<Quote[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    api.get<{ items: Quote[] }>(`/market/quote?symbols=${MAJORS.join(',')}`).then((r) => setWatch(r.items)).catch(() => {})
    const loadDs = () => api.get<DataSourceInfo>('/market/data-source').then(setDsInfo).catch(() => {})
    loadDs()
    const t = window.setInterval(loadDs, 60_000)   // 数据源状态/失败原因每分钟刷新
    return () => window.clearInterval(t)
  }, [])

  // 搜索建议：250ms 防抖，仅用于下拉建议；**不再自动提交 symbol**。
  // 旧实现把输入框既当搜索框又当标的提交器：输入 "0700.HK" 的过程中
  // "0700" 就会在 500ms 后被提交 → 触发整页行情重载 → 请求风暴 → 越用越慢。
  // 现在 symbol 只在 回车 / 点建议 / 点快速标签 时变更。
  useEffect(() => {
    if (!query.trim()) {
      setSuggest([])
      return
    }
    const t = setTimeout(() => {
      api.get<{ items: any[] }>(`/market/search?q=${encodeURIComponent(query)}&limit=8`).then((r) => {
        setSuggest(r.items)
        setSuggestIdx(-1)   // 新一批建议重置键盘高亮
      }).catch(() => {})
    }, 250)
    return () => clearTimeout(t)
  }, [query])

  const commitSymbol = (v: string) => {
    const raw = v.trim().toUpperCase()
    if (raw) setSymbol(raw)
    setQuery('')
    setSuggest([])
    setSuggestIdx(-1)
  }

  // 快速周期：点击后自动适配区间 + K 线周期；若当前是分时则切到折线
  const applyQuick = (key: string) => {
    const r = QUICK_RANGES.find((q) => q.key === key)
    if (!r) return
    setRange(r.key)
    setInterval(r.interval)
    setChartType(chartType === 'intraday' ? 'line' : chartType)
  }

  // 标的级内存缓存：切回看过的标的瞬间渲染旧数据，后台再刷新（缓存命中 0.04s，未命中 2~5s）
  const symCache = useRef(new Map<string, { hist: HistoryResp; ind: IndicatorResp; snap: SnapResp }>())

  // P1-12：请求竞态守卫 —— 快速切换标的时，慢响应（2~5s）会比快响应后到，
  // 旧实现直接 setState 会把 A 标的的 K 线/指标渲染到 B 标的标题下（还挂着 LIVE 角标），
  // 极易据错误数据下单。现在每个请求持序号，过期响应一律丢弃。
  const seqRef = useRef(0)

  const load = useCallback(async () => {
    const seq = ++seqRef.current
    // 立即上屏该标的的上次数据（如有），消除白屏等待
    const cached = symCache.current.get(symbol)
    if (cached) {
      setHist(cached.hist)
      setInd(cached.ind)
      setSnap(cached.snap)
      setLoading(false)
    } else {
      setLoading(true)
    }
    const days = ALL_RANGES.find((r) => r.key === range)?.days ?? 730
    const start = new Date(Date.now() - days * 864e5).toISOString().slice(0, 10)
    const qs = `symbol=${encodeURIComponent(symbol)}&start=${start}&interval=${interval}&source=${source}`
    const results = await Promise.allSettled([
      api.get<HistoryResp>(`/market/history?${qs}`),
      api.get<IndicatorResp>(`/market/indicators?symbol=${encodeURIComponent(symbol)}&list=rsi,macd,adx,bb,sma5,sma10,sma20,sma60,sma50,sma200,vol`),
      api.get<SnapResp>(`/market/snapshot?symbol=${encodeURIComponent(symbol)}`),
    ])
    if (seq !== seqRef.current) return   // 已有更新的请求 → 本响应整体作废
    if (results[0].status === 'fulfilled') {
      setHist(results[0].value)
      retryRef.current = 0
      if (results[0].value.warning) toast('warning', results[0].value.warning)
    } else {
      if (!cached) setHist(null)
      toast('error', `获取 ${symbol} 行情失败`)
      // 免费源偶发限流（Yahoo 429 等）：2.5 秒后针对同一标的静默补拉一次
      const sym = symbol
      const tries = retryRef.current
      retryRef.current = tries + 1
      if (tries < 1) {
        // P2：重试定时器带卸载守卫，页面已离开时不再触发任何 setState
        setTimeout(() => {
          if (aliveRef.current && symbolRef.current === sym) load()
        }, 2500)
      }
    }
    if (results[1].status === 'fulfilled') setInd(results[1].value)
    if (results[2].status === 'fulfilled') setSnap(results[2].value)
    // 成功后写入标的级缓存（LRU 上限 30 个标的）
    if (results[0].status === 'fulfilled' && results[1].status === 'fulfilled' && results[2].status === 'fulfilled') {
      const m = symCache.current
      m.set(symbol, { hist: results[0].value, ind: results[1].value, snap: results[2].value })
      if (m.size > 30) {
        const oldest = m.keys().next().value
        if (oldest !== undefined) m.delete(oldest)
      }
    }
    setLoading(false)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [symbol, range, interval, source])

  useEffect(() => {
    load()
  }, [load])

  // 分时模式：加载当日 1m 数据并 30s 自动刷新（切换标的/图表类型时重置）
  const intraSeqRef = useRef(0)
  const loadIntraday = useCallback(async () => {
    const seq = ++intraSeqRef.current
    try {
      const r = await api.get<IntradayResp>(`/market/intraday?symbol=${encodeURIComponent(symbol)}`, 30_000)
      if (seq !== intraSeqRef.current) return   // P1-12：过期分时响应作废
      setIntra(r)
      setIntraError('')
    } catch (e: any) {
      if (seq !== intraSeqRef.current) return
      setIntra(null)
      setIntraError(e?.message || '分时数据加载失败')
    }
  }, [symbol])

  useEffect(() => {
    if (chartType !== 'intraday') return
    loadIntraday()
    const t = window.setInterval(loadIntraday, 30_000)
    return () => window.clearInterval(t)
  }, [chartType, loadIntraday])

  // ===== WebSocket 实时推送（T-106，秒级）=====
  // ① 当前标的报价 → 顶卡价格实时跳动 + 分时图实时延伸
  const [liveQuote, setLiveQuote] = useState<Quote | null>(null)
  const symbolRef2 = useRef(symbol)
  useEffect(() => {
    symbolRef2.current = symbol
  }, [symbol])

  useEffect(() => {
    if (!symbol) return
    return rtSubscribe([`quotes:${symbol}`], (m) => {
      const q = (m.data || []).find((r: Quote) => r.symbol === symbolRef2.current)
      if (!q) return
      setLiveQuote(q)
      // 分时图实时延伸：同一分钟替换尾点，跨分钟追加新点
      setIntra((prev) => {
        if (!prev || prev.symbol !== symbolRef2.current) return prev
        const pts = [...prev.points]
        if (!pts.length) return prev
        const t = String(q.rt_t || pts[pts.length - 1].t)
        const last = pts[pts.length - 1]
        const np = { t, price: q.price, avg: last.avg, vol: Number(q.volume) || last.vol }
        if (last.t === t) pts[pts.length - 1] = np
        else pts.push(np)
        return { ...prev, points: pts.slice(-420), last_price: q.price, change_pct: q.change_pct }
      })
    })
  }, [symbol])

  useEffect(() => {
    const next = new URLSearchParams(sp)
    next.set('symbol', symbol)
    setSp(next, { replace: true })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [symbol])

  const overlays = useMemo(() => {
    if (!ind || !hist) return []
    const pick = (key: string) => {
      const s = ind.series[key]
      if (!s) return []
      const byDate = new Map(ind.dates.map((d, i) => [d, s[i]]))
      return hist.dates.map((d) => byDate.get(d) ?? null)
    }
    const maLines = (keys: string[]) =>
      keys
        .map((k) => {
          const st = MA_STYLE.find((m) => m.key === k)
          if (!st) return null
          return { name: st.label, data: pick(k), color: st.color }
        })
        .filter(Boolean) as { name: string; data: (number | null)[]; color: string }[]
    const bbLines = () => [
      { name: '布林上轨', data: pick('bb_upper'), color: '#94a3b8', dashed: true },
      { name: '布林中轨', data: pick('bb_mid'), color: '#a78bfa' },
      { name: '布林下轨', data: pick('bb_lower'), color: '#94a3b8', dashed: true },
    ]
    if (overlay === 'ma') return maLines(['sma5', 'sma10', 'sma20', 'sma60'])
    if (overlay === 'sma') return maLines(['sma50', 'sma200'])
    if (overlay === 'bb') return bbLines()
    if (overlay === 'all') return [...maLines(['sma5', 'sma10', 'sma20', 'sma60']), ...maLines(['sma50', 'sma200']), ...bbLines()]
    return []
  }, [ind, hist, overlay])

  const subSeries = useMemo(() => {
    if (!ind || !hist) return { data: [] as (number | null)[], extra: [] as any[], label: '', unit: '' }
    const pick = (key: string) => {
      const s = ind.series[key]
      if (!s) return []
      const byDate = new Map(ind.dates.map((d, i) => [d, s[i]]))
      return hist.dates.map((d) => byDate.get(d) ?? null)
    }
    if (subChart === 'rsi') return { data: pick('rsi'), extra: [], label: 'RSI(14)', unit: '' }
    if (subChart === 'macd')
      return {
        data: pick('macd_hist'),
        extra: [
          { name: 'MACD', data: pick('macd'), color: '#4f46e5' },
          { name: '信号线', data: pick('macd_signal'), color: '#f59e0b' },
        ],
        label: 'MACD 柱',
        unit: '',
      }
    if (subChart === 'adx')
      return {
        data: pick('adx'),
        extra: [
          { name: '+DI', data: pick('plus_di'), color: '#e11d48' },
          { name: '-DI', data: pick('minus_di'), color: '#059669' },
        ],
        label: 'ADX(14)',
        unit: '',
      }
    return { data: pick('vol'), extra: [], label: '已实现波动率 %', unit: '' }
  }, [ind, hist, subChart])

  const levels = useMemo(() => {
    if (!snap) return []
    const sup = (snap.levels as any)?.支撑 ?? []
    const res = (snap.levels as any)?.阻力 ?? []
    return [
      ...sup.slice(0, 2).map((v: number, i: number) => ({ value: v, label: `支撑${i + 1}`, color: '#059669' })),
      ...res.slice(0, 2).map((v: number, i: number) => ({ value: v, label: `阻力${i + 1}`, color: '#e11d48' })),
    ]
  }, [snap])

  const quote = watch.find((w) => w.symbol === symbol)
  // WebSocket 实时报价优先（秒级），轮询报价兜底
  const shownQuote = liveQuote && liveQuote.symbol === symbol ? liveQuote : quote

  // 数据源最近失败原因（诊断可见化：哪个源在限流/挂掉，一眼看到）
  const srcWarn = useMemo(() => {
    const errs = dsInfo?.recent_errors
    if (!errs || Object.keys(errs).length === 0) return ''
    return Object.entries(errs)
      .slice(0, 2)
      .map(([k, v]) => `${k}: ${v}`)
      .join(' ｜ ')
  }, [dsInfo])

  return (
    <div className="space-y-5">
      {/* 快速选择：关注 + 持仓 一点即切 */}
      <QuickPicks current={symbol} onPick={commitSymbol} />

      {/* 搜索栏 */}
      <Card>
        <div className="flex flex-wrap items-end gap-3">
          <div className="relative min-w-[220px] flex-1">
            <label className="lbl">标的代码</label>
            <div className="relative">
              <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
              <Input
                className="pl-9"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                onKeyDown={(e) => {
                  // T-116：搜索建议键盘导航 —— ↓↑ 移动高亮、Enter 选中高亮项（无高亮则提交原文）、Esc 关闭
                  if (e.key === 'ArrowDown' && suggest.length) {
                    e.preventDefault()
                    setSuggestIdx((i) => Math.min(i + 1, suggest.length - 1))
                    return
                  }
                  if (e.key === 'ArrowUp' && suggest.length) {
                    e.preventDefault()
                    setSuggestIdx((i) => Math.max(i - 1, 0))
                    return
                  }
                  if (e.key === 'Enter') {
                    if (suggest.length && suggestIdx >= 0 && suggestIdx < suggest.length) {
                      commitSymbol(suggest[suggestIdx].symbol)
                    } else {
                      commitSymbol(query || symbol)
                    }
                    return
                  }
                  if (e.key === 'Escape') {
                    setQuery('')
                    setSuggest([])
                    setSuggestIdx(-1)
                  }
                }}
                onBlur={() => setTimeout(() => { setSuggest([]); setSuggestIdx(-1) }, 150)}
                placeholder="搜索代码或名称，回车切换（如 NVDA / 腾讯）"
              />
              <span className="absolute right-2.5 top-1/2 -translate-y-1/2 rounded bg-brand-50 px-1.5 py-0.5 text-[10px] font-semibold text-brand-700">
                {symbol}
              </span>
            </div>
            {suggest.length > 0 && (
              <div className="absolute z-30 mt-1 max-h-72 w-full overflow-y-auto rounded-lg border border-slate-200 bg-white py-1 shadow-pop" role="listbox">
                {suggest.map((s, i) => (
                  <button
                    key={s.symbol}
                    onClick={() => commitSymbol(s.symbol)}
                    onMouseEnter={() => setSuggestIdx(i)}
                    role="option"
                    aria-selected={i === suggestIdx}
                    className={`flex w-full items-center justify-between px-3 py-2 text-left ${
                      i === suggestIdx ? 'bg-brand-50' : 'hover:bg-slate-50'
                    }`}
                  >
                    <span className="text-sm font-medium text-slate-700">{s.symbol}</span>
                    <span className="ml-3 flex-1 truncate text-xs text-slate-400">{s.name}</span>
                    <Badge tone="slate">{s.kind}</Badge>
                  </button>
                ))}
              </div>
            )}
          </div>

          <Field label="周期区间">
            <Select value={range} onChange={(e) => setRange(e.target.value)} className="w-32">
              {RANGES.map((r) => (
                <option key={r.key} value={r.key}>
                  {r.key}
                </option>
              ))}
            </Select>
          </Field>

          <Field label="K 线周期">
            <Select value={interval} onChange={(e) => setInterval(e.target.value)} className="w-44">
              {INTERVALS.map((i) => (
                <option key={i.key} value={i.key}>
                  {i.label}
                </option>
              ))}
            </Select>
          </Field>

          <Field label="均线叠加">
            <Select value={overlay} onChange={(e) => setOverlay(e.target.value as OverlayKey)} className="w-44">
              <option value="ma">短线均线 MA5/10/20/60</option>
              <option value="sma">长期均线 SMA50/200</option>
              <option value="bb">布林带</option>
              <option value="all">全部叠加</option>
              <option value="none">不叠加</option>
            </Select>
          </Field>

          <Field label="数据源" hint={dsInfo && dsInfo.providers?.ibkr?.available ? 'IBKR 已连接' : 'IBKR 未连接，将自动降级'}>
            <Select value={source} onChange={(e) => setSource(e.target.value)} className="w-40">
              <option value="auto">自动（推荐）</option>
              <option value="ibkr">IBKR 优先</option>
            </Select>
          </Field>

          <Button variant="primary" onClick={load} loading={loading} icon={<TrendingUp className="h-3.5 w-3.5" />}>
            加载
          </Button>
        </div>

        {hist?.warning && (
          <div className="mt-3 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
            ⚠️ {hist.warning}
          </div>
        )}
        {hist?.source === 'synthetic' && (
          <div className="mt-3 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
            ⚠️ 当前显示的是<span className="font-medium">合成数据</span>（非真实行情）。说明外部数据源均不可用，仅供界面演示。
          </div>
        )}
        {srcWarn && (
          <div className="mt-3 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-[11px] text-slate-500">
            数据源诊断：{srcWarn}（已自动降级/重试；若频繁出现可切换数据源或稍后再试）
          </div>
        )}
      </Card>

      <div className="grid gap-5 xl:grid-cols-4">
        {/* 新闻 / 公告面板 */}
        <div className="space-y-5 xl:col-span-1 xl:order-2">
          <NewsPanel symbol={symbol} />
        </div>

        {/* 图表区 */}
        <div className="space-y-5 xl:col-span-3 xl:order-1">
          {loading && !hist ? (
            <Card>
              <Loading label="正在获取行情…" />
            </Card>
          ) : hist ? (
            view === 'intel' ? (
              <CompanyIntel symbol={symbol} />
            ) : (
            <>
              <Card
                title={
                  <span className="flex items-center gap-2">
                    {hist.symbol}
                    {shownQuote && (
                      <span className={`num text-base ${signClass(shownQuote.change_pct)}`}>
                        {fmtNum(shownQuote.price, 2)}
                        <span className="ml-2 text-xs">
                          {shownQuote.change > 0 ? '+' : ''}
                          {fmtNum(shownQuote.change, 2)} ({shownQuote.change_pct > 0 ? '+' : ''}
                          {shownQuote.change_pct.toFixed(2)}%)
                        </span>
                        <span className="ml-2 inline-flex items-center gap-1 text-[10px] text-emerald-600">
                          <span className="inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-emerald-500" />
                          LIVE
                        </span>
                      </span>
                    )}
                  </span>
                }
                subtitle={
                  chartType === 'intraday' && intra
                    ? `${intra.is_today ? '当日' : `交易日 ${intra.trade_date || ''}`}分时 ｜ ${intra.count} 根 1 分钟 ｜ 数据源 ${intra.source}${intra.delayed ? '（约 15 分钟延迟）' : '（实时）'}`
                    : `${hist.count} 根 bar ｜ 数据源 ${hist.source}${hist.realtime ? '（末根为实时价）' : ''} ｜ ${hist.dates[0]?.slice(0, 10)} ~ ${hist.dates[hist.dates.length - 1]?.slice(0, 10)}`
                }
                actions={
                  <div className="flex items-center gap-2">
                    <Badge tone={hist.source === 'synthetic' ? 'amber' : hist.source === 'ibkr' ? 'green' : 'slate'}>
                      {hist.source}
                    </Badge>
                    <Tabs
                      value={view}
                      onChange={(k) => setView(k as 'chart' | 'intel')}
                      tabs={[
                        { key: 'chart', label: '图表' },
                        { key: 'intel', label: '公司情报' },
                      ]}
                    />
                    <span className="mx-1 h-5 w-px bg-slate-200" />
                    <Tabs
                      value={chartType}
                      onChange={(k) => setChartType(k as 'candle' | 'line' | 'intraday')}
                      tabs={[
                        { key: 'candle', label: 'K 线' },
                        { key: 'intraday', label: '分时' },
                        { key: 'line', label: '折线' },
                      ]}
                    />
                  </div>
                }
              >
                {/* 快速周期选择框：分时(24H) / 一周 / 一月 / 3 月 / 半年 / 1 年 */}
                <div className="mb-3 flex flex-wrap items-center gap-1.5">
                  <span className="mr-1 text-[11px] text-slate-400">快速周期</span>
                  <button
                    onClick={() => setChartType('intraday')}
                    className={`rounded-lg border px-2.5 py-1 text-xs transition-colors ${
                      chartType === 'intraday'
                        ? 'border-brand-400 bg-brand-50 font-semibold text-brand-700'
                        : 'border-slate-200 text-slate-600 hover:border-brand-300 hover:bg-slate-50'
                    }`}
                  >
                    分时 (24H)
                  </button>
                  {QUICK_RANGES.map((q) => (
                    <button
                      key={q.key}
                      onClick={() => applyQuick(q.key)}
                      className={`rounded-lg border px-2.5 py-1 text-xs transition-colors ${
                        chartType !== 'intraday' && range === q.key
                          ? 'border-brand-400 bg-brand-50 font-semibold text-brand-700'
                          : 'border-slate-200 text-slate-600 hover:border-brand-300 hover:bg-slate-50'
                      }`}
                    >
                      {q.label}
                    </button>
                  ))}
                  <span className="ml-2 hidden text-[11px] text-slate-300 sm:inline">
                    1 周/1 月含小时线；更细周期与区间用上方「周期区间 / K 线周期」自定义
                  </span>
                </div>
                {chartType === 'candle' ? (
                  <CandleChart
                    dates={hist.dates}
                    open={hist.open}
                    high={hist.high}
                    low={hist.low}
                    close={hist.close}
                    volume={hist.volume}
                    overlays={overlays}
                    levels={levels}
                    height={430}
                    showVolume
                    colorMode={getColorMode()}
                  />
                ) : chartType === 'intraday' ? (
                  intra ? (
                    <>
                      <IntradayChart
                        points={intra.points}
                        prevClose={intra.prev_close}
                        height={430}
                        colorMode={getColorMode()}
                      />
                      {intra.is_today === false && (
                        <div className="mt-2 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-xs text-slate-600">
                          当前非交易时段（或数据未更新），展示的是最近交易日 <b>{intra.trade_date}</b> 的分时走势。
                        </div>
                      )}
                      {intra.delayed && (
                        <div className="mt-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
                          ⚠️ 当前分时来自免费源（{intra.source}），日内数据约有 15 分钟延迟；接入 IBKR 行情后自动切换为实时。
                        </div>
                      )}
                    </>
                  ) : intraError ? (
                    <div className="py-16 text-center text-sm text-slate-400">
                      {intraError}
                      <div className="mt-1 text-[11px] text-slate-300">30 秒后自动重试；也可切换数据源或稍后再试</div>
                    </div>
                  ) : (
                    <div className="py-16 text-center text-sm text-slate-400">正在加载分时…（30 秒自动刷新）</div>
                  )
                ) : (
                  <PriceChart dates={hist.dates} close={hist.close} overlays={overlays} levels={levels} height={430} />
                )}
              </Card>
              {view === 'chart' && (
              <>
              <Card
                title="技术指标"
                actions={
                  <Tabs
                    value={subChart}
                    onChange={setSubChart}
                    tabs={[
                      { key: 'rsi', label: 'RSI' },
                      { key: 'macd', label: 'MACD' },
                      { key: 'adx', label: 'ADX' },
                      { key: 'vol', label: '波动率' },
                    ]}
                  />
                }
              >
                <PriceChart
                  dates={hist.dates}
                  close={subSeries.data as number[]}
                  overlays={subSeries.extra}
                  height={190}
                />
              </Card>

              <Card title="成交量" subtitle="用于识别放量突破与缩量整理">
                <PriceChart dates={hist.dates} close={hist.volume} height={150} />
              </Card>
              </>
              )}
            </>
            )
          ) : (
            <Card>
              <Empty icon={<LineIcon className="h-8 w-8" />} title="未获取到行情" desc="请检查标的代码，或稍后重试" />
            </Card>
          )}
        </div>

        {/* 侧栏 */}
        <div className="space-y-5">
          <Card
            title="关键价位与结构"
            subtitle={
              <span className="flex flex-wrap items-center gap-2">
                <span>{snap ? `截至 ${snap.last_date}` : ''}</span>
                {snap?.realtime?.realtime ? (
                  <span
                    className="inline-flex items-center gap-1 rounded bg-emerald-50 px-1.5 py-0.5 text-[10px] font-semibold text-emerald-700"
                    title={`报价来源 ${snap.realtime.quote_source || '-'} · ${snap.realtime.quote_ts || ''}`}
                  >
                    <span className="inline-block h-1.5 w-1.5 rounded-full bg-emerald-500" />
                    实时价 · {snap.realtime.quote_source}
                  </span>
                ) : (
                  <span className="rounded bg-slate-100 px-1.5 py-0.5 text-[10px] text-slate-500" title={snap?.realtime?.note || ''}>
                    日线口径
                  </span>
                )}
              </span>
            }
          >
            {snap ? (
              <div className="space-y-3">
                <KV
                  cols={1}
                  items={[
                    { k: '现价', v: fmtNum(snap.price, 2) },
                    { k: '52 周最高', v: fmtNum(snap.levels?.high_52w, 2) },
                    { k: '52 周最低', v: fmtNum(snap.levels?.low_52w, 2) },
                    { k: '距 52 周高点', v: <span className={signClass(snap.dist?.to_52w_high ?? 0)}>{fmtRatioPct((snap.dist?.to_52w_high ?? 0) / 100, 2, true)}</span> },
                    { k: 'SMA50', v: fmtNum(snap.ma?.sma50, 2) },
                    { k: 'SMA200', v: fmtNum(snap.ma?.sma200, 2) },
                    { k: 'ATR(14)', v: fmtNum(snap.indicators?.atr14, 2) },
                    { k: 'ATR 占比', v: `${fmtNum(snap.indicators?.atr_pct, 2)}%` },
                    { k: '枢轴价', v: fmtNum(snap.levels?.pivot, 2) },
                  ]}
                />
              </div>
            ) : (
              <Loading />
            )}
          </Card>

          <Card title="区间收益" subtitle="用于判断动量强弱">
            {snap ? (
              <div className="space-y-2">
                {[
                  ['1 日', snap.returns?.['1d']],
                  ['5 日', snap.returns?.['5d']],
                  ['1 月', snap.returns?.['1m']],
                  ['3 月', snap.returns?.['3m']],
                  ['6 月', snap.returns?.['6m']],
                  ['1 年', snap.returns?.['1y']],
                  ['年初至今', snap.returns?.ytd],
                ].map(([label, v]) => (
                  <div key={label as string} className="flex items-center justify-between border-b border-dashed border-slate-100 pb-1.5">
                    <span className="text-xs text-slate-500">{label}</span>
                    <span className={`num text-sm font-medium ${signClass(v as number)}`}>
                      {v === null || v === undefined ? '—' : `${Number(v) > 0 ? '+' : ''}${Number(v).toFixed(2)}%`}
                    </span>
                  </div>
                ))}
              </div>
            ) : (
              <Loading />
            )}
          </Card>

          <Card title="指标读数" subtitle={snap?.realtime?.realtime ? '已融合实时价计算' : ''}>
            {snap ? (
              <div className="space-y-2">
                {[
                  ['RSI(14)', snap.indicators?.rsi14, 2],
                  ['MACD 柱', snap.indicators?.macd_hist, 4],
                  ['ADX(14)', snap.indicators?.adx14, 1],
                  ['+DI', snap.indicators?.plus_di, 1],
                  ['-DI', snap.indicators?.minus_di, 1],
                  ['布林 %B', snap.indicators?.bb_pctb, 3],
                  ['量比', snap.indicators?.vol_ratio, 2],
                  ['CMF(20)', snap.indicators?.cmf20, 3],
                  ['Z 分数', snap.indicators?.zscore20, 2],
                  ['效率比', snap.indicators?.efficiency_ratio, 3],
                  ['Hurst', snap.indicators?.hurst, 3],
                ].map(([label, v, d]) => (
                  <div key={label as string} className="flex items-center justify-between border-b border-dashed border-slate-100 pb-1.5">
                    <span className="text-xs text-slate-500">{label}</span>
                    <span className="num text-sm font-medium text-slate-700">
                      {v === null || v === undefined ? '—' : Number(v).toFixed(d as number)}
                    </span>
                  </div>
                ))}
              </div>
            ) : (
              <Loading />
            )}
          </Card>
        </div>
      </div>

      <Card
        title={<span className="flex items-center gap-2"><Star className="h-4 w-4 text-amber-400" />重点关注池</span>}
        subtitle="点击切换标的"
        dense
      >
        <DataTable<Quote>
          rows={watch}
          rowKey={(r) => r.symbol}
          onRowClick={(r) => {
            setSymbol(r.symbol)
            setQuery('')
          }}
          columns={[
            { key: 's', label: '标的', render: (r) => <span className="font-medium text-slate-800">{r.symbol}</span> },
            { key: 'p', label: '现价', align: 'right', render: (r) => <span className="num">{fmtNum(r.price, 2)}</span> },
            {
              key: 'c',
              label: '涨跌',
              align: 'right',
              render: (r) => (
                <span className={`num ${signClass(r.change)}`}>
                  {r.change > 0 ? '+' : ''}
                  {fmtNum(r.change, 2)}
                </span>
              ),
            },
            {
              key: 'cp',
              label: '涨跌幅',
              align: 'right',
              render: (r) => (
                <span className={`num ${signClass(r.change_pct)}`}>
                  {r.change_pct > 0 ? '+' : ''}
                  {r.change_pct.toFixed(2)}%
                </span>
              ),
            },
            { key: 'h', label: '最高', align: 'right', render: (r) => <span className="num text-slate-500">{fmtNum(r.day_high, 2)}</span> },
            { key: 'l', label: '最低', align: 'right', render: (r) => <span className="num text-slate-500">{fmtNum(r.day_low, 2)}</span> },
            { key: 'v', label: '成交量', align: 'right', render: (r) => <span className="num text-slate-500">{fmtCompact(r.volume)}</span> },
            { key: 'src', label: '来源', align: 'center', render: (r) => <Badge tone={r.source === 'synthetic' ? 'amber' : 'slate'}>{r.source}</Badge> },
          ]}
        />
      </Card>
    </div>
  )
}
