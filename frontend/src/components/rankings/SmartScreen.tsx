/**
 * 智能选股（自然语言 → 筛选条件）
 * ================================
 * 用户用一句话描述想找什么，后端 `smart_screen` 任务把它翻译成**结构化筛选条件**，
 * 这里把条件渲染成可删除的 chips，用户确认后一键应用回榜单的筛选面板。
 *
 * 为什么不用通用的 `AIAssist` 卡片：这个功能要的是**结构化结果**（能变成筛选条件
 * 作用到页面上），不是一段自然语言文本，所以需要自定义渲染。但它同样走
 * `lib/ai.ts` 的统一入口 `aiAssist()`，因此网关/密钥/模型与其它接入点完全一致。
 *
 * 安全边界：AI 返回的字段必须命中白名单，数值超范围会被钳制并在界面上说明 ——
 * 绝不让模型输出的野字段/野数值静默作用到筛选上。
 */
import { useState } from 'react'
import { Sparkles, Wand2, X } from 'lucide-react'
import { aiAssist, type AiTaskResult } from '../../lib/ai'
import { RANKING_COLUMNS } from '../../lib/rankingColumns'
import { Alert, Badge, Button, Card, Loading } from '../ui'
import type { RankingFiltersValue } from './RankingFilters'

/* ---------------- 字段白名单（与后端 ai_tasks_screen._SCREEN_FIELDS 对齐） ---------------- */
const NUM_RANGES: Record<string, [number, number]> = {
  peMin: [-1e4, 1e4], peMax: [-1e4, 1e4], pbMax: [0, 1e4], capMin: [0, 1e6],
  divMin: [0, 100], roeMin: [-1e4, 1e4], fromHighMax: [-100, 0],
  rsiMin: [0, 100], rsiMax: [0, 100], volMax: [0, 500], betaMax: [-5, 10],
  req1yMin: [-100, 1000], excessMin: [-100, 1000],
}
const BOOL_KEYS = ['excludeLoss', 'onlyBull'] as const
const LABELS: Record<string, string> = {
  peMin: 'PE ≥', peMax: 'PE ≤', pbMax: 'PB ≤', capMin: '市值 ≥', divMin: '股息 ≥',
  roeMin: 'ROE ≥', fromHighMax: '距 52 周高 ≤', rsiMin: 'RSI ≥', rsiMax: 'RSI ≤',
  volMax: '年化波动 ≤', betaMax: 'Beta ≤', req1yMin: '近 1 年 ≥', excessMin: '超额 SPY ≥',
  excludeLoss: '排除亏损', onlyBull: '均线多头排列', maPos: '200 日均线',
}
const UNITS: Record<string, string> = {
  capMin: '亿美元', divMin: '%', roeMin: '%', fromHighMax: '%',
  volMax: '%', req1yMin: '%', excessMin: '%',
}

export interface ScreenApply {
  filters: Partial<RankingFiltersValue>
  sector?: string
  sort?: string
  direction?: 'asc' | 'desc'
  view?: 'all' | 'pool'
}

/** 把 AI 返回的原始对象清洗成「只能命中白名单 + 数值在范围内」的安全条件。 */
function sanitize(raw: any, sectors: string[]): { filters: Record<string, string | boolean>; sector: string; sort: string; direction: 'asc' | 'desc'; view: 'all' | 'pool'; notes: string[] } {
  const filters: Record<string, string | boolean> = {}
  const notes: string[] = []
  const f = raw?.filters
  if (f && typeof f === 'object') {
    for (const [k, v] of Object.entries(f)) {
      if (k in NUM_RANGES) {
        const n = Number(v)
        if (!Number.isFinite(n)) {
          notes.push(`「${k}」不是有效数字，已忽略`)
          continue
        }
        const [lo, hi] = NUM_RANGES[k]
        const c = Math.min(hi, Math.max(lo, n))
        if (c !== n) notes.push(`「${k}」的 ${n} 超出合理范围，已收敛为 ${c}`)
        filters[k] = String(c)
      } else if ((BOOL_KEYS as readonly string[]).includes(k)) {
        filters[k] = !!v
      } else if (k === 'maPos') {
        if (v === 'above' || v === 'below') filters[k] = v
        else notes.push(`「200 日均线」取值 ${JSON.stringify(v)} 无效，已忽略`)
      } else {
        notes.push(`AI 返回了平台不支持的字段「${k}」，已忽略`)
      }
    }
  }
  let sector = typeof raw?.sector === 'string' ? raw.sector : ''
  if (sector && sectors.length > 0 && !sectors.includes(sector)) {
    notes.push(`AI 指定的行业「${sector}」不在当前行业列表里，已忽略`)
    sector = ''
  }
  const sortable = new Set(RANKING_COLUMNS.filter((c) => c.sortable).map((c) => c.key))
  let sort = typeof raw?.sort === 'string' ? raw.sort : ''
  if (sort && !sortable.has(sort)) {
    notes.push(`AI 指定的排序字段「${sort}」不是可排序列，已忽略`)
    sort = ''
  }
  // 方向必须保留：用户说「PE 从低到高」时 AI 会给 asc，硬编码 desc 会把语义反过来。
  const direction: 'asc' | 'desc' = raw?.direction === 'asc' ? 'asc' : 'desc'
  const view: 'all' | 'pool' = raw?.view === 'pool' ? 'pool' : 'all'
  return { filters, sector, sort, direction, view, notes }
}

