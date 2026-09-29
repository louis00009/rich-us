/**
 * 事件流（重点优先）
 *
 * 旧实现把 200 条事件按入库时间平铺，所有卡片完全同构、impact 只用 11px 星星表示。
 * 实测近 3 天入库 587 条、其中 5★ 只有 22 条 —— 真正重要的被埋掉了。
 *
 * 现在：
 *   ① 默认按**确定性重要度**排序（后端算好返回），不是按时间；
 *   ② 三档视觉分级：重大（粗红边+大字号+为什么重要）/ 重要 / 可看；
 *   ③ 低影响条目**折叠**成紧凑行，默认不占版面（可一键展开）；
 *   ④ 筛选条覆盖 影响度 / 方向 / 时间 / 类别 / 阶段 / 内容类型 —— 想只看「近 3 天 4★以上的利空」一步到位。
 *   ⑤ **媒体评论单独成档**：媒体评论 / 行情播报 / 分析师调价（约占入库量 11%）不是公司自身事件，
 *      后端已把其重要度封顶到 40 分以下（永不进必读），前端再给「媒体」标记 + 内容类型筛选，
 *      让用户能把噪音一次滤掉，而不是靠肉眼在 200 条里挑。
 *
 * 结构（铁律 9 拆分，2026-09-29）：单条事件卡已抽到 `./EventCard.tsx`，
 * 本文件只保留编排（取数 + 筛选状态 + 列表布局）。
 */
import { useCallback, useEffect, useMemo, useState } from 'react'
import { ChevronDown, ChevronRight, Filter, RefreshCw } from 'lucide-react'
import { Button, Card, Empty, Select, Tabs, useToast } from '../ui'
import { api } from '../../lib/api'
import { EventCard } from './EventCard'
import { TimelineView } from './Timeline'
import {
  EVENT_CATEGORIES,
  type Analysis,
  type Company,
  type EventItem,
  fmtSince,
  MEDIA_OPTIONS,
  sentimentColor,
  STAGE_OPTIONS,
  type Tier,
  tierOf,
} from './types'

type SortKey = 'importance' | 'created'
const IMPACT_OPTIONS = [
  { key: '0', label: '全部影响度' },
  { key: '3', label: '3★ 以上' },
  { key: '4', label: '4★ 以上' },
  { key: '5', label: '仅 5★' },
]
const SINCE_OPTIONS = [
  { key: '0', label: '全部时间' },
  { key: '1', label: '今日/昨日' },
  { key: '3', label: '近 3 天' },
  { key: '7', label: '近 7 天' },
  { key: '30', label: '近 30 天' },
]
const SENTIMENT_OPTIONS = [
  { key: '', label: '全部方向' },
  { key: 'positive', label: '利好' },
  { key: 'negative', label: '利空' },
  { key: 'neutral', label: '中性' },
]

