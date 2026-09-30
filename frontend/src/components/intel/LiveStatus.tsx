/**
 * 监控实时运行状态条（从 MonitorBar.tsx 抽出——加「指定标的/异动阈值」后主文件超组件软上限 400）。
 *
 * 纯展示、无任何状态；`monitorOn && live` 才渲染（老后端 live=null 时不显示）。
 * 正在抓取/分析哪家、进度几分之几、用的哪个模型 —— 后台动静必须可见，
 * 否则「跑了但没数据回来」的观感永远在。/intel/live 只读后端内存 + 两条本地
 * 小查询，3s 轮询零负担。
 */
import { fmtSince, type LiveStatus, type Overview } from './types'

export default function LiveStatus({
  monitorOn,
  live,
  ov,
  defaultModel,
}: {
  monitorOn: boolean
  /** 实时运行状态（/intel/live，父级 3s 轮询）；null = 老后端 */
  live: LiveStatus | null
  ov: Overview | null
  defaultModel: string
}) {
  if (!monitorOn || !live) return null
  return (
    <div
      className={`mb-3 rounded-lg border px-3 py-2 text-xs ${
        live.live.phase === 'scrape' || live.live.phase === 'analyze'
          ? 'border-emerald-200 bg-emerald-50/60'
          : 'border-slate-100 bg-slate-50/60'
      }`}
    >
      <div className="flex flex-wrap items-center gap-2">
        {live.live.phase === 'scrape' || live.live.phase === 'analyze' ? (
          <span className="h-2 w-2 shrink-0 animate-pulse rounded-full bg-emerald-500" />
        ) : (
          <span className="h-2 w-2 shrink-0 rounded-full bg-slate-300" />
        )}
        <b className="shrink-0 text-slate-700">
          {live.live.phase === 'scrape'
            ? '正在抓取'
            : live.live.phase === 'analyze'
              ? '正在 AI 分析'
              : live.live.phase === 'skipped'
                ? '本轮跳过'
                : '监控空闲'}
        </b>
        {live.live.total > 0 && (live.live.phase === 'scrape' || live.live.phase === 'analyze') && (
          <span className="num shrink-0 font-semibold text-emerald-700">
            {live.live.progress}/{live.live.total} 家
          </span>
        )}
        <span className="min-w-0 flex-1 truncate text-slate-500" title={live.live.note}>
          {live.live.note || (live.live.ts ? `上轮动作 ${fmtSince(live.live.ts)}` : '等待首轮调度…')}
        </span>
        <span className="shrink-0 text-slate-400" title="监控调度使用设置页默认模型">
          模型 {defaultModel || '默认'}
        </span>
        <span className="shrink-0 text-slate-400">周期 {live.interval_minutes} 分钟</span>
        {(ov?.settings.pinned_symbols?.length ?? 0) > 0 && (
          <span
            className="shrink-0 font-medium text-emerald-600"
            title="「指定标的」已同步为重点标的：监控每轮优先抓取（≤4 家），再补 3 家到期轮转"
          >
            重点 {ov?.settings.pinned_symbols?.join('、')}
          </span>
        )}
        <span
          className="shrink-0 text-slate-400"
          title={`观察标的盘中涨跌幅达到 ±${ov?.settings.surge_pct ?? 3}% 时，自动记录「股价异动」事件并触发 AI 归因分析`}
        >
          异动阈值 ±{ov?.settings.surge_pct ?? 3}%
        </span>
      </div>
      {(live.live.phase === 'scrape' || live.live.phase === 'analyze') && live.live.total > 0 && (
        <div className="mt-1.5 h-1.5 w-full overflow-hidden rounded-full bg-slate-200">
          <div
            className="h-full rounded-full bg-emerald-500 transition-all duration-500"
            style={{ width: `${Math.max(4, Math.round((live.live.progress / Math.max(1, live.live.total)) * 100))}%` }}
          />
        </div>
      )}
    </div>
  )
}
