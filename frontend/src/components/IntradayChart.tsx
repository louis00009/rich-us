/**
 * 当日分时走势图（自绘 SVG）
 * ============================
 * · 价格线（深色）+ 累计均价线（黄）
 * · 昨收基准虚线 + 右侧标签
 * · 相对昨收的涨跌分域填充（红涨绿跌，中国习惯）
 * · 成交量副图
 * · 悬停：竖线 + 顶部信息条（时间/价/均价/量/涨跌%）+ 右侧价格气泡
 */
import { useEffect, useMemo, useRef, useState } from 'react'
import { downColor, fmtCompact, fmtNum, upColor, upClass, downClass } from '../lib/format'

export interface IntraPoint {
  t: string
  price: number
  avg: number | null
  vol: number
}

interface Props {
  points: IntraPoint[]
  prevClose: number
  height?: number
  colorMode?: string
}

const PAD_L = 8
const PAD_R = 62
const PAD_T = 10
const PAD_B = 22

function useWidth<T extends HTMLElement>() {
  const ref = useRef<T | null>(null)
  const [w, setW] = useState(900)
  useEffect(() => {
    const el = ref.current
    if (!el) return
    const ro = new ResizeObserver(() => setW(el.clientWidth || 900))
    ro.observe(el)
    setW(el.clientWidth || 900)
    return () => ro.disconnect()
  }, [])
  return [ref, w] as const
}

