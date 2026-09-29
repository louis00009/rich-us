import {
  Activity,
  CheckCircle2,
  Database,
  ExternalLink,
  KeyRound,
  Lock,
  Palette,
  RefreshCw,
  Save,
  Server,
  ShieldCheck,
  Trash2,
  Unplug,
  XCircle,
} from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import DataSourcePanel from '../components/DataSourcePanel'
import TwelveDataKeys from '../components/TwelveDataKeys'
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
  Select,
  Stat,
  Switch,
  Tabs,
  useToast,
} from '../components/ui'
import { api, getUser } from '../lib/api'
import { invalidateAiStatus } from '../lib/ai'
import { fmtAgo, fmtNum, getColorMode, setColorMode, type ColorMode } from '../lib/format'
import type { SystemStatus } from '../lib/types'

interface BrokerCfg {
  provider: 'simulated' | 'ibkr'
  host: string
  port: number
  client_id: number
  account: string
  connection_type: 'tws' | 'gateway'
  readonly: boolean
  market_data_type: number
  use_rth: boolean
}

export default function Settings() {
  const toast = useToast()
  const [tab, setTab] = useState('broker')
  const [status, setStatus] = useState<SystemStatus | null>(null)
  const [cfg, setCfg] = useState<BrokerCfg | null>(null)
  const [presets, setPresets] = useState<any[]>([])
  const [guide, setGuide] = useState<string[]>([])
  const [catalog, setCatalog] = useState<any>(null)
  const [audit, setAudit] = useState<any>(null)
  const [loading, setLoading] = useState(true)
  const [testing, setTesting] = useState(false)
  const [testResult, setTestResult] = useState<any>(null)
  const [saving, setSaving] = useState(false)
  const [colorMode, setCM] = useState<ColorMode>(getColorMode())
  const [dsInfo, setDsInfo] = useState<any>(null)

  const [aiCfg, setAiCfg] = useState<any>(null)
  const [aiModels, setAiModels] = useState<any>(null)
  const [aiKeyInput, setAiKeyInput] = useState('')
  const [aiSaving, setAiSaving] = useState(false)
  const [aiTesting, setAiTesting] = useState(false)

  const [pwdOpen, setPwdOpen] = useState(false)
  const [curPwd, setCurPwd] = useState('')
  const [newPwd, setNewPwd] = useState('')
  const [confirmPwd, setConfirmPwd] = useState('')

  const load = useCallback(async () => {
    const rs = await Promise.allSettled([
      api.get<SystemStatus>('/system/status'),
      api.get<{ config: BrokerCfg; presets: any[]; setup_guide: string[] }>('/system/broker'),
      api.get<any>('/market/catalog'),
      api.get<any>('/system/audit-summary'),
      api.get<any>('/market/data-source'),
      api.get<any>('/system/ai'),
    ])
    if (rs[0].status === 'fulfilled') setStatus(rs[0].value)
    if (rs[1].status === 'fulfilled') {
      setCfg(rs[1].value.config)
      setPresets(rs[1].value.presets)
      setGuide(rs[1].value.setup_guide)
    }
    if (rs[2].status === 'fulfilled') setCatalog(rs[2].value)
    if (rs[3].status === 'fulfilled') setAudit(rs[3].value)
    if (rs[4].status === 'fulfilled') setDsInfo(rs[4].value)
    if (rs[5].status === 'fulfilled') {
      setAiCfg(rs[5].value.config)
      setAiModels(rs[5].value.models)
    }
    setLoading(false)
  }, [])

  useEffect(() => {
    load()
  }, [load])

  const upd = (patch: Partial<BrokerCfg>) => setCfg((c) => (c ? { ...c, ...patch } : c))

  const save = async () => {
    if (!cfg) return
    setSaving(true)
    try {
      const r = await api.put<any>('/system/broker', cfg)
      toast(r.warning ? 'warning' : 'success', r.warning || '券商设置已保存')
      load()
    } catch (e: any) {
      toast('error', e?.message || '保存失败')
    } finally {
      setSaving(false)
    }
  }

  const test = async () => {
    setTesting(true)
    setTestResult(null)
    try {
      const r = await api.post<any>('/system/broker/test')
      setTestResult(r)
      toast(r.ok ? 'success' : 'error', r.message)
    } catch (e: any) {
      toast('error', e?.message || '测试失败')
    } finally {
      setTesting(false)
    }
  }

  const disconnect = async () => {
    try {
      await api.post('/system/broker/disconnect')
      toast('success', '已断开券商连接')
    } catch (e: any) {
      toast('error', e?.message || '操作失败')
    }
  }

  const saveAi = async () => {
    if (!aiCfg?.model) {
      toast('warning', '请先选择模型')
      return
    }
    setAiSaving(true)
    try {
      const payload: any = {
        model: aiCfg.model,
        base_url: aiCfg.base_url || 'http://127.0.0.1:16689',
      }
      if (aiKeyInput.trim()) payload.api_key = aiKeyInput.trim()
      const r = await api.put<any>('/system/ai', payload)
      setAiCfg(r.config)
      setAiKeyInput('')
      // 让其它页面（AI 助手卡片）立刻看到新模型，而不是等下次刷新
      invalidateAiStatus()
      toast('success', 'AI 全局配置已保存')
      load()
    } catch (e: any) {
      toast('error', e?.message || '保存失败')
    } finally {
      setAiSaving(false)
    }
  }

  const testAi = async () => {
    setAiTesting(true)
    try {
      const r = await api.post<any>('/system/ai/test')
      toast(r.ok ? 'success' : 'error', r.message)
    } catch (e: any) {
      toast('error', e?.message || '测试失败')
    } finally {
      setAiTesting(false)
    }
  }

  const changePwd = async () => {
    if (newPwd !== confirmPwd) {
      toast('warning', '两次输入的新口令不一致')
      return
    }
    try {
      await api.post('/auth/password', { current_password: curPwd, new_password: newPwd })
      toast('success', '口令已更新')
      setPwdOpen(false)
      setCurPwd('')
      setNewPwd('')
      setConfirmPwd('')
    } catch (e: any) {
      toast('error', e?.message || '修改失败')
    }
  }

  const switchColor = (m: ColorMode) => {
    setColorMode(m)
    setCM(m)
    window.dispatchEvent(new Event('qd-colormode'))
    toast('success', m === 'cn' ? '已切换为红涨绿跌（中国习惯）' : '已切换为绿涨红跌（欧美习惯）')
  }

  if (loading && !cfg) return <Loading label="加载系统设置…" />

  return (
    <div className="space-y-5">
      <Tabs
        className="w-fit"
        value={tab}
        onChange={setTab}
        tabs={[
          { key: 'broker', label: '券商连接' },
          { key: 'ai', label: 'AI 分析' },
          { key: 'security', label: '安全与实盘' },
          { key: 'data', label: '数据与缓存' },
          { key: 'ui', label: '界面偏好' },
          { key: 'about', label: '系统信息' },
        ]}
      />

      {/* ============ 券商连接 ============ */}
      {tab === 'broker' && cfg && (
        <div className="grid gap-5 xl:grid-cols-3">
          <Card className="xl:col-span-2" title="券商配置" subtitle="默认使用内置模拟券商，零资金风险">
            <div className="space-y-4">
              <Field label="券商提供方">
                <Select value={cfg.provider} onChange={(e) => upd({ provider: e.target.value as any })}>
                  <option value="simulated">内置模拟券商（推荐先用它跑通全流程）</option>
                  <option value="ibkr">Interactive Brokers (IBKR)</option>
                </Select>
              </Field>

              {cfg.provider === 'ibkr' && (
                <>
                  <div className="grid gap-3 sm:grid-cols-2">
                    <Field label="TWS / Gateway 主机">
                      <Input value={cfg.host} onChange={(e) => upd({ host: e.target.value })} />
                    </Field>
                    <Field label="端口" hint="纸面 7497(TWS)/4002(GW) ｜ 实盘 7496(TWS)/4001(GW)">
                      <Input type="number" value={cfg.port} onChange={(e) => upd({ port: parseInt(e.target.value || '7497', 10) })} />
                    </Field>
                    <Field label="Client ID" hint="同一 TWS 上多个客户端需用不同 ID">
                      <Input type="number" value={cfg.client_id} onChange={(e) => upd({ client_id: parseInt(e.target.value || '17', 10) })} />
                    </Field>
                    <Field label="账户号（可选）" hint="留空则自动使用第一个受管账户">
                      <Input value={cfg.account} onChange={(e) => upd({ account: e.target.value })} />
                    </Field>
                  </div>

                  <div className="flex flex-wrap gap-1.5">
                    {presets
                      .filter((p) => p.key !== 'simulated')
                      .map((p) => (
                        <button
                          key={p.key}
                          onClick={() => upd({ host: p.host, port: p.port, provider: 'ibkr' })}
                          className={`rounded-md px-2.5 py-1.5 text-xs transition-colors ${
                            cfg.port === p.port ? 'bg-brand-600 text-white' : 'bg-slate-100 text-slate-600 hover:bg-slate-200'
                          }`}
                        >
                          {p.label} · {p.host}:{p.port}
                        </button>
                      ))}
                  </div>

                  <Switch
                    checked={cfg.readonly}
                    onChange={(v) => upd({ readonly: v })}
                    label="只读模式（推荐保持开启）"
                    hint="开启后本平台只能读取账户与持仓，无法通过 IBKR 下单。需要下单时再关闭。"
                  />

                  <div className="grid gap-3 sm:grid-cols-2">
                    <Field
                      label="行情类型"
                      hint="无实时行情订阅时请用「延迟」；做日内交易建议订阅后改为「实时」"
                    >
                      <Select value={cfg.market_data_type} onChange={(e) => upd({ market_data_type: parseInt(e.target.value, 10) })}>
                        <option value={1}>1 · 实时行情（需订阅）</option>
                        <option value={2}>2 · 冻结行情</option>
                        <option value={3}>3 · 延迟行情（默认，无需订阅）</option>
                        <option value={4}>4 · 延迟冻结行情</option>
                      </Select>
                    </Field>
                    <div className="flex items-end pb-1">
                      <Switch
                        checked={cfg.use_rth}
                        onChange={(v) => upd({ use_rth: v })}
                        label="仅使用常规交易时段数据"
                        hint="做日内策略建议保持开启；关闭后包含盘前盘后"
                      />
                    </div>
                  </div>

                  <Alert tone="info" title="行情权限说明">
                    IBKR 的实时行情需要单独订阅（美股约 $1.5–4.5/月，可用非专业用户费率）。
                    未订阅时用「延迟行情」也能正常回测与看盘，但
                    <span className="font-medium">日内策略不宜基于延迟价实盘成交</span>。
                  </Alert>

                  {cfg.port === 7496 || cfg.port === 4001 ? (
                    <Alert tone="danger" title="⚠️ 当前配置的是实盘端口">
                      即使端口指向实盘，下单仍受「环境变量 + 运行时解锁 + 逐笔护栏」三重保护。
                      请先在风控中心复核限额，再考虑解锁实盘。
                    </Alert>
                  ) : null}
                </>
              )}

              <div className="flex flex-wrap gap-2">
                <Button variant="primary" loading={saving} onClick={save} icon={<Save className="h-4 w-4" />}>
                  保存配置
                </Button>
                <Button loading={testing} onClick={test} icon={<Activity className="h-4 w-4" />}>
                  测试连接
                </Button>
                <Button onClick={disconnect} icon={<Unplug className="h-4 w-4" />}>
                  断开连接
                </Button>
              </div>

              {testResult && (
                <Alert tone={testResult.ok ? 'success' : 'danger'} title={testResult.ok ? '连接成功' : '连接失败'}>
                  {testResult.message}
                  {testResult.ok && testResult.account?.equity !== undefined && (
                    <div className="mt-2 grid grid-cols-2 gap-2 text-xs sm:grid-cols-4">
                      <span>
                        权益 <b className="num">${fmtNum(testResult.account.equity, 0)}</b>
                      </span>
                      <span>
                        现金 <b className="num">${fmtNum(testResult.account.cash, 0)}</b>
                      </span>
                      <span>
                        买入力 <b className="num">${fmtNum(testResult.account.buying_power, 0)}</b>
                      </span>
                      <span>
                        账户 <b>{testResult.account.account_id}</b>
                      </span>
                    </div>
                  )}
                </Alert>
              )}
            </div>
          </Card>

          <div className="space-y-5">
            {cfg.provider === 'ibkr' && (
              <Card title="IBKR 准备工作" subtitle="在 TWS 中完成以下设置后才能连接">
                <ol className="space-y-2.5">
                  {guide.map((g, i) => (
                    <li key={i} className="flex gap-2 text-xs leading-relaxed text-slate-600">
                      <span className="mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded-full bg-brand-100 text-[10px] font-semibold text-brand-700">
                        {i + 1}
                      </span>
                      {g.replace(/^\d+\.\s*/, '')}
                    </li>
                  ))}
                </ol>
                <Alert tone="warn" className="mt-4" title="端口被占用？">
                  IB Gateway 与 TWS 不能同时占用同一端口。若提示连接失败，先确认只有一个客户端在运行且 API 已启用。
                </Alert>
              </Card>
            )}

            <Card title="模拟券商" subtitle="内置虚拟账户，用于全链路演练">
              <div className="space-y-3 text-xs text-slate-600">
                <p>
                  模拟券商按最新行情 + 2bp 滑点即时撮合，佣金按
                  <span className="num"> max(0.0035/股, 0.35, 名义×0.005%) </span>
                  计算。账户状态持久化在本地数据库，重启不丢失。
                </p>
                <p className="text-slate-500">
                  它同样会穿过全部风控护栏，因此是验证策略与风控逻辑最安全的方式。
                </p>
                <Button
                  onClick={async () => {
                    if (!confirm('确认将模拟账户重置为 $100,000？当前持仓与历史将被清空。')) return
                    await api.post('/trading/sim/reset?cash=100000')
                    toast('success', '模拟账户已重置')
                  }}
                  icon={<RefreshCw className="h-3.5 w-3.5" />}
                >
                  重置模拟账户
                </Button>
              </div>
            </Card>
          </div>
        </div>
      )}

      {/* ============ AI 分析 ============ */}
      {tab === 'ai' && aiCfg && (
        <div className="grid gap-5 xl:grid-cols-3">
          <Card
            className="xl:col-span-2"
            title="AI 全局模型"
            subtitle="AI 研判 / AI Copilot 的默认模型。下拉列出网关的全部国内与国际模型，保存即生效，无需重启"
          >
            <div className="space-y-4">
              <Field
                label="分析模型"
                hint={
                  aiModels?.ok
                    ? `网关共 ${((aiModels.cn || []).length + (aiModels.global || []).length)} 个模型（国内 ${(aiModels.cn || []).length} · 国际 ${(aiModels.global || []).length}）`
                    : '网关不可达：请先运行 aistart.bat 启动 AI 服务'
                }
              >
                <Select
                  value={aiCfg.model}
                  onChange={(e) => setAiCfg((c: any) => ({ ...c, model: e.target.value }))}
                >
                  {(aiModels?.cn || []).length > 0 && (
                    <optgroup label={`国内模型（${(aiModels.cn || []).length}）`}>
                      {aiModels.cn.map((m: string) => (
                        <option key={m} value={m}>
                          {m}
                        </option>
                      ))}
                    </optgroup>
                  )}
                  {(aiModels?.global || []).length > 0 && (
                    <optgroup label={`国际模型（${(aiModels.global || []).length}）`}>
                      {aiModels.global.map((m: string) => (
                        <option key={m} value={m}>
                          {m}
                        </option>
                      ))}
                    </optgroup>
                  )}
                  {aiCfg.model && !(aiModels?.cn || []).includes(aiCfg.model) && !(aiModels?.global || []).includes(aiCfg.model) && (
                    <option value={aiCfg.model}>{aiCfg.model}（当前，网关清单中未返回）</option>
                  )}
                </Select>
              </Field>

              {aiModels?.ok === false && (
                <Alert tone="danger" title="网关不可达">
                  {aiModels?.error || '未知错误'} —— 请确认已运行 IBKR 目录下的 aistart.bat（或 wbm.sh start）。
                </Alert>
              )}
              {aiModels?.ok && (aiModels?.global || []).length === 0 && (
                <Alert tone="info" title="没有看到国际模型？">
                  网关按密钥的版本归属过滤清单。到 WorkBuddy 面板（127.0.0.1:16689）「密钥」页，把当前密钥的版本改为「不限定」，即可解锁全部国际模型。
                </Alert>
              )}

              <div className="grid gap-3 sm:grid-cols-2">
                <Field label="网关地址（OpenAI 兼容）" hint="仅允许本机回环地址">
                  <Input
                    value={aiCfg.base_url || ''}
                    onChange={(e) => setAiCfg((c: any) => ({ ...c, base_url: e.target.value }))}
                    placeholder="http://127.0.0.1:16689"
                  />
                </Field>
                <Field label="网关密钥" hint={aiCfg.api_key ? `当前：${aiCfg.api_key}（留空 = 保持不变）` : '面板「密钥」页签发的 wbk_ 密钥'}>
                  <Input
                    type="password"
                    value={aiKeyInput}
                    onChange={(e) => setAiKeyInput(e.target.value)}
                    placeholder={aiCfg.api_key ? '留空保持现有密钥' : 'wbk_...'}
                  />
                </Field>
              </div>

              <div className="flex flex-wrap items-center gap-3">
                <Button onClick={saveAi} disabled={aiSaving}>
                  <Save className="h-4 w-4" />
                  {aiSaving ? '保存中…' : '保存 AI 配置'}
                </Button>
                <Button variant="secondary" onClick={testAi} disabled={aiTesting}>
                  <Unplug className="h-4 w-4" />
                  {aiTesting ? '测试中…' : '测试连通（真实调用一次）'}
                </Button>
              </div>
            </div>
          </Card>

          <Card title="说明" subtitle="这条链路走的是什么">
            <div className="space-y-3 text-sm opacity-80">
              <p>
                保存后，平台<strong className="font-medium">所有 AI 功能</strong>都会走这里配置的网关：
                AI 研判、AI Copilot，以及散落在各页的 AI 助手卡片（行情页个股快评与新闻要点、
                榜单候选池点评、回测诊断、寻优解读、风控体检、组合点评、订单诊断、情报解读、盘面简报）。
                额度来自 WorkBuddy 账号池，按调用计费，在面板「调用日志」里逐条可查。
              </p>
              <p>
                未配置网关时不会报错：每个 AI 助手都会退回<span className="font-medium">确定性的本地规则兜底</span>，
                页面照常可用，只是少了自然语言深度解读。
              </p>
              <p>
                单次分析也可以临时换模型：AI 页的「模型」下拉（仅本次生效）；
                这里改的是全局默认。
              </p>
              <p>
                Claude Code 编码助手用的是另一份配置
                （.claude/settings.local.json），与本卡互不影响。
              </p>
            </div>
          </Card>
        </div>
      )}

      {/* ============ 安全 ============ */}
      {tab === 'security' && (
        <div className="grid gap-5 xl:grid-cols-3">
          <Card className="xl:col-span-2" title="实盘交易三重锁" subtitle="三道锁全部打开才可能下出实盘单">
            <div className="space-y-4">
              {[
                {
                  n: '①',
                  title: '环境变量开关',
                  on: status?.live_env_gate,
                  desc: '需要在后端启动前设置 QD_ALLOW_LIVE_TRADING=true。这是编译期级别的硬闸门，防止误配置。',
                  fix: '在 backend/runtime/.env 写入 QD_ALLOW_LIVE_TRADING=true 后重启服务',
                },
                {
                  n: '②',
                  title: '运行时解锁',
                  on: status?.live_unlocked,
                  desc: '在「实盘交易」页面逐字输入确认短语 I UNDERSTAND THE RISK 并输入账户口令，才能解锁。',
                  fix: '前往「实盘交易」页面点击「解锁实盘」',
                },
                {
                  n: '③',
                  title: '逐笔风控护栏',
                  on: true,
                  desc: '每一笔订单都要通过单标的限额、总敞口、日亏上限、回撤熔断、白黑名单、交易时段等全部检查。',
                  fix: '',
                },
              ].map((l) => (
                <div
                  key={l.n}
                  className={`flex items-start gap-3 rounded-lg border p-3.5 ${
                    l.on ? 'border-emerald-200 bg-emerald-50/50' : 'border-slate-200 bg-slate-50'
                  }`}
                >
                  <span className={`text-xl font-bold ${l.on ? 'text-emerald-600' : 'text-slate-300'}`}>{l.n}</span>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-medium text-slate-800">{l.title}</span>
                      {l.on ? (
                        <Badge tone="green">
                          <CheckCircle2 className="mr-0.5 h-3 w-3" />
                          已开启
                        </Badge>
                      ) : (
                        <Badge tone="slate">
                          <XCircle className="mr-0.5 h-3 w-3" />
                          未开启
                        </Badge>
                      )}
                    </div>
                    <p className="mt-1 text-xs leading-relaxed text-slate-500">{l.desc}</p>
                    {!l.on && l.fix && <p className="mt-1.5 text-[11px] text-brand-600">如何开启：{l.fix}</p>}
                  </div>
                </div>
              ))}

              <Alert tone={status?.live_ready ? 'danger' : 'success'} title={status?.live_ready ? '⚠️ 实盘通道当前已就绪' : '🛡️ 实盘通道当前已锁定'}>
                {status?.live_reason}
              </Alert>

              <div className="flex gap-2">
                <Link to="/trading">
                  <Button variant="primary" icon={<Lock className="h-3.5 w-3.5" />}>
                    前往实盘交易页管理解锁
                  </Button>
                </Link>
                <Link to="/risk">
                  <Button icon={<ShieldCheck className="h-3.5 w-3.5" />}>复核风控限额</Button>
                </Link>
              </div>
            </div>
          </Card>

          <div className="space-y-5">
            <Card title="账户安全">
              <div className="space-y-3">
                <div className="flex items-center justify-between border-b border-dashed border-slate-100 pb-2">
                  <span className="text-xs text-slate-500">登录账户</span>
                  <span className="flex items-center gap-2 text-sm font-medium text-slate-700">
                    {getUser() || '—'}
                    <Badge tone="green">已认证</Badge>
                  </span>
                </div>
                <p className="text-xs text-slate-500">
                  口令使用 bcrypt（cost=12）加盐哈希存储，服务端无法还原明文。会话使用 JWT 放在
                  Authorization 头中，不使用 Cookie，因此天然免疫 CSRF。
                </p>
                <Button onClick={() => setPwdOpen(true)} icon={<KeyRound className="h-3.5 w-3.5" />}>
                  修改口令
                </Button>
              </div>
            </Card>

            <Card title="服务安全基线">
              <div className="space-y-2 text-xs text-slate-600">
                {[
                  ['仅监听本机回环地址', status ? `未暴露（${status.broker_host}）` : '—'],
                  ['会话令牌有效期', '12 小时'],
                  ['登录失败锁定', '8 次 / 5 分钟'],
                  ['请求体大小限制', '4 MB'],
                  ['安全响应头', '已启用'],
                  ['凭据加密', 'Fernet (AES-128-CBC + HMAC)'],
                  ['审计留痕', `${audit?.audit_total ?? 0} 条记录`],
                ].map(([k, v]) => (
                  <div key={k} className="flex items-center justify-between border-b border-dashed border-slate-100 pb-1.5">
                    <span className="text-slate-500">{k}</span>
                    <span className="font-medium text-slate-700">{v}</span>
                  </div>
                ))}
              </div>
            </Card>
          </div>
        </div>
      )}

      {/* ============ 数据 ============ */}
      {tab === 'data' && (
        <div className="grid gap-5 xl:grid-cols-3">
          <Card className="xl:col-span-2" title="行情数据源" subtitle="三级自动降级，保证永远有数据可用">
            {/* 数据源偏好 + 降级链 + 源健康状态：全部字段来自后端 /market/data-source，
                避免前端硬编码链（曾漏掉 TwelveData，用户在设置页看不到自己配的源） */}
            <DataSourcePanel info={dsInfo} onChanged={load} />

            <div className="mt-5 grid grid-cols-2 gap-4 border-t border-slate-100 pt-4 sm:grid-cols-3">
              <Stat label="缓存文件" value={String(catalog?.cache?.files ?? 0)} icon={<Database className="h-4 w-4" />} />
              <Stat label="缓存体积" value={`${(((catalog?.cache?.bytes ?? 0) / 1024 / 1024) || 0).toFixed(2)} MB`} />
              <Stat label="支持周期" value={String(catalog?.intervals?.length ?? 0)} />
            </div>

            <div className="mt-4 flex flex-wrap gap-2">
              <Button
                onClick={async () => {
                  const r = await api.post<any>('/market/cache/clear')
                  toast('success', `已清理 ${r.removed} 个缓存文件`)
                  load()
                }}
                icon={<Trash2 className="h-3.5 w-3.5" />}
              >
                清理行情缓存
              </Button>
              <Button onClick={load} icon={<RefreshCw className="h-3.5 w-3.5" />}>
                刷新统计
              </Button>
            </div>
            <p className="mt-2 text-[11px] text-slate-400">缓存目录：{catalog?.cache?.dir}</p>
          </Card>

          {/* TwelveData 多 Key 轮询池（自包含组件；本文件已超 900 行硬上限，只做一行挂载） */}
          <TwelveDataKeys />

          <Card title="审计概览">
            {audit ? (
              <div className="space-y-3">
                <div className="grid grid-cols-2 gap-3">
                  <Stat label="审计记录" value={String(audit.audit_total)} />
                  <Stat label="订单总数" value={String(audit.orders_total)} />
                  <Stat label="实盘订单" value={String(audit.live_orders)} tone={audit.live_orders > 0 ? 'up' : 'neutral'} />
                  <Stat label="回测次数" value={String(audit.backtests)} />
                </div>
                <div className="border-t border-slate-100 pt-3">
                  <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-400">按级别分布</div>
                  {Object.entries(audit.audit_by_level || {}).map(([k, v]) => (
                    <div key={k} className="flex items-center justify-between border-b border-dashed border-slate-100 pb-1.5">
                      <Badge tone={k === 'CRITICAL' ? 'red' : k === 'WARN' ? 'amber' : 'slate'}>{k}</Badge>
                      <span className="num text-sm font-medium text-slate-700">{v as number}</span>
                    </div>
                  ))}
                </div>
                {audit.live_orders > 0 && (
                  <Alert tone="warn" title="存在实盘订单记录">
                    已有 {audit.live_orders} 笔订单以实盘模式提交。请前往「持仓组合」核对。
                  </Alert>
                )}
              </div>
            ) : (
              <Loading />
            )}
          </Card>
        </div>
      )}

      {/* ============ 界面 ============ */}
      {tab === 'ui' && (
        <div className="grid gap-5 xl:grid-cols-2">
          <Card title={<span className="flex items-center gap-2"><Palette className="h-4 w-4" />涨跌配色</span>} subtitle="影响所有价格、盈亏与热力图的颜色语义">
            <div className="grid gap-3 sm:grid-cols-2">
              <button
                onClick={() => switchColor('cn')}
                className={`rounded-xl border p-4 text-left transition-all ${
                  colorMode === 'cn' ? 'border-brand-400 bg-brand-50 ring-1 ring-brand-300' : 'border-slate-200 hover:bg-slate-50'
                }`}
              >
                <div className="flex items-center justify-between">
                  <span className="text-sm font-medium text-slate-800">中国习惯</span>
                  {colorMode === 'cn' && <CheckCircle2 className="h-4 w-4 text-brand-600" />}
                </div>
                <p className="mt-1 text-xs text-slate-500">涨 = 红，跌 = 绿（A 股、港股惯例）</p>
                <div className="mt-3 flex gap-2">
                  <span className="rounded px-2 py-1 text-xs font-medium text-white" style={{ background: '#e11d48' }}>
                    +2.35%
                  </span>
                  <span className="rounded px-2 py-1 text-xs font-medium text-white" style={{ background: '#059669' }}>
                    -1.12%
                  </span>
                </div>
              </button>

              <button
                onClick={() => switchColor('us')}
                className={`rounded-xl border p-4 text-left transition-all ${
                  colorMode === 'us' ? 'border-brand-400 bg-brand-50 ring-1 ring-brand-300' : 'border-slate-200 hover:bg-slate-50'
                }`}
              >
                <div className="flex items-center justify-between">
                  <span className="text-sm font-medium text-slate-800">欧美习惯</span>
                  {colorMode === 'us' && <CheckCircle2 className="h-4 w-4 text-brand-600" />}
                </div>
                <p className="mt-1 text-xs text-slate-500">涨 = 绿，跌 = 红（美股惯例）</p>
                <div className="mt-3 flex gap-2">
                  <span className="rounded px-2 py-1 text-xs font-medium text-white" style={{ background: '#059669' }}>
                    +2.35%
                  </span>
                  <span className="rounded px-2 py-1 text-xs font-medium text-white" style={{ background: '#e11d48' }}>
                    -1.12%
                  </span>
                </div>
              </button>
            </div>
            <Alert tone="info" className="mt-4">
              默认使用中国习惯（红涨绿跌）。切换后立即生效，并保存在浏览器本地。
            </Alert>
          </Card>

          <Card title="界面说明">
            <ul className="space-y-3 text-xs text-slate-600">
              <li className="flex gap-2">
                <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-emerald-500" />
                <span>所有数字使用等宽字体与表格数字特性（tabular-nums），便于纵向对齐比较。</span>
              </li>
              <li className="flex gap-2">
                <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-emerald-500" />
                <span>实时行情通过 WebSocket 推送，断开时会自动降级为轮询，界面右上角有连接状态提示。</span>
              </li>
              <li className="flex gap-2">
                <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-emerald-500" />
                <span>危险操作（下单、解锁实盘、解除熔断）均需二次确认。</span>
              </li>
              <li className="flex gap-2">
                <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0 text-emerald-500" />
                <span>数据来源为「合成行情」时，界面顶部会显示醒目的黄色警告条。</span>
              </li>
            </ul>
          </Card>
        </div>
      )}

      {/* ============ 系统信息 ============ */}
      {tab === 'about' && (
        <div className="grid gap-5 xl:grid-cols-3">
          <Card className="xl:col-span-2" title="系统状态">
            {status ? (
              <div className="grid gap-3 sm:grid-cols-2">
                {[
                  ['应用名称', status.app],
                  ['版本', status.version],
                  ['当前模式', status.mode === 'live' ? '实盘' : '模拟盘'],
                  ['券商', status.broker],
                  ['券商地址', status.broker_host],
                  ['只读模式', status.readonly ? '是' : '否'],
                  ['内置策略数', String(status.strategies)],
                  ['熔断开关', status.kill_switch ? '已启用' : '正常'],
                  ['实盘环境开关', status.live_env_gate ? '已开启' : '已关闭'],
                  ['实盘解锁', status.live_unlocked ? '已解锁' : '已锁定'],
                  ['AI 引擎', status.ai_configured ? 'LLM + 本地' : '本地量化引擎'],
                  ['服务端时间', status.server_time?.replace('T', ' ').slice(0, 19) || '—'],
                ].map(([k, v]) => (
                  <div key={k} className="flex items-center justify-between border-b border-dashed border-slate-100 pb-1.5">
                    <span className="text-xs text-slate-500">{k}</span>
                    <span className="num text-sm font-medium text-slate-700">{v}</span>
                  </div>
                ))}
              </div>
            ) : (
              <Loading />
            )}
            <p className="mt-4 text-[11px] text-slate-400">运行目录：{status?.runtime_dir}</p>
          </Card>

          <Card title="关于 QuantDesk">
            <div className="space-y-3 text-xs leading-relaxed text-slate-600">
              <p>
                QuantDesk 是一个面向 Interactive Brokers 的本地化 AI 量化交易平台，覆盖
                <span className="font-medium">策略研究 → 回测验证 → 风险控制 → 模拟演练 → 实盘执行</span> 的完整闭环。
              </p>
              <p>
                内置 28 个策略（趋势动量 / 均值回归 / 进阶前沿 / 日内微观），支持参数化自定义、可视化规则编辑与
                AST 沙箱保护的 Python 代码策略。
              </p>
              <p>
                回测引擎采用事件驱动逐 bar 撮合：第 t 根 bar 收盘生成的信号只在第 t+1 根开盘成交，
                并计入双边佣金与不利滑点，止损判定使用 bar 内极值 —— 尽可能贴近真实交易。
              </p>
              <div className="flex flex-wrap gap-2 pt-1">
                <a href="/api/docs" target="_blank" rel="noreferrer">
                  <Button size="sm" icon={<ExternalLink className="h-3.5 w-3.5" />}>
                    API 文档
                  </Button>
                </a>
              </div>
            </div>
          </Card>
        </div>
      )}

      {/* 修改口令 */}
      <Modal
        open={pwdOpen}
        onClose={() => setPwdOpen(false)}
        title="修改账户口令"
        footer={
          <>
            <Button onClick={() => setPwdOpen(false)}>取消</Button>
            <Button variant="primary" onClick={changePwd} disabled={!curPwd || !newPwd}>
              确认修改
            </Button>
          </>
        }
      >
        <div className="space-y-3">
          <Field label="当前口令">
            <Input type="password" value={curPwd} onChange={(e) => setCurPwd(e.target.value)} autoComplete="current-password" />
          </Field>
          <Field label="新口令" hint="至少 10 位，包含大写、小写、数字、符号中的至少三类">
            <Input type="password" value={newPwd} onChange={(e) => setNewPwd(e.target.value)} autoComplete="new-password" />
          </Field>
          <Field label="确认新口令">
            <Input type="password" value={confirmPwd} onChange={(e) => setConfirmPwd(e.target.value)} autoComplete="new-password" />
          </Field>
        </div>
      </Modal>
    </div>
  )
}
