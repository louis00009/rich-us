/**
 * 组合优化 —— 从「一篮子标的」求解「配多少仓位」。
 *
 * 与回测中心的「参数寻优」区分：那边搜策略参数，这边解资金权重。
 * 核心不是按一个按钮，而是先看等权基准能不能被打败——打不过就别优化。
 */
import {
  Download,
  Info,
  Layers,
  Play,
  RotateCcw,
  Save,
  Sparkles,
  Target,
  TrendingUp,
  Wallet,
} from 'lucide-react'
import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  CorrelationMatrix,
  EfficientFrontierChart,
  HBar,
} from '../components/charts'
import {
  Alert,
  Badge,
  Button,
  Card,
  DataTable,
  Empty,
  Field,
  Input,
  Modal,
  Progress,
  Select,
  Stat,
  Switch,
  Tabs,
  useToast,
} from '../components/ui'
import { api, LONG_TIMEOUT } from '../lib/api'
import { fmtNum, fmtRatioPct, signClass } from '../lib/format'

/* ---------------- 类型 ---------------- */
interface Meta {
  objectives: { key: string; label: string; desc: string }[]
  cov_methods: { key: string; label: string; desc: string }[]
  return_methods: { key: string; label: string; desc: string }[]
  defaults: Record<string, any>
  notes: string[]
}

interface PStats {
  ann_return: number
  ann_vol: number
  sharpe: number
  diversification_ratio: number
  effective_n: number
  risk_concentration: number
  gross: number
}

interface AssetStat {
  symbol: string
  weight: number
  ann_return: number
  ann_vol: number
  sharpe: number
  max_drawdown: number
  risk_contrib_pct: number
  obs: number
}

interface OptResult {
  ok: boolean
  objective: string
  symbols: string[]
  weights: Record<string, number>
  feasible: boolean
  infeasible_reason: string
  portfolio: PStats
  benchmark_equal_weight: PStats
  assets: AssetStat[]
  correlation: { symbols: string[]; matrix: number[][] }
  clusters: string[][]
  frontier: { lambda: number; ret: number; vol: number; sharpe: number }[]
  constraints: Record<string, any>
  params: Record<string, any>
  notes: string[]
  data_sources: Record<string, string>
  data_source_used: string
  synthetic_symbols: string[]
}

const PRESETS: { name: string; symbols: string }[] = [
  { name: '核心宽基', symbols: 'SPY, QQQ, IWM, EFA, EEM, AGG, GLD' },
  { name: '科技七巨头', symbols: 'AAPL, MSFT, NVDA, GOOGL, AMZN, META, TSLA' },
  { name: '股债商均衡', symbols: 'SPY, TLT, IEF, GLD, DBC, VNQ' },
  { name: '低相关尝试', symbols: 'SPY, TLT, GLD, UUP, XLE, XLK' },
]