export default function IntradayChart({ points, prevClose, height = 380, colorMode = 'cn' }: Props) {
  const [wrapRef, width] = useWidth<HTMLDivElement>()
  const [hover, setHover] = useState<number | null>(null)
  const n = points.length

  const volH = Math.round(height * 0.18)
  const priceH = height - volH - 8
  const innerW = Math.max(80, width - PAD_L - PAD_R)

  const geom = useMemo(() => {
    if (!n || !Number.isFinite(prevClose) || prevClose <= 0) return null
    const prices = points.map((p) => p.price).filter(Number.isFinite)
    const avgs = points.map((p) => p.avg).filter((v): v is number => v !== null && Number.isFinite(v))
    let lo = Math.min(...prices, ...avgs, prevClose)
    let hi = Math.max(...prices, ...avgs, prevClose)
    if (!Number.isFinite(lo) || !Number.isFinite(hi) || hi <= lo) return null
    const pad = (hi - lo) * 0.08
    lo -= pad
    hi += pad
    const volMax = Math.max(...points.map((p) => p.vol).filter(Number.isFinite), 1)
    const priceH_ = priceH - PAD_T
    return { lo, hi, volMax, priceH_ }
  }, [points, prevClose, n, priceH])

  // ⚠️ hooks 必须在 early return 之前（React #300 铁律）
  const svgRef = useRef<SVGSVGElement | null>(null)
  useEffect(() => setHover(null), [n])

  // 最高/最低点索引（分时图标注用）
  const hiIdx = useMemo(() => {
    let mi = -1
    let mv = -Infinity
    for (let i = 0; i < n; i++) {
      const v = points[i].price
      if (Number.isFinite(v) && v > mv) {
        mv = v
        mi = i
      }
    }
    return mi
  }, [points, n])
  const loIdx = useMemo(() => {
    let mi = -1
    let mv = Infinity
    for (let i = 0; i < n; i++) {
      const v = points[i].price
      if (Number.isFinite(v) && v < mv) {
        mv = v
        mi = i
      }
    }
    return mi
  }, [points, n])

  // 相对昨收的分域填充：按符号切段（穿越点线性插值），每段闭合到昨收基线。
  // geom 为 null（空数据）时返回 []，保证 hook 顺序稳定。
  const areas = useMemo(() => {
    if (!n || !geom || !Number.isFinite(prevClose) || prevClose <= 0) return []
    const { lo: _lo, hi: _hi } = geom
    const _xOf = (i: number) => PAD_L + (i + 0.5) * (innerW / n)
    const _yOf = (p: number) => PAD_T + ((geom.hi - p) / (geom.hi - geom.lo)) * (priceH - PAD_T)
    const _baseY = _yOf(prevClose)
    const out: { d: string; up: boolean }[] = []
    let seg: { x: number; y: number }[] = []
    let sign = 0
    const flush = () => {
      if (seg.length > 1) {
        const d =
          `M${seg[0].x.toFixed(1)},${_baseY.toFixed(1)} ` +
          seg.map((s) => `L${s.x.toFixed(1)},${s.y.toFixed(1)}`).join(' ') +
          ` L${seg[seg.length - 1].x.toFixed(1)},${_baseY.toFixed(1)} Z`
        out.push({ d, up: sign > 0 })
      }
      seg = []
    }
    for (let i = 0; i < n; i++) {
      const v = points[i].price
      if (!Number.isFinite(v)) continue
      const s = v >= prevClose ? 1 : -1
      if (sign === 0) sign = s
      if (s !== sign) {
        const pv = points[i - 1]?.price
        if (Number.isFinite(pv) && pv !== v) {
          const xr = (prevClose - (pv as number)) / (v - (pv as number))
          const xc = _xOf(i - 1) + (_xOf(i) - _xOf(i - 1)) * xr
          seg.push({ x: xc, y: _baseY })
        }
        flush()
        sign = s
      }
      seg.push({ x: _xOf(i), y: _yOf(v) })
    }
    flush()
    return out
  }, [points, prevClose, n, innerW, geom, priceH])

  if (!n || !geom) {
    return <div className="py-16 text-center text-sm text-slate-400">当日暂无分时数据（非交易时段或数据源未覆盖）</div>
  }

  const bw = innerW / n
  const xOf = (i: number) => PAD_L + (i + 0.5) * bw
  const yOf = (p: number) => PAD_T + ((geom.hi - p) / (geom.hi - geom.lo)) * geom.priceH_
  const yVol = (v: number) => height - PAD_B - (v / geom.volMax) * (volH - 6)
  const UP = upColor()
  const DOWN = downColor()
  const baseY = yOf(prevClose)

  const linePath = (pick: (p: IntraPoint) => number | null) => {
    const pts: string[] = []
    for (let i = 0; i < n; i++) {
      const v = pick(points[i])
      if (v === null || v === undefined || !Number.isFinite(v)) continue
      pts.push(`${pts.length === 0 ? 'M' : 'L'}${xOf(i).toFixed(1)},${yOf(v).toFixed(1)}`)
    }
    return pts.join(' ')
  }

  // 相对昨收的分域填充已在 early return 前用 useMemo 计算（areas）

  const hov = hover !== null && hover >= 0 && hover < n ? hover : null
  const hovPoint = hov !== null ? points[hov] : null
  const lastPrice = points[n - 1]?.price ?? 0
  const chgPct = prevClose ? ((lastPrice / prevClose - 1) * 100) : 0

  const onMove = (e: React.MouseEvent<SVGSVGElement>) => {
    const rect = e.currentTarget.getBoundingClientRect()
    const x = e.clientX - rect.left
    setHover(Math.max(0, Math.min(n - 1, Math.round((x - PAD_L) / bw - 0.5))))
  }

  const gridLines = 4
  const grids = Array.from({ length: gridLines + 1 }, (_, k) => {
    const p = geom.lo + ((geom.hi - geom.lo) * k) / gridLines
    return { p, y: yOf(p) }
  })

  return (
    <div ref={wrapRef} className="relative w-full">
      {/* 顶部信息条 */}
      <div className="mb-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs">
        {hovPoint ? (
          <>
            <span className="num font-semibold text-slate-700">{hovPoint.t}</span>
            <span className="num text-slate-500">价 <b className="text-slate-800">{fmtNum(hovPoint.price, 2)}</b></span>
            <span className="num text-slate-500">均价 <b className="text-amber-600">{fmtNum(hovPoint.avg, 2)}</b></span>
            <span className="num text-slate-500">量 <b className="text-slate-600">{fmtCompact(hovPoint.vol)}</b></span>
            <span className={`num ${hovPoint.price >= prevClose ? upClass() : downClass()}`}>
              较昨收 {hovPoint.price >= prevClose ? '+' : ''}
              {prevClose ? ((hovPoint.price / prevClose - 1) * 100).toFixed(2) : '—'}%
            </span>
          </>
        ) : (
          <>
            <span className="text-slate-400">
              分时 · 最新 <b className="text-slate-800 num">{fmtNum(lastPrice, 2)}</b>
            </span>
            <span className={`num text-sm font-semibold ${chgPct >= 0 ? upClass() : downClass()}`}>
              {chgPct >= 0 ? '+' : ''}
              {chgPct.toFixed(2)}%
            </span>
            <span className="text-slate-400 num">昨收 {fmtNum(prevClose, 2)}</span>
            {hiIdx >= 0 && (
              <span className={`num ${upClass()}`}>
                最高 {fmtNum(points[hiIdx].price, 2)}
                <span className="text-slate-300"> ({points[hiIdx].t})</span>
              </span>
            )}
            {loIdx >= 0 && (
              <span className={`num ${downClass()}`}>
                最低 {fmtNum(points[loIdx].price, 2)}
                <span className="text-slate-300"> ({points[loIdx].t})</span>
              </span>
            )}
            <span className="text-slate-300">｜ 悬停查看分钟明细</span>
          </>
        )}
      </div>

      <svg
        ref={svgRef}
        width="100%"
        height={height}
        onMouseMove={onMove}
        onMouseLeave={() => setHover(null)}
        style={{ display: 'block', cursor: 'crosshair' }}
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

        {/* 昨收基准虚线 */}
        <line x1={PAD_L} y1={baseY} x2={PAD_L + innerW} y2={baseY} stroke="#94a3b8" strokeWidth={1} strokeDasharray="4 3" />
        <text x={PAD_L + innerW + 6} y={baseY + 3.5} fontSize={9} fill="#64748b" className="num">
          {fmtNum(prevClose, 2)}
        </text>

        {/* X 轴时间标签（首/中/尾） */}
        {[0, Math.floor(n / 2), n - 1].map((i, k) => (
          <text key={k} x={xOf(i)} y={height - 6} fontSize={10} fill="#94a3b8" textAnchor="middle" className="num">
            {points[i]?.t}
          </text>
        ))}

        {/* 成交量副图 */}
        {points.map((p, i) => {
          if (!Number.isFinite(p.vol) || p.vol <= 0) return null
          const up = p.price >= prevClose
          return (
            <rect
              key={i}
              x={xOf(i) - Math.max(0.6, bw * 0.36)}
              y={yVol(p.vol)}
              width={Math.max(1.2, bw * 0.72)}
              height={Math.max(1, height - PAD_B - yVol(p.vol))}
              fill={up ? UP : DOWN}
              opacity={0.45}
            />
          )
        })}

        {/* 涨跌分域填充 */}
        {areas.map((a, k) => (
          <path key={k} d={a.d} fill={a.up ? UP : DOWN} opacity={0.10} />
        ))}

        {/* 价格线 + 均价线 */}
        <path d={linePath((p) => p.price)} fill="none" stroke="#334155" strokeWidth={1.4} />
        <path d={linePath((p) => p.avg)} fill="none" stroke="#f59e0b" strokeWidth={1.2} />

        {/* 最高点 / 最低点标注 */}
        {hiIdx >= 0 && (
          <g>
            <circle cx={xOf(hiIdx)} cy={yOf(points[hiIdx].price)} r={3.2} fill={UP} stroke="#fff" strokeWidth={1} />
            <text
              x={Math.min(xOf(hiIdx), PAD_L + innerW - 70)}
              y={Math.max(yOf(points[hiIdx].price) - 8, 12)}
              fontSize={10}
              fill={UP}
              textAnchor="middle"
              className="num"
            >
              ▲最高 {fmtNum(points[hiIdx].price, 2)} · {points[hiIdx].t}
            </text>
          </g>
        )}
        {loIdx >= 0 && loIdx !== hiIdx && (
          <g>
            <circle cx={xOf(loIdx)} cy={yOf(points[loIdx].price)} r={3.2} fill={DOWN} stroke="#fff" strokeWidth={1} />
            <text
              x={Math.min(xOf(loIdx), PAD_L + innerW - 70)}
              y={Math.min(yOf(points[loIdx].price) + 14, height - PAD_B - 6)}
              fontSize={10}
              fill={DOWN}
              textAnchor="middle"
              className="num"
            >
              ▼最低 {fmtNum(points[loIdx].price, 2)} · {points[loIdx].t}
            </text>
          </g>
        )}

        {/* 开盘价标记（首点） */}
        {n > 1 && (
          <g>
            <circle cx={xOf(0)} cy={yOf(points[0].price)} r={2.5} fill="#94a3b8" stroke="#fff" strokeWidth={1} />
            <text x={xOf(0) + 6} y={yOf(points[0].price) - 6} fontSize={9} fill="#94a3b8" className="num">
              开 {fmtNum(points[0].price, 2)}
            </text>
          </g>
        )}

        {/* 十字线 + 右侧价格气泡 */}
        {hov !== null && hovPoint && (
          <>
            <line x1={xOf(hov)} y1={PAD_T} x2={xOf(hov)} y2={height - PAD_B} stroke="#94a3b8" strokeWidth={1} strokeDasharray="3 3" />
            <line x1={PAD_L} y1={yOf(hovPoint.price)} x2={PAD_L + innerW} y2={yOf(hovPoint.price)} stroke="#94a3b8" strokeWidth={1} strokeDasharray="3 3" />
            <rect x={PAD_L + innerW + 2} y={yOf(hovPoint.price) - 8} width={56} height={16} rx={3} fill={hovPoint.price >= prevClose ? UP : DOWN} />
            <text x={PAD_L + innerW + 6} y={yOf(hovPoint.price) + 3.5} fontSize={10} fill="#fff" className="num">
              {fmtNum(hovPoint.price, 2)}
            </text>
          </>
        )}

        {/* 最新价圆点 */}
        <circle cx={xOf(n - 1)} cy={yOf(lastPrice)} r={2.5} fill={lastPrice >= prevClose ? UP : DOWN} stroke="#fff" strokeWidth={1} />
      </svg>

      <div className="mt-1 flex flex-wrap gap-3 text-[11px] text-slate-400">
        <span className="flex items-center gap-1.5">
          <span className="inline-block h-0.5 w-4 rounded bg-slate-600" /> 价格
        </span>
        <span className="flex items-center gap-1.5">
          <span className="inline-block h-0.5 w-4 rounded bg-amber-500" /> 均价
        </span>
        <span className="flex items-center gap-1.5">
          <span className="inline-block h-2 w-2 rounded-sm" style={{ background: UP }} /> 高于昨收
        </span>
        <span className="flex items-center gap-1.5">
          <span className="inline-block h-2 w-2 rounded-sm" style={{ background: DOWN }} /> 低于昨收
        </span>
        <span>配色遵循{colorMode === 'cn' ? '中国习惯（红涨绿跌）' : '欧美习惯（绿涨红跌）'}</span>
      </div>
    </div>
  )
}
