/**
 * HistoryPanel —— 历史回测记录
 * ==============================
 * 从 pages/Backtest.tsx 抽出（铁律 9）。
 *
 * 自持「加载详情 / 删除」两件事，父级只接结果：
 *   - 点行 → 拉 `/backtest/{id}` 详情，拼成 BacktestResult 交给 `onOpenResult`；
 *   - 齿轮 → `onLoadConfig(id)`，由父级回填配置（因为配置状态在父级）。
 *
 * ⚠️ `monthlyFromCurve`：历史记录没有单独存月度收益，只能按「本月末净值 / 上月末净值 - 1」
 *    从净值曲线重算，否则详情页的月度分析与热力图会恒为空。
 */
import { RotateCcw, SlidersHorizontal, Trash2 } from 'lucide-react'
import { api } from '../../lib/api'
import { symbolsToList, symbolsToInput } from '../../lib/backtestPrefs'
import { fmtNum, fmtRatioPct, signClass } from '../../lib/format'
import type { BacktestResult } from '../../lib/types'
import { Button, Card, DataTable, Empty, useToast } from '../ui'

/** 从净值曲线重算月度收益（历史记录未单独存月度数据）。 */
function monthlyFromCurve(curve: { date: string; equity: number }[] | undefined): Record<string, number> {
  if (!curve || curve.length < 2) return {}
  const monthEnd = new Map<string, number>()
  for (const p of curve) {
    const mo = String(p?.date ?? '').slice(0, 7)
    const v = Number(p?.equity)
    if (mo.length === 7 && Number.isFinite(v) && v > 0) monthEnd.set(mo, v)
  }
  const months = [...monthEnd.keys()].sort()
  const out: Record<string, number> = {}
  for (let i = 1; i < months.length; i++) {
    const prev = monthEnd.get(months[i - 1]) as number
    const cur = monthEnd.get(months[i]) as number
    if (prev > 0) out[months[i]] = cur / prev - 1
  }
  return out
}

export default function HistoryPanel({
  history,
  onRefresh,
  onLoadConfig,
  onOpenResult,
}: {
  history: any[]
  onRefresh: () => void
  onLoadConfig: (rid: number) => void | Promise<void>
  onOpenResult: (r: BacktestResult) => void
}) {
  const toast = useToast()

  const open = async (r: any) => {
    try {
      const d = await api.get<any>(`/backtest/${r.id}`)
      onOpenResult({
        ok: true,
        strategy_name: d.strategy_name,
        metrics: d.metrics,
        curve: d.curve,
        trades: d.trades,
        trade_count: d.trades.length,
        monthly: monthlyFromCurve(d.curve),
        symbols: symbolsToList(d.symbols),
        data_sources: {},
        strategy_notes: [],
        bars: d.curve.length,
        date_range: [d.start, d.end],
      })
      toast('info', `已加载历史回测「${d.label}」`)
    } catch (e: any) {
      toast('error', e?.message || '加载失败')
    }
  }

  const remove = async (id: number) => {
    try {
      await api.del(`/backtest/${id}`)
      onRefresh()
    } catch (e: any) {
      toast('error', `删除失败：${e?.message || e}`)
    }
  }

  return (
    <Card
      title="历史回测记录"
      subtitle="点击某一行可以直接查看那次回测的结果"
      actions={
        <Button size="sm" icon={<RotateCcw className="h-3.5 w-3.5" />} onClick={onRefresh}>
          刷新
        </Button>
      }
      dense
    >
      <DataTable<any>
        rows={history}
        rowKey={(r) => r.id}
        maxHeight="280px"
        empty={<Empty title="暂无回测记录" desc="跑一次回测后，结果会自动保存在这里，方便日后对比。" />}
        columns={[
          {
            key: 'l',
            label: '策略',
            render: (r) => (
              <div className="max-w-[240px]">
                <div className="truncate font-medium text-slate-700">{r.label}</div>
                <div className="truncate text-[10px] text-slate-400">{r.strategy_name || r.strategy_key}</div>
              </div>
            ),
          },
          { key: 's', label: '标的', render: (r) => <span className="text-xs text-slate-500">{symbolsToInput(r.symbols) ?? ''}</span> },
          {
            key: 'r',
            label: '累计收益',
            align: 'right',
            render: (r) => <span className={`num ${signClass(r.metrics.total_return)}`}>{fmtRatioPct(r.metrics.total_return, 1, true)}</span>,
          },
          { key: 'sh', label: '夏普', align: 'right', render: (r) => <span className="num">{fmtNum(r.metrics.sharpe, 2)}</span> },
          { key: 'dd', label: '最大回撤', align: 'right', render: (r) => <span className="num text-emerald-600">{fmtRatioPct(r.metrics.max_drawdown, 1)}</span> },
          { key: 't', label: '交易', align: 'right', render: (r) => <span className="num text-slate-500">{r.metrics.trades}</span> },
          { key: 'd', label: '时间', render: (r) => <span className="num text-xs text-slate-400">{String(r.created_at).slice(0, 16).replace('T', ' ')}</span> },
          {
            key: 'act',
            label: '',
            align: 'right',
            render: (r) => (
              <div className="flex items-center justify-end gap-1">
                <button
                  className="rounded p-1 text-slate-300 hover:bg-brand-50 hover:text-brand-600"
                  title="把这套配置填回左侧表单（标的 / 区间 / 止损 / 参数）"
                  onClick={async (ev) => {
                    ev.stopPropagation()
                    await onLoadConfig(r.id)
                  }}
                >
                  <SlidersHorizontal className="h-3.5 w-3.5" />
                </button>
                <button
                  className="rounded p-1 text-slate-300 hover:bg-rose-50 hover:text-rose-500"
                  title="删除该记录"
                  onClick={(ev) => {
                    ev.stopPropagation()
                    remove(r.id)
                  }}
                >
                  <Trash2 className="h-3.5 w-3.5" />
                </button>
              </div>
            ),
          },
        ]}
        onRowClick={open}
      />
    </Card>
  )
}
