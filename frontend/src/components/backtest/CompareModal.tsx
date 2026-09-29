/**
 * CompareModal —— 多策略对比
 * ============================
 * 从 pages/Backtest.tsx 抽出（铁律 9）。自持「对比清单 / 是否沿用参数记忆 /
 * 运行中 / 结果」状态，以及 CSV 导出。
 *
 * ⚠️ `customId` 为空串表示「内置策略」，非空表示「我的策略」。这个约定来自
 *    Backtest 主面板（`customId === ''` 才用 strategyKey），不要改成 null/undefined，
 *    否则与主面板的持久化字段对不上。
 */
import { useState } from 'react'
import { Download, GitCompare, Plus, Trash2 } from 'lucide-react'
import { api, LONG_TIMEOUT } from '../../lib/api'
import { loadParamMemory } from '../../lib/backtestPrefs'
import { fmtNum, fmtRatioPct, signClass } from '../../lib/format'
import type { CompareResult, StrategyConfig, StrategyInfo } from '../../lib/types'
import { MultiEquityChart } from '../charts'
import { Alert, Badge, Button, DataTable, Field, Input, Loading, Modal, Select, Switch, useToast } from '../ui'
import { TermTip } from '../terms/TermTip'
import type { RiskSettings } from './types'

interface CmpItem {
  label: string
  strategy_key: string
  symbols: string
  customId?: number | ''
}

