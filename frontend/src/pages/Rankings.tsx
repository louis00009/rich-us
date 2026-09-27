import { RefreshCw, Search, Star, StarOff } from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Alert, Badge, Button, Input, Modal, Select, Spinner, useToast } from '../components/ui'
import { api } from '../lib/api'
import { downColor, upColor } from '../lib/format'

interface RankRow {
  symbol: string
  name: string
  name_cn?: string
  sector: string
  watched: boolean
  price: number
  prev_close: number
  change_pct: number
  volume: number
  amount: number
  market_cap?: number | null
}

interface RankResp {
  total: number
  count: number
  updated: string
  quote_age_sec?: number | null
  stale?: boolean
  refreshing?: boolean
  rows: RankRow[]
  sectors: string[]
}

const SORTS = [
  { key: 'change_pct', label: '涨跌幅' },
  { key: 'market_cap', label: '总市值' },
  { key: 'amount', label: '成交额' },
  { key: 'volume', label: '成交量' },
  { key: 'price', label: '价格' },
  { key: 'symbol', label: '代码' },
]

/** 美股 Top 500（S&P 500）榜单页。 */
export default function Rankings() {
  const saved = (() => {
    try {
      return JSON.parse(localStorage.getItem('qd_rankings_pref') || '{}')
    } catch {
      return {}
    }
  })()
  const [data, setData] = useState<RankResp | null>(null)
  const [sort, setSort] = useState<string>(saved.sort || 'change_pct')
  const [dir, setDir] = useState<'asc' | 'desc'>(saved.dir || 'desc')
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
  const nav = useNavigate()
  const toast = useToast()
  const profileSeqRef = useRef(0)

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
    try {
      const params = new URLSearchParams({ sort, direction: dir, limit: String(limit) })
      if (q) params.set('q', q)
      if (sector) params.set('sector', sector)
      // 后端是 stale-while-revalidate：永远秒回（旧数据 + 后台刷新），不再长时间阻塞
      const r = await api.get<RankResp>(`/market/rankings?${params}`, 30_000)
      setData(r)
    } catch (e: any) {
      setError(e?.message || '加载失败')
    } finally {
      setLoading(false)
    }
  }, [sort, dir, limit, q, sector])

  useEffect(() => {
    const t = setTimeout(load, q ? 400 : 0)   // 搜索防抖
    return () => clearTimeout(t)
  }, [load])

  // T-118：排序/方向/条数偏好记忆（localStorage）
  useEffect(() => {
    try {
      localStorage.setItem('qd_rankings_pref', JSON.stringify({ sort, dir, limit }))
    } catch {
      /* noop */
    }
  }, [sort, dir, limit])

  // stale-while-revalidate：数据标记 stale / refreshing 时每 5 秒自动补拉，直至新鲜
  const pollRef = useRef(0)
  useEffect(() => {
    if (!data) return
    if (!data.stale && !data.refreshing) {
      pollRef.current = 0
      return
    }
    if (pollRef.current > 40) return          // 最多轮询 ~3.5 分钟
    const t = setTimeout(() => {
      pollRef.current += 1
      load()
    }, 5000)
    return () => clearTimeout(t)
  }, [data, load])

  const refresh = async () => {
    setRefreshing(true)
    try {
      await api.post('/market/rankings/refresh-quotes', undefined, 15_000)
      toast('info', '已在后台刷新行情，数据就绪后自动更新')
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
        toast('success', `已关注 ${row.symbol}（${row.name}）`)
      }
      setData((d) =>
        d ? { ...d, rows: d.rows.map((r) => (r.symbol === row.symbol ? { ...r, watched: !r.watched } : r)) } : d,
      )
    } catch (e: any) {
      toast('error', e?.message || '操作失败')
    }
  }

  const fmtAmount = (v: number) =>
    v >= 1e9 ? `${(v / 1e9).toFixed(1)}B` : v >= 1e6 ? `${(v / 1e6).toFixed(1)}M` : v >= 1e3 ? `${(v / 1e3).toFixed(0)}K` : String(v)

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-2">
          <Badge tone="brand">S&P 500</Badge>
          <span className="text-xs text-slate-400">
            {data
              ? `共 ${data.total} 只 · 行情更新于 ${data.updated}${data.stale || data.refreshing ? '（后台刷新中…）' : ''}`
              : ''}
          </span>
          {refreshing && <Spinner />}
        </div>
        <Button
          icon={<RefreshCw className={`h-3.5 w-3.5 ${refreshing ? 'animate-spin' : ''}`} />}
          onClick={refresh}
        >
          刷新行情
        </Button>
        <Button
          variant={onlyWatched ? 'primary' : 'ghost'}
          icon={<Star className={`h-3.5 w-3.5 ${onlyWatched ? 'fill-amber-400 text-amber-400' : ''}`} />}
          onClick={() => setOnlyWatched((v) => !v)}
          title="只显示已加入关注列表的标的"
        >
          只看已关注{data ? `（${data.rows.filter((r) => r.watched).length}）` : ''}
        </Button>
      </div>

      {/* 排序与筛选 */}
      <div className="flex flex-wrap items-center gap-2 rounded-xl border border-slate-200 bg-white px-3 py-2.5">
        <span className="text-[11px] text-slate-400">排序</span>
        <div className="flex flex-wrap gap-1">
          {SORTS.map((s) => (
            <button
              key={s.key}
              onClick={() => {
                if (sort === s.key) setDir((d) => (d === 'desc' ? 'asc' : 'desc'))
                else {
                  setSort(s.key)
                  setDir(s.key === 'symbol' ? 'asc' : 'desc')
                }
              }}
              className={`rounded-lg px-2.5 py-1 text-xs transition-colors ${
                sort === s.key ? 'bg-brand-50 font-semibold text-brand-700' : 'text-slate-500 hover:bg-slate-50'
              }`}
            >
              {s.label}
              {sort === s.key && (dir === 'desc' ? ' ↓' : ' ↑')}
            </button>
          ))}
        </div>
        <div className="relative ml-auto">
          <Search className="absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-slate-300" />
          <Input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="搜索代码 / 名称"
            className="w-44 py-1.5 pl-7 text-xs"
          />
        </div>
        <Select value={sector} onChange={(e) => setSector(e.target.value)} className="w-36 py-1.5 text-xs">
          <option value="">全部行业</option>
          {(data?.sectors ?? []).map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </Select>
        <Select value={String(limit)} onChange={(e) => setLimit(Number(e.target.value))} className="w-24 py-1.5 text-xs">
          {[20, 50, 100, 200, 503].map((n) => (
            <option key={n} value={n}>
              前 {n}
            </option>
          ))}
        </Select>
      </div>

      {error && <Alert tone="danger" title="加载失败">{error}</Alert>}

      {/* 榜单表格 */}
      <div className="overflow-x-auto rounded-xl border border-slate-200 bg-white">
        <table className="w-full min-w-[680px] text-sm">
          <thead>
            <tr className="border-b border-slate-100 text-left text-[11px] uppercase tracking-wide text-slate-400">
              <th className="px-3 py-2 w-8"></th>
              <th className="px-3 py-2">代码</th>
              <th className="px-3 py-2">名称</th>
              <th className="px-3 py-2 text-right">现价</th>
              <th className="px-3 py-2 text-right">涨跌幅</th>
              <th className="px-3 py-2 text-right">成交量</th>
              <th className="px-3 py-2 text-right">成交额</th>
              <th className="px-3 py-2 text-right">总市值</th>
              <th className="px-3 py-2">行业</th>
              <th className="px-3 py-2"></th>
            </tr>
          </thead>
          <tbody>
            {loading && !data && (
              <tr>
                <td colSpan={9} className="px-3 py-10 text-center text-xs text-slate-400">
                  正在后台拉取行情（首次约 30 秒），就绪后自动刷新，无需手动操作…
                </td>
              </tr>
            )}
            {data && data.rows.length === 0 && (data.refreshing || data.stale) && (
              <tr>
                <td colSpan={9} className="px-3 py-10 text-center text-xs text-slate-400">
                  行情首次预热中（约 30 秒）… 页面每 5 秒自动刷新
                </td>
              </tr>
            )}
            {data && data.rows.length === 0 && !(data.refreshing || data.stale) && (
              <tr>
                <td colSpan={9} className="px-3 py-10 text-center text-xs text-slate-400">
                  没有匹配的标的 —— 调整搜索关键词或行业筛选后重试。
                </td>
              </tr>
            )}
            {(data?.rows || [])
              .filter((r) => !onlyWatched || r.watched)
              .map((r) => (
              <tr key={r.symbol} className="border-b border-slate-50 transition-colors hover:bg-slate-50/60">
                <td className="px-3 py-2">
                  <button
                    onClick={() => toggleWatch(r)}
                    className="rounded p-0.5 text-slate-300 transition-colors hover:text-amber-500"
                    title={r.watched ? '取消关注' : '加入关注'}
                  >
                    {r.watched ? <Star className="h-3.5 w-3.5 fill-amber-400 text-amber-400" /> : <StarOff className="h-3.5 w-3.5" />}
                  </button>
                </td>
                <td className="px-3 py-2 font-semibold text-slate-800">
                  <button onClick={() => openProfile(r.symbol)} className="hover:text-brand-700 hover:underline" title="查看公司介绍">
                    {r.symbol}
                  </button>
                </td>
                <td className="max-w-[180px] truncate px-3 py-2 text-slate-600">
                  <button
                    onClick={() => openProfile(r.symbol)}
                    className="hover:text-brand-700 hover:underline"
                    title={r.name_cn ? `${r.name_cn} · ${r.name}` : r.name}
                  >
                    {(r.name_cn || r.name)}
                  </button>
                </td>
                <td className="px-3 py-2 text-right tabular-nums">{r.price != null ? Number(r.price).toFixed(2) : '—'}</td>
                <td className="px-3 py-2 text-right font-medium tabular-nums" style={{ color: r.change_pct == null ? undefined : (r.change_pct >= 0 ? upColor() : downColor()) }}>
                  {r.change_pct == null ? '—' : `${r.change_pct >= 0 ? '+' : ''}${r.change_pct.toFixed(2)}%`}
                </td>
                <td className="px-3 py-2 text-right tabular-nums text-slate-500">{fmtAmount(r.volume)}</td>
                <td className="px-3 py-2 text-right tabular-nums text-slate-500">{fmtAmount(r.amount)}</td>
                <td className="px-3 py-2 text-right tabular-nums text-slate-500">
                  {r.market_cap ? fmtAmount(r.market_cap) : '—'}
                </td>
                <td className="px-3 py-2 text-xs text-slate-400">{r.sector}</td>
                <td className="px-3 py-2 text-right">
                  <button
                    onClick={() => nav(`/market?symbol=${encodeURIComponent(r.symbol)}`)}
                    className="rounded-lg border border-slate-200 px-2 py-0.5 text-[11px] text-slate-500 transition-colors hover:border-brand-300 hover:text-brand-700"
                  >
                    分析
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* 公司档案弹窗 */}
      <Modal open={!!profileSym} onClose={() => setProfileSym('')} title={profileSym ? `${profileSym} · 公司档案` : ''}>
        {profileLoading && (
          <div className="flex items-center justify-center gap-2 py-8 text-sm text-slate-400">
            <Spinner /> 正在获取档案…
          </div>
        )}
        {profile && !profileLoading && (
          <div className="space-y-3">
            {profile.error && !profile.name && (
              <Alert tone="warn" title="档案不可用">{profile.error}</Alert>
            )}
            {profile.name && (
              <>
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-lg font-semibold text-slate-900">{profile.name}</span>
                  {profile.sector && <Badge tone="brand">{profile.sector}</Badge>}
                  {profile.industry && <Badge tone="slate">{profile.industry}</Badge>}
                  {profile.country && <Badge tone="slate">{profile.country}</Badge>}
                </div>
                <div className="flex flex-wrap gap-x-6 gap-y-1 text-xs text-slate-500">
                  {profile.market_cap > 0 && (
                    <span>市值 <span className="num font-medium text-slate-700">${(profile.market_cap / 1e9).toFixed(0)}B</span></span>
                  )}
                  {profile.ipo_date && <span>IPO <span className="text-slate-700">{profile.ipo_date}</span></span>}
                  {profile.website && (
                    <a href={profile.website} target="_blank" rel="noreferrer" className="text-brand-600 hover:underline">
                      官网 ↗
                    </a>
                  )}
                </div>
                {profile.summary && (
                  <div>
                    <div className="mb-1 text-[11px] font-medium uppercase tracking-wide text-slate-400">
                      Business Summary
                    </div>
                    <p className="max-h-72 overflow-y-auto whitespace-pre-wrap rounded-lg bg-slate-50 p-3 text-[13px] leading-6 text-slate-600">
                      {profile.summary}
                    </p>
                  </div>
                )}
                <div className="flex justify-end gap-2 pt-1">
                  <Button onClick={() => openProfile(profileSym)}>强制刷新</Button>
                  <Button variant="primary" onClick={() => nav(`/market?symbol=${encodeURIComponent(profileSym)}`)}>
                    去行情分析
                  </Button>
                </div>
              </>
            )}
          </div>
        )}
      </Modal>
    </div>
  )
}
