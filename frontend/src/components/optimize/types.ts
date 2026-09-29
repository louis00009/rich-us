/**
 * 组合优化共享类型
 * =================
 * 抽成独立文件是为了打断 ConfigPanel ↔ ResultPanel ↔ 页面的循环引用 ——
 * 这三个地方互相需要对方的 props 类型，类型放在任一方的文件里都会形成环。
 */

/** `/optimize/meta` 的返回结构。 */
export interface Meta {
  objectives: { key: string; label: string; desc: string }[]
  cov_methods: { key: string; label: string; desc: string }[]
  return_methods: { key: string; label: string; desc: string }[]
  defaults: Record<string, any>
  notes: string[]
}

/** 一组权重的统计量。组合本身与等权基准都是这个结构。 */
export interface PStats {
  ann_return: number
  ann_vol: number
  sharpe: number
  diversification_ratio: number
  effective_n: number
  risk_concentration: number
  gross: number
}

/** 逐个标的的明细（权重表与导出 CSV 用）。 */
export interface AssetStat {
  symbol: string
  weight: number
  ann_return: number
  ann_vol: number
  sharpe: number
  max_drawdown: number
  risk_contrib_pct: number
  obs: number
}

/** `/optimize/run` 的完整返回。 */
export interface OptResult {
  ok: boolean
  objective: string
  symbols: string[]
  weights: Record<string, number>
  feasible: boolean
  infeasible_reason: string
  portfolio: PStats
  benchmark_equal_weight: PStats
  assets: AssetStat[]
  correlation: { symbols: string[]; matrix: number[][] }
  clusters: string[][]
  frontier: { lambda: number; ret: number; vol: number; sharpe: number }[]
  constraints: Record<string, any>
  params: Record<string, any>
  notes: string[]
  data_sources: Record<string, string>
  data_source_used: string
  synthetic_symbols: string[]
}

/** 配置项的**值**（全部来自 Optimize.tsx 的 state）。 */
export interface OptForm {
  /** 标的池，逗号/空格分隔的原始文本 */
  symbolsText: string
  start: string
  interval: string
  objective: string
  covMethod: string
  returnMethod: string
  /** 以下均为**百分数**（35 = 35%），发给后端前统一除以 100 */
  maxWeight: number
  maxGross: number
  corrThreshold: number
  maxCluster: number
  riskFree: number
  longOnly: boolean
  useBudget: boolean
  budgetText: string
  includeFrontier: boolean
}

/** 配置项的**写回函数**。 */
export interface OptSetters {
  setSymbolsText: (v: string) => void
  setStart: (v: string) => void
  setInterval: (v: string) => void
  setObjective: (v: string) => void
  setCovMethod: (v: string) => void
  setReturnMethod: (v: string) => void
  setMaxWeight: (v: number) => void
  setMaxGross: (v: number) => void
  setCorrThreshold: (v: number) => void
  setMaxCluster: (v: number) => void
  setRiskFree: (v: number) => void
  setLongOnly: (v: boolean) => void
  setUseBudget: (v: boolean) => void
  setBudgetText: (v: string) => void
  setIncludeFrontier: (v: boolean) => void
}
