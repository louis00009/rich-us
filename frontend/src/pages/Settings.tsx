import { CheckCircle2, Database, ExternalLink, Palette, RefreshCw, Trash2 } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import DataSourcePanel from '../components/DataSourcePanel'
import TwelveDataKeys from '../components/TwelveDataKeys'
import BrokerTab from '../components/settings/BrokerTab'
import { AiTab, SecurityTab } from '../components/settings/AiSecurityTabs'
import type { BrokerCfg } from '../components/settings/types'
import {
  Alert,
  Badge,
  Button,
  Card,
  Field,
  Input,
  Loading,
  Modal,
  Stat,
  Tabs,
  useToast,
} from '../components/ui'
import { api, getUser } from '../lib/api'
import { invalidateAiStatus } from '../lib/ai'
import { getColorMode, setColorMode, type ColorMode } from '../lib/format'
import type { SystemStatus } from '../lib/types'

/**
 * 系统设置。结构（FILE_SIZE_DEBT Batch C-3）：
 * 取数、保存/测试逻辑与口令弹窗在本文件；券商 / AI / 安全三个 tab 见
 * components/settings/。⚠️ 清单类数据（模型、preset、数据源）一律从后端取。
 */
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

  const resetSim = async () => {
    if (!confirm('确认将模拟账户重置为 $100,000？当前持仓与历史将被清空。')) return
    await api.post('/trading/sim/reset?cash=100000')
    toast('success', '模拟账户已重置')
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
        <BrokerTab
          cfg={cfg}
          presets={presets}
          guide={guide}
          testResult={testResult}
          saving={saving}
          testing={testing}
          onUpd={upd}
          onSave={save}
          onTest={test}
          onDisconnect={disconnect}
          onResetSim={resetSim}
        />
      )}

      {/* ============ AI 分析 ============ */}
      {tab === 'ai' && aiCfg && (
        <AiTab
          aiCfg={aiCfg}
          aiModels={aiModels}
          aiKeyInput={aiKeyInput}
          aiSaving={aiSaving}
          aiTesting={aiTesting}
          onAiCfg={setAiCfg}
          onKeyInput={setAiKeyInput}
          onSaveAi={saveAi}
          onTestAi={testAi}
        />
      )}

      {/* ============ 安全 ============ */}
      {tab === 'security' && (
        <SecurityTab status={status} audit={audit} onOpenPwd={() => setPwdOpen(true)} />
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

          {/* TwelveData 多 Key 轮询池（自包含组件；只做一行挂载） */}
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
