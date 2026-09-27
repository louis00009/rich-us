/**
 * 格式化工具
 * 配色遵循中国习惯：涨=红，跌=绿（可在设置中切换为欧美习惯）
 */
export type ColorMode = 'cn' | 'us'

let colorMode: ColorMode = (localStorage.getItem('qd_colormode') as ColorMode) || 'cn'
export function setColorMode(m: ColorMode) {
  colorMode = m
  localStorage.setItem('qd_colormode', m)
}
export function getColorMode(): ColorMode {
  return colorMode
}

/** 上涨色（CSS 值） */
export function upColor(): string {
  return colorMode === 'cn' ? '#e11d48' : '#059669'
}
export function downColor(): string {
  return colorMode === 'cn' ? '#059669' : '#e11d48'
}
export function upClass(): string {
  return colorMode === 'cn' ? 'text-rose-600' : 'text-emerald-600'
}
export function downClass(): string {
  return colorMode === 'cn' ? 'text-emerald-600' : 'text-rose-600'
}
/** 依据数值正负返回涨/跌色类 */
export function signClass(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v) || v === 0) return 'text-slate-500'
  return v > 0 ? upClass() : downClass()
}
export function signColor(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v) || v === 0) return '#64748b'
  return v > 0 ? upColor() : downColor()
}

/* ---------------- 数值 ---------------- */
export function fmtNum(v: any, digits = 2): string {
  const n = Number(v)
  if (v === null || v === undefined || Number.isNaN(n)) return '—'
  return n.toLocaleString('en-US', { minimumFractionDigits: digits, maximumFractionDigits: digits })
}

export function fmtMoney(v: any, digits = 2, symbol = '$'): string {
  const n = Number(v)
  if (v === null || v === undefined || Number.isNaN(n)) return '—'
  const sign = n < 0 ? '-' : ''
  return `${sign}${symbol}${Math.abs(n).toLocaleString('en-US', {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  })}`
}

/** 大额金额缩写：1.23M / 45.6K */
export function fmtCompact(v: any): string {
  const n = Number(v)
  if (v === null || v === undefined || Number.isNaN(n)) return '—'
  const a = Math.abs(n)
  if (a >= 1e12) return `${(n / 1e12).toFixed(2)}T`
  if (a >= 1e9) return `${(n / 1e9).toFixed(2)}B`
  if (a >= 1e6) return `${(n / 1e6).toFixed(2)}M`
  if (a >= 1e3) return `${(n / 1e3).toFixed(1)}K`
  return n.toFixed(2)
}

export function fmtPct(v: any, digits = 2, withSign = false): string {
  const n = Number(v)
  if (v === null || v === undefined || Number.isNaN(n)) return '—'
  const s = withSign && n > 0 ? '+' : ''
  return `${s}${n.toFixed(digits)}%`
}

/** 输入 0.1234 → 输出 12.34% */
export function fmtRatioPct(v: any, digits = 2, withSign = false): string {
  const n = Number(v)
  if (v === null || v === undefined || Number.isNaN(n)) return '—'
  return fmtPct(n * 100, digits, withSign)
}

export function fmtDate(s: any): string {
  if (!s) return '—'
  const str = String(s)
  return str.length >= 10 ? str.slice(0, 10) : str
}

export function fmtDateTime(s: any): string {
  if (!s) return '—'
  const str = String(s)
  return str.replace('T', ' ').slice(0, 19)
}

export function fmtAgo(s: any): string {
  if (!s) return '—'
  const t = new Date(String(s).endsWith('Z') || String(s).includes('+') ? String(s) : `${s}Z`).getTime()
  if (Number.isNaN(t)) return '—'
  const diff = Math.max(0, Date.now() - t)
  const min = Math.floor(diff / 60000)
  if (min < 1) return '刚刚'
  if (min < 60) return `${min} 分钟前`
  const hr = Math.floor(min / 60)
  if (hr < 24) return `${hr} 小时前`
  return `${Math.floor(hr / 24)} 天前`
}

export function titleCase(s: string): string {
  return s ? s.charAt(0).toUpperCase() + s.slice(1) : s
}

/** 指标中文名 */
export const METRIC_LABEL: Record<string, string> = {
  total_return: '累计收益',
  cagr: '年化收益',
  excess_cagr: '超额年化',
  volatility: '年化波动',
  sharpe: '夏普比率',
  sortino: '索提诺',
  calmar: '卡玛比率',
  max_drawdown: '最大回撤',
  max_dd_days: '最长水下期',
  win_rate: '胜率',
  profit_factor: '盈亏比',
  payoff_ratio: '平均盈亏比',
  expectancy: '单笔期望',
  trades: '交易笔数',
  avg_bars_held: '平均持有',
  turnover: '换手率',
  avg_exposure: '平均持仓比',
  var95_daily: '日 VaR95',
  cvar95_daily: '日 CVaR95',
  beta: 'Beta',
  alpha: '年化 Alpha',
  information_ratio: '信息比率',
  benchmark_cagr: '基准年化',
  benchmark_max_drawdown: '基准回撤',
  final_equity: '期末权益',
  best_month: '最佳月份',
  worst_month: '最差月份',
  skew: '偏度',
  kurtosis: '峰度',
}

export type MetricFmt = 'pct' | 'ratio' | 'num' | 'int' | 'money'

export function fmtMetric(key: string, v: any): string {
  const pctKeys = new Set([
    'total_return', 'cagr', 'excess_cagr', 'volatility', 'max_drawdown', 'win_rate',
    'avg_exposure', 'var95_daily', 'cvar95_daily', 'alpha', 'benchmark_cagr',
    'benchmark_max_drawdown', 'best_month', 'worst_month', 'benchmark_total_return',
  ])
  const intKeys = new Set(['trades', 'max_dd_days', 'max_consec_loss'])
  const moneyKeys = new Set(['expectancy', 'final_equity', 'best_trade', 'worst_trade'])
  if (pctKeys.has(key)) return fmtRatioPct(v, 2, true)
  if (intKeys.has(key)) return v === null || v === undefined ? '—' : String(Math.round(Number(v)))
  if (moneyKeys.has(key)) return fmtMoney(v, 2)
  if (key === 'turnover') return `${fmtNum(v, 2)}x`
  return fmtNum(v, 2)
}