export default function CompareModal({
  open,
  onClose,
  builtin,
  customs,
  symbols,
  start,
  end,
  interval,
  capital,
  commission,
  slippage,
  benchmark,
  dataSource,
  risk,
}: {
  open: boolean
  onClose: () => void
  builtin: StrategyInfo[]
  customs: StrategyConfig[]
  symbols: string
  start: string
  end: string
  interval: string
  capital: number
  commission: number
  slippage: number
  benchmark: string
  dataSource: string
  risk: RiskSettings
}) {
  const toast = useToast()
  const [items, setItems] = useState<CmpItem[]>([
    { label: '策略 A', strategy_key: 'dual_ma_trend', symbols: 'SPY', customId: '' },
    { label: '策略 B', strategy_key: 'vol_managed_momentum', symbols: 'SPY', customId: '' },
  ])
  const [useMemory, setUseMemory] = useState(true)
  const [running, setRunning] = useState(false)
  const [result, setResult] = useState<CompareResult | null>(null)

  const run = async () => {
    const payload = items
      .filter((it) => (it.customId || it.strategy_key) && it.symbols.trim())
      .map((it, i) => {
        const cfg = it.customId ? customs.find((c) => c.id === it.customId) : null
        const effKey = cfg?.strategy_key || it.strategy_key
        const mem = useMemory && !cfg ? loadParamMemory(effKey) || {} : {}
        return {
          label: it.label || `策略 ${i + 1}`,
          strategy_key: effKey,
          symbols: it.symbols
            .split(',')
            .map((s) => s.trim().toUpperCase())
            .filter(Boolean),
          params: { ...(cfg?.params || {}), ...mem },
          rule: cfg?.kind === 'rule' ? cfg.rule : undefined,
          code: cfg?.kind === 'code' ? cfg.code : undefined,
          risk: {
            stop_type: risk.stopType,
            stop_value: risk.stopValue,
            take_profit_r: risk.takeProfitR,
            time_stop_bars: risk.timeStop,
            sizing_method: risk.sizing,
            risk_per_trade_pct: risk.riskPct,
          },
        }
      })
    if (payload.length < 2) {
      toast('warning', '至少需要 2 个策略才能对比')
      return
    }
    setRunning(true)
    setResult(null)
    try {
      const r = await api.post<CompareResult>(
        '/backtest/compare',
        {
          items: payload,
          start,
          end: end || null,
          interval,
          initial_capital: capital,
          commission_bps: commission,
          slippage_bps: slippage,
          benchmark,
          data_source: dataSource,
        },
        LONG_TIMEOUT,
      )
      setResult(r)
      toast('success', `对比完成：${r.labels.length} 个策略`)
    } catch (e: any) {
      toast('error', e?.message || '对比失败')
    } finally {
      setRunning(false)
    }
  }

  const exportCsv = () => {
    if (!result) return
    const cols = [
      'label', 'strategy', 'ok', 'total_return', 'cagr', 'sharpe', 'sortino', 'calmar',
      'max_drawdown', 'win_rate', 'profit_factor', 'trades', 'turnover',
    ]
    const lines = result.results.map((r: any) => {
      const m = r.ok ? r.metrics : {}
      const row: Record<string, any> = {
        label: r.label, strategy: r.strategy_name || '', ok: r.ok ? 1 : 0,
        total_return: m.total_return ?? '', cagr: m.cagr ?? '', sharpe: m.sharpe ?? '',
        sortino: m.sortino ?? '', calmar: m.calmar ?? '', max_drawdown: m.max_drawdown ?? '',
        win_rate: m.win_rate ?? '', profit_factor: m.profit_factor ?? '',
        trades: m.trades ?? '', turnover: m.turnover ?? '',
      }
      return cols.map((c) => `"${String(row[c]).replace(/"/g, '""')}"`).join(',')
    })
    const csv = [cols.join(','), ...lines].join('\n')
    const blob = new Blob(['\ufeff' + csv], { type: 'text/csv;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `quantdesk_compare_${new Date().toISOString().slice(0, 10)}.csv`
    document.body.appendChild(a)
    a.click()
    a.remove()
    URL.revokeObjectURL(url)
    toast('success', '对比结果已导出 CSV')
  }

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="多策略对比"
      width="max-w-5xl"
      footer={
        <>
          <Button onClick={onClose}>关闭</Button>
          <Button variant="primary" loading={running} onClick={run} icon={<GitCompare className="h-3.5 w-3.5" />}>
            开始对比
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <Alert tone="info" title="对比是公平的">
          所有策略使用<span className="font-medium">完全相同的时间区间、初始资金、成本与止损设置</span>，
          只有策略与参数不同，所以结果可以直接横向比较。曲线会统一归一化到初始资金，方便叠加观察。
        </Alert>

        <Switch
          checked={useMemory}
          onChange={setUseMemory}
          label="使用各策略记忆的参数"
          hint="开启后，每个策略用它在上次回测里调好的参数；关闭则全部用默认参数。我的策略始终使用它自己保存的配置。"
        />

        <div className="space-y-2">
          {items.map((it, i) => (
            <div
              key={i}
              className="grid gap-2 rounded-lg border border-slate-200 bg-slate-50/60 p-3 lg:grid-cols-[1fr_2fr_2fr_auto]"
            >
              <Field label={`名称 ${i + 1}`}>
                <Input
                  value={it.label}
                  onChange={(e) => setItems((s) => s.map((x, j) => (j === i ? { ...x, label: e.target.value } : x)))}
                />
              </Field>
              <Field label="策略">
                <Select
                  value={it.customId ? `custom:${it.customId}` : it.strategy_key}
                  onChange={(e) => {
                    const v = e.target.value
                    setItems((s) =>
                      s.map((x, j) => {
                        if (j !== i) return x
                        if (v.startsWith('custom:')) {
                          const id = parseInt(v.split(':')[1], 10)
                          const cfg = customs.find((c) => c.id === id)
                          return { ...x, customId: id, strategy_key: cfg?.strategy_key || x.strategy_key, label: cfg?.name || x.label }
                        }
                        return { ...x, customId: '', strategy_key: v }
                      }),
                    )
                  }}
                >
                  <optgroup label="内置策略">
                    {builtin.map((b) => (
                      <option key={b.key} value={b.key}>
                        [{b.category}] {b.name}
                      </option>
                    ))}
                  </optgroup>
                  {customs.length > 0 && (
                    <optgroup label="我的策略">
                      {customs.map((c) => (
                        <option key={`cc${c.id}`} value={`custom:${c.id}`}>
                          {c.name}（{c.kind === 'rule' ? '规则' : c.kind === 'code' ? '代码' : '内置'}）
                        </option>
                      ))}
                    </optgroup>
                  )}
                </Select>
              </Field>
              <Field label={<TermTip id="symbol">标的（逗号分隔）</TermTip>}>
                <Input
                  value={it.symbols}
                  onChange={(e) =>
                    setItems((s) => s.map((x, j) => (j === i ? { ...x, symbols: e.target.value.toUpperCase() } : x)))
                  }
                />
              </Field>
              <div className="flex items-end">
                <Button
                  variant="ghost"
                  size="sm"
                  disabled={items.length <= 2}
                  onClick={() => setItems((s) => s.filter((_, j) => j !== i))}
                  icon={<Trash2 className="h-3.5 w-3.5" />}
                />
              </div>
            </div>
          ))}
          <Button
            size="sm"
            disabled={items.length >= 6}
            onClick={() =>
              setItems((s) => [
                ...s,
                { label: `策略 ${String.fromCharCode(65 + s.length)}`, strategy_key: 'trend_composite', symbols, customId: '' },
              ])
            }
            icon={<Plus className="h-3.5 w-3.5" />}
          >
            添加策略（最多 6 个）
          </Button>
        </div>

        {running && <Loading label="正在依次回测各策略…" />}

        {result && !running && (
          <div className="space-y-4">
            <div className="flex flex-wrap gap-2">
              <Badge tone="brand">{result.labels.length} 个成功</Badge>
              {result.results.filter((r) => !r.ok).length > 0 && (
                <Badge tone="amber">{result.results.filter((r) => !r.ok).length} 个失败</Badge>
              )}
              <Button size="sm" icon={<Download className="h-3.5 w-3.5" />} onClick={exportCsv}>
                导出 CSV
              </Button>
            </div>

            <MultiEquityChart data={result.aligned} labels={result.labels} height={320} />

            <DataTable<any>
              rows={result.results}
              rowKey={(r, i) => `${r.label}-${i}`}
              maxHeight="300px"
              columns={[
                {
                  key: 'lb',
                  label: '策略',
                  render: (r) => (
                    <div>
                      <div className="font-medium text-slate-800">{r.label}</div>
                      {r.strategy_name && <div className="text-[10px] text-slate-400">{r.strategy_name}</div>}
                    </div>
                  ),
                },
                {
                  key: 'ret',
                  label: <TermTip id="total_return">累计收益</TermTip>,
                  align: 'right',
                  render: (r) =>
                    r.ok ? (
                      <span className={`num ${signClass(r.metrics.total_return)}`}>{fmtRatioPct(r.metrics.total_return, 1, true)}</span>
                    ) : (
                      <span className="text-xs text-rose-500">{r.error}</span>
                    ),
                },
                { key: 'cagr', label: <TermTip id="cagr">年化</TermTip>, align: 'right', render: (r) => (r.ok ? <span className={`num ${signClass(r.metrics.cagr)}`}>{fmtRatioPct(r.metrics.cagr, 1, true)}</span> : '—') },
                { key: 'sh', label: <TermTip id="sharpe">夏普</TermTip>, align: 'right', render: (r) => (r.ok ? <span className="num font-medium">{fmtNum(r.metrics.sharpe, 2)}</span> : '—') },
                { key: 'so', label: <TermTip id="sortino">索提诺</TermTip>, align: 'right', render: (r) => (r.ok ? <span className="num">{fmtNum(r.metrics.sortino, 2)}</span> : '—') },
                { key: 'ca', label: <TermTip id="calmar">卡玛</TermTip>, align: 'right', render: (r) => (r.ok ? <span className="num">{fmtNum(r.metrics.calmar, 2)}</span> : '—') },
                { key: 'dd', label: <TermTip id="max_drawdown">最大回撤</TermTip>, align: 'right', render: (r) => (r.ok ? <span className="num text-emerald-600">{fmtRatioPct(r.metrics.max_drawdown, 1)}</span> : '—') },
                { key: 'wr', label: <TermTip id="win_rate">胜率</TermTip>, align: 'right', render: (r) => (r.ok ? <span className="num">{fmtRatioPct(r.metrics.win_rate, 1)}</span> : '—') },
                { key: 'pf', label: <TermTip id="profit_factor">盈亏比</TermTip>, align: 'right', render: (r) => (r.ok ? <span className="num">{fmtNum(r.metrics.profit_factor, 2)}</span> : '—') },
                { key: 't', label: <TermTip id="trades">交易</TermTip>, align: 'right', render: (r) => (r.ok ? <span className="num text-slate-500">{r.metrics.trades}</span> : '—') },
                { key: 'to', label: <TermTip id="turnover">换手</TermTip>, align: 'right', render: (r) => (r.ok ? <span className="num text-slate-500">{fmtNum(r.metrics.turnover, 1)}x</span> : '—') },
              ]}
            />

            <Alert tone="warn" title="怎么看对比结果">
              不要只挑收益最高的。优先看三项组合：
              <span className="font-medium">夏普 / 卡玛（这份收益的性价比）</span>、
              <span className="font-medium">最大回撤（你扛不扛得住）</span>、
              <span className="font-medium">换手率（成本侵蚀）</span>。若某条曲线明显更平滑、回撤更浅，
              即便收益略低，通常也更适合真实资金。
            </Alert>
          </div>
        )}
      </div>
    </Modal>
  )
}
