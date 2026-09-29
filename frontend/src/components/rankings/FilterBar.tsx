/**
 * 榜单页 · 搜索 / 行业 / 条数 / 列 工具条
 *
 * 从 `pages/Rankings.tsx` 抽出（铁律 9 拆分，2026-09-29）。
 */
import { Search } from 'lucide-react'
import { Input, Select } from '../ui'
import { RANKING_COLUMNS } from '../../lib/rankingColumns'
import { ColumnPicker } from './RankingsTable'

export function FilterBar({
  sort,
  dir,
  q,
  setQ,
  sector,
  setSector,
  sectors,
  limit,
  setLimit,
  visible,
  toggleColumn,
  resetVisible,
}: {
  sort: string
  dir: 'asc' | 'desc'
  q: string
  setQ: (v: string) => void
  sector: string
  setSector: (v: string) => void
  sectors: string[]
  limit: number
  setLimit: (v: number) => void
  visible: string[]
  toggleColumn: (key: string) => void
  resetVisible: () => void
}) {
  return (
    <div className="flex flex-wrap items-center gap-2 rounded-xl border border-slate-200 bg-white px-3 py-2.5">
      <span className="text-[11px] text-slate-400">排序</span>
      <span className="text-xs font-medium text-brand-700">
        {RANKING_COLUMNS.find((c) => c.key === sort)?.label ?? sort} {dir === 'desc' ? '↓' : '↑'}
      </span>
      <span className="text-[11px] text-slate-300">点列头可切换</span>
      <div className="relative ml-auto">
        <Search className="absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-slate-300" />
        <Input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="搜索代码 / 中英文名称"
          className="!w-44 py-1.5 pl-7 text-xs"
        />
      </div>
      <Select value={sector} onChange={(e) => setSector(e.target.value)} className="!w-36 py-1.5 text-xs">
        <option value="">全部行业</option>
        {sectors.map((s) => (
          <option key={s} value={s}>
            {s}
          </option>
        ))}
      </Select>
      <Select value={String(limit)} onChange={(e) => setLimit(Number(e.target.value))} className="!w-24 py-1.5 text-xs">
        {[20, 50, 100, 200, 1550].map((n) => (
          <option key={n} value={n}>
            {n >= 1550 ? '全部' : `前 ${n}`}
          </option>
        ))}
      </Select>
      <ColumnPicker visible={visible} onToggle={toggleColumn} onReset={resetVisible} />
    </div>
  )
}
