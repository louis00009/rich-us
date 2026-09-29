/**
 * 全局连接状态（顶栏常驻）
 * ========================
 * 放在顶栏「模拟盘 / IBKR 127.0.0.1:7497」旁边，一眼看到两条外部链路是否通：
 *   · 券商 TWS / IB Gateway（下单与行情通道）
 *   · AI 网关（系统设置 → AI 分析 里配置的那个）
 *
 * 三态配色：**绿=通 / 红=有问题 / 灰=不适用**（内置模拟券商、AI 未配置）。
 * 点开面板可对每一条单独「重试连接」—— 券商走真正的握手（/system/broker/test），
 * AI 走重新探测网关（/system/links?refresh=1，跳过 60s 缓存）。
 *
 * ⚠️ 两个坑（改这个文件前先看）：
 *  1. 顶栏带 `backdrop-blur` —— **`position:fixed` 的覆盖层会被它当成包含块**，
 *     所以这里**不用** `fixed inset-0` 做遮罩，改用 document 上的 mousedown 关闭。
 *  2. 轮询只做**只读探活**，绝不顺手发起 TWS 连接（握手占 client_id 且可能弹窗），
 *     连接动作只在用户点「重试连接」时才发生。
 */
import clsx from 'clsx'
import { Loader2, RefreshCw, Settings2 } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../lib/api'
import { Button, useToast } from './ui'

/** ok=通 / error=有问题 / na=不适用（未启用或未配置） */
type LinkState = 'ok' | 'error' | 'na'

/** 展示用：一条链路的状态 + 明细 */
interface LinkInfo {
  state: LinkState
  label: string
  detail: string
  error?: string
  /** 附加信息行（账户/模型/地址…） */
  facts?: [string, string][]
}

/** GET /api/system/links 的原始返回（后端 app/api/system.py::links） */
interface RawBroker {
  provider: string
  host: string
  port: number
  label: string
  mode: string
  state: LinkState
  connected: boolean
  account: string
  client_id: number | null
  market_data_label: string
  detail: string
  error: string
}
interface RawAi {
  configured: boolean
  model: string
  base_url: string
  models: number
  state: LinkState
  detail: string
  error: string
}
interface LinksResp {
  broker: RawBroker
  ai: RawAi
  checked_at?: string
}

/** 原始返回 → 展示模型（把字段拼成「地址/模式/账户」这类明细行）。 */
function toBrokerInfo(b: RawBroker): LinkInfo {
  const facts: [string, string][] = [['通道', b.provider === 'ibkr' ? `${b.host}:${b.port}` : '内置']]
  if (b.provider === 'ibkr') facts.push(['模式', b.mode === 'live' ? '实盘端口' : '纸面'])
  if (b.account) facts.push(['账户', b.account])
  if (b.market_data_label) facts.push(['行情', b.market_data_label])
  if (b.client_id != null && b.provider === 'ibkr') facts.push(['client_id', String(b.client_id)])
  return { state: b.state, label: b.label, detail: b.detail, error: b.error, facts }
}

function toAiInfo(a: RawAi): LinkInfo {
  const facts: [string, string][] = [['地址', a.base_url || '—']]
  facts.push(['模型', a.model || '—'])
  if (a.state === 'ok') facts.push(['可选模型', `${a.models} 个`])
  return { state: a.state, label: 'AI 网关', detail: a.detail, error: a.error, facts }
}

const DOT: Record<LinkState, string> = {
  ok: 'bg-emerald-500',
  error: 'bg-rose-500',
  na: 'bg-slate-300',
}
const TEXT: Record<LinkState, string> = {
  ok: 'text-emerald-700',
  error: 'text-rose-700',
  na: 'text-slate-500',
}
const STATE_LABEL: Record<LinkState, string> = { ok: '正常', error: '异常', na: '未启用' }
const CHIP_TONE: Record<LinkState, string> = {
  ok: 'border-emerald-200 bg-emerald-50 hover:bg-emerald-100',
  error: 'border-rose-200 bg-rose-50 hover:bg-rose-100',
  na: 'border-slate-200 bg-white hover:bg-slate-50',
}

