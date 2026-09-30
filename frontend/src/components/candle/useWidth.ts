// 容器宽度 hook：ResizeObserver + callback ref
import { useCallback, useEffect, useState } from 'react'

export function useWidth<T extends HTMLElement>() {
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
