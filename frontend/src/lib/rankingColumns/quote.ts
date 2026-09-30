/**
 * 榜单列定义 · 行情与股本派生列
 *
 * 从 `lib/rankingColumns.ts` 拆出（铁律 9）。列顺序 = 数组顺序，
 * 三组按 base → quote → technical 拼接，与拆分前完全一致。
 */
import type { RankingColumn } from './types'

export const QUOTE_COLUMNS: RankingColumn[] = [
  {
    key: 'volume',
    label: '成交量',
    align: 'right',
    width: 64,
    sortable: true,
    tip: {
      title: '成交量',
      what: '当日成交股数。',
      how: '与平时成交量比才有意义：突然放量往往意味着有重要消息或资金异动。',
    },
  },
  {
    key: 'eps_ttm',
    label: 'EPS',
    align: 'right',
    width: 60,
    sortable: true,
    tip: {
      title: '每股收益 EPS（TTM）',
      what: '最近 12 个月净利润 ÷ 总股本。',
      how: '本页的 PE 就是用「现价 ÷ 这个 EPS」实时算出来的，所以你可以自己验算。EPS 持续增长而股价没涨，说明估值在变便宜。',
      warn: '亏损公司为负值，此时 PE 不显示。',
    },
  },
  {
    key: 'turnover',
    label: '换手率',
    align: 'right',
    width: 60,
    sortable: true,
    tip: {
      title: '换手率',
      what: '当日成交股数 ÷ 流通股本，反映筹码转手的活跃程度。',
      how: '适度放大（1%~3%）通常是好事；长期极低说明无人问津，极度过高（> 10%）常伴随炒作。',
    },
  },
  {
    key: 'amplitude',
    label: '振幅',
    align: 'right',
    width: 60,
    sortable: true,
    tip: {
      title: '振幅',
      what: '（当日最高 − 当日最低）÷ 昨收，衡量当天价格波动幅度。',
      how: '振幅大意味着日内机会与风险都更大；做短线要看它，做长线意义不大。',
    },
  },
  {
    key: 'w52_high',
    label: '52 周高',
    align: 'right',
    width: 64,
    sortable: true,
    tip: {
      title: '52 周最高价',
      what: '过去 52 周内的最高成交价。',
      how: '常被视为关键压力位；突破它往往被趋势策略视为买点。',
    },
  },
  {
    key: 'w52_low',
    label: '52 周低',
    align: 'right',
    width: 64,
    sortable: true,
    tip: {
      title: '52 周最低价',
      what: '过去 52 周内的最低成交价。',
      how: '常被视为关键支撑位；跌破它常触发止损与恐慌性抛售。',
    },
  },
  {
    key: 'market_cap_float',
    label: '流通市值',
    align: 'right',
    width: 74,
    sortable: true,
    tip: {
      title: '流通市值',
      what: '可自由交易的股份 × 现价（不含限售/内部人持股）。',
      how: '衡量真实可交易的盘子大小。指数编制、被动资金流入更多看流通市值而非总市值。',
    },
  },
]