export default function LinkStatus() {
  const toast = useToast()
  const nav = useNavigate()
  const [data, setData] = useState<LinksResp | null>(null)
  const [open, setOpen] = useState(false)
  const [busy, setBusy] = useState<'broker' | 'ai' | ''>('')

  const load = useCallback(async (refresh = false) => {
    try {
      const r = await api.get<LinksResp>(`/system/links${refresh ? '?refresh=1' : ''}`)
      setData(r)
      return r
    } catch {
      return null // 顶栏不打扰用户：拿不到就保持上一次的状态
    }
  }, [])

  useEffect(() => {
    load()
    const t = setInterval(() => load(), 30_000)
    return () => clearInterval(t)
  }, [load])

  // 点面板外关闭（见文件头坑 ①：不能用 fixed 遮罩）
  useEffect(() => {
    if (!open) return
    const onDown = (e: MouseEvent) => {
      const el = e.target as HTMLElement | null
      if (!el?.closest?.('[data-linkstatus]')) setOpen(false)
    }
    document.addEventListener('mousedown', onDown)
    return () => document.removeEventListener('mousedown', onDown)
  }, [open])

  /** 重试：券商会真的握手一次（慢，给 60s）；AI 只是重新探网关（快）。 */
  const retry = async (which: 'broker' | 'ai') => {
    if (busy) return
    setBusy(which)
    try {
      if (which === 'broker') {
        const r = await api.post<any>('/system/broker/test', undefined, 60_000)
        toast(r?.ok ? 'success' : 'error', r?.message || (r?.ok ? '券商连接正常' : '券商连接失败'))
      } else {
        const r = await load(true)
        if (!r) toast('error', '读取 AI 状态失败')
        else if (r.ai.state === 'ok') toast('success', `AI 网关已连通：${r.ai.model || '默认模型'}`)
        else if (r.ai.state === 'na') toast('warning', '尚未配置 AI 网关，当前走本地规则兜底')
        else toast('error', r.ai.detail || 'AI 网关不可达')
      }
    } catch (e: any) {
      toast('error', e?.message || '重试失败')
    } finally {
      setBusy('')
    }
  }

  const broker: LinkInfo | null = data ? toBrokerInfo(data.broker) : null
  const ai: LinkInfo | null = data ? toAiInfo(data.ai) : null
  const checked = data?.checked_at ? new Date(data.checked_at).toLocaleTimeString('zh-CN', { hour12: false }) : ''

  const brokerChip = data?.broker.provider === 'ibkr' && data.broker.port ? `TWS ${data.broker.port}` : 'TWS'

  return (
    <div className="relative hidden sm:block" data-linkstatus>
      <div className="flex items-center gap-1">
        <Chip
          state={broker?.state ?? 'na'}
          label={brokerChip}
          title={broker ? `券商链路：${STATE_LABEL[broker.state]} · ${broker.detail}` : '正在读取券商状态…'}
          onClick={() => setOpen((v) => !v)}
          active={open}
        />
        <Chip
          state={ai?.state ?? 'na'}
          label="AI"
          title={ai ? `AI 网关：${STATE_LABEL[ai.state]} · ${ai.detail}` : '正在读取 AI 状态…'}
          onClick={() => setOpen((v) => !v)}
          active={open}
        />
      </div>

      {open && (
        <div className="absolute right-0 top-full z-30 mt-1.5 w-[21rem] rounded-lg border border-slate-200 bg-white p-3 shadow-pop">
          <div className="mb-2 flex items-center justify-between">
            <span className="text-xs font-semibold text-slate-700">连接状态</span>
            <span className="text-[10px] text-slate-400">{checked ? `${checked} 探测` : '点击芯片查看详情'}</span>
          </div>

          <div className="space-y-2">
            <Row
              name={broker?.label || '券商通道'}
              info={broker}
              busy={busy === 'broker'}
              onRetry={() => retry('broker')}
              retryText="重试连接"
            />
            <Row
              name="AI 网关"
              info={ai}
              busy={busy === 'ai'}
              onRetry={() => retry('ai')}
              retryText="重试连接"
            />
          </div>

          <div className="mt-2.5 flex items-center justify-between border-t border-slate-100 pt-2">
            <button
              className="flex items-center gap-1 text-[11px] text-brand-600 hover:underline"
              onClick={() => {
                setOpen(false)
                nav('/settings')
              }}
            >
              <Settings2 className="h-3 w-3" />
              去系统设置
            </button>
            <span className="text-[10px] text-slate-400">每 30 秒自动探测</span>
          </div>
        </div>
      )}
    </div>
  )
}

function Chip({
  state,
  label,
  title,
  onClick,
  active,
}: {
  state: LinkState
  label: string
  title: string
  onClick: () => void
  active?: boolean
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      title={title}
      className={clsx(
        'flex items-center gap-1.5 rounded-lg border px-2 py-1 text-[11px] font-medium transition-colors',
        CHIP_TONE[state],
        active && 'ring-2 ring-brand-500/30',
      )}
    >
      <span className={clsx('h-1.5 w-1.5 rounded-full', DOT[state], state === 'ok' && 'animate-pulse')} />
      <span className={TEXT[state]}>{label}</span>
    </button>
  )
}

function Row({
  name,
  info,
  busy,
  onRetry,
  retryText,
}: {
  name: string
  info: LinkInfo | null
  busy: boolean
  onRetry: () => void
  retryText: string
}) {
  const state: LinkState = info?.state ?? 'na'
  return (
    <div className="rounded-lg border border-slate-100 p-2.5">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="flex items-center gap-1.5">
            <span className={clsx('h-1.5 w-1.5 shrink-0 rounded-full', DOT[state])} />
            <span className="truncate text-xs font-medium text-slate-700">{name}</span>
            <span className={clsx('shrink-0 text-[10px]', TEXT[state])}>{STATE_LABEL[state]}</span>
          </div>
          <p className="mt-1 break-words text-[11px] leading-relaxed text-slate-500">
            {info?.detail ?? '正在读取…'}
          </p>
        </div>
        <Button
          size="sm"
          variant={state === 'ok' ? 'secondary' : 'primary'}
          loading={busy}
          disabled={busy}
          icon={busy ? undefined : <RefreshCw className="h-3 w-3" />}
          onClick={onRetry}
          className="shrink-0"
        >
          {busy ? '重试中' : retryText}
        </Button>
      </div>

      {!!info?.facts?.length && (
        <dl className="mt-1.5 space-y-0.5 border-t border-dashed border-slate-100 pt-1.5">
          {info.facts.map(([k, v]) => (
            <div key={k} className="flex items-baseline justify-between gap-2 text-[10px]">
              <dt className="shrink-0 text-slate-400">{k}</dt>
              <dd className="truncate text-slate-600">{v}</dd>
            </div>
          ))}
        </dl>
      )}

      {state === 'error' && info?.error && (
        <p className="mt-1.5 break-words rounded bg-rose-50 px-1.5 py-1 text-[10px] leading-relaxed text-rose-600">
          {info.error}
        </p>
      )}

      {busy && <Loader2 className="mt-1.5 h-3 w-3 animate-spin text-slate-400" />}
    </div>
  )
}
