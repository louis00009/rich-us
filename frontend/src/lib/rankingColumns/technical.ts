/**
 * 榜单列定义 · 1 年日线派生的技术指标列（默认隐藏，在「列」菜单里打开）
 *
 * 从 `lib/rankingColumns.ts` 拆出（铁律 9）。列顺序 = 数组顺序，
 * 三组按 base → quote → technical 拼接，与拆分前完全一致。
 */
import type { RankingColumn } from './types'

export const TECHNICAL_COLUMNS: RankingColumn[] = [
  /* ---------- 以下为 1 年日线派生的技术指标（默认隐藏，在「列」里打开） ---------- */
  {
    key: 'ma200_rel',
    label: '距 MA200',
    align: 'right',
    width: 72,
    sortable: true,
    tip: {
      title: '现价相对 200 日均线',
      what: '（现价 − 200 日均线）÷ 200 日均线。200 日均线是最经典的中长期多空分界。',
      how: '正值 = 站在均线上方（中期趋势向上），负值 = 跌破（趋势偏弱）。经验上 +10% 以上偏强、-10% 以下偏弱。',
      warn: '均线是滞后指标：它在趋势已经走完之后才转向。单看它无法判断贵贱，必须和估值一起看。',
    },
  },
  {
    key: 'ma20_rel',
    label: '距 MA20',
    align: 'right',
    width: 68,
    sortable: true,
    tip: {
      title: '现价相对 20 日均线',
      what: '（现价 − 20 日均线）÷ 20 日均线，反映最近一个月的短期强弱。',
      how: '短线择时用它：偏离过大（如 +15%）往往意味着短期超买。中长线投资者看 MA200 更有意义。',
    },
  },
  {
    key: 'ma_bull',
    label: '多头排列',
    align: 'right',
    width: 70,
    sortable: true,
    tip: {
      title: '均线多头排列',
      what: '是否满足「现价 > MA20 > MA60 > MA200」这一经典强势结构。',
      how: '满足时说明短、中、长期三个周期的持仓成本依次抬升，是趋势最健康的状态。勾选上方「只看多头排列」即可筛出。',
      warn: '多头排列说明「趋势正在向上」，不代表现在买入便宜 —— 强势股往往估值也在高位。',
    },
  },
  {
    key: 'r1y',
    label: '近 1 年',
    align: 'right',
    width: 68,
    sortable: true,
    tip: {
      title: '近 1 年涨跌幅',
      what: '过去 251 个交易日的累计涨跌幅。',
      how: '衡量中长期动量。配合「相对 SPY 超额」看更有意义：大盘整体涨了 20% 时，个股涨 15% 其实是跑输的。',
    },
  },
  {
    key: 'excess_1y',
    label: '超额 1Y',
    align: 'right',
    width: 70,
    sortable: true,
    tip: {
      title: '相对 SPY 超额收益（1 年）',
      what: '个股近 1 年涨跌幅 − SPY（标普 500 ETF）同期涨跌幅。',
      how: '这才是真正衡量「这只股票有没有跑赢大盘」的指标。正值 = 跑赢。看动量时它比绝对涨幅有用得多，因为已经扣掉了大盘整体的涨跌。',
    },
  },
  {
    key: 'r3m',
    label: '近 3 月',
    align: 'right',
    width: 68,
    sortable: true,
    tip: {
      title: '近 3 月涨跌幅',
      what: '过去 63 个交易日的累计涨跌幅。',
      how: '中期动量。3 个月与 1 年一起看：都在涨说明趋势一致；1 年涨但 3 月跌，可能是趋势转弱。',
    },
  },
  {
    key: 'rsi14',
    label: 'RSI',
    align: 'right',
    width: 56,
    sortable: true,
    tip: {
      title: 'RSI(14) 相对强弱指标',
      what: '衡量近期涨跌力量对比的震荡指标，取值 0~100。计算上比较了近 14 个交易日的平均涨幅与平均跌幅。',
      how: '常用读法：> 70 视为超买（短期涨幅过大）、< 30 视为超卖（短期跌幅过大）、50 附近为中性。震荡市里做反向参考，趋势市里它会在超买区长期钝化。',
      warn: '强趋势中 RSI 可以长期停在 70 以上（钝化），此时「超买」并不意味着要跌。不要把它当成卖出信号单独使用。',
    },
  },
  {
    key: 'vol_ann',
    label: '波动率',
    align: 'right',
    width: 68,
    sortable: true,
    tip: {
      title: '年化波动率',
      what: '日收益率的标准差 × √252，把日波动折算成一年的波动幅度。',
      how: '衡量风险最直接的指标。约 15~20% 属低波动（大盘蓝筹常见），30% 以上偏高，60% 以上属高波动。同样收益下波动越低越好。',
      warn: '波动率只描述「晃得厉害不厉害」，不区分上涨还是下跌 —— 一只翻倍股也会显示高波动率。',
    },
  },
  {
    key: 'beta',
    label: 'Beta',
    align: 'right',
    width: 58,
    sortable: true,
    tip: {
      title: 'Beta（相对 SPY）',
      what: '个股涨跌相对标普 500 的放大幅度。计算时按日期对齐了两条日线序列（避免停牌/新股造成的错位）。',
      how: 'Beta = 1 与大盘同步；> 1 涨跌都更猛（1.5 意味着大盘涨 1%，它平均涨 1.5%）；< 1 更稳；接近 0 或为负说明与大盘走势关联弱（如 BRK-B、黄金股）。做组合时用它估算整体风险敞口。',
    },
  },
]