function chipText(k: string, v: string | boolean): string {
  if (typeof v === 'boolean') return LABELS[k] || k
  if (k === 'maPos') return `${LABELS[k]} ${v === 'above' ? '站上' : '跌破'}`
  return `${LABELS[k] || k} ${v}${UNITS[k] || ''}`
}

const EXAMPLES = [
  '低估值高股息、RSI 不超买的金融股',
  '便宜的、ROE 高的科技股',
  '不要超买，趋势向上的大盘蓝筹',
  '最近跌得多、波动小的防御性标的',
]

export default function SmartScreen({
  sectors,
  onApply,
}: {
  sectors: string[]
  onApply: (patch: ScreenApply) => void
}) {
  const [query, setQuery] = useState('')
  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState('')
  const [res, setRes] = useState<AiTaskResult | null>(null)
  const [conds, setConds] = useState<Record<string, string | boolean> | null>(null)
  const [sector, setSector] = useState('')
  const [sort, setSort] = useState('')
  const [direction, setDirection] = useState<'asc' | 'desc'>('desc')
  const [view, setView] = useState<'all' | 'pool'>('all')
  const [notes, setNotes] = useState<string[]>([])

  const parse = async () => {
    const q = query.trim()
    if (!q) return
    setLoading(true)
    setErr('')
    setRes(null)
    setConds(null)
    try {
      const r = await aiAssist('smart_screen', {
        query: q,
        sectors,
        sorts: RANKING_COLUMNS.filter((c) => c.sortable).map((c) => c.key),
      })
      const s = sanitize(r.data, sectors)
      setRes(r)
      setConds(s.filters)
      setSector(s.sector)
      setSort(s.sort)
      setDirection(s.direction)
      setView(s.view)
      setNotes(s.notes)
    } catch (e: any) {
      setErr(e?.message || 'AI 解析失败')
    } finally {
      setLoading(false)
    }
  }

  const drop = (k: string) =>
    setConds((c) => {
      if (!c) return c
      const next = { ...c }
      delete next[k]
      return next
    })

  const isLLM = res?.engine === 'llm'
  const count = (conds ? Object.keys(conds).length : 0) + (sector ? 1 : 0) + (sort ? 1 : 0)
  const explain = typeof res?.data?.explain === 'string' ? res.data.explain : ''

  return (
    <Card
      title={
        <span className="flex items-center gap-2">
          <Wand2 className="h-4 w-4 text-violet-500" />
          智能选股
        </span>
      }
      subtitle="用一句话描述你想找什么，AI 把它翻译成下方筛选面板能直接用的条件"
    >
      <div className="space-y-3">
        <div className="flex flex-col gap-2 sm:flex-row sm:items-start">
          <textarea
            className="inp min-h-[44px] flex-1 resize-y"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) parse()
            }}
            placeholder="例如：找低估值、高股息、RSI 不超买的金融股（⌘/Ctrl + Enter 解析）"
          />
          <Button
            variant="primary"
            loading={loading}
            disabled={!query.trim()}
            onClick={parse}
            icon={<Sparkles className="h-3.5 w-3.5" />}
          >
            解析为条件
          </Button>
        </div>

        <div className="flex flex-wrap items-center gap-1.5">
          <span className="text-[11px] text-slate-400">试试：</span>
          {EXAMPLES.map((x) => (
            <button
              key={x}
              type="button"
              onClick={() => setQuery(x)}
              className="rounded-md bg-slate-100 px-2 py-1 text-[11px] text-slate-600 transition-colors hover:bg-brand-100 hover:text-brand-700"
            >
              {x}
            </button>
          ))}
        </div>

        {loading && <Loading label="AI 正在把你的需求翻译成筛选条件…" className="py-4" />}

        {!loading && err && (
          <Alert tone="danger" title="解析失败">
            {err}
          </Alert>
        )}

        {!loading && !err && res && conds && (
          <div className="space-y-2.5 rounded-xl border border-slate-200 bg-slate-50/60 p-3">
            <div className="flex flex-wrap items-center gap-2">
              <Badge tone={isLLM ? 'violet' : 'slate'} dot>
                {isLLM ? 'LLM 解析' : '本地规则解析'}
              </Badge>
              <span className="text-[11px] text-slate-500">共 {count} 个条件</span>
            </div>

            {res.llm_error && (
              <Alert tone="warn" title="大模型调用失败，已降级为本地规则解析">
                {res.llm_error}
              </Alert>
            )}

            {count === 0 ? (
              <Alert tone="info" title="没有解析出可用条件">
                {explain || '换一种更具体的说法再试，例如指明估值、股息、行业或技术面要求。'}
              </Alert>
            ) : (
              <>
                <div className="flex flex-wrap gap-1.5">
                  {sector && (
                    <span className="inline-flex items-center gap-1 rounded-full bg-brand-50 px-2 py-1 text-xs text-brand-700 ring-1 ring-brand-200">
                      行业：{sector}
                      <button onClick={() => setSector('')} title="移除" className="text-brand-400 hover:text-brand-700">
                        <X className="h-3 w-3" />
                      </button>
                    </span>
                  )}
                  {sort && (
                    <span className="inline-flex items-center gap-1 rounded-full bg-slate-100 px-2 py-1 text-xs text-slate-600">
                      按「{RANKING_COLUMNS.find((c) => c.key === sort)?.label ?? sort}」{direction === 'asc' ? '升序 ↑' : '降序 ↓'}
                      <button onClick={() => setSort('')} title="移除" className="text-slate-400 hover:text-slate-700">
                        <X className="h-3 w-3" />
                      </button>
                    </span>
                  )}
                  {Object.entries(conds).map(([k, v]) => (
                    <span
                      key={k}
                      className="inline-flex items-center gap-1 rounded-full bg-white px-2 py-1 text-xs text-slate-700 ring-1 ring-slate-200"
                    >
                      {chipText(k, v)}
                      <button onClick={() => drop(k)} title="移除该条件" className="text-slate-300 hover:text-rose-600">
                        <X className="h-3 w-3" />
                      </button>
                    </span>
                  ))}
                </div>

                {view === 'pool' && (
                  <p className="text-[11px] text-slate-500">
                    将同时切到「候选观察池」视图（只看综合评分达标的标的）。
                  </p>
                )}

                {explain && <p className="text-[11px] leading-5 text-slate-500">{explain}</p>}

                {notes.length > 0 && (
                  <ul className="space-y-0.5 text-[11px] leading-5 text-amber-700">
                    {notes.map((n, i) => (
                      <li key={i}>· {n}</li>
                    ))}
                  </ul>
                )}

                <div className="flex flex-wrap items-center gap-2 pt-0.5">
                  <Button
                    variant="primary"
                    size="sm"
                    onClick={() => onApply({ filters: conds as Partial<RankingFiltersValue>, sector, sort, direction, view })}
                  >
                    应用到筛选
                  </Button>
                  <Button size="sm" onClick={parse}>
                    重新解析
                  </Button>
                </div>
              </>
            )}
          </div>
        )}

        <p className="flex items-start gap-1.5 text-[10.5px] leading-relaxed text-slate-400">
          <Sparkles className="mt-0.5 h-3 w-3 shrink-0" />
          应用后条件会写入下方筛选面板，你可以再手动微调；AI 只负责翻译条件，不构成买卖信号。
        </p>
      </div>
    </Card>
  )
}
