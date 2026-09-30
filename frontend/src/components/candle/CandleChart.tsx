/**
 * 蜡烛图（K 线）—— 自绘 SVG 主组件
 * ============================
 * recharts 没有内置蜡烛图，这里手绘以获得完整控制：
 *   · 蜡烛实体 + 上下影线
 *   · 成交量副图（按涨跌着色）
 *   · 均线 / 布林带叠加
 *   · 支撑阻力参考线
 *   · 十字光标 + 悬浮 OHLC 提示
 *   · 可视区间缩放（拖动条 / 滚轮）
 *
 * 结构：类型见 types.ts，纯几何计算见 overlays.ts，展示子块见 parts.tsx
 * （本文件只做状态、交互与编排）。
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { downColor, fmtNum, upColor } from '../../lib/format'
import {
  MIN_BARS,
  buildValueLabels,
  clampRange,
  computeView,
  findExtremes,
  linePath,
  zoomRange,
  PAD_L,
  PAD_R,
  PAD_T,
  PAD_B,
} from './overlays'
import { ChartLegend, ChartTooltip, HoverInfoBar, ZoomBar } from './parts'
import { Candles, Crosshair, ExtremesMarkers, VolumePane } from './svgParts'
import { useWidth } from './useWidth'
import type { CandleChartProps } from './types'

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
}: CandleChartProps) {
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

  const view = useMemo(
    () => computeView(high, low, volume, i0, i1),
    [n, i0, i1, high, low, volume],
  )

  const extremes = useMemo(
    () => findExtremes(high, low, i0, i1),
    [n, i0, i1, high, low],
  )

  const valueLabels = useMemo(
    () => buildValueLabels(span, i0, i1, close, extremes),
    [span, i0, i1, close, extremes],
  )

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
        <ChartTooltip
          hov={hov}
          hovX={hovState.x}
          tipLeft={tipLeft}
          dates={dates}
          open={open}
          high={high}
          low={low}
          close={close}
          volume={volume}
          overlays={overlays}
          hovUp={hovUp}
        />
      )}

      {/* 悬浮信息条 */}
      <HoverInfoBar
        hov={hov}
        n={n}
        span={span}
        changePct={changePct}
        dates={dates}
        open={open}
        high={high}
        low={low}
        close={close}
        volume={volume}
        hovUp={hovUp}
      />

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
          <VolumePane
            volume={volume}
            open={open}
            close={close}
            i0={i0}
            span={span}
            xOf={xOf}
            yVol={yVol}
            bw={bw}
            height={height}
            innerW={innerW}
            volH={volH}
            up={UP}
            down={DOWN}
          />
        )}

        {/* 蜡烛 */}
        <Candles
          open={open}
          high={high}
          low={low}
          close={close}
          i0={i0}
          span={span}
          xOf={xOf}
          yOf={yOf}
          bw={bw}
          up={UP}
          down={DOWN}
        />

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
            d={linePath(ov.data, i0, i1, xOf, yOf)}
            fill="none"
            stroke={ov.color}
            strokeWidth={1.3}
            strokeDasharray={ov.dashed ? '4 3' : undefined}
          />
        ))}

        {/* 区间最高 / 最低点标注 */}
        {extremes && (
          <ExtremesMarkers
            extremes={extremes}
            dates={dates}
            xOf={xOf}
            yOf={yOf}
            hiX={hiX}
            loX={loX}
            hiY={hiY}
            loY={loY}
            hiTextY={hiTextY}
            loTextY={loTextY}
            up={UP}
            down={DOWN}
          />
        )}

        {/* 十字光标 */}
        {hov !== null && (
          <Crosshair hov={hov} close={close} xOf={xOf} yOf={yOf} innerW={innerW} height={height} color={hovC} />
        )}
      </svg>

      {/* 区间缩放 / 平移 */}
      <ZoomBar
        span={span}
        n={n}
        onShift={(dir) => setRange(clampRange(i0 + dir * Math.round(span * 0.25), i1 + dir * Math.round(span * 0.25), n))}
        onRangeInput={(s) => {
          // 保持右端不变地调整可视根数，便于连续缩放
          setRange(clampRange(i1 - s + 1, i1, n))
        }}
        onZoom={(f) => setRange(zoomRange([i0, i1], n, (i0 + i1) / 2, f))}
        onReset={resetView}
      />
      <div className="mt-1 text-[11px] text-slate-400">
        滚轮缩放 · 按住拖拽平移 · 双击重置
      </div>

      {/* 图例 */}
      <ChartLegend overlays={overlays} up={UP} down={DOWN} colorMode={colorMode} />
    </div>
  )
}
