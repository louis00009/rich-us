/**
 * AI 情报中心 —— 事件驱动研究流水线
 *
 * 一键开启监控后：外部 AI Agent（WorkBuddy / Claude Code / Codex）通过 Bridge
 * API 抓取互联网信息 → 提交美股核心公司的关键节点（模型/产品发布、合作、财报、
 * 监管）→ 结合量化快照提交买入建议；未配置外部 Agent 时内置 LLM/本地量化引擎
 * 自动分析兜底。截止后整批节点与建议自动落盘为 Markdown 报告。
 */
import {
  Activity,
  Bot,
  Check,
  Copy,
  Download,
  FileText,
  Play,
  Plus,
  RefreshCw,
  Satellite,
  Square,
  Trash2,
  Zap,
} from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import {
  Alert,
  Badge,
  Button,
  Card,
  Empty,
  Input,
  Modal,
  Progress,
  Field,
  Select,
  Switch,
  Tabs,
  useToast,
} from '../components/ui'
import { api } from '../lib/api'
import { downColor, fmtAgo, fmtNum, upColor } from '../lib/format'

/* P2-7：impact 由**外部 AI Agent 提交**，必须夹取到 1..5。
   旧实现直接 `'☆'.repeat(5 - e.impact)` —— impact > 5 时参数为负，
   String.repeat 抛 RangeError，整个页面白屏。 */
function clampImpact(v: unknown): number {
  const n = Math.round(Number(v))
  if (!Number.isFinite(n)) return 3
  return Math.max(1, Math.min(5, n))
}

/* ---------------- 类型 ---------------- */
type Rec = 'strong_buy' | 'buy' | 'hold' | 'reduce' | 'avoid'

interface Company {
  id: number
  symbol: string
  name: string
  theme: string
  focus: string
  enabled: boolean
  last_scrape_at: string | null
}

interface EventItem {
  id: number
  symbol: string
  occurred_on: string
  category: string
  category_cn: string
  title: string
  summary: string
  impact: number
  sentiment: 'positive' | 'neutral' | 'negative'
  source_name: string
  source_url: string
  agent: string
  created_at: string
}

interface Analysis {
  id: number
  symbol: string
  recommendation: Rec
  recommendation_cn: string
  confidence: number
  thesis: string
  catalysts: string
  risks: string
  position_pct: number
  invalidation: string
  price_at_analysis: number
  horizon: string
  agent: string
  engine: string
  based_on_events?: number[]
  event_score?: number | null
  outcome_checked_at?: string | null
  outcome_price?: number | null
  outcome_return?: number | null
  outcome_hit?: boolean | null
  created_at: string
}

interface VerifyAgentStat {
  agent: string
  n: number
  hits: number
  hit_rate: number | null
  avg_return: number | null
  avg_confidence: number | null
}

interface VerifyStats {
  verified_total: number
  pending: number
  analyses_total: number
  agents: VerifyAgentStat[]
  global_hit_rate: number | null
  tolerance_pct: number
  window_days: number
}

interface PriceSeries {
  symbol: string
  source: string
  dates: string[]
  close: number[]
}

interface Run {
  id: number
  status: 'running' | 'finished' | 'stopped'
  interval_minutes: number
  auto_analyze: boolean
  started_at: string
  ended_at: string | null
  tick_count: number
  last_tick_at: string | null
  events_found: number
  analyses_done: number
  agents_seen: string
  note: string
  report_path: string
}

interface Overview {
  settings: { monitor_enabled: boolean; interval_minutes: number; auto_analyze: boolean; bridge_token: string }
  scheduler: { scheduler_alive: boolean; monitor_enabled: boolean; current_run: Run | null }
  stats: {
    events_total: number
    analyses_total: number
    companies_total: number
    companies_enabled: number
    tasks_pending: number
    agents_24h: Record<string, string>
  }
  companies: Company[]
  recent_events: EventItem[]
  recent_analyses: Analysis[]
  runs: Run[]
}

const PROMPT_LABEL: Record<string, string> = {
  workbuddy: 'WorkBuddy',
  claude_code: 'Claude Code',
  codex: 'Codex',
}

interface Guide {
  base_url: string
  token: string
  token_header: string
  endpoints: Record<string, string>
  prompts: Record<string, string>
  event_categories: Record<string, string>
  recommendation_options: string[]
  security_note: string
}

/* ---------------- 展示辅助 ---------------- */
const REC_LABEL: Record<Rec, string> = {
  strong_buy: '强烈买入',
  buy: '买入',
  hold: '持有',
  reduce: '减持',
  avoid: '回避',
}

function recBg(rec: Rec): string {
  // 中国习惯：看多 = 红，看空 = 绿（跟随平台配色切换）
  const bull: Rec[] = ['strong_buy', 'buy']
  const base = bull.includes(rec) ? upColor() : rec === 'hold' ? '#d97706' : downColor()
  return base
}

function sentimentColor(s: string): string {
  return s === 'positive' ? upColor() : s === 'negative' ? downColor() : '#94a3b8'
}

function fmtUtc(s: string | null | undefined): string {
  if (!s) return '—'
  const d = new Date(String(s).endsWith('Z') || String(s).includes('+') ? String(s) : `${s}Z`)
  if (Number.isNaN(d.getTime())) return String(s)
  return d.toLocaleString('zh-CN', { hour12: false })
}

function duration(since: string): string {
  const t = new Date(String(since).endsWith('Z') || String(since).includes('+') ? since : `${since}Z`).getTime()
  if (Number.isNaN(t)) return '—'
  const min = Math.max(0, Math.floor((Date.now() - t) / 60000))
  if (min < 60) return `${min} 分钟`
  const hr = Math.floor(min / 60)
  return `${hr} 小时 ${min % 60} 分`
}

const INTERVALS = [5, 10, 15, 30, 60, 120]

/* ---------------- 时间线辅助 ---------------- */
const EVENT_FACE_DAYS = 90

function eventAgeDays(e: EventItem): number | null {
  const ref = e.occurred_on || String(e.created_at).slice(0, 10)
  if (!/^\d{4}-\d{2}-\d{2}$/.test(ref)) return null
  const d = (Date.now() - new Date(`${ref}T00:00:00Z`).getTime()) / 86400000
  return Number.isNaN(d) ? null : Math.max(0, Math.round(d))
}

function eventWeight(e: EventItem): number {
  const age = eventAgeDays(e) ?? EVENT_FACE_DAYS
  return (e.impact / 5) * Math.max(0.05, 1 - Math.max(0, age) / EVENT_FACE_DAYS)
}

