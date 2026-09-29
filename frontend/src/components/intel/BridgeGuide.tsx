/**
 * AI Agent 接入（Bridge）+ 提示词弹窗
 *
 * 从 `pages/Intel.tsx` 抽出（页面超硬上限）。用户明确要求 prompt 常驻可见，
 * 因此这张卡不做折叠；多选弹窗用于一次性复制多套提示词。
 */
import { useState } from 'react'
import { Bot, Copy } from 'lucide-react'
import { Alert, Button, Card, Empty, Modal, useToast } from '../ui'

export interface Guide {
  base_url: string
  token: string
  token_header: string
  endpoints: Record<string, string>
  prompts: Record<string, string>
  event_categories: Record<string, string>
  recommendation_options: string[]
  security_note: string
}

export const PROMPT_LABEL: Record<string, string> = {
  workbuddy: 'WorkBuddy',
  claude_code: 'Claude Code',
  codex: 'Codex',
}

export function copyText(text: string, what: string, toast: ReturnType<typeof useToast>) {
  navigator.clipboard
    .writeText(text)
    .then(() => toast('success', `${what}已复制`))
    .catch(() => toast('error', '复制失败'))
}

export default function BridgeGuide({
  guide,
  onReload,
  onResetToken,
  busy,
}: {
  guide: Guide | null
  onReload: () => void
  onResetToken: () => void
  busy: string
}) {
  const toast = useToast()
  const [promptOpen, setPromptOpen] = useState(false)
  const [sel, setSel] = useState<string[]>(['workbuddy'])

  const copy = (text: string, what: string) => copyText(text, what, toast)

  return (
    <Card
      className="shrink-0"
      title="AI Agent 接入"
      subtitle="把提示词粘给 WorkBuddy / Claude Code / Codex 即开始抓取 · Bridge 与交易账户完全隔离"
    >
      {!guide ? (
        <Empty title="指南加载中…" />
      ) : (
        <div className="space-y-3">
          <Alert tone="info">{guide.security_note}</Alert>
          <div className="grid grid-cols-1 gap-3">
            <div className="rounded-lg border border-slate-200 bg-slate-50 p-3 text-xs">
              <div className="mb-1 font-semibold text-slate-600">Bridge 地址</div>
              <code className="block break-all text-slate-700">{guide.base_url}/api/intel/bridge/*</code>
              <div className="mb-1 mt-2 font-semibold text-slate-600">
                {guide.token_header}（
                <button className="text-brand-600 hover:underline" onClick={() => copy(guide.token, 'Token')}>
                  复制
                </button>
                ）
              </div>
              <code className="block break-all text-slate-700">{guide.token.slice(0, 18)}…</code>
              <Button size="sm" variant="ghost" className="mt-2" loading={busy === 'token'} onClick={onResetToken}>
                重置 Token
              </Button>
            </div>
            <div className="flex flex-col gap-2">
              <p className="text-xs text-slate-500">点击按钮把对应 Agent 的完整提示词复制到剪贴板，或打开弹窗多选后一键复制多套。</p>
              <div className="flex flex-wrap gap-2">
                {['workbuddy', 'claude_code', 'codex'].map((k) => (
                  <Button key={k} size="sm" variant="ghost" icon={<Copy className="h-3.5 w-3.5" />} onClick={() => copy(guide.prompts[k], PROMPT_LABEL[k] + ' 提示词')}>
                    复制 {PROMPT_LABEL[k]}
                  </Button>
                ))}
                <Button size="sm" variant="primary" icon={<Bot className="h-3.5 w-3.5" />} onClick={() => setPromptOpen(true)}>
                  多选 / 预览
                </Button>
                <Button size="sm" variant="ghost" onClick={onReload}>
                  刷新指南
                </Button>
              </div>
            </div>
          </div>
        </div>
      )}

      <Modal
        open={promptOpen}
        onClose={() => setPromptOpen(false)}
        title="Agent 提示词 · 多选与一键复制"
        width="max-w-4xl"
        footer={
          <>
            <Button onClick={() => setSel(['workbuddy', 'claude_code', 'codex'])}>全选</Button>
            <Button onClick={() => setSel([])}>清空</Button>
            <Button
              variant="primary"
              icon={<Copy className="h-3.5 w-3.5" />}
              disabled={sel.length === 0 || !guide}
              onClick={() => {
                const merged = sel.map((k) => `===== ${PROMPT_LABEL[k]} =====\n\n${guide!.prompts[k] || ''}`).join('\n\n')
                copy(merged, `${sel.length} 套提示词`)
              }}
            >
              一键复制所选（{sel.length} 套）
            </Button>
          </>
        }
      >
        {!guide ? (
          <Empty title="指南加载中…" />
        ) : (
          <div className="space-y-3">
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-xs font-medium text-slate-500">选择 Agent（可多选）：</span>
              {['workbuddy', 'claude_code', 'codex'].map((k) => {
                const on = sel.includes(k)
                return (
                  <button
                    key={k}
                    onClick={() => setSel(on ? sel.filter((x) => x !== k) : [...sel, k])}
                    className={`rounded-lg border px-3 py-1.5 text-xs font-medium transition-colors ${
                      on ? 'border-brand-400 bg-brand-50 text-brand-700 ring-1 ring-brand-300' : 'border-slate-200 text-slate-600 hover:border-brand-300 hover:bg-slate-50'
                    }`}
                  >
                    {on ? '✓ ' : ''}
                    {PROMPT_LABEL[k]}
                  </button>
                )
              })}
              {guide.token && (
                <span className="ml-auto text-[11px] text-slate-400">
                  Token 已内嵌于提示词（
                  <button className="text-brand-600 hover:underline" onClick={() => copy(guide.token, 'Token')}>
                    单独复制
                  </button>
                  ）
                </span>
              )}
            </div>
            <div className="space-y-3">
              {sel.length === 0 ? (
                <Empty title="未选择任何 Agent" desc="点击上方标签选择要复制的提示词" />
              ) : (
                sel.map((k) => (
                  <div key={k} className="relative">
                    <div className="mb-1 flex items-center gap-2 text-[11px] font-semibold text-slate-600">
                      {PROMPT_LABEL[k]}
                      <button
                        className="ml-auto rounded p-1 text-slate-400 hover:bg-slate-100 hover:text-brand-600"
                        title="复制这一套"
                        onClick={() => copy(guide.prompts[k], PROMPT_LABEL[k] + ' 提示词')}
                      >
                        <Copy className="h-3 w-3" />
                      </button>
                    </div>
                    <pre className="max-h-52 overflow-y-auto whitespace-pre-wrap rounded-lg bg-slate-900 p-3 text-[11px] leading-relaxed text-slate-100">{guide.prompts[k]}</pre>
                  </div>
                ))
              )}
            </div>
          </div>
        )}
      </Modal>
    </Card>
  )
}
