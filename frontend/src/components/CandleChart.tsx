/**
 * 蜡烛图（K 线）—— 自绘 SVG
 * ============================
 * recharts 没有内置蜡烛图，这里手绘以获得完整控制：
 *   · 蜡烛实体 + 上下影线
 *   · 成交量副图（按涨跌着色）
 *   · 均线 / 布林带叠加
 *   · 支撑阻力参考线
 *   · 十字光标 + 悬浮 OHLC 提示
 *   · 可视区间缩放（拖动条 / 滚轮）
 */
import { Fragment, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { downColor, fmtCompact, fmtDate, fmtNum, upColor, upClass, downClass } from '../lib/format'

export interface CandleOverlay {
  name: string
  data: (number | null)[]
  color: string
  dashed?: boolean
}

export interface CandleLevel {
  value: number
  label: string
  color?: string
}

interface Props {
  dates: string[]
  open: number[]
  high: number[]
  low: number[]
  close: number[]
  volume?: number[]
  overlays?: CandleOverlay[]
  levels?: CandleLevel[]
  height?: number
  showVolume?: boolean
  colorMode?: string
}

const PAD_L = 8
const PAD_R = 62
const PAD_T = 10
const PAD_B = 22

const MIN_BARS = 20

/** 把可视区间夹到 [0, n-1] 内，并保证至少 MIN_BARS 根。 */
function clampRange(sIn: number, eIn: number, n: number): [number, number] {
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
function zoomRange(
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

function useWidth<T extends HTMLElement>() {
  // P2 修复：旧实现 effect 只在挂载时跑一次（deps=[]），若挂载时数据为空、
  // 包裹 div 尚未渲染（early-return 分支不挂 ref），observer 永远不会挂上 ——
  // 图表按硬编码 900px 绘制，滚轮缩放无反应且恢复不了。
  // 改用 callback ref：节点每次真正挂载都会触发 setEl → effect 重跑 → 重新 observe。
  const [el, setEl] = useState<T | null>(null)
  const [w, setW] = useState(900)
  useEffect(() => {
    if (!el) return
    const ro = new ResizeObserver(() => setW(el.clientWidth || 900))
    ro.observe(el)
    setW(el.clientWidth || 900)
    return () => ro.disconnect()
  }, [el])
  const ref = useCallback((node: T | null) => setEl(node), [])
  return [ref, w] as const
}

export default function CandleChart({
  dates,
  open,
  high,
  low,
  close,
  volume,
  overlays = [],
  levels = [],
  height = 420,
  showVolume = true,
  colorMode = 'cn',
}: Props) {
  const [wrapRef, width] = useWidth<HTMLDivElement>()
  const n = dates.length
  const [range, setRange] = useState<[number, number] | null>(null)  // [startIdx, endIdx]
  // 合并 hover 双 state：mousemove 高频路径每次只触发一次渲染
  const [hovState, setHovState] = useState<{ i: number; x: number } | null>(null)
  const dragRef = useRef<{ x: number; i0: number; i1: number; moved: boolean } | null>(null)

  // 数据变化时重置可视区间（默认最近 180 根）
  useEffect(() => {
    const end = Math.max(0, n - 1)
    const start = Math.max(0, n - 180)
    setRange([start, end])
    setHovState(null)
    dragRef.current = null
  }, [n, dates[0]])

  const [i0, i1] = range ?? [0, n - 1]
  const span = Math.max(1, i1 - i0 + 1)

  const view = useMemo(() => {
    if (!n) return null
    const hi = Math.max(...high.slice(i0, i1 + 1).filter(Number.isFinite))
    const lo = Math.min(...low.slice(i0, i1 + 1).filter(Number.isFinite))
    if (!Number.isFinite(hi) || !Number.isFinite(lo) || hi <= lo) return null
    const pad = (hi - lo) * 0.06
    const volMax = volume && volume.length ? Math.max(...volume.slice(i0, i1 + 1).filter(Number.isFinite), 1) : 1
    return { hi: hi + pad, lo: lo - pad, volMax }
  }, [n, i0, i1, high, low, volume])

  // 可视区间内的最高点 / 最低点（图上直接标注数值与日期）
  const extremes = useMemo(() => {
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
  }, [n, i0, i1, high, low])

  // 收盘价数值标注：可视区间 K 线 ≤ 40 根时逐根标（抽稀至 ≤32），普通黑色小字
  const valueLabels = useMemo(() => {
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
  }, [span, i0, i1, close, extremes])

  const volH = showVolume ? Math.round(height * 0.22) : 0
  const priceH = height - volH - (showVolume ? 8 : 0)
  const innerW = Math.max(80, width - PAD_L - PAD_R)
  const bw = innerW / span

  // --- 滚轮缩放 ---
  // React 的 onWheel 在根节点上是被动监听，preventDefault() 无效（页面会跟着滚）。
  // 因此用原生监听 + { passive: false }。闭包通过 ref 读取最新状态，避免反复解绑。
  //
  // ⚠️ 这 4 个 hook 必须位于下方 `if (!n || !view) return ...` 之前：
  // 曾因放在 early return 之后，切换标的瞬间（数据为空 → 0 个 hook，
  // 数据到达 → 4 个 hook）触发 React #300 "Rendered fewer hooks than
  // expected"，整个页面白屏。
  const svgRef = useRef<SVGSVGElement | null>(null)
  const wheelState = useRef({ i0, i1, bw, n, range })
  useEffect(() => {
    wheelState.current = { i0, i1, bw, n, range }
  }, [i0, i1, bw, n, range])

  useEffect(() => {
    const el = svgRef.current
    if (!el) return
    const handler = (e: WheelEvent) => {
      const { i0: a, i1: b, bw: step, n: total, range: cur } = wheelState.current
      if (!total || step <= 0) return
      e.preventDefault()
      const rect = el.getBoundingClientRect()
      const x = e.clientX - rect.left
      const idx = Math.max(a, Math.min(b, a + Math.round((x - PAD_L) / step - 0.5)))
      const base: [number, number] = cur ?? [Math.max(0, total - 180), total - 1]
      setRange(zoomRange(base, total, idx, e.deltaY > 0 ? 1.15 : 1 / 1.15))
    }
    el.addEventListener('wheel', handler, { passive: false })
    return () => el.removeEventListener('wheel', handler)
  }, [])

  if (!n || !view) {
    return <div className="py-16 text-center text-sm text-slate-400">暂无 K 线数据</div>
  }

  const xOf = (i: number) => PAD_L + (i - i0 + 0.5) * bw
  const yOf = (p: number) => PAD_T + (view.hi - p) / (view.hi - view.lo) * (priceH - PAD_T)
  const yVol = (v: number) => height - PAD_B - (v / view.volMax) * (volH - 6)
  const UP = upColor()
  const DOWN = downColor()

  const gridLines = 5
  const grids = Array.from({ length: gridLines + 1 }, (_, k) => {
    const p = view.lo + ((view.hi - view.lo) * k) / gridLines
    return { p, y: yOf(p) }
  })

  const tickStep = Math.max(1, Math.ceil(span / 8))
  const xTicks: number[] = []
  for (let i = i0; i <= i1; i += tickStep) xTicks.push(i)

  const path = (data: (number | null)[]) => {
    const pts: string[] = []
    for (let i = i0; i <= i1; i++) {
      const v = data[i]
      if (v === null || v === undefined || !Number.isFinite(v)) continue
      pts.push(`${pts.length === 0 ? 'M' : 'L'}${xOf(i).toFixed(1)},${yOf(v).toFixed(1)}`)
    }
    return pts.join(' ')
  }

  const onMove = (e: React.MouseEvent<SVGSVGElement>) => {
    const d = dragRef.current
    if (d && Math.abs(e.clientX - d.x) >= 2) {
      // 拖拽平移：按像素位移换算成 bar 数
      d.moved = true
      setHovState(null)
      const bars = Math.round((e.clientX - d.x) / Math.max(bw, 1e-6))
      setRange(clampRange(d.i0 - bars, d.i1 - bars, n))
      return
    }
    const rect = e.currentTarget.getBoundingClientRect()
    const x = e.clientX - rect.left
    // setHoverPos(x) — 合并到下方单次 setState
    // 光标 → bar 索引：bar k 的中心在 PAD_L + (k + 0.5) * bw，
    // 所以 k = (x - PAD_L) / bw - 0.5，必须**整体 round**。
    // ⚠️ 旧实现是 Math.round((x-PAD_L)/bw) + i0 - 0.5，hover 永远是
    // x.5 的小数索引 → open[hov] 等全部 undefined → 界面数值全是 "—"。
    const idx = i0 + Math.round((x - PAD_L) / bw - 0.5)
    const clamped = Math.max(i0, Math.min(i1, idx))
    setHovState({ i: clamped, x })
  }

  const onDown = (e: React.MouseEvent<SVGSVGElement>) => {
    dragRef.current = { x: e.clientX, i0, i1, moved: false }
  }
  const onUp = () => {
    dragRef.current = null
  }

  const resetView = () => {
    setRange(clampRange(n - 180, n - 1, n))
    setHovState(null)
  }

  const hov = hovState !== null && Number.isInteger(hovState.i) && hovState.i >= 0 && hovState.i < n ? hovState.i : null
  const hovUp = hov !== null && close[hov] >= open[hov]
  const hovC = hov !== null ? (hovUp ? UP : DOWN) : '#64748b'

  // 浮动 tooltip 定位：光标右侧优先，靠右边界时翻到左侧（w-44 = 176px）
  const TIP_W = 176
  const tipLeft =
    hovState === null ? 0 : hovState.x + 14 + TIP_W > width ? Math.max(4, hovState.x - 14 - TIP_W) : hovState.x + 14

  // 最高 / 最低点标签位置：左右夹在绘图区内，上下越界时翻到另一侧
  const labelX = (i: number) => Math.max(PAD_L + 38, Math.min(PAD_L + innerW - 38, xOf(i)))
  const hiX = extremes ? labelX(extremes.hiIdx) : 0
  const loX = extremes ? labelX(extremes.loIdx) : 0
  const hiY = extremes ? yOf(extremes.hiVal) : 0
  const loY = extremes ? yOf(extremes.loVal) : 0
  const hiTextY = extremes ? (hiY - 26 >= PAD_T ? hiY - 24 : hiY + 16) : 0
  const loTextY = extremes ? (loY + 26 <= height - PAD_B ? loY + 18 : loY - 24) : 0

  const changePct = n >= 2 && close[i0] ? ((close[i1] / close[i0] - 1) * 100) : 0

  return (
    <div ref={wrapRef} className="relative w-full">
      {/* 浮动 tooltip：跟随光标，显示日期 + OHLC + 量 + 叠加线数值 */}
      {hov !== null && hovState !== null && (
        <div
          className="pointer-events-none absolute z-20 w-44 rounded-lg border border-slate-200 bg-white/95 px-3 py-2 text-[11px] shadow-pop"
          style={{ top: PAD_T + 4, left: tipLeft }}
        >
          <div className="mb-1 border-b border-dashed border-slate-100 pb-1 font-semibold text-slate-700 num">
            {fmtDate(dates[hov])}
          </div>
          <div className="grid grid-cols-2 gap-x-2 gap-y-0.5 num">
            <span className="text-slate-400">开</span>
            <b className={hovUp ? upClass() : downClass()}>{fmtNum(open[hov], 2)}</b>
            <span className="text-slate-400">高</span>
            <b className="text-slate-800">{fmtNum(high[hov], 2)}</b>
            <span className="text-slate-400">低</span>
            <b className="text-slate-800">{fmtNum(low[hov], 2)}</b>
            <span className="text-slate-400">收</span>
            <b className={hovUp ? upClass() : downClass()}>{fmtNum(close[hov], 2)}</b>
            {volume && Number.isFinite(volume[hov]) && (
              <>
                <span className="text-slate-400">量</span>
                <b className="text-slate-600">{fmtCompact(volume[hov])}</b>
              </>
            )}
            {overlays.map((o) => {
              const v = o.data[hov]
              if (v === null || v === undefined || !Number.isFinite(v)) return null
              return (
                <Fragment key={o.name}>
                  <span className="flex items-center gap-1 text-slate-400">
                    <span className="inline-block h-0.5 w-2.5 rounded" style={{ background: o.color }} />
                    {o.name}
                  </span>
                  <b className="text-slate-800">{fmtNum(v, 2)}</b>
                </Fragment>
              )
            })}
          </div>
        </div>
      )}

      {/* 悬浮信息条 */}
      <div className="mb-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs">
        {hov !== null ? (
          <>
            <span className="num text-slate-400">{fmtDate(dates[hov])}</span>
            <span className="num text-slate-600">
              开 <b className={hovUp ? upClass() : downClass()}>{fmtNum(open[hov], 2)}</b>
            </span>
            <span className="num text-slate-600">
              高 <b className="text-slate-800">{fmtNum(high[hov], 2)}</b>
            </span>
            <span className="num text-slate-600">
              低 <b className="text-slate-800">{fmtNum(low[hov], 2)}</b>
            </span>
            <span className="num text-slate-600">
              收 <b className={hovUp ? upClass() : downClass()}>{fmtNum(close[hov], 2)}</b>
            </span>
            {volume && <span className="num text-slate-500">量 {fmtCompact(volume[hov])}</span>}
          </>
        ) : (
          <span className="text-slate-400">
            共 {n} 根 K 线 ｜ 可视 {span} 根 ｜ 区间涨跌{' '}
            <b className={changePct >= 0 ? upClass() : downClass()}>
              {changePct >= 0 ? '+' : ''}
              {changePct.toFixed(2)}%
            </b>
          </span>
        )}
      </div>

      <svg
        ref={svgRef}
        width="100%"
        height={height}
        onMouseMove={onMove}
        onMouseLeave={() => {
          setHovState(null)
          dragRef.current = null
        }}
        onMouseDown={onDown}
        onMouseUp={onUp}
        onDoubleClick={resetView}
        style={{ display: 'block', userSelect: 'none', cursor: 'crosshair', touchAction: 'pan-y' }}
      >
        {/* 网格 */}
        {grids.map((g, k) => (
          <g key={k}>
            <line x1={PAD_L} y1={g.y} x2={PAD_L + innerW} y2={g.y} stroke="#eef2f7" strokeWidth={1} />
            <text x={PAD_L + innerW + 6} y={g.y + 3.5} fontSize={10} fill="#94a3b8" className="num">
              {fmtNum(g.p, g.p > 100 ? 0 : 2)}
            </text>
          </g>
        ))}

        {/* X 轴时间（悬停中的日期加亮加粗） */}
        {xTicks.map((i) => (
          <text
            key={i}
            x={xOf(i)}
            y={height - 6}
            fontSize={10}
            fill={i === hov ? '#334155' : '#94a3b8'}
            fontWeight={i === hov ? 700 : 400}
            textAnchor="middle"
          >
            {String(dates[i]).slice(0, 10)}
          </text>
        ))}

        {/* 参考线（支撑/阻力） */}
        {levels
          .filter((l) => Number.isFinite(l.value) && l.value <= view.hi && l.value >= view.lo)
          .map((l, k) => (
            <g key={`lv${k}`}>
              <line
                x1={PAD_L}
                y1={yOf(l.value)}
                x2={PAD_L + innerW}
                y2={yOf(l.value)}
                stroke={l.color || '#cbd5e1'}
                strokeWidth={1}
                strokeDasharray="4 3"
              />
              <text x={PAD_L + 4} y={yOf(l.value) - 3} fontSize={9} fill={l.color || '#94a3b8'}>
                {l.label} {fmtNum(l.value, 2)}
              </text>
            </g>
          ))}

        {/* 成交量副图 */}
        {showVolume && volume && (
          <>
            <text x={PAD_L + innerW + 6} y={height - PAD_B - volH / 2} fontSize={9} fill="#cbd5e1">
              量
            </text>
            {Array.from({ length: span }, (_, k) => {
              const i = i0 + k
              const v = volume[i]
              if (!Number.isFinite(v)) return null
              const up = close[i] >= open[i]
              const c = up ? UP : DOWN
              const y = yVol(v)
              return (
                <rect
                  key={i}
                  x={xOf(i) - Math.max(1, bw * 0.32)}
                  y={y}
                  width={Math.max(1, bw * 0.64)}
                  height={Math.max(1, height - PAD_B - y)}
                  fill={c}
                  opacity={0.42}
                />
              )
            })}
            {/* 20 日均量线（放量/缩量一眼可辨） */}
            <path
              d={(() => {
                const pts: string[] = []
                for (let i = i0; i <= i1; i++) {
                  if (i < 20 || !volume || !Number.isFinite(volume[i])) continue
                  let s = 0
                  for (let j = i - 19; j <= i; j++) s += Number(volume[j]) || 0
                  const mv = s / 20
                  if (!Number.isFinite(mv) || mv <= 0) continue
                  pts.push(`${pts.length === 0 ? 'M' : 'L'}${xOf(i).toFixed(1)},${yVol(mv).toFixed(1)}`)
                }
                return pts.join(' ')
              })()}
              fill="none"
              stroke="#f59e0b"
              strokeWidth={1}
              strokeDasharray="2 2"
              opacity={0.9}
            />
          </>
        )}

        {/* 蜡烛 */}
        {Array.from({ length: span }, (_, k) => {
          const i = i0 + k
          const o = open[i]
          const c = close[i]
          const h = high[i]
          const l = low[i]
          if (![o, c, h, l].every(Number.isFinite)) return null
          const up = c >= o
          const col = up ? UP : DOWN
          const yO = yOf(o)
          const yC = yOf(c)
          const top = Math.min(yO, yC)
          const bodyH = Math.max(1, Math.abs(yC - yO))
          const w = Math.max(1.2, bw * 0.66)
          return (
            <g key={i}>
              <line x1={xOf(i)} y1={yOf(h)} x2={xOf(i)} y2={yOf(l)} stroke={col} strokeWidth={1} />
              <rect x={xOf(i) - w / 2} y={top} width={w} height={bodyH} fill={col} stroke={col} strokeWidth={0.5} />
            </g>
          )
        })}

        {/* 收盘价数值标注：可视 K 线 ≤ 40 根时逐根显示（黑色小字，上下交错防重叠） */}
        {valueLabels.map(({ i, v, above }) => {
          const yC = yOf(close[i])
          return (
            <text
              key={`vl-${i}`}
              x={xOf(i)}
              y={above ? yC - 10 : yC + 16}
              textAnchor="middle"
              fontSize={9}
              fill="#334155"
              className="num"
            >
              {fmtNum(v, v > 100 ? 1 : 2)}
            </text>
          )
        })}

        {/* 叠加线 */}
        {overlays.map((ov) => (
          <path
            key={ov.name}
            d={path(ov.data)}
            fill="none"
            stroke={ov.color}
            strokeWidth={1.3}
            strokeDasharray={ov.dashed ? '4 3' : undefined}
          />
        ))}

        {/* 区间最高 / 最低点标注：圆点 + 数值 + 日期（白描边保证可读性） */}
        {extremes && (
          <g>
            <circle cx={xOf(extremes.hiIdx)} cy={hiY} r={3} fill={UP} stroke="#fff" strokeWidth={1} />
            <text
              x={hiX} y={hiTextY} fontSize={10.5} fontWeight={700} fill={UP} textAnchor="middle"
              stroke="#fff" strokeWidth={3} paintOrder="stroke" className="num"
            >
              最高 {fmtNum(extremes.hiVal, 2)}
            </text>
            <text
              x={hiX} y={hiTextY + 11} fontSize={9} fill="#64748b" textAnchor="middle"
              stroke="#fff" strokeWidth={3} paintOrder="stroke" className="num"
            >
              {fmtDate(dates[extremes.hiIdx])}
            </text>
          </g>
        )}
        {extremes && extremes.loIdx !== extremes.hiIdx && (
          <g>
            <circle cx={xOf(extremes.loIdx)} cy={loY} r={3} fill={DOWN} stroke="#fff" strokeWidth={1} />
            <text
              x={loX} y={loTextY} fontSize={10.5} fontWeight={700} fill={DOWN} textAnchor="middle"
              stroke="#fff" strokeWidth={3} paintOrder="stroke" className="num"
            >
              最低 {fmtNum(extremes.loVal, 2)}
            </text>
            <text
              x={loX} y={loTextY + 11} fontSize={9} fill="#64748b" textAnchor="middle"
              stroke="#fff" strokeWidth={3} paintOrder="stroke" className="num"
            >
              {fmtDate(dates[extremes.loIdx])}
            </text>
          </g>
        )}

        {/* 十字光标 */}
        {hov !== null && (
          <>
            <line
              x1={xOf(hov)}
              y1={PAD_T}
              x2={xOf(hov)}
              y2={height - PAD_B}
              stroke="#94a3b8"
              strokeWidth={1}
              strokeDasharray="3 3"
            />
            <line
              x1={PAD_L}
              y1={yOf(close[hov])}
              x2={PAD_L + innerW}
              y2={yOf(close[hov])}
              stroke="#94a3b8"
              strokeWidth={1}
              strokeDasharray="3 3"
            />
            <rect x={PAD_L + innerW + 2} y={yOf(close[hov]) - 8} width={56} height={16} rx={3} fill={hovC} />
            <text x={PAD_L + innerW + 6} y={yOf(close[hov]) + 3.5} fontSize={10} fill="#fff" className="num">
              {fmtNum(close[hov], 2)}
            </text>
          </>
        )}
      </svg>

      {/* 区间缩放 / 平移 */}
      <div className="mt-3 flex items-center gap-2">
        <span className="shrink-0 text-[11px] text-slate-400">可视区间</span>
        <button
          type="button"
          onClick={() => setRange(clampRange(i0 - Math.round(span * 0.25), i1 - Math.round(span * 0.25), n))}
          className="h-6 w-6 shrink-0 rounded border border-slate-200 text-xs text-slate-500 hover:bg-slate-50"
          title="向左平移（更早）"
        >
          ‹
        </button>
        <input
          type="range"
          min={MIN_BARS}
          max={n}
          value={span}
          onChange={(e) => {
            const s = parseInt(e.target.value, 10)
            // 保持右端不变地调整可视根数，便于连续缩放
            setRange(clampRange(i1 - s + 1, i1, n))
          }}
          className="h-1 flex-1 cursor-pointer appearance-none rounded bg-slate-200 accent-brand-600"
        />
        <button
          type="button"
          onClick={() => setRange(clampRange(i0 + Math.round(span * 0.25), i1 + Math.round(span * 0.25), n))}
          className="h-6 w-6 shrink-0 rounded border border-slate-200 text-xs text-slate-500 hover:bg-slate-50"
          title="向右平移（更近）"
        >
          ›
        </button>
        <button
          type="button"
          onClick={() => setRange(zoomRange([i0, i1], n, (i0 + i1) / 2, 1 / 1.4))}
          className="h-6 shrink-0 rounded border border-slate-200 px-1.5 text-[11px] text-slate-500 hover:bg-slate-50"
          title="放大"
        >
          放大
        </button>
        <button
          type="button"
          onClick={() => setRange(zoomRange([i0, i1], n, (i0 + i1) / 2, 1.4))}
          className="h-6 shrink-0 rounded border border-slate-200 px-1.5 text-[11px] text-slate-500 hover:bg-slate-50"
          title="缩小"
        >
          缩小
        </button>
        <button
          type="button"
          onClick={resetView}
          className="h-6 shrink-0 rounded border border-slate-200 px-1.5 text-[11px] text-slate-500 hover:bg-slate-50"
          title="重置视图（双击图表亦可）"
        >
          重置
        </button>
        <span className="num shrink-0 text-[11px] text-slate-500">
          {span} / {n} 根
        </span>
      </div>
      <div className="mt-1 text-[11px] text-slate-400">
        滚轮缩放 · 按住拖拽平移 · 双击重置
      </div>

      {overlays.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-3">
          {overlays.map((o) => (
            <span key={o.name} className="flex items-center gap-1.5 text-[11px] text-slate-500">
              <span className="inline-block h-0.5 w-4 rounded" style={{ background: o.color }} />
              {o.name}
            </span>
          ))}
        </div>
      )}
      <div className="mt-1 flex flex-wrap gap-3 text-[11px] text-slate-400">
        <span className="flex items-center gap-1.5">
          <span className="inline-block h-2 w-2 rounded-sm" style={{ background: UP }} />
          涨
        </span>
        <span className="flex items-center gap-1.5">
          <span className="inline-block h-2 w-2 rounded-sm" style={{ background: DOWN }} />
          跌
        </span>
        <span>配色遵循{colorMode === 'cn' ? '中国习惯（红涨绿跌）' : '欧美习惯（绿涨红跌）'}</span>
      </div>
    </div>
  )
}
