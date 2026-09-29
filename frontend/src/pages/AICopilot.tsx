import {
  AlertTriangle,
  Bot,
  Brain,
  Gauge,
  Layers,
  MessageSquare,
  Send,
  Sparkles,
  Target,
  TrendingUp,
} from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { CorrelationMatrix, HBar, ScoreGauge } from '../components/charts'
import {
  Alert,
  Badge,
  Button,
  Card,
  Empty,
  Field,
  Input,
  Loading,
  ScoreBar,
  Select,
  Stat,
  Tabs,
  useToast,
} from '../components/ui'
import { api } from '../lib/api'
import { fmtNum, signClass } from '../lib/format'
import type { AIResult } from '../lib/types'

const PRESETS = [
  { label: '大盘核心', symbols: ['SPY', 'QQQ', 'IWM'] },
  { label: '半导体', symbols: ['NVDA', 'AMD', 'AVGO', 'TSM', 'SMH'] },
  { label: '科技巨头', symbols: ['AAPL', 'MSFT', 'GOOGL', 'META', 'AMZN'] },
  { label: '避险组合', symbols: ['GLD', 'TLT', 'SPY', 'UUP'] },
  { label: '中国资产', symbols: ['FXI', 'KWEB', 'BABA', 'PDD'] },
  { label: '加密相关', symbols: ['IBIT', 'COIN', 'MSTR'] },
]

