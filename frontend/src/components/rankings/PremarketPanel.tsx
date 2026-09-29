import { Bot, Clock, Loader2, Newspaper, RefreshCw, TrendingDown, TrendingUp } from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'
import { Badge, Button, useToast } from '../ui'
import { api } from '../../lib/api'
import { upColor, downColor } from '../../lib/format'

/**
 * 盘前监控面板（美东 04:00–09:30）。
 *
 * 数据：`GET /market/rankings/premarket` —— 盘前价 / 涨跌幅 / 盘前量 + 新闻标题
 * （新闻由后端并发抓 yahoo-rss，「为什么动」比「动了多少」值钱）。
 * AI 综述：`POST /market/rankings/premarket/analyze` —— top movers + 新闻喂 LLM，
 * 输出盘前主线 / 重点关注 / 风险；LLM 失败自动降级本地统计（engine="local"）。
 *
 * 盘前时段（is_premarket=true）默认每 30 秒自动刷新；非盘前时段 2 分钟（可在
 * 「自动刷新」下拉调整间隔或关闭）。手动「刷新」按钮强制后端立即重抓全池盘前价。
 */

interface PreRow {
  symbol: string
  name: string
  name_cn?: string
  sector?: string
  pre_price: number
  prev_close: number
  pre_pct: number
  pre_vol: number
  pre_time?: string
  news?: { headline: string; source: string; published: string }[]
}

interface PreResp {
  session: string
  is_premarket: boolean
  updated: string
  quotes_updated?: string | null
  age_sec?: number | null
  stale?: boolean
  refreshing?: boolean
  covered?: number
  note: string
  gainers: PreRow[]
  losers: PreRow[]
  threshold: number
}

interface AnalyzeResp {
  engine: 'llm' | 'local'
  model: string
  summary: string
  updated: string
  session: string
}

const VOL_HINT = 50_000            // 盘前量低于此值的异动可信度低
// 页面自动刷新间隔（秒）：-1 关闭；0 = 智能（盘前 30s / 其他 2min）
const POLL_CHOICES = [-1, 0, 30, 60, 120, 300]

function Row({ r, onOpen }: { r: PreRow; onOpen: (s: string) => void }) {
  const news = (r.news || [])[0]
  return (
    <div className="rounded-lg border border-slate-100 bg-white p-2 transition-colors hover:border-brand-200">
      <div className="flex items-baseline gap-1.5">
        <button
          onClick={() => onOpen(r.symbol)}
          className="text-xs font-semibold text-slate-800 hover:text-brand-700 hover:underline"
          title="查看公司档案"
        >
          {r.symbol}
        </button>
        <span className="truncate text-[10px] text-slate-400">{r.name_cn || r.name}</span>
        <span
          className="num ml-auto text-xs font-semibold tabular-nums"
          style={{ color: r.pre_pct >= 0 ? upColor() : downColor() }}
        >
          {r.pre_pct > 0 ? '+' : ''}{r.pre_pct.toFixed(1)}%
        </span>
      </div>
      <div className="mt-0.5 flex items-center gap-2 text-[10px] text-slate-400">
        <span className="num tabular-nums">{r.prev_close.toFixed(2)} → {r.pre_price.toFixed(2)}</span>
        {r.pre_vol > 0 ? (
          <span
            className={`num tabular-nums ${r.pre_vol < VOL_HINT ? 'text-amber-600' : ''}`}
            title={r.pre_vol < VOL_HINT ? '盘前量偏小，异动可信度低' : '盘前累计成交量'}
          >
            量 {r.pre_vol >= 1e6 ? `${(r.pre_vol / 1e6).toFixed(1)}M` : `${Math.round(r.pre_vol / 1e3)}K`}
          </span>
        ) : (
          <span title="数据源不提供盘前成交量">盘前量未知</span>
        )}
      </div>
      {news && (
        <p className="mt-1 line-clamp-2 text-[10px] leading-4 text-slate-500" title={news.headline}>
          <Newspaper className="mr-1 inline h-2.5 w-2.5 align-[-1px] text-slate-300" />
          {news.headline}
        </p>
      )}
    </div>
  )
}

