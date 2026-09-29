/**
 * 组合优化的「人话」总结
 * =======================
 * 用户对回测页的原话是「很多东西我都不懂」，组合优化页的问题更严重 ——
 * 它吐出来的是一张权重表和一堆协方差衍生的指标（分散化比率、有效标的数、
 * 风险集中度……），小白看完完全不知道「所以这组权重到底能不能用」。
 *
 * 而这个页面自己的代码注释已经写明了判断标准：
 *   「核心不是按一个按钮，而是先看等权基准能不能被打败 —— 打不过就别优化。」
 * 所以这里就把它做成一句话结论。
 *
 * ⚠️ **诚实性**：结论只从返回的真实数字推导，缺字段一律如实说缺，绝不按 0 编造。
 *    尤其这三件事必须主动说：
 *      ① 有标的是**合成行情**（随机生成）→ 结果根本不能用；
 *      ② 约束无解、退回等权 → 这份权重不满足你的原始约束；
 *      ③ 有效标的数远小于名义标的数 → 名义上分散了，实际没有。
 */
import { AlertTriangle, CheckCircle2, Info, MinusCircle, ThumbsDown, ThumbsUp } from 'lucide-react'
import type { ReactNode } from 'react'
import { fmtNum, fmtRatioPct } from '../../lib/format'
import { TermTip } from '../terms/TermTip'
import type { OptResult } from './types'

const num = (v: unknown): number => {
  const n = Number(v)
  return Number.isFinite(n) ? n : 0
}
const finite = (v: unknown) => Number.isFinite(Number(v))

export interface OptSummary {
  /**
   * - win      打赢了等权基准
   * - tie      和等权基本打平（差异在噪声范围内）
   * - lose     打不过等权
   * - not_opt  目标本身就是等权，没有可比性
   * - infeasible 约束无解、已退回等权可行解
   * - unknown  返回里缺关键数字，判不了
   */
  verdict: 'win' | 'tie' | 'lose' | 'not_opt' | 'infeasible' | 'unknown'
  sharpe: number
  benchSharpe: number
  /** 夏普差（组合 - 等权） */
  delta: number
  effectiveN: number
  gross: number
  /** 取不到真实行情的标的 */
  synthetic: string[]
  /** 全部标的都是合成数据 —— 结论完全不可用 */
  allSynthetic: boolean
  clusters: string[][]
  caveats: string[]
}

/** 夏普差小于这个值视为「打平」：再小的差异是估计噪声，不是能力。 */
const SHARPE_TIE = 0.05

export function summarizeOptimize(result: OptResult | null | undefined): OptSummary {
  const r = result
  const empty: OptSummary = {
    verdict: 'unknown',
    sharpe: 0,
    benchSharpe: 0,
    delta: 0,
    effectiveN: 0,
    gross: 0,
    synthetic: [],
    allSynthetic: false,
    clusters: [],
    caveats: [],
  }
  if (!r) return empty

  const hasSharpe = finite(r.portfolio?.sharpe)
  const hasBench = finite(r.benchmark_equal_weight?.sharpe)
  const sharpe = num(r.portfolio?.sharpe)
  const benchSharpe = num(r.benchmark_equal_weight?.sharpe)
  const delta = sharpe - benchSharpe
  const effectiveN = num(r.portfolio?.effective_n)
  const gross = num(r.portfolio?.gross)
  const synthetic = Array.isArray(r.synthetic_symbols) ? r.synthetic_symbols.filter(Boolean) : []
  const total = Array.isArray(r.symbols) ? r.symbols.length : 0
  const allSynthetic = synthetic.length > 0 && total > 0 && synthetic.length >= total
  const clusters = Array.isArray(r.clusters) ? r.clusters : []

  let verdict: OptSummary['verdict']
  if (allSynthetic) verdict = 'unknown'
  else if (!hasSharpe || !hasBench) verdict = 'unknown'
  else if (r.feasible === false) verdict = 'infeasible'
  else if (r.objective === 'equal_weight') verdict = 'not_opt'
  else if (delta > SHARPE_TIE) verdict = 'win'
  else if (delta < -SHARPE_TIE) verdict = 'lose'
  else verdict = 'tie'

  const caveats: string[] = []
  if (allSynthetic) {
    caveats.push(
      `全部 ${total} 个标的都没取到真实历史行情（用的是随机生成的合成价格），这组权重没有任何参考价值，请换标的或换数据源重跑。`,
    )
  } else if (synthetic.length > 0) {
    caveats.push(
      `${synthetic.join('、')} 用的是合成行情（随机生成），它们的权重与风险贡献不可信，建议换掉这几个标的重新跑。`,
    )
  }
  if (r.feasible === false) {
    caveats.push(
      '你设的约束互相矛盾，系统已退回「等权可行解」。下面这份权重「不满足你的原始约束」，只用来兜底，不要当优化结果用。',
    )
  }
  if (verdict === 'lose') {
    caveats.push(
      '没打赢等权基准。花了这么大力气估计协方差，结果还不如每个都买一样多 —— 直接改用等权就好，还省掉一整套估计误差。',
    )
  }
  if (!hasSharpe || !hasBench) {
    caveats.push('返回结果里缺夏普比率，无法判断有没有跑赢等权基准。')
  }
  if (verdict === 'not_opt') {
    caveats.push('你选的优化目标本身就是「等权」，所以这一栏没有「打赢自己」可言 —— 它只是给你一个可以拿去比对的及格线。')
  }
  if (total > 1 && effectiveN > 0 && effectiveN < total * 0.5) {
    caveats.push(
      `你放了 ${total} 个标的，但有效标的数只有 ${fmtNum(effectiveN, 1)} —— 权重高度集中在少数几个标的上，名义上的分散并没有真的发生。`,
    )
  }
  if (clusters.length > 0) {
    caveats.push(
      `检测到 ${clusters.length} 组高相关簇（同涨同跌的标的）。簇内的权重被限制住了，这是为了防「伪分散」，但也会压低这组权重的历史表现。`,
    )
  }
  if (gross > 0 && gross < 0.99) {
    caveats.push(`总仓位只有 ${fmtRatioPct(gross, 0)}，剩下的是现金。和满仓的等权基准直接比夏普会失真。`)
  }

  return {
    verdict,
    sharpe,
    benchSharpe,
    delta,
    effectiveN,
    gross,
    synthetic,
    allSynthetic,
    clusters,
    caveats,
  }
}

