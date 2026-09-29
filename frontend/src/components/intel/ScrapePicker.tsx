/**
 * 指定抓取标的（抓取范围选择器）
 *
 * 「AI 立即抓取」原来只能按**家数**跑（最多 4/8/12 家 或 全部待抓取），取的是待抓取
 * 清单的**前 N 家**。用户的实际诉求是「今天重点想跑这几家」或「我就跑一家」——
 * 这个诉求原来无法表达，只能碰运气看轮转到谁。
 *
 * 本组件给出一份可搜索、可多选的标的清单：
 *   · **点选顺序 = 抓取顺序**（后端按传入顺序依次跑），选中项带 ①②③ 序号；
 *   · 「待抓取」标记与「全选待抓取」由**后端清单**驱动（`stats.pending_symbols`）——
 *     待抓取判定含 `interval*1.2` 的窗口逻辑，前端自行推算迟早与后端不一致；
 *   · 已停用的标的**仍可勾选**（显式指定优先于 enabled：用户说跑就跑）；
 *   · 排序把「待抓取」放最前（≈最久没抓的），让该跑的落在最前面。
 *
 * 选择结果由父级持久化（lib/intelPrefs），刷新 / 切页后仍在 —— 用户每天要跑，
 * 不该每天重挑一遍。
 */
import { useMemo, useState } from 'react'
import { Badge, Button, Input } from '../ui'
import { fmtSince, type Company } from './types'

/** 单家约 30~90 秒 → 预估区间用 0.5~1.5 分钟/家（与 MonitorBar 的文案口径一致） */
function estimate(count: number): string {
  if (!count) return '—'
  const lo = Math.max(1, Math.round(count * 0.5))
  const hi = Math.max(1, Math.round(count * 1.5))
  return `${lo}~${hi} 分钟`
}

