/**
 * ParamForm —— 依据后端 ParamSpec 自动渲染的参数表单
 * =====================================================
 * 从 `pages/Strategies.tsx` 抽出（铁律 9：页面文件已超硬上限，新功能必须先拆）。
 * 纯展示组件：不持有状态，值由父级通过 `values` / `onChange` 控制。
 */
import { useMemo } from 'react'
import { Field, Input, Select, Switch } from '../ui'
import type { ParamSpec } from '../../lib/types'

export default function ParamForm({
  specs,
  values,
  onChange,
}: {
  specs: ParamSpec[]
  values: Record<string, any>
  onChange: (k: string, v: any) => void
}) {
  const groups = useMemo(() => {
    const g: Record<string, ParamSpec[]> = {}
    specs.forEach((s) => {
      ;(g[s.group] ||= []).push(s)
    })
    return g
  }, [specs])

  if (!specs.length) return <p className="text-xs text-slate-400">该策略无可调参数</p>

  return (
    <div className="space-y-4">
      {Object.entries(groups).map(([group, items]) => (
        <div key={group}>
          <div className="mb-2 flex items-center gap-2">
            <span className="text-xs font-semibold uppercase tracking-wide text-slate-400">{group}</span>
            <div className="h-px flex-1 bg-slate-100" />
          </div>
          <div className="grid gap-3 sm:grid-cols-2">
            {items.map((p) => {
              const v = values[p.key] ?? p.default
              if (p.type === 'bool') {
                return (
                  <div key={p.key} className="sm:col-span-1">
                    <Switch
                      checked={!!v}
                      onChange={(nv) => onChange(p.key, nv)}
                      label={p.label}
                      hint={p.help || undefined}
                    />
                  </div>
                )
              }
              if (p.type === 'choice') {
                return (
                  <Field key={p.key} label={p.label} hint={p.help || undefined}>
                    <Select value={String(v)} onChange={(e) => onChange(p.key, e.target.value)}>
                      {(p.choices || []).map((c) => (
                        <option key={String(c)} value={String(c)}>
                          {String(c) || '（留空）'}
                        </option>
                      ))}
                    </Select>
                  </Field>
                )
              }
              return (
                <Field
                  key={p.key}
                  label={
                    <span className="flex items-center gap-1.5">
                      {p.label}
                      {p.min !== undefined && p.max !== undefined && (
                        <span className="text-[10px] font-normal text-slate-400">
                          [{p.min} ~ {p.max}]
                        </span>
                      )}
                    </span>
                  }
                  hint={p.help || undefined}
                >
                  <Input
                    type="number"
                    step={p.step ?? (p.type === 'int' ? 1 : 0.01)}
                    min={p.min}
                    max={p.max}
                    value={v}
                    onChange={(e) =>
                      onChange(p.key, p.type === 'int' ? parseInt(e.target.value || '0', 10) : parseFloat(e.target.value || '0'))
                    }
                  />
                </Field>
              )
            })}
          </div>
        </div>
      ))}
      <button
        className="text-xs text-brand-600 hover:underline"
        onClick={() => specs.forEach((p) => onChange(p.key, p.default))}
      >
        恢复全部默认值
      </button>
    </div>
  )
}
