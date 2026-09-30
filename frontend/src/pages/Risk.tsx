import {
  AlertOctagon,
  Ban,
  Power,
  Save,
  ShieldCheck,
  Unlock,
} from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import {
  Alert,
  Button,
  Card,
  Field,
  Input,
  Loading,
  Modal,
  Switch,
  Tabs,
  useToast,
} from '../components/ui'
import { api } from '../lib/api'
import type { AuditRow, RiskConfig } from '../lib/types'
import { AuditTab, ExposureTab, SIZING, STOP_GALLERY, StopsSideCards } from '../components/risk/tabs'

/**
 * 风控页。结构（FILE_SIZE_DEBT Batch C-1）：
 * 取数与护栏/止损两个表单 tab 在本文件；实时敞口 / 审计日志 tab 与
 * 止损选项常量见 components/risk/tabs.tsx。
 */
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

          <StopsSideCards />
        </div>
      )}

      {/* 实时敞口 */}
      {tab === 'exposure' && <ExposureTab expo={expo} cfg={cfg} />}

      {/* 审计日志 */}
      {tab === 'audit' && <AuditTab audit={audit} levelFilter={levelFilter} onLevelFilter={setLevelFilter} />}

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
