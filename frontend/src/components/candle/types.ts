// 蜡烛图共享类型

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

export interface CandleChartProps {
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
