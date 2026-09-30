/**
 * 全部新闻（新闻流）—— 每日必读的「完整底稿」
 *
 * 用户原话：「这个新闻排序你也应该有一个专门的地方让我看到所有近期的新闻」。
 * 必读清单只有 top 12 条且可能被窗口内的高重要度旧事件占据；这里是**全量视角**：
 * 近 N 天入库的全部事件/新闻，按**入库时间**倒序平铺（`sort=created`）——
 * 新抓到的立刻出现在最上面，「系统在动、数据在进」一眼可见；
 * 必读清单还在消化旧重大事件时，新动向也能第一时间在这里看到。
 *
 * 数据源：`GET /intel/events?sort=created&since_days=N&limit=200`（后端已附
 * importance / tier / stage_cn / commentary）。自含取数（FILE_SIZE_DEBT 约定），
 * DailyDigest 只挂一个页签；30s 静默轮询与必读同节奏，父级 refreshToken
 * （抓取/监控动作完成）变化时立即静默刷新。
 */
import { useCallback, useEffect, useState } from 'react'
import { Newspaper, RefreshCw } from 'lucide-react'
import { Badge, Button, Empty, Select } from '../../ui'
import { api } from '../../../lib/api'
import { type EventItem, fmtSince, fmtUtc, sentimentColor } from '../types'

const SINCE_OPTIONS = [
  { key: '1', label: '今日/昨日' },
  { key: '3', label: '近 3 天' },
  { key: '7', label: '近 7 天' },
  { key: '14', label: '近 14 天' },
]

export default function NewsFlow({ refreshToken = 0 }: { refreshToken?: number }) {
  const [items, setItems] = useState<EventItem[]>([])
  const [loading, setLoading] = useState(false)
  const [since, setSince] = useState('3')

  const load = useCallback(
    (silent = false) => {
      if (!silent) setLoading(true)
      api
        .get<{ items: EventItem[] }>(`/intel/events?sort=created&since_days=${since}&limit=200`)
        .then((d) => setItems(d.items || []))
        .catch(() => {})
        .finally(() => {
          if (!silent) setLoading(false)
        })
    },
    [since],
  )

  useEffect(() => {
    load()
  }, [load])

  /* 抓取/监控动作后父级 refreshToken 变化 → 静默刷新（新入库的立即出现） */
  useEffect(() => {
    if (!refreshToken) return
    load(true)
  }, [refreshToken, load])

  /* 30s 静默轮询：与每日必读同节奏，监控后台抓到新数据自动出现 */
  useEffect(() => {
    const t = setInterval(() => load(true), 30_000)
    return () => clearInterval(t)
  }, [load])

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-2 text-[11px] text-slate-500">
        <span>时间范围</span>
        <Select value={since} onChange={(e) => setSince(e.target.value)} className="!w-[104px]">
          {SINCE_OPTIONS.map((o) => (
            <option key={o.key} value={o.key}>
              {o.label}
            </option>
          ))}
        </Select>
        <span>
          共 <b className="num text-slate-900">{items.length}</b> 条 · 按<b>入库时间</b>倒序，新抓取的排最上
        </span>
        <Button size="sm" variant="ghost" icon={<RefreshCw className="h-3.5 w-3.5" />} loading={loading} onClick={() => load()}>
          刷新
        </Button>
        <span className="ml-auto hidden text-slate-400 lg:inline">
          「媒体」= 评论/播报（非公司自身事件，永不进必读）；★ = 影响度
        </span>
      </div>

      {items.length === 0 ? (
        <Empty
          icon={<Newspaper className="h-8 w-8" />}
          title="窗口内没有入库新闻"
          desc="开启监控或点上方「立即抓取」后，新数据会按入库时间出现在这里。"
        />
      ) : (
        <ul className="max-h-[70vh] divide-y divide-slate-100 overflow-y-auto pr-1">
          {items.map((it) => (
            <li key={it.id} className="flex items-start gap-2 py-1.5 text-xs">
              {/* 入库时刻是本视图的排序主键，必须显眼 —— 用户硬要求所有信息带日期 */}
              <span className="w-[150px] shrink-0 text-[11px] text-slate-400" title={`入库：${fmtUtc(it.created_at)}`}>
                {fmtSince(it.created_at)}
              </span>
              <span className="w-14 shrink-0 font-semibold text-slate-700">{it.symbol}</span>
              <span className="w-10 shrink-0 text-rose-600" title={`影响度 ${it.impact}★`}>
                {'★'.repeat(it.impact)}
              </span>
              <span className="w-10 shrink-0" style={{ color: sentimentColor(it.sentiment) }}>
                {it.sentiment === 'positive' ? '利好' : it.sentiment === 'negative' ? '利空' : '中性'}
              </span>
              <span className="min-w-0 flex-1 truncate">
                {it.source_url ? (
                  <a
                    href={it.source_url}
                    target="_blank"
                    rel="noreferrer"
                    className="text-slate-700 hover:text-brand-700 hover:underline"
                    title={it.title}
                  >
                    {it.title}
                  </a>
                ) : (
                  <span className="text-slate-700" title={it.title}>
                    {it.title}
                  </span>
                )}
              </span>
              <span className="hidden w-16 shrink-0 truncate text-[11px] text-slate-400 xl:inline" title={it.category_cn}>
                {it.category_cn}
              </span>
              {it.tier === 'critical' && <Badge tone="red">重大</Badge>}
              {it.tier === 'high' && <Badge tone="amber">重要</Badge>}
              {it.stage === 'confirmed' && <Badge tone="green">已敲定</Badge>}
              {it.stage === 'rumor' && <Badge tone="slate">传闻</Badge>}
              {it.commentary && <Badge tone="slate">媒体</Badge>}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
