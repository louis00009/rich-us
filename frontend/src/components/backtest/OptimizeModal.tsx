/**
 * OptimizeModal —— 参数寻优（网格搜索）
 * ======================================
 * 从 pages/Backtest.tsx 抽出（铁律 9）。把「候选值输入 / 组合数预算 / 后台任务
 * 轮询 / 进度 / 取消 / 结果表 / 一键回写最优参数」整块收进来，
 * 父级只负责 `open` 与「把最优参数写回主面板」这一件事。
 *
 * ⚠️ 轮询定时器必须在卸载时清理（旧实现漏过一次：寻优进行中切走页面会在已卸载
 *    组件上持续 setState）。
 * ⚠️ 候选值网格以**参数 key** 为键，换策略后旧 key 已失效 —— 除了换策略时清空，
 *    提交前还要按当前策略的参数表过滤一次，防止把上一个策略的 key 发给后端。
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Check, Sparkles } from 'lucide-react'
import { api, LONG_TIMEOUT } from '../../lib/api'
import { fmtNum, fmtRatioPct, signClass } from '../../lib/format'
import type { StrategyInfo } from '../../lib/types'
import { Alert, Badge, Button, DataTable, Field, Input, Loading, Modal, Progress, Select, useToast } from '../ui'
import { TermTip } from '../terms/TermTip'

interface MetaLike {
  objectives: { key: string; label: string }[]
}

/** 由 ParamSpec 生成候选值建议：默认值、±1 步长、区间端点（去重升序）。 */
function suggestCandidates(p: { default: any; min?: number; max?: number; step?: number }): number[] {
  const d = Number(p.default)
  const mn = p.min ?? Math.max(0, d / 2)
  const mx = p.max ?? d * 2
  const st = p.step ?? 1
  const set = new Set<number>([d, mn, mx])
  for (const v of [d - st, d + st]) {
    if (v >= mn && v <= mx) set.add(Number(v.toFixed(4)))
  }
  return [...set].filter((v) => Number.isFinite(v)).sort((a, b) => a - b)
}

