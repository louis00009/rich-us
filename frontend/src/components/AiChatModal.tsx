import { MessageSquare, Send, Trash2, X } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { Spinner } from './ui'
import { api } from '../lib/api'

/**
 * AI 对话弹窗（多轮）—— 看到哪几只票，勾选后直接在弹窗里提问。
 *
 * 后端：POST /api/ai/chat（message + context_symbols + history[-8:] + model），
 * 与 AI Copilot 页共用同一端点；模型名解析与「设置 → AI 分析」同源
 * （QD_AI_EXTRA_MODELS 别名 / 网关模型 id / 默认全局模型）。
 * LLM 失败时后端自动降级本地量化引擎（engine="local"），前端据实标注。
 *
 * ⚠️ AI 回复是研究辅助，不是交易建议；关键数字请以页面行情与官方披露为准。
 */

export interface ChatMsg {
  role: 'user' | 'assistant'
  content: string
  engine?: string
}

interface AiStatus {
  llm_configured?: boolean
  model?: string
  extra_models?: string[]
  models_by_realm?: { cn?: string[]; global?: string[] }
}

export default function AiChatModal({
  open,
  onClose,
  symbols = [],
  contextLabel,
}: {
  open: boolean
  onClose: () => void
  /** 上下文标的（勾选的股票）：随每轮请求带给后端做量化快照注入 */
  symbols?: string[]
  contextLabel?: string
}) {
  const [messages, setMessages] = useState<ChatMsg[]>([])
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [model, setModel] = useState(() => localStorage.getItem('qd_chat_model') || '')
  const [aiStatus, setAiStatus] = useState<AiStatus | null>(null)
  const scrollRef = useRef<HTMLDivElement>(null)

  // 打开时拉一次模型清单（与设置页 / AI Copilot 同源）
  useEffect(() => {
    if (!open) return
    api.get<AiStatus>('/ai/status', 15_000).then(setAiStatus).catch(() => setAiStatus(null))
  }, [open])

  // 新消息自动滚到底
  useEffect(() => {
    if (open) scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: 'smooth' })
  }, [messages, busy, open])

  // ESC 关闭
  useEffect(() => {
    if (!open) return undefined
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [open, onClose])

  if (!open) return null

  const send = async () => {
    const text = input.trim()
    if (!text || busy) return
    const history = messages.map((m) => ({ role: m.role, content: m.content }))
    setMessages((p) => [...p, { role: 'user', content: text }])
    setInput('')
    setBusy(true)
    setError('')
    try {
      const r = await api.post<{ reply: string; engine: string; llm_error?: string }>(
        '/ai/chat',
        { message: text, context_symbols: symbols.slice(0, 6), history, model },
        180_000,
      )
      setMessages((p) => [...p, { role: 'assistant', content: r.reply || '（模型返回为空）', engine: r.engine }])
      if (r.llm_error) setError(`模型调用失败，已降级本地引擎：${r.llm_error}`)
    } catch (e: any) {
      const msg = e?.message || '请求失败'
      setError(msg)
      setMessages((p) => [...p, { role: 'assistant', content: `⚠ 请求失败：${msg}`, engine: 'error' }])
    } finally {
      setBusy(false)
    }
  }

  const extraModels = aiStatus?.extra_models ?? []
  const cnModels = aiStatus?.models_by_realm?.cn ?? []
  const globalModels = aiStatus?.models_by_realm?.global ?? []

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4" role="dialog" aria-modal="true">
      {/* 遮罩 */}
      <div className="absolute inset-0 bg-slate-900/40 backdrop-blur-sm" onClick={onClose} />
      {/* 弹窗卡片 */}
      <div className="relative flex h-[min(680px,88vh)] w-full max-w-2xl flex-col overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-2xl">
        {/* 头部 */}
        <div className="flex flex-wrap items-center gap-2 border-b border-slate-100 px-4 py-2.5">
          <MessageSquare className="h-4 w-4 text-brand-600" />
          <span className="text-sm font-semibold text-slate-800">AI 对话</span>
          {symbols.length > 0 && (
            <span className="max-w-56 truncate rounded bg-brand-50 px-1.5 py-0.5 text-[10px] font-medium text-brand-700" title={symbols.join('、')}>
              上下文：{symbols.join('、')}
            </span>
          )}
          {contextLabel && <span className="hidden text-[10px] text-slate-400 sm:inline">{contextLabel}</span>}
          <div className="ml-auto flex items-center gap-1.5">
            <select
              value={model}
              onChange={(e) => {
                setModel(e.target.value)
                localStorage.setItem('qd_chat_model', e.target.value)
              }}
              className="max-w-40 rounded border border-slate-200 bg-white px-1.5 py-1 text-[11px] text-slate-700"
              title="本次对话使用的模型（与「设置 → AI 分析」同一套接入）"
            >
              <option value="">默认模型{aiStatus?.model ? `（${aiStatus.model}）` : ''}</option>
              {extraModels.length > 0 && (
                <optgroup label="别名 / 已接入">
                  {extraModels.map((m) => (
                    <option key={m} value={m}>{m}</option>
                  ))}
                </optgroup>
              )}
              {cnModels.length > 0 && (
                <optgroup label="国内">
                  {cnModels.map((m) => (
                    <option key={m} value={m}>{m}</option>
                  ))}
                </optgroup>
              )}
              {globalModels.length > 0 && (
                <optgroup label="国际">
                  {globalModels.map((m) => (
                    <option key={m} value={m}>{m}</option>
                  ))}
                </optgroup>
              )}
            </select>
            <button
              onClick={() => setMessages([])}
              disabled={messages.length === 0 || busy}
              className="rounded p-1.5 text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-600 disabled:opacity-40"
              title="清空对话（上下文历史同时清空）"
            >
              <Trash2 className="h-3.5 w-3.5" />
            </button>
            <button
              onClick={onClose}
              className="rounded p-1.5 text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-600"
              title="关闭（ESC）"
            >
              <X className="h-4 w-4" />
            </button>
          </div>
        </div>

        {/* 消息流 */}
        <div ref={scrollRef} className="flex-1 space-y-3 overflow-y-auto px-4 py-3">
          {messages.length === 0 && (
            <div className="mt-6 text-center text-[11px] leading-5 text-slate-400">
              <SparklesHint />
              <p className="mt-2">
                {symbols.length > 0
                  ? `正在围绕 ${symbols.slice(0, 6).join('、')} 提问 —— 后端会把它们的量化快照（价格 / 趋势 / RSI / 支撑阻力）注入上下文。`
                  : '输入问题开始对话；勾选榜单标的后再打开，AI 会自动带上它们的量化快照。'}
              </p>
              {!aiStatus?.llm_configured && (
                <p className="mt-2 text-slate-500">未配置 LLM：回复由本地量化引擎生成（确定性计算，无生成式解读）。</p>
              )}
            </div>
          )}
          {messages.map((m, i) => (
            <div key={i} className={`flex ${m.role === 'user' ? 'justify-end' : 'justify-start'}`}>
              <div
                className={`max-w-[86%] whitespace-pre-wrap rounded-2xl px-3 py-2 text-xs leading-5 ${
                  m.role === 'user'
                    ? 'rounded-br-sm bg-brand-600 text-white'
                    : m.engine === 'error'
                      ? 'rounded-bl-sm bg-rose-50 text-rose-700'
                      : 'rounded-bl-sm bg-slate-100 text-slate-800'
                }`}
              >
                {m.content}
                {m.role === 'assistant' && m.engine && m.engine !== 'error' && (
                  <div className="mt-1 text-right text-[9px] text-slate-400">
                    {m.engine === 'llm' ? `${model || aiStatus?.model || '默认模型'}` : '本地量化引擎'}
                  </div>
                )}
              </div>
            </div>
          ))}
          {busy && (
            <div className="flex justify-start">
              <div className="flex items-center gap-2 rounded-2xl rounded-bl-sm bg-slate-100 px-3 py-2 text-xs text-slate-500">
                <Spinner />
                思考中…
              </div>
            </div>
          )}
        </div>

        {error && (
          <p className="mx-4 mb-1 rounded bg-amber-50 px-2 py-1 text-[10px] text-amber-800">{error}</p>
        )}

        {/* 输入区 */}
        <div className="border-t border-slate-100 p-3">
          <div className="flex items-end gap-2">
            <textarea
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter' && !e.shiftKey) {
                  e.preventDefault()
                  send()
                }
              }}
              rows={2}
              placeholder="向 AI 提问…（Enter 发送，Shift+Enter 换行）"
              className="flex-1 resize-none rounded-lg border border-slate-200 px-3 py-2 text-xs text-slate-800 placeholder:text-slate-300 focus:border-brand-300 focus:outline-none"
              disabled={busy}
            />
            <button
              onClick={send}
              disabled={busy || !input.trim()}
              className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-brand-600 text-white transition-colors hover:bg-brand-700 disabled:opacity-40"
              title="发送"
            >
              {busy ? <Spinner /> : <Send className="h-4 w-4" />}
            </button>
          </div>
          <p className="mt-1.5 text-[9px] leading-3 text-slate-300">
            AI 回复是研究辅助，不是交易建议；多轮对话保留最近 8 轮上下文。
          </p>
        </div>
      </div>
    </div>
  )
}

function SparklesHint() {
  return <span className="text-2xl">💬</span>
}