export default function PremarketPanel({ onOpenProfile }: { onOpenProfile: (s: string) => void }) {
  const [data, setData] = useState<PreResp | null>(null)
  const [loading, setLoading] = useState(true)
  const [analyzing, setAnalyzing] = useState(false)
  const [ai, setAi] = useState<AnalyzeResp | null>(null)
  const [manualBusy, setManualBusy] = useState(false)
  const [pollSec, setPollSec] = useState<number>(() => {
    const n = Number(localStorage.getItem('qd_premarket_poll'))
    return POLL_CHOICES.includes(n) ? n : 0
  })
  const toast = useToast()
  const timer = useRef(0)

  const load = useCallback(async (force = false) => {
    try {
      const r = await api.get<PreResp>(
        `/market/rankings/premarket?limit=12${force ? '&force=true' : ''}`,
        45_000,
      )
      setData(r)
    } catch { /* 盘前数据拉不到不阻塞页面 */ } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
    if (pollSec < 0) return undefined       // 自动刷新已关闭（手动模式）
    // 0 = 智能：盘前时段 30 秒，其余时段 2 分钟
    const period = (pollSec || (data?.is_premarket ? 30 : 120)) * 1000
    timer.current = window.setInterval(() => load(), period)
    return () => window.clearInterval(timer.current)
  }, [load, pollSec, data?.is_premarket])

  /** 手动刷新：强制后端立即重抓全池盘前数据（约 1~2 分钟后生效，错峰补拉）。 */
  const refreshNow = async () => {
    setManualBusy(true)
    try {
      await load(true)
      window.setTimeout(() => load(), 45_000)
      window.setTimeout(() => load(), 120_000)
    } finally {
      setManualBusy(false)
    }
  }

  const runAnalyze = async () => {
    setAnalyzing(true)
    try {
      const r = await api.post<AnalyzeResp>('/market/rankings/premarket/analyze', undefined, 150_000)
      setAi(r)
    } catch (e: any) {
      toast('error', e?.message || 'AI 解读失败')
    } finally {
      setAnalyzing(false)
    }
  }

  const sessionBadge = data?.is_premarket
    ? <Badge tone="red" dot>盘前监控中</Badge>
    : <Badge tone="slate">盘前快照</Badge>

  return (
    <div className="rounded-xl border border-slate-200 bg-white p-3">
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <Clock className="h-3.5 w-3.5 text-brand-600" />
        <span className="text-xs font-semibold text-slate-700">盘前监控</span>
        {sessionBadge}
        <span className="text-[11px] text-slate-400">{data?.note || '盘前时段：美东 04:00–09:30（北京时间 16:00–21:30 夏令时）'}</span>
        {data?.refreshing && <Loader2 className="h-3 w-3 animate-spin text-slate-300" />}
        <div className="ml-auto flex items-center gap-2">
          <span className="text-[10px] text-slate-400" title="盘前数据真正抓取完成的时刻（非页面刷新时刻）">
            数据更新于 <span className="num text-slate-600">{data?.quotes_updated?.slice(11, 16) || '—'}</span>
          </span>
          <span className="inline-flex items-center gap-1 text-[10px] text-slate-400">
            自动刷新
            <select
              value={pollSec}
              onChange={(e) => {
                const v = Number(e.target.value)
                setPollSec(v)
                localStorage.setItem('qd_premarket_poll', String(v))
              }}
              className="rounded border border-slate-200 bg-white px-1 py-0.5 text-[11px] text-slate-700"
              title="页面轮询间隔；「智能」= 盘前时段 30 秒 / 其他时段 2 分钟"
            >
              {POLL_CHOICES.map((s) => (
                <option key={s} value={s}>
                  {s < 0 ? '关闭' : s === 0 ? '智能' : s < 60 ? `${s} 秒` : `${s / 60} 分钟`}
                </option>
              ))}
            </select>
          </span>
          <Button
            variant="ghost"
            icon={<Bot className="h-3.5 w-3.5" />}
            onClick={runAnalyze}
            disabled={analyzing || !data || (!data.gainers.length && !data.losers.length)}
            title="AI 汇总盘前主线、值得关注的标的与风险"
          >
            {analyzing ? '解读中…' : 'AI 盘前解读'}
          </Button>
          <Button
            variant="ghost"
            icon={manualBusy ? <Loader2 className="h-3 w-3 animate-spin" /> : <RefreshCw className="h-3 w-3" />}
            onClick={refreshNow}
            disabled={manualBusy}
            title="强制后端立即重抓全池盘前行情（约 1~2 分钟后生效）"
          >
            刷新
          </Button>
        </div>
      </div>

      {loading && !data ? (
        <p className="py-3 text-[11px] text-slate-400">正在抓取盘前数据（全池 5 分钟 K 线，约 1~2 分钟）…</p>
      ) : !data ? (
        <p className="py-3 text-[11px] text-slate-400">盘前数据暂不可用 —— 稍后自动重试。</p>
      ) : (
        <>
          <div className="grid gap-2 md:grid-cols-2">
            <div>
              <div className="mb-1 flex items-center gap-1 text-[11px] font-medium" style={{ color: upColor() }}>
                <TrendingUp className="h-3 w-3" />盘前上涨（≥{data.threshold}%）
              </div>
              <div className="space-y-1.5">
                {data.gainers.length === 0
                  ? <p className="rounded-lg border border-dashed border-slate-200 px-2 py-3 text-[11px] text-slate-400">暂无触发阈值的上涨 —— 可降低阈值</p>
                  : data.gainers.slice(0, 8).map((r) => <Row key={r.symbol} r={r} onOpen={onOpenProfile} />)}
              </div>
            </div>
            <div>
              <div className="mb-1 flex items-center gap-1 text-[11px] font-medium" style={{ color: downColor() }}>
                <TrendingDown className="h-3 w-3" />盘前下跌（≤ -{data.threshold}%）
              </div>
              <div className="space-y-1.5">
                {data.losers.length === 0
                  ? <p className="rounded-lg border border-dashed border-slate-200 px-2 py-3 text-[11px] text-slate-400">暂无触发阈值的下跌</p>
                  : data.losers.slice(0, 8).map((r) => <Row key={r.symbol} r={r} onOpen={onOpenProfile} />)}
              </div>
            </div>
          </div>

          {ai && (
            <div className="mt-2 rounded-lg border border-brand-100 bg-brand-50/40 p-2.5">
              <div className="mb-1 flex items-center gap-1.5 text-[11px] font-medium text-brand-700">
                <Bot className="h-3 w-3" />AI 盘前综述
                <Badge tone={ai.engine === 'llm' ? 'brand' : 'slate'}>
                  {ai.engine === 'llm' ? ai.model || 'LLM' : '本地统计（AI 暂不可用）'}
                </Badge>
                <span className="ml-auto text-[10px] text-slate-400">{ai.updated}</span>
              </div>
              <p className="whitespace-pre-wrap text-[11px] leading-5 text-slate-600">{ai.summary}</p>
            </div>
          )}

          <p className="mt-2 text-[10px] leading-4 text-slate-400">
            盘前价格来自免费数据源（5 分钟 K 线），可能延迟数分钟；盘前量偏小的异动可信度低。
            新闻标题仅作线索，请点开公司档案与新闻原文核实后再做决策。本面板不构成投资建议。
          </p>
        </>
      )}
    </div>
  )
}
