/**
 * 行情页 · 搜索栏与参数卡
 *
 * 含：标的搜索（键盘导航 + 快捷收藏）、周期区间 / K 线周期 / 均线叠加 / 数据源选择，
 * 以及数据源告警与诊断提示。
 *
 * 从 `pages/Market.tsx` 抽出（铁律 9 拆分，2026-09-29）。
 */
import type { Dispatch, SetStateAction } from 'react'
import { Search, Star, TrendingUp } from 'lucide-react'
import { Badge, Button, Card, Field, Input, Select } from '../ui'
import type { DataSourceInfo } from '../../lib/types'
import { INTERVALS, RANGES } from './constants'
import type { HistoryResp, OverlayKey } from './types'

export interface SuggestItem {
  symbol: string
  name: string
  kind: string
}

export function SearchPanel({
  query,
  setQuery,
  symbol,
  suggest,
  setSuggest,
  suggestIdx,
  setSuggestIdx,
  watchedSet,
  commitSymbol,
  toggleSuggestFav,
  range,
  setRange,
  interval,
  setInterval,
  overlay,
  setOverlay,
  source,
  setSource,
  dsInfo,
  hist,
  srcWarn,
  onLoad,
  loading,
}: {
  query: string
  setQuery: Dispatch<SetStateAction<string>>
  symbol: string
  suggest: SuggestItem[]
  setSuggest: Dispatch<SetStateAction<SuggestItem[]>>
  suggestIdx: number
  setSuggestIdx: Dispatch<SetStateAction<number>>
  watchedSet: Set<string>
  commitSymbol: (v: string) => void
  toggleSuggestFav: (sym: string) => void
  range: string
  setRange: (v: string) => void
  interval: string
  setInterval: (v: string) => void
  overlay: OverlayKey
  setOverlay: (v: OverlayKey) => void
  source: string
  setSource: (v: string) => void
  dsInfo: DataSourceInfo | null
  hist: HistoryResp | null
  srcWarn: string
  onLoad: () => void
  loading: boolean
}) {
  return (
    <Card>
      <div className="flex flex-wrap items-end gap-3">
        <div className="relative min-w-[220px] flex-1">
          <label className="lbl">标的代码</label>
          <div className="relative">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
            <Input
              className="pl-9"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => {
                // T-116：搜索建议键盘导航 —— ↓↑ 移动高亮、Enter 选中高亮项（无高亮则提交原文）、Esc 关闭
                if (e.key === 'ArrowDown' && suggest.length) {
                  e.preventDefault()
                  setSuggestIdx((i) => Math.min(i + 1, suggest.length - 1))
                  return
                }
                if (e.key === 'ArrowUp' && suggest.length) {
                  e.preventDefault()
                  setSuggestIdx((i) => Math.max(i - 1, 0))
                  return
                }
                if (e.key === 'Enter') {
                  if (suggest.length && suggestIdx >= 0 && suggestIdx < suggest.length) {
                    commitSymbol(suggest[suggestIdx].symbol)
                  } else {
                    commitSymbol(query || symbol)
                  }
                  return
                }
                if (e.key === 'Escape') {
                  setQuery('')
                  setSuggest([])
                  setSuggestIdx(-1)
                }
              }}
              onBlur={() =>
                setTimeout(() => {
                  setSuggest([])
                  setSuggestIdx(-1)
                }, 150)
              }
              placeholder="搜索代码或名称，回车切换（如 NVDA / 腾讯）"
            />
            <span className="absolute right-2.5 top-1/2 -translate-y-1/2 rounded bg-brand-50 px-1.5 py-0.5 text-[10px] font-semibold text-brand-700">
              {symbol}
            </span>
          </div>
          {suggest.length > 0 && (
            <div
              className="absolute z-30 mt-1 max-h-72 w-full overflow-y-auto rounded-lg border border-slate-200 bg-white py-1 shadow-pop"
              role="listbox"
            >
              {suggest.map((s, i) => (
                <div
                  key={s.symbol}
                  onClick={() => commitSymbol(s.symbol)}
                  onMouseEnter={() => setSuggestIdx(i)}
                  role="option"
                  aria-selected={i === suggestIdx}
                  className={`flex w-full cursor-pointer items-center justify-between px-3 py-2 text-left ${
                    i === suggestIdx ? 'bg-brand-50' : 'hover:bg-slate-50'
                  }`}
                >
                  <span className="text-sm font-medium text-slate-700">{s.symbol}</span>
                  <span className="ml-3 flex-1 truncate text-xs text-slate-400">{s.name}</span>
                  {/* 快捷收藏：点星直接关注该建议项（不切换标的），与关注列表即时同步 */}
                  <button
                    onClick={(e) => {
                      e.stopPropagation()
                      toggleSuggestFav(s.symbol)
                    }}
                    title={watchedSet.has(s.symbol) ? '取消收藏' : '收藏到我的关注'}
                    className="rounded p-1 transition-colors hover:bg-slate-100"
                  >
                    <Star
                      className={`h-3.5 w-3.5 ${
                        watchedSet.has(s.symbol) ? 'fill-amber-400 text-amber-400' : 'text-slate-300 hover:text-amber-400'
                      }`}
                    />
                  </button>
                  <Badge tone="slate">{s.kind}</Badge>
                </div>
              ))}
            </div>
          )}
        </div>

        <Field label="周期区间">
          <Select value={range} onChange={(e) => setRange(e.target.value)} className="w-32">
            {RANGES.map((r) => (
              <option key={r.key} value={r.key}>
                {r.key}
              </option>
            ))}
          </Select>
        </Field>

        <Field label="K 线周期">
          <Select value={interval} onChange={(e) => setInterval(e.target.value)} className="w-44">
            {INTERVALS.map((i) => (
              <option key={i.key} value={i.key}>
                {i.label}
              </option>
            ))}
          </Select>
        </Field>

        <Field label="均线叠加">
          <Select value={overlay} onChange={(e) => setOverlay(e.target.value as OverlayKey)} className="w-44">
            <option value="ma">短线均线 MA5/10/20/60</option>
            <option value="sma">长期均线 SMA50/200</option>
            <option value="bb">布林带</option>
            <option value="all">全部叠加</option>
            <option value="none">不叠加</option>
          </Select>
        </Field>

        <Field
          label="数据源"
          hint={dsInfo && dsInfo.providers?.ibkr?.available ? 'IBKR 已连接' : 'IBKR 未连接，将自动降级'}
        >
          <Select value={source} onChange={(e) => setSource(e.target.value)} className="w-40">
            <option value="auto">自动（推荐）</option>
            <option value="ibkr">IBKR 优先</option>
          </Select>
        </Field>

        <Button variant="primary" onClick={onLoad} loading={loading} icon={<TrendingUp className="h-3.5 w-3.5" />}>
          加载
        </Button>
      </div>

      {hist?.warning && (
        <div className="mt-3 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
          ⚠️ {hist.warning}
        </div>
      )}
      {hist?.source === 'synthetic' && (
        <div className="mt-3 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
          ⚠️ 当前显示的是<span className="font-medium">合成数据</span>（非真实行情）。说明外部数据源均不可用，仅供界面演示。
        </div>
      )}
      {srcWarn && (
        <div className="mt-3 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-[11px] text-slate-500">
          数据源诊断：{srcWarn}（已自动降级/重试；若频繁出现可切换数据源或稍后再试）
        </div>
      )}
    </Card>
  )
}