export default function AICopilot() {
  const toast = useToast()
  const nav = useNavigate()
  const [symbols, setSymbols] = useState('SPY,QQQ,NVDA')
  const [horizon, setHorizon] = useState<'intraday' | 'swing' | 'position'>('swing')
  const [useLLM, setUseLLM] = useState(false)
  const [llmAvailable, setLlmAvailable] = useState(false)
  const [extraModels, setExtraModels] = useState<string[]>([])
  const [selModel, setSelModel] = useState('')
  const [result, setResult] = useState<any>(null)
  const [loading, setLoading] = useState(false)
  const [activeSym, setActiveSym] = useState('')
  const [propBusy, setPropBusy] = useState('')
  const [watch, setWatch] = useState<{ symbol: string; name_cn?: string; held?: boolean }[]>([])
  useEffect(() => {
    api.get<{ items: any[] }>('/watchlist').then((r) => setWatch(r.items || [])).catch(() => {})
  }, [])
  const toggleSymbol = (sym: string) => {
    const list = symbols.split(',').map((s) => s.trim()).filter(Boolean)
    const i = list.indexOf(sym)
    if (i >= 0) list.splice(i, 1)
    else if (list.length < 12) list.push(sym)
    else return toast('warning', '最多 12 个标的')
    setSymbols(list.join(','))
  }

  // AI 研判 → 一键转为交易提案（进入 AI 接管中心审批，批准后走完整下单链）
  const toProposal = async (r: any) => {
    const action = r.bias === '多头' ? 'BUY' : r.bias === '空头' ? 'SELL' : ''
    if (!action) {
      toast('warning', `${r.symbol} 当前为震荡行情，不建议建仓，未创建提案`)
      return
    }
    setPropBusy(r.symbol)
    try {
      const res: any = await api.post('/ops/proposals', {
        symbol: r.symbol,
        action,
        size_pct: r.suggested_position_pct || 5,
        rationale: `AI Copilot 研判：${r.bias}｜综合评分 ${Number(r.composite_score).toFixed(1)}｜状态 ${r.regime}｜置信度 ${r.confidence}%`,
        entry: r.price,
        factors: r.dimensions,
      })
      toast('success', `已创建 ${action} ${r.symbol} 提案 #${res.proposal?.id ?? ''} — 前往「AI 接管」批准执行`)
    } catch (e: any) {
      toast('error', e?.message || '创建提案失败')
    } finally {
      setPropBusy('')
    }
  }

  const [chatInput, setChatInput] = useState('')
  const [chat, setChat] = useState<{ role: string; content: string }[]>([])
  const [chatLoading, setChatLoading] = useState(false)
  const chatEnd = useRef<HTMLDivElement>(null)

  useEffect(() => {
    api
      .get<{ llm_configured: boolean; extra_models?: string[] }>('/ai/status')
      .then((r) => {
        setLlmAvailable(r.llm_configured)
        setExtraModels(r.extra_models || [])
      })
      .catch(() => {})
  }, [])

  useEffect(() => {
    chatEnd.current?.scrollIntoView({ behavior: 'smooth' })
  }, [chat])

  const analyzeSeqRef = useRef(0)

  const analyze = async (syms?: string[]) => {
    const list = (syms || symbols.split(',')).map((s) => s.trim().toUpperCase()).filter(Boolean)
    if (!list.length) {
      toast('warning', '请至少输入一个标的')
      return
    }
    // P1-9：序号守卫 —— 连续点两次「分析」时，先发的慢响应不得覆盖后发的结果
    const seq = ++analyzeSeqRef.current
    setLoading(true)
    setResult(null)
    try {
      const r = await api.post<any>('/ai/analyze', {
        symbols: list, horizon, use_llm: useLLM && llmAvailable,
        use_intraday: horizon === 'intraday',
        model: selModel,
      })
      if (seq !== analyzeSeqRef.current) return
      setResult(r)
      setActiveSym(r.results[0]?.symbol || '')
      toast('success', `完成 ${r.results.length} 个标的的分析（引擎：${r.engine === 'llm' ? 'LLM + 本地' : '本地量化'}）`)
    } catch (e: any) {
      if (seq !== analyzeSeqRef.current) return
      toast('error', e?.message || '分析失败')
    } finally {
      if (seq === analyzeSeqRef.current) setLoading(false)
    }
  }

  const sendChat = async () => {
    if (!chatInput.trim()) return
    const msg = chatInput.trim()
    setChat((c) => [...c, { role: 'user', content: msg }])
    setChatInput('')
    setChatLoading(true)
    try {
      const r = await api.post<any>('/ai/chat', {
        message: msg,
        context_symbols: symbols.split(',').map((s) => s.trim().toUpperCase()).filter(Boolean).slice(0, 6),
        history: chat.slice(-6),
      })
      setChat((c) => [...c, { role: 'assistant', content: r.reply }])
    } catch (e: any) {
      setChat((c) => [...c, { role: 'assistant', content: `出错：${e?.message || '请求失败'}` }])
    } finally {
      setChatLoading(false)
    }
  }

  const active: AIResult | undefined = result?.results?.find((r: AIResult) => r.symbol === activeSym)

  return (
    <div className="space-y-5">
      <Card>
        <div className="flex flex-wrap items-end gap-3">
          <Field label="标的（逗号分隔，最多 12 个）" className="min-w-[260px] flex-1">
            <Input value={symbols} onChange={(e) => setSymbols(e.target.value.toUpperCase())} placeholder="SPY,QQQ,NVDA" />
          </Field>
          {/* 关注列表快捷选择：一键把收藏标的加入/移出研判 */}
          {watch.length > 0 && (
            <div className="flex w-full flex-wrap items-center gap-1.5">
              <span className="mr-1 flex items-center gap-1 text-[10px] font-medium uppercase tracking-wide text-slate-400">
                关注列表
              </span>
              {watch.map((w) => {
                const on = symbols.split(',').map((s) => s.trim()).includes(w.symbol)
                return (
                  <button
                    key={w.symbol}
                    onClick={() => toggleSymbol(w.symbol)}
                    title={w.name_cn || w.symbol}
                    className={`flex max-w-[170px] items-center gap-1 rounded-lg border px-2 py-1 text-xs transition-colors ${
                      on
                        ? 'border-brand-400 bg-brand-50 font-semibold text-brand-700'
                        : 'border-slate-200 text-slate-600 hover:border-brand-300 hover:bg-slate-50'
                    }`}
                  >
                    {w.held && <span className="h-1.5 w-1.5 shrink-0 rounded-full bg-emerald-500" title="当前持仓" />}
                    <span className="shrink-0 font-medium">{w.symbol}</span>
                    {w.name_cn && <span className="truncate text-[10px] text-slate-400">{w.name_cn}</span>}
                  </button>
                )
              })}
            </div>
          )}
          <Field label="投资周期">
            <Select value={horizon} onChange={(e) => setHorizon(e.target.value as any)} className="w-40">
              <option value="intraday">日内（1–3 天）</option>
              <option value="swing">波段（1–4 周）</option>
              <option value="position">中长线（3 月+）</option>
            </Select>
          </Field>
          <Field label="解读引擎">
            <Select
              value={useLLM && llmAvailable ? 'llm' : 'local'}
              onChange={(e) => setUseLLM(e.target.value === 'llm')}
              className="w-52"
            >
              <option value="local">本地量化引擎（确定性）</option>
              <option value="llm" disabled={!llmAvailable}>
                {llmAvailable ? 'LLM 深度解读' : 'LLM 深度解读（未配置）'}
              </option>
            </Select>
          </Field>
          {useLLM && llmAvailable && extraModels.length > 0 && (
            <Field label="模型（T-109 多模型）">
              <Select value={selModel} onChange={(e) => setSelModel(e.target.value)} className="w-52">
                <option value="">默认（跟随「设置 → AI 分析」的全局模型）</option>
                {extraModels.map((m) => (
                  <option key={m} value={m}>
                    {m}
                  </option>
                ))}
              </Select>
            </Field>
          )}
          <Button variant="primary" size="lg" loading={loading} onClick={() => analyze()} icon={<Brain className="h-4 w-4" />}>
            开始研判
          </Button>
        </div>

        <div className="mt-3 flex flex-wrap gap-1.5">
          <span className="mr-1 py-1 text-xs text-slate-400">快速组合：</span>
          {PRESETS.map((p) => (
            <button
              key={p.label}
              onClick={() => {
                setSymbols(p.symbols.join(','))
                analyze(p.symbols)
              }}
              className="rounded-md bg-slate-100 px-2.5 py-1 text-xs text-slate-600 transition-colors hover:bg-brand-100 hover:text-brand-700"
            >
              {p.label}
            </button>
          ))}
        </div>

        {!llmAvailable && (
          <Alert tone="info" className="mt-3">
            当前使用<span className="font-medium">内置本地量化引擎</span>：结论完全由行情数据计算得出（趋势/动量/波动率/量能多维度加权），
            结果确定、可复现、不依赖外部服务。若需自然语言深度解读，可在 <code className="rounded bg-slate-200 px-1">backend/runtime/.env</code> 中配置
            <code className="mx-1 rounded bg-slate-200 px-1">QD_AI_BASE_URL</code> 与 <code className="rounded bg-slate-200 px-1">QD_AI_API_KEY</code>。
          </Alert>
        )}
      </Card>

      {loading && (
        <Card>
          <Loading label="正在拉取行情并计算多维度评分…" />
        </Card>
      )}

      {!loading && !result && (
        <Card>
          <Empty
            icon={<Bot className="h-10 w-10" />}
            title="选择标的后点击「开始研判」"
            desc="系统会为每个标的计算状态判定（趋势/震荡/高波动）、多空综合评分、关键支撑阻力、建议仓位，并从内置策略库中推荐最适配的策略。多标的时还会给出组合相关性检查与集中度提示。"
          />
        </Card>
      )}

      {!loading && result && (
        <>
          {/* 标的导航 */}
          <div className="flex flex-wrap gap-2">
            {result.results.map((r: AIResult) => (
              <button
                key={r.symbol}
                onClick={() => setActiveSym(r.symbol)}
                className={`flex items-center gap-2 rounded-lg border px-3 py-2 transition-all ${
                  activeSym === r.symbol ? 'border-brand-400 bg-brand-50 ring-1 ring-brand-300' : 'border-slate-200 bg-white hover:bg-slate-50'
                }`}
              >
                <span className="text-sm font-semibold text-slate-800">{r.symbol}</span>
                <span className={`num text-xs font-medium ${signClass(r.composite_score)}`}>
                  {r.composite_score > 0 ? '+' : ''}
                  {r.composite_score.toFixed(0)}
                </span>
                <Badge tone={r.bias === '多头' ? 'red' : r.bias === '空头' ? 'green' : 'slate'}>{r.regime}</Badge>
              </button>
            ))}
          </div>

          {active && (
            <div className="grid gap-5 xl:grid-cols-3">
              {/* 主结论 */}
              <div className="space-y-5 xl:col-span-2">
                <Card
                  title={
                    <span className="flex items-center gap-2">
                      <Target className="h-4 w-4 text-brand-500" />
                      {active.symbol} · 量化研判
                    </span>
                  }
                  subtitle={
                    <span className="flex flex-wrap items-center gap-2">
                      <span>截至 {active.as_of} ｜ 现价 {fmtNum(active.price, 2)} ｜ 周期 {active.horizon}</span>
                      {active.realtime?.realtime ? (
                        <span
                          className="inline-flex items-center gap-1 rounded bg-emerald-50 px-1.5 py-0.5 text-[10px] font-semibold text-emerald-700"
                          title={`报价来源 ${active.realtime.quote_source || '-'} · ${active.realtime.quote_ts || ''}（指标已融合实时价）`}
                        >
                          <span className="inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-emerald-500" />
                          实时盘 · {active.realtime.quote_source}
                        </span>
                      ) : (
                        <span
                          className="rounded bg-slate-100 px-1.5 py-0.5 text-[10px] text-slate-500"
                          title={active.realtime?.note || '指标基于日线收盘价'}
                        >
                          非实时
                        </span>
                      )}
                    </span>
                  }
                  actions={
                    <span className="flex items-center gap-2">
                      <Badge tone={active.bias === '多头' ? 'red' : active.bias === '空头' ? 'green' : 'slate'}>{active.bias}</Badge>
                      <button
                        onClick={() => toProposal(active)}
                        disabled={propBusy === active.symbol}
                        className={`rounded-lg px-2.5 py-1 text-xs font-medium transition-colors ${
                          active.bias === '多头'
                            ? 'bg-rose-600 text-white hover:bg-rose-700'
                            : active.bias === '空头'
                              ? 'bg-emerald-600 text-white hover:bg-emerald-700'
                              : 'bg-slate-200 text-slate-400'
                        } disabled:opacity-60`}
                        title="转为交易提案，到「AI 接管」批准后自动下单"
                      >
                        {propBusy === active.symbol ? '提交中…' : `转为${active.bias === '空头' ? '卖出' : '买入'}提案`}
                      </button>
                    </span>
                  }
                >
                  <div className="flex flex-wrap items-start gap-6">
                    <ScoreGauge score={active.composite_score} />
                    <div className="min-w-[240px] flex-1 space-y-3">
                      <div>
                        <div className="text-xs text-slate-500">市场状态</div>
                        <div className="mt-1 flex items-center gap-2">
                          <Badge tone="blue">{active.regime}</Badge>
                          <span className="text-xs text-slate-500">{active.regime_desc}</span>
                        </div>
                      </div>
                      <div>
                        <div className="mb-1.5 text-xs text-slate-500">
                          维度评分（正=看多，负=看空；权重已按 {active.horizon} 周期调整）
                        </div>
                        <div className="space-y-2">
                          {Object.entries(active.dimensions).map(([k, v]) => (
                            <ScoreBar
                              key={k}
                              label={{ trend: '趋势', momentum: '动量', reversion: '反转', volume: '量能', risk: '风险' }[k] || k}
                              value={v}
                            />
                          ))}
                        </div>
                      </div>
                    </div>
                  </div>

                  <div className="mt-5 grid grid-cols-2 gap-3 sm:grid-cols-4">
                    <Stat label="综合评分" value={active.composite_score.toFixed(1)} tone={active.composite_score > 0 ? 'up' : 'down'} />
                    <Stat label="置信度" value={`${active.confidence}%`} />
                    <Stat label="日均波动" value={`${active.atr_pct}%`} />
                    <Stat label="建议仓位" value={`${active.suggested_position_pct}%`} />
                  </div>
                </Card>

                {/* 关键价位 */}
                <Card title="关键价位" subtitle="支撑取低于现价、阻力取高于现价的有效结构位">
                  <div className="grid gap-5 sm:grid-cols-2">
                    <div>
                      <div className="mb-2 flex items-center gap-2">
                        <span className="text-xs font-semibold uppercase tracking-wide text-emerald-600">支撑位</span>
                        <div className="h-px flex-1 bg-emerald-100" />
                      </div>
                      <div className="space-y-2">
                        {active.levels?.支撑?.length ? (
                          active.levels.支撑.map((v, i) => (
                            <div key={i} className="flex items-center justify-between rounded-lg border border-emerald-100 bg-emerald-50/50 px-3 py-2">
                              <span className="text-xs text-slate-500">S{i + 1}</span>
                              <span className="num text-sm font-semibold text-emerald-700">{fmtNum(v, 2)}</span>
                              <span className="num text-xs text-slate-500">
                                {/* P3：旧实现直接除以 active.price —— 价格为 0 时输出
                                    "Infinity%" / "NaN%"。这里显式兜底。 */}
                                {active.price
                                  ? `${(((v - active.price) / active.price) * 100).toFixed(2)}%`
                                  : '—'}
                              </span>
                            </div>
                          ))
                        ) : (
                          <p className="text-xs text-slate-400">现价下方未识别到有效支撑</p>
                        )}
                      </div>
                    </div>
                    <div>
                      <div className="mb-2 flex items-center gap-2">
                        <span className="text-xs font-semibold uppercase tracking-wide text-rose-600">阻力位</span>
                        <div className="h-px flex-1 bg-rose-100" />
                      </div>
                      <div className="space-y-2">
                        {active.levels?.阻力?.length ? (
                          active.levels.阻力.map((v, i) => (
                            <div key={i} className="flex items-center justify-between rounded-lg border border-rose-100 bg-rose-50/50 px-3 py-2">
                              <span className="text-xs text-slate-500">R{i + 1}</span>
                              <span className="num text-sm font-semibold text-rose-700">{fmtNum(v, 2)}</span>
                              <span className="num text-xs text-slate-500">
                                {/* P3：同支撑位 —— 价格为 0 时不得输出 Infinity/NaN */}
                                {active.price
                                  ? `${(((v - active.price) / active.price) * 100).toFixed(2)}%`
                                  : '—'}
                              </span>
                            </div>
                          ))
                        ) : (
                          <p className="text-xs text-slate-400">现价上方未识别到有效阻力</p>
                        )}
                      </div>
                    </div>
                  </div>
                </Card>

                {/* 策略匹配 */}
                <Card title="适配策略推荐" subtitle="依据当前市场状态从内置 28 个策略中筛选">
                  <div className="space-y-2.5">
                    {active.strategy_matches?.map((m) => (
                      <div key={m.key} className="flex items-start justify-between gap-3 rounded-lg border border-slate-200 p-3">
                        <div className="min-w-0">
                          <div className="flex items-center gap-2">
                            <span className="text-sm font-medium text-slate-800">{m.name}</span>
                            <code className="rounded bg-slate-100 px-1.5 py-0.5 text-[10px] text-slate-500">{m.key}</code>
                          </div>
                          <p className="mt-1 text-xs text-slate-500">{m.reason}</p>
                        </div>
                        <Button
                          size="sm"
                          variant="primary"
                          icon={<TrendingUp className="h-3.5 w-3.5" />}
                          onClick={() =>
                            nav('/backtest', {
                              state: { strategy_key: m.key, symbols: [active.symbol], name: m.name },
                            })
                          }
                        >
                          回测
                        </Button>
                      </div>
                    ))}
                  </div>
                </Card>

                {/* 指标读数 */}
                <Card title="指标读数与解读">
                  <div className="space-y-2">
                    {active.readings?.map((r, i) => (
                      <div key={i} className="flex items-start justify-between gap-4 border-b border-dashed border-slate-100 pb-2">
                        <div className="min-w-0 flex-1">
                          <div className="flex items-center gap-2">
                            <span className="text-xs font-medium text-slate-600">{r.name}</span>
                            <span
                              className={`num text-xs ${
                                r.signal === 'bull' ? 'text-rose-600' : r.signal === 'bear' ? 'text-emerald-600' : 'text-slate-400'
                              }`}
                            >
                              {typeof r.value === 'number' ? r.value.toFixed(3) : r.value}
                            </span>
                          </div>
                          <p className="mt-0.5 text-[11px] text-slate-400">{r.reading}</p>
                        </div>
                      </div>
                    ))}
                  </div>
                </Card>
              </div>

              {/* 右栏 */}
              <div className="space-y-5">
                <Card title="风险提示" subtitle="系统自动识别的异常信号">
                  <div className="space-y-2">
                    {active.warnings?.map((w, i) => (
                      <div key={i} className="flex items-start gap-2 rounded-lg border border-amber-100 bg-amber-50/60 p-2.5">
                        <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-amber-500" />
                        <p className="text-xs text-amber-900">{w}</p>
                      </div>
                    ))}
                  </div>
                </Card>

                {active.llm_report && (
                  <Card title={<span className="flex items-center gap-2"><Sparkles className="h-4 w-4 text-violet-500" />LLM 深度解读</span>}>
                    <div className="whitespace-pre-wrap text-xs leading-relaxed text-slate-700">{active.llm_report}</div>
                  </Card>
                )}
                {active.llm_error && <Alert tone="warn" title="LLM 调用失败">{active.llm_error}</Alert>}

                {result.portfolio && (
                  <>
                    <Card title="组合视角" subtitle="多标的横向对比">
                      <div className="space-y-3">
                        <div className="grid grid-cols-2 gap-3">
                          <Stat label="最强" value={result.portfolio.strongest} tone="up" />
                          <Stat label="最弱" value={result.portfolio.weakest} tone="down" />
                        </div>
                        <HBar
                          data={(result.portfolio.ranking || []).map((r: any) => ({ name: r.symbol, value: r.score }))}
                          height={Math.max(120, (result.portfolio.ranking?.length || 0) * 32)}
                          color="#6366f1"
                        />
                        <div className="space-y-2 border-t border-slate-100 pt-3">
                          <div className="flex items-center justify-between text-xs">
                            <span className="text-slate-500">组合平均波动率</span>
                            <span className="num font-medium">{(result.portfolio.avg_volatility * 100).toFixed(2)}%</span>
                          </div>
                          <div className="flex items-center justify-between text-xs">
                            <span className="text-slate-500">建议总敞口</span>
                            <span className="num font-medium">{result.portfolio.suggested_gross_pct}%</span>
                          </div>
                        </div>
                        <Alert tone="info">{result.portfolio.concentration_note}</Alert>
                      </div>
                    </Card>

                    {result.portfolio.correlation && (
                      <Card title="相关性矩阵" subtitle="用于检查组合分散度">
                        <CorrelationMatrix corr={result.portfolio.correlation} />
                        <div className="mt-3 flex items-center gap-3 text-[11px] text-slate-400">
                          <span className="flex items-center gap-1">
                            <span className="h-3 w-3 rounded" style={{ background: 'rgba(99,102,241,0.5)' }} />正相关
                          </span>
                          <span className="flex items-center gap-1">
                            <span className="h-3 w-3 rounded" style={{ background: 'rgba(245,158,11,0.5)' }} />负相关
                          </span>
                        </div>
                      </Card>
                    )}
                  </>
                )}

                {/* 对话 */}
                <Card
                  title={
                    <span className="flex items-center gap-2">
                      <MessageSquare className="h-4 w-4" />追问
                    </span>
                  }
                  subtitle="本地引擎模式下为规则化应答；配置 LLM 后可自由问答"
                >
                  <div className="mb-3 max-h-72 space-y-2 overflow-y-auto">
                    {chat.length === 0 && (
                      <p className="text-xs text-slate-400">
                        试试问：「当前波动率适合多大仓位？」「如果跌破第一支撑该怎么办？」
                      </p>
                    )}
                    {chat.map((m, i) => (
                      <div
                        key={i}
                        className={`rounded-lg px-3 py-2 text-xs leading-relaxed ${
                          m.role === 'user' ? 'ml-8 bg-brand-50 text-slate-700' : 'mr-4 bg-slate-50 text-slate-700'
                        }`}
                      >
                        <div className="whitespace-pre-wrap">{m.content}</div>
                      </div>
                    ))}
                    {chatLoading && <Loading label="思考中…" className="py-3" />}
                    <div ref={chatEnd} />
                  </div>
                  <div className="flex gap-2">
                    <Input
                      value={chatInput}
                      onChange={(e) => setChatInput(e.target.value)}
                      onKeyDown={(e) => e.key === 'Enter' && !e.shiftKey && sendChat()}
                      placeholder="输入你的问题…"
                    />
                    <Button variant="primary" onClick={sendChat} loading={chatLoading} icon={<Send className="h-3.5 w-3.5" />} />
                  </div>
                </Card>

                <Card title="引擎说明">
                  <div className="space-y-2.5 text-xs text-slate-600">
                    <div className="flex gap-2">
                      <Gauge className="mt-0.5 h-3.5 w-3.5 shrink-0 text-brand-500" />
                      <span>
                        <span className="font-medium">本地引擎</span>：5 个维度（趋势/动量/反转/量能/风险）加权打分，
                        权重按投资周期调整，全部结论可追溯到具体指标数值。
                      </span>
                    </div>
                    <div className="flex gap-2">
                      <Layers className="mt-0.5 h-3.5 w-3.5 shrink-0 text-brand-500" />
                      <span>
                        <span className="font-medium">状态识别</span>：综合 ADX、效率比、已实现波动率分位判定趋势市/震荡市/高波动/过渡市。
                      </span>
                    </div>
                    <div className="flex gap-2">
                      <Brain className="mt-0.5 h-3.5 w-3.5 shrink-0 text-brand-500" />
                      <span>
                        <span className="font-medium">策略匹配</span>：根据识别出的市场状态从内置库中推荐最契合的策略族，
                        可直接一键跳转回测。
                      </span>
                    </div>
                  </div>
                </Card>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  )
}
