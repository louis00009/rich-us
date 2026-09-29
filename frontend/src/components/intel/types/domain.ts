/**
 * 情报中心 · 领域类型
 *
 * 从 `types.ts` 抽出（铁律 9 拆分，2026-09-29）。`types.ts` 已改为 `types/` 目录 + barrel，
 * 因此所有既有 `from './types'` / `from '../components/intel/types'` 的导入**无需改动**。
 *
 * 本文件只放**数据形状**（接口 / 联合类型），不放任何逻辑与样式。
 */
export type Rec = 'strong_buy' | 'buy' | 'hold' | 'reduce' | 'avoid'
export type Tier = 'critical' | 'high' | 'medium' | 'low'

/* ---------------- 事件 / 建议 ---------------- */
export interface Company {
  id: number
  symbol: string
  name: string
  theme: string
  focus: string
  enabled: boolean
  last_scrape_at: string | null
}

export interface EventItem {
  id: number
  symbol: string
  occurred_on: string
  occurred_at?: string
  category: string
  category_cn: string
  title: string
  summary: string
  impact: number
  sentiment: 'positive' | 'neutral' | 'negative'
  source_name: string
  source_url: string
  agent: string
  created_at: string
  /** 后端新增：前瞻管道阶段（旧后端不返回 → 前端必须回落） */
  stage?: string
  stage_cn?: string
  /** 后端新增：确定性重要度 0~100 与分档 */
  importance?: number
  tier?: Tier
  importance_reasons?: string[]
  /**
   * 后端新增：媒体评论 / 行情播报 / 分析师调价（**不是公司自身事件**）。
   * 后端已把这类条目的重要度封顶到 40 分以下 → 永远进不了「必读」。
   * 旧后端不返回该字段 → 前端必须回落（`undefined` 视为 false）。
   */
  commentary?: boolean
}

export interface Analysis {
  id: number
  symbol: string
  recommendation: Rec
  recommendation_cn: string
  confidence: number
  thesis: string
  catalysts: string
  risks: string
  position_pct: number
  invalidation: string
  price_at_analysis: number
  horizon: string
  agent: string
  engine: string
  based_on_events?: number[]
  event_score?: number | null
  outcome_checked_at?: string | null
  outcome_price?: number | null
  outcome_return?: number | null
  outcome_benchmark?: number | null
  outcome_hit?: boolean | null
  outcome_window_days?: number | null
  created_at: string
}

/* ---------------- 总控 ---------------- */
export interface Run {
  id: number
  status: 'running' | 'finished' | 'stopped'
  interval_minutes: number
  auto_analyze: boolean
  started_at: string
  ended_at: string | null
  tick_count: number
  last_tick_at: string | null
  events_found: number
  analyses_done: number
  agents_seen: string
  note: string
  report_path: string
}

/** 总控批次摘要：三个计数口径（见后端 intel_activity.run_summary 注释）
 *  注意 `agents_seen` 在此已被后端解析成数组（与 /runs 接口返回的 JSON 字符串不同）。 */
export interface RunSummary extends Omit<Run, 'agents_seen'> {
  duration_seconds: number | null
  running: boolean
  events_in_window: number
  analyses_in_window: number
  events_in_db: number
  analyses_in_db: number
  agents_seen: string[]
}

export interface Activity {
  today_events: number
  h24_events: number
  h24_analyses: number
  h24_high_impact: number
  events_total: number
  analyses_total: number
  daily: { date: string; count: number }[]
  last_scrape_at: string | null
  scraped_24h: number
  companies_enabled: number
}

export interface Overview {
  settings: {
    monitor_enabled: boolean
    interval_minutes: number
    auto_analyze: boolean
    ai_scrape: boolean
    bridge_token: string
  }
  llm: { configured: boolean }
  scheduler: { scheduler_alive: boolean; monitor_enabled: boolean; current_run: Run | null }
  stats: {
    events_total: number
    analyses_total: number
    companies_total: number
    companies_enabled: number
    tasks_pending: number
    /**
     * 后端新增：待抓取标的**清单**（判定含 interval*1.2 窗口，前端不得自行推算）。
     * 旧后端不返回 → 前端必须回落成 []（「指定标的」里的待抓取标记与「全选待抓取」依赖它）。
     */
    pending_symbols?: string[]
    agents_24h: Record<string, string>
  }
  /** 后端新增：上次批次摘要（监控停止后也在）与今日/近 24h 活动 */
  last_run?: RunSummary | null
  activity?: Activity
  digest?: {
    available: boolean
    digest_date: string | null
    top_count: number
    event_count: number
    updated_at: string | null
    has_llm_text: boolean
  }
  companies: Company[]
  recent_events: EventItem[]
  recent_analyses: Analysis[]
  runs: Run[]
}

/* ---------------- 每日必读 ---------------- */
export interface DigestItem extends EventItem {
  importance: number
  tier: Tier
  reasons: string[]
  age_days: number | null
}

export interface DigestSymbol {
  symbol: string
  name: string
  theme: string
  count: number
  max_importance: number
  positive: number
  negative: number
  high_impact: number
  top_title: string
  top_importance: number
  /** top 事件的发生日（YYYY-MM-DD）与精确时间（YYYY-MM-DD HH:MM）—— 所有信息必须带日期 */
  top_date: string | null
  top_at: string | null
  recommendation: Rec | null
  confidence: number | null
  analysis_at: string | null
}

export interface DigestWatch {
  symbol: string
  name: string
  theme: string
  reason: string
  recommendation: Rec | null
  confidence: number | null
  importance: number
  /** 依据事件（top）的发生日与精确时间 —— 所有信息必须带日期 */
  event_date: string | null
  event_at: string | null
  zone_low: number | null
  zone_high: number | null
  trigger: string
  invalidation: string
  rsi14: number | null
  atr14: number | null
  price: number | null
  note: string
}

export interface Digest {
  available: boolean
  digest_date: string | null
  scope: string
  days: number
  totals: {
    events?: number
    critical?: number
    high?: number
    positive?: number
    negative?: number
    symbols?: number
    top?: number
  }
  top: DigestItem[]
  by_symbol: DigestSymbol[]
  watch: DigestWatch[]
  notes: string[]
  llm_text: string
  llm_engine: string
  generated_by: string
  updated_at: string | null
  llm_configured?: boolean
}

/* ---------------- 建议验证 ---------------- */
export interface CalBucket {
  bucket: string
  n: number
  hits: number
  hit_rate: number | null
  avg_confidence: number | null
}

export interface VerifyAgentStat {
  agent: string
  n: number
  hits: number
  hit_rate: number | null
  avg_return: number | null
  avg_excess_return?: number | null
  avg_confidence: number | null
  brier?: number | null
  calibration?: CalBucket[]
}

export interface VerifyStats {
  verified_total: number
  pending: number
  analyses_total: number
  agents: VerifyAgentStat[]
  global_hit_rate: number | null
  global_avg_excess_return?: number | null
  global_brier?: number | null
  global_calibration?: CalBucket[]
  tolerance_pct: number
  window_days: number
  window_days_by_horizon?: Record<string, number>
  benchmark?: string
}

export interface PriceSeries {
  symbol: string
  source: string
  dates: string[]
  close: number[]
}
