/**
 * 情报中心 · 时间/数值格式化
 *
 * 从 `types.ts` 抽出（铁律 9 拆分，2026-09-29）。这些函数**无副作用、无 UI 依赖**，
 * 可以独立测试。
 */

/**
 * P2-7：impact 由外部 AI Agent 提交，必须夹取到 1..5
 * （否则 `'★'.repeat(impact)` 抛 RangeError → 整页白屏）
 */
export function clampImpact(v: unknown): number {
  const n = Math.round(Number(v))
  if (!Number.isFinite(n)) return 3
  return Math.max(1, Math.min(5, n))
}

export function fmtUtc(s: string | null | undefined): string {
  if (!s) return '—'
  const raw = String(s)
  const d = new Date(raw.endsWith('Z') || raw.includes('+') ? raw : `${raw}Z`)
  if (Number.isNaN(d.getTime())) return raw
  return d.toLocaleString('zh-CN', { hour12: false })
}

function toDate(s: string): Date {
  const raw = String(s)
  return new Date(raw.endsWith('Z') || raw.includes('+') ? raw : `${raw}Z`)
}

export function duration(since: string): string {
  const t = toDate(since).getTime()
  if (Number.isNaN(t)) return '—'
  const min = Math.max(0, Math.floor((Date.now() - t) / 60000))
  if (min < 60) return `${min} 分钟`
  const hr = Math.floor(min / 60)
  if (hr < 24) return `${hr} 小时 ${min % 60} 分`
  return `${Math.floor(hr / 24)} 天 ${hr % 24} 小时`
}

/** 秒 → 人类可读时长（批次运行窗口用） */
export function fmtDuration(seconds: number | null | undefined): string {
  if (seconds == null || Number.isNaN(seconds)) return '—'
  const s = Math.max(0, Math.floor(seconds))
  if (s < 60) return `${s} 秒`
  const m = Math.floor(s / 60)
  if (m < 60) return `${m} 分钟`
  const h = Math.floor(m / 60)
  if (h < 24) return `${h} 小时 ${m % 60} 分`
  return `${Math.floor(h / 24)} 天 ${h % 24} 小时`
}

/** 「3 分钟前 / 2 小时前」——比 fmtAgo 更适合展示抓取新鲜度 */
export function fmtSince(s: string | null | undefined): string {
  if (!s) return '从未'
  const t = toDate(s).getTime()
  if (Number.isNaN(t)) return String(s)
  const min = Math.floor((Date.now() - t) / 60000)
  if (min < 1) return '刚刚'
  if (min < 60) return `${min} 分钟前`
  const hr = Math.floor(min / 60)
  if (hr < 24) return `${hr} 小时前`
  const d = Math.floor(hr / 24)
  return d < 30 ? `${d} 天前` : fmtUtc(s).slice(0, 10)
}

export function eventAgeDays(e: { occurred_on?: string; created_at?: string }): number | null {
  const ref = e.occurred_on || String(e.created_at || '').slice(0, 10)
  if (!/^\d{4}-\d{2}-\d{2}$/.test(ref)) return null
  const d = (Date.now() - new Date(`${ref}T00:00:00Z`).getTime()) / 86400000
  return Number.isNaN(d) ? null : Math.max(0, Math.round(d))
}
