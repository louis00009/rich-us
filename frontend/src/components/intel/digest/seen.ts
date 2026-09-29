/**
 * 「每日必读」已读标记（localStorage）
 *
 * 从 DailyDigest.tsx 抽出（铁律 9 拆分，2026-09-29）。原文件 501 行超 400 软上限。
 *
 * 为什么要单独一个模块：这是**唯一**的持久化副作用，和渲染无关，
 * 单独放便于测试与替换（例如以后改成服务端已读态）。
 *
 * 语义：按**归集日**记一个时间戳。「强制提示」需要一个能持续提醒的未读态 ——
 * 用户真正展开/切换页签后才算读过，未读徽章才有意义。
 */

const SEEN_KEY = 'qd.intel.digest.seen'

/** 只保留最近 14 天，避免 localStorage 无限增长 */
const KEEP_DAYS = 14

export function readSeen(): Record<string, string> {
  try {
    return JSON.parse(localStorage.getItem(SEEN_KEY) || '{}') as Record<string, string>
  } catch {
    return {}
  }
}

export function markSeen(date: string) {
  try {
    const all = readSeen()
    all[date] = new Date().toISOString()
    const keys = Object.keys(all).sort().slice(-KEEP_DAYS)
    const trimmed: Record<string, string> = {}
    for (const k of keys) trimmed[k] = all[k]
    localStorage.setItem(SEEN_KEY, JSON.stringify(trimmed))
  } catch {
    /* localStorage 不可用（隐私模式）时静默降级：只是没有未读标记 */
  }
}
