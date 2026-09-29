/**
 * 组合优化 —— 从「一篮子标的」求解「配多少仓位」。
 *
 * 与回测中心的「参数寻优」区分：那边搜策略参数，这边解资金权重。
 * 核心不是按一个按钮，而是先看等权基准能不能被打败——打不过就别优化。
 *
 * ⚠️ 本文件是**编排层**：只持有配置状态 + 取数 + 组装子组件。
 *    页面规模铁律（600 软上限）此前被突破到 861 行，已按回测页的成功模式拆分：
 *      - `components/optimize/ConfigPanel.tsx`     四步向导 + 新手模式
 *      - `components/optimize/ResultPanel.tsx`     结果区（指标卡 / 权重表 / 三个 tab）
 *      - `components/optimize/PlainSummary.tsx`    人话预览与结论（含纯函数判定）
 *      - `components/optimize/SaveModal.tsx`       另存为策略
 *      - `components/optimize/{types,presets}.ts`  共享类型与预设值
 *    配置状态集中在**这里**一处，因为一键推荐 / 恢复默认 / localStorage 三条写入
 *    路径都会改它，拆开必然出现「两个真相」。
 */
import { FlaskConical, Target } from 'lucide-react'
import { useCallback, useEffect, useMemo, useState } from 'react'
import OptimizeConfigPanel from '../components/optimize/ConfigPanel'
import OptimizeResultPanel from '../components/optimize/ResultPanel'
import SaveStrategyModal from '../components/optimize/SaveModal'
import { DEFAULT_OBJECTIVE, RECOMMENDED } from '../components/optimize/presets'
import type { Meta, OptForm, OptResult, OptSetters } from '../components/optimize/types'
import { Card, Empty, useToast } from '../components/ui'
import { api, LONG_TIMEOUT } from '../lib/api'
import { yearsAgo } from '../lib/dateRange'
import { fmtNum } from '../lib/format'
import { loadOptimizePrefs, parseBudget, parseSymbols, saveOptimizePrefs } from '../lib/optimizePrefs'

/**
 * 出厂默认值。数值与后端 `api/optimize.py::meta()['defaults']` 对齐，
 * 但**以后端为准** —— meta 加载完成后会用后端默认值覆盖（仅当用户没有本地偏好）。
 */
const DEFAULTS: OptForm = {
  symbolsText: 'SPY, TLT, IEF, GLD, DBC, VNQ',
  start: yearsAgo(5),
  interval: '1d',
  objective: DEFAULT_OBJECTIVE,
  covMethod: 'ledoit_wolf',
  returnMethod: 'shrunk',
  maxWeight: 35,
  maxGross: 100,
  corrThreshold: 85,
  maxCluster: 50,
  riskFree: 0,
  longOnly: true,
  useBudget: false,
  budgetText: '',
  includeFrontier: true,
}

/** 首屏表单：出厂默认 + 本地偏好（本地偏好优先）。 */
function initialForm(): OptForm {
  const p = loadOptimizePrefs()
  return {
    ...DEFAULTS,
    ...(p.symbolsText ? { symbolsText: p.symbolsText } : {}),
    ...(p.start ? { start: p.start } : {}),
    ...(p.interval ? { interval: p.interval } : {}),
    ...(p.objective ? { objective: p.objective } : {}),
    ...(p.covMethod ? { covMethod: p.covMethod } : {}),
    ...(p.returnMethod ? { returnMethod: p.returnMethod } : {}),
    ...(typeof p.maxWeight === 'number' ? { maxWeight: p.maxWeight } : {}),
    ...(typeof p.maxGross === 'number' ? { maxGross: p.maxGross } : {}),
    ...(typeof p.corrThreshold === 'number' ? { corrThreshold: p.corrThreshold } : {}),
    ...(typeof p.maxCluster === 'number' ? { maxCluster: p.maxCluster } : {}),
    ...(typeof p.riskFree === 'number' ? { riskFree: p.riskFree } : {}),
    ...(typeof p.longOnly === 'boolean' ? { longOnly: p.longOnly } : {}),
    ...(typeof p.useBudget === 'boolean' ? { useBudget: p.useBudget } : {}),
    ...(typeof p.budgetText === 'string' ? { budgetText: p.budgetText } : {}),
    ...(typeof p.includeFrontier === 'boolean' ? { includeFrontier: p.includeFrontier } : {}),
  }
}

