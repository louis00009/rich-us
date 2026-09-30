/**
 * 美股榜单的列定义 + 每个指标的「是什么 / 怎么看」说明文案。
 *
 * 抽成数据而不是散在 JSX 里：列顺序、默认可见性、宽度、说明文案都只在这里定义，
 * 表格组件只负责渲染 —— 加一个指标不用碰任何组件逻辑。
 *
 * ⚠️ 拆成 `rankingColumns/` 目录后，`./rankingColumns` 会自动解析到本文件，
 * 所有既有 import 一行都不用改（铁律 9 的零改动拆分）。
 */
export * from './types'
import type { RankingColumn } from './types'
import { BASE_COLUMNS } from './base'
import { QUOTE_COLUMNS } from './quote'
import { TECHNICAL_COLUMNS } from './technical'

/** ⚠️ 顺序即列顺序：base → quote → technical，改动会直接改变表格列序。 */
export const RANKING_COLUMNS: RankingColumn[] = [
  ...BASE_COLUMNS,
  ...QUOTE_COLUMNS,
  ...TECHNICAL_COLUMNS,
]

export const COLUMN_MAP: Record<string, RankingColumn> = Object.fromEntries(
  RANKING_COLUMNS.map((c) => [c.key, c]),
)

export const DEFAULT_VISIBLE: string[] = RANKING_COLUMNS.filter((c) => c.defaultOn).map((c) => c.key)
