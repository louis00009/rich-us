/**
 * backtestPrefs —— 回测中心配置持久化
 * =====================================
 * 解决两个问题：
 * 1. SPA 切页 / 刷新后全部配置回默认（组件卸载即丢状态）；
 * 2. 切换策略时参数被无条件重置（per-strategy 参数记忆）。
 *
 * 存 localStorage（单机单用户，键带版本号便于将来迁移）。
 * 写入统一防抖 300ms，避免输入框每敲一个字符就序列化一次。
 * 读写全部 try/catch：隐私模式 / 配额满时静默降级为「不持久化」，绝不影响主流程。
 */

export interface BacktestPrefs {
  strategyKey: string
  customId: number | ''
  symbols: string
  start: string
  end: string
  interval: string
  capital: number
  commission: number
  slippage: number
  benchmark: string
  stopType: string
  stopValue: number
  takeProfitR: number
  timeStop: number
  sizing: string
  riskPct: number
  dataSource: string
  params: Record<string, any>
  rule: any | null
  code: string
  /** 是否处于「新手模式」（隐藏高级选项）。默认开 —— 见 ConfigPanel 的说明。 */
  beginner?: boolean
}

const KEY = 'qd.backtest.v1'
const MEM_KEY = 'qd.backtest.paramMemory.v1'

/**
 * 把任意来源的 symbols 统一成「大写、去空格、去重」的标的数组。
 * 兼容三种形态：数组（榜单/策略跳转、后端 JSON 字段）、逗号分隔字符串（本地偏好、
 * 后端历史遗留数据）、以及单个字符串。非法输入一律返回 []，绝不抛错。
 */
export function symbolsToList(v: unknown): string[] {
  const raw = Array.isArray(v) ? v : typeof v === 'string' ? v.split(',') : v == null ? [] : [v]
  const out: string[] = []
  for (const it of raw) {
    const s = String(it ?? '').trim().toUpperCase()
    if (s && !out.includes(s)) out.push(s)
  }
  return out
}

/** symbolsToList 的「输入框形态」：数组 → 'SPY,QQQ'；无有效标的返回 null（便于 ?? 兜底）。 */
export function symbolsToInput(v: unknown): string | null {
  const list = symbolsToList(v)
  return list.length ? list.join(',') : null
}

export function loadBacktestPrefs(): Partial<BacktestPrefs> {
  try {
    const raw = localStorage.getItem(KEY)
    const parsed = raw ? (JSON.parse(raw) as Partial<BacktestPrefs>) : {}
    // 历史版本曾把 symbols 写成数组，读取时统一成字符串，避免下游 .join() 炸掉
    const sym = symbolsToInput(parsed.symbols)
    return sym ? { ...parsed, symbols: sym } : { ...parsed, symbols: '' }
  } catch {
    return {}
  }
}

let saveTimer: ReturnType<typeof setTimeout> | null = null
export function saveBacktestPrefs(patch: Partial<BacktestPrefs>): void {
  if (saveTimer) clearTimeout(saveTimer)
  saveTimer = setTimeout(() => {
    try {
      const cur = loadBacktestPrefs()
      localStorage.setItem(KEY, JSON.stringify({ ...cur, ...patch }))
    } catch {
      /* ignore */
    }
  }, 300)
}

/* ---------------- per-strategy 参数记忆 ---------------- */

export function loadParamMemory(key: string): Record<string, any> | null {
  try {
    const raw = localStorage.getItem(MEM_KEY)
    const all = raw ? (JSON.parse(raw) as Record<string, Record<string, any>>) : {}
    const memo = all[key]
    return memo && Object.keys(memo).length ? memo : null
  } catch {
    return null
  }
}

let memTimer: ReturnType<typeof setTimeout> | null = null
export function saveParamMemory(key: string, params: Record<string, any>): void {
  if (!key || !Object.keys(params).length) return
  if (memTimer) clearTimeout(memTimer)
  memTimer = setTimeout(() => {
    try {
      const raw = localStorage.getItem(MEM_KEY)
      const all = raw ? JSON.parse(raw) : {}
      all[key] = params
      localStorage.setItem(MEM_KEY, JSON.stringify(all))
    } catch {
      /* ignore */
    }
  }, 300)
}
