import {
  Bot,
  ChevronDown,
  ChevronRight,
  CircleDot,
  Eye,
  Play,
  Power,
  RefreshCw,
  ShieldBan,
} from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { Alert, Badge, Button, Card, Loading } from '../components/ui'
import OrderAiDiagnose from '../components/OrderAiDiagnose'
import ProposalAiReview from '../components/ProposalAiReview'
import { api } from '../lib/api'
import { downColor, fmtMoney, upColor } from '../lib/format'

interface Overview {
  system: Record<string, any>
  account: Record<string, any>
  positions: any[]
  watchlist_quotes: any[]
  engines: any[]
  recent_decisions: any[]
  unread_alerts: number
  recent_alerts: any[]
  proposals?: any[]
  pending_proposals?: number
  decision_stats: { by_actor: Record<string, number>; by_action: Record<string, number> }
}

const ACTION_TONE: Record<string, 'green' | 'red' | 'amber' | 'slate'> = {
  BUY: 'green',
  SELL: 'red',
  STOP: 'red',
  SKIP: 'amber',
  ANALYZE: 'slate',
  DRY_RUN: 'slate',
}

/**
 * AI 接管中心：一屏看清「AI 正在看什么 → 想做什么 → 做了什么 → 为什么」。
 * 数据全部来自 GET /api/ops/overview（字段自带说明，任何 LLM 可直接消费）。
 */
