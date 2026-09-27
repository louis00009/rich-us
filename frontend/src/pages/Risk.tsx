import {
  AlertOctagon,
  AlertTriangle,
  Ban,
  Power,
  Save,
  ScrollText,
  Shield,
  ShieldAlert,
  ShieldCheck,
  TrendingDown,
  Unlock,
} from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import {
  Alert,
  Badge,
  Button,
  Card,
  DataTable,
  Empty,
  Field,
  Input,
  Loading,
  Modal,
  Progress,
  Select,
  Switch,
  Tabs,
  useToast,
} from '../components/ui'
import { api } from '../lib/api'
import { fmtAgo, fmtDateTime, fmtMoney, fmtNum } from '../lib/format'
import type { AuditRow, RiskConfig } from '../lib/types'

const STOP_GALLERY = [
  { key: 'none', label: '不启用', desc: '仅靠策略信号离场' },
  { key: 'fixed_pct', label: '固定百分比', desc: '自成本价固定百分比，简单直接', param: '百分比 %' },
  { key: 'pct_trailing', label: '百分比移动', desc: '跟随最高价回撤百分比离场', param: '百分比 %' },
  { key: 'atr_fixed', label: 'ATR 固定', desc: '以 N 倍 ATR 为距离，随波动自适应', param: 'ATR 倍数' },
  { key: 'atr_trailing', label: 'ATR 移动', desc: '最高价 − N×ATR，趋势策略标配', param: 'ATR 倍数' },
  { key: 'chandelier', label: '吊灯止损', desc: '取更宽的 ATR 距离，避免过早离场', param: 'ATR 倍数' },
  { key: 'breakeven', label: '保本止损', desc: '浮盈达 R 后把止损移到成本价', param: 'R 触发点' },
  { key: 'time_stop', label: '时间止损', desc: '持满 N 根 bar 仍无表现即离场', param: 'bar 数' },
  { key: 'volatility', label: '波动率自适应', desc: 'ATR 放大时同步放宽，防噪声扫出', param: 'ATR 倍数' },
]

const SIZING = [
  { key: 'weight', label: '策略权重直用', desc: '把策略输出的目标权重直接当作权益占比（回测最常用）' },
  { key: 'fixed_fraction', label: '固定比例', desc: '每笔按权益固定百分比建仓' },
  { key: 'risk_parity_vol', label: '波动率平价', desc: '按波动率倒数分配，低波动多配' },
  { key: 'atr_risk', label: '固定风险（ATR）', desc: '单笔最大亏损锁定为权益的 N%，机构标准做法' },
  { key: 'kelly_capped', label: '凯利公式（封顶）', desc: '按胜率与盈亏比推算最优仓位' },
  { key: 'equal_weight', label: '等权分配', desc: '所有标的均分仓位' },
]