export default function OptimizeModal({
  open,
  onClose,
  meta,
  currentStrategy,
  strategyKey,
  symbols,
  start,
  end,
  interval,
  capital,
  onApplyBestParams,
}: {
  open: boolean
  onClose: () => void
  meta: MetaLike | null
  currentStrategy: StrategyInfo | null
  strategyKey: string
  symbols: string
  start: string
  end: string
  interval: string
  capital: number
  onApplyBestParams: (params: Record<string, any>) => void
}) {
  const toast = useToast()
  const [grid, setGrid] = useState<Record<string, string>>({})
  const [objective, setObjective] = useState('sharpe')
  const [result, setResult] = useState<any>(null)
  const [running, setRunning] = useState(false)
  const [jobId, setJobId] = useState<string | null>(null)
  const [progress, setProgress] = useState<{ done: number; total: number } | null>(null)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const jobIdRef = useRef<string | null>(null)

  // 换策略后旧参数的 key 已失效，清空候选值输入
  useEffect(() => {
    setGrid({})
    setResult(null)
  }, [strategyKey, currentStrategy?.key])

  const stopPoll = useCallback(() => {
    if (pollRef.current) clearInterval(pollRef.current)
    pollRef.current = null
  }, [])

  // 卸载 / 关闭弹窗时清掉轮询定时器
  useEffect(
    () => () => {
      stopPoll()
    },
    [stopPoll],
  )

  const poll = useCallback(
    (id: string) => {
      stopPoll()
      pollRef.current = setInterval(async () => {
        try {
          const j = await api.get<any>(`/backtest/job/${id}`)
          if (j.status === 'running') {
            setProgress({ done: j.progress, total: j.total })
            return
          }
          stopPoll()
          setProgress(null)
          setRunning(false)
          setJobId(null)
          jobIdRef.current = null
          if (j.status === 'done' && j.result?.ok) {
            setResult(j.result)
            toast('success', `寻优完成，评估 ${j.result.evaluated} 组参数`)
          } else if (j.status === 'cancelled') {
            if (j.result?.ok) setResult(j.result)
            toast('warning', `寻优已取消（已评估 ${j.result?.evaluated ?? 0} 组，结果保留）`)
          } else {
            toast('error', j.error || '寻优失败')
          }
        } catch {
          // 404（后端重启后任务丢失）等：停止轮询，不弹错
          stopPoll()
          setProgress(null)
          setRunning(false)
          setJobId(null)
        }
      }, 1200)
    },
    [stopPoll, toast],
  )

  const comboCount = useMemo(() => {
    let n = 1
    for (const v of Object.values(grid)) {
      const c = v.split(',').map((x) => parseFloat(x.trim())).filter((x) => !Number.isNaN(x)).length
      if (c > 0) n *= c
    }
    return n
  }, [grid])

  const fillEvenPoints = (key: string, mn: number, mx: number, n: number) => {
    const vals: string[] = []
    for (let i = 0; i < n; i++) {
      vals.push(String(Number((mn + ((mx - mn) * i) / (n - 1)).toFixed(4))))
    }
    setGrid((s) => ({ ...s, [key]: vals.join(', ') }))
  }

  const run = async () => {
    // 只保留当前策略真实存在的参数 key，避免把上一个策略的键发给后端
    const validKeys = new Set((currentStrategy?.params || []).map((p) => p.key))
    const g: Record<string, number[]> = {}
    Object.entries(grid).forEach(([k, v]) => {
      if (validKeys.size && !validKeys.has(k)) return
      const arr = v.split(',').map((x) => parseFloat(x.trim())).filter((x) => !Number.isNaN(x))
      if (arr.length) g[k] = arr
    })
    if (!Object.keys(g).length) {
      toast('warning', '请至少为一个参数填写候选值（点下面的建议值即可）')
      return
    }
    setRunning(true)
    setResult(null)
    setProgress(null)
    try {
      const r = await api.post<any>(
        '/backtest/optimize-async',
        {
          strategy_key: strategyKey,
          param_grid: g,
          symbols: symbols
            .split(',')
            .map((s) => s.trim().toUpperCase())
            .filter(Boolean)
            .slice(0, 5),
          start,
          end: end || null,
          interval: interval === '1wk' ? '1wk' : '1d',
          initial_capital: capital,
          objective,
          max_combos: 120,
        },
        LONG_TIMEOUT,
      )
      jobIdRef.current = r.job_id
      setJobId(r.job_id)
      poll(r.job_id)
    } catch (e: any) {
      toast('error', e?.message || '寻优启动失败')
      setRunning(false)
    }
  }

  const cancel = async () => {
    const id = jobIdRef.current
    if (!id) return
    try {
      await api.post(`/backtest/job/${id}/cancel`)
      toast('info', '已请求取消，当前组合评估完成后停止')
    } catch (e: any) {
      toast('error', e?.message || '取消失败')
    }
  }

  const numericParams = (currentStrategy?.params || []).filter((p) => p.type === 'int' || p.type === 'float').slice(0, 8)

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="参数寻优 · 网格搜索"
      width="max-w-3xl"
      footer={
        <>
          <Button onClick={onClose}>关闭</Button>
          <Button variant="primary" loading={running} onClick={run} icon={<Sparkles className="h-3.5 w-3.5" />}>
            开始寻优
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <Alert tone="warn" title="先看这条：寻优最容易骗自己">
          网格搜索会挑出「历史最优」的参数，但它在未来往往失效。建议：<br />
          1）优先看「参数平原」（相邻取值表现接近）而不是单点最优；<br />
          2）选出结果后换一个时间区间复验；3）同时调的参数不超过 2~3 个。
          <span className="ml-1 inline-flex align-middle">
            <TermTip id="grid_search" dotted={false}>
              为什么
            </TermTip>
          </span>
        </Alert>

        <Field label="优化目标" hint="用哪个指标来判断「哪组参数最好」">
          <Select value={objective} onChange={(e) => setObjective(e.target.value)}>
            {meta?.objectives.map((o) => (
              <option key={o.key} value={o.key}>
                {o.label}
              </option>
            ))}
          </Select>
        </Field>

        <div>
          <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-400">
            参数候选值（点下面的建议值追加，或自己用逗号分隔手输）
          </div>
          {numericParams.length === 0 && (
            <p className="text-xs text-slate-400">当前策略没有可调的数字参数，无法寻优。</p>
          )}
          <div className="grid gap-3 sm:grid-cols-2">
            {numericParams.map((p) => {
              const cands = suggestCandidates(p)
              return (
                <Field
                  key={p.key}
                  label={`${p.label}（${p.key}）`}
                  hint={`范围 ${p.min ?? '-∞'} ~ ${p.max ?? '∞'} · 默认 ${p.default}`}
                >
                  <Input
                    value={grid[p.key] ?? ''}
                    onChange={(e) => setGrid((s) => ({ ...s, [p.key]: e.target.value }))}
                    placeholder={`如 ${cands.slice(0, 3).join(', ')}`}
                  />
                  <div className="mt-1.5 flex flex-wrap items-center gap-1">
                    {cands.map((c) => (
                      <button
                        key={c}
                        type="button"
                        className="rounded border border-slate-200 px-1.5 py-0.5 text-[10px] text-slate-500 transition-colors hover:border-brand-300 hover:text-brand-700"
                        title="追加为候选值"
                        onClick={() => {
                          const cur = (grid[p.key] ?? '').split(',').map((x) => x.trim()).filter(Boolean)
                          if (!cur.includes(String(c))) {
                            setGrid((s) => ({ ...s, [p.key]: [...cur, String(c)].join(', ') }))
                          }
                        }}
                      >
                        {c}
                      </button>
                    ))}
                    {p.min !== undefined && p.max !== undefined && (
                      <button
                        type="button"
                        className="text-[10px] text-brand-600 hover:underline"
                        onClick={() => fillEvenPoints(p.key, Number(p.min), Number(p.max), 5)}
                      >
                        均匀取 5 点
                      </button>
                    )}
                  </div>
                </Field>
              )
            })}
          </div>
          {comboCount > 0 && (
            <p className={`mt-2 text-xs ${comboCount > 120 ? 'font-semibold text-rose-600' : 'text-slate-400'}`}>
              当前将评估 <span className="num">{comboCount}</span> 组组合
              {comboCount > 120
                ? ' —— 超过 120 组上限，超出部分不会执行，请削减候选值'
                : '；上限 120 组；标的会限制为前 5 个以控制耗时。'}
            </p>
          )}
        </div>

        {running && (
          <div className="flex items-center gap-3">
            <div className="flex-1">
              {progress && progress.total > 0 ? (
                <>
                  <Progress value={progress.done} max={progress.total} height="h-1.5" />
                  <p className="mt-1 text-xs text-slate-500">
                    进度 {progress.done} / {progress.total} 组（约{' '}
                    {Math.max(1, Math.ceil(((progress.total - progress.done) * 1.5) / 60))} 分钟）
                  </p>
                </>
              ) : (
                <Loading label="正在逐组回测…" />
              )}
            </div>
            {jobId && (
              <Button variant="danger" size="sm" onClick={cancel}>
                取消
              </Button>
            )}
          </div>
        )}

        {result && (
          <div className="space-y-3">
            <div className="flex flex-wrap gap-3">
              <Badge tone="brand">评估 {result.evaluated} 组</Badge>
              <Badge tone={result.failed ? 'amber' : 'green'}>失败 {result.failed} 组</Badge>
              <Badge tone="violet">目标：{result.objective}</Badge>
            </div>
            {result.best && (
              <>
                <Alert tone="success" title="历史最优参数组合">
                  {JSON.stringify(result.best.params)} → 夏普 {fmtNum(result.best.sharpe, 2)}，累计收益{' '}
                  {fmtRatioPct(result.best.return, 1, true)}，最大回撤 {fmtRatioPct(result.best.max_drawdown, 1)}
                </Alert>
                <div className="flex flex-wrap items-center gap-2">
                  <Button
                    size="sm"
                    variant="primary"
                    icon={<Check className="h-3.5 w-3.5" />}
                    onClick={() => onApplyBestParams(result.best.params)}
                  >
                    应用最优参数到主面板
                  </Button>
                  <span className="text-[11px] text-slate-400">
                    写入后自动记入该策略的参数记忆，强烈建议换时间区间复验一次
                  </span>
                </div>
              </>
            )}
            <DataTable<any>
              rows={result.results || []}
              rowKey={(r, i) => i}
              maxHeight="380px"
              columns={[
                { key: 'p', label: '参数', render: (r) => <span className="num text-xs">{JSON.stringify(r.params)}</span> },
                { key: 'sh', label: '夏普', align: 'right', render: (r) => <span className="num font-medium">{fmtNum(r.sharpe, 2)}</span> },
                { key: 'so', label: '索提诺', align: 'right', render: (r) => <span className="num">{fmtNum(r.sortino, 2)}</span> },
                { key: 'ca', label: '卡玛', align: 'right', render: (r) => <span className="num">{fmtNum(r.calmar, 2)}</span> },
                { key: 'r', label: '累计收益', align: 'right', render: (r) => <span className={`num ${signClass(r.return)}`}>{fmtRatioPct(r.return, 1, true)}</span> },
                { key: 'dd', label: '回撤', align: 'right', render: (r) => <span className="num text-emerald-600">{fmtRatioPct(r.max_drawdown, 1)}</span> },
                { key: 't', label: '交易', align: 'right', render: (r) => <span className="num text-slate-500">{r.trades}</span> },
              ]}
            />
          </div>
        )}
      </div>
    </Modal>
  )
}