export default function AIOps() {
  const [data, setData] = useState<Overview | null>(null)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [expanded, setExpanded] = useState<number | null>(null)
  const [toastMsg, setToastMsg] = useState('')
  // P2：旧实现多处裸 setTimeout 清 toast —— 连续操作时前一个定时器会把后一条
  // 提示提前清掉。统一走 showToast，先清旧定时器。
  const toastTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const showToast = (msg: string, ms = 4500) => {
    if (toastTimer.current) clearTimeout(toastTimer.current)
    setToastMsg(msg)
    toastTimer.current = setTimeout(() => setToastMsg(''), ms)
  }

  const load = useCallback(async () => {
    try {
      const r = await api.get<Overview>('/ops/overview', 60_000)
      setData(r)
    } catch {
      /* 静默重试 */
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
    const t = setInterval(load, 10_000)
    return () => clearInterval(t)
  }, [load])

  const stopEngine = async (sid: number) => {
    setBusy(true)
    try {
      await api.post(`/ops/engine/${sid}/stop`)
      showToast(`引擎 #${sid} 已停止`)
      load()
    } catch (e: any) {
      showToast(e?.message || '停止失败')
    } finally {
      setBusy(false)
    }
  }

  // AI 提案审批（T-107）：批准 = 走完整下单链立即执行。
  // 实盘模式（IBKR 实盘端口）下需再输账户口令（第四道防线）。
  const decide = async (pid: number, approve: boolean) => {
    let password = ''
    if (approve && data?.system?.mode === 'live') {
      password = window.prompt(`⚠️ 实盘模式：批准后立即提交真实订单。\n请输入账户口令确认执行：`) || ''
      if (!password) return
    }
    setBusy(true)
    try {
      await api.post(`/ops/proposals/${pid}/${approve ? 'approve' : 'reject'}`,
        approve && password ? { password } : undefined)
      showToast(`提案 #${pid} 已${approve ? '批准执行' : '拒绝'}`)
      load()
    } catch (e: any) {
      showToast(e?.message || '操作失败')
    } finally {
      setBusy(false)
    }
  }

  const toggleKill = async () => {
    const cur = data?.system?.kill_switch
    // 解除熔断（升险）需要账户口令 —— 与风控页 /risk/kill-switch 同规则
    let body: any = undefined
    if (cur) {
      const pwd = window.prompt('解除熔断会让下单通道恢复，请输入账户口令确认：') || ''
      if (!pwd) return
      body = { password: pwd }
    }
    setBusy(true)
    try {
      await api.post(`/ops/kill-switch?enable=${!cur}`, body)
      setToastMsg(!cur ? '⛔ 熔断已启用：所有新订单将被拒绝' : '✅ 熔断已解除')
      load()
    } catch (e: any) {
      // P1-13：失败必须可见 —— 旧实现吞异常，用户不知道熔断到底开没开
      showToast(`⚠️ ${e?.message || '熔断操作失败（状态未变更）'}`)
    } finally {
      setBusy(false)
    }
  }

  if (loading && !data) return <Loading label="正在拉取接管上下文…" />

  const kill = data?.system?.kill_switch
  const acc = data?.account

  return (
    <div className="space-y-5">
      {/* 顶栏：状态 + 一键操作 */}
      <div className="flex flex-wrap items-center gap-2">
        <Badge tone="brand" dot>
          <Bot className="mr-0.5 inline h-3 w-3" /> AI 接管中心
        </Badge>
        {kill ? (
          <Badge tone="red" dot>熔断中 —— 全部拒单</Badge>
        ) : (
          <Badge tone="green" dot>{data?.system?.mode === 'live' ? '实盘模式' : '模拟盘'}</Badge>
        )}
        <Badge tone={acc?.connected ? 'green' : 'amber'} dot>
          {acc?.connected ? '券商已连接' : '券商未连接'}
        </Badge>
        {data?.engines?.length ? (
          <Badge tone="slate">{data.engines.length} 个引擎运行中</Badge>
        ) : (
          <Badge tone="slate">无活跃引擎</Badge>
        )}
        <a
          href="/api/ops/guide"
          target="_blank"
          rel="noreferrer"
          title="AI 操作手册（任何模型接管的规范）"
          className="text-[11px] text-slate-400 underline decoration-dotted hover:text-brand-600"
        >
          AI 操作手册
        </a>
        <div className="ml-auto flex items-center gap-2">
          <OrderAiDiagnose autoRefresh />
          <Button icon={<RefreshCw className="h-3.5 w-3.5" />} onClick={load}>刷新</Button>
          <Button
            variant={kill ? 'primary' : 'danger'}
            icon={<Power className="h-3.5 w-3.5" />}
            onClick={toggleKill}
            disabled={busy}
          >
            {kill ? '解除熔断' : '一键熔断'}
          </Button>
        </div>
      </div>

      {toastMsg && <Alert tone={toastMsg.includes('熔断已启用') ? 'danger' : 'info'} title={toastMsg} />}

      <div className="grid gap-5 xl:grid-cols-3">
        {/* 左：引擎 + 决策日志（2/3 宽） */}
        <div className="space-y-5 xl:col-span-2">
          {/* AI 正在看什么 / 想做什么 */}
          <Card
            title={
              <span className="flex items-center gap-2">
                <Eye className="h-4 w-4 text-brand-600" />
                AI 正在看什么 · 想做什么
              </span>
            }
            subtitle="活跃引擎的策略、标的、目标权重与最近一轮动作"
          >
            {!data?.engines?.length && (
              <div className="px-2 py-6 text-center text-xs leading-5 text-slate-400">
                当前没有运行中的引擎。
                <br />
                在<Link to="/trading" className="text-brand-600 hover:underline">实盘交易</Link>页启动策略引擎后，
                这里会实时显示它正在盯的标的、目标权重与每一步决策。
              </div>
            )}
            <div className="space-y-3">
              {data?.engines?.map((e) => (
                <div key={e.strategy_id} className="rounded-xl border border-slate-200 p-3">
                  <div className="flex flex-wrap items-center gap-2">
                    <CircleDot className={`h-3.5 w-3.5 ${e.running ? 'animate-pulse text-emerald-500' : 'text-slate-300'}`} />
                    <span className="text-sm font-semibold text-slate-800">#{e.strategy_id} {e.strategy_name}</span>
                    <Badge tone={e.mode === 'live' ? 'red' : 'brand'}>{e.mode === 'live' ? '实盘' : '模拟'}</Badge>
                    <span className="text-[11px] text-slate-400">
                      执行 {e.runtime_stats?.exec_count ?? 0} 轮 · 最近 {e.runtime_stats?.last_tick_ago_sec ?? '—'}s 前
                      {e.runtime_stats?.exec_loop_ms_p95 ? ` · P95 ${e.runtime_stats.exec_loop_ms_p95}ms` : ''}
                    </span>
                    <Button
                      variant="danger"
                      className="ml-auto"
                      icon={<Power className="h-3 w-3" />}
                      onClick={() => stopEngine(e.strategy_id)}
                      disabled={busy}
                    >
                      停止
                    </Button>
                  </div>

                  <div className="mt-2 flex flex-wrap items-center gap-1.5">
                    {(e.symbols || []).map((s: string) => (
                      <Link
                        key={s}
                        to={`/market?symbol=${encodeURIComponent(s)}`}
                        className="rounded-md border border-slate-200 px-1.5 py-0.5 text-[11px] font-medium text-slate-600 hover:border-brand-300 hover:text-brand-700"
                      >
                        {s}
                        {e.target_weights?.[s] !== undefined && (
                          <span className="ml-1 text-slate-400">{(e.target_weights[s] * 100).toFixed(1)}%</span>
                        )}
                      </Link>
                    ))}
                  </div>

                  {e.last_actions?.length > 0 && (
                    <div className="mt-2 space-y-1">
                      {e.last_actions.map((a: any, i: number) => (
                        <div key={i} className="flex items-center gap-2 text-xs">
                          <Badge tone={ACTION_TONE[a.type === 'ORDER' ? a.side : 'DRY_RUN'] ?? 'slate'}>
                            {a.type === 'ORDER' ? a.side : a.type}
                          </Badge>
                          <span className="font-medium text-slate-700">{a.symbol}</span>
                          <span className="text-slate-500">{a.quantity}</span>
                          {a.status && <span className="text-slate-400">→ {a.status}</span>}
                          {a.latency_ms != null && <span className="text-slate-300">{a.latency_ms}ms</span>}
                        </div>
                      ))}
                    </div>
                  )}
                  {e.last_skipped?.length > 0 && (
                    <div className="mt-2 space-y-0.5">
                      {e.last_skipped.slice(0, 3).map((s: any, i: number) => (
                        <div key={i} className="text-[11px] text-amber-600">
                          ⚠️ {s.symbol} {s.side} 被拦：[{s.code}] {s.reason}
                        </div>
                      ))}
                    </div>
                  )}
                  {e.last_errors?.length > 0 && (
                    <div className="mt-1 text-[11px] text-rose-600">⛔ {e.last_errors[0]}</div>
                  )}
                </div>
              ))}
            </div>
          </Card>

          {/* AI 提案（T-107）：AI 建议 → 人工批准 → 走完整下单链 */}
          <Card
            title={`AI 提案${data?.pending_proposals ? `（${data.pending_proposals} 条待审）` : ''}`}
            subtitle="AI 只有建议权 —— 批准后走与手动下单完全相同的风控护栏执行"
          >
            {data?.system?.mode === 'live' ? (
              <div className={`mb-3 rounded-lg border px-3 py-2 text-xs ${
                data.system.live_ready
                  ? 'border-rose-200 bg-rose-50 text-rose-700'
                  : 'border-amber-200 bg-amber-50 text-amber-800'
              }`}>
                {data.system.live_ready
                  ? '🔴 实盘模式已解锁：批准提案将提交真实订单（IBKR 实盘端口）。执行需输入账户口令。'
                  : `实盘链路未就绪：${data.system.live_reason}（批准仅在模拟/纸面模式执行）`}
              </div>
            ) : (
              <div className="mb-3 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-xs text-slate-500">
                当前为模拟/纸面模式 —— 提案批准以模拟单执行。接 IBKR 实盘端口并解锁后自动切换为真实订单。
              </div>
            )}
            <div className="space-y-2">
              {(data?.proposals || []).slice(0, 6).map((p) => (
                <div key={p.id} className="rounded-lg border border-slate-100 p-2.5">
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge tone={p.action === 'BUY' ? 'green' : p.action === 'SELL' ? 'red' : 'slate'}>{p.action}</Badge>
                    <span className="text-sm font-semibold text-slate-800">{p.symbol}</span>
                    <span className="num text-xs text-slate-500">{p.size_pct}% 仓位</span>
                    <span className="num text-xs text-slate-400">@ {p.entry || '—'}</span>
                    {p.stop && <span className="num text-[11px] text-emerald-600">止损 {p.stop}</span>}
                    {p.take_profit && <span className="num text-[11px] text-rose-600">止盈 {p.take_profit}</span>}
                    <Badge tone={p.status === 'proposed' ? 'amber' : p.status === 'executed' ? 'green' : 'slate'}>
                      {p.status === 'proposed' ? '待审' : p.status === 'executed' ? '已执行' : p.status === 'rejected' ? '已拒绝' : p.status}
                    </Badge>
                    <span className="ml-auto text-[10px] text-slate-300">{p.created_by}</span>
                    {p.status === 'proposed' && (
                      <span className="flex items-center gap-1.5">
                        <ProposalAiReview proposal={p} mode={data?.system?.mode} />
                        <Button
                          variant="primary"
                          onClick={() => decide(p.id, true)}
                          disabled={busy}
                          className="!px-2 !py-1 text-[11px]"
                        >
                          批准执行
                        </Button>
                        <Button onClick={() => decide(p.id, false)} disabled={busy} className="!px-2 !py-1 text-[11px]">
                          拒绝
                        </Button>
                      </span>
                    )}
                  </div>
                  {p.rationale && <p className="mt-1.5 line-clamp-2 text-[11px] leading-4 text-slate-500">{p.rationale}</p>}
                  {p.order_id && <div className="mt-1 text-[11px] text-slate-400">已生成订单 #{p.order_id}</div>}
                </div>
              ))}
              {!data?.proposals?.length && (
                <div className="px-2 py-6 text-center text-xs text-slate-400">
                  暂无提案 —— 前往「AI 量化研判」分析标的，点「转为买入/卖出提案」即可送审；也可由外部 AI 接管方调用 POST /ops/proposals 创建。
                </div>
              )}
            </div>
          </Card>

          {/* 决策日志流 */}
          <Card
            title="决策日志（可回溯）"
            subtitle="每条 = 当时看到的因子(context) → 结论 → 依据；点击展开因子快照"
          >
            <div className="max-h-[460px] space-y-1 overflow-y-auto">
              {data?.recent_decisions?.map((d) => {
                const open = expanded === d.id
                return (
                  <div key={d.id} className="rounded-lg border border-slate-100">
                    <button
                      className="flex w-full items-center gap-2 px-3 py-2 text-left hover:bg-slate-50"
                      onClick={() => setExpanded(open ? null : d.id)}
                    >
                      {open ? <ChevronDown className="h-3.5 w-3.5 text-slate-300" /> : <ChevronRight className="h-3.5 w-3.5 text-slate-300" />}
                      <Badge tone={ACTION_TONE[d.action?.split(':')[0]] ?? 'slate'}>{d.action}</Badge>
                      <span className="text-xs font-semibold text-slate-700">{d.symbol || '—'}</span>
                      <span className="min-w-0 flex-1 truncate text-xs text-slate-500">{d.decision}</span>
                      <span className="shrink-0 text-[10px] text-slate-300">
                        {new Date(d.ts + 'Z').toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' })}
                      </span>
                    </button>
                    {open && (
                      <div className="border-t border-slate-100 px-3 py-2">
                        <div className="text-[11px] text-slate-400">决策者：<span className="font-medium text-slate-600">{d.actor}</span>
                          {d.order_id ? ` · 订单 #${d.order_id}` : ''}</div>
                        {d.reasoning && <p className="mt-1 whitespace-pre-wrap text-xs leading-5 text-slate-600">{d.reasoning}</p>}
                        <pre className="mt-2 max-h-56 overflow-auto rounded-lg bg-slate-900 p-2.5 text-[10px] leading-4 text-slate-100">
                          {JSON.stringify(d.context, null, 2)}
                        </pre>
                      </div>
                    )}
                  </div>
                )
              })}
              {!data?.recent_decisions?.length && (
                <div className="px-2 py-6 text-center text-xs text-slate-400">
                  暂无决策记录 —— 启动引擎、跑一次 dry-run 或 AI 分析后，这里会出现完整链条。
                </div>
              )}
            </div>
          </Card>
        </div>

        {/* 右：账户 + 决策统计 + 提示 */}
        <div className="space-y-5">
          <Card title="账户">
            {acc?.connected ? (
              <div className="space-y-1.5 text-sm">
                <div className="flex justify-between"><span className="text-slate-500">权益</span><span className="num font-semibold">{fmtMoney(acc.equity ?? 0, 2)}</span></div>
                <div className="flex justify-between"><span className="text-slate-500">现金</span><span className="num">{fmtMoney(acc.cash ?? 0, 2)}</span></div>
                <div className="flex justify-between">
                  <span className="text-slate-500">当日盈亏</span>
                  <span className="num font-medium" style={{ color: (acc.day_pnl ?? 0) >= 0 ? upColor() : downColor() }}>
                    {(acc.day_pnl ?? 0) >= 0 ? '+' : ''}{(acc.day_pnl ?? 0).toFixed(2)}
                  </span>
                </div>
                {data?.positions?.length ? (
                  <div className="mt-2 border-t border-slate-100 pt-2 text-xs">
                    {data.positions.map((p) => (
                      <div key={p.symbol} className="flex justify-between py-0.5">
                        <Link to={`/market?symbol=${encodeURIComponent(p.symbol)}`} className="font-medium text-slate-600 hover:text-brand-700">
                          {p.symbol}
                        </Link>
                        <span className="num text-slate-500">{p.quantity} @ {p.last_price}</span>
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="pt-2 text-xs text-slate-400">当前无持仓</div>
                )}
              </div>
            ) : (
              <div className="text-xs text-slate-400">券商未连接：{acc?.error || acc?.message || '—'}</div>
            )}
          </Card>

          <Card title="近 24h 决策统计">
            <div className="space-y-2 text-xs">
              {Object.entries(data?.decision_stats?.by_actor ?? {}).length === 0 && (
                <div className="text-slate-400">暂无决策</div>
              )}
              {Object.entries(data?.decision_stats?.by_actor ?? {}).map(([k, v]) => (
                <div key={k} className="flex items-center justify-between">
                  <span className="text-slate-500">{k}</span>
                  <span className="num font-semibold text-slate-700">{v}</span>
                </div>
              ))}
              <div className="flex flex-wrap gap-1 border-t border-slate-100 pt-2">
                {Object.entries(data?.decision_stats?.by_action ?? {}).map(([k, v]) => (
                  <Badge key={k} tone={ACTION_TONE[k] ?? 'slate'}>{k} × {v}</Badge>
                ))}
              </div>
            </div>
          </Card>

          <Card
            title={<span className="flex items-center gap-2"><ShieldBan className="h-4 w-4 text-slate-400" />最新智能提示</span>}
            subtitle={<Link to="/dashboard" className="text-brand-600 hover:underline">未读 {data?.unread_alerts ?? 0} 条</Link>}
          >
            <div className="max-h-64 space-y-1.5 overflow-y-auto">
              {data?.recent_alerts?.length === 0 && <div className="text-xs text-slate-400">暂无提示</div>}
              {data?.recent_alerts?.map((a) => (
                <div key={a.id} className="rounded-lg border border-slate-100 px-2.5 py-1.5">
                  <div className="flex items-center gap-1.5">
                    <Badge tone={a.level === 'hot' ? 'red' : a.level === 'warn' ? 'amber' : 'slate'}>
                      {a.level === 'hot' ? '重要' : a.level === 'warn' ? '风险' : '动态'}
                    </Badge>
                    <span className="text-[11px] font-semibold text-slate-600">{a.symbol}</span>
                  </div>
                  <p className="mt-0.5 line-clamp-2 text-[11px] text-slate-500">{a.title}</p>
                </div>
              ))}
            </div>
          </Card>
        </div>
      </div>
    </div>
  )
}
