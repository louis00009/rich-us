import { ReactNode } from 'react'
import { useInfoTip } from './InfoTip'

/**
 * 综合评分单元格 —— 候选观察池的核心展示件。
 *
 * 两个设计决定：
 *  ① **分数必须可溯源**：悬停要能看到四个维度各自得了多少分、各自的理由。
 *     只给一个「85 分」而不说为什么，用户没法判断该不该信它 ——
 *     那正是「黑盒评分」的问题。后端 `score_parts` 提供了逐维理由。
 *  ② **缺数据的标的要显式标注**：后端会标记 `score_low_conf`。不标的话，
 *     一只因为「没有 ROE 数据」而只得 75 分的股票会与真正算出来 75 分的混在一起，
 *     用户会误以为两者可比。
 */

export interface ScoreDims {
  valuation: number | null
  quality: number | null
  position: number | null
  trend: number | null
}

export interface ScoreInfo {
  score?: number | null
  score_band?: 'buy' | 'mid' | 'low' | 'na' | string
  score_dims?: ScoreDims | null
  score_parts?: Record<string, string> | null
  score_coverage?: number | null
  score_low_conf?: boolean
}

const DIM_ORDER: (keyof ScoreDims)[] = ['valuation', 'quality', 'position', 'trend']
const DIM_LABEL: Record<string, string> = {
  valuation: '估值',
  quality: '质量',
  position: '位置',
  trend: '趋势',
}

/** 分档配色：候选池用蓝（**刻意不用涨红跌绿** —— 评分不是涨跌）。 */
function bandClass(band?: string): string {
  if (band === 'buy') return 'bg-brand-50 font-semibold text-brand-700 ring-1 ring-brand-200'
  if (band === 'mid') return 'bg-slate-50 text-slate-600'
  if (band === 'na') return 'bg-slate-50 text-slate-300'
  return 'bg-white text-slate-400'
}

function DimBar({ value }: { value: number | null }) {
  if (value === null) {
    return <span className="text-[10px] text-slate-300">无数据</span>
  }
  // 估值色阶：低=蓝，中=灰，高=青绿（表示「这一维度表现好」）。不用红绿以免与涨跌混淆。
  const color = value >= 70 ? '#0d9488' : value >= 40 ? '#94a3b8' : '#cbd5e1'
  return (
    <span className="inline-flex items-center gap-1.5">
      <span className="inline-block h-1 w-10 overflow-hidden rounded-full bg-slate-100 align-middle">
        <span className="block h-full rounded-full" style={{ width: `${Math.max(4, value)}%`, background: color }} />
      </span>
      <span className="num w-7 text-right text-[11px] tabular-nums text-slate-500">{value.toFixed(0)}</span>
    </span>
  )
}

function ScoreTipContent({ row }: { row: ScoreInfo }) {
  const dims = row.score_dims || ({} as ScoreDims)
  const parts = row.score_parts || {}
  const cov = row.score_coverage
  return (
    <>
      <div className="mb-2 flex items-center gap-2">
        <span className="text-lg font-bold text-slate-900">
          {typeof row.score === 'number' ? row.score.toFixed(1) : '—'}
        </span>
        <span className="text-[11px] text-slate-400">/ 100</span>
        {row.score_low_conf && (
          <span className="rounded bg-amber-50 px-1.5 py-px text-[10px] text-amber-700">
            数据不全，仅供参考
          </span>
        )}
      </div>
      <div className="space-y-1.5">
        {DIM_ORDER.map((k) => (
          <div key={k} className="flex items-start gap-2">
            <span className="w-8 shrink-0 pt-px text-[11px] text-slate-400">{DIM_LABEL[k]}</span>
            <span className="shrink-0 pt-px">
              <DimBar value={dims[k] ?? null} />
            </span>
            <span className="min-w-0 flex-1 text-[10.5px] leading-4 text-slate-500">{parts[k] || ''}</span>
          </div>
        ))}
      </div>
      {typeof cov === 'number' && cov < 1 && (
        <p className="mt-2 rounded bg-amber-50 p-1.5 text-[10.5px] leading-4 text-amber-800">
          只有 {Math.round(cov * 100)}% 的维度有数据 —— 缺失的维度不计入总分（权重重新归一），
          所以这个分数只反映已有数据的部分，不要与数据齐全的标的直接比较。
        </p>
      )}
      <p className="mt-2 border-t border-slate-100 pt-2 text-[10.5px] leading-4 text-slate-400">
        总分 = 四维加权。权重与阈值可在上方调整；这是筛选辅助，不是买入信号。
      </p>
    </>
  )
}

export function ScoreCell({ row }: { row: ScoreInfo }) {
  const band = row.score_band
  const { ref, handlers, layer } = useInfoTip<HTMLSpanElement>(
    '综合评分明细',
    <ScoreTipContent row={row} />,
  )

  if (typeof row.score !== 'number') {
    return <span className="text-slate-300">—</span>
  }

  return (
    <span ref={ref} {...handlers} className="inline-block cursor-help">
      <span className={`inline-block rounded px-1.5 py-0.5 text-[11px] tabular-nums ${bandClass(band)}`}>
        {row.score.toFixed(1)}
      </span>
      {row.score_low_conf && <span className="ml-1 align-middle text-[9px] text-amber-500">*</span>}
      {layer}
    </span>
  )
}

/** 候选池视图顶部的说明条 —— 把「这不是买入信号」讲清楚，别让人误解。
 *
 * `bypassed`：用户正在搜索，后端已**忽略**候选池评分门槛（否则搜一个明确代码
 * 会因该标的评分低于阈值而返回空，页面看起来像「这只股票不存在」）。
 * 必须显式告知 —— 否则用户在候选池里看到 40 分的标的会以为门槛失灵了。
 */
export function PoolNotice({
  count,
  total,
  threshold,
  bypassed = false,
}: {
  count: number
  total: number
  threshold: number
  bypassed?: boolean
}): ReactNode {
  return (
    <div className="rounded-xl border border-brand-100 bg-brand-50/60 px-3 py-2.5 text-[11.5px] leading-5 text-slate-600">
      <span className="font-semibold text-brand-800">候选观察池</span>
      <span className="text-slate-400"> · </span>
      {bypassed ? (
        <>
          正在搜索，已<strong className="font-medium">临时忽略评分门槛</strong>
          （≥ {threshold}）—— 搜索时按代码 / 名称直接定位标的，不受评分限制。
          清空搜索框即可回到候选池。
        </>
      ) : (
        <>
          按综合评分 ≥ {threshold} 从 {total} 只中筛出{' '}
          <span className="num font-semibold text-brand-800">{count}</span> 只，按评分从高到低排列。
        </>
      )}
      <div className="mt-1 text-slate-500">
        这个列表是<strong className="font-medium">筛选辅助</strong>，不是买入信号 ——
        本项目的复盘结论是规则化策略在收益上打不过买入持有，其价值在回撤控制。
        评分只负责把范围缩小，最终判断请结合公司档案、行业与你的持仓情况。
      </div>
    </div>
  )
}
