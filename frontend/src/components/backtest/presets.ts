/**
 * 回测中心预设值
 * ===============
 * 小白不可能知道「SPY 是什么」「回测多久合适」「哪个策略简单」。
 * 所以这里把「有依据的默认值」集中成数据，由 ConfigPanel 渲染成**一键按钮**。
 *
 * ⚠️ `BEGINNER_STRATEGIES` 的 key 必须与后端 `app/strategies/builtin_*.py` 里
 *    类的 `key` 一致。写错的话按钮点下去策略下拉框不会变，界面上毫无报错 ——
 *    所以 render-check 里有断言：这些 key 必须都能在 /strategies 返回里找到。
 *    这里只放**规则可一句话讲清**的策略，机器学习/多因子类刻意不放。
 */
import type { StrategyInfo } from '../../lib/types'

/** 推荐的入门策略：规则能用一句话讲明白，且不依赖黑箱模型。 */
export const BEGINNER_STRATEGIES: { key: string; why: string }[] = [
  {
    key: 'dual_ma_trend',
    why: '最简单的趋势规则：短期均线跑到长期均线上方就买入，跌破就卖出。适合长期向上的大盘指数。',
  },
  {
    key: 'vol_managed_momentum',
    why: '在动量策略基础上，按波动率自动调整仓位 —— 市场越乱，买得越少。',
  },
  {
    key: 'dual_momentum',
    why: '在几个标的里挑最近表现最强的那个持有，其余空仓。经典的「追强避弱」。',
  },
  {
    key: 'trend_composite',
    why: '让多个趋势指标一起投票，分数够了才买入。信号更稳，但反应更慢。',
  },
]

/** 一键勾选的常见标的。value 必须是美股代码。 */
export const SYMBOL_PRESETS: { value: string; label: string; note: string }[] = [
  { value: 'SPY', label: 'SPY', note: '标普500指数基金 · 最常用的大盘' },
  { value: 'QQQ', label: 'QQQ', note: '纳斯达克100指数基金 · 偏科技' },
  { value: 'AAPL', label: 'AAPL', note: '苹果 · 单只个股' },
  { value: 'MSFT', label: 'MSFT', note: '微软 · 单只个股' },
]

/** 对比基准候选。后端在 benchmark 为空时会回落成 SPY，所以这里不提供「不对比」。 */
export const BENCHMARK_PRESETS: { value: string; label: string }[] = [
  { value: 'SPY', label: 'SPY 标普500' },
  { value: 'QQQ', label: 'QQQ 纳斯达克100' },
  { value: 'DIA', label: 'DIA 道琼斯' },
]

/** 回测时长预设（年）。`end` 留空 = 到今天。 */
export const PERIOD_PRESETS: { years: number; label: string }[] = [
  { years: 1, label: '近 1 年' },
  { years: 3, label: '近 3 年' },
  { years: 5, label: '近 5 年' },
  { years: 10, label: '近 10 年' },
]

/** 本地时区的 n 年前日期（YYYY-MM-DD）。
 *  ⚠️ 实现已移到 `lib/dateRange.ts` —— 组合优化页也要用同一个函数，
 *     复制一份等于让「UTC 会得到昨天」这个坑各自漂移一次。这里保留再导出，
 *     是为了不让既有 import 路径（`./presets`）发生无谓变动。 */
export { yearsAgo } from '../../lib/dateRange'

/** 一键推荐配置：只依赖稳定存在的 key，任何一个对不上都会在 render-check 里报出来。 */
export const RECOMMENDED = {
  strategyKey: 'dual_ma_trend',
  symbols: 'SPY',
  years: 5,
  capital: 100000,
  benchmark: 'SPY',
  interval: '1d',
  commission: 1,
  slippage: 2,
  dataSource: 'auto',
  stopType: 'none',
  sizing: 'weight',
}

/**
 * 进阶策略分类 —— 命中时给出「这是进阶内容」的提示。
 * 依据是后端策略文件里的 `category`，不是前端自己编的分类。
 */
export const ADVANCED_CATEGORIES = ['进阶前沿', '日内微观']

/** 某个策略是否在入门推荐名单里。 */
export function isBeginnerStrategy(s: StrategyInfo | null | undefined): boolean {
  return !!s && BEGINNER_STRATEGIES.some((b) => b.key === s.key)
}
