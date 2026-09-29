import { ListFilter, MessageSquare, RefreshCw, Sliders, Star } from 'lucide-react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import RankingFilters, {
  EMPTY_FILTERS,
  matchPreset,
  RankingFiltersValue,
} from '../components/rankings/RankingFilters'
import RankingsTable, { RankRow } from '../components/rankings/RankingsTable'
import { PoolNotice } from '../components/rankings/ScoreCell'
import ScoreSettings, { DEFAULT_W, Weights } from '../components/rankings/ScoreSettings'
import CompanyProfileModal from '../components/rankings/CompanyProfileModal'
import SelectionToolbar, { useRowSelection } from '../components/rankings/SelectionToolbar'
import SmartScreen from '../components/rankings/SmartScreen'
import PickCenter from '../components/rankings/PickCenter'
import PremarketPanel from '../components/rankings/PremarketPanel'
import MoversMonitor from '../components/rankings/MoversMonitor'
import { SignalDef } from '../components/rankings/SignalCell'
import { FilterBar } from '../components/rankings/FilterBar'
import { PoolAiReview } from '../components/rankings/PoolAiReview'
import { loadPref, putNum, PREF_KEY, type RankResp } from '../components/rankings/pageState'
import { notifyWatchlistChanged } from '../lib/watchlistBus'
import AiChatModal from '../components/AiChatModal'
import { Alert, Badge, Button, Spinner, useToast } from '../components/ui'
import { api } from '../lib/api'
import { DEFAULT_VISIBLE, RANKING_COLUMNS } from '../lib/rankingColumns'

