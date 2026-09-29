/**
 * 关注列表（收藏）全局同步总线。
 *
 * 背景：关注数据只存在后端一张表（/watchlist），但前端有四处独立渲染：
 * Dashboard 顶部的 WatchBar、行情页顶部的 QuickPicks、行情页底部「我的收藏」、
 * 榜单页的 watched 列状态。各自只有 60s 降级轮询，任何一处增删后其余三处
 * 要么等 1 分钟要么不刷新 → 用户看到「收藏和关注没打通」。
 *
 * 用法：任何成功写入关注列表的代码调 notifyWatchlistChanged()；
 * 关心该列表的组件在 mount 时 onWatchlistChanged(load) 订阅，返回卸载函数。
 */
const EVENT = 'qd-watchlist-changed'

export function notifyWatchlistChanged(): void {
  window.dispatchEvent(new CustomEvent(EVENT))
}

export function onWatchlistChanged(cb: () => void): () => void {
  window.addEventListener(EVENT, cb)
  return () => window.removeEventListener(EVENT, cb)
}
