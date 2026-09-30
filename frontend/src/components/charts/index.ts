/**
 * 图表组件（基于 recharts）
 * 配色：涨红跌绿（中国习惯），可在设置中切换。
 *
 * ⚠️ 拆成 `components/charts/` 目录后，`./charts` 与 `../components/charts`
 * 都会解析到本文件，4 个使用方一行都不用改（铁律 9 的零改动拆分）。
 */
export * from './equity'
export * from './price'
export * from './monthly'
export * from './score'
export * from './portfolio'