export default function Risk() {
  const toast = useToast()
  const [cfg, setCfg] = useState<RiskConfig | null>(null)
  const [summary, setSummary] = useState<any[]>([])
  const [expo, setExpo] = useState<any>(null)
  const [audit, setAudit] = useState<AuditRow[]>([])
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [tab, setTab] = useState('limits')
  const [killOpen, setKillOpen] = useState(false)
  const [killPwd, setKillPwd] = useState('')
  // P2 修复：旧实现输入框清空时 parseFloat('') 会把 0 存进配置
  //（如 max_position_pct=0 → 之后每笔订单都被 POSITION_CAP 拒绝，而 UI 提示「已保存」）。
  // 现在：草稿字符串保持输入流畅；非法值标记 bad 且阻止保存。
  // ⚠️ hooks 必须全部位于 early return 之前（React #300 铁律）。
  const [drafts, setDrafts] = useState<Record<string, string>>({})
  const [bad, setBad] = useState<Record<string, boolean>>({})
  const [levelFilter, setLevelFilter] = useState('')

  const load = useCallback(async () => {
    const rs = await Promise.allSettled([
      api.get<{ config: RiskConfig; summary: any[] }>('/risk/config'),
      api.get<any>('/risk/exposure'),
      api.get<{ items: AuditRow[] }>('/risk/audit?limit=200'),
    ])
    if (rs[0].status === 'fulfilled') {
      setCfg(rs[0].value.config)
      setSummary(rs[0].value.summary)
    }
    if (rs[1].status === 'fulfilled') setExpo(rs[1].value)
    if (rs[2].status === 'fulfilled') setAudit(rs[2].value.items)
    setLoading(false)
  }, [])

  useEffect(() => {
    load()
  }, [load])

  const save = async () => {
    if (!cfg) return
    if (badKeys.length) {
      toast('error', '存在无效的风控数值（' + badKeys.join('、') + '），已取消保存 —— 请修正后再保存')
      return
    }
    setSaving(true)
    try {
      await api.put('/risk/config', cfg)
      toast('success', '风控配置已保存，对下一笔订单立即生效')
      load()
    } catch (e: any) {
      toast('error', e?.message || '保存失败')
    } finally {
      setSaving(false)
    }
  }

  const toggleKill = async (on: boolean) => {
    if (on) {
      try {
        await api.post('/risk/kill-switch', { engaged: true })
        toast('warning', '🛑 熔断已启用，所有下单通道关闭')
        load()
      } catch (e: any) {
        toast('error', e?.message || '操作失败')
      }
    } else {
      setKillOpen(true)
    }
  }

  const confirmUnkill = async () => {
    try {
      await api.post('/risk/kill-switch', { engaged: false, password: killPwd })
      toast('success', '熔断已解除')
      setKillOpen(false)
      setKillPwd('')
      load()
    } catch (e: any) {
      toast('error', e?.message || '口令不正确')
    }
  }

  if (loading && !cfg) return <Loading label="加载风控配置…" />

  const upd = (patch: Partial<RiskConfig>) => setCfg((c) => (c ? { ...c, ...patch } : c))

  const updNum = (key: string, raw: string, min: number, isInt = false) => {
    setDrafts((d) => ({ ...d, [key]: raw }))
    const v = isInt ? parseInt(raw, 10) : parseFloat(raw)
    if (Number.isNaN(v) || v < min) {
      setBad((b) => ({ ...b, [key]: true }))
      return
    }
    setBad((b) => {
      const nx = { ...b }
      delete nx[key]
      return nx
    })
    upd({ [key]: v } as unknown as Partial<RiskConfig>)
  }

  const numVal = (key: string, cur: unknown) =>
    drafts[key] !== undefined ? drafts[key] : String(cur ?? '')

  const badKeys = Object.keys(bad)
  const filteredAudit = audit.filter((a) => !levelFilter || a.level === levelFilter)

  return (
    <div className="space-y-5">
      {/* 熔断状态 */}
      <Card>
        <div className="flex flex-wrap items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <div
              className={`flex h-11 w-11 items-center justify-center rounded-xl ${
                cfg?.kill_switch ? 'bg-rose-100 text-rose-600' : 'bg-emerald-100 text-emerald-600'
              }`}
            >
              {cfg?.kill_switch ? <AlertOctagon className="h-5 w-5" /> : <ShieldCheck className="h-5 w-5" />}
            </div>
            <div>
              <div className="text-sm font-semibold text-slate-800">
                {cfg?.kill_switch ? '熔断开关已启用' : '交易通道正常'}
              </div>
              <div className="text-xs text-slate-500">
                {cfg?.kill_switch
                  ? '所有新订单（含实时引擎）会被拒绝；已有持仓不会被自动平仓'
                  : '所有订单在提交前都会经过下列护栏检查'}
              </div>
            </div>
          </div>
          <Button
            variant={cfg?.kill_switch ? 'success' : 'danger'}
            size="lg"
            onClick={() => toggleKill(!cfg?.kill_switch)}
            icon={cfg?.kill_switch ? <Power className="h-4 w-4" /> : <Ban className="h-4 w-4" />}
          >
            {cfg?.kill_switch ? '解除熔断' : '启用熔断（紧急制动）'}
          </Button>
        </div>
      </Card>

      <Tabs
        className="w-fit"
        value={tab}
        onChange={setTab}
        tabs={[
          { key: 'limits', label: '护栏参数' },
          { key: 'stops', label: '止损与仓位' },
          { key: 'exposure', label: '实时敞口' },
          { key: 'audit', label: '审计日志', badge: audit.length },
        ]}
      />

      {/* 护栏参数 */}
      {tab === 'limits' && cfg && (
        <div className="grid gap-5 xl:grid-cols-3">
          <Card className="xl:col-span-2" title="头寸与集中度限额" subtitle="任一超限的订单会被拒绝或自动缩减">
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="单标的持仓上限（% 权益）" hint="防止单一标的风险过度集中">
                <Input
                  type="number"
                  step="0.5"
                  min="0.1"
                  max="100"
                  value={numVal('max_position_pct', cfg.max_position_pct)}
                  onChange={(e) => updNum('max_position_pct', e.target.value, 0.1)}
                />
              </Field>
              <Field label="总敞口上限（% 权益）" hint="多空绝对市值之和的上限">
                <Input
                  type="number"
                  step="5"
                  min="1"
                  max="400"
                  value={numVal('max_gross_exposure_pct', cfg.max_gross_exposure_pct)}
                  onChange={(e) => updNum('max_gross_exposure_pct', e.target.value, 1)}
                />
              </Field>
              <Field label="最大持仓数量" hint="同时持有的标的数量上限">
                <Input
                  type="number"
                  min="1"
                  max="200"
                  value={numVal('max_open_positions', cfg.max_open_positions)}
                  onChange={(e) => updNum('max_open_positions', e.target.value, 1, true)}
                />
              </Field>
              <Field label="最小下单金额（$）" hint="低于此金额的订单直接拒绝，避免碎单">
                <Input
                  type="number"
                  step="50"
                  min="0"
                  value={numVal('min_order_notional', cfg.min_order_notional)}
                  onChange={(e) => updNum('min_order_notional', e.target.value, 0)}
                />
              </Field>
              <Field label="单笔下单上限（$）" hint="超过会自动缩减到该金额">
                <Input
                  type="number"
                  step="1000"
                  value={numVal('max_order_notional', cfg.max_order_notional)}
                  onChange={(e) => updNum('max_order_notional', e.target.value, 1)}
                />
              </Field>
              <div className="sm:col-span-2">
                <Switch
                  checked={cfg.trading_hours_only}
                  onChange={(v) => upd({ trading_hours_only: v })}
                  label="仅允许在美股常规交易时段（09:30–16:00 ET）下单"
                  hint="关闭后可在盘前盘后下单，但会增加流动性风险，建议仅在确有需要时关闭"
                />
              </div>
            </div>

            <div className="mt-5 border-t border-slate-100 pt-4">
              <h4 className="mb-3 text-xs font-semibold uppercase tracking-wide text-slate-400">亏损保护</h4>
              <div className="grid gap-4 sm:grid-cols-2">
                <Field label="单日最大亏损（%）" hint="达到该比例后当日禁止继续开仓">
                  <Input
                    type="number"
                    step="0.5"
                    min="0.1"
                    value={numVal('max_daily_loss_pct', cfg.max_daily_loss_pct)}
                    onChange={(e) => updNum('max_daily_loss_pct', e.target.value, 0.1)}
                  />
                </Field>
                <Field label="最大回撤熔断（%）" hint="账户回撤触及该线后全部禁止开仓">
                  <Input
                    type="number"
                    step="1"
                    min="0.1"
                    value={numVal('max_drawdown_pct', cfg.max_drawdown_pct)}
                    onChange={(e) => updNum('max_drawdown_pct', e.target.value, 0.1)}
                  />
                </Field>
              </div>
            </div>

            <div className="mt-5 border-t border-slate-100 pt-4">
              <h4 className="mb-3 text-xs font-semibold uppercase tracking-wide text-slate-400">标的白 / 黑名单</h4>
              <div className="grid gap-4 sm:grid-cols-2">
                <Field label="白名单（逗号分隔）" hint="非空时，只有名单内的标的可以交易">
                  <Input value={cfg.whitelist} onChange={(e) => upd({ whitelist: e.target.value.toUpperCase() })} placeholder="SPY,QQQ" />
                </Field>
                <Field label="黑名单（逗号分隔）" hint="名单内的标的任何时候都会被拒绝">
                  <Input value={cfg.blacklist} onChange={(e) => upd({ blacklist: e.target.value.toUpperCase() })} placeholder="TSLA,COIN" />
                </Field>
              </div>
            </div>

            <div className="mt-5 flex gap-2">
              <Button variant="primary" loading={saving} onClick={save} icon={<Save className="h-4 w-4" />}>
                保存护栏配置
              </Button>
              <Button onClick={load}>放弃修改</Button>
            </div>
          </Card>

          <Card title="当前生效的限额" subtitle="下单时逐条校验">
            <div className="space-y-2.5">
              {summary.map((s, i) => (
                <div key={i} className="flex items-start justify-between gap-3 border-b border-dashed border-slate-100 pb-2">
                  <span className="text-xs text-slate-500">{s.key}</span>
                  <span className="text-right text-xs font-medium text-slate-700">{s.value}</span>
                </div>
              ))}
            </div>
            <Alert tone="info" className="mt-4" title="护栏是最后一道防线">
              策略可以出错，护栏不能。任何不通过校验的订单都会被拒绝并写入审计日志，
              <span className="font-medium">包括由实时引擎自动生成的订单</span>。
            </Alert>
          </Card>
        </div>
      )}

      {/* 止损与仓位 */}
      {tab === 'stops' && cfg && (
        <div className="grid gap-5 xl:grid-cols-3">
          <Card className="xl:col-span-2" title="默认止损策略" subtitle="应用于实时引擎的每一笔持仓">
            <div className="grid gap-2.5 sm:grid-cols-2 lg:grid-cols-3">
              {STOP_GALLERY.map((s) => (
                <button
                  key={s.key}
                  onClick={() => upd({ stop_type: s.key })}
                  className={`rounded-lg border p-3 text-left transition-all ${
                    cfg.stop_type === s.key
                      ? 'border-brand-400 bg-brand-50 ring-1 ring-brand-300'
                      : 'border-slate-200 hover:border-slate-300 hover:bg-slate-50'
                  }`}
                >
                  <div className="flex items-center justify-between">
                    <span className="text-sm font-medium text-slate-800">{s.label}</span>
                    {cfg.stop_type === s.key && <ShieldCheck className="h-4 w-4 text-brand-600" />}
                  </div>
                  <p className="mt-1 text-[11px] leading-relaxed text-slate-500">{s.desc}</p>
                </button>
              ))}
            </div>

            <div className="mt-5 border-t border-slate-100 pt-4">
              <h4 className="mb-3 text-xs font-semibold uppercase tracking-wide text-slate-400">止损参数</h4>
              <div className="grid gap-4 sm:grid-cols-3">
                <Field
                  label={STOP_GALLERY.find((s) => s.key === cfg.stop_type)?.param || '参数值'}
                  hint="ATR 类通常 2–3.5 倍；百分比类通常 3–8%"
                >
                  <Input
                    type="number"
                    step="0.1"
                    min="0"
                    value={numVal('stop_value', cfg.stop_value)}
                    onChange={(e) => updNum('stop_value', e.target.value, 0.1)}
                    disabled={cfg.stop_type === 'none'}
                  />
                </Field>
                <Field label="R 倍止盈" hint="0 = 关闭。2R 表示盈利达到 2 倍风险距离时止盈">
                  <Input
                    type="number"
                    step="0.5"
                    min="0"
                    value={numVal('take_profit_r', cfg.take_profit_r)}
                    onChange={(e) => updNum('take_profit_r', e.target.value, 0)}
                  />
                </Field>
                <Field label="时间止损（bar）" hint="0 = 关闭">
                  <Input
                    type="number"
                    min="0"
                    value={numVal('time_stop_bars', cfg.time_stop_bars)}
                    onChange={(e) => updNum('time_stop_bars', e.target.value, 0, true)}
                  />
                </Field>
              </div>
            </div>

            <div className="mt-5 border-t border-slate-100 pt-4">
              <h4 className="mb-3 text-xs font-semibold uppercase tracking-wide text-slate-400">仓位算法</h4>
              <div className="grid gap-2.5 sm:grid-cols-2 lg:grid-cols-3">
                {SIZING.map((s) => (
                  <button
                    key={s.key}
                    onClick={() => upd({ sizing_method: s.key })}
                    className={`rounded-lg border p-3 text-left transition-all ${
                      cfg.sizing_method === s.key
                        ? 'border-brand-400 bg-brand-50 ring-1 ring-brand-300'
                        : 'border-slate-200 hover:border-slate-300 hover:bg-slate-50'
                    }`}
                  >
                    <div className="flex items-center justify-between">
                      <span className="text-sm font-medium text-slate-800">{s.label}</span>
                      {cfg.sizing_method === s.key && <ShieldCheck className="h-4 w-4 text-brand-600" />}
                    </div>
                    <p className="mt-1 text-[11px] leading-relaxed text-slate-500">{s.desc}</p>
                  </button>
                ))}
              </div>
              {(cfg.sizing_method === 'atr_risk' || cfg.sizing_method === 'kelly_capped') && (
                <div className="mt-4 max-w-xs">
                  <Field label="每笔风险（% 权益）" hint="固定风险仓位法：单笔最大亏损锁定在此比例">
                    <Input
                      type="number"
                      step="0.1"
                      min="0.1"
                      max="20"
                      value={numVal('risk_per_trade_pct', cfg.risk_per_trade_pct)}
                      onChange={(e) => updNum('risk_per_trade_pct', e.target.value, 0.1)}
                    />
                  </Field>
                </div>
              )}
            </div>

            <div className="mt-5 flex gap-2">
              <Button variant="primary" loading={saving} onClick={save} icon={<Save className="h-4 w-4" />}>
                保存止损与仓位设置
              </Button>
              <Button onClick={load}>放弃修改</Button>
            </div>
          </Card>

          <div className="space-y-5">
            <Card title="止损机制说明">
              <ul className="space-y-2.5 text-xs text-slate-600">
                <li className="flex gap-2">
                  <Shield className="mt-0.5 h-3.5 w-3.5 shrink-0 text-brand-500" />
                  <span>回测与实盘使用<span className="font-medium">同一套止损状态机</span>，保证「回测即实盘」。</span>
                </li>
                <li className="flex gap-2">
                  <TrendingDown className="mt-0.5 h-3.5 w-3.5 shrink-0 text-brand-500" />
                  <span>移动止损只朝有利方向推进，绝不会反向放宽。</span>
                </li>
                <li className="flex gap-2">
                  <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-amber-500" />
                  <span>止损判定使用 bar 内最高/最低价，而非收盘价 —— 避免高估收益。</span>
                </li>
                <li className="flex gap-2">
                  <ShieldAlert className="mt-0.5 h-3.5 w-3.5 shrink-0 text-rose-500" />
                  <span>「不启用止损」在杠杆或高波动品种上极其危险，请谨慎选择。</span>
                </li>
              </ul>
            </Card>

            <Card title="推荐组合">
              <div className="space-y-3 text-xs">
                <div className="rounded-lg border border-slate-200 p-3">
                  <div className="font-medium text-slate-700">趋势跟随</div>
                  <div className="mt-1 text-slate-500">
                    ATR 移动止损（3 倍）+ 固定风险仓位（1%）。让盈利奔跑、把单笔亏损锁死。
                  </div>
                </div>
                <div className="rounded-lg border border-slate-200 p-3">
                  <div className="font-medium text-slate-700">均值回归</div>
                  <div className="mt-1 text-slate-500">
                    ATR 固定止损（2 倍）+ R 倍止盈（1.5R）+ 时间止损（10 bar）。避免久拖不决。
                  </div>
                </div>
                <div className="rounded-lg border border-slate-200 p-3">
                  <div className="font-medium text-slate-700">组合配置</div>
                  <div className="mt-1 text-slate-500">
                    吊灯止损（3.5 倍）+ 波动率平价仓位。低波动标的自然多配，组合波动率更平稳。
                  </div>
                </div>
              </div>
            </Card>
          </div>
        </div>
      )}

      {/* 实时敞口 */}
      {tab === 'exposure' && (
        <div className="grid gap-5 xl:grid-cols-3">
          <Card className="xl:col-span-2" title="持仓敞口明细" subtitle="每个标的的占用与剩余额度">
            <DataTable<any>
              rows={expo?.positions || []}
              rowKey={(r) => r.symbol}
              empty={<Empty title="当前无持仓" />}
              columns={[
                { key: 's', label: '标的', render: (r) => <span className="font-medium">{r.symbol}</span> },
                { key: 'q', label: '数量', align: 'right', render: (r) => <span className="num">{fmtNum(r.quantity, 2)}</span> },
                { key: 'm', label: '市值', align: 'right', render: (r) => <span className="num">{fmtMoney(r.market_value, 0)}</span> },
                { key: 'p', label: '占权益', align: 'right', render: (r) => <span className="num">{r.pct}%</span> },
                {
                  key: 'h',
                  label: '剩余额度',
                  width: '180px',
                  render: (r) => (
                    <div className="flex items-center gap-2">
                      <div className="w-24">
                        <Progress value={r.pct} max={Math.max(r.pct + r.headroom_pct, 1)} tone={r.pct > 18 ? 'red' : 'brand'} height="h-1" />
                      </div>
                      <span className="num text-xs text-slate-500">+{r.headroom_pct}%</span>
                    </div>
                  ),
                },
              ]}
            />
          </Card>

          <Card title="组合指标">
            {expo ? (
              <div className="space-y-3">
                {[
                  ['账户权益', fmtMoney(expo.equity, 2)],
                  ['现金', fmtMoney(expo.cash, 2)],
                  ['净敞口', `${fmtMoney(expo.net_exposure, 0)} (${expo.net_pct}%)`],
                  ['总敞口', `${fmtMoney(expo.gross_exposure, 0)} (${expo.gross_pct}%)`],
                  ['多头市值', fmtMoney(expo.long_value, 0)],
                  ['空头市值', fmtMoney(expo.short_value, 0)],
                  ['持仓数量', String(expo.positions?.length ?? 0)],
                ].map(([k, v]) => (
                  <div key={k} className="flex items-center justify-between border-b border-dashed border-slate-100 pb-2">
                    <span className="text-xs text-slate-500">{k}</span>
                    <span className="num text-sm font-medium text-slate-700">{v}</span>
                  </div>
                ))}
              </div>
            ) : (
              <Loading />
            )}
          </Card>
        </div>
      )}

      {/* 审计日志 */}
      {tab === 'audit' && (
        <Card
          title={
            <span className="flex items-center gap-2">
              <ScrollText className="h-4 w-4" />审计日志
            </span>
          }
          subtitle="所有下单、风控变更、登录与实盘解锁操作都会留痕"
          actions={
            <Select className="w-36" value={levelFilter} onChange={(e) => setLevelFilter(e.target.value)}>
              <option value="">全部级别</option>
              <option value="INFO">INFO</option>
              <option value="WARN">WARN</option>
              <option value="CRITICAL">CRITICAL</option>
            </Select>
          }
          dense
        >
          <DataTable<AuditRow>
            rows={filteredAudit}
            rowKey={(r) => r.id}
            maxHeight="620px"
            empty={<Empty title="暂无日志" />}
            columns={[
              { key: 't', label: '时间', render: (r) => <span className="num text-xs text-slate-500" title={fmtDateTime(r.ts)}>{fmtAgo(r.ts)}</span> },
              {
                key: 'lv',
                label: '级别',
                render: (r) => (
                  <Badge tone={r.level === 'CRITICAL' ? 'red' : r.level === 'WARN' ? 'amber' : 'slate'}>{r.level}</Badge>
                ),
              },
              { key: 'a', label: '动作', render: (r) => <span className="font-mono text-xs text-slate-600">{r.action}</span> },
              { key: 'ac', label: '操作者', render: (r) => <span className="text-xs text-slate-500">{r.actor}</span> },
              { key: 'd', label: '详情', render: (r) => <span className="text-xs text-slate-600">{r.detail}</span> },
            ]}
          />
        </Card>
      )}

      {/* 解除熔断 */}
      <Modal
        open={killOpen}
        onClose={() => setKillOpen(false)}
        title="解除熔断"
        footer={
          <>
            <Button onClick={() => setKillOpen(false)}>取消</Button>
            <Button variant="primary" disabled={!killPwd} onClick={confirmUnkill} icon={<Unlock className="h-3.5 w-3.5" />}>
              确认解除
            </Button>
          </>
        }
      >
        <div className="space-y-3">
          <Alert tone="warn" title="解除熔断需要口令确认">
            这是为了避免误触导致风险敞口在无准备的情况下重新打开。请输入账户口令。
          </Alert>
          <Field label="账户口令">
            <Input type="password" value={killPwd} onChange={(e) => setKillPwd(e.target.value)} autoComplete="current-password" />
          </Field>
        </div>
      </Modal>
    </div>
  )
}