export default function Optimize() {
  const toast = useToast()
  const [meta, setMeta] = useState<Meta | null>(null)
  const [form, setForm] = useState<OptForm>(initialForm)
  // 新手模式默认开：小白第一眼不该看到协方差估计与簇上限
  const [beginner, setBeginner] = useState(() => loadOptimizePrefs().beginner !== false)

  const [running, setRunning] = useState(false)
  const [result, setResult] = useState<OptResult | null>(null)

  const [saveOpen, setSaveOpen] = useState(false)
  const [saveName, setSaveName] = useState('')
  const [saving, setSaving] = useState(false)

  // 配置变化即持久化（内部已防抖 300ms）
  useEffect(() => {
    saveOptimizePrefs({ ...form, beginner })
  }, [form, beginner])

  useEffect(() => {
    api
      .get<Meta>('/optimize/meta')
      .then((m) => {
        setMeta(m)
        // 后端默认值只在用户没有本地偏好时生效 —— 否则每次进页面都会把
        // 用户调好的参数冲掉（回测页踩过同样的坑）。
        const d = m.defaults || {}
        const p = loadOptimizePrefs()
        setForm((f) => ({
          ...f,
          objective: p.objective ?? d.objective ?? f.objective,
          covMethod: p.covMethod ?? d.cov_method ?? f.covMethod,
          returnMethod: p.returnMethod ?? d.return_method ?? f.returnMethod,
          maxWeight: typeof p.maxWeight === 'number' ? p.maxWeight : Math.round((d.max_weight ?? 0.35) * 100),
          maxGross: typeof p.maxGross === 'number' ? p.maxGross : Math.round((d.max_gross ?? 1) * 100),
          corrThreshold:
            typeof p.corrThreshold === 'number' ? p.corrThreshold : Math.round((d.corr_threshold ?? 0.85) * 100),
          maxCluster:
            typeof p.maxCluster === 'number' ? p.maxCluster : Math.round((d.max_cluster_weight ?? 0.5) * 100),
          longOnly: typeof p.longOnly === 'boolean' ? p.longOnly : (d.long_only ?? true),
          includeFrontier:
            typeof p.includeFrontier === 'boolean' ? p.includeFrontier : d.include_frontier !== false,
        }))
      })
      .catch(() => toast('error', '加载优化器参数失败，请确认后端已启动'))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const set: OptSetters = useMemo(
    () => ({
      setSymbolsText: (v) => setForm((f) => ({ ...f, symbolsText: v })),
      setStart: (v) => setForm((f) => ({ ...f, start: v })),
      setInterval: (v) => setForm((f) => ({ ...f, interval: v })),
      setObjective: (v) => setForm((f) => ({ ...f, objective: v })),
      setCovMethod: (v) => setForm((f) => ({ ...f, covMethod: v })),
      setReturnMethod: (v) => setForm((f) => ({ ...f, returnMethod: v })),
      setMaxWeight: (v) => setForm((f) => ({ ...f, maxWeight: v })),
      setMaxGross: (v) => setForm((f) => ({ ...f, maxGross: v })),
      setCorrThreshold: (v) => setForm((f) => ({ ...f, corrThreshold: v })),
      setMaxCluster: (v) => setForm((f) => ({ ...f, maxCluster: v })),
      setRiskFree: (v) => setForm((f) => ({ ...f, riskFree: v })),
      setLongOnly: (v) => setForm((f) => ({ ...f, longOnly: v })),
      setUseBudget: (v) => setForm((f) => ({ ...f, useBudget: v })),
      setBudgetText: (v) => setForm((f) => ({ ...f, budgetText: v })),
      setIncludeFrontier: (v) => setForm((f) => ({ ...f, includeFrontier: v })),
    }),
    [],
  )

  const symbols = useMemo(() => parseSymbols(form.symbolsText), [form.symbolsText])
  const objectiveLabel = meta?.objectives.find((o) => o.key === form.objective)?.label ?? form.objective

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
          start: form.start,
          interval: form.interval,
          objective: form.objective,
          cov_method: form.covMethod,
          return_method: form.returnMethod,
          risk_free_rate: form.riskFree / 100,
          max_weight: form.maxWeight / 100,
          max_gross: form.maxGross / 100,
          long_only: form.longOnly,
          corr_threshold: form.corrThreshold / 100,
          max_cluster_weight: form.maxCluster / 100,
          risk_budget: form.useBudget ? parseBudget(form.budgetText) : {},
          include_frontier: form.includeFrontier,
        },
        LONG_TIMEOUT,
      )
      setResult(res)
      if (res.synthetic_symbols?.length) {
        toast('warning', `注意：${res.synthetic_symbols.join('、')} 为合成行情，非真实数据`)
      } else {
        const beat = res.portfolio.sharpe - res.benchmark_equal_weight.sharpe
        toast(
          'success',
          `优化完成：预期夏普 ${fmtNum(res.portfolio.sharpe, 2)}，相对等权 ${
            beat >= 0 ? '高' : '低'
          } ${fmtNum(Math.abs(beat), 2)}`,
        )
      }
    } catch (e: any) {
      toast('error', e?.message || '优化失败')
    } finally {
      setRunning(false)
    }
  }, [symbols, form, toast])

  const onApplyRecommended = useCallback(() => {
    setForm((f) => ({
      ...f,
      symbolsText: RECOMMENDED.symbols,
      start: yearsAgo(RECOMMENDED.years),
      interval: RECOMMENDED.interval,
      objective: RECOMMENDED.objective,
      maxWeight: RECOMMENDED.maxWeight,
      maxGross: RECOMMENDED.maxGross,
      corrThreshold: RECOMMENDED.corrThreshold,
      maxCluster: RECOMMENDED.maxCluster,
      riskFree: RECOMMENDED.riskFree,
      longOnly: RECOMMENDED.longOnly,
      includeFrontier: RECOMMENDED.includeFrontier,
      useBudget: false,
    }))
    toast('info', `已填入推荐配置：${RECOMMENDED.pool} · 近 ${RECOMMENDED.years} 年`)
  }, [toast])

  const onResetDefaults = useCallback(() => {
    const d = meta?.defaults || {}
    setForm((f) => ({
      ...f,
      objective: d.objective ?? DEFAULTS.objective,
      covMethod: d.cov_method ?? DEFAULTS.covMethod,
      returnMethod: d.return_method ?? DEFAULTS.returnMethod,
      maxWeight: Math.round((d.max_weight ?? 0.35) * 100),
      maxGross: Math.round((d.max_gross ?? 1) * 100),
      corrThreshold: Math.round((d.corr_threshold ?? 0.85) * 100),
      maxCluster: Math.round((d.max_cluster_weight ?? 0.5) * 100),
      riskFree: Math.round((d.risk_free_rate ?? 0) * 100),
      longOnly: !!d.long_only,
      includeFrontier: d.include_frontier !== false,
      useBudget: false,
    }))
    toast('info', '已恢复默认参数')
  }, [meta, toast])

  const exportCsv = useCallback(() => {
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
  }, [result, toast])

  const doSave = useCallback(async () => {
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
        notes: `优化区间 ${form.start} 起 · ${result.params.cov_method} · 预期夏普 ${fmtNum(result.portfolio.sharpe, 2)}`,
      })
      toast('success', `已保存为策略「${r.name}」（#${r.id}），可在策略实验室直接回测`)
      setSaveOpen(false)
      setSaveName('')
    } catch (e: any) {
      toast('error', e?.message || '保存失败')
    } finally {
      setSaving(false)
    }
  }, [result, saveName, form.start, toast])

  return (
    <div className="grid gap-4 xl:grid-cols-3">
      <OptimizeConfigPanel
        meta={meta}
        form={form}
        set={set}
        beginner={beginner}
        onBeginner={setBeginner}
        onApplyRecommended={onApplyRecommended}
        onResetDefaults={onResetDefaults}
        onRun={run}
        running={running}
      />

      <div className="space-y-4 xl:col-span-2">
        {!result ? (
          <Card>
            <Empty
              icon={<Target className="h-8 w-8" />}
              title="还没算过权重"
              desc="左边按 ①②③④ 填完，点「开始优化」。第一次用的话，直接点「一键填入推荐配置」再点运行就行。"
            />
            <div className="mx-auto max-w-xl space-y-2 px-2 pb-2 text-xs leading-6 text-slate-500">
              <div className="flex items-center gap-1.5 font-medium text-slate-600">
                <FlaskConical className="h-3.5 w-3.5" />
                第一次用？照这个顺序来
              </div>
              <ol className="space-y-1.5">
                <li>① 标的池选「股债商均衡」—— 股票、债券、黄金都有，最容易看出「分散」在做什么。</li>
                <li>② 优化目标先用「最大夏普」，它在收益和波动之间取平衡。</li>
                <li>③ 历史区间选「近 5 年」，样本太短估出来的权重只是在拟合噪声。</li>
                <li>④ 跑完之后，先看最上面那句结论 —— 它比的是「每个都买一样多」这个及格线。</li>
              </ol>
              <p className="pt-1 text-slate-400">
                记住一件事：优化器只决定「每个买多少」，它不会替你判断这些标的值不值得买。
              </p>
            </div>
          </Card>
        ) : (
          <OptimizeResultPanel
            result={result}
            meta={meta}
            objectiveLabel={objectiveLabel}
            onExportCsv={exportCsv}
            onOpenSave={() => setSaveOpen(true)}
          />
        )}
      </div>

      <SaveStrategyModal
        open={saveOpen}
        onClose={() => setSaveOpen(false)}
        onSave={doSave}
        saving={saving}
        name={saveName}
        setName={setSaveName}
        result={result}
      />
    </div>
  )
}
