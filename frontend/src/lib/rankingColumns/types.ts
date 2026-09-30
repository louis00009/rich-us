/**
 * 榜单列的列定义类型。
 *
 * 从 `lib/rankingColumns.ts` 拆出（铁律 9）。
 */

export interface MetricTipText {
  title: string
  what: string
  how: string
  warn?: string
}

export interface RankingColumn {
  key: string
  label: string
  align: 'left' | 'right'
  /** 列宽（px，用于 colgroup）。窄屏靠外层横向滚动。 */
  width: number
  sortable?: boolean
  /** 默认是否显示（其余可在「列」菜单里打开） */
  defaultOn?: boolean
  tip: MetricTipText
}
