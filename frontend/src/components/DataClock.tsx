/**
 * 全局数据时钟（T-105）：顶栏显示实时链路状态。
 * 绿 = WebSocket 推送中且 15s 内有新行情；黄 = 链路在但 90s 无更新；红 = 断线。
 */
import { useEffect, useState } from 'react'
import { lastRtTick, onRtState, rtSubscribe } from '../lib/realtime'

export default function DataClock() {
  const [online, setOnline] = useState(false)
  const [, force] = useState(0)
  const [last, setLast] = useState<number>(lastRtTick())

  // 常驻订阅：保证全局链路在线（Layout 挂载即生效），同时作为时钟数据源
  useEffect(
    () =>
      rtSubscribe(['quotes:SPY'], () => {
        setLast(lastRtTick())
      }),
    [],
  )
  useEffect(() => onRtState(setOnline), [])
  useEffect(() => {
    const t = setInterval(() => {
      setLast(lastRtTick())
      force((x) => x + 1)
    }, 1000)
    return () => clearInterval(t)
  }, [])

  const age = last ? (Date.now() - last) / 1000 : Infinity
  const color = !online || age > 90 ? 'bg-rose-500' : age > 15 ? 'bg-amber-500' : 'bg-emerald-500'
  const label = !online ? '已断线' : age > 90 ? '数据停滞' : '实时中'
  const time = Number.isFinite(age) && last ? new Date(last).toLocaleTimeString('zh-CN', { hour12: false }) : '—'

  return (
    <span
      className="hidden items-center gap-1.5 rounded-lg border border-slate-200 px-2 py-1 text-[11px] text-slate-500 sm:inline-flex"
      title={`实时推送链路：${label} ｜ 最近行情 ${time} ｜ 断线时页面自动降级为轮询`}
    >
      <span className={`inline-block h-1.5 w-1.5 animate-pulse rounded-full ${color}`} />
      {label} · {time}
    </span>
  )
}