/**
 * 价格叠加层：120 天收盘曲线，事件按发生日钉在对应价位上
 * （利好=红 / 利空=绿 / 中性=灰，圆点大小=影响度），事件对股价的影响一眼可见。
 */
function PriceOverlay({ symbol, events, big = false }: { symbol: string; events: EventItem[]; big?: boolean }) {
  const [days, setDays] = useState(30)
  const [tip, setTip] = useState<{ e: EventItem; x: number; y: number; px: number } | null>(null)
  const [data, setData] = useState<PriceSeries | null>(null)
  const [err, setErr] = useState('')

  useEffect(() => {
    setData(null)
    setErr('')
    api.get<PriceSeries>(`/intel/history/${symbol}?days=${days}`).then(setData).catch((e) => setErr(e.message))
  }, [symbol, days])

  if (err) return <div className="mb-3 rounded-lg bg-slate-50 px-3 py-2 text-[11px] text-slate-400">价格曲线不可用（{err}）</div>
  if (!data || data.close.length < 2) return null

  const W = 640
  const H = 110
  const PAD = 10
  const n = data.close.length
  const min = Math.min(...data.close)
  const max = Math.max(...data.close)
  const span = max - min || 1
  const xs = (i: number) => PAD + (i * (W - 2 * PAD)) / (n - 1)
  const ys = (v: number) => H - PAD - ((v - min) / span) * (H - 2 * PAD)
  const line = data.close.map((v, i) => `${i ? 'L' : 'M'}${xs(i).toFixed(1)},${ys(v).toFixed(1)}`).join(' ')
  const area = `${line} L${xs(n - 1).toFixed(1)},${H - PAD} L${xs(0).toFixed(1)},${H - PAD} Z`

  // 事件钉点：occurred_on → 数据中 ≤ 该日的最近交易日
  const dots = events
    .filter((e) => /^\d{4}-\d{2}-\d{2}$/.test(e.occurred_on || ''))
    .map((e) => {
      let idx = -1
      for (let i = n - 1; i >= 0; i--) {
        if (data.dates[i] <= e.occurred_on) {
          idx = i
          break
        }
      }
      if (idx < 0) return null
      return { e, x: xs(idx), y: ys(data.close[idx]), px: data.close[idx] }
    })
    .filter(Boolean) as { e: EventItem; x: number; y: number; px: number }[]

  const first = data.dates[0]
  const last = data.dates[n - 1]

  return (
    <div className="mb-4 rounded-lg border border-slate-100 bg-slate-50/60 p-2">
      <div className="mb-1 flex items-center gap-2 px-1 text-[11px] text-slate-400">
        <span className="font-medium text-slate-600">{symbol} 股价 · 近 {days} 天</span>
        <span>最低 {fmtNum(min)} / 最高 {fmtNum(max)}</span>
        <span className="ml-auto">来源 {data.source} · {first} ~ {last}</span>
        <Tabs
          value={String(days)}
          onChange={(k) => setDays(Number(k))}
          tabs={[
            { key: '7', label: '1 周' },
            { key: '30', label: '1 个月' },
            { key: '90', label: '3M' },
            { key: '180', label: '6M' },
            { key: '365', label: '1Y' },
          ]}
        />
      </div>
      <div className="relative">
        <svg viewBox={`0 0 ${W} ${H}`} className={big ? 'h-52 w-full' : 'h-28 w-full'} preserveAspectRatio="none">
        <defs>
          <linearGradient id="pxfill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#6366f1" stopOpacity="0.18" />
            <stop offset="100%" stopColor="#6366f1" stopOpacity="0.01" />
          </linearGradient>
        </defs>
        <path d={area} fill="url(#pxfill)" />
        <path d={line} fill="none" stroke="#6366f1" strokeWidth="1.8" />
        {dots.map(({ e, x, y, px }) => {
          const c = sentimentColor(e.sentiment)
          const r = 3 + e.impact * 0.7
          return (
            <g key={e.id}>
              <line x1={x} y1={y} x2={x} y2={H - PAD} stroke={c} strokeOpacity="0.25" strokeDasharray="2 3" />
              <circle
                cx={x} cy={y} r={tip && tip.e.id === e.id ? r + 2 : r} fill={c} stroke="#fff" strokeWidth="1.2" opacity="0.9"
                className="cursor-pointer"
                onMouseEnter={() => setTip({ e, x, y, px })}
                onMouseLeave={() => setTip(null)}
              />
            </g>
          )
        })}
      </svg>
      {tip && (
        <div
          className="pointer-events-none absolute z-30 w-64 rounded-lg border border-slate-300 bg-white p-3 shadow-xl"
          style={{
            left: `${Math.min(78, Math.max(2, (tip.x / W) * 100))}%`,
            top: 6,
          }}
        >
          <div className="flex items-center gap-1.5 text-[11px]">
            <span className="num font-semibold text-slate-700">{tip.e.occurred_on || '日期未知'}</span>
            <span className={`font-medium ${tip.e.sentiment === 'positive' ? 'text-rose-600' : tip.e.sentiment === 'negative' ? 'text-emerald-600' : 'text-slate-500'}`}>
              {tip.e.sentiment === 'positive' ? '利多' : tip.e.sentiment === 'negative' ? '利空' : '中性'} {tip.e.impact}★
            </span>
            <span className="num ml-auto text-slate-500">收盘 {fmtNum(tip.px)}</span>
          </div>
          <div className="mt-1 text-xs font-medium leading-snug text-slate-800">{tip.e.title}</div>
          {tip.e.summary && <p className="mt-1 line-clamp-3 text-[11px] leading-relaxed text-slate-500">{tip.e.summary}</p>}
          {tip.e.source_url && (
            <div className="mt-1 truncate text-[10px] text-brand-600">来源：{tip.e.source_name || tip.e.source_url}</div>
          )}
        </div>
      )}
      {dots.length > 0 && (
        <div className="px-1 pt-1 text-[10px] text-slate-400">
          图上圆点 = 事件（悬停查看详情）：颜色=利好/利空，大小=影响度，位置=当日收盘价
        </div>
      )}
      </div>
    </div>
  )
}

/**
 * 公司专属时间线：最新事件在上，AI 判定作为特殊节点嵌在时间轴顶端，
 * 把「新闻串联 → 结论」做成一条可视化的因果链。
 */
