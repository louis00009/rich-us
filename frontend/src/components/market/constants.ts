/**
 * 行情页 · 常量（快捷标的 / 周期 / K 线周期 / 均线配色）
 *
 * 从 `pages/Market.tsx` 抽出（铁律 9 拆分，2026-09-29）。
 */

/** 收藏列表为空时的回退标的池 */
export const MAJORS = ['SPY', 'QQQ', 'IWM', 'DIA', 'SMH', 'TLT', 'GLD', 'USO', '^VIX', 'FXI', 'EEM', 'IBIT']

export const RANGES = [
  { key: '6M', days: 180 },
  { key: '1Y', days: 365 },
  { key: '2Y', days: 730 },
  { key: '5Y', days: 1825 },
]

// 快速周期（用户语义：24H 分时 / 一周 / 一月 / 3 月 / 半年），点击自动适配 K 线周期
export const QUICK_RANGES: { key: string; label: string; days: number; interval: string }[] = [
  { key: '1W', label: '1 周', days: 8, interval: '1h' },
  { key: '1M', label: '1 月', days: 31, interval: '1d' },
  { key: '3M', label: '3 月', days: 92, interval: '1d' },
  { key: '6M', label: '半年', days: 183, interval: '1d' },
  { key: '1Y', label: '1 年', days: 366, interval: '1d' },
]

export const ALL_RANGES = [...QUICK_RANGES, ...RANGES]

export const INTERVALS = [
  { key: '1d', label: '日线' },
  { key: '1wk', label: '周线' },
  { key: '1h', label: '小时线（近 180 天）' },
  { key: '30m', label: '30 分钟（近 60 天）' },
  { key: '15m', label: '15 分钟（近 60 天）' },
  { key: '5m', label: '5 分钟（近 60 天）' },
]

// 均线配色（周期越长越冷色，一眼区分短中期与长期趋势）
export const MA_STYLE: { key: string; label: string; color: string }[] = [
  { key: 'sma5', label: 'MA5', color: '#f97316' },
  { key: 'sma10', label: 'MA10', color: '#eab308' },
  { key: 'sma20', label: 'MA20', color: '#a855f7' },
  { key: 'sma60', label: 'MA60', color: '#14b8a6' },
  { key: 'sma50', label: 'SMA50', color: '#f59e0b' },
  { key: 'sma200', label: 'SMA200', color: '#0ea5e9' },
]