export default function Optimize() {
  const toast = useToast()
  const [meta, setMeta] = useState<Meta | null>(null)
  const [symbolsText, setSymbolsText] = useState('SPY, QQQ, IWM, EFA, EEM, AGG, GLD')
  const [start, setStart] = useState('2019-01-01')
  const [interval, setInterval] = useState('1d')

  const [objective, setObjective] = useState('max_sharpe')
  const [covMethod, setCovMethod] = useState('ledoit_wolf')
  const [returnMethod, setReturnMethod] = useState('shrunk')
  const [maxWeight, setMaxWeight] = useState(35)
  const [maxGross, setMaxGross] = useState(100)
  const [corrThreshold, setCorrThreshold] = useState(85)
  const [maxCluster, setMaxCluster] = useState(50)
  const [riskFree, setRiskFree] = useState(0)
  const [longOnly, setLongOnly] = useState(true)
  const [useBudget, setUseBudget] = useState(false)
  const [budgetText, setBudgetText] = useState('')
  const [includeFrontier, setIncludeFrontier] = useState(true)

  const [running, setRunning] = useState(false)
  const [result, setResult] = useState<OptResult | null>(null)
  const [tab, setTab] = useState('weights')

  const [saveOpen, setSaveOpen] = useState(false)
  const [saveName, setSaveName] = useState('')
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    api
      .get<Meta>('/optimize/meta')
      .then((m) => {
        setMeta(m)
        const d = m.defaults
        setObjective(d.objective)
        setCovMethod(d.cov_method)
        setReturnMethod(d.return_method)
        setMaxWeight(Math.round(d.max_weight * 100))
        setMaxGross(Math.round(d.max_gross * 100))
        setCorrThreshold(Math.round(d.corr_threshold * 100))
        setMaxCluster(Math.round(d.max_cluster_weight * 100))
        setLongOnly(!!d.long_only)
        setIncludeFrontier(d.include_frontier !== false)
      })
      .catch(() => toast('error', '加载优化器参数失败，请确认后端已启动'))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const symbols = useMemo(
    () =>
      Array.from(
        new Set(
          symbolsText
            .split(/[\s,;]+/)
            .map((s) => s.trim().toUpperCase())
            .filter((s) => /^[\^A-Z][A-Z0-9.\-]{0,9}$/.test(s)),
        ),
      ),
    [symbolsText],
  )

  const budget = useMemo(() => {
    if (!useBudget) return {}
    const out: Record<string, number> = {}
    budgetText
      .split(/[\s,;]+/)
      .map((s) => s.trim())
      .filter(Boolean)
      .forEach((tok) => {
        const [k, v] = tok.split(/[:=]/)
        if (!k) return
        const num = Number(v)
        if (Number.isFinite(num) && num >= 0) out[k.trim().toUpperCase()] = num
      })
    return out
  }, [useBudget, budgetText])

  // 单标的上限 × 标的数 < 总仓位时约束不可行，前端先提示，避免用户白等一次计算
  const capInfeasible = symbols.length > 1 && (maxWeight / 100) * symbols.length < maxGross / 100 - 1e-9

  const run = useCallback(async () => {
    if (symbols.length < 2) {
      toast('warning', '至少需要 2 个有效标的')
      return
    }
    setRunning(true)
    try {
      const res = await api.post<OptResult>(
        '/optimize/run',
        {
          symbols,
          start,
          interval,
          objective,
          cov_method: covMethod,
          return_method: returnMethod,
          risk_free_rate: riskFree / 100,
          max_weight: maxWeight / 100,
          max_gross: maxGross / 100,
          long_only: longOnly,
          corr_threshold: corrThreshold / 100,
          max_cluster_weight: maxCluster / 100,
          risk_budget: budget,
          include_frontier: includeFrontier,
        },
        LONG_TIMEOUT,
      )
      setResult(res)
      setTab('weights')
      if (res.synthetic_symbols?.length) {
        toast('warning', `注意：${res.synthetic_symbols.join('、')} 为合成行情，非真实数据`)
      } else {
        toast('success', `优化完成：预期夏普 ${fmtNum(res.portfolio.sharpe, 2)}，有效标的数 ${fmtNum(res.portfolio.effective_n, 1)}`)
      }
    } catch (e: any) {
      toast('error', e?.message || '优化失败')
    } finally {
      setRunning(false)
    }
  }, [
    symbols, start, interval, objective, covMethod, returnMethod, riskFree,
    maxWeight, maxGross, longOnly, corrThreshold, maxCluster, budget, includeFrontier, toast,
  ])

  const resetParams = () => {
    if (!meta) return
    const d = meta.defaults
    setObjective(d.objective)
    setCovMethod(d.cov_method)
    setReturnMethod(d.return_method)
    setMaxWeight(Math.round(d.max_weight * 100))
    setMaxGross(Math.round(d.max_gross * 100))
    setCorrThreshold(Math.round(d.corr_threshold * 100))
    setMaxCluster(Math.round(d.max_cluster_weight * 100))
    setRiskFree(Math.round((d.risk_free_rate || 0) * 100))
    setLongOnly(!!d.long_only)
    setIncludeFrontier(d.include_frontier !== false)
    setUseBudget(false)
    toast('info', '已恢复默认参数')
  }

  const doSave = async () => {
    if (!result) return
    if (!saveName.trim()) {
      toast('warning', '请填写策略名')
      return
    }
    setSaving(true)
    try {
      const r = await api.post<{ id: number; name: string }>('/optimize/save', {
        name: saveName.trim(),
        symbols: result.symbols,
        weights: result.weights,
        objective: result.objective,
        notes: `优化区间 ${start} 起 · ${result.params.cov_method} · 预期夏普 ${fmtNum(result.portfolio.sharpe, 2)}`,
      })
      toast('success', `已保存为策略「${r.name}」（#${r.id}），可在策略实验室直接回测`)
      setSaveOpen(false)
      setSaveName('')
    } catch (e: any) {
      toast('error', e?.message || '保存失败')
    } finally {
      setSaving(false)
    }
  }

  const exportCsv = () => {
    if (!result) return
    const rows = [
      'symbol,weight,ann_return,ann_vol,sharpe,max_drawdown,risk_contrib_pct,obs',
      ...result.assets.map((a) =>
        [a.symbol, a.weight, a.ann_return, a.ann_vol, a.sharpe, a.max_drawdown, a.risk_contrib_pct, a.obs].join(','),
      ),
      '',
      `# 目标,${result.objective}`,
      `# 协方差,${result.params.cov_method}`,
      `# 期望收益,${result.params.return_method}`,
      `# 组合年化收益,${result.portfolio.ann_return}`,
      `# 组合年化波动,${result.portfolio.ann_vol}`,
      `# 组合夏普,${result.portfolio.sharpe}`,
      `# 等权年化收益,${result.benchmark_equal_weight.ann_return}`,
      `# 等权年化波动,${result.benchmark_equal_weight.ann_vol}`,
      `# 等权夏普,${result.benchmark_equal_weight.sharpe}`,
      `# 数据源,${result.data_source_used}`,
    ].join('\n')
    const blob = new Blob(['\ufeff' + rows], { type: 'text/csv;charset=utf-8' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `quantdesk_optimize_${result.symbols.slice(0, 3).join('_')}.csv`
    a.click()
    URL.revokeObjectURL(url)
    toast('success', '已导出权重与逐标的指标（CSV）')
  }

  const corrMatrix = useMemo(() => {
    if (!result) return {}
    const { symbols: syms, matrix } = result.correlation
    const out: Record<string, Record<string, number | null>> = {}
    syms.forEach((a, i) => {
      out[a] = {}
      syms.forEach((b, j) => {
        out[a][b] = matrix[i]?.[j] ?? null
      })
    })
    return out
  }, [result])

  const beatEqual = result
    ? result.portfolio.sharpe - result.benchmark_equal_weight.sharpe
    : 0

  return (
    <div className="space-y-4">
      {/* ============ 参数区 ============ */}
      <Card
        title="标的与约束"
        subtitle="输入一篮子标的，求解在约束下的最优资金权重"
        actions={
          <>
            <Button size="sm" icon={<RotateCcw className="h-3.5 w-3.5" />} onClick={resetParams}>
              恢复默认
            </Button>
            <Button
              size="sm"
              variant="primary"
              icon={<Play className="h-3.5 w-3.5" />}
              loading={running}
              onClick={run}
              disabled={symbols.length < 2}
            >
              {running ? '求解中…' : '运行优化'}
            </Button>
          </>
        }
      >
        <div className="space-y-4">
          <Field
            label="标的池（逗号或空格分隔）"
            hint={
              symbols.length
                ? `已识别 ${symbols.length} 个：${symbols.join(' · ')}`
                : '至少输入 2 个美股/ETF 代码，例如 SPY, QQQ, TLT, GLD'
            }
          >
            <Input
              value={symbolsText}
              onChange={(e) => setSymbolsText(e.target.value)}
              placeholder="SPY, QQQ, IWM, EFA, EEM, AGG, GLD"
            />
          </Field>

          <div className="flex flex-wrap gap-2">
            {PRESETS.map((p) => (
              <button
                key={p.name}
                onClick={() => setSymbolsText(p.symbols)}
                className="rounded-md border border-slate-200 px-2.5 py-1 text-xs text-slate-600 hover:border-brand-300 hover:bg-brand-50 hover:text-brand-700"
              >
                {p.name}
              </button>
            ))}
            <span className="self-center text-[11px] text-slate-400">快捷标的池</span>
          </div>

          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <Field label="起始日期">
              <Input value={start} onChange={(e) => setStart(e.target.value)} placeholder="2019-01-01" />
            </Field>
            <Field label="周期">
              <Select value={interval} onChange={(e) => setInterval(e.target.value)}>
                <option value="1d">日线</option>
                <option value="1wk">周线</option>
              </Select>
            </Field>
            <Field label="优化目标" hint={meta?.objectives.find((o) => o.key === objective)?.desc}>
              <Select value={objective} onChange={(e) => setObjective(e.target.value)}>
                {(meta?.objectives ?? []).map((o) => (
                  <option key={o.key} value={o.key}>
                    {o.label}
                  </option>
                ))}
              </Select>
            </Field>
            <Field label="无风险利率（%）" hint="用于计算夏普比率">
              <Input
                type="number"
                step={0.1}
                value={riskFree}
                onChange={(e) => setRiskFree(Number(e.target.value))}
              />
            </Field>
          </div>

          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <Field label="协方差估计" hint={meta?.cov_methods.find((o) => o.key === covMethod)?.desc}>
              <Select value={covMethod} onChange={(e) => setCovMethod(e.target.value)}>
                {(meta?.cov_methods ?? []).map((o) => (
                  <option key={o.key} value={o.key}>
                    {o.label}
                  </option>
                ))}
              </Select>
            </Field>
            <Field label="期望收益估计" hint={meta?.return_methods.find((o) => o.key === returnMethod)?.desc}>
              <Select value={returnMethod} onChange={(e) => setReturnMethod(e.target.value)}>
                {(meta?.return_methods ?? []).map((o) => (
                  <option key={o.key} value={o.key}>
                    {o.label}
                  </option>
                ))}
              </Select>
            </Field>
            <Field label="单标的上限（%）" hint={`上限 × 标的数 = ${((maxWeight / 100) * symbols.length * 100).toFixed(0)}%，需 ≥ 总仓位`}>
              <Input
                type="number"
                min={1}
                max={100}
                value={maxWeight}
                onChange={(e) => setMaxWeight(Number(e.target.value))}
              />
            </Field>
            <Field label="总仓位（%）" hint="100% 为满仓，可设为 80% 保留现金">
              <Input
                type="number"
                min={1}
                max={400}
                value={maxGross}
                onChange={(e) => setMaxGross(Number(e.target.value))}
              />
            </Field>
          </div>

          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <Field label="相关簇阈值（%）" hint="相关系数 ≥ 阈值即视为同一簇">
              <Input
                type="number"
                min={0}
                max={100}
                value={corrThreshold}
                onChange={(e) => setCorrThreshold(Number(e.target.value))}
              />
            </Field>
            <Field label="单簇上限（%）" hint="伪分散防护：同一簇总权重不超过此值">
              <Input
                type="number"
                min={1}
                max={100}
                value={maxCluster}
                onChange={(e) => setMaxCluster(Number(e.target.value))}
              />
            </Field>
            <div className="space-y-3 pt-5">
              <Switch checked={longOnly} onChange={setLongOnly} label="仅做多" hint="关闭则允许负权重（做空/杠杆，本机回测暂不支持负仓位撮合）" />
              <Switch checked={includeFrontier} onChange={setIncludeFrontier} label="计算有效前沿" hint="关闭可显著加快求解" />
            </div>
            <div className="space-y-2 pt-5">
              <Switch checked={useBudget} onChange={setUseBudget} label="启用风险预算" hint="格式：SPY:3, TLT:2, GLD:1" />
              {useBudget && (
                <Input value={budgetText} onChange={(e) => setBudgetText(e.target.value)} placeholder="SPY:3, TLT:2, GLD:1" />
              )}
            </div>
          </div>

          {capInfeasible && (
            <Alert tone="warn" title="约束不可行：单标的上限 × 标的数 < 总仓位">
              当前 {maxWeight}% × {symbols.length} = {maxWeight * symbols.length}% 小于总仓位 {maxGross}%。
              求解器会自动把上限放宽到 {(maxGross / symbols.length).toFixed(1)}% 并显式标注；
              若你要严格守住 {maxWeight}%，请把总仓位降到 {maxWeight * symbols.length}% 以下，或增加标的数。
            </Alert>
          )}
        </div>
      </Card>

      {/* ============ 结果区 ============ */}
      {!result ? (
        <Card>
          <Empty
            icon={<Target className="h-8 w-8" />}
            title="尚未运行优化"
            desc="输入标的池与约束后点击「运行优化」。建议先看一眼等权基准的夏普——如果优化结果打不过等权，说明这篮子标的本身就没什么可优化的空间。"
          />
        </Card>
      ) : (
        <>
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
              你设定的上限是 {(result.constraints.max_weight * 100).toFixed(0)}%，
              但生效上限是 {(result.constraints.effective_max_weight * 100).toFixed(2)}%。
              详见下方「备注」。
            </Alert>
          )}

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
                <span className={signClass(beatEqual)}>
                  相对等权 {beatEqual >= 0 ? '+' : ''}
                  {fmtNum(beatEqual, 2)}
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

          {beatEqual < 0 && (
            <Alert tone="warn" title="优化结果没有跑赢等权基准">
              在 {corrThreshold}% 相关阈值与 {maxWeight}% 单标的上限下，优化组合的预期夏普低于 1/N 等权。
              这通常意味着历史均值/协方差估计的噪声吃掉了优化收益——放宽约束或延长样本区间再试，
              也可以直接采用等权（简单且难以被击败）。
            </Alert>
          )}

          <Card
            title="优化结果"
            subtitle={`${result.objective} · 数据源 ${result.data_source_used} · ${
              result.feasible ? '约束满足' : '已回退可行解'
            }`}
            actions={
              <>
                <Button size="sm" icon={<Download className="h-3.5 w-3.5" />} onClick={exportCsv}>
                  导出 CSV
                </Button>
                <Button size="sm" variant="primary" icon={<Save className="h-3.5 w-3.5" />} onClick={() => setSaveOpen(true)}>
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
                      label: '目标权重',
                      width: '190px',
                      render: (r) => (
                        <div className="flex items-center gap-2">
                          <div className="w-20">
                            <Progress value={r.weight * 100} max={100} tone="brand" />
                          </div>
                          <span className="num text-sm font-medium text-slate-800">
                            {fmtRatioPct(r.weight, 2)}
                          </span>
                        </div>
                      ),
                    },
                    {
                      key: 'rc',
                      label: '风险贡献',
                      align: 'right',
                      render: (r) => (
                        <span className="num text-slate-700">{fmtNum(r.risk_contrib_pct, 1)}%</span>
                      ),
                    },
                    {
                      key: 'ret',
                      label: '年化收益',
                      align: 'right',
                      render: (r) => (
                        <span className={`num ${signClass(r.ann_return)}`}>
                          {fmtRatioPct(r.ann_return, 1, true)}
                        </span>
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
                      label: '夏普',
                      align: 'right',
                      render: (r) => <span className="num text-slate-600">{fmtNum(r.sharpe, 2)}</span>,
                    },
                    {
                      key: 'dd',
                      label: '最大回撤',
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
                  rows={[...result.assets].sort((a, b) => b.weight - a.weight)}
                  rowKey={(r) => r.symbol}
                />

                <div className="grid gap-3 lg:grid-cols-2">
                  <div className="rounded-lg border border-slate-200 p-3">
                    <div className="mb-2 text-xs font-medium text-slate-600">权重分布</div>
                    <HBar
                      height={Math.max(140, result.assets.length * 26)}
                      data={[...result.assets]
                        .sort((a, b) => b.weight - a.weight)
                        .map((a) => ({ name: a.symbol, value: Number((a.weight * 100).toFixed(2)) }))}
                      valueFormatter={(v: number) => `${v.toFixed(1)}%`}
                    />
                  </div>
                  <div className="rounded-lg border border-slate-200 p-3">
                    <div className="mb-2 text-xs font-medium text-slate-600">风险贡献分布（占比 %）</div>
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
                    <div className="mb-1 font-medium">检测到高相关簇（伪分散风险）</div>
                    相关系数 ≥ {(result.constraints.corr_threshold * 100).toFixed(0)}% 的标的会被归为一簇，
                    每簇总权重被限制在 {(result.constraints.max_cluster_weight * 100).toFixed(0)}% 以内：
                    <div className="mt-1.5 flex flex-wrap gap-1.5">
                      {result.clusters.map((c, i) => (
                        <Badge key={i} tone="amber">
                          {c.join(' / ')} · {fmtRatioPct(c.reduce((s, k) => s + (result.weights[k] || 0), 0), 1)}
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
                        <div key={key} className="flex items-baseline justify-between gap-3 border-b border-dashed border-slate-200 pb-1">
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

            {tab === 'frontier' && (
              <div className="space-y-3 px-3 pb-3">
                <EfficientFrontierChart
                  points={result.frontier}
                  current={{ ret: result.portfolio.ann_return, vol: result.portfolio.ann_vol }}
                  equalWeight={{
                    ret: result.benchmark_equal_weight.ann_return,
                    vol: result.benchmark_equal_weight.ann_vol,
                  }}
                  assets={result.assets}
                />
                <p className="text-xs text-slate-500">
                  横轴为年化波动、纵轴为年化收益。灰色散点为各标的自身位置，金色三角为 1/N 等权基准，
                  紫色星号为当前优化解。理论上最优组合应位于前沿曲线与「最大夏普射线」的切点上——
                  若它反而落在曲线内侧，说明约束（单标的上限 / 簇上限）把它从最优点上拽了回来。
                </p>
                <DataTable
                  columns={[
                    { key: 'i', label: '#', width: '48px', render: (_r, i) => <span className="num text-slate-400">{i + 1}</span> },
                    { key: 'lam', label: 'λ', align: 'right', render: (r: any) => <span className="num text-slate-500">{fmtNum(r.lambda, 4)}</span> },
                    { key: 'vol', label: '年化波动', align: 'right', render: (r: any) => <span className="num">{fmtRatioPct(r.vol)}</span> },
                    { key: 'ret', label: '年化收益', align: 'right', render: (r: any) => <span className={`num ${signClass(r.ret)}`}>{fmtRatioPct(r.ret, 2, true)}</span> },
                    { key: 'sharpe', label: '夏普', align: 'right', render: (r: any) => <span className="num">{fmtNum(r.sharpe, 3)}</span> },
                  ]}
                  rows={result.frontier}
                  maxHeight="320px"
                />
              </div>
            )}

            {tab === 'corr' && (
              <div className="space-y-3 px-3 pb-3">
                <CorrelationMatrix corr={corrMatrix} />
                <p className="text-xs text-slate-500">
                  蓝色为同向、橙色为反向。相关系数接近 1 的标的并排放置时几乎没有分散效果——
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
{JSON.stringify({ constraints: result.constraints, params: result.params, data_sources: result.data_sources }, null, 2)}
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
        </>
      )}

      <Modal
        open={saveOpen}
        onClose={() => setSaveOpen(false)}
        title="把权重另存为策略"
        footer={
          <>
            <Button onClick={() => setSaveOpen(false)}>取消</Button>
            <Button variant="primary" loading={saving} onClick={doSave} icon={<Save className="h-3.5 w-3.5" />}>
              保存
            </Button>
          </>
        }
      >
        <div className="space-y-3">
          <Alert tone="info">
            将生成一个「恒定目标权重」的代码策略：每根 bar 输出同一组权重，引擎按权重再平衡。
            保存后可在「策略实验室」直接回测，或挂到实时引擎上运行。
          </Alert>
          <Field label="策略名称" hint="需唯一，建议带上目标与区间，例如「最大夏普-核心宽基-2019起」">
            <Input
              value={saveName}
              onChange={(e) => setSaveName(e.target.value)}
              placeholder="最大夏普 · 核心宽基"
            />
          </Field>
          {result && (
            <div className="rounded-lg border border-slate-200 p-3 text-xs">
              <div className="mb-1 font-medium text-slate-600">即将保存的权重</div>
              <div className="flex flex-wrap gap-1.5">
                {Object.entries(result.weights)
                  .filter(([, v]) => Math.abs(v) > 1e-6)
                  .sort((a, b) => b[1] - a[1])
                  .map(([k, v]) => (
                    <Badge key={k} tone="brand">
                      {k} {fmtRatioPct(v, 1)}
                    </Badge>
                  ))}
              </div>
            </div>
          )}
        </div>
      </Modal>
    </div>
  )
}
