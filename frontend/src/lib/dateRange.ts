/**
 * 日期区间小工具
 * ==============
 * 回测页和组合优化页都需要「近 N 年」这类快捷时长，且**必须是本地时区**的日期。
 *
 * ⚠️ 不要用 `toISOString().slice(0,10)`：那返回的是 UTC 日期，在东八区凌晨
 *    （UTC 还停在昨天）会算出「昨天」，用户看到的起始日和预期差一天，
 *    而且这种偏差只在特定时段复现，极难排查。
 *
 * 放在 lib/ 而不是某个页面的 presets 里，是因为它已经被两个页面用到 ——
 * 复制一份到另一个页面 = 这个时区坑会各自漂移一次。
 */

const pad = (n: number) => String(n).padStart(2, '0')

/** 本地时区的「n 年前的今天」，格式 YYYY-MM-DD。 */
export function yearsAgo(n: number): string {
  const d = new Date()
  d.setFullYear(d.getFullYear() - n)
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}

/** 本地时区的「n 天前的今天」，格式 YYYY-MM-DD。 */
export function daysAgo(n: number): string {
  const d = new Date()
  d.setDate(d.getDate() - n)
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}

/** 本地时区的「今天」，格式 YYYY-MM-DD。 */
export function today(): string {
  return daysAgo(0)
}
