/**
 * 行情数据源面板（数据源偏好 + 降级链 + 源健康状态）
 * ==================================================
 * **所有字段都来自后端 `GET /market/data-source`**，前端不再硬编码降级链。
 *
 * 为什么抽出来：这块原先写死在 `pages/Settings.tsx` 里，是一份 5 项的硬编码数组，
 * 结果接入 TwelveData 后设置页仍在显示「yfinance → Stooq → 合成」——
 * 用户看不到自己刚配好的源，也无法把 TwelveData 选为优先源。
 * 后端 `available` / `chain` 早已是正确的 6 项，前端只是没跟上。
 * 抽成组件后：设置页减负（该文件已超 900 行硬上限），且**以后加源只改后端**。
 */
import { useEffect, useState } from 'react'

import { api } from '../lib/api'
import { Badge, Button, Field, Select, useToast } from './ui'

const SOURCE_LABEL: Record<string, string> = {
  ibkr: 'IBKR',
  twelvedata: 'TwelveData',
  yfinance: 'yfinance',
  stooq: 'Stooq CSV',
}

export default function DataSourcePanel({ info, onChanged }: { info: any; onChanged?: () => void }) {
  const toast = useToast()
  const [preferred, setPreferred] = useState<string>(info?.preferred || 'auto')

  // 偏好可能在别处被改（或本次 load 刷新）→ 保持同步
  useEffect(() => {
    if (info?.preferred) setPreferred(info.preferred)
  }, [info?.preferred])

  const available: string[] = info?.available || ['auto', 'ibkr']
  const providers: Record<string, any> = info?.providers || {}
  const chain: string[] = info?.chain || []
  const ibkrOk = !!providers?.ibkr?.available

  return (
    <>
      <div className="mb-4 rounded-lg border border-slate-200 bg-slate-50/60 p-3.5">
        <div className="flex flex-wrap items-end gap-3">
          <Field label="数据源偏好" className="min-w-[240px] flex-1" hint={info?.note}>
            <Select
              value={preferred}
              onChange={async (e) => {
                const v = e.target.value
                try {
                  const r = await api.post<{ preferred: string }>('/market/data-source', { preferred: v })
                  setPreferred(r.preferred)
                  toast('success', `数据源偏好已设为「${r.preferred}」`)
                  onChanged?.()
                } catch (err: any) {
                  toast('error', err?.message || '切换失败')
                }
              }}
            >
              {available.map((k) => {
                if (k === 'auto') {
                  return (
                    <option key={k} value="auto">
                      自动（按下方降级链依次尝试）
                    </option>
                  )
                }
                const p = providers?.[k]
                return (
                  <option key={k} value={k}>
                    {SOURCE_LABEL[k] || k} 优先{p?.available ? '（可用）' : '（不可用，会自动降级）'}
                  </option>
                )
              })}
            </Select>
          </Field>
          <div className="pb-1">
            <Badge tone={ibkrOk ? 'green' : 'slate'} dot>
              IBKR {ibkrOk ? '可用' : '不可用'}
            </Badge>
          </div>
        </div>
        {!ibkrOk && (
          <p className="mt-2 text-xs text-amber-700">
            提示：{providers?.ibkr?.reason}。IBKR 行情对日内策略尤其重要 ——
            免费源只能提供约 60 天的分钟级数据。
          </p>
        )}
      </div>

      {/* 降级链：逐项来自后端，不再硬编码（硬编码曾漏掉 TwelveData） */}
      <div className="space-y-3">
        {chain.map((desc, i) => (
          <div key={desc} className="flex items-start gap-3 rounded-lg border border-slate-200 p-3">
            <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-slate-100 text-[11px] font-semibold text-slate-600">
              {i + 1}
            </span>
            <div className="flex min-w-0 flex-1 flex-wrap items-center gap-2">
              <span className="text-sm font-medium text-slate-800">{desc}</span>
              {desc.includes('非真实数据') && <Badge tone="amber">非真实数据</Badge>}
            </div>
          </div>
        ))}
      </div>

      <div className="mt-5 border-t border-slate-100 pt-4">
        <div className="mb-2 flex items-center justify-between">
          <span className="text-xs font-semibold uppercase tracking-wide text-slate-400">源健康状态</span>
          <Button
            className="!px-2 !py-1 text-[11px]"
            onClick={async () => {
              try {
                const t0 = Date.now()
                await api.get('/market/history?symbol=SPY&start=2026-08-01&interval=1d', 30_000)
                toast('success', `探测成功：SPY 日线 ${Date.now() - t0}ms`)
                onChanged?.()
              } catch (e: any) {
                toast('error', `探测失败：${e?.message || '超时'}`)
              }
            }}
          >
            探测链路
          </Button>
        </div>
        {info?.recent_errors && Object.keys(info.recent_errors).length > 0 ? (
          <div className="mb-3 space-y-1 rounded-lg border border-amber-200 bg-amber-50 p-2.5">
            {Object.entries(info.recent_errors).map(([k, v]: any) => (
              <div key={k} className="text-[11px] text-amber-800">
                <span className="font-semibold">{k}</span>：{v}
              </div>
            ))}
            <div className="text-[10px] text-amber-600">
              失败会在下一次请求自动重试；频繁出现可切换数据源偏好。
            </div>
          </div>
        ) : (
          <div className="mb-3 rounded-lg border border-emerald-100 bg-emerald-50 px-2.5 py-2 text-[11px] text-emerald-700">
            ✅ 全部数据源近期无失败记录
          </div>
        )}
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
          {Object.entries(providers).map(([name, p]: any) => (
            <div key={name} className="rounded-lg border border-slate-200 px-2.5 py-2">
              <div className="text-xs font-medium text-slate-700">{name}</div>
              <div className="mt-0.5 flex items-center gap-1 text-[10px] text-slate-400">
                <span
                  className={`inline-block h-1.5 w-1.5 rounded-full ${
                    p?.available ? 'bg-emerald-500' : 'bg-slate-300'
                  }`}
                />
                {p?.available ? '可用' : '不可用'}
              </div>
            </div>
          ))}
        </div>
      </div>
    </>
  )
}
