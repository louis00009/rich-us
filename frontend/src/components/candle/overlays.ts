// 蜡烛图纯几何计算：可视区间、叠加线、量能、极值标记
// 全部为纯函数，不依赖 React；坐标函数（xOf/yOf/yVol）由调用方注入。

// SVG 四周留白（主图与 parts 共享布局常量）
export const PAD_L = 8
export const PAD_R = 62
export const PAD_T = 10
export const PAD_B = 22

export const MIN_BARS = 20

/** 把可视区间夹到 [0, n-1] 内，并保证至少 MIN_BARS 根。 */
export function clampRange(sIn: number, eIn: number, n: number): [number, number] {
  let s = Math.round(sIn)
  let e = Math.round(eIn)
  if (e < s) {
    const t = s
    s = e
    e = t
  }
  const len = Math.max(MIN_BARS, Math.min(n, e - s + 1))
  s = Math.max(0, Math.min(s, n - len))
  e = Math.min(n - 1, s + len - 1)
  return [s, e]
}

/** 以 anchorIdx 为锚点缩放（大于 1 表示拉远 / 显示更多根）。 */
export function zoomRange(
  cur: [number, number],
  n: number,
  anchorIdx: number,
  factor: number,
): [number, number] {
  const [s, e] = cur
  const len = e - s + 1
  const nextLen = Math.max(MIN_BARS, Math.min(n, Math.round(len * factor)))
  if (nextLen === len) return cur
  const ratio = len > 1 ? (anchorIdx - s) / (len - 1) : 0.5
  const r = Math.max(0, Math.min(1, ratio))
  const anchor = s + ratio * (len - 1)
  return clampRange(anchor - r * (nextLen - 1), anchor + (1 - r) * (nextLen - 1), n)
}

/** 可视区间的价格上下界（含 6% padding）与量能上限；数据不可绘时返回 null。 */
export function computeView(
  high: number[],
  low: number[],
  volume: number[] | undefined,
  i0: number,
  i1: number,
): { hi: number; lo: number; volMax: number } | null {
  if (!high.length) return null
  const hi = Math.max(...high.slice(i0, i1 + 1).filter(Number.isFinite))
  const lo = Math.min(...low.slice(i0, i1 + 1).filter(Number.isFinite))
  if (!Number.isFinite(hi) || !Number.isFinite(lo) || hi <= lo) return null
  const pad = (hi - lo) * 0.06
  const volMax = volume && volume.length ? Math.max(...volume.slice(i0, i1 + 1).filter(Number.isFinite), 1) : 1
  return { hi: hi + pad, lo: lo - pad, volMax }
}

/** 可视区间内的最高点 / 最低点（图上直接标注数值与日期）。 */
export function findExtremes(
  high: number[],
  low: number[],
  i0: number,
  i1: number,
): { hiIdx: number; loIdx: number; hiVal: number; loVal: number } | null {
  let hiVal = -Infinity
  let loVal = Infinity
  let hiIdx = -1
  let loIdx = -1
  for (let i = i0; i <= i1; i++) {
    const h = high[i]
    const l = low[i]
    if (Number.isFinite(h) && h > hiVal) { hiVal = h; hiIdx = i }
    if (Number.isFinite(l) && l < loVal) { loVal = l; loIdx = i }
  }
  return hiIdx >= 0 && loIdx >= 0 ? { hiIdx, loIdx, hiVal, loVal } : null
}

/** 收盘价数值标注：可视区间 K 线 ≤ 40 根时逐根标（抽稀至 ≤32），跳过极值点。 */
export function buildValueLabels(
  span: number,
  i0: number,
  i1: number,
  close: number[],
  extremes: { hiIdx: number; loIdx: number } | null,
): { i: number; v: number; above: boolean }[] {
  if (span > 40) return []
  const step = Math.ceil(span / 32)
  const out: { i: number; v: number; above: boolean }[] = []
  let k = 0
  for (let i = i0; i <= i1; i++) {
    const v = close[i]
    if (!Number.isFinite(v)) continue
    if (k % step !== 0) { k++; continue }
    const isExt = extremes && (i === extremes.hiIdx || i === extremes.loIdx)
    if (!isExt) out.push({ i, v, above: k % 2 === 0 })
    k++
  }
  return out
}

/** 叠加线（均线/布林等）折线 path；跳过 null / 非有限值。 */
export function linePath(
  data: (number | null)[],
  i0: number,
  i1: number,
  xOf: (i: number) => number,
  yOf: (p: number) => number,
): string {
  const pts: string[] = []
  for (let i = i0; i <= i1; i++) {
    const v = data[i]
    if (v === null || v === undefined || !Number.isFinite(v)) continue
    pts.push(`${pts.length === 0 ? 'M' : 'L'}${xOf(i).toFixed(1)},${yOf(v).toFixed(1)}`)
  }
  return pts.join(' ')
}

/** 20 日均量线 path（放量/缩量一眼可辨）。 */
export function volumeMAPath(
  volume: number[] | undefined,
  i0: number,
  i1: number,
  xOf: (i: number) => number,
  yVol: (v: number) => number,
): string {
  if (!volume) return ''
  const pts: string[] = []
  for (let i = i0; i <= i1; i++) {
    if (i < 20 || !Number.isFinite(volume[i])) continue
    let s = 0
    for (let j = i - 19; j <= i; j++) s += Number(volume[j]) || 0
    const mv = s / 20
    if (!Number.isFinite(mv) || mv <= 0) continue
    pts.push(`${pts.length === 0 ? 'M' : 'L'}${xOf(i).toFixed(1)},${yVol(mv).toFixed(1)}`)
  }
  return pts.join(' ')
}
