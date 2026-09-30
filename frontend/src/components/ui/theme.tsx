/**
 * UI 零件 · 主题变量注入
 *
 * 从 `components/ui.tsx` 拆出（铁律 9）。
 * `./ui` 解析到 `ui/index.ts`，故所有使用方 import 路径不变。
 */

/** 使用方可在应用中注入主题色 */
export function ThemeVars({ up, down }: { up: string; down: string }) {
  return <style>{`:root{--qd-up:${up};--qd-down:${down}}`}</style>
}
