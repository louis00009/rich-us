/**
 * 情报中心 · 共享类型与展示工具（barrel）
 *
 * 原为单文件 `types.ts`（432 行，超 400 软上限）。铁律 9 拆分（2026-09-29）后
 * 改为本目录 + barrel：**所有既有 `from './types'` / `from '../components/intel/types'`
 * 的导入都不需要改动**（`./types` 会解析到本 `index.ts`）。
 *
 * 拆分依据：
 *   - `domain.ts` —— 纯数据形状（接口 / 联合类型），无逻辑；
 *   - `format.ts` —— 无副作用的格式化函数（时间、影响度夹取）；
 *   - `style.ts`  —— 展示样式与筛选选项常量（配色遵循中国习惯：看多红 / 看空绿）。
 *
 * 新增内容请按上述归属放入对应文件，不要把三类混回同一个文件。
 */
export * from './domain'
export * from './format'
export * from './style'
