import { ExternalLink, RefreshCw } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { api } from '../lib/api'

interface NewsItem {
  source: string
  headline: string
  url: string
  summary: string
  symbol: string
  market: string
  category: string
  published_at: string
}

const SOURCE_LABEL: Record<string, string> = {
  finnhub: 'Finnhub',
  'yahoo-rss': 'Yahoo',
  hkex: '港交所',
  ibkr: 'IBKR',
}

/**
 * 新闻 / 公告面板（行情分析页侧栏）。
 * 美股 → Finnhub + Yahoo RSS；港股 → 港交所披露易公告（标记"公告"）+ Yahoo。
 */
export default function NewsPanel({ symbol }: { symbol: string }) {
  const [items, setItems] = useState<NewsItem[]>([])
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [loading, setLoading] = useState(false)

  const load = useCallback(
    async (force = false) => {
      if (!symbol) return
      setLoading(true)
      try {
        const r = await api.post<{ items: NewsItem[]; errors: Record<string, string> }>(
          `/news/refresh?symbol=${encodeURIComponent(symbol)}`,
          undefined,
          45_000,
        )
        setItems(r.items)
        setErrors(r.errors || {})
      } catch {
        setItems([])
      } finally {
        setLoading(false)
      }
    },
    [symbol],
  )

  useEffect(() => {
    // 先展示缓存（GET），再后台强制刷新
    api
      .get<{ items: NewsItem[] }>(`/news?symbol=${encodeURIComponent(symbol)}`)
      .then((r) => setItems(r.items))
      .catch(() => {})
  }, [symbol])

  return (
    <div className="rounded-xl border border-slate-200 bg-white">
      <div className="flex items-center justify-between border-b border-slate-100 px-4 py-2.5">
        <div className="text-sm font-semibold text-slate-800">
          新闻与公告
          <span className="ml-2 text-[11px] font-normal text-slate-400">{symbol}</span>
        </div>
        <button
          onClick={() => load(true)}
          className="rounded p-1.5 text-slate-400 hover:bg-slate-100 hover:text-slate-600"
          title="刷新"
        >
          <RefreshCw className={`h-3.5 w-3.5 ${loading ? 'animate-spin' : ''}`} />
        </button>
      </div>
      <div className="max-h-[420px] overflow-y-auto p-2">
        {items.length === 0 && !loading && (
          <div className="px-2 py-6 text-center text-xs leading-5 text-slate-400">
            暂无新闻。
            {Object.keys(errors).length > 0 && (
              <span className="mt-1 block text-[10px] text-amber-500">
                部分来源不可用：{Object.keys(errors).join('、')}
              </span>
            )}
          </div>
        )}
        {items.map((it, idx) => (
          <a
            key={`${it.source}-${idx}`}
            href={it.url || undefined}
            target="_blank"
            rel="noreferrer"
            className={`block rounded-lg px-2.5 py-2 transition-colors hover:bg-slate-50 ${!it.url ? 'cursor-default' : ''}`}
          >
            <div className="flex items-center gap-1.5">
              <span
                className={`rounded px-1 py-0.5 text-[9px] font-medium ${
                  it.category === 'announcement'
                    ? 'bg-amber-50 text-amber-600'
                    : 'bg-slate-100 text-slate-500'
                }`}
              >
                {it.category === 'announcement' ? '公告' : SOURCE_LABEL[it.source] || it.source}
              </span>
              <span className="text-[10px] text-slate-300">
                {it.published_at
                  ? new Date(it.published_at).toLocaleString('zh-CN', {
                      month: '2-digit',
                      day: '2-digit',
                      hour: '2-digit',
                      minute: '2-digit',
                    })
                  : ''}
              </span>
              {it.url && <ExternalLink className="ml-auto h-3 w-3 text-slate-200" />}
            </div>
            <p className="mt-1 line-clamp-2 text-[12.5px] leading-snug text-slate-700">{it.headline}</p>
          </a>
        ))}
      </div>
    </div>
  )
}