function TimelineView({ symbol, events, analysis, big = false }: { symbol: string; events: EventItem[]; analysis: Analysis | null; big?: boolean }) {
  const sorted = [...events].sort((a, b) => {
    const ka = a.occurred_on || '9999-99-99'
    const kb = b.occurred_on || '9999-99-99'
    return ka === kb ? String(b.created_at).localeCompare(String(a.created_at)) : kb.localeCompare(ka)
  })
  const pos = events.filter((e) => e.sentiment === 'positive').length
  const neg = events.filter((e) => e.sentiment === 'negative').length
  const neu = events.length - pos - neg
  const recent = events.filter((e) => (eventAgeDays(e) ?? EVENT_FACE_DAYS + 1) <= EVENT_FACE_DAYS).length

  return (
    <div>
      {/* 价格叠加层：事件钉在股价曲线上 */}
      <PriceOverlay symbol={symbol} events={events} big={big} />

      {/* 统计条 */}
      <div className="mb-3 flex flex-wrap items-center gap-2 text-[11px]">
        <Badge tone="brand">近 {EVENT_FACE_DAYS} 天 {recent} 条</Badge>
        <span className="font-medium" style={{ color: upColor() }}>利好 {pos}</span>
        <span className="font-medium" style={{ color: downColor() }}>利空 {neg}</span>
        <span className="text-slate-400">中性 {neu}</span>
        <span className="ml-auto text-slate-400">按事件发生日排序 · 越靠上越新</span>
      </div>

      <div className="relative">
        <div className="absolute bottom-3 left-[86px] top-3 w-px bg-slate-200" />
        <ol className="space-y-3">
          {/* AI 判定节点（时间轴顶端：新闻串联出的结论） */}
          {analysis && (
            <li className="flex gap-3">
              <div className="w-[74px] shrink-0 pt-1.5 text-right text-[11px] font-semibold text-amber-600">AI 判定</div>
              <div className="relative z-10 mt-1.5 h-4 w-4 shrink-0 rounded-full border-[3px] border-amber-400 bg-white" />
              <div className="min-w-0 flex-1 rounded-lg border border-amber-200 bg-amber-50/60 p-3">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="rounded px-2 py-0.5 text-[11px] font-semibold text-white" style={{ background: recBg(analysis.recommendation) }}>
                    {REC_LABEL[analysis.recommendation]}
                  </span>
                  <span className="text-[11px] text-slate-500">
                    置信度 {analysis.confidence.toFixed(0)}% · 仓位 {analysis.position_pct}%
                    {analysis.event_score != null && ` · 事件面 ${analysis.event_score > 0 ? '+' : ''}${analysis.event_score}`}
                  </span>
                  <span className="ml-auto text-[11px] text-slate-400">
                    基于 {analysis.based_on_events?.length ?? 0} 条事件 · {fmtAgo(analysis.created_at)}
                  </span>
                </div>
                {analysis.thesis && <p className="mt-1.5 text-xs leading-relaxed text-slate-600">{analysis.thesis}</p>}
              </div>
            </li>
          )}

          {sorted.map((e) => {
            const dot = sentimentColor(e.sentiment)
            return (
              <li key={e.id} className="flex gap-3">
                <div className="w-[74px] shrink-0 pt-2 text-right">
                  <div className="text-[11px] font-medium text-slate-600">{e.occurred_on || '—'}</div>
                  <div className="text-[10px] text-slate-400">{e.occurred_on ? '' : '日期未知'}</div>
                </div>
                <div className="relative z-10 mt-2 h-3.5 w-3.5 shrink-0 rounded-full border-[3px] bg-white" style={{ borderColor: dot }} />
                <div className="min-w-0 flex-1 rounded-lg border border-slate-100 bg-white p-2.5" style={{ borderLeft: `3px solid ${dot}` }}>
                  <div className="flex flex-wrap items-center gap-1.5">
                    <Badge tone="blue">{e.category_cn || e.category}</Badge>
                    <span className="text-[11px] text-amber-500" title={`影响度 ${clampImpact(e.impact)}/5`}>
                      {'★'.repeat(clampImpact(e.impact))}
                    </span>
                    <Badge tone="violet">{e.agent || 'unknown'}</Badge>
                    <span className="ml-auto text-[10px] text-slate-400">{eventAgeDays(e) != null ? `${eventAgeDays(e)} 天前` : ''}</span>
                  </div>
                  <p className="mt-1 text-sm font-medium text-slate-700">{e.title}</p>
                  {e.summary && <p className="mt-0.5 line-clamp-2 text-xs leading-relaxed text-slate-500">{e.summary}</p>}
                  <div className="mt-1 flex items-center gap-2 text-[11px]">
                    {e.source_url ? (
                      <a href={e.source_url} target="_blank" rel="noreferrer" className="truncate text-brand-600 hover:underline">
                        {e.source_name || e.source_url}
                      </a>
                    ) : (
                      <span className="truncate text-slate-400">{e.source_name || '来源未提供'}</span>
                    )}
                  </div>
                </div>
              </li>
            )
          })}
        </ol>
      </div>
    </div>
  )
}