/** 跑之前的一句话预览：让人知道「我现在要干什么」。 */
export function PlanSummary({
  poolName,
  symbols,
  objectiveLabel,
  start,
  maxWeight,
  maxGross,
}: {
  poolName: string
  symbols: string[]
  objectiveLabel: string
  start: string
  maxWeight: number
  maxGross: number
}) {
  const list = symbols.length ? symbols.join('、') : '（还没填标的）'
  return (
    <div className="rounded-lg border border-brand-100 bg-brand-50/60 px-3.5 py-3 text-xs leading-6 text-slate-700">
      <span className="mr-1 rounded bg-white px-1.5 py-0.5 text-[10px] font-medium text-brand-700 ring-1 ring-brand-200">
        本次要做什么
      </span>
      拿
      <span className="mx-0.5 font-semibold text-slate-900">{list}</span>
      这 {symbols.length} 个标的（
      {poolName ? `快捷池「${poolName}」` : '自定义'}），用
      <span className="mx-0.5 font-semibold text-slate-900">{start || '（起始日）'}</span>
      至今的历史数据，按
      <span className="mx-0.5 font-semibold text-slate-900">{objectiveLabel || '（还没选目标）'}</span>
      这个目标去算「每个该买多少」；限制是单个标的最多占
      <span className="mx-0.5 font-semibold text-slate-900">{maxWeight}%</span>
      、总共投出去
      <span className="mx-0.5 font-semibold text-slate-900">{maxGross}%</span>
      。算完会和
      <TermTip id="equal_weight">等权基准</TermTip>
      对比 —— 打不过它就别用这套权重。
    </div>
  )
}

/**
 * 跑完之后的大白话结论。
 * 结构：① 一句话结论 → ② 关键对比数字 → ③ 风险与前提提示。
 */