/** 美股榜单（S&P 500 + NASDAQ 100 + S&P 400/600 + Nasdaq 市值补充 ≈ 2240 只）：行情/估值/技术面的筛选、排序与候选观察池。 */
export default function Rankings() {
  const saved = useMemo(loadPref, [])
  const savedCols = useMemo(() => {
    const keys = (saved.columns || []).filter((k) => RANKING_COLUMNS.some((c) => c.key === k))
    if (!keys.length) return DEFAULT_VISIBLE
    // 列迁移：老偏好里没有「关注信号」列 —— 自动插入到「代码/名称」之前，
    // 否则老用户升级后看不到新列，会以为功能没做。
    if (!keys.includes('signals')) {
      const idx = keys.indexOf('symbol')
      keys.splice(idx >= 0 ? idx : keys.length, 0, 'signals')
    }
    return keys
  }, [saved.columns])

  const [data, setData] = useState<RankResp | null>(null)
  // 持久化的 sort 可能是已改名/已删除的列 —— 先校验再用，否则后端直接 422，整页加载失败
  const [sort, setSort] = useState<string>(() =>
    RANKING_COLUMNS.some((c) => c.key === saved.sort && c.sortable) ? (saved.sort as string) : 'change_pct',
  )
  const [dir, setDir] = useState<'asc' | 'desc'>(saved.dir || 'desc')
  const [filters, setFilters] = useState<RankingFiltersValue>({ ...EMPTY_FILTERS, ...(saved.filters || {}) })
  const [visible, setVisible] = useState<string[]>(savedCols)
  const [q, setQ] = useState('')
  const [onlyWatched, setOnlyWatched] = useState(false)
  const [sector, setSector] = useState('')
  const [limit, setLimit] = useState<number>(saved.limit || 50)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [refreshing, setRefreshing] = useState(false)
  const [profileSym, setProfileSym] = useState('')
  const [profile, setProfile] = useState<any>(null)
  const [profileLoading, setProfileLoading] = useState(false)
  /* ---- 候选观察池 ---- */
  const [view, setView] = useState<'all' | 'pool'>(saved.view || 'all')
  const [threshold, setThreshold] = useState<number>(saved.threshold ?? 70)
  const [weights, setWeights] = useState<Weights>({ ...DEFAULT_W, ...(saved.weights || {}) })
  const [showWeights, setShowWeights] = useState(false)
  /* ---- 选股中心 ---- */
  const [signal, setSignal] = useState<string>(saved.signal || '')
  const [catalog, setCatalog] = useState<SignalDef[]>([])
  const nav = useNavigate()
  const toast = useToast()
  const profileSeqRef = useRef(0)
  /* ---- AI 对话弹窗（多轮，勾选标的作上下文） ---- */
  const [chatOpen, setChatOpen] = useState(false)
  const [chatSymbols, setChatSymbols] = useState<string[]>([])

  // filters 是对象，直接进 useCallback 依赖会因引用变化反复触发；序列化成字符串当 key
  const filterKey = JSON.stringify(filters)
  const matched = useMemo(() => matchPreset(JSON.parse(filterKey)), [filterKey])
  const weightKey = JSON.stringify(weights)
  // 候选池视图 = 服务端按 score_min 过滤（不是在本地 filter 已加载的 50 条上筛 ——
  // 那样只会从当前这一页里挑，用户看到 5 只但实际有 52 只符合条件，严重误导）。
  const poolOnly = view === 'pool'

  const openProfile = useCallback(async (sym: string) => {
    // P1-9：序号守卫。快速点两个代码时，先发的请求可能后到，
    // 旧实现会让它覆盖新档案 —— 弹窗标题是 B、内容却是 A 的公司资料。
    const seq = ++profileSeqRef.current
    setProfileSym(sym)
    setProfile(null)
    setProfileLoading(true)
    try {
      const r = await api.get<any>(`/market/rankings/profile?symbol=${encodeURIComponent(sym)}`, 30_000)
      if (seq !== profileSeqRef.current) return
      setProfile(r)
    } catch {
      if (seq !== profileSeqRef.current) return
      setProfile({ error: '档案获取失败' })
    } finally {
      if (seq === profileSeqRef.current) setProfileLoading(false)
    }
  }, [])

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    const f: RankingFiltersValue = JSON.parse(filterKey)
    const w: Weights = JSON.parse(weightKey)
    try {
      const params = new URLSearchParams({ sort, direction: dir, limit: String(limit) })
      if (q) params.set('q', q)
      if (sector) params.set('sector', sector)
      putNum(params, 'pe_min', f.peMin)
      putNum(params, 'pe_max', f.peMax)
      putNum(params, 'pb_max', f.pbMax)
      putNum(params, 'cap_min', f.capMin)
      putNum(params, 'div_min', f.divMin)
      putNum(params, 'roe_min', f.roeMin)
      putNum(params, 'from_high_max', f.fromHighMax)
      if (f.excludeLoss) params.set('exclude_loss', 'true')
      // ---- 技术面 ----
      putNum(params, 'rsi_min', f.rsiMin)
      putNum(params, 'rsi_max', f.rsiMax)
      if (f.maPos === 'above') params.set('above_ma200', 'true')
      if (f.maPos === 'below') params.set('below_ma200', 'true')
      if (f.onlyBull) params.set('only_bull', 'true')
      putNum(params, 'vol_max', f.volMax)
      putNum(params, 'beta_max', f.betaMax)
      putNum(params, 'req_1y_min', f.req1yMin)
      putNum(params, 'excess_min', f.excessMin)
      // ---- 评分：候选池视图 = 至少 N 分 ----
      params.set('threshold', String(threshold))
      params.set('weights', JSON.stringify(w))
      if (poolOnly) params.set('score_min', String(threshold))
      if (signal) params.set('signal', signal)
      // 后端是 stale-while-revalidate：永远秒回（旧数据 + 后台刷新），不再长时间阻塞
      const r = await api.get<RankResp>(`/market/rankings?${params}`, 30_000)
      setData(r)
    } catch (e: any) {
      setError(e?.message || '加载失败')
    } finally {
      setLoading(false)
    }
  }, [sort, dir, limit, q, sector, filterKey, threshold, weightKey, poolOnly, signal])

  useEffect(() => {
    const t = setTimeout(load, q ? 400 : 0)   // 搜索防抖
    return () => clearTimeout(t)
  }, [load])

  // 信号目录（说明文案的单一事实源在后端）：页面挂载时拉一次即可
  useEffect(() => {
    api
      .get<{ signals: SignalDef[] }>('/market/rankings/signal-catalog')
      .then((r) => setCatalog(r.signals || []))
      .catch(() => setCatalog([]))   // 目录拉不到只影响说明文案，不阻塞榜单
  }, [])

  // T-118：排序/方向/条数/筛选/列偏好记忆（localStorage）
  useEffect(() => {
    try {
      localStorage.setItem(
        PREF_KEY,
        JSON.stringify({ sort, dir, limit, filters, columns: visible, weights, threshold, view, signal }),
      )
    } catch {
      /* noop */
    }
  }, [sort, dir, limit, filters, visible, weights, threshold, view, signal])

  // stale-while-revalidate：数据 / 估值 / 技术指标还在后台补时每 5 秒自动补拉，直至新鲜
  const pollRef = useRef(0)
  // 覆盖率用 95% 做阈值：腾讯对极少数小票（BRK-B 之类）本来就不覆盖，
  // 用 covered < rows 会让页面永远认为「没补完」—— 一直轮询 + 文案永远挂着「补齐中」。
  const fundPending =
    !!data?.fundamentals &&
    (data.fundamentals.refreshing || data.fundamentals.covered < data.fundamentals.rows * 0.95)
  // 技术指标需要 1 年日线，冷启动全量约 70s。这里同样用 95% 阈值。
  const techPending =
    !!data?.technicals &&
    (data.technicals.refreshing || data.technicals.covered < data.technicals.rows * 0.95)
  const pollNeeded = !!data && (data.stale || data.refreshing || fundPending || techPending)
  useEffect(() => {
    if (!pollNeeded) {
      pollRef.current = 0
      return
    }
    if (pollRef.current > 60) return          // 最多轮询 ~5 分钟（技术指标首拉较慢）
    const t = setTimeout(() => {
      pollRef.current += 1
      load()
    }, 5000)
    return () => clearTimeout(t)
  }, [pollNeeded, load])

  const refresh = async () => {
    setRefreshing(true)
    try {
      await api.post('/market/rankings/refresh-quotes', undefined, 15_000)
      toast('info', '已在后台刷新行情与估值数据，就绪后自动更新')
      await load()
    } catch {
      toast('error', '刷新失败')
    } finally {
      setRefreshing(false)
    }
  }

  const toggleWatch = async (row: RankRow) => {
    try {
      if (row.watched) {
        await api.del(`/watchlist/${encodeURIComponent(row.symbol)}`)
        toast('info', `已取消关注 ${row.symbol}`)
      } else {
        await api.post('/watchlist', { symbol: row.symbol })
        toast('info', `已关注 ${row.symbol}（${row.name}）`)
      }
      notifyWatchlistChanged()
      setData((d) =>
        d ? { ...d, rows: d.rows.map((r) => (r.symbol === row.symbol ? { ...r, watched: !r.watched } : r)) } : d,
      )
    } catch (e: any) {
      toast('error', e?.message || '操作失败')
    }
  }

  /** 点列头：同一列切换升降序；换列时重置为降序（代码列默认升序）。 */
  const onSort = (key: string) => {
    if (sort === key) {
      setDir((d) => (d === 'desc' ? 'asc' : 'desc'))
    } else {
      setSort(key)
      setDir(key === 'symbol' ? 'asc' : 'desc')
    }
  }

  const toggleColumn = (key: string) => {
    setVisible((v) => (v.includes(key) ? v.filter((x) => x !== key) : [...v, key]))
  }

  const rows = (data?.rows || []).filter((r) => !onlyWatched || r.watched)
  // 勾选状态（供「一键分析单只/多只」用）。放在这里而非顶部：它依赖上面的 rows。
  // 本组件没有 early return，因此 hook 调用顺序每次渲染都一致，不违反 hooks 规则。
  const sel = useRowSelection(rows)
  const watchedCount = (data?.rows || []).filter((r) => r.watched).length
  // universe_total 是新增字段：老后端不返回时回落 total，避免页面上出现 "undefined"
  const universeTotal = data?.universe_total ?? data?.total
  const filtered = !!data && universeTotal != null && data.total !== universeTotal
  // 后端进程可能仍是旧代码：前端是直接从 dist 读的、刷新就更新，后端不会。
  // 旧后端不返回 universe_total / fundamentals —— 那样估值列会静默全变成「—」，
  // 用户只会觉得「页面没做好」。这里显式识别，并给出可执行的修复步骤。
  const staleBackend = !!data && data.universe_total == null
  const sortRejected = /query\.sort|sort.*pattern/i.test(error)
  // 技术指标未就绪时，技术面筛选会一个都筛不出来 —— 那不是「没有符合的股票」，
  // 而是「还没数据」。两者必须区分，否则用户会得出完全错误的结论。
  const techNotReady = !!data && !data.technicals
  const poolCount = data?.bands?.buy ?? 0
  const catalogMap = useMemo(
    () => Object.fromEntries(catalog.map((d) => [d.key, d])) as Record<string, SignalDef>,
    [catalog],
  )

  const emptyMsg =
    loading && !data
      ? '正在拉取行情数据，就绪后自动刷新，无需手动操作…'
      : data && (data.refreshing || data.stale)
        ? '行情后台刷新中（首次约 1 分钟）… 页面每 5 秒自动更新'
        : view === 'pool' && techPending
          ? '技术指标正在后台补齐（首次约 2 分钟），补齐后候选池会自动更新…'
          : q.trim()
            ? `没有找到匹配「${q.trim()}」的标的 —— 换个代码或名称关键词再试（支持中文名，如「赛默飞」）。`
            : '没有匹配的标的 —— 放宽筛选条件、降低评分阈值或调整搜索关键词后重试。'

  return (
    <div className="space-y-4">
      {/* 盘前监控：美东 04:00–09:30 抓盘前异动 + 新闻 + AI 综述；其余时段显示最近快照 */}
      <PremarketPanel onOpenProfile={openProfile} />

      {/* 视图切换：全部 / 候选观察池 */}
      <div className="flex flex-wrap items-center gap-2">
        <div className="inline-flex rounded-lg border border-slate-200 bg-white p-0.5">
          <button
            onClick={() => setView('all')}
            className={`rounded-md px-3 py-1 text-xs transition-colors ${
              view === 'all' ? 'bg-brand-50 font-semibold text-brand-700' : 'text-slate-500 hover:text-slate-700'
            }`}
          >
            全部标的
          </button>
          <button
            onClick={() => {
              setView('pool')
              // 进候选池时自动按评分排序 —— 否则用户会看到「一堆 70 分里的涨跌幅榜」
              setSort('score')
              setDir('desc')
            }}
            title={`综合评分 ≥ ${threshold} 的标的，按评分从高到低`}
            className={`inline-flex items-center gap-1 rounded-md px-3 py-1 text-xs transition-colors ${
              view === 'pool' ? 'bg-brand-50 font-semibold text-brand-700' : 'text-slate-500 hover:text-slate-700'
            }`}
          >
            <ListFilter className="h-3 w-3" />
            候选观察池
            {poolCount > 0 && <span className="num text-[10px] text-slate-400">{poolCount}</span>}
          </button>
        </div>

        <button
          onClick={() => setShowWeights((v) => !v)}
          className={`inline-flex items-center gap-1 rounded-lg border px-2.5 py-1 text-xs transition-colors ${
            showWeights ? 'border-brand-300 text-brand-700' : 'border-slate-200 text-slate-500 hover:text-brand-700'
          }`}
          title="调整四个维度的权重与候选池阈值"
        >
          <Sliders className="h-3 w-3" />
          评分设置
        </button>

        <Badge tone="brand">美股 {universeTotal ?? '…'}</Badge>
        {data?.snapshot_restored && (
          <Badge tone="amber">缓存秒开 · 后台刷新中</Badge>
        )}
        <span className="text-xs text-slate-400">
          {data
            ? `共 ${universeTotal} 只${filtered ? ` · 筛出 ${data.total} 只` : ''} · 行情更新于 ${data.updated}${
                data.stale || data.refreshing ? '（后台刷新中…）' : ''
              }${
                data.fundamentals
                  ? ` · 估值 ${data.fundamentals.covered}/${data.fundamentals.rows} 只${
                      fundPending ? '（后台补齐中…）' : ''
                    }`
                  : ''
              }${
                data.technicals
                  ? ` · 技术指标 ${data.technicals.covered}/${data.technicals.rows} 只${
                      techPending ? '（后台补齐中…）' : ''
                    }`
                  : ''
              }`
            : ''}
        </span>
        {refreshing && <Spinner />}
        <div className="ml-auto flex items-center gap-2">
          <Button
            size="sm"
            icon={<MessageSquare className="h-3.5 w-3.5" />}
            onClick={() => {
              setChatSymbols([])
              setChatOpen(true)
            }}
            title="打开 AI 对话弹窗（勾选标的后入口会自动带上它们的量化快照）"
          >
            AI 问答
          </Button>
          <Button
            variant={onlyWatched ? 'primary' : 'ghost'}
            icon={<Star className={`h-3.5 w-3.5 ${onlyWatched ? 'fill-amber-400 text-amber-400' : ''}`} />}
            onClick={() => setOnlyWatched((v) => !v)}
            title="只显示已加入关注列表的标的"
          >
            只看已关注{data ? `（${watchedCount}）` : ''}
          </Button>
          <Button
            icon={<RefreshCw className={`h-3.5 w-3.5 ${refreshing ? 'animate-spin' : ''}`} />}
            onClick={refresh}
          >
            刷新行情
          </Button>
        </div>
      </div>

      {showWeights && (
        <ScoreSettings
          threshold={threshold}
          onThreshold={setThreshold}
          weights={weights}
          onWeights={setWeights}
          poolCount={data ? poolCount : null}
          onReset={() => {
            setWeights({ ...DEFAULT_W })
            setThreshold(70)
          }}
        />
      )}

      {view === 'pool' && data && (
        <PoolNotice
          count={data.total}
          total={universeTotal ?? 0}
          threshold={threshold}
          bypassed={!!data.pool_bypassed && !!q}
        />
      )}

      {/* 每日开盘监控：全池暴涨/暴跌实时扫描（30 秒轮询，阈值可调） */}
      <MoversMonitor onOpenProfile={openProfile} />

      {/* 选股中心：今日关注（全池挑出）+ 信号统计（点击筛选）+ 信号说明目录 */}
      <PickCenter
        focus={data?.focus ?? []}
        stats={data?.signal_stats ?? {}}
        catalog={catalog}
        activeSignal={signal}
        onPickSignal={setSignal}
        onOpenProfile={openProfile}
        loading={loading && !data}
      />

      {/* 智能选股：自然语言 → 筛选条件（结果直接写进下面的筛选面板） */}
      <SmartScreen
        sectors={data?.sectors ?? []}
        onApply={(p) => {
          setFilters({ ...EMPTY_FILTERS, ...p.filters })
          if (p.sector !== undefined) setSector(p.sector)
          if (p.sort) {
            setSort(p.sort)
            // 方向由 AI 给出（「PE 从低到高」= asc）；缺省才回落降序。
            setDir(p.direction === 'asc' ? 'asc' : 'desc')
          }
          if (p.view) setView(p.view)
          toast('success', '已应用 AI 解析的筛选条件')
        }}
      />

      <RankingFilters
        value={filters}
        onChange={setFilters}
        onReset={() => setFilters(EMPTY_FILTERS)}
        matched={matched}
      />

      {techNotReady && (
        <Alert tone="warn" title="技术指标未加载（后端为旧版本）">
          技术面筛选（RSI / 均线 / 波动率 / Beta）需要后端返回技术指标字段。当前接口没有返回这些字段，
          说明<strong className="font-medium">后端进程仍是旧版本</strong>。先执行 stop.bat，再执行 start.bat，
          然后刷新本页；首次加载技术指标需要约 1 分钟后台补齐。
        </Alert>
      )}

      {/* 搜索 / 行业 / 条数 / 列 */}
      <FilterBar
        sort={sort}
        dir={dir}
        q={q}
        setQ={setQ}
        sector={sector}
        setSector={setSector}
        sectors={data?.sectors ?? []}
        limit={limit}
        setLimit={setLimit}
        visible={visible}
        toggleColumn={toggleColumn}
        resetVisible={() => setVisible(DEFAULT_VISIBLE)}
      />

      {error && (
        <Alert tone="danger" title="加载失败">
          {error}
          {sortRejected && (
            <div className="mt-1.5 rounded bg-white/60 px-2 py-1.5 text-xs leading-5">
              排序参数被后端拒绝，通常是<strong className="font-medium">后端进程仍是旧版本</strong>
              （旧白名单里没有新指标）。先执行 stop.bat，再执行 start.bat，然后刷新本页。
            </div>
          )}
        </Alert>
      )}

      {staleBackend && (
        <Alert tone="warn" title="后端未加载新代码">
          接口没有返回估值字段（PE / PB / ROE / 股息率）与筛选结果，说明后端进程还是旧版本。
          前端已是最新（从 dist 直接读），但<strong className="font-medium">后端必须重启</strong>
          才会加载新代码：先执行 stop.bat，再执行 start.bat，然后刷新本页。
        </Alert>
      )}

      {/* 多选工具条：勾选 1 只 = AI 深度分析，多只 = AI 对比分析 */}
      <SelectionToolbar
        rows={rows}
        selected={sel.selected}
        onClear={sel.clear}
        onToggleWatch={toggleWatch}
        context={view === 'pool' ? `候选观察池（评分 ≥ ${threshold}）` : `美股榜单（${rows.length} 只）`}
        onOpenChat={(syms) => {
          setChatSymbols(syms)
          setChatOpen(true)
        }}
        onBacktest={(syms) => nav('/backtest', { state: { symbols: syms } })}
      />

      {/* AI 多轮对话弹窗（上下文 = 勾选的标的或空） */}
      <AiChatModal
        open={chatOpen}
        onClose={() => setChatOpen(false)}
        symbols={chatSymbols}
        contextLabel={view === 'pool' ? `候选观察池 · 评分 ≥ ${threshold}` : '美股全池榜单'}
      />

      <RankingsTable
        rows={rows}
        visible={visible}
        sort={sort}
        dir={dir}
        onSort={onSort}
        loading={loading && !data}
        empty={emptyMsg}
        onToggleWatch={toggleWatch}
        onOpenProfile={openProfile}
        onAnalyze={(s) => nav(`/market?symbol=${encodeURIComponent(s)}`)}
        onBacktest={(s) => nav('/backtest', { state: { symbols: [s] } })}
        selected={sel.selected}
        onToggleSelect={sel.toggle}
        onToggleAll={sel.toggleAll}
        allSelected={sel.allSelected}
        catalog={catalogMap}
        onPickSignal={setSignal}
      />

      {/* AI 候选池点评：只解读「当前筛选条件筛出来的这一批」，不是买入建议 */}
      <PoolAiReview
        rows={rows}
        universeTotal={universeTotal}
        matched={data?.total}
        scoreMin={view === 'pool' ? threshold : undefined}
        sort={sort}
        dir={dir}
        view={view}
        threshold={threshold}
      />

      {/* 公司档案弹窗（展示块已抽到组件里，见 components/rankings/CompanyProfileModal.tsx） */}
      <CompanyProfileModal
        symbol={profileSym}
        profile={profile}
        loading={profileLoading}
        onClose={() => setProfileSym('')}
        onRefresh={() => openProfile(profileSym)}
        onGoMarket={() => nav(`/market?symbol=${encodeURIComponent(profileSym)}`)}
      />
    </div>
  )
}
