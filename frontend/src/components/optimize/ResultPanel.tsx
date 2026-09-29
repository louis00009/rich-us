/**
 * OptimizeResultPanel —— 组合优化结果区
 * ======================================
 * 从 `pages/Optimize.tsx` 抽出（铁律 9：页面 600 行硬上限，原文件 861 行）。
 * 本组件只持有「结果区当前是哪个 tab」这一个 UI 状态，其余全部来自 props。
 *
 * 结构刻意做成「先结论、再数字、最后才是权重表」：
 * 小白看完 4 张指标卡 + 一张权重表并不知道该不该用这组权重，
 * 所以最上面先放 `ResultSummary`（人话一句话结论）。
 */
import { Download, Info, Layers, Save, Sparkles, TrendingUp, Wallet } from 'lucide-react'
import { useState } from 'react'
import { CorrelationMatrix, HBar } from '../charts'
import AIAssist from '../AIAssist'
import { Alert, Badge, Button, Card, DataTable, Progress, Stat, Tabs } from '../ui'
import { fmtNum, fmtRatioPct, signClass } from '../../lib/format'
import { TermTip } from '../terms/TermTip'
import FrontierTab from './FrontierTab'
import { ResultSummary } from './PlainSummary'
import type { AssetStat, Meta, OptResult } from './types'

interface Props {
  result: OptResult
  meta: Meta | null
  objectiveLabel: string
  onExportCsv: () => void
  onOpenSave: () => void
}

