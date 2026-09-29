import { LineChart as LineIcon, Star } from 'lucide-react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import CandleChart from '../components/CandleChart'
import IntradayChart from '../components/IntradayChart'
import { PriceChart } from '../components/charts'
import NewsPanel from '../components/NewsPanel'
import QuickPicks from '../components/QuickPicks'
import CompanyIntel from '../components/CompanyIntel'
import AIAssist from '../components/AIAssist'
import { Badge, Card, Empty, KV, Loading, Tabs, useToast } from '../components/ui'
import { SearchPanel, type SuggestItem } from '../components/market/SearchPanel'
import { WatchPool } from '../components/market/WatchPool'
import { ChartPanel } from '../components/market/ChartPanel'
import { SidePanel } from '../components/market/SidePanel'
import { ALL_RANGES, MAJORS, MA_STYLE, QUICK_RANGES } from '../components/market/constants'
import type { HistoryResp, IndicatorResp, IntradayResp, OverlayKey, SnapResp } from '../components/market/types'
import { api } from '../lib/api'
import { rtSubscribe } from '../lib/realtime'
import { notifyWatchlistChanged } from '../lib/watchlistBus'
import { fmtNum, fmtRatioPct, getColorMode, signClass } from '../lib/format'
import type { DataSourceInfo, Quote } from '../lib/types'

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
  // 下方「我的收藏」池：来自关注列表（收藏后实时更新），空列表回退主流 ETF
  const [watch, setWatch] = useState<Quote[]>([])
  const [watchNames, setWatchNames] = useState<Record<string, string>>({})
  const [watchedSet, setWatchedSet] = useState<Set<string>>(new Set())
  const [favBusy, setFavBusy] = useState(false)
  const [loading, setLoading] = useState(true)

  const loadWatchQuotes = useCallback(async () => {
    try {
      const wl = await api.get<{ items: { symbol: string; name_cn?: string }[] }>('/watchlist')
      const favs = wl.items.map((i) => i.symbol)
      setWatchNames(Object.fromEntries(wl.items.map((i) => [i.symbol, i.name_cn || ''])))
      const syms = favs.length ? favs : MAJORS
      const r = await api.get<{ items: Quote[] }>(`/market/quote?symbols=${syms.join(',')}`)
      setWatch(r.items)
    } catch {
      /* 静默：收藏池加载失败不影响主行情 */
    }
  }, [])

  const loadWatched = useCallback(() => {
    api.get<{ items: { symbol: string }[] }>('/watchlist')
      .then((r) => setWatchedSet(new Set(r.items.map((i) => i.symbol))))
      .catch(() => {})
  }, [])

  // 当前标的 收藏/取消收藏（写入后端关注列表，同步刷新收藏池）
  const toggleWatched = async () => {
    if (favBusy || !symbol) return
    setFavBusy(true)
    try {
      if (watchedSet.has(symbol)) {
        await api.del(`/watchlist/${encodeURIComponent(symbol)}`)
        toast('info', `已取消收藏 ${symbol}`)
        setWatchedSet((s) => {
          const n = new Set(s)
          n.delete(symbol)
          return n
        })
      } else {
        await api.post('/watchlist', { symbol })
        toast('info', `已收藏 ${symbol} 到我的关注`)
        setWatchedSet((s) => new Set(s).add(symbol))
      }
      loadWatchQuotes()
      // 广播给 QuickPicks / WatchBar / 榜单页：关注列表已变化，即时刷新
      notifyWatchlistChanged()
    } catch (e: any) {
      toast('error', e?.message || '收藏操作失败')
    } finally {
      setFavBusy(false)
    }
  }

  // 搜索建议项的快捷收藏：不切换当前标的，直接加入/移出关注列表
  const toggleSuggestFav = async (sym: string) => {
    if (favBusy || !sym) return
    setFavBusy(true)
    try {
      if (watchedSet.has(sym)) {
        await api.del(`/watchlist/${encodeURIComponent(sym)}`)
        toast('info', `已取消收藏 ${sym}`)
        setWatchedSet((s) => {
          const n = new Set(s)
          n.delete(sym)
          return n
        })
      } else {
        await api.post('/watchlist', { symbol: sym })
        toast('info', `已收藏 ${sym} 到我的关注`)
        setWatchedSet((s) => new Set(s).add(sym))
      }
      loadWatchQuotes()
      notifyWatchlistChanged()
    } catch (e: any) {
      toast('error', e?.message || '收藏操作失败')
    } finally {
      setFavBusy(false)
    }
  }

  useEffect(() => {
    loadWatchQuotes()
    loadWatched()
    const loadDs = () => api.get<DataSourceInfo>('/market/data-source').then(setDsInfo).catch(() => {})
    loadDs()
    const t = window.setInterval(loadDs, 60_000)   // 数据源状态/失败原因每分钟刷新
    return () => window.clearInterval(t)
  }, [loadWatchQuotes, loadWatched])

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

      {/* 搜索栏（已抽到 components/market/SearchPanel.tsx，铁律 9） */}
      <SearchPanel
        query={query}
        setQuery={setQuery}
        symbol={symbol}
        suggest={suggest}
        setSuggest={setSuggest}
        suggestIdx={suggestIdx}
        setSuggestIdx={setSuggestIdx}
        watchedSet={watchedSet}
        commitSymbol={commitSymbol}
        toggleSuggestFav={toggleSuggestFav}
        range={range}
        setRange={setRange}
        interval={interval}
        setInterval={setInterval}
        overlay={overlay}
        setOverlay={setOverlay}
        source={source}
        setSource={setSource}
        dsInfo={dsInfo}
        hist={hist}
        srcWarn={srcWarn}
        onLoad={load}
        loading={loading}
      />

      <div className="grid gap-5 xl:grid-cols-4">
        {/* 新闻 / 公告面板 */}
        <div className="space-y-5 xl:col-span-1 xl:order-2">
          <NewsPanel symbol={symbol} />
        </div>

        {/* 图表区（已抽到 components/market/ChartPanel.tsx，铁律 9） */}
        <ChartPanel
          loading={loading}
          hist={hist}
          view={view}
          setView={setView}
          chartType={chartType}
          setChartType={setChartType}
          intra={intra}
          intraError={intraError}
          overlays={overlays}
          levels={levels}
          subChart={subChart}
          setSubChart={setSubChart}
          subSeries={subSeries}
          symbol={symbol}
          watchedSet={watchedSet}
          favBusy={favBusy}
          toggleWatched={toggleWatched}
          shownQuote={shownQuote}
          range={range}
          applyQuick={applyQuick}
        />

        {/* 侧栏（已抽到 components/market/SidePanel.tsx，铁律 9） */}
        <SidePanel snap={snap} symbol={symbol} />
      </div>

      {/* 我的收藏（已抽到 components/market/WatchPool.tsx，铁律 9） */}
      <WatchPool
        watch={watch}
        watchedSet={watchedSet}
        watchNames={watchNames}
        onRefresh={loadWatchQuotes}
        onPick={(sym) => {
          setSymbol(sym)
          setQuery('')
        }}
      />
    </div>
  )
}
