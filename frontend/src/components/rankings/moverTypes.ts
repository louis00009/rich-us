// 每日开盘监控共享类型（MoversMonitor / MoverList / MoverFilters 共用）

export interface MoverRow {
  symbol: string
  name?: string
  name_cn?: string
  sector?: string
  price?: number | null
  prev_close?: number | null
  change_pct?: number | null
  volume?: number | null
  amount?: number | null
  vol_ratio?: number | null
  bar_date?: string
  hits?: number
  first_seen?: string | null
  src?: 'pool' | 'market'
}

export interface MoversResp {
  universe: string
  covered: number
  market_extra?: number
  threshold: number
  limit: number
  as_of?: string | null
  updated: string
  quotes_updated?: string | null
  status?: { session?: string; session_label?: string; is_open?: boolean; now_local?: string; reason?: string }
  stale?: boolean
  refreshing?: boolean
  note?: string
  gainers: MoverRow[]
  losers: MoverRow[]
  log?: {
    events: number
    symbols: number
    top_repeat?: { symbol: string; hits: number; first_seen?: string; last_change_pct?: number | null; dir?: string }[]
  }
  monitor?: {
    running: boolean
    last_scan?: string
    scans?: number
    last_error?: string
    cfg?: { enabled: boolean; threshold: number; interval: number; model: string }
    llm_configured?: boolean
  }
}

export interface AiStatus {
  llm_configured?: boolean
  model?: string
  extra_models?: string[]
  models_by_realm?: { cn?: string[]; global?: string[] }
}