export function ResultSummary({
  result,
  objectiveLabel,
  benchmarkNote,
}: {
  result: OptResult
  objectiveLabel: string
  /** 等权基准用哪些标的（默认就是输入池，可显式传入） */
  benchmarkNote?: ReactNode
}) {
  const s = summarizeOptimize(result)
  const { verdict, sharpe, benchSharpe, delta, effectiveN, caveats } = s

  const head: { icon: ReactNode; tone: string; text: string } =
    verdict === 'unknown'
      ? {
          icon: <Info className="h-4 w-4" />,
          tone: 'border-sky-200 bg-sky-50 text-sky-900',
          text: s.allSynthetic ? '取不到真实行情，这次结果不能用' : '关键数字缺失，判不了这组权重好不好',
        }
      : verdict === 'infeasible'
        ? {
            icon: <AlertTriangle className="h-4 w-4" />,
            tone: 'border-amber-200 bg-amber-50 text-amber-900',
            text: '你的约束互相矛盾，已退回等权兜底 —— 这不是优化结果',
          }
        : verdict === 'not_opt'
          ? {
              icon: <MinusCircle className="h-4 w-4" />,
              tone: 'border-sky-200 bg-sky-50 text-sky-900',
              text: '你选的就是等权本身，所以只当作一条及格线看',
            }
          : verdict === 'win'
            ? {
                icon: <ThumbsUp className="h-4 w-4" />,
                tone: 'border-emerald-200 bg-emerald-50 text-emerald-900',
                text: '这组权重打赢了等权基准（每个都买一样多）',
              }
            : verdict === 'lose'
              ? {
                  icon: <ThumbsDown className="h-4 w-4" />,
                  tone: 'border-rose-200 bg-rose-50 text-rose-900',
                  text: '这组权重没打赢等权基准 —— 不如每个都买一样多',
                }
              : {
                  icon: <Info className="h-4 w-4" />,
                  tone: 'border-sky-200 bg-sky-50 text-sky-900',
                  text: '这组权重和等权基准基本打平',
                }

  return (
    <div className="space-y-3">
      <div className={`flex items-start gap-2.5 rounded-lg border px-3.5 py-3 ${head.tone}`}>
        <span className="mt-0.5 shrink-0">{head.icon}</span>
        <div className="min-w-0 flex-1">
          <div className="text-sm font-semibold">一句话结论：{head.text}</div>
          <p className="mt-1.5 text-xs leading-6 opacity-90">
            {verdict === 'not_opt' ? (
              <>
                这组权重的<TermTip id="sharpe">夏普比率</TermTip>是{' '}
                <span className="num font-semibold">{fmtNum(sharpe, 2)}</span>
                。把它记下来，然后换成「最大夏普」再跑一次，就知道优化到底有没有多赚到什么。
              </>
            ) : (
              <>
                <TermTip id="objective">优化目标</TermTip>
                「{objectiveLabel}」算出来的组合，夏普比率{' '}
                <span className="num font-semibold">{fmtNum(sharpe, 2)}</span>，而等权基准是{' '}
                <span className="num font-semibold">{fmtNum(benchSharpe, 2)}</span>（
                {delta >= 0 ? '高' : '低'}了 <span className="num font-semibold">{fmtNum(Math.abs(delta), 2)}</span>）。
                {verdict === 'win' && ' 不过打赢的幅度要结合下面几条一起看，别只看这一个数。'}
              </>
            )}
            {benchmarkNote}
            {effectiveN > 0 && (
              <>
                {' '}
                名义上放了 {result.symbols?.length ?? 0} 个标的，<TermTip id="effective_n">有效标的数</TermTip>只有{' '}
                <span className="num font-semibold">{fmtNum(effectiveN, 1)}</span>。
              </>
            )}
          </p>
        </div>
      </div>

      {caveats.length > 0 && (
        <div className="rounded-lg border border-amber-200 bg-amber-50 px-3.5 py-3">
          <div className="flex items-center gap-1.5 text-xs font-semibold text-amber-900">
            <AlertTriangle className="h-3.5 w-3.5" />
            用这组权重之前，先知道这几件事
          </div>
          <ul className="mt-1.5 space-y-1 text-xs leading-6 text-amber-900/90">
            {caveats.map((c, i) => (
              <li key={i} className="flex gap-1.5">
                <span className="shrink-0">·</span>
                <span>{c}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {caveats.length === 0 && (
        <div className="flex items-center gap-1.5 rounded-lg border border-emerald-200 bg-emerald-50 px-3.5 py-2.5 text-xs text-emerald-900">
          <CheckCircle2 className="h-3.5 w-3.5 shrink-0" />
          没发现明显问题。仍然建议
          <span className="font-semibold">换一段时间区间再跑一次</span>
          —— 两次结论一致，才说明这组权重不是拟合出来的。
        </div>
      )}

      <p className="text-[11px] leading-5 text-slate-400">
        下面每个指标名都可以把鼠标放上去，看它「是什么 / 怎么看」。权重是基于历史数据的估计，
        <TermTip id="cov_method">协方差</TermTip>与
        <TermTip id="return_method">期望收益</TermTip>
        都来自过去，不构成任何投资建议。
      </p>
    </div>
  )
}
