/**
 * 观察标的列表
 *
 * 从 `pages/Intel.tsx` 抽出（页面超硬上限）。行为保持：点卡片进入该公司时间线、
 * 卡片内开关启用/停用、悬停出现「立即分析 / 移除」。
 */
import { useState } from 'react'
import { Plus, RefreshCw, Trash2, Zap } from 'lucide-react'
import { Badge, Button, Card, Empty, Field, Input, Modal, Switch } from '../ui'
import { fmtSince, type Company } from './types'

export default function CompanyList({
  companies,
  enabled,
  total,
  selected,
  onSelect,
  onToggle,
  onAnalyze,
  onDelete,
  onSync,
  onAdd,
  busy,
}: {
  companies: Company[]
  enabled: number
  total: number
  selected: string
  onSelect: (s: string) => void
  onToggle: (c: Company, v: boolean) => void
  onAnalyze: (symbol: string) => void
  onDelete: (c: Company) => void
  onSync: () => void
  onAdd: (form: { symbol: string; name: string; theme: string; focus: string }) => void
  busy: string
}) {
  const [addOpen, setAddOpen] = useState(false)
  const [form, setForm] = useState({ symbol: '', name: '', theme: '', focus: '' })

  const submit = () => {
    const s = form.symbol.trim().toUpperCase()
    if (!s) return
    onAdd({ ...form, symbol: s })
    setForm({ symbol: '', name: '', theme: '', focus: '' })
    setAddOpen(false)
  }

  return (
    <Card
      className="flex min-h-0 flex-1 flex-col"
      bodyClass="min-h-0 flex-1 overflow-y-auto"
      title="观察标的（美股核心公司）"
      subtitle={`${enabled} / ${total} 启用中 · 数量不限`}
      actions={
        <div className="flex items-center gap-1.5">
          <Button
            size="sm"
            variant="ghost"
            icon={<RefreshCw className="h-3.5 w-3.5" />}
            loading={busy === 'sync-watch'}
            title="把行情页关注列表的全部标的同步进来（已有的跳过）"
            onClick={onSync}
          >
            ⇄ 同步关注
          </Button>
          <Button size="sm" icon={<Plus className="h-3.5 w-3.5" />} onClick={() => setAddOpen(true)}>
            添加
          </Button>
        </div>
      }
    >
      {companies.length === 0 ? (
        <Empty title="还没有观察标的" desc="点「添加」或「同步关注」把标的加进来" />
      ) : (
        <div className="grid grid-cols-1 gap-2">
          {companies.map((c) => {
            const isSel = selected === c.symbol
            return (
              <div
                key={c.id}
                onClick={() => onSelect(isSel ? '' : c.symbol)}
                title="点击查看该公司的专属时间线"
                className={`group flex cursor-pointer items-start gap-2 rounded-lg border p-2.5 transition-all ${
                  isSel
                    ? 'border-brand-400 bg-brand-50/50 ring-1 ring-brand-300'
                    : c.enabled
                      ? 'border-slate-200 bg-white hover:border-brand-200'
                      : 'border-dashed border-slate-200 bg-slate-50 opacity-70'
                }`}
              >
                <span onClick={(e) => e.stopPropagation()}>
                  <Switch checked={c.enabled} onChange={(v) => onToggle(c, v)} />
                </span>
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-semibold text-slate-800">{c.symbol}</span>
                    <span className="truncate text-xs text-slate-400">{c.name}</span>
                    {isSel && <Badge tone="brand">时间线</Badge>}
                  </div>
                  <div className="mt-0.5 truncate text-[11px] text-slate-400">
                    {c.theme || '—'} · 抓取：{fmtSince(c.last_scrape_at)}
                  </div>
                </div>
                <div className="flex shrink-0 items-center gap-0.5 opacity-0 transition-opacity group-hover:opacity-100">
                  <button
                    title={`立即分析 ${c.symbol}（基于最近事件 + 量化快照）`}
                    className="rounded p-1.5 text-brand-600 hover:bg-brand-50"
                    onClick={(e) => {
                      e.stopPropagation()
                      onAnalyze(c.symbol)
                    }}
                  >
                    <Zap className="h-3.5 w-3.5" />
                  </button>
                  <button
                    title="移除"
                    className="rounded p-1.5 text-slate-400 hover:bg-rose-50 hover:text-rose-600"
                    onClick={(e) => {
                      e.stopPropagation()
                      onDelete(c)
                    }}
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                </div>
              </div>
            )
          })}
        </div>
      )}

      <Modal
        open={addOpen}
        onClose={() => setAddOpen(false)}
        title="添加观察标的"
        footer={
          <>
            <Button onClick={() => setAddOpen(false)}>取消</Button>
            <Button variant="primary" icon={<Plus className="h-3.5 w-3.5" />} onClick={submit}>
              确认添加
            </Button>
          </>
        }
      >
        <div className="space-y-3">
          <Field label="标的代码（必填）">
            <Input
              value={form.symbol}
              onChange={(e) => setForm({ ...form, symbol: e.target.value.toUpperCase() })}
              onKeyDown={(e) => e.key === 'Enter' && submit()}
              placeholder="NVDA / BRK.B / 0700.HK"
            />
          </Field>
          <Field label="公司名称（选填）">
            <Input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="NVIDIA" />
          </Field>
          <Field label="观察主题（选填）">
            <Input value={form.theme} onChange={(e) => setForm({ ...form, theme: e.target.value })} placeholder="AI 算力 / 减肥药 / 云…" />
          </Field>
          <Field label="关注要点（选填，指导 AI Agent 抓取方向）">
            <textarea
              value={form.focus}
              onChange={(e) => setForm({ ...form, focus: e.target.value })}
              rows={3}
              placeholder="例：数据中心 GPU 出货节奏、大厂资本开支、出口管制"
              className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-800 outline-none transition-colors focus:border-brand-400"
            />
          </Field>
          <p className="text-[11px] text-slate-400">
            添加后立即进入观察列表；开启监控后外部 AI Agent 会按主题/要点定向检索该公司新闻。
          </p>
        </div>
      </Modal>
    </Card>
  )
}
