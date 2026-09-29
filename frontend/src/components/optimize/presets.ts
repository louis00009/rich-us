/**
 * 组合优化预设值
 * ===============
 * 小白不可能知道「该放哪些标的」「优化目标选哪个」「用多长历史」。
 * 所以把有依据的默认值集中成数据，由 ConfigPanel 渲染成一键按钮。
 *
 * ⚠️ `POOL_PRESETS` 的 symbols 会**直接发给后端**，写错代码不会报错，
 *    只会让那一个标的数据拉不到、被静默剔除。所以 render-check 里有断言：
 *    每个池子至少 2 个标的，且都能通过 `parseSymbols` 校验。
 */

/** 一键标的池。`note` 说明这个池子**演示了什么**，而不是只列代码。 */
export const POOL_PRESETS: { name: string; symbols: string; note: string; beginner?: boolean }[] = [
  {
    name: '股债商均衡',
    symbols: 'SPY, TLT, IEF, GLD, DBC, VNQ',
    note: '股票 + 国债 + 黄金 + 商品 + 房产。类别不同、涨跌不同步，最能看出「分散」到底在做什么。新手先用这个。',
    beginner: true,
  },
  {
    name: '核心宽基',
    symbols: 'SPY, QQQ, IWM, EFA, EEM, AGG, GLD',
    note: '美股大中小盘 + 海外 + 新兴市场 + 债券 + 黄金。覆盖面最广的一篮子。',
  },
  {
    name: '科技七巨头',
    symbols: 'AAPL, MSFT, NVDA, GOOGL, AMZN, META, TSLA',
    note: '七只科技巨头。它们高度同涨同跌 —— 用来观察「高相关簇」是怎么把分散效果吃掉的。',
  },
  {
    name: '低相关尝试',
    symbols: 'SPY, TLT, GLD, UUP, XLE, XLK',
    note: '刻意挑方向不同的资产（股票/长债/黄金/美元/能源/科技）。',
  },
]

/** 优化目标的一键选项。key 必须与后端 `OBJECTIVES` 一致。 */
export const OBJECTIVE_PRESETS: { key: string; label: string; why: string }[] = [
  {
    key: 'max_sharpe',
    label: '最大夏普',
    why: '在收益和波动之间取平衡，最常用的默认选择。',
  },
  {
    key: 'min_variance',
    label: '最小方差',
    why: '只压波动、不看收益。想睡得安稳选它。',
  },
  {
    key: 'equal_weight',
    label: '等权',
    why: '每个都买一样多。先跑它拿到及格线，再看别的目标能不能打赢。',
  },
]

/** 历史区间预设（年）。协方差估计需要足够样本，所以偏长。 */
export const PERIOD_PRESETS: { years: number; label: string }[] = [
  { years: 3, label: '近 3 年' },
  { years: 5, label: '近 5 年' },
  { years: 10, label: '近 10 年' },
]

/**
 * 一键推荐配置 —— 第一次用的人点这个就能跑出一个有意义的结果。
 * 刻意选「股债商均衡 + 最大夏普 + 近 5 年」：类别分散、目标稳健、样本够长。
 */
export const RECOMMENDED = {
  pool: '股债商均衡',
  symbols: 'SPY, TLT, IEF, GLD, DBC, VNQ',
  years: 5,
  objective: 'max_sharpe',
  interval: '1d',
  maxWeight: 35,
  maxGross: 100,
  corrThreshold: 85,
  maxCluster: 50,
  riskFree: 0,
  longOnly: true,
  includeFrontier: true,
}

/** 新手模式下的默认优化目标（= 后端 defaults.objective）。 */
export const DEFAULT_OBJECTIVE = 'max_sharpe'

/** 后端默认值，用于「恢复默认参数」。 */
export const BACKEND_DEFAULTS = {
  maxWeightPct: 35,
  maxGrossPct: 100,
  corrThresholdPct: 85,
  maxClusterPct: 50,
  riskFreePct: 0,
}
