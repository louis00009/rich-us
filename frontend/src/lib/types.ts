/** 与后端 Pydantic 模型对应的 TypeScript 类型。 */

export interface ParamSpec {
  key: string
  label: string
  type: 'int' | 'float' | 'bool' | 'choice' | 'symbols'
  default: any
  min?: number
  max?: number
  step?: number
  choices?: string[]
  group: string
  help: string
}

export interface StrategyInfo {
  key: string
  name: string
  category: string
  description: string
  multi_symbol: boolean
  min_bars: number
  tags: string[]
  params: ParamSpec[]
}

export interface StrategyConfig {
  id: number
  name: string
  kind: 'builtin' | 'rule' | 'code'
  strategy_key: string
  params: Record<string, any>
  rule: any
  code: string
  symbols: string[]
  risk: Record<string, any>
  notes: string
  tags: string[]
  is_active: boolean
  created_at: string
  updated_at: string
}

export interface Quote {
  symbol: string
  price: number
  prev_close: number
  change: number
  change_pct: number
  volume: number
  day_high: number
  day_low: number
  open?: number
  bid?: number | null
  ask?: number | null
  ts: string
  source: string
  md_type?: number
  error?: string
  /** WebSocket 实时推送附加字段（realtime.py） */
  rt_t?: string
  rt_delayed?: boolean
}

export interface AccountSnapshot {
  broker: string
  mode: string
  connected: boolean
  account_id: string
  currency: string
  equity: number
  cash: number
  buying_power: number
  gross_position_value: number
  unrealized_pnl: number
  realized_pnl: number
  day_pnl: number
  day_pnl_pct: number
  margin_used: number
  message: string
  configured_mode?: string
  live_ready?: boolean
  live_reason?: string
}

export interface PositionItem {
  symbol: string
  quantity: number
  avg_cost: number
  last_price: number
  market_value: number
  unrealized_pnl: number
  unrealized_pct: number
  weight: number
  strategy_id: number | null
  stop_price: number | null
  sec_type?: string
  currency?: string           // T-112：该持仓的计价币种（USD/HKD）
  market_value_base?: number  // T-112：折算到账户基准币种的市值
  market?: string
}

export interface OrderRow {
  id: number
  client_order_id: string
  broker_order_id: string
  mode: string
  broker: string
  symbol: string
  side: string
  quantity: number
  order_type: string
  limit_price: number | null
  stop_price: number | null
  status: string
  filled_qty: number
  avg_fill_price: number
  commission: number
  reason: string
  created_at: string
}

export interface CurvePoint {
  date: string
  equity: number
  benchmark: number | null
  drawdown: number
  exposure: number
}

export interface TradeRow {
  symbol: string
  side: string
  entry_time: string
  exit_time: string
  entry_price: number
  exit_price: number
  qty: number
  pnl: number
  return_pct: number
  bars_held: number
  exit_reason: string
}

export interface BacktestResult {
  ok: boolean
  error?: string
  run_id?: number
  label?: string
  strategy_name: string
  metrics: Record<string, number>
  curve: CurvePoint[]
  trades: TradeRow[]
  trade_count: number
  monthly: Record<string, number>
  symbols: string[]
  data_sources: Record<string, string>
  data_source_used?: string
  data_source_requested?: string
  data_warning?: string
  strategy_notes: string[]
  bars: number
  date_range: string[]
}

export interface CompareItemResult {
  label: string
  ok: boolean
  error?: string
  strategy_name?: string
  metrics?: Record<string, number>
  curve?: CurvePoint[]
  monthly?: Record<string, number>
  bars?: number
  date_range?: string[]
}

export interface CompareResult {
  ok: boolean
  results: CompareItemResult[]
  aligned: Record<string, any>[]
  labels: string[]
}

export interface DataSourceInfo {
  preferred: string
  available: string[]
  providers: Record<string, any>
  recent_errors?: Record<string, string>
  chain: string[]
  note: string
}

export interface BrokerStatus {
  broker: string
  mode?: string
  connected: boolean
  host?: string
  port?: number
  client_id?: number
  account_id?: string
  readonly?: boolean
  market_data_type?: number
  market_data_label?: string
  use_rth?: boolean
  contracts_cached?: number
  historical_requests?: number
  supports_history?: boolean
  supports_streaming?: boolean
  last_error?: string
}

export interface BrokerOpenOrder {
  order_id: string
  perm_id?: string
  symbol: string
  action: string
  quantity: number
  type: string
  lmt_price?: number
  aux_price?: number
  status: string
  filled: number
  remaining: number
  oca_group?: string
}

export interface FillRow {
  exec_id: string
  order_id: string
  perm_id?: string
  symbol: string
  side: string
  shares: number
  price: number
  time: string
  commission: number
}

export interface RiskConfig {
  max_position_pct: number
  max_gross_exposure_pct: number
  max_open_positions: number
  min_order_notional: number
  max_order_notional: number
  max_daily_loss_pct: number
  max_drawdown_pct: number
  stop_type: string
  stop_value: number
  take_profit_r: number
  time_stop_bars: number
  sizing_method: string
  risk_per_trade_pct: number
  trading_hours_only: boolean
  whitelist: string
  blacklist: string
  kill_switch: boolean
  live_unlocked: boolean
  updated_at?: string
}

export interface SystemStatus {
  app: string
  version: string
  mode: string
  broker: string
  broker_host: string
  readonly: boolean
  strategies: number
  kill_switch: boolean
  live_env_gate: boolean
  live_unlocked: boolean
  live_ready: boolean
  live_reason: string
  ai_configured: boolean
  server_time: string
  runtime_dir?: string
  frontend_built?: boolean
}

export interface AIResult {
  symbol: string
  as_of: string
  mode: string
  price: number
  bias: string
  composite_score: number
  confidence: number
  regime: string
  regime_desc: string
  dimensions: Record<string, number>
  realtime?: { realtime: boolean; mode?: string; quote_source?: string; quote_ts?: string; note?: string }
  levels: { 支撑: number[]; 阻力: number[] }
  atr_pct: number
  suggested_position_pct: number
  warnings: string[]
  strategy_matches: { key: string; name: string; reason: string }[]
  readings: { name: string; value: any; reading: string; signal: string }[]
  horizon: string
  llm_report?: string
  llm_error?: string
}

export interface AuditRow {
  id: number
  ts: string
  actor: string
  action: string
  level: string
  detail: string
  ip: string
}
