/**
 * PlainSummary —— 回测的「人话」总结
 * ===================================
 * 用户原话：「很多东西我都不懂」。所以除了把指标名字挂上悬浮解释，更重要的是
 * **在指标表之前先给一句话结论** —— 小白不会自己去把 24 个指标翻译成结论。
 *
 * 两个组件：
 *   - `PlanSummary`：点「开始回测」**之前**，用一句话复述你即将做什么，
 *     避免「参数填完不知道会发生什么」；
 *   - `ResultSummary`：跑完之后，用大白话给出结论 + 风险提示。
 *
 * ⚠️ **诚实性**：结论只从 `result.metrics` 的真实数字推导，不做任何外推或美化。
 *    尤其「交易次数 < 30」「区间 < 2 年」这两种情况必须**主动泼冷水** ——
 *    本项目自己的复盘结论就是规则化策略经常打不过买入持有，把运气包装成能力
 *    比不做这个功能更糟。
 */
import { AlertTriangle, CheckCircle2, Info, ThumbsDown, ThumbsUp } from 'lucide-react'
import { fmtMoney, fmtNum, fmtRatioPct } from '../../lib/format'
import type { BacktestResult } from '../../lib/types'
import { TermTip } from '../terms/TermTip'

const num = (v: unknown): number => {
  const n = Number(v)
  return Number.isFinite(n) ? n : 0
}

/** 开始回测前的一句话预览：让人知道「我现在要干什么」。 */
export function PlanSummary({
  strategyName,
  symbols,
  start,
  end,
  capital,
  benchmark,
}: {
  strategyName: string
  symbols: string[]
  start: string
  end: string
  capital: number
  benchmark: string
}) {
  const list = symbols.length ? symbols.join('、') : '（还没填股票代码）'
  return (
    <div className="rounded-lg border border-brand-100 bg-brand-50/60 px-3.5 py-3 text-xs leading-6 text-slate-700">
      <span className="mr-1 rounded bg-white px-1.5 py-0.5 text-[10px] font-medium text-brand-700 ring-1 ring-brand-200">
        本次要做什么
      </span>
      用
      <span className="mx-0.5 font-semibold text-slate-900">{strategyName || '（还没选策略）'}</span>
      这套规则，在
      <span className="mx-0.5 font-semibold text-slate-900">{list}</span>
      上，跑一遍
      <span className="mx-0.5 font-semibold text-slate-900">
        {start || '（起始日）'} ~ {end || '今天'}
      </span>
      的历史行情；假设一开始有
      <span className="mx-0.5 font-semibold text-slate-900">{fmtMoney(capital, 0)}</span>
      ，<TermTip id="benchmark">及格线</TermTip>是
      <span className="mx-0.5 font-semibold text-slate-900">{benchmark || 'SPY'}</span>
      （什么都不做、直接买它拿着不动的收益）。
    </div>
  )
}

/**
 * 结论的**纯计算**部分（不含任何 JSX）—— 单独抽出来是为了能被 render-check
 * 直接调用做单元断言。这里最容易出的事故是「字段缺失时按 0 处理」，
 * 那会凭空生成「你跑赢了 0.0% 的基准」这种假结论，而界面上看不出任何异常。
 */
export interface Summary {
  /** unknown = 记录里没有基准数据，根本判不了 */
  verdict: 'win' | 'tie' | 'lose' | 'unknown'
  hasBench: boolean
  hasExcess: boolean
  /** 初始本金：优先用记录自带的，其次才是外部传入 */
  cap: number
  finalEq: number
  tr: number
  benchTr: number
  /** 最大回撤，已取绝对值 */
  mdd: number
  /** 交易样本是否够（>= 30 笔） */
  enough: boolean
  caveats: string[]
}

const finiteNum = (v: unknown) => Number.isFinite(Number(v))

export function summarizeResult(
  metrics: Record<string, any> | undefined,
  bars: number,
  fallbackCapital: number,
): Summary {
  const m = metrics || {}
  const tr = num(m.total_return)
  // ⚠️ 必须先用 Number.isFinite 判断「有没有这个字段」，再决定说不说 ——
  //    直接 Number(undefined) 得到 NaN、num() 得到 0，会变成「基准 0.0%」这种假数字。
  const hasBench = finiteNum(m.benchmark_total_return)
  const hasExcess = finiteNum(m.excess_cagr)
  const benchTr = hasBench ? num(m.benchmark_total_return) : 0
  const exCagr = hasExcess ? num(m.excess_cagr) : 0
  const mdd = Math.abs(num(m.max_drawdown))
  const trades = num(m.trades)
  const turnover = num(m.turnover)
  const exposure = num(m.avg_exposure)
  const cap = num(m.initial_capital) || fallbackCapital
  const finalEq = num(m.final_equity) || cap * (1 + tr)

  // 阈值说明：excess_cagr 是年化口径，±2 个百分点以内视为「和基准基本打平」，
  // 避免把统计噪声当成能力。
  const enough = trades >= 30
  let verdict: Summary['verdict'] = 'unknown'
  if (hasExcess) {
    if (exCagr > 0.02) verdict = 'win'
    else if (exCagr < -0.02) verdict = 'lose'
    else verdict = 'tie'
  }

  // 风险提示：只列真实命中项，不凑数
  const caveats: string[] = []
  if (!hasExcess) caveats.push('这条回测记录里没有存基准收益与超额收益，所以「有没有跑赢」这一项无法判断。')
  if (!enough) caveats.push(`整段只成交了 ${trades} 笔。样本这么少，结果很可能只是运气好/运气差，不能作为判断依据。`)
  if (bars > 0 && bars < 500) caveats.push(`回测区间不到 2 年（约 ${bars} 根 K 线），至少要看 3~5 年才比较可信。`)
  if (mdd > 0.3) caveats.push(`最大回撤 ${fmtRatioPct(mdd, 1)} 太深了，实盘中绝大多数人会在中途放弃。`)
  if (verdict === 'lose' && enough) caveats.push('没有超额收益，说明这套规则只是换了个方式承担风险，不值得用真钱去跑。')
  if (turnover > 12) caveats.push(`换手率 ${fmtNum(turnover, 1)}x 偏高，手续费和滑点的侵蚀已经很可观，上面的收益是扣完成本后的净值。`)
  if (exposure > 0 && exposure < 0.3) caveats.push(`平均只有 ${fmtRatioPct(exposure, 0)} 的资金在市场里，大部分时间空仓，和满仓基准直接比会失真。`)

  return { verdict, hasBench, hasExcess, cap, finalEq, tr, benchTr, mdd, enough, caveats }
}

