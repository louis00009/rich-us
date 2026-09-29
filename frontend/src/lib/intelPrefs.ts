/**
 * intelPrefs —— 情报中心「抓取范围」持久化
 * ========================================
 * 用户是**每天都要跑**的，而且有固定的重点标的。每次进页面都回到「自动 4 家」
 * 等于让他每天重挑一遍 —— 所以「指定标的」的选择必须存下来。
 *
 * ⚠️ 与 /backtest 同一类陷阱（见 lib/backtestPrefs.ts 注释）：localStorage 里的
 * symbols **不保证是数组** —— 历史版本可能写成逗号串，用户手改也可能写坏。
 * 读取一律走 `symbolsToList` 规范化，**绝不在页面里直接 `JSON.parse` 后当数组用**：
 * 那种写法首次访问正常、**第二次**才 TypeError 整页崩，构建/typecheck 全拦不住。
 */
import { symbolsToList } from './backtestPrefs'

const KEY = 'qd.intel.scrape.v1'

/**
 * 读取用户指定的抓取标的。兼容三种历史形态，任一非法输入都返回 []（绝不抛错）：
 *   `{ symbols: ['NVDA','MSFT'] }` / `{ symbols: 'NVDA,MSFT' }` / 裸数组 `['NVDA']`
 */
export function loadScrapeSymbols(): string[] {
  try {
    const raw = localStorage.getItem(KEY)
    if (!raw) return []
    const parsed: unknown = JSON.parse(raw)
    const inner = Array.isArray(parsed) ? parsed : (parsed as { symbols?: unknown } | null)?.symbols
    return symbolsToList(inner)
  } catch {
    return []
  }
}

/** 保存选择。隐私模式 / 配额满时静默降级为「不持久化」，绝不影响主流程。 */
export function saveScrapeSymbols(list: unknown): void {
  try {
    localStorage.setItem(KEY, JSON.stringify({ symbols: symbolsToList(list) }))
  } catch {
    /* ignore */
  }
}