export default function EventFeed({
  companies,
  symbol,
  onSymbolChange,
  analyses,
  refreshToken,
  onZoom,
  onData,
}: {
  companies: Company[]
  symbol: string
  onSymbolChange: (s: string) => void
  analyses: Analysis[]
  refreshToken: number
  onZoom: () => void
  onData?: (items: EventItem[]) => void
}) {
  const toast = useToast()
  const [items, setItems] = useState<EventItem[]>([])
  const [loading, setLoading] = useState(false)
  const [sort, setSort] = useState<SortKey>('importance')
  const [minImpact, setMinImpact] = useState('0')
  const [sinceDays, setSinceDays] = useState('3')
  const [sentiment, setSentiment] = useState('')
  const [category, setCategory] = useState('')
  const [stage, setStage] = useState('')
  const [media, setMedia] = useState('')
  const [showLow, setShowLow] = useState(false)
  const [showFilters, setShowFilters] = useState(true)

  const load = useCallback(() => {
    setLoading(true)
    const qs = new URLSearchParams({ limit: '200', sort })
    if (symbol) qs.set('symbol', symbol)
    if (minImpact !== '0') qs.set('min_impact', minImpact)
    if (sinceDays !== '0') qs.set('since_days', sinceDays)
    if (sentiment) qs.set('sentiment', sentiment)
    if (category) qs.set('category', category)
    if (stage) qs.set('stage', stage)
    if (media) qs.set('media', media)
    api
      .get<{ items: EventItem[] }>(`/intel/events?${qs.toString()}`)
      .then((d) => {
        setItems(d.items)
        onData?.(d.items)
      })
      .catch((e) => toast('error', e.message))
      .finally(() => setLoading(false))
    // onData 由父级以 useCallback 稳定引用，不进依赖数组以免自激
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [symbol, sort, minImpact, sinceDays, sentiment, category, stage, media, toast])

  useEffect(load, [load, refreshToken])

  const remove = async (id: number) => {
    try {
      await api.del(`/intel/events/${id}`)
      toast('success', '节点已删除')
      load()
    } catch (e: any) {
      toast('error', e.message)
    }
  }

  const stats = useMemo(() => {
    const byTier = { critical: 0, high: 0, medium: 0, low: 0 } as Record<Tier, number>
    let pos = 0
    let neg = 0
    let impSum = 0
    let impN = 0
    let media = 0
    for (const e of items) {
      byTier[e.tier ?? tierOf(e.importance, e.impact)] += 1
      if (e.commentary) media += 1
      if (e.sentiment === 'positive') pos += 1
      else if (e.sentiment === 'negative') neg += 1
      if (e.importance != null) {
        impSum += e.importance
        impN += 1
      }
    }
    return { byTier, pos, neg, media, avgImp: impN ? impSum / impN : null }
  }, [items])

  const primary = items.filter((e) => {
    const t = e.tier ?? tierOf(e.importance, e.impact)
    return t === 'critical' || t === 'high'
  })
  const rest = items.filter((e) => {
    const t = e.tier ?? tierOf(e.importance, e.impact)
    return t !== 'critical' && t !== 'high'
  })

  const filterActive =
    minImpact !== '0' || sinceDays !== '3' || sentiment !== '' || category !== '' || stage !== '' || media !== ''
  // 用户明确选「仅媒体评论」时，低影响折叠区必须默认展开 —— 否则等于给他看一个空页面
  const lowOpen = showLow || media === 'only'

  return (
    <Card
      className="flex min-h-0 flex-1 flex-col"
      bodyClass="min-h-0 flex-1 overflow-y-auto"
      title={symbol ? `${symbol} · 关键节点时间线` : '项目关键节点 · 事件流（重点优先）'}
      subtitle={
        symbol
          ? '新闻沿时间轴串联，最新在上；AI 判定节点嵌于顶端'
          : '默认按重要度排序：重大 / 重要 / 可看 三档分级，低影响条目折叠'
      }
      actions={
        <div className="flex items-center gap-1.5">
          <Select value={symbol} onChange={(e) => onSymbolChange(e.target.value)} className="!w-28">
            <option value="">全部公司</option>
            {companies.map((c) => (
              <option key={c.id} value={c.symbol}>
                {c.symbol}
              </option>
            ))}
          </Select>
          <Button
            size="sm"
            variant={showFilters ? 'primary' : 'ghost'}
            icon={<Filter className="h-3.5 w-3.5" />}
            onClick={() => setShowFilters((v) => !v)}
          >
            筛选{filterActive ? ' ·' : ''}
          </Button>
          <Button size="sm" variant="ghost" icon={<RefreshCw className="h-3.5 w-3.5" />} loading={loading} onClick={load} />
          {symbol && (
            <Button size="sm" variant="ghost" title="放大时间线" onClick={onZoom}>
              ⤢ 放大
            </Button>
          )}
        </div>
      }
    >
      {/* 筛选条 */}
      {showFilters && (
        <div className="mb-3 flex flex-wrap items-center gap-2 rounded-lg border border-slate-100 bg-slate-50/60 px-2.5 py-2">
          <Tabs
            value={sort}
            onChange={(k) => setSort(k as SortKey)}
            tabs={[
              { key: 'importance', label: '重点优先' },
              { key: 'created', label: '最新入库' },
            ]}
          />
          <Select value={minImpact} onChange={(e) => setMinImpact(e.target.value)} className="!w-32">
            {IMPACT_OPTIONS.map((o) => (
              <option key={o.key} value={o.key}>
                {o.label}
              </option>
            ))}
          </Select>
          <Select value={sinceDays} onChange={(e) => setSinceDays(e.target.value)} className="!w-32">
            {SINCE_OPTIONS.map((o) => (
              <option key={o.key} value={o.key}>
                {o.label}
              </option>
            ))}
          </Select>
          <Select value={sentiment} onChange={(e) => setSentiment(e.target.value)} className="!w-28">
            {SENTIMENT_OPTIONS.map((o) => (
              <option key={o.key} value={o.key}>
                {o.label}
              </option>
            ))}
          </Select>
          <Select value={category} onChange={(e) => setCategory(e.target.value)} className="!w-32">
            {EVENT_CATEGORIES.map((o) => (
              <option key={o.key} value={o.key}>
                {o.label}
              </option>
            ))}
          </Select>
          <Select value={stage} onChange={(e) => setStage(e.target.value)} className="!w-28">
            {STAGE_OPTIONS.map((o) => (
              <option key={o.key} value={o.key}>
                {o.label}
              </option>
            ))}
          </Select>
          <Select value={media} onChange={(e) => setMedia(e.target.value)} className="!w-32">
            {MEDIA_OPTIONS.map((o) => (
              <option key={o.key} value={o.key}>
                {o.label}
              </option>
            ))}
          </Select>
          <button
            className="text-[11px] text-brand-600 hover:underline"
            onClick={() => {
              setMinImpact('0')
              setSinceDays('0')
              setSentiment('')
              setCategory('')
              setStage('')
              setMedia('')
            }}
          >
            重置
          </button>
        </div>
      )}

      {items.length === 0 ? (
        <Empty
          icon={<Filter className="h-8 w-8" />}
          title={loading ? '加载中…' : '没有符合条件的事件'}
          desc={
            loading
              ? undefined
              : filterActive
                ? '当前筛选条件下没有事件，可点「重置」放宽条件'
                : '开启监控并接入 AI Agent（或手动触发分析）后，抓取到的关键节点会出现在这里'
          }
        />
      ) : symbol ? (
        <TimelineView symbol={symbol} events={items} analysis={analyses[0] ?? null} />
      ) : (
        <>
          {/* 汇总条：一眼看清这批情报的构成 */}
          <div className="mb-3 flex flex-wrap items-center gap-x-3 gap-y-1.5 rounded-lg bg-slate-50 px-3 py-2 text-[11px]">
            <span className="text-slate-500">
              命中 <b className="num text-slate-800">{items.length}</b> 条
            </span>
            <span className="text-rose-600">重大 {stats.byTier.critical}</span>
            <span className="text-amber-600">重要 {stats.byTier.high}</span>
            <span className="text-slate-500">可看 {stats.byTier.medium + stats.byTier.low}</span>
            {stats.media > 0 && (
              <span className="text-slate-400" title="媒体评论 / 行情播报，非公司自身事件；重要度已封顶">
                媒体评论 {stats.media}
              </span>
            )}
            <span className="text-slate-300">|</span>
            <span style={{ color: sentimentColor('positive') }}>利好 {stats.pos}</span>
            <span style={{ color: sentimentColor('negative') }}>利空 {stats.neg}</span>
            {stats.avgImp != null && (
              <>
                <span className="text-slate-300">|</span>
                <span className="text-slate-500">
                  平均重要度 <b className="num text-slate-800">{stats.avgImp.toFixed(1)}</b>
                </span>
              </>
            )}
            <span className="ml-auto text-slate-400">
              {sort === 'importance' ? '按重要度排序（影响度×新鲜度×类别×阶段×来源）' : '按入库时间排序'}
            </span>
          </div>

          <ul className="space-y-2.5">
            {primary.map((e) => (
              <EventCard key={e.id} e={e} onDelete={remove} defaultOpen />
            ))}
          </ul>

          {rest.length > 0 && (
            <div className="mt-3">
              <button
                className="flex w-full items-center gap-2 rounded-lg border border-dashed border-slate-200 px-3 py-2 text-[11px] text-slate-500 hover:bg-slate-50"
                onClick={() => setShowLow((v) => !v)}
              >
                {lowOpen ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
                {media === 'only'
                  ? `${rest.length} 条媒体评论（已按你的筛选展开）`
                  : `其余 ${rest.length} 条低影响条目（可看 / 低）已折叠`}
                <span className="ml-auto text-slate-400">{lowOpen ? '点击收起' : '点击展开'}</span>
              </button>
              {lowOpen && (
                <ul className="mt-2 space-y-1.5">
                  {rest.map((e) => (
                    <EventCard key={e.id} e={e} onDelete={remove} defaultOpen={false} />
                  ))}
                </ul>
              )}
            </div>
          )}

          <div className="mt-2 text-[10px] text-slate-400">
            最后刷新 {fmtSince(new Date().toISOString())} · 重要度由规则计算，不构成投资建议
          </div>
        </>
      )}
    </Card>
  )
}