/**
 * 跑完之后的大白话结论。
 *
 * 结构刻意做成「先结论 → 再数字 → 再泼冷水」：
 *   ① 一句话结论（跑赢 / 打平 / 没跑赢 / 判不了），
 *   ② 三个最直观的数字（本金变多少、和及格线差多少、最惨浮亏多少），
 *   ③ 风险提示（样本太少 / 回撤太深 / 换手太高 / 区间太短）。
 *
 * 全部数字来自 `summarizeResult`（纯函数），缺失字段一律如实说缺，绝不拿 0 顶替。
 */
export function ResultSummary({
  result,
  capital,
  benchmark,
}: {
  result: BacktestResult
  capital: number
  benchmark: string
}) {
  const s = summarizeResult(result.metrics, Number(result.bars) || 0, capital)
  const { verdict, hasBench, cap, finalEq, tr, benchTr, mdd, enough, caveats } = s
  const benchName = benchmark || 'SPY'

  const head =
    verdict === 'unknown'
      ? {
          icon: <Info className="h-4 w-4" />,
          tone: 'border-sky-200 bg-sky-50 text-sky-900',
          text: '这条记录没有保存对比基准的数据，无法判断有没有跑赢及格线',
        }
      : !enough
        ? {
            icon: <Info className="h-4 w-4" />,
            tone: 'border-sky-200 bg-sky-50 text-sky-900',
            text: '样本太少，这个结果先别当真',
          }
        : verdict === 'win'
          ? {
              icon: <ThumbsUp className="h-4 w-4" />,
              tone: 'border-emerald-200 bg-emerald-50 text-emerald-900',
              text: `在这段历史里，它跑赢了及格线（${benchName}）`,
            }
          : verdict === 'lose'
            ? {
                icon: <ThumbsDown className="h-4 w-4" />,
                tone: 'border-rose-200 bg-rose-50 text-rose-900',
                text: `它没跑赢及格线（${benchName}）—— 不如直接买它拿着`,
              }
            : {
                icon: <Info className="h-4 w-4" />,
                tone: 'border-sky-200 bg-sky-50 text-sky-900',
                text: `它和及格线（${benchName}）基本打平`,
              }

  return (
    <div className="space-y-3">
      <div className={`flex items-start gap-2.5 rounded-lg border px-3.5 py-3 ${head.tone}`}>
        <span className="mt-0.5 shrink-0">{head.icon}</span>
        <div className="min-w-0 flex-1">
          <div className="text-sm font-semibold">一句话结论：{head.text}</div>
          <p className="mt-1.5 text-xs leading-6 opacity-90">
            {fmtMoney(cap, 0)} 变成 <span className="num font-semibold">{fmtMoney(finalEq, 0)}</span>（
            {fmtRatioPct(tr, 1, true)}）。
            {hasBench ? (
              <>
                同期<TermTip id="benchmark">及格线</TermTip>（什么都不做、直接买 {benchName} 拿着）是{' '}
                <span className="num font-semibold">{fmtRatioPct(benchTr, 1, true)}</span>
                {tr !== benchTr && (
                  <>
                    ，你比它{tr > benchTr ? '多' : '少'}赚了{' '}
                    <span className="num font-semibold">{fmtRatioPct(Math.abs(tr - benchTr), 1)}</span>
                  </>
                )}
                。
              </>
            ) : (
              <>这条记录里没有存及格线的收益，所以没法做对比。</>
            )}{' '}
            最难受的时候账户浮亏 <span className="num font-semibold">{fmtRatioPct(mdd, 1)}</span>
            （约 <span className="num">{fmtMoney(finalEq * mdd, 0)}</span>）。
          </p>
        </div>
      </div>

      {caveats.length > 0 && (
        <div className="rounded-lg border border-amber-200 bg-amber-50 px-3.5 py-3">
          <div className="flex items-center gap-1.5 text-xs font-semibold text-amber-900">
            <AlertTriangle className="h-3.5 w-3.5" />
            看这些数字之前，先知道这几件事
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

      {caveats.length === 0 && enough && hasBench && (
        <div className="flex items-center gap-1.5 rounded-lg border border-emerald-200 bg-emerald-50 px-3.5 py-2.5 text-xs text-emerald-900">
          <CheckCircle2 className="h-3.5 w-3.5 shrink-0" />
          交易样本、回测区间、回撤深度都在合理范围内。仍然建议
          <span className="font-semibold">换一个时间区间再跑一次</span>
          ，两次都好才算真的稳。
        </div>
      )}

      <p className="text-[11px] leading-5 text-slate-400">
        下面每个指标名都可以把鼠标放上去，看它「是什么 / 怎么看」。本结果基于历史数据模拟，
        <TermTip id="benchmark">基准</TermTip>
        之外没有考虑税费、融资利息与真实成交滑点差异，不构成任何投资建议。
      </p>
    </div>
  )
}
