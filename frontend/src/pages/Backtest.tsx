/**
 * 回测中心（编排层）
 * ==================
 * 2026-09-29 重构：页面从 1641 行降到 ~500 行，UI 拆到 `components/backtest/`：
 *   ConfigPanel / ResultPanel / HistoryPanel / OptimizeModal / CompareModal /
 *   FactorModal / WatchPicker，术语解释在 glossary.ts + TermTip.tsx。
 *
 * 本文件只负责三件事，**不再直接写大段 JSX**：
 *   ① 配置状态（含 prefill / localStorage / 参数记忆三条写入路径的唯一真相）；
 *   ② 与后端交互（跑回测、导出、历史记录、载入历史配置）；
 *   ③ 把各部分拼起来。
 *
 * ⚠️ 状态必须集中在这里。配置有 prefill（榜单跳转）、localStorage（刷新保留）、
 *    per-strategy 参数记忆三条来源，拆到子组件里必然出现「两个真相」——
 *    历史上已经踩过一次「换策略时参数记忆覆盖掉刚载入的配置」。
 *
 * ⚠️ `symbols` 恒为**逗号分隔字符串**。外部来源（prefill / localStorage / 后端 JSON 列）
 *    可能是数组，一律先过 `symbolsToInput` / `symbolsToList` 再使用 ——
 *    直接 `.join()` 会 TypeError 整页白屏（render-check 有源码级守卫）。
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { BarChart3 } from 'lucide-react'
import { useLocation } from 'react-router-dom'
import CompareModal from '../components/backtest/CompareModal'
import ConfigPanel, { type ConfigForm, type MetaResp } from '../components/backtest/ConfigPanel'
import FactorModal from '../components/backtest/FactorModal'
import HistoryPanel from '../components/backtest/HistoryPanel'
import OptimizeModal from '../components/backtest/OptimizeModal'
import ResultPanel from '../components/backtest/ResultPanel'
import WatchPicker from '../components/backtest/WatchPicker'
import { RECOMMENDED, yearsAgo } from '../components/backtest/presets'
import { Alert, Card, Loading, useToast } from '../components/ui'
import { api, getToken, LONG_TIMEOUT } from '../lib/api'
import {
  loadBacktestPrefs,
  loadParamMemory,
  saveBacktestPrefs,
  saveParamMemory,
  symbolsToInput,
} from '../lib/backtestPrefs'
import type { BacktestResult, DataSourceInfo, StrategyConfig, StrategyInfo } from '../lib/types'

export default function Backtest() {
  const loc = useLocation()
  const toast = useToast()
  const prefill = (loc.state || {}) as any
  // 持久化偏好只在挂载时读一次；此后每次变更防抖写回
  const [saved] = useState(() => loadBacktestPrefs())

  const [meta, setMeta] = useState<MetaResp | null>(null)
  const [builtin, setBuiltin] = useState<StrategyInfo[]>([])
  const [customs, setCustoms] = useState<StrategyConfig[]>([])

  // 初始化优先级：外部 prefill（榜单跳转）> localStorage > 默认值
  const [strategyKey, setStrategyKey] = useState(prefill.strategy_key || saved.strategyKey || RECOMMENDED.strategyKey)
  const [customId, setCustomId] = useState<number | ''>(saved.customId ?? '')
  const [symbols, setSymbols] = useState<string>(
    symbolsToInput(prefill.symbols) ?? symbolsToInput(saved.symbols) ?? RECOMMENDED.symbols,
  )
  const [start, setStart] = useState(saved.start || yearsAgo(RECOMMENDED.years))
  const [end, setEnd] = useState(saved.end || '')
  const [interval, setInterval_] = useState(saved.interval || RECOMMENDED.interval)
  const [capital, setCapital] = useState(saved.capital ?? RECOMMENDED.capital)
  const [commission, setCommission] = useState(saved.commission ?? RECOMMENDED.commission)
  const [slippage, setSlippage] = useState(saved.slippage ?? RECOMMENDED.slippage)
  const [benchmark, setBenchmark] = useState(saved.benchmark || RECOMMENDED.benchmark)
  const [stopType, setStopType] = useState(saved.stopType || RECOMMENDED.stopType)
  const [stopValue, setStopValue] = useState(saved.stopValue ?? 3)
  const [takeProfitR, setTakeProfitR] = useState(saved.takeProfitR ?? 0)
  const [timeStop, setTimeStop] = useState(saved.timeStop ?? 0)
  const [sizing, setSizing] = useState(saved.sizing || RECOMMENDED.sizing)
  const [riskPct, setRiskPct] = useState(saved.riskPct ?? 1)
  const [dataSource, setDataSource] = useState(saved.dataSource || RECOMMENDED.dataSource)
  const [dsInfo, setDsInfo] = useState<DataSourceInfo | null>(null)
  const [params, setParams] = useState<Record<string, any>>(prefill.params || saved.params || {})
  const [rule, setRule] = useState<any>(prefill.rule || saved.rule || null)
  const [code, setCode] = useState<string>(prefill.code || saved.code || '')

  // 新手模式默认开：小白第一次进来看到的是 4 步向导，而不是 13 个控件
  const [beginner, setBeginner] = useState(saved.beginner ?? true)

  const [running, setRunning] = useState(false)
  const [result, setResult] = useState<BacktestResult | null>(null)

  const [optOpen, setOptOpen] = useState(false)
  const [cmpOpen, setCmpOpen] = useState(false)
  const [factorOpen, setFactorOpen] = useState(false)
  const [watchOpen, setWatchOpen] = useState(false)

  const [history, setHistory] = useState<any[]>([])

  useEffect(() => {
    Promise.all([
      api.get<MetaResp>('/backtest/meta'),
      api.get<{ builtin: StrategyInfo[] }>('/strategies'),
      api.get<{ items: StrategyConfig[] }>('/strategies/custom'),
      api.get<DataSourceInfo>('/market/data-source'),
    ])
      .then(([m, b, c, d]) => {
        setMeta(m)
        setBuiltin(b.builtin)
        setCustoms(c.items)
        setDsInfo(d)
      })
      .catch(() => toast('error', '加载回测元信息失败'))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const loadHistory = useCallback(() => {
    api
      .get<{ items: any[] }>('/backtest/history?limit=30')
      .then((r) => setHistory(r.items))
      .catch(() => {})
  }, [])
  useEffect(() => {
    loadHistory()
  }, [loadHistory])

  const currentStrategy = useMemo(
    () => (strategyKey === '' ? null : builtin.find((s) => s.key === strategyKey) || null),
    [builtin, strategyKey],
  )

  // 配置变更 → 防抖写回 localStorage（跨页面 / 刷新保留用户选择）
  useEffect(() => {
    saveBacktestPrefs({
      strategyKey, customId, symbols, start, end, interval, capital, commission,
      slippage, benchmark, stopType, stopValue, takeProfitR, timeStop, sizing,
      riskPct, dataSource, params, rule, code, beginner,
    })
  }, [
    strategyKey, customId, symbols, start, end, interval, capital, commission,
    slippage, benchmark, stopType, stopValue, takeProfitR, timeStop, sizing,
    riskPct, dataSource, params, rule, code, beginner,
  ])

  // 参数变更 → per-strategy 记忆（仅内置策略；自定义策略参数由其配置保存）
  useEffect(() => {
    if (customId === '' && currentStrategy && Object.keys(params).length) {
      saveParamMemory(strategyKey, params)
    }
  }, [params, strategyKey, customId, currentStrategy])

  // 切换策略时：优先恢复该策略的参数记忆，无记忆才落默认值。
  // overrideParamsRef：外部「一次性注入」参数（如历史记录载入配置）——
  // 切 strategyKey 会触发本 effect，若不拦截，参数记忆会覆盖刚载入的配置。
  const firstRunRef = useRef(true)
  const overrideParamsRef = useRef<Record<string, any> | null>(null)
  useEffect(() => {
    const isFirst = firstRunRef.current
    firstRunRef.current = false
    if (customId !== '') return // 自定义策略的参数来自其配置
    if (!currentStrategy) return
    if (overrideParamsRef.current) {
      setParams(overrideParamsRef.current)
      overrideParamsRef.current = null
      return
    }
    if (isFirst && prefill.params) return // 首次挂载且外部带参数：尊重 prefill
    const memo = loadParamMemory(strategyKey)
    if (memo) {
      setParams(memo)
    } else {
      setParams(Object.fromEntries(currentStrategy.params.map((p) => [p.key, p.default])))
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [strategyKey, customId])

  /* ---------------- 策略切换 ---------------- */
  const handleStrategyChange = (v: string) => {
    if (v.startsWith('custom:')) {
      const id = parseInt(v.split(':')[1], 10)
      setCustomId(id)
      const c = customs.find((x) => x.id === id)
      if (c) {
        setStrategyKey(c.strategy_key)
        setParams(c.params || {})
        setRule(c.rule || null)
        setCode(c.code || '')
        const cs = symbolsToInput(c.symbols)
        if (cs) setSymbols(cs)
      }
    } else {
      setCustomId('')
      setStrategyKey(v)
      setRule(null)
      setCode('')
    }
  }

  /* ---------------- 一键推荐配置 ---------------- */
  const applyRecommended = () => {
    setCustomId('')
    setRule(null)
    setCode('')
    if (strategyKey !== RECOMMENDED.strategyKey) setStrategyKey(RECOMMENDED.strategyKey)
    setSymbols(RECOMMENDED.symbols)
    setStart(yearsAgo(RECOMMENDED.years))
    setEnd('')
    setCapital(RECOMMENDED.capital)
    setBenchmark(RECOMMENDED.benchmark)
    setInterval_(RECOMMENDED.interval)
    setCommission(RECOMMENDED.commission)
    setSlippage(RECOMMENDED.slippage)
    setDataSource(RECOMMENDED.dataSource)
    setStopType(RECOMMENDED.stopType)
    setSizing(RECOMMENDED.sizing)
    toast('success', '已填入推荐配置：双均线趋势跟踪 · SPY · 近 5 年。直接点「开始回测」即可。')
  }

  /** 寻优完成后把最优参数写回主面板（参数记忆 effect 会自动持久化）。 */
  const applyBestParams = (best: Record<string, any>) => {
    if (!best || !Object.keys(best).length) return
    setParams((s) => ({ ...s, ...best }))
    toast('success', `最优参数已写入主面板：${Object.entries(best).map(([k, v]) => `${k}=${v}`).join('，')}`)
  }

  /**
   * 历史记录 → 把这套配置填回表单（标的 / 区间 / 资金 / 止损 / 仓位 / 参数）。
   * detail 接口不返回 rule/code，custom_* 策略只能回填能回填的部分。
   */
  const applyRunConfig = async (rid: number) => {
    try {
      const d = await api.get<any>(`/backtest/${rid}`)
      const sym = symbolsToInput(d.symbols)
      if (sym) setSymbols(sym)
      if (d.start) setStart(String(d.start).slice(0, 10))
      if (d.end) setEnd(String(d.end).slice(0, 10))
      if (d.initial_capital) setCapital(Number(d.initial_capital))
      if (d.benchmark) setBenchmark(String(d.benchmark).toUpperCase())
      if (d.commission_bps != null) setCommission(Number(d.commission_bps))
      if (d.slippage_bps != null) setSlippage(Number(d.slippage_bps))
      if (d.interval) setInterval_(String(d.interval))
      if (d.data_source) setDataSource(String(d.data_source))
      const rk = d.risk || {}
      if (rk.stop_type) setStopType(String(rk.stop_type))
      if (rk.stop_value != null) setStopValue(Number(rk.stop_value))
      if (rk.take_profit_r != null) setTakeProfitR(Number(rk.take_profit_r))
      if (rk.time_stop_bars != null) setTimeStop(Number(rk.time_stop_bars))
      if (rk.sizing_method) setSizing(String(rk.sizing_method))
      if (rk.risk_per_trade_pct != null) setRiskPct(Number(rk.risk_per_trade_pct))
      if (d.strategy_key && !String(d.strategy_key).startsWith('custom_')) {
        const inject = d.params && Object.keys(d.params).length ? { ...d.params } : null
        if (String(d.strategy_key) !== strategyKey) {
          // 切策略会触发参数记忆 effect —— 用 override 拦截，保证载入的参数生效
          if (inject) overrideParamsRef.current = inject
          setCustomId('')
          setStrategyKey(String(d.strategy_key))
        } else if (inject) {
          setParams(inject)
        }
      } else if (d.params && Object.keys(d.params).length) {
        setParams(d.params)
      }
      toast('success', `已载入「${d.label || `回测 #${rid}`}」的配置（标的 / 区间 / 止损 / 参数）`)
    } catch (e: any) {
      toast('error', e?.message || '载入配置失败')
    }
  }

  /* ---------------- 跑回测 ---------------- */
  const run = async () => {
    setRunning(true)
    setResult(null)
    try {
      const body: any = {
        strategy_key: strategyKey,
        params,
        symbols: symbols.split(',').map((s) => s.trim().toUpperCase()).filter(Boolean),
        start,
        end: end || null,
        interval,
        initial_capital: capital,
        commission_bps: commission,
        slippage_bps: slippage,
        benchmark,
        risk: {
          stop_type: stopType,
          stop_value: stopValue,
          take_profit_r: takeProfitR,
          time_stop_bars: timeStop,
          sizing_method: sizing,
          risk_per_trade_pct: riskPct,
        },
        label: '',
        data_source: dataSource,
      }
      if (strategyKey === 'custom_rule') body.rule = rule
      if (strategyKey === 'custom_code') body.code = code

      const r = await api.post<BacktestResult>('/backtest/run', body, LONG_TIMEOUT)
      setResult(r)
      if (r.data_warning) toast('warning', r.data_warning)
      else toast('success', `回测完成：${r.bars} 根 K 线，${r.trade_count} 笔交易（数据源 ${r.data_source_used}）`)
      loadHistory()
    } catch (e: any) {
      toast('error', e?.message || '回测失败')
    } finally {
      setRunning(false)
    }
  }

  const download = async (kind: 'trades' | 'equity' | 'monthly') => {
    if (!result?.run_id) {
      toast('warning', '请先运行一次回测（结果会自动保存后再导出）')
      return
    }
    try {
      const res = await fetch(`/api/backtest/${result.run_id}/export?kind=${kind}`, {
        headers: { Authorization: `Bearer ${getToken()}` },
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const blob = await res.blob()
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `quantdesk_${result.strategy_name}_${kind}.csv`
      document.body.appendChild(a)
      a.click()
      a.remove()
      URL.revokeObjectURL(url)
      toast('success', `${kind} 已导出为 CSV`)
    } catch (e: any) {
      toast('error', `导出失败：${e?.message || e}`)
    }
  }

  const form: ConfigForm = {
    strategyKey, customId, symbols, start, end, interval, capital, commission,
    slippage, benchmark, stopType, stopValue, takeProfitR, timeStop, sizing,
    riskPct, dataSource, params,
  }

  return (
    <div className="space-y-5">
      <div className="grid gap-5 xl:grid-cols-4">
        <ConfigPanel
          meta={meta}
          builtin={builtin}
          customs={customs}
          dsInfo={dsInfo}
          currentStrategy={currentStrategy}
          form={form}
          set={{
            setSymbols, setStart, setEnd, setInterval: setInterval_, setCapital, setCommission,
            setSlippage, setBenchmark, setStopType, setStopValue, setTakeProfitR, setTimeStop,
            setSizing, setRiskPct, setDataSource, setParams,
          }}
          beginner={beginner}
          onBeginner={setBeginner}
          onStrategyChange={handleStrategyChange}
          onApplyRecommended={applyRecommended}
          onRun={run}
          running={running}
          onOpenWatch={() => setWatchOpen(true)}
          onOpenOptimize={() => setOptOpen(true)}
          onOpenCompare={() => setCmpOpen(true)}
          onOpenFactor={() => setFactorOpen(true)}
        />

        {/* 结果区 */}
        <div className="space-y-5 xl:col-span-3">
          {running && (
            <Card>
              <Loading label="正在拉取行情并逐根 K 线撮合，标的越多耗时越长…" />
            </Card>
          )}

          {!running && !result && (
            <Card title="第一次用？照这个顺序来">
              <ol className="space-y-2.5 text-sm leading-6 text-slate-600">
                <li className="flex gap-2">
                  <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-slate-100 text-[11px] font-semibold text-slate-600">
                    1
                  </span>
                  <span>
                    左边第 ① 步选一个策略。不知道怎么选就点「一键填入推荐配置」，它会填好一套能直接跑的设置。
                  </span>
                </li>
                <li className="flex gap-2">
                  <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-slate-100 text-[11px] font-semibold text-slate-600">
                    2
                  </span>
                  <span>
                    第 ② 步填股票代码（也就是「标的」）。新手直接用 SPY —— 它是标普500指数基金，由 500 家公司组成，
                    比押注单只个股稳得多。
                  </span>
                </li>
                <li className="flex gap-2">
                  <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-slate-100 text-[11px] font-semibold text-slate-600">
                    3
                  </span>
                  <span>第 ③ 步选回测多长时间，建议至少 3 年，最好能覆盖一轮完整的涨和跌。</span>
                </li>
                <li className="flex gap-2">
                  <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-slate-100 text-[11px] font-semibold text-slate-600">
                    4
                  </span>
                  <span>
                    点「开始回测」。跑完后右侧会出现一句话结论，直接告诉你好不好、以及要注意什么。
                  </span>
                </li>
              </ol>
              <div className="mt-4">
                <Alert tone="info" title="回测到底在干什么">
                  把一套买卖规则放到历史行情里跑一遍，看它过去能不能赚钱。它是一台「体检仪」，不是「预测机」——
                  历史表现好，不等于未来也能赚钱。所有指标名都可以把鼠标放上去看解释。
                </Alert>
              </div>
              <div className="mt-4 flex items-center gap-2 text-xs text-slate-400">
                <BarChart3 className="h-4 w-4" />
                跑完的结果会自动存进下方的「历史回测记录」，随时可以回头对比。
              </div>
            </Card>
          )}

          {result && !running && (
            <ResultPanel
              result={result}
              capital={capital}
              benchmark={benchmark}
              commission={commission}
              slippage={slippage}
              params={params}
              onDownload={download}
            />
          )}

          <HistoryPanel
            history={history}
            onRefresh={loadHistory}
            onLoadConfig={applyRunConfig}
            onOpenResult={(r) => setResult(r)}
          />
        </div>
      </div>

      <OptimizeModal
        open={optOpen}
        onClose={() => setOptOpen(false)}
        meta={meta}
        currentStrategy={currentStrategy}
        strategyKey={strategyKey}
        symbols={symbols}
        start={start}
        end={end}
        interval={interval}
        capital={capital}
        onApplyBestParams={applyBestParams}
      />

      <CompareModal
        open={cmpOpen}
        onClose={() => setCmpOpen(false)}
        builtin={builtin}
        customs={customs}
        symbols={symbols}
        start={start}
        end={end}
        interval={interval}
        capital={capital}
        commission={commission}
        slippage={slippage}
        benchmark={benchmark}
        dataSource={dataSource}
        risk={{ stopType, stopValue, takeProfitR, timeStop, sizing, riskPct }}
      />

      <FactorModal
        open={factorOpen}
        onClose={() => setFactorOpen(false)}
        strategyKey={strategyKey}
        params={params}
        symbols={symbols}
        start={start}
        end={end}
        interval={interval}
      />

      <WatchPicker
        open={watchOpen}
        symbols={symbols}
        onClose={() => setWatchOpen(false)}
        onConfirm={(merged) => {
          setSymbols(merged)
          setWatchOpen(false)
        }}
      />
    </div>
  )
}