export default function ScrapePicker({
  companies,
  pendingSymbols,
  value,
  onChange,
  disabled = false,
}: {
  companies: Company[]
  /** 后端给出的「已到期待抓取」清单（口径唯一来源） */
  pendingSymbols: string[]
  /** 已选标的，**有序**（顺序即抓取顺序） */
  value: string[]
  onChange: (list: string[]) => void
  disabled?: boolean
}) {
  const [q, setQ] = useState('')

  const pendingSet = useMemo(() => new Set(pendingSymbols.map((s) => s.toUpperCase())), [pendingSymbols])

  const rows = useMemo(() => {
    const kw = q.trim().toUpperCase()
    const list = companies.filter(
      (c) =>
        !kw ||
        c.symbol.toUpperCase().includes(kw) ||
        (c.name || '').toUpperCase().includes(kw) ||
        (c.theme || '').toUpperCase().includes(kw),
    )
    return [...list].sort((a, b) => {
      const pa = pendingSet.has(a.symbol.toUpperCase()) ? 0 : 1
      const pb = pendingSet.has(b.symbol.toUpperCase()) ? 0 : 1
      if (pa !== pb) return pa - pb
      return a.symbol.localeCompare(b.symbol)
    })
  }, [companies, q, pendingSet])

  const idxOf = (sym: string) => value.findIndex((s) => s.toUpperCase() === sym.toUpperCase())

  const toggle = (sym: string) => {
    const s = sym.toUpperCase()
    const i = idxOf(s)
    onChange(i >= 0 ? value.filter((_, k) => k !== i) : [...value, s])
  }

  const enabledSymbols = companies.filter((c) => c.enabled).map((c) => c.symbol.toUpperCase())

  return (
    <div className="mt-3 rounded-lg border border-brand-200 bg-brand-50/40 px-3 py-2.5">
      {/* 头部：已选摘要 + 搜索 + 快捷选择 */}
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        <b className="shrink-0 text-xs text-brand-800">指定抓取标的</b>
        <span className="min-w-0 text-[11px] text-slate-600">
          {value.length ? (
            <>
              已选 <b className="num text-brand-700">{value.length}</b> 家 · 预计 {estimate(value.length)}
              <span className="text-slate-400"> · 按选择顺序依次抓取</span>
            </>
          ) : (
            <span className="text-slate-500">未选择任何标的 —— 将按「自动（待抓取轮转）」执行</span>
          )}
        </span>

        <div className="ml-auto flex flex-wrap items-center gap-1.5">
          <Input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="搜索代码 / 名称 / 主题"
            className="!w-48"
            disabled={disabled}
          />
          <Button
            size="sm"
            variant="ghost"
            disabled={disabled || !pendingSymbols.length}
            title="把选择替换为「已到期待抓取」的全部标的（口径与后端一致）"
            onClick={() => onChange(pendingSymbols.map((s) => s.toUpperCase()))}
          >
            全选待抓取 {pendingSymbols.length || ''}
          </Button>
          <Button
            size="sm"
            variant="ghost"
            disabled={disabled || !enabledSymbols.length}
            title="把选择替换为「已启用」的全部标的"
            onClick={() => onChange(enabledSymbols)}
          >
            全选启用
          </Button>
          <Button
            size="sm"
            variant="ghost"
            disabled={disabled || !value.length}
            title="清空选择 → 回到「自动（待抓取轮转）」"
            onClick={() => onChange([])}
          >
            清空
          </Button>
        </div>
      </div>

      {/* 标的筹码：点选/取消；选中带序号（=抓取顺序），待抓取带圆点 */}
      <div className="mt-2 max-h-44 overflow-y-auto pr-0.5">
        {rows.length === 0 ? (
          <div className="py-3 text-center text-[11px] text-slate-400">
            {companies.length === 0 ? '观察标的为空 —— 先到左侧「观察标的」添加或同步关注列表' : `没有匹配「${q}」的标的`}
          </div>
        ) : (
          <div className="flex flex-wrap gap-1.5">
            {rows.map((c) => {
              const sym = c.symbol.toUpperCase()
              const i = idxOf(sym)
              const sel = i >= 0
              const isPending = pendingSet.has(sym)
              return (
                <button
                  key={c.id}
                  type="button"
                  disabled={disabled}
                  onClick={() => toggle(c.symbol)}
                  aria-pressed={sel}
                  title={
                    `${c.name || c.symbol}${c.theme ? ` · ${c.theme}` : ''}\n` +
                    `上次抓取：${fmtSince(c.last_scrape_at)}` +
                    (isPending ? '\n已到期待抓取' : '') +
                    (c.enabled ? '' : '\n⚠️ 该标的已停用（仍可手动指定抓取）') +
                    (sel ? `\n第 ${i + 1} 个抓取` : '')
                  }
                  className={`inline-flex items-center gap-1 rounded-md border px-2 py-1 text-[11px] font-medium transition-colors disabled:cursor-not-allowed ${
                    sel
                      ? 'border-brand-600 bg-brand-600 text-white'
                      : c.enabled
                        ? 'border-slate-200 bg-white text-slate-700 hover:border-brand-300 hover:text-brand-700'
                        : 'border-dashed border-slate-300 bg-slate-50 text-slate-400 hover:border-brand-300'
                  }`}
                >
                  {sel && <span className="num opacity-80">{i + 1}</span>}
                  <span>{c.symbol}</span>
                  {isPending && (
                    <span
                      className={`h-1.5 w-1.5 rounded-full ${sel ? 'bg-white/80' : 'bg-amber-500'}`}
                      title="已到期待抓取"
                    />
                  )}
                </button>
              )
            })}
          </div>
        )}
      </div>

      {/* 已选清单（有序）—— 一眼确认「我到底要跑哪几家、什么顺序」 */}
      {value.length > 0 && (
        <div className="mt-2 flex flex-wrap items-center gap-x-2 gap-y-1 border-t border-brand-200/60 pt-2">
          <span className="text-[11px] text-slate-500">抓取顺序：</span>
          <span className="num min-w-0 flex-1 truncate text-[11px] text-brand-800" title={value.join(' → ')}>
            {value.join(' → ')}
          </span>
          <Badge tone={value.length > 20 ? 'amber' : 'brand'}>
            {value.length} 家 · {estimate(value.length)}
          </Badge>
        </div>
      )}
    </div>
  )
}
