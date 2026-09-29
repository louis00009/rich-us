/**
 * 回测中心共享类型
 * =================
 * 抽成独立文件是为了打断 ConfigPanel ↔ AdvancedSettings 的循环引用 ——
 * 这两个组件互相需要对方的 props 类型，类型放在任一方的文件里都会形成环。
 */

/** `/backtest/meta` 的返回结构。 */
export interface MetaResp {
  metrics: { key: string; label: string; fmt: string }[]
  stop_types: { key: string; label: string; desc: string }[]
  sizing_methods: { key: string; label: string; desc: string }[]
  objectives: { key: string; label: string }[]
}

/** 配置项的**值**（全部来自 Backtest.tsx 的 state）。 */
export interface ConfigForm {
  strategyKey: string
  customId: number | ''
  symbols: string
  start: string
  end: string
  interval: string
  capital: number
  commission: number
  slippage: number
  benchmark: string
  stopType: string
  stopValue: number
  takeProfitR: number
  timeStop: number
  sizing: string
  riskPct: number
  dataSource: string
  params: Record<string, any>
}

/** 配置项的**写回函数**。 */
export interface ConfigSetters {
  setSymbols: (v: string) => void
  setStart: (v: string) => void
  setEnd: (v: string) => void
  setInterval: (v: string) => void
  setCapital: (v: number) => void
  setCommission: (v: number) => void
  setSlippage: (v: number) => void
  setBenchmark: (v: string) => void
  setStopType: (v: string) => void
  setStopValue: (v: number) => void
  setTakeProfitR: (v: number) => void
  setTimeStop: (v: number) => void
  setSizing: (v: string) => void
  setRiskPct: (v: number) => void
  setDataSource: (v: string) => void
  setParams: (v: Record<string, any>) => void
}

/** 风控设置（主面板 → 多策略对比弹窗共用同一套）。 */
export interface RiskSettings {
  stopType: string
  stopValue: number
  takeProfitR: number
  timeStop: number
  sizing: string
  riskPct: number
}
