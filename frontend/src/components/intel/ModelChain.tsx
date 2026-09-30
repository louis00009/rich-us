/**
 * 模型 fallback 链（UI 09-30 加）
 *
 * 用户原话：「用一个模型用完了应该换下一个、第二个降级；不应该一个模型失败
 * 就全部失败」。后端把顺序存到 `intel_settings.llm_fallback_chain`（逗号分隔），
 * 本组件做：
 *   · 显示当前顺序（带优先级编号 1/2/3…）
 *   · 上下移按钮（不引拖拽框架）
 *   · 单档删除
 *   · 添加新模型（自动从 `/ai/status` 拉候选下拉）
 *   · 每次变动 300ms 防抖调 `PUT /intel/settings` 持久化
 *
 * 为什么单档？5★ 失守时不重复 23 家全 503，**每家**按链顺序逐档试，
 * 首档可用即用；后端 `intel_digest._resolve_chain` 走的就是这个顺序。
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { ArrowDown, ArrowUp, Plus, RefreshCw, Trash2, X } from 'lucide-react'
import { Button, Select } from '../ui'
import { api } from '../../lib/api'

export function ModelChain({ chain, onChange }: { chain: string[]; onChange?: () => void }) {
  const [items, setItems] = useState<string[]>(chain)
  const [models, setModels] = useState<string[]>([])
  const [adding, setAdding] = useState('')
  const [saving, setSaving] = useState(false)
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null)

  /* 父级 chain 改变（如切换 overview 重新拉）同步进本地状态 */
  useEffect(() => {
    setItems(chain || [])
  }, [chain?.join('|')])

  /* 拉候选模型列表（下拉用） */
  useEffect(() => {
    api
      .get<{ extra_models: string[]; model: string }>('/ai/status')
      .then((d) => {
        const set = new Set<string>(d.extra_models || [])
        if (d.model) set.add(d.model)
        setModels(Array.from(set).sort())
      })
      .catch(() => {})
  }, [])

  /* 防抖保存：300ms 内多次变动只发一次 PUT */
  const save = useCallback(
    (next: string[]) => {
      if (timer.current) clearTimeout(timer.current)
      timer.current = setTimeout(() => {
        setSaving(true)
        api
          .put('/intel/settings', { llm_fallback_chain: next.join(',') })
          .then(() => onChange?.())
          .catch(() => {})
          .finally(() => setSaving(false))
      }, 300)
    },
    [onChange],
  )

  const update = useCallback(
    (next: string[]) => {
      setItems(next)
      save(next)
    },
    [save],
  )

  const move = (i: number, dir: -1 | 1) => {
    const j = i + dir
    if (j < 0 || j >= items.length) return
    const next = items.slice()
    ;[next[i], next[j]] = [next[j], next[i]]
    update(next)
  }
  const remove = (i: number) => {
    update(items.filter((_, k) => k !== i))
  }
  const add = () => {
    const v = adding.trim()
    if (!v) return
    if (items.includes(v)) {
      setAdding('')
      return
    }
    update([...items, v].slice(0, 5))   // 硬上限 5 档（与后端一致）
    setAdding('')
  }

  /* 自定义模型（不在候选下拉里）—— 输入框直接回车 */
  const onAddKey = (e: React.KeyboardEvent<HTMLSelectElement>) => {
    if (e.key === 'Enter') {
      e.preventDefault()
      add()
    }
  }

  const candidates = useMemo(
    () => models.filter((m) => !items.includes(m)).slice(0, 60),
    [models, items],
  )

  return (
    <div className="flex flex-wrap items-center gap-2 text-[11px] text-slate-500">
      <span className="shrink-0">模型链</span>
      <div className="flex flex-wrap items-center gap-1.5">
        {items.length === 0 && <span className="text-slate-400">（空：用默认模型单档）</span>}
        {items.map((m, i) => (
          <span
            key={`${m}-${i}`}
            className="inline-flex items-center gap-1 rounded-md bg-brand-50 px-1.5 py-0.5 text-brand-800 ring-1 ring-inset ring-brand-200"
          >
            <span className="num text-[10px] text-brand-500">{i + 1}</span>
            <span className="font-medium">{m}</span>
            <button
              onClick={() => move(i, -1)}
              disabled={i === 0}
              className="rounded p-0.5 hover:bg-brand-100 disabled:opacity-30"
              title="上移"
            >
              <ArrowUp className="h-3 w-3" />
            </button>
            <button
              onClick={() => move(i, 1)}
              disabled={i === items.length - 1}
              className="rounded p-0.5 hover:bg-brand-100 disabled:opacity-30"
              title="下移"
            >
              <ArrowDown className="h-3 w-3" />
            </button>
            <button
              onClick={() => remove(i)}
              className="rounded p-0.5 hover:bg-rose-100 hover:text-rose-700"
              title="移除"
            >
              <X className="h-3 w-3" />
            </button>
          </span>
        ))}
      </div>
      {items.length < 5 && (
        <span className="inline-flex items-center gap-1">
          <Select
            value={adding}
            onChange={(e) => setAdding(e.target.value)}
            className="!w-[180px]"
            onKeyDown={onAddKey}
          >
            <option value="">+ 添加模型</option>
            {candidates.map((m) => (
              <option key={m} value={m}>
                {m}
              </option>
            ))}
          </Select>
          <Button
            size="sm"
            variant="ghost"
            icon={<Plus className="h-3 w-3" />}
            disabled={!adding.trim()}
            onClick={add}
          >
            加入
          </Button>
        </span>
      )}
      <span className="ml-auto inline-flex items-center gap-1 text-slate-400">
        {saving ? (
          <>
            <RefreshCw className="h-3 w-3 animate-spin" />
            保存中…
          </>
        ) : items.length > 0 ? (
          <>
            <Trash2 className="h-3 w-3 opacity-0" />
            {items.length}/5 档
          </>
        ) : null}
      </span>
    </div>
  )
}