/** 建议验证面板：每个 Agent 的 7 天胜率与置信度校准（该信谁，数据说话）。 */
function VerifyCard() {
  const toast = useToast()
  const [st, setSt] = useState<VerifyStats | null>(null)
  const [busy, setBusy] = useState(false)

  const load = useCallback(() => {
    api.get<VerifyStats>('/intel/verify/stats').then(setSt).catch(() => {})
  }, [])
  useEffect(load, [load])

  const runVerify = async () => {
    setBusy(true)
    try {
      const d = await api.post<{ verified: number; stats: VerifyStats }>('/intel/verify/run')
      setSt(d.stats)
      toast('success', d.verified > 0 ? `已对账 ${d.verified} 条到期建议` : '暂无到期（满 7 天）的建议需要对账')
    } catch (e: any) {
      toast('error', e.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <Card
      title="建议验证 · 谁的建议靠谱"
      subtitle={`窗口 ${st?.window_days ?? 7} 天 · ±${st?.tolerance_pct ?? 1}% 死区为平 · 看多涨算对、看空跌算对，hold 不参与`}
      actions={
        <Button size="sm" variant="secondary" loading={busy} icon={<Zap className="h-3.5 w-3.5" />} onClick={runVerify}>
          立即对账
        </Button>
      }
    >
      {!st ? (
        <Empty title="加载中…" />
      ) : st.agents.length === 0 ? (
        <Empty title="还没有已对账的建议" desc={`建议满 ${st.window_days} 天后自动结算（监控开启时每小时核对一次），也可点「立即对账」提前结算。已验证 ${st.verified_total} / ${st.analyses_total} 条，待对账 ${st.pending} 条`} />
      ) : (
        <>
          <div className="mb-2 flex flex-wrap gap-2 text-[11px] text-slate-500">
            <Badge tone="brand">全局胜率 {st.global_hit_rate ?? '—'}%</Badge>
            <span>已验证 {st.verified_total} 条 · 待对账 {st.pending} 条</span>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-slate-200 text-left text-slate-400">
                  <th className="py-2 pr-3 font-medium">Agent</th>
                  <th className="py-2 pr-3 font-medium">已验证 / 命中</th>
                  <th className="py-2 pr-3 font-medium">胜率</th>
                  <th className="py-2 pr-3 font-medium">平均实际收益</th>
                  <th className="py-2 pr-3 font-medium">平均置信度</th>
                </tr>
              </thead>
              <tbody>
                {st.agents.map((a) => (
                  <tr key={a.agent} className="border-b border-slate-50 text-slate-600">
                    <td className="py-2 pr-3 font-semibold text-slate-700">{a.agent}</td>
                    <td className="py-2 pr-3">{a.n} / {a.hits}</td>
                    <td className="py-2 pr-3">
                      <div className="flex items-center gap-2">
                        <span className="w-12 font-medium">{a.hit_rate?.toFixed(0)}%</span>
                        <div className="w-20">
                          <Progress value={a.hit_rate ?? 0} max={100} tone={(a.hit_rate ?? 0) >= 50 ? 'green' : 'red'} />
                        </div>
                      </div>
                    </td>
                    <td className="py-2 pr-3 font-medium" style={{ color: (a.avg_return ?? 0) >= 0 ? upColor() : downColor() }}>
                      {a.avg_return != null ? `${a.avg_return > 0 ? '+' : ''}${a.avg_return}%` : '—'}
                    </td>
                    <td className="py-2 pr-3">{a.avg_confidence?.toFixed(0)}%</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="mt-2 text-[11px] text-slate-400">
            校准提示：若某 Agent 平均置信度 80% 但胜率只有 40%，说明它过度自信——降低其建议权重；胜率高且置信度与胜率接近的才是可依赖的信息源。
          </p>
        </>
      )}
    </Card>
  )
}

/* ---------------- 页面 ---------------- */
export default function Intel() {
  const toast = useToast()
  const [ov, setOv] = useState<Overview | null>(null)
  const [guide, setGuide] = useState<Guide | null>(null)
  const [events, setEvents] = useState<EventItem[]>([])
  const [analyses, setAnalyses] = useState<Analysis[]>([])
  const [evFilter, setEvFilter] = useState('')
  const [newSymbol, setNewSymbol] = useState('')
  const [addOpen, setAddOpen] = useState(false)
  const [addForm, setAddForm] = useState({ symbol: '', name: '', theme: '', focus: '' })
  const [zoomOpen, setZoomOpen] = useState(false)
  const [zoomDays, setZoomDays] = useState(180)
  const [intervalMin, setIntervalMin] = useState(30)
  const [autoAnalyze, setAutoAnalyze] = useState(true)
  const [busy, setBusy] = useState('')
  const [guideTab, setGuideTab] = useState('workbuddy')
  const [promptOpen, setPromptOpen] = useState(false)
  const [promptSel, setPromptSel] = useState<string[]>(['workbuddy'])
  const [report, setReport] = useState<{ id: number; md: string } | null>(null)
  const [, setTick] = useState(0)

  const loadOverview = useCallback(() => {
    api.get<Overview>('/intel/overview').then((d) => {
      setOv(d)
      setIntervalMin(d.settings.interval_minutes)
      setAutoAnalyze(d.settings.auto_analyze)
    }).catch((e) => toast('error', e.message))
  }, [toast])

  const loadEvents = useCallback(() => {
    api
      .get<{ items: EventItem[] }>(`/intel/events?limit=200${evFilter ? `&symbol=${evFilter}` : ''}`)
      .then((d) => setEvents(d.items))
      .catch(() => {})
  }, [evFilter])

  const loadAnalyses = useCallback(() => {
    api
      .get<{ items: Analysis[] }>(`/intel/analyses?limit=40${evFilter ? `&symbol=${evFilter}` : ''}`)
      .then((d) => setAnalyses(d.items))
      .catch(() => {})
  }, [evFilter])

  useEffect(() => {
    loadOverview()
    api.get<Guide>('/intel/bridge/guide').then(setGuide).catch(() => {})
    const t = setInterval(() => {
      loadOverview()
      setTick((x) => x + 1)
    }, 30000)
    return () => clearInterval(t)
  }, [loadOverview])

  useEffect(() => {
    loadEvents()
    loadAnalyses()
  }, [loadEvents, loadAnalyses])

  const running = ov?.scheduler.current_run ?? null
  const monitorOn = Boolean(ov?.settings.monitor_enabled && ov?.scheduler.scheduler_alive)
  const seenAgents: string[] = (() => {
    try {
      return JSON.parse(running?.agents_seen || '[]')
    } catch {
      return []
    }
  })()

  /* ---------------- 动作 ---------------- */
  const act = async (key: string, fn: () => Promise<any>, okMsg: string) => {
    setBusy(key)
    try {
      await fn()
      toast('success', okMsg)
      loadOverview()
      loadEvents()
      loadAnalyses()
    } catch (e: any) {
      toast('error', e.message)
    } finally {
      setBusy('')
    }
  }

  const startMonitor = () =>
    act('monitor', () => api.post('/intel/monitor/start', { interval_minutes: intervalMin, auto_analyze: autoAnalyze }),
      `监控已开启（周期 ${intervalMin} 分钟）`)

  const stopMonitor = () =>
    act('monitor', () => api.post('/intel/monitor/stop'), '监控已截止，报告已归档')

  const addCompany = () => {
    const s = addForm.symbol.trim().toUpperCase()
    if (!s) {
      toast('warning', '请填写标的代码')
      return
    }
    act('add', () => api.post('/intel/companies', {
      symbol: s,
      name: addForm.name.trim(),
      theme: addForm.theme.trim(),
      focus: addForm.focus.trim(),
    }), `已添加 ${s}`)
    setAddForm({ symbol: '', name: '', theme: '', focus: '' })
    setAddOpen(false)
  }

  const analyzeNow = (symbol: string) =>
    act(`an-${symbol}`, () => api.post(`/intel/analyze/${symbol}`), `${symbol} 分析已生成`)

  const viewReport = async (id: number) => {
    try {
      const d = await api.get<{ markdown: string }>(`/intel/runs/${id}/report`)
      setReport({ id, md: d.markdown })
    } catch (e: any) {
      toast('error', e.message)
    }
  }

  const copy = (text: string, what: string) => {
    navigator.clipboard.writeText(text).then(() => toast('success', `${what}已复制`)).catch(() => toast('error', '复制失败'))
  }

  const downloadReport = () => {
    if (!report) return
    const blob = new Blob([report.md], { type: 'text/markdown;charset=utf-8' })
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob)
    a.download = `intel-run-${report.id}.md`
    a.click()
    URL.revokeObjectURL(a.href)
  }

  /* ---------------- 渲染 ---------------- */
  return (
    <div className="flex h-[calc(100vh-88px)] flex-col gap-3">
      {/* 总控 */}
      <Card className="shrink-0"
        title="监控总控"
        subtitle="开启后 AI Agent 按周期抓取情报；截止时自动归档事件节点与建议报告"
        actions={
          monitorOn ? (
            <Button variant="danger" icon={<Square className="h-3.5 w-3.5" />} loading={busy === 'monitor'} onClick={stopMonitor}>
              截止并归档
            </Button>
          ) : (
            <Button variant="success" icon={<Play className="h-3.5 w-3.5" />} loading={busy === 'monitor'} onClick={startMonitor}>
              一键开启监控
            </Button>
          )
        }
      >
        <div className="flex flex-wrap items-center gap-x-6 gap-y-3">
          <div className="flex items-center gap-2">
            {monitorOn ? (
              <Badge tone="green" dot>
                监控运行中{running ? ` · Run #${running.id}` : ''}
              </Badge>
            ) : (
              <Badge tone="slate">监控已停止</Badge>
            )}
            {ov && !ov.settings.monitor_enabled && ov.scheduler.current_run && (
              <Badge tone="amber">存在未关闭批次</Badge>
            )}
          </div>

          <label className="flex items-center gap-2 text-xs text-slate-500">
            抓取周期
            <Select value={intervalMin} onChange={(e) => setIntervalMin(Number(e.target.value))} disabled={monitorOn} className="w-24">
              {INTERVALS.map((m) => (
                <option key={m} value={m}>
                  {m} 分钟
                </option>
              ))}
            </Select>
          </label>

          <Switch checked={autoAnalyze} onChange={setAutoAnalyze} label="自动 AI 分析" hint="无外部 Agent 时用 LLM/本地引擎兜底" disabled={monitorOn} />

          <div className="ml-auto flex flex-wrap items-center gap-4 text-xs text-slate-500">
            {running && (
              <>
                <span>
                  已运行 <b className="text-slate-700">{duration(running.started_at)}</b>
                </span>
                <span title="调度线程每 20 秒轻 tick（刷新报价/计数），按周期重 tick（派发任务/自动分析）">
                  心跳 <b className="text-slate-700">{fmtAgo(running.last_tick_at)}</b>
                  <span className="text-slate-400"> · {running.tick_count} 次</span>
                </span>
                <span title="到期待抓取的公司数（等待 AI Agent 来领取）">
                  待抓 <b className="text-slate-700">{ov?.stats.tasks_pending ?? '—'}</b> 家
                </span>
                <span>
                  事件 <b className="text-slate-700">{running.events_found}</b> 条
                </span>
                <span>
                  建议 <b className="text-slate-700">{running.analyses_done}</b> 条
                </span>
                <span>
                  Agent <b className="text-slate-700">{seenAgents.length ? seenAgents.join(' / ') : '暂无接入'}</b>
                </span>
              </>
            )}
            <span>
              累计事件 <b className="text-slate-700">{ov?.stats.events_total ?? '—'}</b>
            </span>
            <span>
              累计建议 <b className="text-slate-700">{ov?.stats.analyses_total ?? '—'}</b>
            </span>
          </div>
        </div>
      </Card>
      <div className="grid min-h-0 flex-1 grid-cols-12 gap-3">
        <div className="col-span-2 flex min-h-0 flex-col">
      {/* 观察标的 */}
      <Card className="flex min-h-0 flex-1 flex-col"
        bodyClass="min-h-0 flex-1 overflow-y-auto"
        title="观察标的（美股核心公司）"
        subtitle={`${ov?.stats.companies_enabled ?? 0} / ${ov?.stats.companies_total ?? 0} 启用中 · 数量不限`}
        actions={
          <div className="flex items-center gap-1.5">
            <Button
              size="sm"
              variant="ghost"
              icon={<RefreshCw className="h-3.5 w-3.5" />}
              loading={busy === 'sync-watch'}
              title="把行情页关注列表的全部标的同步进来（已有的跳过）"
              onClick={() =>
                act('sync-watch', () => api.post('/intel/companies/sync-watchlist'), '已与关注列表同步').then(() => loadOverview())
              }
            >
              ⇄ 同步关注
            </Button>
            <Button size="sm" icon={<Plus className="h-3.5 w-3.5" />} onClick={() => setAddOpen(true)}>
              添加
            </Button>
          </div>
        }
      >
        <div className="grid grid-cols-1 gap-2">
          {(ov?.companies ?? []).map((c) => {
            const selected = evFilter === c.symbol
            return (
              <div
                key={c.id}
                onClick={() => setEvFilter(selected ? '' : c.symbol)}
                title="点击查看该公司的专属时间线"
                className={`group flex cursor-pointer items-start gap-2 rounded-lg border p-2.5 transition-all ${selected ? 'border-brand-400 bg-brand-50/50 ring-1 ring-brand-300' : c.enabled ? 'border-slate-200 bg-white hover:border-brand-200' : 'border-dashed border-slate-200 bg-slate-50 opacity-70'}`}
              >
                <span onClick={(e) => e.stopPropagation()}>
                  <Switch checked={c.enabled} onChange={(v) => act(`c-${c.id}`, () => api.put(`/intel/companies/${c.id}`, { enabled: v }), '已更新')} />
                </span>
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-semibold text-slate-800">{c.symbol}</span>
                    <span className="truncate text-xs text-slate-400">{c.name}</span>
                    {selected && <Badge tone="brand">时间线</Badge>}
                  </div>
                  <div className="mt-0.5 truncate text-[11px] text-slate-400">
                    {c.theme || '—'} · 抓取：{c.last_scrape_at ? fmtAgo(c.last_scrape_at) : '从未'}
                  </div>
                </div>
                <div className="flex shrink-0 items-center gap-0.5 opacity-0 transition-opacity group-hover:opacity-100">
                  <button
                    title={`立即分析 ${c.symbol}（基于最近事件 + 量化快照）`}
                    className="rounded p-1.5 text-brand-600 hover:bg-brand-50"
                    onClick={(e) => { e.stopPropagation(); analyzeNow(c.symbol) }}
                  >
                    <Zap className="h-3.5 w-3.5" />
                  </button>
                  <button
                    title="移除"
                    className="rounded p-1.5 text-slate-400 hover:bg-rose-50 hover:text-rose-600"
                    onClick={(e) => { e.stopPropagation(); act(`d-${c.id}`, () => api.del(`/intel/companies/${c.id}`), '已移除') }}
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                </div>
              </div>
            )
          })}
        </div>
      </Card>
        </div>
        <div className="col-span-7 flex min-h-0 flex-col">
        <Card
          className="flex min-h-0 flex-1 flex-col"
          bodyClass="min-h-0 flex-1 overflow-y-auto"
          title={evFilter ? `${evFilter} · 关键节点时间线` : '项目关键节点 · 事件时间线'}
          subtitle={evFilter ? '新闻沿时间轴串联，最新在上；AI 判定节点嵌于顶端' : '点击上方公司卡片可进入该公司专属时间线视图'}
          actions={
            <div className="flex items-center gap-2">
              <Select value={evFilter} onChange={(e) => setEvFilter(e.target.value)} className="w-32">
                <option value="">全部公司</option>
                {(ov?.companies ?? []).map((c) => (
                  <option key={c.id} value={c.symbol}>
                    {c.symbol}
                  </option>
                ))}
              </Select>
              <Button size="sm" variant="ghost" icon={<RefreshCw className="h-3.5 w-3.5" />} onClick={() => { loadEvents(); loadAnalyses() }} />
              <Button
                size="sm"
                variant="ghost"
                title="放大时间线（大弹窗查看更多信息）"
                onClick={() => setZoomOpen(true)}
              >
                ⤢ 放大
              </Button>
            </div>
          }
         
        >
          {events.length === 0 ? (
            <Empty icon={<Satellite className="h-8 w-8" />} title="暂无事件节点" desc="开启监控并接入 AI Agent（或手动触发分析）后，抓取到的关键节点会出现在这里" />
          ) : evFilter ? (
            <TimelineView symbol={evFilter} events={events} analysis={analyses[0] ?? null} />
          ) : (
            <ul className="space-y-3">
              {events.map((e) => (
                <li key={e.id} className="relative rounded-lg border border-slate-100 bg-white p-3 pl-4" style={{ borderLeft: `3px solid ${sentimentColor(e.sentiment)}` }}>
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-sm font-semibold text-slate-800">{e.symbol}</span>
                    <Badge tone="blue">{e.category_cn || e.category}</Badge>
                    <span className="text-[11px] text-slate-400" title="影响度">
                      {'★'.repeat(clampImpact(e.impact))}
                      {'☆'.repeat(5 - clampImpact(e.impact))}
                    </span>
                    {e.occurred_on && <span className="text-[11px] text-slate-400">事发 {e.occurred_on}</span>}
                    <span className="ml-auto flex items-center gap-2">
                      <Badge tone="violet">{e.agent || 'unknown'}</Badge>
                      <button
                        title="删除该节点"
                        className="rounded p-1 text-slate-300 hover:bg-rose-50 hover:text-rose-600"
                        onClick={() => act(`e-${e.id}`, () => api.del(`/intel/events/${e.id}`), '节点已删除')}
                      >
                        <Trash2 className="h-3 w-3" />
                      </button>
                    </span>
                  </div>
                  <p className="mt-1.5 text-sm text-slate-700">{e.title}</p>
                  {e.summary && <p className="mt-1 line-clamp-3 text-xs leading-relaxed text-slate-500">{e.summary}</p>}
                  <div className="mt-1.5 flex items-center gap-2 text-[11px] text-slate-400">
                    {e.source_url ? (
                      <a href={e.source_url} target="_blank" rel="noreferrer" className="truncate text-brand-600 hover:underline">
                        {e.source_name || e.source_url}
                      </a>
                    ) : (
                      <span>{e.source_name || '来源未提供'}</span>
                    )}
                    <span className="ml-auto">提交 {fmtAgo(e.created_at)}</span>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </Card>
        </div>
        <div className="col-span-3 flex min-h-0 flex-col gap-3 overflow-y-auto pr-0.5">
      {/* AI 接入（显式：用户要求 prompt 常驻可见） */}
      <Card
        className="shrink-0"
        title="AI Agent 接入"
        subtitle="把提示词粘给 WorkBuddy / Claude Code / Codex 即开始抓取 · Bridge 与交易账户完全隔离">

        {!guide ? (
          <Empty title="指南加载中…" />
        ) : (
          <div className="space-y-3">
            <Alert tone="info">{guide.security_note}</Alert>
            <div className="grid grid-cols-1 gap-3 lg:grid-cols-3">
              <div className="rounded-lg border border-slate-200 bg-slate-50 p-3 text-xs">
                <div className="mb-1 font-semibold text-slate-600">Bridge 地址</div>
                <code className="block break-all text-slate-700">{guide.base_url}/api/intel/bridge/*</code>
                <div className="mb-1 mt-2 font-semibold text-slate-600">
                  {guide.token_header}（<button className="text-brand-600 hover:underline" onClick={() => copy(guide.token, 'Token')}>复制</button>）
                </div>
                <code className="block break-all text-slate-700">{guide.token.slice(0, 18)}…</code>
                <Button
                  size="sm"
                  variant="ghost"
                  className="mt-2"
                  loading={busy === 'token'}
                  onClick={() => act('token', () => api.post('/intel/bridge-token/reset'), 'Token 已重置（旧 Token 立即失效）').then(() => api.get<Guide>('/intel/bridge/guide').then(setGuide))}
                >
                  重置 Token
                </Button>
              </div>
              <div className="lg:col-span-2 flex flex-col gap-2">
                <p className="text-xs text-slate-500">
                  点击按钮把对应 Agent 的完整提示词复制到剪贴板，或打开弹窗多选后一键复制多套。
                </p>
                <div className="flex flex-wrap gap-2">
                  {['workbuddy', 'claude_code', 'codex'].map((k) => (
                    <Button
                      key={k}
                      size="sm"
                      variant="ghost"
                      icon={<Copy className="h-3.5 w-3.5" />}
                      onClick={() => copy(guide.prompts[k], PROMPT_LABEL[k] + ' 提示词')}
                    >
                      复制 {PROMPT_LABEL[k]}
                    </Button>
                  ))}
                  <Button size="sm" variant="primary" icon={<Bot className="h-3.5 w-3.5" />} onClick={() => setPromptOpen(true)}>
                    多选 / 预览提示词
                  </Button>
                </div>
              </div>
            </div>
          </div>
        )}
      </Card>
        <Card className="flex shrink-0 flex-col"
 title="AI 买入建议" subtitle="事件面 + 量化快照 → 结构化建议（红=看多 绿=看空，跟随配色习惯）" bodyClass="min-h-0 flex-1 space-y-3 overflow-y-auto">
          {analyses.length === 0 ? (
            <Empty icon={<Bot className="h-8 w-8" />} title="暂无建议" desc="开启监控或点击观察标上的⚡立即分析" />
          ) : (
            analyses.map((a) => (
              <div key={a.id} className="rounded-lg border border-slate-100 bg-white p-3">
                <div className="flex items-center gap-2">
                  <span className="text-sm font-semibold text-slate-800">{a.symbol}</span>
                  <span className="rounded px-2 py-0.5 text-[11px] font-semibold text-white" style={{ background: recBg(a.recommendation) }}>
                    {REC_LABEL[a.recommendation]}
                  </span>
                  <span className="ml-auto text-[11px] text-slate-400">{fmtAgo(a.created_at)}</span>
                </div>
                <div className="mt-2">
                  <div className="flex items-center justify-between text-[11px] text-slate-400">
                    <span>置信度</span>
                    <span>
                      {a.confidence.toFixed(0)}% · 建议仓位 {a.position_pct}% · {a.engine === 'agent' ? '外部 Agent' : a.engine === 'llm' ? 'LLM' : '本地引擎'}
                    </span>
                  </div>
                  <div className="mt-1">
                    <Progress value={a.confidence} max={100} />
                  </div>
                </div>
                {(a.event_score != null || (a.based_on_events?.length ?? 0) > 0) && (
                  <div className="mt-2 flex flex-wrap items-center gap-1.5 text-[11px]">
                    {a.event_score != null && (
                      <span className="rounded px-1.5 py-0.5 font-medium" style={{ background: `${a.event_score >= 0 ? upColor() : downColor()}1A`, color: a.event_score >= 0 ? upColor() : downColor() }}>
                        事件面 {a.event_score > 0 ? '+' : ''}{a.event_score}
                      </span>
                    )}
                    {(a.based_on_events?.length ?? 0) > 0 && <Badge tone="amber">依据 {a.based_on_events!.length} 条近期事件</Badge>}
                  </div>
                )}
                {a.thesis && <p className="mt-2 text-xs leading-relaxed text-slate-600">{a.thesis}</p>}
                {a.based_on_events && a.based_on_events.length > 0 && (
                  <details className="mt-1.5">
                    <summary className="cursor-pointer text-[11px] text-brand-600 hover:underline">查看依据的事件节点</summary>
                    <ul className="mt-1 space-y-0.5 border-l-2 border-slate-100 pl-2.5">
                      {a.based_on_events.map((id) => {
                        const ev = events.find((x) => x.id === id)
                        return (
                          <li key={id} className="truncate text-[11px] text-slate-500">
                            {ev ? (
                              <>
                                <span className="text-slate-400">{ev.occurred_on || ''} </span>
                                {ev.title}
                              </>
                            ) : (
                              `事件 #${id}（切换到该公司时间线可查看）`
                            )}
                          </li>
                        )
                      })}
                    </ul>
                  </details>
                )}
                {a.catalysts && (
                  <p className="mt-1.5 text-[11px] text-slate-500">
                    <b className="text-slate-600">催化剂：</b>
                    {a.catalysts}
                  </p>
                )}
                {a.risks && (
                  <p className="mt-1 text-[11px] text-slate-500">
                    <b className="text-slate-600">风险：</b>
                    {a.risks}
                  </p>
                )}
                {a.invalidation && (
                  <p className="mt-1 text-[11px] text-rose-500/90">
                    <b>失效条件：</b>
                    {a.invalidation}
                  </p>
                )}
                {a.outcome_checked_at && a.outcome_return != null && (
                  <div className="mt-2 flex items-center gap-1.5 text-[11px]">
                    <span
                      className="rounded px-1.5 py-0.5 font-semibold text-white"
                      style={{ background: a.outcome_hit ? upColor() : downColor() }}
                    >
                      7 天对账 {a.outcome_return > 0 ? '+' : ''}{a.outcome_return}% {a.outcome_hit ? '✓ 命中' : a.outcome_hit === false ? '✗ 未中' : '— 平'}
                    </span>
                    {a.outcome_price != null && <span className="text-slate-400">验证价 {a.outcome_price}</span>}
                  </div>
                )}
                {a.price_at_analysis > 0 && <p className="mt-1 text-[11px] text-slate-400">分析时价格 {a.price_at_analysis} · Agent {a.agent}</p>}
              </div>
            ))
          )}
        </Card>
      {/* 建议验证 */}
      <VerifyCard />
      <details className="shrink-0 rounded-xl border border-slate-200 bg-white">
        <summary className="cursor-pointer px-4 py-2.5 text-sm font-semibold text-slate-700">📂 历史批次与归档报告</summary>
        <div className="px-3 pb-3">
      {/* 历史批次 */}

        {(ov?.runs ?? []).length === 0 ? (
          <Empty title="还没有批次记录" desc="点击「一键开启监控」开始第一批" />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-slate-200 text-left text-slate-400">
                  <th className="py-2 pr-3 font-medium">批次</th>
                  <th className="py-2 pr-3 font-medium">状态</th>
                  <th className="py-2 pr-3 font-medium">运行窗口</th>
                  <th className="py-2 pr-3 font-medium">事件 / 建议</th>
                  <th className="py-2 pr-3 font-medium">参与 Agent</th>
                  <th className="py-2 pr-3 font-medium">报告</th>
                </tr>
              </thead>
              <tbody>
                {(ov?.runs ?? []).map((r) => {
                  let agents: string[] = []
                  try {
                    agents = JSON.parse(r.agents_seen || '[]')
                  } catch { /* ignore */ }
                  return (
                    <tr key={r.id} className="border-b border-slate-50 text-slate-600">
                      <td className="py-2 pr-3 font-semibold text-slate-700">#{r.id}</td>
                      <td className="py-2 pr-3">
                        {r.status === 'running' ? (
                          <Badge tone="green" dot>运行中</Badge>
                        ) : r.status === 'finished' ? (
                          <Badge tone="slate">已归档</Badge>
                        ) : (
                          <Badge tone="amber">中断收尾</Badge>
                        )}
                      </td>
                      <td className="py-2 pr-3">
                        {fmtUtc(r.started_at)} → {r.ended_at ? fmtUtc(r.ended_at) : '进行中'}
                      </td>
                      <td className="py-2 pr-3">
                        {r.events_found} / {r.analyses_done}
                      </td>
                      <td className="py-2 pr-3">{agents.length ? agents.join('、') : '—'}</td>
                      <td className="py-2 pr-3">
                        <Button size="sm" variant="ghost" icon={<FileText className="h-3.5 w-3.5" />} onClick={() => viewReport(r.id)}>
                          查看
                        </Button>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
            </div>
          </details>
        </div>
      </div>
      {/* 报告弹窗 */}
      <Modal
        open={!!report}
        onClose={() => setReport(null)}
        title={`批次报告 · Run #${report?.id ?? ''}`}
        width="max-w-3xl"
        footer={
          <>
            <Button icon={<Copy className="h-3.5 w-3.5" />} onClick={() => report && copy(report.md, '报告')}>
              复制
            </Button>
            <Button variant="primary" icon={<Download className="h-3.5 w-3.5" />} onClick={downloadReport}>
              下载 .md
            </Button>
          </>
        }
      >
        <pre className="whitespace-pre-wrap text-xs leading-relaxed text-slate-700">{report?.md}</pre>
      </Modal>

      {/* Agent 提示词弹窗（多选 + 一键复制） */}
      <Modal
        open={promptOpen}
        onClose={() => setPromptOpen(false)}
        title="Agent 提示词 · 多选与一键复制"
        width="max-w-4xl"
        footer={
          <>
            <Button onClick={() => setPromptSel(['workbuddy', 'claude_code', 'codex'])}>全选</Button>
            <Button onClick={() => setPromptSel([])}>清空</Button>
            <Button
              variant="primary"
              icon={<Copy className="h-3.5 w-3.5" />}
              disabled={promptSel.length === 0 || !guide}
              onClick={() => {
                const merged = promptSel.map((k) => `===== ${PROMPT_LABEL[k]} =====\n\n${guide!.prompts[k] || ''}`).join('\n\n')
                copy(merged, `${promptSel.length} 套提示词`)
              }}
            >
              一键复制所选（{promptSel.length} 套）
            </Button>
          </>
        }
      >
        {!guide ? (
          <Empty title="指南加载中…" />
        ) : (
          <div className="space-y-3">
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-xs font-medium text-slate-500">选择 Agent（可多选）：</span>
              {['workbuddy', 'claude_code', 'codex'].map((k) => {
                const on = promptSel.includes(k)
                return (
                  <button
                    key={k}
                    onClick={() => setPromptSel(on ? promptSel.filter((x) => x !== k) : [...promptSel, k])}
                    className={`rounded-lg border px-3 py-1.5 text-xs font-medium transition-colors ${
                      on
                        ? 'border-brand-400 bg-brand-50 text-brand-700 ring-1 ring-brand-300'
                        : 'border-slate-200 text-slate-600 hover:border-brand-300 hover:bg-slate-50'
                    }`}
                  >
                    {on ? '✓ ' : ''}{PROMPT_LABEL[k]}
                  </button>
                )
              })}
              {guide.token && (
                <span className="ml-auto text-[11px] text-slate-400">
                  Token 已内嵌于提示词（<button className="text-brand-600 hover:underline" onClick={() => copy(guide.token, 'Token')}>单独复制</button>）
                </span>
              )}
            </div>
            <div className="space-y-3">
              {promptSel.length === 0 ? (
                <Empty title="未选择任何 Agent" desc="点击上方标签选择要复制的提示词" />
              ) : (
                promptSel.map((k) => (
                  <div key={k} className="relative">
                    <div className="mb-1 flex items-center gap-2 text-[11px] font-semibold text-slate-600">
                      {PROMPT_LABEL[k]}
                      <button className="ml-auto rounded p-1 text-slate-400 hover:bg-slate-100 hover:text-brand-600" title="复制这一套" onClick={() => copy(guide.prompts[k], PROMPT_LABEL[k] + ' 提示词')}>
                        <Copy className="h-3 w-3" />
                      </button>
                    </div>
                    <pre className="max-h-52 overflow-y-auto whitespace-pre-wrap rounded-lg bg-slate-900 p-3 text-[11px] leading-relaxed text-slate-100">{guide.prompts[k]}</pre>
                  </div>
                ))
              )}
            </div>
          </div>
        )}
      </Modal>

      {/* 添加观察标的（弹窗表单） */}
      <Modal
        open={addOpen}
        onClose={() => setAddOpen(false)}
        title="添加观察标的"
        footer={
          <>
            <Button onClick={() => setAddOpen(false)}>取消</Button>
            <Button variant="primary" icon={<Plus className="h-3.5 w-3.5" />} loading={busy === 'add'} onClick={addCompany}>
              确认添加
            </Button>
          </>
        }
      >
        <div className="space-y-3">
          <Field label="标的代码（必填）">
            <Input
              value={addForm.symbol}
              onChange={(e) => setAddForm({ ...addForm, symbol: e.target.value.toUpperCase() })}
              onKeyDown={(e) => e.key === 'Enter' && addCompany()}
              placeholder="NVDA / BRK.B / 0700.HK"
            />
          </Field>
          <Field label="公司名称（选填）">
            <Input value={addForm.name} onChange={(e) => setAddForm({ ...addForm, name: e.target.value })} placeholder="NVIDIA" />
          </Field>
          <Field label="观察主题（选填）">
            <Input value={addForm.theme} onChange={(e) => setAddForm({ ...addForm, theme: e.target.value })} placeholder="AI 算力 / 减肥药 / 云…" />
          </Field>
          <Field label="关注要点（选填，指导 AI Agent 抓取方向）">
            <textarea
              value={addForm.focus}
              onChange={(e) => setAddForm({ ...addForm, focus: e.target.value })}
              rows={3}
              placeholder="例：数据中心 GPU 出货节奏、大厂资本开支、出口管制"
              className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-800 outline-none transition-colors focus:border-brand-400"
            />
          </Field>
          <p className="text-[11px] text-slate-400">添加后立即进入观察列表；开启监控后外部 AI Agent 会按主题/要点定向检索该公司新闻。</p>
        </div>
      </Modal>

      {/* 时间线放大弹窗（近全屏；图只保留 TimelineView 内置的那张，避免重复） */}
      <Modal
        open={zoomOpen}
        onClose={() => setZoomOpen(false)}
        title={evFilter ? `${evFilter} · 关键节点时间线（放大视图）` : '请先在左侧选择一家公司'}
        width="!max-w-[96vw]"
        className="h-[94vh] flex flex-col"
        bodyClass="min-h-0 flex-1 overflow-y-auto"
      >
        {evFilter ? (
          <div className="space-y-4 pr-1">
            <TimelineView
              symbol={evFilter}
              events={events.filter((e) => e.symbol === evFilter)}
              analysis={analyses.find((a) => a.symbol === evFilter) ?? null}
              big
            />
          </div>
        ) : (
          <Empty icon={<Satellite className="h-8 w-8" />} title="未选择公司" desc="先在左侧观察标的列表点击一家公司，再点放大" />
        )}
      </Modal>

    </div>
  )
}
