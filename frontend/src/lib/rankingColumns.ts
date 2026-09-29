/**
 * 美股榜单的列定义 + 每个指标的「是什么 / 怎么看」说明文案。
 *
 * 抽成数据而不是散在 JSX 里：列顺序、默认可见性、宽度、说明文案都只在这里定义，
 * 表格组件只负责渲染 —— 加一个指标不用碰任何组件逻辑。
 */

export interface MetricTipText {
  title: string
  what: string
  how: string
  warn?: string
}

export interface RankingColumn {
  key: string
  label: string
  align: 'left' | 'right'
  /** 列宽（px，用于 colgroup）。窄屏靠外层横向滚动。 */
  width: number
  sortable?: boolean
  /** 默认是否显示（其余可在「列」菜单里打开） */
  defaultOn?: boolean
  tip: MetricTipText
}

export const RANKING_COLUMNS: RankingColumn[] = [
  {
    key: 'score',
    label: '综合评分',
    align: 'right',
    width: 92,
    sortable: true,
    defaultOn: true,
    tip: {
      title: '综合评分（候选观察池依据）',
      what: '把「估值 / 质量 / 位置 / 趋势」四个维度各自打 0~100 分后加权成的总分。每一分都能溯源：鼠标移到分数上可以看到四个维度分别得了多少、各自的理由。',
      how: '分数越高说明这四个维度越没有明显短板，越值得你逐个去看。默认 ≥ 70 分归入「候选观察池」—— 阈值可以在上方拖。',
      warn: '这不是买入信号。本项目的复盘结论是：规则化策略在收益上打不过买入持有，真实价值在回撤控制。这个分数只做一件事 —— 把 500 多只缩到你愿意逐个看的一小撮。缺数据的维度不计入总分（权重重新归一），此类标的会标「数据不全」，分数仅供参考。',
    },
  },
  {
    key: 'signals',
    label: '关注信号',
    align: 'left',
    width: 172,
    defaultOn: true,
    tip: {
      title: '关注信号（选股中心）',
      what: '由确定性规则生成的机会 / 风险提示：红色 = 机会（如「同行业便宜 + 盈利强」），橙色 = 风险（如「短期超买」「股息陷阱嫌疑」）。每个信号必须同时满足多个独立条件才会亮灯，悬停可以看到触发时的具体数值。',
      how: '把它当作「为什么这只出现在眼前」的一行摘要：有红色信号 → 值得点开公司档案细看；有橙色信号 → 看的时候多留个心眼。点击信号可以在下方筛选出同类标的。',
      warn: '信号是筛选辅助，不是买入信号。每个信号都有明确的失效场景（悬停可见）—— 例如强趋势中「超买」可以长期钝化，深度回撤可能是基本面真的坏了。',
    },
  },
  {
    key: 'symbol',
    label: '代码 / 名称',
    align: 'left',
    width: 116,
    sortable: true,
    defaultOn: true,
    tip: {
      title: '代码 / 名称',
      what: '美股代码（如 AAPL）与公司名。中文名来自腾讯行情，点代码或名称可打开公司档案。',
      how: '点列头按字母排序，便于在一长串里定位某只股票。',
    },
  },
  {
    key: 'price',
    label: '现价',
    align: 'right',
    width: 64,
    sortable: true,
    defaultOn: true,
    tip: {
      title: '现价',
      what: '最新成交价（美元）。数据来自行情源，可能有十几分钟延迟。',
      how: '与「距 52 周高」一起看，能快速判断这只股票处在什么位置。',
    },
  },
  {
    key: 'change_pct',
    label: '涨跌幅',
    align: 'right',
    width: 70,
    sortable: true,
    defaultOn: true,
    tip: {
      title: '涨跌幅',
      what: '相对上一交易日收盘价的涨跌百分比。',
      how: '红色为上涨、绿色为下跌（A 股配色习惯，可在设置里切换）。按降序看就是当日强势榜。',
      warn: '单日涨跌幅噪音很大，不适合作为选股依据；它衡量的是情绪，不是价值。',
    },
  },
  {
    key: 'amount',
    label: '成交额',
    align: 'right',
    width: 64,
    sortable: true,
    defaultOn: true,
    tip: {
      title: '成交额',
      what: '当日成交金额 = 现价 × 成交量。',
      how: '衡量流动性。成交额太小的标的买卖价差大、冲击成本高，不适合重仓。',
    },
  },
  {
    key: 'market_cap',
    label: '总市值',
    align: 'right',
    width: 66,
    sortable: true,
    defaultOn: true,
    tip: {
      title: '总市值',
      what: '总股本 × 现价，代表市场对这家公司的整体定价。',
      how: '大盘股（> 1000 亿美元）流动性好、波动小；小盘股弹性大但风险高。',
      warn: '注意与「流通市值」区分：存在大量未流通股份的公司，两者差异可能很大。',
    },
  },
  {
    key: 'pe_ttm',
    label: '市盈率 PE',
    align: 'right',
    width: 96,
    sortable: true,
    defaultOn: true,
    tip: {
      title: '市盈率 PE（TTM）',
      what: '现价 ÷ 最近 12 个月每股收益。通俗说就是「按当前盈利能力，多少年回本」。',
      how: '越低越便宜，但必须和同行业比。参考：< 15 偏低、15~25 常见、> 40 偏贵（高成长科技股例外）。后面的色条是它在同行业里的分位：越靠左越便宜，越靠右越贵。',
      warn: '亏损公司 PE 没有意义（显示「亏损」）；一次性损益会让 PE 严重失真（卖资产、大额减值都会扭曲）；PE > 200 已单独标记为「异常」，不参与估值排序。周期股在盈利高点时 PE 反而最低，是典型陷阱。',
    },
  },
  {
    key: 'pb',
    label: '市净率 PB',
    align: 'right',
    width: 56,
    sortable: true,
    defaultOn: true,
    tip: {
      title: '市净率 PB',
      what: '现价 ÷ 每股净资产，衡量股价相对公司账面价值贵多少。',
      how: '最适合银行、保险、地产、公用事业等重资产行业：< 1 表示股价跌破净资产。轻资产公司（科技、消费品牌）PB 天然很高，不能拿来横向比。',
      warn: '高 PB 不等于高估 —— 关键看 ROE：只要 ROE 足够高，高 PB 是合理的（PB ≈ PE × ROE）。净资产为负时不显示。',
    },
  },
  {
    key: 'roe',
    label: 'ROE',
    align: 'right',
    width: 60,
    sortable: true,
    defaultOn: true,
    tip: {
      title: 'ROE 净资产收益率',
      what: '公司用股东每 1 元净资产赚回多少利润。本页由 PB ÷ PE 推算（TTM 口径）。',
      how: '这是「质量」指标，与贵不贵无关。长期 > 15% 通常说明有竞争优势（护城河），< 8% 偏弱。最经典的组合筛选是「低 PE + 高 ROE」：又便宜又能赚钱。',
      warn: '高负债会推高 ROE（靠借钱而不是靠盈利能力），所以高 ROE 要结合负债水平看。本页数值由 PB ÷ PE 推算（TTM），与财报披露的加权 ROE 可能有差异；超过 300% 的一律不显示 —— 那通常意味着净资产趋近于 0（大额回购或累计亏损），数字已失去意义。',
    },
  },
  {
    key: 'div_yield',
    label: '股息率',
    align: 'right',
    width: 62,
    sortable: true,
    defaultOn: true,
    tip: {
      title: '股息率',
      what: '每股年度现金分红 ÷ 现价，即只靠分红每年能拿到的现金回报率。',
      how: '拿它和无风险利率（美债收益率）比：明显更高才有吸引力。一般 > 3% 算高股息，适合追求现金流的稳健配置。',
      warn: '异常高的股息率（如 > 8%）往往是股价大跌或一次性特别分红造成的，很可能是「股息陷阱」—— 分红不可持续。不分红的公司显示「—」，这只是公司选择把利润再投资，不代表不好。',
    },
  },
  {
    key: 'pct_from_high',
    label: '距 52 周高',
    align: 'right',
    width: 74,
    sortable: true,
    defaultOn: true,
    tip: {
      title: '距 52 周高',
      what: '（现价 − 52 周最高价）÷ 52 周最高价，单位 %。',
      how: '越接近 0% 越强势（接近年内新高，趋势策略偏好）；-30% 以下属于深度回撤（超跌反弹策略偏好）。它衡量「位置」，不衡量「贵贱」。',
      warn: '强势 ≠ 便宜：接近新高时 PE 往往也在高位。反之跌得多的股票也可能是基本面真的变差了。',
    },
  },
  {
    key: 'sector',
    label: '行业',
    align: 'left',
    width: 132,
    defaultOn: true,
    tip: {
      title: '行业（GICS 一级）',
      what: '公司所属行业分类（GICS 口径），来自 S&P 500 / NASDAQ 100 / S&P 400 成分快照。',
      how: '估值指标必须在行业内比较：银行 PE 14 和软件 PE 40 可能都算合理。上方的「行业」下拉可以只看某一个行业。',
    },
  },
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

export const COLUMN_MAP: Record<string, RankingColumn> = Object.fromEntries(
  RANKING_COLUMNS.map((c) => [c.key, c]),
)

export const DEFAULT_VISIBLE: string[] = RANKING_COLUMNS.filter((c) => c.defaultOn).map((c) => c.key)
