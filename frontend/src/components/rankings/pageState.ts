/**
 * 榜单页 · 页面私有类型与偏好持久化
 *
 * 从 `pages/Rankings.tsx` 抽出（铁律 9 拆分，2026-09-29）。
 * 这些类型/工具**只被榜单页使用**（已 grep 确认无其他模块 import），
 * 放在这里只是为了让页面保持「编排层」体积。
 */
import type { FocusRow } from './PickCenter'
import type { RankRow } from './RankingsTable'
import type { RankingFiltersValue } from './RankingFilters'
import type { Weights } from './ScoreSettings'

/** 估值 / 技术指标这类「后台补数据」的进度元信息 */
export interface CacheMeta {
  covered: number
  rows: number
  cached: number
  age_sec: number | null
  stale: boolean
  refreshing: boolean
  last_refresh_ok: boolean | null
  error?: string | null
}

export interface RankResp {
  total: number
  universe_total: number
  count: number
  updated: string
  quote_age_sec?: number | null
  stale?: boolean
  refreshing?: boolean
  /** 搜索时后端是否绕过了候选池评分门槛（见 backend/app/rankings.py） */
  pool_bypassed?: boolean
  fundamentals?: CacheMeta
  technicals?: CacheMeta
  bands?: Record<string, number>
  threshold?: number
  /** 打开即有完整数据：本次是否用了上次快照兜底（冷启动/行情未就绪时） */
  snapshot_restored?: boolean
  /* ---- 选股中心 ---- */
  active_signal?: string | null
  signal_stats?: Record<string, number>
  focus?: FocusRow[]
  rows: RankRow[]
  sectors: string[]
}

export const PREF_KEY = 'qd_rankings_pref'

export interface Pref {
  sort?: string
  dir?: 'asc' | 'desc'
  limit?: number
  filters?: RankingFiltersValue
  columns?: string[]
  weights?: Weights
  threshold?: number
  view?: 'all' | 'pool'
  signal?: string
}

export function loadPref(): Pref {
  try {
    return JSON.parse(localStorage.getItem(PREF_KEY) || '{}')
  } catch {
    return {}
  }
}

/** 空字符串表示「不筛选」——不能转成 0，否则空输入会被当成上限 0，把所有股票筛没。 */
export function putNum(p: URLSearchParams, key: string, raw: string) {
  const s = raw.trim()
  if (s === '') return
  const n = Number(s)
  if (!Number.isNaN(n)) p.set(key, String(n))
}
