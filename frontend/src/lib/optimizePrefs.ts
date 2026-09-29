/**
 * 组合优化的输入解析
 * ==================
 * 「标的池」和「风险预算」都是**自由文本输入**，用户可能写成
 * `SPY,QQQ`、`spy qqq`、`SPY QQQ IWM` 甚至带换行。解析规则集中在这里，
 * 页面和组件都从这里取，避免两处各写一份正则、慢慢长歪。
 *
 * ⚠️ 为什么不直接在页面里 `.split(',')`：组合优化至少需要 2 个**有效**标的，
 *    如果解析太宽松（把 `SPY QQQ` 当成一个代码），用户会看到「标的不足 2 个」
 *    却完全不知道自己写错了什么。所以这里做严格校验 + 去重 + 大写归一。
 */

/** 合法美股/ETF 代码：可带 ^ 前缀（指数），字母数字加点或横线，最长 10 位。 */
const SYMBOL_RE = /^[\^A-Z][A-Z0-9.\-]{0,9}$/

/**
 * 把自由文本解析成规范化后的标的数组（大写、去重、保序、剔除非法项）。
 * 去重保留**首次出现的位置**，这样「点选顺序 = 顺序」的直觉成立。
 */
export function parseSymbols(text: string): string[] {
  const seen = new Set<string>()
  const out: string[] = []
  for (const raw of String(text || '').split(/[\s,;]+/)) {
    const s = raw.trim().toUpperCase()
    if (!s || !SYMBOL_RE.test(s) || seen.has(s)) continue
    seen.add(s)
    out.push(s)
  }
  return out
}

/** 数组 → 输入框文本。⚠️ 输入来源可能是数组也可能是逗号串，先过 parseSymbols 归一。 */
export function symbolsToInput(list: unknown): string {
  if (Array.isArray(list)) return parseSymbols(list.join(',')).join(',')
  return parseSymbols(String(list ?? '')).join(',')
}

/**
 * 解析风险预算文本，形如 `SPY:3, TLT:2, GLD:1`。
 * 只接受非负有限数；解析不出数字的项直接忽略（宁可少一条预算，
 * 也不要塞一个 NaN 进去让求解器整轮失败）。
 */
export function parseBudget(text: string): Record<string, number> {
  const out: Record<string, number> = {}
  for (const tok of String(text || '').split(/[\s,;]+/)) {
    const t = tok.trim()
    if (!t) continue
    const [k, v] = t.split(/[:=]/)
    if (!k) continue
    const num = Number(v)
    if (!Number.isFinite(num) || num < 0) continue
    const sym = k.trim().toUpperCase()
    if (!SYMBOL_RE.test(sym)) continue
    out[sym] = num
  }
  return out
}

/** 预算对象 → 文本（用于把默认值回填到输入框）。 */
export function budgetToInput(budget: Record<string, number>): string {
  return Object.entries(budget)
    .map(([k, v]) => `${k}:${v}`)
    .join(', ')
}

/* ==================== 配置持久化 ==================== */

/**
 * 组合优化的配置快照。
 * ⚠️ `symbolsText` **始终是字符串**。历史教训（回测页真实事故）：曾把 symbols 存成数组、
 *    读取时当字符串用，于是 `.join()` 抛 TypeError，页面第一次访问正常、第二次直接崩。
 *    所以这里的读写都过 `symbolsToInput()`，不管存进去的是什么形态，取出来一定是串。
 */
export interface OptimizePrefs {
  symbolsText: string
  start: string
  interval: string
  objective: string
  covMethod: string
  returnMethod: string
  maxWeight: number
  maxGross: number
  corrThreshold: number
  maxCluster: number
  riskFree: number
  longOnly: boolean
  useBudget: boolean
  budgetText: string
  includeFrontier: boolean
  /** 是否处于「新手模式」（隐藏高级选项）。默认开。 */
  beginner?: boolean
}

const KEY = 'qd.optimize.v1'

export function loadOptimizePrefs(): Partial<OptimizePrefs> {
  try {
    const raw = localStorage.getItem(KEY)
    if (!raw) return {}
    const parsed = JSON.parse(raw) as Partial<OptimizePrefs>
    // 无论存的是什么形态，一律归一成「逗号串」
    const sym = symbolsToInput(parsed.symbolsText)
    return sym ? { ...parsed, symbolsText: sym } : { ...parsed, symbolsText: '' }
  } catch {
    return {}
  }
}

let saveTimer: ReturnType<typeof setTimeout> | null = null
export function saveOptimizePrefs(patch: Partial<OptimizePrefs>): void {
  if (saveTimer) clearTimeout(saveTimer)
  saveTimer = setTimeout(() => {
    try {
      const cur = loadOptimizePrefs()
      localStorage.setItem(KEY, JSON.stringify({ ...cur, ...patch }))
    } catch {
      /* ignore */
    }
  }, 300)
}