export default function OptimizeResultPanel({ result, meta, objectiveLabel, onExportCsv, onOpenSave }: Props) {
  const [tab, setTab] = useState('weights')

  const corrMatrix = (() => {
    const { symbols: syms, matrix } = result.correlation
    const out: Record<string, Record<string, number | null>> = {}
    syms.forEach((a, i) => {
      out[a] = {}
      syms.forEach((b, j) => {
        out[a][b] = matrix[i]?.[j] ?? null
      })
    })
    return out
  })()

  const sorted = [...result.assets].sort((a, b) => b.weight - a.weight)

  return (
    <div className="space-y-4">
      {result.synthetic_symbols?.length > 0 && (
        <Alert tone="warn" title="部分标的使用了合成行情（非真实数据）">
          {result.synthetic_symbols.join('、')} 未能取到真实历史数据，其结果仅供流程演示，不可用于实盘。
        </Alert>
      )}
      {!result.feasible && (
        <Alert tone="danger" title="约束无解，已退回等权可行解">
          {result.infeasible_reason || '当前约束组合无法同时满足，请放宽单标的上限或降低总仓位。'}
        </Alert>
      )}
      {result.constraints?.max_weight_relaxed && (
        <Alert tone="warn" title="单标的上限已被自动放宽">
          你设定的上限是 {(result.constraints.max_weight * 100).toFixed(0)}%，但生效上限是{' '}
          {(result.constraints.effective_max_weight * 100).toFixed(2)}%。详见下方「备注」。
        </Alert>
      )}

      {/* ============ 人话结论（先给结论，再给数字） ============ */}
      <Card title="这次优化到底怎么样">
        <ResultSummary
          result={result}
          objectiveLabel={objectiveLabel || result.objective}
          benchmarkNote={
            <>
              {' '}
              等权基准 = 这 {result.symbols.length} 个标的每个都买同样多。
            </>
          }
        />
      </Card>

      {/* ============ 四张关键指标卡 ============ */}
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Stat
          label="预期年化收益"
          value={fmtRatioPct(result.portfolio.ann_return, 2, true)}
          sub={`等权基准 ${fmtRatioPct(result.benchmark_equal_weight.ann_return, 2, true)}`}
          tone={result.portfolio.ann_return >= 0 ? 'up' : 'down'}
          icon={<TrendingUp className="h-4 w-4" />}
        />
        <Stat
          label="预期年化波动"
          value={fmtRatioPct(result.portfolio.ann_vol)}
          sub={`等权基准 ${fmtRatioPct(result.benchmark_equal_weight.ann_vol)}`}
          icon={<Layers className="h-4 w-4" />}
        />
        <Stat
          label="预期夏普"
          value={fmtNum(result.portfolio.sharpe, 2)}
          sub={
            <span className={signClass(result.portfolio.sharpe - result.benchmark_equal_weight.sharpe)}>
              相对等权{' '}
              {result.portfolio.sharpe - result.benchmark_equal_weight.sharpe >= 0 ? '+' : ''}
              {fmtNum(result.portfolio.sharpe - result.benchmark_equal_weight.sharpe, 2)}
            </span>
          }
          icon={<Sparkles className="h-4 w-4" />}
        />
        <Stat
          label="有效标的数"
          value={fmtNum(result.portfolio.effective_n, 1)}
          sub={`名义 ${result.symbols.length} 个 · 分散化比率 ${fmtNum(result.portfolio.diversification_ratio, 2)}`}
          icon={<Wallet className="h-4 w-4" />}
        />
      </div>

      <Card
        title="权重与明细"
        subtitle={`${result.objective} · 数据源 ${result.data_source_used} · ${
          result.feasible ? '约束满足' : '已回退可行解'
        }`}
        actions={
          <>
            <Button size="sm" icon={<Download className="h-3.5 w-3.5" />} onClick={onExportCsv}>
              导出 CSV
            </Button>
            <Button size="sm" variant="primary" icon={<Save className="h-3.5 w-3.5" />} onClick={onOpenSave}>
              另存为策略
            </Button>
          </>
        }
        bodyClass="p-0 max-h-[70vh] overflow-y-auto"
      >
        <Tabs
          className="m-3"
          value={tab}
          onChange={setTab}
          tabs={[
            { key: 'weights', label: '权重配置', badge: result.symbols.length },
            { key: 'frontier', label: '有效前沿', badge: result.frontier.length },
            { key: 'corr', label: '相关性' },
            { key: 'notes', label: '备注', badge: result.notes.length },
          ]}
        />

        {tab === 'weights' && (
          <div className="space-y-4 px-3 pb-3">
            <DataTable<AssetStat>
              columns={[
                {
                  key: 'sym',
                  label: '标的',
                  width: '96px',
                  render: (r) => <span className="font-medium text-slate-800">{r.symbol}</span>,
                },
                {
                  key: 'w',
                  label: <TermTip id="target_weight">目标权重</TermTip>,
                  width: '190px',
                  render: (r) => (
                    <div className="flex items-center gap-2">
                      <div className="w-20">
                        <Progress value={r.weight * 100} max={100} tone="brand" />
                      </div>
                      <span className="num text-sm font-medium text-slate-800">{fmtRatioPct(r.weight, 2)}</span>
                    </div>
                  ),
                },
                {
                  key: 'rc',
                  label: <TermTip id="risk_contrib">风险贡献</TermTip>,
                  align: 'right',
                  render: (r) => <span className="num text-slate-700">{fmtNum(r.risk_contrib_pct, 1)}%</span>,
                },
                {
                  key: 'ret',
                  label: '年化收益',
                  align: 'right',
                  render: (r) => (
                    <span className={`num ${signClass(r.ann_return)}`}>{fmtRatioPct(r.ann_return, 1, true)}</span>
                  ),
                },
                {
                  key: 'vol',
                  label: '年化波动',
                  align: 'right',
                  render: (r) => <span className="num text-slate-600">{fmtRatioPct(r.ann_vol, 1)}</span>,
                },
                {
                  key: 'sharpe',
                  label: <TermTip id="sharpe">夏普</TermTip>,
                  align: 'right',
                  render: (r) => <span className="num text-slate-600">{fmtNum(r.sharpe, 2)}</span>,
                },
                {
                  key: 'dd',
                  label: <TermTip id="max_drawdown">最大回撤</TermTip>,
                  align: 'right',
                  render: (r) => <span className="num text-emerald-600">{fmtRatioPct(r.max_drawdown, 1)}</span>,
                },
                {
                  key: 'obs',
                  label: '样本数',
                  align: 'right',
                  render: (r) => <span className="num text-slate-400">{r.obs}</span>,
                },
              ]}
              rows={sorted}
              rowKey={(r) => r.symbol}
            />

            <div className="grid gap-3 lg:grid-cols-2">
              <div className="rounded-lg border border-slate-200 p-3">
                <div className="mb-2 flex items-center gap-1.5 text-xs font-medium text-slate-600">
                  权重分布
                  <TermTip id="target_weight" dotted={false}>
                    <Info className="h-3.5 w-3.5 text-slate-300" />
                  </TermTip>
                </div>
                <HBar
                  height={Math.max(140, result.assets.length * 26)}
                  data={sorted.map((a) => ({ name: a.symbol, value: Number((a.weight * 100).toFixed(2)) }))}
                  valueFormatter={(v: number) => `${v.toFixed(1)}%`}
                />
              </div>
              <div className="rounded-lg border border-slate-200 p-3">
                <div className="mb-2 flex items-center gap-1.5 text-xs font-medium text-slate-600">
                  风险贡献分布（占比 %）
                  <TermTip id="risk_contrib" dotted={false}>
                    <Info className="h-3.5 w-3.5 text-slate-300" />
                  </TermTip>
                </div>
                <HBar
                  height={Math.max(140, result.assets.length * 26)}
                  color="#f59e0b"
                  data={[...result.assets]
                    .sort((a, b) => b.risk_contrib_pct - a.risk_contrib_pct)
                    .map((a) => ({ name: a.symbol, value: Number(a.risk_contrib_pct.toFixed(2)) }))}
                  valueFormatter={(v: number) => `${v.toFixed(1)}%`}
                />
              </div>
            </div>

            {result.clusters.length > 0 && (
              <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-xs text-amber-900">
                <div className="mb-1 font-medium">
                  检测到 <TermTip id="cluster">高相关簇</TermTip>（伪分散风险）
                </div>
                相关系数 ≥ {(result.constraints.corr_threshold * 100).toFixed(0)}% 的标的会被归为一伙，
                每伙总权重被限制在 {(result.constraints.max_cluster_weight * 100).toFixed(0)}% 以内：
                <div className="mt-1.5 flex flex-wrap gap-1.5">
                  {result.clusters.map((c, i) => (
                    <Badge key={i} tone="amber">
                      {c.join(' / ')} ·{' '}
                      {fmtRatioPct(
                        c.reduce((s, k) => s + (result.weights[k] || 0), 0),
                        1,
                      )}
                    </Badge>
                  ))}
                </div>
              </div>
            )}

            <div className="rounded-lg border border-slate-200 bg-slate-50 p-3">
              <div className="mb-1.5 flex items-center gap-1.5 text-xs font-medium text-slate-600">
                <Info className="h-3.5 w-3.5" />
                与等权基准逐项对比
              </div>
              <div className="grid gap-x-6 gap-y-1.5 text-xs sm:grid-cols-3">
                {(
                  [
                    ['年化收益', 'ann_return', 'pct'],
                    ['年化波动', 'ann_vol', 'pct'],
                    ['夏普比率', 'sharpe', 'num'],
                    ['分散化比率', 'diversification_ratio', 'num'],
                    ['有效标的数', 'effective_n', 'num'],
                    ['风险集中度', 'risk_concentration', 'num'],
                  ] as const
                ).map(([label, key, kind]) => {
                  const a = (result.portfolio as any)[key] as number
                  const b = (result.benchmark_equal_weight as any)[key] as number
                  const fmt = (v: number) => (kind === 'pct' ? fmtRatioPct(v, 2, true) : fmtNum(v, 2))
                  return (
                    <div
                      key={key}
                      className="flex items-baseline justify-between gap-3 border-b border-dashed border-slate-200 pb-1"
                    >
                      <span className="text-slate-500">{label}</span>
                      <span className="num">
                        <span className="font-medium text-slate-800">{fmt(a)}</span>
                        <span className="text-slate-400"> vs </span>
                        <span className="text-slate-500">{fmt(b)}</span>
                      </span>
                    </div>
                  )
                })}
              </div>
            </div>
          </div>
        )}

        {tab === 'frontier' && <FrontierTab result={result} />}

        {tab === 'corr' && (
          <div className="space-y-3 px-3 pb-3">
            <CorrelationMatrix corr={corrMatrix} />
            <p className="text-xs text-slate-500">
              蓝色为同向、橙色为反向。相关系数接近 1 的标的并排放置时几乎没有分散效果 ——
              这就是为什么优化器要对它们加总权重上限。真正的分散来自低相关，而非标的数量。
            </p>
          </div>
        )}

        {tab === 'notes' && (
          <div className="space-y-3 px-3 pb-3">
            <ul className="space-y-1.5 text-xs text-slate-600">
              {result.notes.map((n, i) => (
                <li key={i} className="flex gap-2">
                  <span className="text-slate-300">•</span>
                  <span className={n.startsWith('⚠️') ? 'text-amber-700' : undefined}>{n}</span>
                </li>
              ))}
            </ul>
            <div className="rounded-lg border border-slate-200 p-3 text-xs text-slate-500">
              <div className="mb-1 font-medium text-slate-600">本轮参数</div>
              <pre className="num overflow-x-auto text-[11px] leading-relaxed">
                {JSON.stringify(
                  { constraints: result.constraints, params: result.params, data_sources: result.data_sources },
                  null,
                  2,
                )}
              </pre>
            </div>
            {(meta?.notes ?? []).length > 0 && (
              <div className="rounded-lg border border-slate-200 bg-slate-50 p-3 text-xs text-slate-500">
                <div className="mb-1 font-medium text-slate-600">使用注意</div>
                <ul className="space-y-1">
                  {meta!.notes.map((n, i) => (
                    <li key={i}>· {n}</li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        )}
      </Card>

      {/* AI 寻优解读：判断最优解是「参数平台期」还是「孤峰」（过拟合嫌疑） */}
      <AIAssist
        mode="panel"
        task="optimize_review"
        title="AI 寻优解读"
        desc="判断最优解可信度、参数稳定性，以及与等权基准相比超额的来源"
        label="解读寻优结果"
        runKey={`${result.objective}:${result.symbols?.join(',')}:${result.frontier?.length ?? 0}`}
        payload={{
          method: result.params?.method || 'max_sharpe',
          objective: result.objective,
          symbols: result.symbols,
          grid_size: result.frontier?.length,
          best: result.weights,
          best_metrics: result.portfolio,
          baseline: result.benchmark_equal_weight,
          constraints: result.constraints,
          top_neighbors: (result.frontier || []).slice(-12),
        }}
        emptyHint="点击上方「解读寻优结果」按钮，AI 会检查最优解周边邻居的表现差距，并提示该不该直接采用这组权重。"
      />
    </div>
  )
}
