/**
 * 行情页 · 「我的收藏」报价池
 *
 * 从 `pages/Market.tsx` 抽出（铁律 9 拆分，2026-09-29）。
 */
import { Star, TrendingUp } from 'lucide-react'
import { Badge, Button, Card, DataTable, Empty } from '../ui'
import { fmtCompact, fmtNum, signClass } from '../../lib/format'
import type { Quote } from '../../lib/types'

export function WatchPool({
  watch,
  watchedSet,
  watchNames,
  onRefresh,
  onPick,
}: {
  watch: Quote[]
  watchedSet: Set<string>
  watchNames: Record<string, string>
  onRefresh: () => void
  onPick: (symbol: string) => void
}) {
  return (
    <Card
      title={
        <span className="flex items-center gap-2">
          <Star className="h-4 w-4 text-amber-400" />
          我的收藏
          {watchedSet.size > 0 && <span className="text-xs font-normal text-slate-400">（{watchedSet.size} 只）</span>}
        </span>
      }
      subtitle="收藏池 · 点击切换标的 · 搜索后在图表标题处点 ★ 即可加入"
      dense
      actions={
        <Button variant="ghost" onClick={onRefresh} icon={<TrendingUp className="h-3.5 w-3.5" />}>
          刷新报价
        </Button>
      }
    >
      {watch.length === 0 ? (
        <Empty
          icon={<Star className="h-8 w-8" />}
          title="收藏列表为空"
          desc="搜索标的后在图表标题处点击 ★ 星标即可收藏"
        />
      ) : (
        <DataTable<Quote>
          rows={watch}
          rowKey={(r) => r.symbol}
          onRowClick={(r) => onPick(r.symbol)}
          columns={[
            {
              key: 's',
              label: '标的',
              render: (r) => (
                <span className="flex items-center gap-1.5">
                  <Star
                    className={`h-3 w-3 shrink-0 ${
                      watchedSet.has(r.symbol) ? 'fill-amber-400 text-amber-400' : 'text-slate-300'
                    }`}
                  />
                  <span className="font-medium text-slate-800">{r.symbol}</span>
                  {watchNames[r.symbol] && <span className="text-xs text-slate-400">{watchNames[r.symbol]}</span>}
                </span>
              ),
            },
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
      )}
    </Card>
  )
}
