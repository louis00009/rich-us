/**
 * AIAssist —— 可复用的 AI 助手卡片
 * ================================
 * 平台里**每一个** AI 接入点都用它，从而保证：
 *   · 交互一致：同一个按钮样式、同一套加载 / 失败 / 重试 / 复制体验；
 *   · 状态一致：都显示「LLM 生成 / 本地规则兜底」以及实际使用的模型；
 *   · 降级一致：未配置 LLM 时展示规则化结论 + 一句去设置页配置的引导，
 *     而不是空白或报错。
 *
 * 三种形态：
 *   panel  卡片块（嵌在页面栅格里，最常用）
 *   inline 工具条按钮 + 展开结果（嵌在 Card actions / 筛选栏里）
 *   modal  按钮触发弹窗（适合空间紧张、结果较长的场景）
 *
 * 用法：
 *   <AIAssist task="backtest_diagnose" title="AI 回测诊断"
 *             payload={{ strategy, symbols, metrics }} runKey={String(result?.id)} />
 */
import { AlertTriangle, Copy, RefreshCw, Sparkles } from 'lucide-react'
import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { aiAssist, getAiStatus, type AiStatus, type AiTaskResult } from '../lib/ai'
import { Alert, Badge, Button, Card, Loading, Modal, useToast } from './ui'

export type AiAssistMode = 'panel' | 'inline' | 'modal'

interface Props {
  /** 后端 ai_tasks 里登记的任务 key */
  task: string
  /** 交给后端的原始数据（页面上的真实数据，原样带过去） */
  payload: Record<string, any>
  title?: string
  desc?: string
  /** 按钮文案 */
  label?: string
  mode?: AiAssistMode
  /** 挂载后自动跑一次 */
  autoRun?: boolean
  /** 变化即重新运行（通常是数据指纹，如回测 id、标的、筛选条件） */
  runKey?: string
  disabled?: boolean
  /** 禁用时的原因说明（直接展示给用户，避免「按钮为什么点不动」） */
  disabledHint?: string
  /** 没有结果时的占位说明 */
  emptyHint?: string
  className?: string
  onResult?: (r: AiTaskResult) => void
}

/* ==================================================================
 * 轻量 Markdown 渲染
 * LLM 返回的是 Markdown（## 小标题 / - 列表 / **强调**），
 * 直接 pre-wrap 会把标记原样显示出来。这里做一个极小的渲染器：
 * 不引入任何依赖，只覆盖模型实际会用的几种语法。
 * ================================================================== */
const BOLD_RE = /\*\*(.+?)\*\*/g

function inline(text: string, keyBase: string): ReactNode[] {
  const out: ReactNode[] = []
  let last = 0
  let m: RegExpExecArray | null
  BOLD_RE.lastIndex = 0
  while ((m = BOLD_RE.exec(text)) !== null) {
    if (m.index > last) out.push(text.slice(last, m.index))
    out.push(
      <strong key={`${keyBase}-b${m.index}`} className="font-semibold text-slate-900">
        {m[1]}
      </strong>,
    )
    last = m.index + m[0].length
  }
  if (last < text.length) out.push(text.slice(last))
  return out
}

/** 极简 Markdown 渲染（无第三方依赖）。导出以便情报中心「每日必读」复用，
 *  避免两处各写一份、样式与行为逐渐分叉。 */
export function MarkdownLite({ text }: { text: string }) {
  const lines = text.split('\n')
  return (
    <div className="space-y-1.5 text-[13px] leading-relaxed text-slate-700">
      {lines.map((raw, i) => {
        const line = raw.replace(/\s+$/, '')
        if (!line.trim()) return <div key={i} className="h-1.5" />
        if (line.startsWith('### ')) {
          return (
            <div key={i} className="pt-1 text-[12px] font-semibold text-slate-600">
              {inline(line.slice(4), `h${i}`)}
            </div>
          )
        }
        if (line.startsWith('## ')) {
          return (
            <div key={i} className="pt-2 text-[13px] font-semibold text-slate-800">
              {inline(line.slice(3), `h${i}`)}
            </div>
          )
        }
        if (line.startsWith('# ')) {
          return (
            <div key={i} className="pt-2 text-sm font-semibold text-slate-800">
              {inline(line.slice(2), `h${i}`)}
            </div>
          )
        }
        const bullet = line.match(/^\s*[-*·]\s+(.*)$/)
        if (bullet) {
          return (
            <div key={i} className="flex gap-2 pl-1">
              <span className="mt-[7px] h-1 w-1 shrink-0 rounded-full bg-slate-400" />
              <span className="min-w-0 flex-1">{inline(bullet[1], `u${i}`)}</span>
            </div>
          )
        }
        const ordered = line.match(/^\s*(\d+)[.)]\s+(.*)$/)
        if (ordered) {
          return (
            <div key={i} className="flex gap-2 pl-1">
              <span className="num shrink-0 text-slate-400">{ordered[1]}.</span>
              <span className="min-w-0 flex-1">{inline(ordered[2], `o${i}`)}</span>
            </div>
          )
        }
        return <p key={i}>{inline(line, `p${i}`)}</p>
      })}
    </div>
  )
}

