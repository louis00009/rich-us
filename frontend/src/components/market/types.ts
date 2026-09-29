/**
 * 行情页 · 类型定义
 *
 * 从 `pages/Market.tsx` 抽出（铁律 9 拆分，2026-09-29）。原文件 1017 行、超硬上限 900。
 */
import type { IntraPoint } from '../IntradayChart'

export interface HistoryResp {
  symbol: string
  source: string
  source_requested?: string
  warning?: string
  realtime?: boolean
  interval: string
  count: number
  dates: string[]
  open: number[]
  high: number[]
  low: number[]
  close: number[]
  volume: number[]
}

export interface IndicatorResp {
  symbol: string
  source: string
  dates: string[]
  series: Record<string, (number | null)[]>
}

export interface SnapResp {
  symbol: string
  last_date: string
  price: number
  source: string
  returns: Record<string, number | null>
  ma: Record<string, number | null>
  dist: Record<string, number | null>
  levels: Record<string, number | null>
  indicators: Record<string, number | null>
  realtime?: { realtime: boolean; quote_source?: string; quote_ts?: string; note?: string }
}

export interface IntradayResp {
  symbol: string
  source: string
  interval: string
  trade_date?: string
  is_today?: boolean
  prev_close: number
  last_price: number
  change_pct: number
  delayed: boolean
  count: number
  points: IntraPoint[]
}

export type OverlayKey = 'ma' | 'sma' | 'bb' | 'all' | 'none'

export type ChartType = 'candle' | 'line' | 'intraday'
