// AI Copilot 的「追问」对话面板（FILE_SIZE_DEBT Batch C-2 拆分）
// 聊天状态自包含：只依赖外层的标的列表（作为上下文传入后端）。
import { MessageSquare, Send } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { Button, Card, Input, Loading } from '../ui'
import { api } from '../../lib/api'

export function ChatPanel({ symbols }: { symbols: string }) {
  const [chatInput, setChatInput] = useState('')
  const [chat, setChat] = useState<{ role: string; content: string }[]>([])
  const [chatLoading, setChatLoading] = useState(false)
  const chatEnd = useRef<HTMLDivElement>(null)

  useEffect(() => {
    chatEnd.current?.scrollIntoView({ behavior: 'smooth' })
  }, [chat])

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

  return (
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
  )
}