/* ================================================================== */

export default function AIAssist({
  task,
  payload,
  title = 'AI 解读',
  desc,
  label = '生成 AI 解读',
  mode = 'panel',
  autoRun = false,
  runKey,
  disabled = false,
  disabledHint,
  emptyHint = '点击上方按钮，让 AI 基于当前页面的真实数据给出解读。',
  className,
  onResult,
}: Props) {
  const toast = useToast()
  const [loading, setLoading] = useState(false)
  const [res, setRes] = useState<AiTaskResult | null>(null)
  const [err, setErr] = useState('')
  const [open, setOpen] = useState(false)
  const [status, setStatus] = useState<AiStatus | null>(null)
  const seqRef = useRef(0)
  const lastKeyRef = useRef<string | undefined>(undefined)
  // payload 每次渲染都是新对象字面量，若进依赖数组会无限重跑；
  // 若只靠闭包捕获又会在 runKey 不变时拿到过期数据 —— 因此用 ref 承接最新值。
  const payloadRef = useRef(payload)
  payloadRef.current = payload

  useEffect(() => {
    getAiStatus().then(setStatus)
  }, [])

  const run = useCallback(async () => {
    if (disabled) return
    // 序号守卫：连续点击时先发的慢响应不得覆盖后发的结果
    const seq = ++seqRef.current
    setLoading(true)
    setErr('')
    try {
      const r = await aiAssist(task, payloadRef.current)
      if (seq !== seqRef.current) return
      setRes(r)
      onResult?.(r)
    } catch (e: any) {
      if (seq !== seqRef.current) return
      setErr(e?.message || 'AI 调用失败')
      setRes(null)
    } finally {
      if (seq === seqRef.current) setLoading(false)
    }
  }, [task, disabled, onResult])

  // 数据指纹变化时自动重跑（runKey 未提供则只在挂载时跑一次）
  useEffect(() => {
    if (!autoRun || disabled) return
    if (lastKeyRef.current === runKey) return
    lastKeyRef.current = runKey
    run()
  }, [autoRun, runKey, disabled, run])

  // **手动模式**下数据指纹变化 → 清空旧结果。
  // 既然不再自动跑（必须点按钮才生成），就不能让上一份结论继续挂在卡片上 ——
  // 否则切了标的 / 换了回测结果，卡片还显示**上一次**的分析，
  // 看起来像「这只已经分析过了」，比空白更误导。
  const firstKeyRef = useRef(true)
  useEffect(() => {
    if (autoRun) return
    if (firstKeyRef.current) {
      firstKeyRef.current = false
      return
    }
    seqRef.current += 1 // 让在途的慢响应作废，别把旧结果写回来
    setRes(null)
    setErr('')
    setLoading(false)
  }, [runKey, autoRun])

  const copy = async () => {
    if (!res?.text) return
    try {
      await navigator.clipboard.writeText(res.text)
      toast('success', '已复制 AI 结果')
    } catch {
      toast('error', '复制失败，请手动选择文本')
    }
  }

  const isLLM = res?.engine === 'llm'
  const localOnly = status && !status.llm_configured

  const headerActions = (
    <span className="flex flex-wrap items-center gap-2">
      {res && (
        <Badge tone={isLLM ? 'violet' : 'slate'} dot>
          {isLLM ? `LLM${status?.model ? ` · ${status.model}` : ''}` : '本地规则兜底'}
        </Badge>
      )}
      {res && (
        <Button size="sm" onClick={copy} icon={<Copy className="h-3.5 w-3.5" />} title="复制结果">
          复制
        </Button>
      )}
      <Button
        size="sm"
        variant="primary"
        loading={loading}
        disabled={disabled}
        onClick={run}
        icon={<Sparkles className="h-3.5 w-3.5" />}
        title={disabled ? disabledHint : label}
      >
        {res ? '重新生成' : label}
      </Button>
    </span>
  )

  const body = (
    <div className="space-y-3">
      {disabled && disabledHint && <Alert tone="info">{disabledHint}</Alert>}
      {localOnly && !res && (
        <Alert tone="info">
          当前使用<span className="font-medium">本地规则兜底</span>：结论由平台数据按确定性规则算出。
          到「<Link to="/settings" className="text-brand-600 hover:underline">设置 → AI 分析</Link>」配置网关后，
          这里会自动切换为大模型生成。
        </Alert>
      )}
      {loading && <Loading label="AI 正在分析当前页面的数据…" className="py-6" />}
      {!loading && err && (
        <Alert tone="danger" title="AI 调用失败">
          {err}
        </Alert>
      )}
      {!loading && !err && res && (
        <>
          {res.llm_error && (
            <Alert tone="warn" title="大模型调用失败，已降级为本地规则结论">
              {res.llm_error}
            </Alert>
          )}
          <MarkdownLite text={res.text} />
          {!isLLM && !res.llm_error && (
            <p className="border-t border-dashed border-slate-100 pt-2 text-[11px] text-slate-400">
              以上为规则化结论。到「设置 → AI 分析」配置模型后可获得自然语言深度解读。
            </p>
          )}
        </>
      )}
      {!loading && !err && !res && (
        <div className="flex items-start gap-2 rounded-lg border border-dashed border-slate-200 bg-slate-50/60 px-3 py-3 text-xs text-slate-500">
          <Sparkles className="mt-0.5 h-3.5 w-3.5 shrink-0 text-violet-400" />
          <span>{emptyHint}</span>
        </div>
      )}
      {err && (
        <Button size="sm" onClick={run} icon={<RefreshCw className="h-3.5 w-3.5" />}>
          重试
        </Button>
      )}
      {/* 诚实性铁律：AI 输出永远不是买卖信号，这句话常驻（不随结果出现/消失） */}
      <p className="flex items-start gap-1.5 text-[10.5px] leading-relaxed text-slate-400">
        <AlertTriangle className="mt-0.5 h-3 w-3 shrink-0" />
        AI 输出仅供研究参考，不构成买卖信号；一切交易动作都需经提案与人工批准。
      </p>
    </div>
  )

  if (mode === 'inline') {
    return (
      <div className={className}>
        <div className="flex flex-wrap items-center gap-2">
          <Button
            size="sm"
            variant="secondary"
            loading={loading}
            disabled={disabled}
            onClick={run}
            icon={<Sparkles className="h-3.5 w-3.5" />}
            title={disabled ? disabledHint : label}
          >
            {res ? '重新生成' : label}
          </Button>
          {res && (
            <>
              <Badge tone={isLLM ? 'violet' : 'slate'}>{isLLM ? 'LLM' : '本地规则'}</Badge>
              <button onClick={copy} className="rounded p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-600" title="复制">
                <Copy className="h-3.5 w-3.5" />
              </button>
            </>
          )}
        </div>
        {(loading || err || res) && <div className="mt-3">{body}</div>}
      </div>
    )
  }

  if (mode === 'modal') {
    return (
      <div className={className}>
        <Button
          size="sm"
          variant="secondary"
          disabled={disabled}
          onClick={() => {
            setOpen(true)
            if (!res && !loading) run()
          }}
          icon={<Sparkles className="h-3.5 w-3.5" />}
          title={disabled ? disabledHint : label}
        >
          {label}
        </Button>
        <Modal
          open={open}
          onClose={() => setOpen(false)}
          title={
            <span className="flex items-center gap-2">
              <Sparkles className="h-4 w-4 text-violet-500" />
              {title}
            </span>
          }
          width="!max-w-[860px]"
          bodyClass="max-h-[74vh] overflow-y-auto"
          footer={<Button onClick={() => setOpen(false)}>关闭</Button>}
        >
          <div className="space-y-3">
            {desc && <p className="text-xs text-slate-500">{desc}</p>}
            <div className="flex justify-end">{headerActions}</div>
            {body}
          </div>
        </Modal>
      </div>
    )
  }

  return (
    <Card
      className={className}
      title={
        <span className="flex items-center gap-2">
          <Sparkles className="h-4 w-4 text-violet-500" />
          {title}
        </span>
      }
      subtitle={desc}
      actions={headerActions}
    >
      {body}
    </Card>
  )
}
